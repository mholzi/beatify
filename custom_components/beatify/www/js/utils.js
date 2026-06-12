/**
 * Beatify Shared Utilities Module
 *
 * Provides common functionality used across multiple pages:
 * - i18n helpers (waitForI18n, t)
 * - View management (showView)
 * - Localization helpers (getLocalizedSongField)
 * - WebSocket utilities (createWebSocket)
 * - HTML escaping (escapeHtml)
 *
 * This module consolidates duplicated code from admin.js, player.js, and dashboard.js.
 */
window.BeatifyUtils = (function() {
    'use strict';

    // ==========================================================================
    // Debug Logging (#1280)
    // ==========================================================================

    /**
     * Whether debug logging is enabled. Off by default so the production console
     * stays clean; opt in via either:
     *   - localStorage: localStorage.setItem('beatify_debug', '1')
     *   - URL query param: ?debug=1 (or ?BeatifyDebug=1)
     * The query param, when present, is persisted to localStorage so it survives
     * reloads/navigation. Evaluated once at module load.
     */
    var debugEnabled = (function() {
        try {
            var params = new URLSearchParams(window.location.search);
            var qp = params.get('debug') || params.get('BeatifyDebug');
            if (qp !== null) {
                var on = qp !== '0' && qp.toLowerCase() !== 'false';
                window.localStorage.setItem('beatify_debug', on ? '1' : '0');
                return on;
            }
            return window.localStorage.getItem('beatify_debug') === '1';
        } catch (e) {
            return false;
        }
    })();

    /**
     * Gated console.log replacement. No-op unless debug logging is enabled.
     * Use for diagnostic noise; keep console.error for real errors (#1280).
     */
    function debug() {
        if (debugEnabled) {
            console.log.apply(console, arguments);
        }
    }

    // ==========================================================================
    // i18n Helpers
    // ==========================================================================

    /**
     * Wait for BeatifyI18n to be available (handles fallback script race condition)
     * @param {number} timeout - Max wait time in ms (default: 3000)
     * @param {number} interval - Check interval in ms (default: 50)
     * @returns {Promise<boolean>} - true if available, false if timeout
     */
    async function waitForI18n(timeout, interval) {
        timeout = timeout || 3000;
        interval = interval || 50;
        var start = Date.now();
        while (typeof BeatifyI18n === 'undefined') {
            if (Date.now() - start > timeout) {
                return false;
            }
            await new Promise(function(resolve) { setTimeout(resolve, interval); });
        }
        return true;
    }

    /**
     * Translation function with smart fallback handling
     * Supports both interpolation params and explicit fallback strings
     * @param {string} key - Translation key (e.g., 'lobby.playerJoined')
     * @param {Object|string} paramsOrFallback - Interpolation params object OR fallback string
     * @returns {string} - Translated text or fallback
     */
    function t(key, paramsOrFallback) {
        var params = null;
        var explicitFallback = null;

        // Determine if second arg is params object or fallback string
        if (typeof paramsOrFallback === 'string') {
            explicitFallback = paramsOrFallback;
        } else if (paramsOrFallback && typeof paramsOrFallback === 'object') {
            params = paramsOrFallback;
        }

        // Use BeatifyI18n.t if available
        if (typeof BeatifyI18n !== 'undefined' && BeatifyI18n.t) {
            var result = BeatifyI18n.t(key, params);
            // If result equals key, i18n didn't find it - use explicit fallback if provided
            if (result === key && explicitFallback) {
                return explicitFallback;
            }
            return result || explicitFallback || key;
        }

        // If explicit fallback provided, use it
        if (explicitFallback) {
            return explicitFallback;
        }

        // Auto-generate fallback: extract last part of key and make it readable
        // e.g., 'lobby.playerJoined' -> 'Player Joined'
        var fallback = key.split('.').pop()
            .replace(/([A-Z])/g, ' $1')
            .replace(/^./, function(str) { return str.toUpperCase(); })
            .trim();

        // Handle params substitution if provided
        if (params) {
            Object.keys(params).forEach(function(param) {
                fallback = fallback.replace(new RegExp('\\{' + param + '\\}', 'g'), params[param]);
            });
        }
        return fallback;
    }

    // ==========================================================================
    // View Management
    // ==========================================================================

    /**
     * Show a specific view and hide all others
     * @param {Array<HTMLElement>} views - Array of view elements to manage
     * @param {string} viewId - ID of view to show
     */
    function showView(views, viewId) {
        views.forEach(function(v) {
            if (v) {
                v.classList.add('hidden');
            }
        });
        var view = document.getElementById(viewId);
        if (view) {
            view.classList.remove('hidden');
        }
    }

    // ==========================================================================
    // Localization Helpers
    // ==========================================================================

    /**
     * Get localized content field from song with English fallback (Story 16.1, 16.3)
     * @param {Object} song - Song object
     * @param {string} field - Base field name ('fun_fact' or 'awards')
     * @returns {string|Array|null} Localized content or English fallback
     */
    function getLocalizedSongField(song, field) {
        if (!song) return null;
        // Guard: fall back to English if i18n unavailable
        var lang = (typeof BeatifyI18n !== 'undefined') ? BeatifyI18n.getLanguage() : 'en';
        // Try localized field first (for non-English)
        if (lang && lang !== 'en') {
            var localizedKey = field + '_' + lang;
            if (song[localizedKey]) {
                return song[localizedKey];
            }
        }
        // Fallback to base field (English)
        return song[field] || null;
    }

    // ==========================================================================
    // HTML Utilities
    // ==========================================================================

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    function escapeHtml(text) {
        if (text === null || text === undefined) {
            return '';
        }
        var div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    // ==========================================================================
    // WebSocket Utilities
    // ==========================================================================

    /**
     * Create a WebSocket connection with auto-reconnect and exponential backoff
     * @param {Object} options - Configuration options
     * @param {string} options.path - WebSocket path (default: '/beatify/ws')
     * @param {number} options.maxReconnectAttempts - Max reconnect attempts (default: 20)
     * @param {number} options.maxReconnectDelay - Max delay in ms (default: 30000)
     * @param {string} options.logPrefix - Prefix for console logs (default: 'WebSocket')
     * @param {Function} options.onOpen - Called when connection opens
     * @param {Function} options.onMessage - Called with parsed JSON message
     * @param {Function} options.onClose - Called when connection closes (after max retries)
     * @param {Function} options.onError - Called on error
     * @returns {Object} WebSocket manager with send(), close(), and getSocket() methods
     */
    function createWebSocket(options) {
        options = options || {};
        var path = options.path || '/beatify/ws';
        var maxReconnectAttempts = options.maxReconnectAttempts || 20;
        var maxReconnectDelay = options.maxReconnectDelay || 30000;
        var logPrefix = options.logPrefix || 'WebSocket';

        var ws = null;
        var reconnectAttempts = 0;
        var intentionallyClosed = false;

        function getReconnectDelay() {
            return Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay);
        }

        function connect() {
            var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            var wsUrl = wsProtocol + '//' + window.location.host + path;

            ws = new WebSocket(wsUrl);

            ws.onopen = function() {
                debug('[' + logPrefix + '] Connected');
                reconnectAttempts = 0;
                if (options.onOpen) {
                    options.onOpen(ws);
                }
            };

            ws.onmessage = function(event) {
                try {
                    var data = JSON.parse(event.data);
                    if (options.onMessage) {
                        options.onMessage(data, ws);
                    }
                } catch (e) {
                    console.error('[' + logPrefix + '] Failed to parse message:', e);
                }
            };

            ws.onclose = function() {
                debug('[' + logPrefix + '] Disconnected');
                if (intentionallyClosed) {
                    return;
                }
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    var delay = getReconnectDelay();
                    debug('[' + logPrefix + '] Reconnecting in ' + delay + 'ms (attempt ' + reconnectAttempts + ')');
                    setTimeout(connect, delay);
                } else {
                    debug('[' + logPrefix + '] Max reconnect attempts reached');
                    if (options.onClose) {
                        options.onClose();
                    }
                }
            };

            ws.onerror = function(err) {
                console.error('[' + logPrefix + '] Error:', err);
                if (options.onError) {
                    options.onError(err);
                }
            };
        }

        // Start connection
        connect();

        // Return manager object
        return {
            send: function(data) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(typeof data === 'string' ? data : JSON.stringify(data));
                    return true;
                }
                return false;
            },
            close: function() {
                intentionallyClosed = true;
                if (ws) {
                    ws.close();
                }
            },
            getSocket: function() {
                return ws;
            },
            isConnected: function() {
                return ws && ws.readyState === WebSocket.OPEN;
            },
            resetReconnect: function() {
                reconnectAttempts = 0;
            }
        };
    }

    // ==========================================================================
    // URL Utilities
    // ==========================================================================

    /**
     * Get a query parameter from the URL
     * @param {string} name - Parameter name
     * @returns {string|null} Parameter value or null
     */
    function getQueryParam(name) {
        var urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(name);
    }

    /**
     * Build WebSocket URL for current host
     * @param {string} path - Path (default: '/beatify/ws')
     * @returns {string} Full WebSocket URL
     */
    function buildWebSocketUrl(path) {
        path = path || '/beatify/ws';
        var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return wsProtocol + '//' + window.location.host + path;
    }

    /**
     * Capped exponential-backoff reconnect delay (#1398).
     *
     * Pure helper so the spectator dashboard (a passive always-on TV display)
     * can retry FOREVER with a bounded delay instead of giving up. The previous
     * dashboard logic stopped after 20 attempts (~8 min), so a router reboot or
     * HA restart longer than that bricked the screen until someone physically
     * woke the tab (visibilitychange) — which never fires on an always-on TV.
     *
     * Delay = base * 2^attempt, capped at maxDelay. `attempt` is the 1-based
     * retry count; it is NOT clamped, so very large values still return maxDelay
     * (no overflow / NaN) — the caller may keep incrementing indefinitely.
     *
     * @param {number} attempt - 1-based reconnect attempt number
     * @param {Object} [opts] - { baseDelay=1000, maxDelay=30000 }
     * @returns {number} delay in ms, in [baseDelay, maxDelay]
     */
    function reconnectBackoffDelay(attempt, opts) {
        opts = opts || {};
        var baseDelay = opts.baseDelay || 1000;
        var maxDelay = opts.maxDelay || 30000;
        var n = (typeof attempt === 'number' && attempt > 0) ? attempt : 1;
        // Math.pow can overflow to Infinity for huge n; Math.min collapses that
        // to maxDelay, so the result is always a finite number in range.
        return Math.min(baseDelay * Math.pow(2, n - 1), maxDelay);
    }

    /**
     * Title & Artist verdict label for a resolved near-miss (#1180).
     * @param {boolean} accepted - whether the close call was accepted
     * @param {number} points - points awarded (only shown when accepted)
     * @returns {string} "✓ +N" when accepted, "✗" when rejected
     */
    function taVerdictLabel(accepted, points) {
        return accepted ? '✓ +' + (points || 0) : '✗';
    }

    /**
     * Title & Artist live tally split as integer percentages (#1180).
     * Returns {yes, no} summing to 100 when any vote is cast, else {0, 0}.
     * @param {number} yes - 👍 count
     * @param {number} no - 👎 count
     */
    function taTallyPercents(yes, no) {
        yes = yes || 0;
        no = no || 0;
        var total = yes + no;
        if (total <= 0) return { yes: 0, no: 0 };
        var yesPct = Math.round((yes / total) * 100);
        return { yes: yesPct, no: 100 - yesPct };
    }

    // ==========================================================================
    // Public API
    // ==========================================================================

    return {
        // Debug
        debug: debug,

        // i18n
        waitForI18n: waitForI18n,
        t: t,

        // Title & Artist helpers
        taVerdictLabel: taVerdictLabel,
        taTallyPercents: taTallyPercents,

        // View management
        showView: showView,

        // Localization
        getLocalizedSongField: getLocalizedSongField,

        // HTML utilities
        escapeHtml: escapeHtml,

        // WebSocket
        createWebSocket: createWebSocket,
        buildWebSocketUrl: buildWebSocketUrl,
        reconnectBackoffDelay: reconnectBackoffDelay,

        // URL utilities
        getQueryParam: getQueryParam
    };
})();
