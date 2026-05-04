/**
 * Playlist Requests Module (Story 44.1)
 * Handles submission and tracking of custom playlist requests
 * Uses Home Assistant backend storage for persistence across devices
 */
(function() {
    'use strict';

    const STORAGE_KEY = 'beatify_playlist_requests';
    const API_URL = 'https://beatify-api.mholzi.workers.dev';
    const BACKEND_API = '/beatify/api/playlist-requests';
    const GITHUB_API = 'https://api.github.com/repos/mholzi/beatify/issues';
    const POLL_INTERVAL_MS = 60 * 60 * 1000; // 1 hour

    // In-memory cache for current session
    let _cache = null;

    // Debug: Log origin on load
    console.log('[PlaylistRequests] Module loaded. Origin:', window.location.origin);

    /**
     * Load requests from HA backend (with localStorage fallback)
     * @returns {Object} Storage object with requests array and last_poll timestamp
     */
    function loadRequests() {
        // Return cache if available (sync path for immediate UI)
        if (_cache) {
            console.log('[PlaylistRequests] Returning cached data:', _cache.requests?.length || 0, 'requests');
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
        try {
            console.log('[PlaylistRequests] Loading from backend API...');
            const response = await fetch(BACKEND_API);
            if (response.ok) {
                const data = await response.json();
                console.log('[PlaylistRequests] Loaded from backend:', data.requests?.length || 0, 'requests');
                _cache = data;
                return data;
            }
            console.warn('[PlaylistRequests] Backend returned:', response.status);
        } catch (e) {
            console.error('[PlaylistRequests] Failed to load from backend:', e);
        }
        // Fallback to empty
        _cache = { requests: [], last_poll: null };
        return _cache;
    }

    /**
     * Save requests to HA backend
     * @param {Object} data - Storage object with requests array
     */
    async function saveRequests(data) {
        // Update cache immediately
        _cache = data;

        try {
            console.log('[PlaylistRequests] Saving to backend:', data.requests?.length || 0, 'requests');
            const response = await fetch(BACKEND_API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (response.ok) {
                console.log('[PlaylistRequests] Saved to backend successfully');
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

        const data = await response.json();

        if (!data.success) {
            // Worker returns {success:false, error:"<code>", message:"<text>"}.
            // Surface the code so the UI can map it to a localized hint (#835).
            const err = new Error(data.message || 'Failed to submit request');
            err.code = data.error || null;
            throw err;
        }

        // Store the request in backend
        const store = await loadRequestsAsync();

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
     * Poll GitHub API for status updates on pending requests
     * @returns {Promise<boolean>} True if any statuses changed
     */
    async function pollStatuses() {
        const store = await loadRequestsAsync();

        // Check rate limiting
        if (store.last_poll) {
            const lastPoll = new Date(store.last_poll).getTime();
            if (Date.now() - lastPoll < POLL_INTERVAL_MS) {
                console.log('Skipping poll - rate limited');
                return false;
            }
        }

        const pendingRequests = store.requests.filter(r => r.status === 'pending' || r.status === 'ready');
        if (pendingRequests.length === 0) {
            return false;
        }

        let changed = false;
        const currentVersion = window.BEATIFY_VERSION;

        for (const request of pendingRequests) {
            try {
                const response = await fetch(`${GITHUB_API}/${request.issue_number}`, {
                    headers: { 'Accept': 'application/vnd.github.v3+json' }
                });

                if (!response.ok) continue;

                const issue = await response.json();
                const labels = issue.labels.map(l => l.name);

                request.last_checked = new Date().toISOString();

                if (issue.state === 'closed') {
                    if (labels.includes('wont-fix')) {
                        // Declined
                        if (request.status !== 'declined') {
                            request.status = 'declined';
                            request.decline_reason = 'Request was declined';
                            changed = true;
                        }
                    } else if (labels.includes('playlist-ready')) {
                        // Find version label (vX.X.X format)
                        const versionLabel = labels.find(l => /^v\d+\.\d+\.\d+/.test(l));
                        if (versionLabel) {
                            request.release_version = versionLabel.replace(/^v/, '');

                            // Check if user has this version installed
                            if (currentVersion && compareVersions(currentVersion, request.release_version) >= 0) {
                                if (request.status !== 'installed') {
                                    request.status = 'installed';
                                    changed = true;
                                }
                            } else if (request.status !== 'ready') {
                                request.status = 'ready';
                                changed = true;
                            }
                        }
                    }
                }
            } catch (e) {
                console.error(`Failed to poll issue #${request.issue_number}:`, e);
            }
        }

        store.last_poll = new Date().toISOString();
        await saveRequests(store);

        return changed;
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
        pollStatuses,
        getRequestsForDisplay,
        getRequestsForDisplayAsync,
        compareVersions,
        isValidSpotifyUrl,
        clearRequests
    };
})();
