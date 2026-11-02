/**
 * Playlist Requests Module (Story 44.1)
 * Handles submission and tracking of custom playlist requests
 * Uses Home Assistant backend storage for persistence across devices
 */
(function() {
    'use strict';

    // Gated debug logging (#1280) — no-op unless BeatifyDebug flag is set.
    const debug = (window.BeatifyUtils && window.BeatifyUtils.debug) || function() {};

    const STORAGE_KEY = 'beatify_playlist_requests';
    const API_URL = 'https://beatify-api.mholzi.workers.dev';
    const BACKEND_API = '/beatify/api/playlist-requests';

    // In-memory cache for current session
    let _cache = null;

    // Debug: Log origin on load
    debug('[PlaylistRequests] Module loaded. Origin:', window.location.origin);

    /**
     * Load requests from HA backend (with localStorage fallback)
     * @returns {Object} Storage object with requests array and last_poll timestamp
     */
    function loadRequests() {
        // Return cache if available (sync path for immediate UI)
        if (_cache) {
            debug('[PlaylistRequests] Returning cached data:', _cache.requests?.length || 0, 'requests');
            return _cache;
        }
        // Return empty for sync calls - async load will populate cache
        return { requests: [], last_poll: null };
    }

    /**
     * Load requests from backend API (async)
     * @returns {Promise<Object>} Storage object with requests array
     */
    async function loadRequestsAsync() {
        // #3390: a failed load is an error, not an empty list. It used to write
        // {requests: []} into the cache, so "could not load" became "No
        // requests yet" and the good list from the last load was gone. The
        // cache now only ever holds an answer the backend actually gave.
        let response;
        try {
            debug('[PlaylistRequests] Loading from backend API...');
            response = await fetch(BACKEND_API);
        } catch (e) {
            console.error('[PlaylistRequests] Failed to load from backend:', e);
            throw new Error('Could not load playlist requests', { cause: e });
        }
        if (!response.ok) {
            console.warn('[PlaylistRequests] Backend returned:', response.status);
            throw new Error('Could not load playlist requests (HTTP ' + response.status + ')');
        }
        const data = await response.json();
        if (!data || !Array.isArray(data.requests)) {
            throw new Error('Could not load playlist requests (bad answer)');
        }
        debug('[PlaylistRequests] Loaded from backend:', data.requests.length, 'requests');
        _cache = data;
        return data;
    }

    /**
     * Save requests to HA backend
     * @param {Object} data - Storage object with requests array
     */
    async function saveRequests(data) {
        // Update cache immediately
        _cache = data;

        try {
            debug('[PlaylistRequests] Saving to backend:', data.requests?.length || 0, 'requests');
            const response = await fetch(BACKEND_API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (response.ok) {
                debug('[PlaylistRequests] Saved to backend successfully');
                return true;
            }
            console.error('[PlaylistRequests] Backend save failed:', response.status);
        } catch (e) {
            console.error('[PlaylistRequests] Failed to save to backend:', e);
        }
        return false;
    }

    /**
     * Submit a playlist request to the API
     * @param {string} spotifyUrl - Spotify playlist URL
     * @returns {Promise<Object>} API response
     */
    async function submitRequest(spotifyUrl) {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ spotify_url: spotifyUrl })
        });

        // #3390: a 5xx page is not JSON. Reading it blindly surfaced as
        // "Unexpected token <" under the URL field.
        let data;
        try {
            data = await response.json();
        } catch (e) {
            const err = new Error('Failed to submit request (HTTP ' + response.status + ')', { cause: e });
            // errors.GITHUB_ERROR is the "backend unavailable, try again" text.
            err.code = 'github_error';
            throw err;
        }

        if (!data || !data.success) {
            // Worker returns {success:false, error:"<code>", message:"<text>"}.
            // Surface the code so the UI can map it to a localized hint (#835).
            const err = new Error(data.message || 'Failed to submit request');
            err.code = data.error || null;
            throw err;
        }

        // Store the request in backend.
        // #3390: if the list does not load, do not save. Saving would write a
        // list holding only this request over every earlier one. The request
        // itself went through above, so the maintainers have it; only this
        // device's list misses it.
        let store;
        try {
            store = await loadRequestsAsync();
        } catch (e) {
            console.warn('[PlaylistRequests] Request sent, but the list did not load; not saving:', e);
            return data;
        }

        // Check if we already have this request stored
        const existingIndex = store.requests.findIndex(r => r.issue_number === data.issue_number);

        if (existingIndex === -1) {
            store.requests.push({
                issue_number: data.issue_number,
                spotify_url: spotifyUrl,
                playlist_name: data.playlist_name,
                thumbnail_url: data.thumbnail_url || null,
                requested_at: new Date().toISOString(),
                status: 'pending',
                release_version: null,
                decline_reason: null,
                last_checked: null
            });
            await saveRequests(store);
        }

        return data;
    }

    /**
     * Compare two semver version strings
     * @param {string} a - First version (e.g., "2.2.0")
     * @param {string} b - Second version (e.g., "2.3.0")
     * @returns {number} -1 if a < b, 0 if a == b, 1 if a > b
     */
    function compareVersions(a, b) {
        if (!a || !b) return 0;

        // Remove 'v' prefix and any beta/alpha suffix for comparison
        const cleanVersion = (v) => v.replace(/^v/, '').split('-')[0];

        const partsA = cleanVersion(a).split('.').map(Number);
        const partsB = cleanVersion(b).split('.').map(Number);

        for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
            const numA = partsA[i] || 0;
            const numB = partsB[i] || 0;
            if (numA < numB) return -1;
            if (numA > numB) return 1;
        }
        return 0;
    }

    /**
     * Get requests formatted for UI display (sync version using cache)
     * @returns {Array} Requests with computed display properties
     */
    function getRequestsForDisplay() {
        const store = loadRequests();
        return formatRequestsForDisplay(store);
    }

    /**
     * Get requests formatted for UI display (async version)
     * @returns {Promise<Array>} Requests with computed display properties
     */
    async function getRequestsForDisplayAsync() {
        const store = await loadRequestsAsync();
        return formatRequestsForDisplay(store);
    }

    /**
     * Format requests for display
     * @param {Object} store - Storage object with requests array
     * @returns {Array} Formatted requests
     */
    function formatRequestsForDisplay(store) {
        const currentVersion = window.BEATIFY_VERSION;

        return store.requests.map(request => {
            const display = { ...request };

            // Compute relative time
            const requestedAt = new Date(request.requested_at);
            const now = new Date();
            const diffMs = now - requestedAt;
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
            const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

            if (diffDays > 0) {
                display.relative_time = diffDays === 1 ? '1 day ago' : `${diffDays} days ago`;
            } else if (diffHours > 0) {
                display.relative_time = diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`;
            } else {
                display.relative_time = 'Just now';
            }

            // Check if update is available for ready status
            if (request.status === 'ready' && request.release_version && currentVersion) {
                display.update_available = compareVersions(currentVersion, request.release_version) < 0;
            }

            return display;
        });
    }

    /**
     * Validate Spotify playlist URL format
     * @param {string} url - URL to validate
     * @returns {boolean} True if valid format
     */
    function isValidSpotifyUrl(url) {
        return /^https:\/\/open\.spotify\.com\/playlist\/[a-zA-Z0-9]+/.test(url);
    }

    /**
     * Clear all stored requests (for testing)
     */
    function clearRequests() {
        localStorage.removeItem(STORAGE_KEY);
    }

    // Expose module globally
    window.PlaylistRequests = {
        loadRequests,
        loadRequestsAsync,
        saveRequests,
        submitRequest,
        getRequestsForDisplay,
        getRequestsForDisplayAsync,
        compareVersions,
        isValidSpotifyUrl,
        clearRequests
    };
})();
