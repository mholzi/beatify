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
        // Escapes the five characters directly rather than routing through a
        // detached div: the div trick leaves the quotes alone, which breaks
        // attribute context. Kept byte-identical to the player-utils.js copy
        // so the two cannot drift. (#2505)
        return String(text)
            .replace(/&/g, '&amp;')   // must come first
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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

    /**
     * Reconnect-timer guard (#1397).
     *
     * Wraps a single pending exponential-backoff reconnect timer so an
     * out-of-band reconnect (e.g. the dashboard's visibilitychange handler)
     * can cancel it before opening its own socket. Without this the backoff
     * timer fires later and opens a SECOND parallel WebSocket — double renders
     * on the TV plus a reconnect storm against the HA server.
     *
     * Usage:
     *   var guard = BeatifyUtils.createReconnectGuard();
     *   // in ws.onclose: guard.schedule(connect, delay)
     *   // at the top of connect(): guard.cancel()
     *
     * `schedule` always cancels any in-flight timer first, so it is safe to
     * call repeatedly; only the most recent pending reconnect ever survives.
     *
     * @returns {{schedule: Function, cancel: Function, isPending: Function}}
     */
    function createReconnectGuard() {
        var timer = null;
        function cancel() {
            if (timer !== null) {
                clearTimeout(timer);
                timer = null;
            }
        }
        function schedule(fn, delay) {
            cancel();
            timer = setTimeout(function() {
                timer = null;
                fn();
            }, delay);
        }
        function isPending() {
            return timer !== null;
        }
        return { schedule: schedule, cancel: cancel, isPending: isPending };
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
     * Build a WebSocket `onclose` reconnect handler (#1662).
     *
     * The player page carried TWO near-identical onclose blocks (session
     * reconnect vs. name-based join) that diverged only in HOW they rescheduled
     * the next attempt. They also each open-coded a bespoke LINEAR backoff while
     * the spectator dashboard used the capped-exponential
     * {@link reconnectBackoffDelay}. This factory captures the shared reconnect
     * contract ONCE — DOM-free and dependency-injected — so the call sites can
     * no longer drift and the behaviour is unit-testable:
     *
     *   1. stop the heartbeat (always),
     *   2. honour a one-shot intentional leave (clear the flag, do NOT reconnect),
     *   3. while a session identity exists AND we are under the attempt cap:
     *      flag reconnecting, bump the 1-based attempt counter, compute the
     *      backoff delay, run the `onReconnecting(attempt, delay)` UI hook and
     *      schedule the caller-supplied reconnect after that delay,
     *   4. once the cap is hit: clear the reconnecting flag and run `onGiveUp()`.
     *
     * Every DOM/socket/timer touch is injected, so the returned handler is pure
     * with respect to this module (see __tests__/player-ws-close.test.js).
     *
     * @param {Object} deps
     * @param {Object} deps.state - shared state object; reads/writes
     *   `intentionalLeave`, `isReconnecting`, `reconnectAttempts`, `playerName`.
     * @param {number} deps.maxAttempts - reconnect attempt cap (inclusive give-up).
     * @param {Function} deps.getDelay - () => next backoff delay in ms.
     * @param {Function} deps.scheduleReconnect - () => void, performs the reconnect.
     * @param {Function} [deps.stopHeartbeat] - teardown run on every close.
     * @param {Function} [deps.onReconnecting] - (attempt, delay) => void UI hook.
     * @param {Function} [deps.onGiveUp] - () => void UI hook at the cap.
     * @param {Function} [deps.setTimeoutFn] - injectable timer (defaults to setTimeout).
     * @returns {Function} a WebSocket onclose handler.
     */
    function createWsCloseHandler(deps) {
        deps = deps || {};
        var state = deps.state;
        var maxAttempts = deps.maxAttempts;
        var getDelay = deps.getDelay;
        var scheduleReconnect = deps.scheduleReconnect;
        var stopHeartbeat = deps.stopHeartbeat || function() {};
        var onReconnecting = deps.onReconnecting || function() {};
        var onGiveUp = deps.onGiveUp || function() {};
        var setTimeoutFn = deps.setTimeoutFn
            || (typeof setTimeout === 'function' ? setTimeout : function() {});

        return function onClose() {
            stopHeartbeat();
            // Deliberate leave/rejoin: consume the one-shot flag and stay closed.
            if (state.intentionalLeave) {
                state.intentionalLeave = false;
                return;
            }
            if (state.playerName && state.reconnectAttempts < maxAttempts) {
                state.isReconnecting = true;
                state.reconnectAttempts++;
                var delay = getDelay();
                onReconnecting(state.reconnectAttempts, delay);
                setTimeoutFn(scheduleReconnect, delay);
            } else if (state.reconnectAttempts >= maxAttempts) {
                state.isReconnecting = false;
                onGiveUp();
            }
        };
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
    // Leaderboard hydration (#1765)
    // ==========================================================================

    /**
     * Re-attach per-player fields to a slim in-round leaderboard.
     *
     * #1765: the server now sends the PLAYING/REVEAL leaderboard as
     * ``{rank, name, rank_change}`` only — score, streak, is_admin, connected,
     * eliminated and eliminated_round are already carried in the same frame's
     * ``players`` array, so they no longer ride along in every leaderboard
     * entry. This joins them back by name on receipt so all downstream render
     * code (standings, TV rows, admin cards, steal modal) is unchanged.
     *
     * Non-destructive: a field already present on an entry wins, so the
     * END-phase final leaderboard (which keeps its full stat block) passes
     * through untouched and this is safe to call in any phase.
     *
     * @param {Array} leaderboard - Leaderboard entries (slim or full).
     * @param {Array} players - Same frame's players array.
     * @returns {Array} Entries with the per-player fields re-attached.
     */
    function hydrateLeaderboard(leaderboard, players) {
        if (!Array.isArray(leaderboard)) return leaderboard;
        var byName = {};
        (players || []).forEach(function(p) {
            if (p && p.name != null) byName[p.name] = p;
        });
        return leaderboard.map(function(entry) {
            var p = entry ? byName[entry.name] : null;
            if (!p) return entry;
            // Object.assign(base, entry): entry wins on overlap, so rank/
            // rank_change (and any full-leaderboard fields) are preserved.
            return Object.assign({
                score: p.score,
                streak: p.streak,
                is_admin: p.is_admin,
                connected: p.connected,
                eliminated: p.eliminated,
                eliminated_round: p.eliminated_round,
                // #2584: who hit this player this round and with what. Already
                // in the players array (#1665) — the TV just never read it.
                sabotaged_by: p.sabotaged_by,
                sabotage_effect: p.sabotage_effect,
                // #2578: sitzt dieses Stechen aus — nicht dasselbe wie eliminated.
                playoff_spectator: p.playoff_spectator
            }, entry);
        });
    }

    // ==========================================================================
    // Lobby brief — the one sentence the lobby reads out (#2647)
    // ==========================================================================

    /**
     * What "normal" is, in one place: the server-side default of every game
     * option the sentence can name.
     *
     * Deliberately NOT a hand-curated "these are the interesting settings"
     * list. A setting is a deviation when, and only when, its value differs
     * from what the server would have used had the host touched nothing —
     * i.e. the default of the matching field on `GameOptions`
     * (`game/config.py`), which is the single list `create_game`, the rematch
     * and the HTTP create-game view all read.
     *
     * `__tests__/lobby-brief-2647.test.js` parses those dataclass defaults out
     * of the Python source and fails when this map drifts, the same way
     * `game-constants-mirror.test.js` guards the numbers in game-constants.js.
     * So a new game option cannot silently change what counts as normal, and
     * nobody has to remember to edit a second list.
     */
    var LOBBY_BRIEF_DEFAULTS = {
        sudden_death_mode: false,
        title_artist_mode: false,
        round_duration: 45,
        closest_wins_mode: false,
        difficulty: 'normal',
        sabotage_enabled: false,
        comeback_token_enabled: false,
        finale_double_enabled: false,
        finale_tiebreaker_enabled: false,
        difficulty_bet_scaling_enabled: false,
        intro_mode_enabled: false,
        rampup_order_enabled: false
    };

    /** How many deviations the sentence may name before it stops being one glance. */
    var LOBBY_BRIEF_MAX_NAMED = 3;

    /**
     * The rank order: most game-changing first.
     *
     * It does two jobs, and both need it to be ONE list. It decides which
     * deviations survive the cap of three — the top of the list is what a
     * player has to know before the first song, the bottom is bookkeeping he
     * can discover in play. And it decides where each clause sits in the
     * sentence: rank 1 is held back to the closing slot (after the dash),
     * because the surprise the issue is about is the one that should land
     * last and loudest. The rest run in rank order in front of it.
     *
     * `yearRound: false` marks the settings that only mean something while the
     * year round is the game — the same suppression the admin's icon row does
     * with `yearRoundActive` (`admin/sections/game-settings.js`). Naming
     * "only the closest guess scores" in a Title & Artist game would describe
     * a rule that is not running.
     */
    var LOBBY_BRIEF_RULES = [
        { field: 'sudden_death_mode', clause: 'suddenDeath' },
        { field: 'title_artist_mode', clause: 'titleArtist' },
        { field: 'round_duration', clause: 'duration' },
        { field: 'closest_wins_mode', clause: 'closestWins', yearRound: true },
        { field: 'difficulty', clause: 'difficulty', yearRound: true },
        { field: 'sabotage_enabled', clause: 'sabotage' },
        { field: 'comeback_token_enabled', clause: 'comeback' },
        { field: 'finale_double_enabled', clause: 'finaleDouble' },
        { field: 'finale_tiebreaker_enabled', clause: 'finaleTiebreaker' },
        { field: 'difficulty_bet_scaling_enabled', clause: 'betScaling', yearRound: true },
        { field: 'intro_mode_enabled', clause: 'intro', yearRound: true },
        { field: 'rampup_order_enabled', clause: 'rampup' }
    ];

    /** Which slot gets which accent. Closing clause = the punchline = pink. */
    var LOBBY_BRIEF_SLOT_CLASS = {
        last: 'lobby-brief-em lobby-brief-em--key',
        a: 'lobby-brief-em lobby-brief-em--alt',
        b: 'lobby-brief-em',
        more: 'lobby-brief-em lobby-brief-em--rest'
    };

    /**
     * Fill `{slot}` placeholders in a locale-owned template.
     *
     * A function replacement, not a string one: a `$` in a translated clause
     * would otherwise be read as a capture reference by String.replace. An
     * unknown placeholder is left standing so a broken template is visible
     * rather than silently swallowing a clause.
     */
    function lobbyBriefFill(template, slots) {
        return String(template).replace(/\{(\w+)\}/g, function(whole, name) {
            return Object.prototype.hasOwnProperty.call(slots, name) ? slots[name] : whole;
        });
    }

    /**
     * The lobby's one sentence, assembled from the game state (#2647).
     *
     * The room used to learn in round 2, at the first skull, that Sudden Death
     * was on: the TV said "10 rounds • Normal" and nothing else, although the
     * server sends every flag in every phase. This builds the sentence both
     * the TV and the guest's phone show, from the same state, in the same
     * words.
     *
     * The sentence is never assembled out of translated words. Each locale
     * owns a whole clause per deviation and a whole sentence shape per number
     * of clauses (`lobby.brief.one` … `lobby.brief.threePlus`), so German
     * compounds, Romance word order and the position of the conjunction stay
     * that locale's business. This function only decides WHICH clauses appear
     * and in what order.
     *
     * @param {Object} data - a LOBBY state payload
     * @param {Function} [translate] - injectable `t` (tests, and only tests)
     * @returns {{text: string, html: string, named: number, hidden: number}|null}
     *   null when there is nothing trustworthy to say — no state, or a round
     *   count the server has not computed yet. The caller hides the line then,
     *   which leaves the lobby looking exactly as it did before this existed.
     */
    function buildLobbyBrief(data, translate) {
        var tr = translate || t;
        if (!data) return null;

        var rounds = Number(data.total_rounds);
        if (!isFinite(rounds) || rounds < 1) return null;
        rounds = Math.round(rounds);

        // #1180: Title & Artist replaces the year round, so the year-only
        // settings describe a rule that is not running this game.
        var yearRound = data.title_artist_mode !== true;

        var found = [];
        LOBBY_BRIEF_RULES.forEach(function(rule) {
            if (rule.yearRound && !yearRound) return;
            var value = data[rule.field];
            if (value === undefined || value === null) return;
            if (value === LOBBY_BRIEF_DEFAULTS[rule.field]) return;

            if (rule.field === 'round_duration') {
                var seconds = Math.round(Number(value));
                if (!isFinite(seconds) || seconds < 1) return;
                if (seconds === LOBBY_BRIEF_DEFAULTS.round_duration) return;
                found.push({ key: 'lobby.brief.dev.duration', params: { n: seconds } });
                return;
            }
            if (rule.field === 'difficulty') {
                if (value !== 'easy' && value !== 'hard') return;
                found.push({
                    key: 'lobby.brief.dev.difficulty' + value.charAt(0).toUpperCase() + value.slice(1),
                    params: null
                });
                return;
            }
            if (value !== true) return;
            found.push({ key: 'lobby.brief.dev.' + rule.clause, params: null });
        });

        var roundsPhrase = tr(rounds === 1 ? 'lobby.brief.roundsOne' : 'lobby.brief.rounds', { n: rounds });
        var slots = { rounds: roundsPhrase };
        var shape;

        if (found.length === 0) {
            shape = 'lobby.brief.standard';
        } else {
            // Rank 1 closes the sentence; ranks 2..3 run in front of it.
            var named = found.slice(0, LOBBY_BRIEF_MAX_NAMED);
            var hidden = found.length - named.length;
            slots.last = tr(named[0].key, named[0].params || undefined);
            if (named[1]) slots.a = tr(named[1].key, named[1].params || undefined);
            if (named[2]) slots.b = tr(named[2].key, named[2].params || undefined);
            if (hidden > 0) {
                slots.more = hidden === 1
                    ? tr('lobby.brief.moreOne', { n: hidden })
                    : tr('lobby.brief.more', { n: hidden });
                shape = 'lobby.brief.threePlus';
            } else {
                shape = ['lobby.brief.one', 'lobby.brief.two', 'lobby.brief.three'][named.length - 1];
            }
        }

        var template = tr(shape);
        // t() hands back the key itself when a locale is missing it. Printing
        // "lobby.brief.three" across the TV would be worse than printing
        // nothing, so treat an un-substituted template as no sentence at all.
        if (!template || template === shape || template.indexOf('{rounds}') === -1) return null;

        var htmlSlots = {};
        var textSlots = {};
        Object.keys(slots).forEach(function(name) {
            var safe = escapeHtml(slots[name]);
            var cls = LOBBY_BRIEF_SLOT_CLASS[name];
            textSlots[name] = slots[name];
            htmlSlots[name] = cls ? '<span class="' + cls + '">' + safe + '</span>' : safe;
        });

        return {
            text: lobbyBriefFill(template, textSlots),
            html: lobbyBriefFill(escapeHtml(template), htmlSlots),
            named: Math.min(found.length, LOBBY_BRIEF_MAX_NAMED),
            hidden: Math.max(0, found.length - LOBBY_BRIEF_MAX_NAMED)
        };
    }

    /**
     * Write the sentence into an element, or hide it when there is none.
     * Shared so the TV and the phone cannot drift in how they handle "no
     * sentence" — the case an old server or an unstarted playlist produces.
     */
    function renderLobbyBrief(el, data, translate) {
        if (!el) return null;
        var brief = buildLobbyBrief(data, translate);
        if (!brief) {
            el.innerHTML = '';
            el.classList.add('hidden');
            return null;
        }
        el.innerHTML = brief.html;
        el.classList.remove('hidden');
        return brief;
    }

    // ==========================================================================
    // Public API
    // ==========================================================================

    return {
        // Debug
        debug: debug,

        // Leaderboard (#1765)
        hydrateLeaderboard: hydrateLeaderboard,

        // i18n
        waitForI18n: waitForI18n,
        t: t,

        // Lobby brief (#2647)
        buildLobbyBrief: buildLobbyBrief,
        renderLobbyBrief: renderLobbyBrief,

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
        createReconnectGuard: createReconnectGuard,
        createWsCloseHandler: createWsCloseHandler,

        // URL utilities
        getQueryParam: getQueryParam
    };
})();
