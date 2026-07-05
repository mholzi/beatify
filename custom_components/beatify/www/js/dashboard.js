/**
 * Beatify Dashboard - Spectator Display (Story 10.4)
 * Read-only observer that connects to WebSocket and displays game state
 */
(function() {
    'use strict';

    // Alias BeatifyUtils for convenience
    var utils = window.BeatifyUtils || {};
    var debug = utils.debug || function() {};

    // View elements
    var loadingView = document.getElementById('dashboard-loading');
    var startingView = document.getElementById('dashboard-starting');  // #1287 cold-start vinyl loader
    var noGameView = document.getElementById('dashboard-no-game');
    var lobbyView = document.getElementById('dashboard-lobby');
    var playingView = document.getElementById('dashboard-playing');
    var revealView = document.getElementById('dashboard-reveal');
    var endView = document.getElementById('dashboard-end');
    var pausedView = document.getElementById('dashboard-paused');

    // All views array for showView helper
    var allViews = [loadingView, startingView, noGameView, lobbyView, playingView, revealView, endView, pausedView];

    // WebSocket connection
    var ws = null;
    var reconnectAttempts = 0;
    // #1398: the dashboard is a passive, read-only always-on TV display. It must
    // reconnect FOREVER (capped backoff), never giving up — a router reboot or
    // HA restart longer than the old ~8 min / 20-attempt cap used to brick the
    // screen until someone physically woke the tab (visibilitychange never fires
    // on an always-on TV). There is intentionally no max-attempt cap any more.
    // #1397: guards the pending exponential-backoff reconnect timer. An
    // out-of-band reconnect (visibilitychange) cancels it before opening its
    // own socket — otherwise the backoff timer fires later and opens a second
    // parallel WebSocket (double renders + reconnect storm). Falls back to a
    // tiny inline shim if utils.js failed to load.
    var reconnectGuard = (utils.createReconnectGuard && utils.createReconnectGuard()) || (function() {
        var t = null;
        return {
            schedule: function(fn, d) { if (t !== null) { clearTimeout(t); } t = setTimeout(function() { t = null; fn(); }, d); },
            cancel: function() { if (t !== null) { clearTimeout(t); t = null; } },
            isPending: function() { return t !== null; }
        };
    })();
    var MAX_RECONNECT_DELAY_MS = 30000;

    // State tracking
    var previousPlayers = [];
    var countdownInterval = null;
    var lastQRCodeUrl = null;
    // Issue #827: dedup key for the full-bleed "OUT" takeover so it only fires
    // once per elimination (re-renders / re-broadcasts of the same REVEAL must
    // not re-trigger it). Format: "<round>:<joined names>".
    var sdLastOutKey = null;
    var sdOutTimer = null;

    // #1705: track the countdown's active deadline so the 1Hz timer is torn
    // down + recreated ONLY when the round's deadline actually changes — not on
    // every state broadcast (a submission/score update re-renders the view but
    // the clock is unchanged, so the running timer must be left ticking).
    var lastCountdownDeadline = null;

    // --- #1705: WS-broadcast render coalescing ------------------------------
    // Mirrors admin's createRenderCoalescer (#1584): the dashboard used to push
    // EVERY `state` broadcast straight into a full re-render (leaderboard
    // innerHTML rebuild + countdown restart). A 20-player round fires ~20
    // broadcasts → O(N^2) DOM re-parses + timer churn on the weakest TV hardware
    // (Chromecast / Fire TV). Coalesce a burst into one paint per animation
    // frame (latest payload wins, final state never dropped) and skip the paint
    // entirely when nothing visible changed. Inlined here because dashboard.js
    // ships as a standalone IIFE (not the admin ES-module bundle) so it can't
    // import admin/util.js.
    function _defaultRenderSchedule(cb) {
        if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(cb);
        return setTimeout(cb, 16);
    }
    function createRenderCoalescer(render, options) {
        var opts = options || {};
        var schedule = typeof opts.schedule === 'function' ? opts.schedule : _defaultRenderSchedule;
        var isEqual = typeof opts.isEqual === 'function' ? opts.isEqual : null;
        var pending = false, hasLatest = false, latest, lastRendered, hasRendered = false;
        function flush() {
            pending = false;
            if (!hasLatest) return;
            var data = latest;
            hasLatest = false; latest = undefined;
            lastRendered = data; hasRendered = true;
            render(data);
        }
        function push(data) {
            // Dirty-check: identical to what's on screen and nothing queued → skip.
            if (isEqual && hasRendered && !hasLatest && isEqual(data, lastRendered)) return;
            latest = data; hasLatest = true;   // coalesce: newest payload wins
            if (!pending) { pending = true; schedule(flush); }
        }
        push.flush = flush;
        push.cancel = function() { pending = false; hasLatest = false; latest = undefined; };
        return push;
    }

    // #1705: dirty-check that strips the volatile countdown-only fields. A
    // broadcast that differs ONLY by a re-stamped `deadline` / `seconds_remaining`
    // / `reveal_started_at` (the values the local 1Hz tickers already animate
    // from the client clock) must NOT force a repaint. Mirrors admin's
    // adminStateEqual (#1659).
    function _stateRenderKey(data) {
        if (!data) return '';
        var clone = {};
        for (var k in data) {
            if (!Object.prototype.hasOwnProperty.call(data, k)) continue;
            if (k === 'deadline' || k === 'seconds_remaining' || k === 'reveal_started_at') continue;
            clone[k] = data[k];
        }
        // Also drop the live-vote re-anchor field nested in the TA challenge.
        if (clone.title_artist_challenge && typeof clone.title_artist_challenge === 'object') {
            var ta = {};
            for (var tk in clone.title_artist_challenge) {
                if (!Object.prototype.hasOwnProperty.call(clone.title_artist_challenge, tk)) continue;
                if (tk === 'vote_seconds_remaining') continue;
                ta[tk] = clone.title_artist_challenge[tk];
            }
            clone.title_artist_challenge = ta;
        }
        try { return JSON.stringify(clone); } catch (e) { return null; }
    }
    function _stateRenderEqual(a, b) {
        var ka = _stateRenderKey(a);
        return ka !== null && ka === _stateRenderKey(b);
    }

    // #1705: keyed row reconciler — replaces the full `container.innerHTML = …`
    // leaderboard rebuild on every broadcast. Each desired row carries a stable
    // `key` (player name) and its full outer-HTML string as the signature; rows
    // whose signature is unchanged keep their existing DOM node (no re-parse, no
    // re-triggered CSS animation), changed rows are swapped in place, stale rows
    // are removed, and the child order is synced to `rows`.
    function _reconcileRows(container, rows) {
        var existing = {};
        var child = container.firstElementChild;
        while (child) {
            var ek = child.getAttribute('data-row-key');
            if (ek != null) existing[ek] = child;
            child = child.nextElementSibling;
        }
        var prevSig = container._beatifyRowSigs || {};
        var newSig = {};
        var desired = [];
        rows.forEach(function(row) {
            var el = existing[row.key];
            if (!el || prevSig[row.key] !== row.html) {
                var tmp = document.createElement('div');
                tmp.innerHTML = row.html;
                el = tmp.firstElementChild;
                if (el) el.setAttribute('data-row-key', row.key);
            }
            if (el) { newSig[row.key] = row.html; desired.push(el); }
        });
        // Remove nodes that are no longer desired.
        var desiredKeys = {};
        desired.forEach(function(n) { desiredKeys[n.getAttribute('data-row-key')] = true; });
        child = container.firstElementChild;
        while (child) {
            var next = child.nextElementSibling;
            var ck = child.getAttribute('data-row-key');
            if (ck == null || !desiredKeys[ck]) container.removeChild(child);
            child = next;
        }
        // Sync order / insert new nodes.
        for (var i = 0; i < desired.length; i++) {
            if (container.children[i] !== desired[i]) {
                container.insertBefore(desired[i], container.children[i] || null);
            }
        }
        container._beatifyRowSigs = newSig;
    }

    // #1712: dim/undim the frozen last frame while the socket is down so the
    // room can tell the connection dropped without the game being wiped.
    function _setDisconnectedDim(on) {
        var root = document.querySelector('.dashboard-container');
        if (root) root.classList.toggle('dashboard-disconnected', !!on);
    }

    // #1705: coalesced entry point — the heavy DOM render runs at most once per
    // frame and only when the visible state changed. Assigned here (both the
    // renderer and the coalescer factory are hoisted function declarations).
    var _scheduleRender = createRenderCoalescer(_applyStateRender, { isEqual: _stateRenderEqual });

    // Utility functions from BeatifyUtils
    // waitForI18n, t, getLocalizedSongField, escapeHtml moved to BeatifyUtils

    /**
     * Show a specific view and hide all others
     * @param {string} viewId - ID of view to show
     */
    function showView(viewId) {
        utils.showView(allViews, viewId);
    }

    /**
     * Get reconnection delay with capped exponential backoff (#1398).
     * Delegates to the shared, unit-tested BeatifyUtils.reconnectBackoffDelay so
     * the policy lives in one place. `reconnectAttempts` is 1-based here (it is
     * incremented before this is called); the helper never overflows for large
     * attempt counts, so an indefinitely-retrying display stays at the 30s cap.
     * @returns {number} Delay in milliseconds
     */
    function getReconnectDelay() {
        if (utils.reconnectBackoffDelay) {
            return utils.reconnectBackoffDelay(reconnectAttempts, { maxDelay: MAX_RECONNECT_DELAY_MS });
        }
        // Fallback if utils failed to load: same capped backoff, 1-based attempt.
        return Math.min(1000 * Math.pow(2, reconnectAttempts - 1), MAX_RECONNECT_DELAY_MS);
    }

    // Reconnect indicator (#1578): a passive always-on TV display can lose its
    // WebSocket overnight and the old code reconnected silently — nothing on the
    // screen showed the connection had dropped. Surface a small, unobtrusive
    // "Reconnecting…" badge while the socket is down so a glance at the display
    // reveals the connection is being re-established; hide it once reconnected.
    // The badge is a fixed corner overlay, so it never blocks the TV content.
    function _showReconnectIndicator() {
        var el = document.getElementById('dashboard-reconnect-indicator');
        if (el) el.classList.remove('hidden');
    }

    function _hideReconnectIndicator() {
        var el = document.getElementById('dashboard-reconnect-indicator');
        if (el) el.classList.add('hidden');
    }

    /**
     * Connect to WebSocket as read-only observer (AC 10.4.1)
     */
    function connectWebSocket() {
        // #1397: cancel any pending backoff-timer reconnect so it can't fire
        // after this call and open a second parallel socket.
        reconnectGuard.cancel();
        // Detach the previous socket's handlers before replacing it. Without
        // this, an orphaned (still-open or closing) socket keeps rendering
        // broadcasts and re-scheduling reconnects via its onclose. (#1397)
        if (ws) {
            ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
            try { ws.close(); } catch (e) { /* already closed */ }
        }

        var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            debug('[Dashboard] WebSocket connected');
            reconnectAttempts = 0;
            // #1578: connection is back — drop the "Reconnecting…" badge.
            _hideReconnectIndicator();
            // #1712: un-dim the frozen last frame; the server's next `state`
            // broadcast is what decides whether we stay on the live view or
            // switch to the confirmed "No active game" screen.
            _setDisconnectedDim(false);
            // Request current state as read-only observer
            ws.send(JSON.stringify({ type: 'get_state' }));
        };

        ws.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error('[Dashboard] Failed to parse message:', e);
            }
        };

        ws.onclose = function() {
            debug('[Dashboard] WebSocket closed');
            // #1398 + #1397: retry FOREVER with capped backoff, scheduled through
            // the dedup guard so a visibilitychange reconnect can cancel the
            // pending timer instead of racing it into a second socket.
            reconnectAttempts++;
            // #1712: a transient mid-game WS drop must NOT wipe the live game.
            // Keep whatever view is currently rendered (leaderboard / round /
            // art / scores) frozen and dimmed, and surface ONLY the reconnect
            // badge. The "No active game" screen is reserved for a
            // server-CONFIRMED no-game state (handleStateUpdate), never a
            // dropped socket — that used to read as a crash to the whole room.
            _setDisconnectedDim(true);
            // #1578: surface the reconnect attempt visibly on the TV display.
            _showReconnectIndicator();
            var delay = getReconnectDelay();
            debug('[Dashboard] Reconnecting in ' + delay + 'ms (attempt ' + reconnectAttempts + ')');
            reconnectGuard.schedule(connectWebSocket, delay);
        };

        ws.onerror = function(err) {
            console.error('[Dashboard] WebSocket error:', err);
        };
    }

    // ============================================
    // Screen Wake Lock (#1122)
    // ============================================
    // Dashboard is typically used as an always-on TV / monitor display.
    // Without the wake lock the screen sleeps after the OS idle timer,
    // the tab is backgrounded, and the WebSocket connection drops within
    // ~30s (iOS Safari is especially aggressive). Mirrors the pattern
    // player-core.js uses (#622 / #646).
    //
    // Layer 1: navigator.wakeLock — Safari ≥16.4, Chrome, Edge, Firefox.
    // Layer 2: NoSleep.js silent-video fallback — iOS HA Companion WKWebView,
    //          older Safari, anywhere Layer 1 is unavailable or rejected.
    // NoSleep loaded via /beatify/static/js/vendor/no-sleep.min.js in
    // dashboard.html before this script runs.

    var _wakeLock = null;
    var _noSleep = null;
    var _noSleepActive = false;

    function _ensureNoSleep() {
        if (_noSleep) return _noSleep;
        if (typeof window !== 'undefined' && typeof window.NoSleep === 'function') {
            try { _noSleep = new window.NoSleep(); } catch (err) {
                console.debug('[BeatifyWakeLock] NoSleep instantiation failed:', err);
            }
        }
        return _noSleep;
    }

    // Layer 2a (#1208): a MUTED autoplay inline video. iOS / iPadOS allow
    // muted inline playback to START WITHOUT a user gesture, unlike NoSleep's
    // unmuted clip below (which iOS gates behind a tap). On a passive TV /
    // dashboard display that never receives a touch, this is the only
    // keep-awake path that can engage. Reuses the proven clip from
    // no-sleep.min.js. Android/desktop already hold the lock via Layer 1.
    var _keepAwakeVideo = null;
    var _KEEPAWAKE_MP4 = 'data:video/mp4;base64,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';
    function _ensureMutedAutoplayVideo() {
        if (_keepAwakeVideo) return _keepAwakeVideo;
        try {
            var v = document.createElement('video');
            v.muted = true;
            v.setAttribute('muted', '');
            v.setAttribute('autoplay', '');
            v.setAttribute('playsinline', '');
            v.setAttribute('loop', '');
            v.setAttribute('title', 'Beatify keep awake');
            v.style.cssText = 'position:fixed;left:-1px;top:-1px;width:1px;height:1px;opacity:0;pointer-events:none;';
            var src = document.createElement('source');
            src.src = _KEEPAWAKE_MP4;
            src.type = 'video/mp4';
            v.appendChild(src);
            (document.body || document.documentElement).appendChild(v);
            _keepAwakeVideo = v;
        } catch (err) {
            console.debug('[BeatifyWakeLock] Layer 2a video create failed:', err);
        }
        return _keepAwakeVideo;
    }

    // Returns true if a reliable wake lock engaged (native Layer 1), false if
    // we had to fall back to a best-effort path. The #1285 banner uses the
    // false result to offer a one-tap re-try inside a trusted user gesture —
    // iOS blocks navigator.wakeLock.request() on a passive TV/dashboard
    // display that never received a touch, but allows it from a tap handler.
    async function requestWakeLock() {
        if ('wakeLock' in navigator) {
            try {
                _wakeLock = await navigator.wakeLock.request('screen');
                _wakeLock.addEventListener('release', function() {
                    console.debug('[BeatifyWakeLock] Layer 1 released by browser');
                    _wakeLock = null;
                });
                console.debug('[BeatifyWakeLock] Layer 1 (native wakeLock) acquired');
                return true;
            } catch (err) {
                console.debug('[BeatifyWakeLock] Layer 1 request failed:', err, '— trying Layer 2');
            }
        } else {
            console.debug('[BeatifyWakeLock] Layer 1 unavailable — using Layer 2');
        }
        // Layer 2a (#1208): muted autoplay video — engages with no gesture,
        // so a never-touched iOS dashboard display still keeps its screen on.
        var mv = _ensureMutedAutoplayVideo();
        if (mv) {
            try {
                var mp = mv.play();
                if (mp && typeof mp.catch === 'function') {
                    mp.catch(function(err) {
                        console.debug('[BeatifyWakeLock] Layer 2a muted-video play rejected:', err);
                    });
                }
            } catch (err) {
                console.debug('[BeatifyWakeLock] Layer 2a play threw:', err);
            }
        }
        var ns = _ensureNoSleep();
        if (!ns) {
            console.debug('[BeatifyWakeLock] Layer 2 unavailable (NoSleep vendor not loaded)');
            return false;
        }
        if (_noSleepActive) return false;
        try {
            var p = ns.enable();
            _noSleepActive = true;
            if (p && typeof p.catch === 'function') {
                p.catch(function(err) {
                    // Reset the flag so a later banner-tap (#1285) /
                    // visibilitychange retry can re-attempt ns.enable() inside a
                    // trusted gesture — otherwise the one-tap recovery silently
                    // no-ops on iOS where the init() call was gesture-rejected.
                    _noSleepActive = false;
                    console.debug('[BeatifyWakeLock] Layer 2 enable promise rejected:', err);
                });
            }
            console.debug('[BeatifyWakeLock] Layer 2 (NoSleep video) enabled');
        } catch (err) {
            console.debug('[BeatifyWakeLock] Layer 2 enable failed:', err);
            _noSleepActive = false;
        }
        return false;
    }

    // ============================================
    // Wake-Lock activation banner (#1285, design option 2)
    // ============================================
    // On a passive iOS TV/dashboard display the native screen wake lock is
    // rejected without a user gesture, so requestWakeLock() above can only fall
    // back to a best-effort path. The banner surfaces a single tap that re-runs
    // requestWakeLock() inside a trusted gesture context, letting the native
    // lock (and NoSleep video) fully engage. Dismissal is remembered so the
    // banner never nags on a display where the user already chose.
    var _WAKE_BANNER_DISMISS_KEY = 'beatify_wakelock_banner_dismissed';

    function _wakeBannerDismissed() {
        try { return localStorage.getItem(_WAKE_BANNER_DISMISS_KEY) === '1'; }
        catch (e) { return false; }
    }

    function _rememberWakeBannerDismissed() {
        try { localStorage.setItem(_WAKE_BANNER_DISMISS_KEY, '1'); } catch (e) { /* private mode */ }
    }

    function _hideWakeBanner() {
        var banner = document.getElementById('dashboard-wakelock-banner');
        if (banner) banner.classList.add('hidden');
    }

    function _showWakeBanner() {
        if (_wakeBannerDismissed()) return;
        var banner = document.getElementById('dashboard-wakelock-banner');
        if (!banner) return;
        banner.classList.remove('hidden');
    }

    function _initWakeBanner() {
        var banner = document.getElementById('dashboard-wakelock-banner');
        if (!banner) return;
        var activateBtn = document.getElementById('dashboard-wakelock-activate');
        var dismissBtn = document.getElementById('dashboard-wakelock-dismiss');
        if (activateBtn) {
            activateBtn.addEventListener('click', function() {
                // Tap is the trusted gesture iOS requires — re-run the full
                // request so the native lock can engage; remember the choice.
                requestWakeLock();
                _rememberWakeBannerDismissed();
                _hideWakeBanner();
            });
        }
        if (dismissBtn) {
            dismissBtn.addEventListener('click', function() {
                _rememberWakeBannerDismissed();
                _hideWakeBanner();
            });
        }
    }

    // Re-acquire the lock and reconnect the WS when the tab becomes
    // visible again. Mobile browsers release wake locks automatically
    // on tab hide; without this handler the dashboard would freeze on
    // its last frame until the exponential-backoff reconnect catches up,
    // which can take 30 seconds.
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            requestWakeLock();
            if (!ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
                debug('[Dashboard] Page visible, WebSocket dead — reconnecting immediately.');
                reconnectAttempts = 0;
                connectWebSocket();
            }
        }
    });

    /**
     * Handle messages from server
     * @param {Object} data - Parsed message data
     */
    function handleServerMessage(data) {
        if (data.type === 'state') {
            // Debug: Log game_performance data (Story 14.4)
            if (data.game_performance) {
                debug('[Dashboard] game_performance:', data.game_performance);
            }
            handleStateUpdate(data);
        } else if (data.type === 'error') {
            debug('[Dashboard] Server error:', data.message);
            // Dashboard ignores most errors since it's read-only
        } else if (data.type === 'player_reaction') {
            // Live reactions from players (Story 18.9)
            showFloatingReaction(data.player_name, data.emoji);
        } else if (data.type === 'metadata_update') {
            // Issue #42: Handle async metadata update for fast transitions
            handleMetadataUpdate(data.song);
        } else if (data.type === 'game_starting') {
            // #1287: cold-start bridge. The admin pressed start; show the
            // animated vinyl-disc loader while the Music Assistant speaker
            // connects + round 1 loads (~10-15s). The next PLAYING `state`
            // broadcast replaces it.
            stopCountdown();
            showView('dashboard-starting');
        }
        // Dashboard ignores submit_ack, song_stopped, volume_changed since it doesn't interact
    }

    /**
     * Handle async metadata update for fast transitions (Issue #42)
     * Updates album art with fade transition when metadata becomes available
     * @param {Object} song - Song metadata with artist, title, album_art
     */
    function handleMetadataUpdate(song) {
        if (!song) return;

        var albumArt = document.getElementById('dashboard-album-art');
        if (albumArt && song.album_art) {
            var newSrc = song.album_art;

            // Skip if already showing this image
            if (albumArt.src === newSrc) return;

            // Fade transition for smooth update
            albumArt.style.transition = 'opacity 0.3s ease-in-out';
            albumArt.style.opacity = '0.5';

            // Preload and swap
            var preloader = new Image();
            preloader.onload = function() {
                albumArt.src = newSrc;
                albumArt.style.opacity = '1';
            };
            preloader.onerror = function() {
                albumArt.src = '/beatify/static/img/no-artwork.svg';
                albumArt.style.opacity = '1';
            };
            preloader.src = newSrc;
        }

        debug('[Dashboard] Metadata updated:', song.artist, '-', song.title);
    }

    /**
     * Handle state update from server
     * @param {Object} data - State data
     */
    function handleStateUpdate(data) {
        // Apply language from game state (Story 12.5, 16.3)
        // Must re-render after language loads to update dynamic content
        // Guard: skip if i18n unavailable
        if (typeof BeatifyI18n !== 'undefined' && data.language && data.language !== BeatifyI18n.getLanguage()) {
            // #1402-B8: setLanguage() normalizes an unsupported code to 'en' and
            // resolves with the EFFECTIVELY-APPLIED code. We must re-render only
            // when the applied locale actually differs from what we'd compare on
            // re-entry — otherwise a state carrying an unsupported language (e.g.
            // 'pt') loops forever: getLanguage() can never equal 'pt', so each
            // re-render re-enters this branch. Re-render with applied locale and
            // guard the recursion against the resolved (not requested) code.
            BeatifyI18n.setLanguage(data.language).then(function(appliedLang) {
                BeatifyI18n.initPageTranslations();
                if (appliedLang === BeatifyI18n.getLanguage()) {
                    // Re-render current view with correct language. The branch
                    // above won't re-fire because data.language is now stale vs
                    // the applied locale check below — but to be safe against an
                    // unsupported code (data.language !== appliedLang) we mutate
                    // the local copy so the recursive call's comparison settles.
                    if (data.language !== appliedLang) {
                        data = Object.assign({}, data, { language: appliedLang });
                    }
                    handleStateUpdate(data);
                }
            });
            // Don't render yet - wait for language to load
            return;
        }

        // #1705: hand the payload to the coalescer instead of rendering inline.
        // A burst of broadcasts now collapses to one render per frame and an
        // unchanged state skips the render entirely.
        _scheduleRender(data);
    }

    /**
     * Apply a state payload to the DOM (the heavy render). Invoked by the
     * #1705 coalescer at most once per animation frame with the latest payload
     * of a burst — never call this directly from the WS handler.
     * @param {Object} data - State data
     */
    function _applyStateRender(data) {
        var phase = data.phase;

        if (!phase || phase === 'END' && !data.game_id) {
            // No active game (server-CONFIRMED — see #1712: a dropped socket
            // does NOT reach here, so it never shows this screen).
            showView('dashboard-no-game');
            stopCountdown();
            return;
        }

        switch (phase) {
            case 'LOBBY':
                stopCountdown();
                showView('dashboard-lobby');
                renderLobbyView(data);
                break;
            case 'PLAYING':
                showView('dashboard-playing');
                renderPlayingView(data);
                break;
            case 'REVEAL':
                stopCountdown();
                showView('dashboard-reveal');
                renderRevealView(data);
                break;
            case 'END':
                stopCountdown();
                showView('dashboard-end');
                renderEndView(data);
                break;
            case 'PAUSED':
                stopCountdown();
                showView('dashboard-paused');
                break;
            default:
                debug('[Dashboard] Unknown phase:', phase);
        }
    }

    // ============================================
    // Lobby View (AC 10.4.2)
    // ============================================

    /**
     * Render lobby view with QR code and player list
     * @param {Object} data - State data
     */
    function renderLobbyView(data) {
        var players = data.players || [];

        // Render QR code
        if (data.join_url) {
            renderQRCode(data.join_url);
        }

        // #1713: always surface the join URL as large, readable text beneath the
        // QR so a guest whose camera can't lock the code (or who prefers to type
        // it) has a fallback — and so there's a real address on screen if the QR
        // library itself fails to load. Single most important join affordance,
        // so it must never be a single point of failure.
        var joinUrlEl = document.getElementById('dashboard-join-url');
        if (joinUrlEl) {
            // #1756: localize the aria-label (was a hardcoded English "Join address").
            joinUrlEl.setAttribute('aria-label', utils.t('dashboard.joinAddressLabel', 'Join address'));
            if (data.join_url) {
                joinUrlEl.textContent = data.join_url;
                joinUrlEl.classList.remove('hidden');
            } else {
                joinUrlEl.textContent = '';
                joinUrlEl.classList.add('hidden');
            }
        }

        // Render game settings indicator (top-right corner)
        renderGameSettings(data);

        // Update player count
        // #1402-B8: was hardcoded English ("N players joined") on an otherwise
        // localized TV dashboard. Use an i18n key with {n} interpolation plus a
        // singular variant; utils.t() falls back to the English literal if the
        // key is missing from a locale.
        var countEl = document.getElementById('dashboard-player-count');
        if (countEl) {
            var count = players.length;
            var joinedKey = count === 1 ? 'dashboard.playersJoinedOne' : 'dashboard.playersJoined';
            var joinedFallback = count + ' player' + (count !== 1 ? 's' : '') + ' joined';
            countEl.textContent = utils.t(joinedKey, joinedFallback).replace(/\{n\}/g, count);
        }

        // Render player list with slide-in animation
        renderPlayerList(players);
    }

    /**
     * Render game settings indicator (rounds, difficulty)
     * @param {Object} data - State data with total_rounds and difficulty
     */
    function renderGameSettings(data) {
        var el = document.getElementById('dashboard-game-settings');
        if (!el) return;

        var rounds = data.total_rounds || 10;
        var difficulty = data.difficulty || 'normal';

        // Translate difficulty label
        var difficultyLabel = t('admin.difficulty' + difficulty.charAt(0).toUpperCase() + difficulty.slice(1), difficulty);

        el.textContent = rounds + ' ' + utils.t('dashboard.rounds', 'rounds') + ' • ' + difficultyLabel;
    }

    /**
     * Render QR code for joining game
     * @param {string} joinUrl - URL to encode
     */
    function renderQRCode(joinUrl) {
        var container = document.getElementById('dashboard-qr-code');
        if (!container) return;

        // Skip re-render if URL hasn't changed (prevents flicker)
        if (joinUrl === lastQRCodeUrl) return;
        lastQRCodeUrl = joinUrl;

        // Clear previous
        container.innerHTML = '';

        if (typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: joinUrl,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });
        } else {
            // #1713: QR library failed to load — don't dead-end on "unavailable".
            // The readable join URL rendered beneath the QR (renderLobbyView) is
            // the fallback, so point the guest at it.
            container.innerHTML = '<p class="dashboard-qr-fallback">' +
                utils.escapeHtml(utils.t('dashboard.qrUnavailable', 'Scan unavailable — enter the web address below')) +
                '</p>';
        }
    }

    /**
     * Render player list in lobby
     * @param {Array} players - Array of player objects
     */
    function renderPlayerList(players) {
        var listEl = document.getElementById('dashboard-player-list');
        if (!listEl) return;

        // Story 11.4: Sort players - connected first, then disconnected
        var sortedPlayers = players.slice().sort(function(a, b) {
            if (a.connected !== b.connected) {
                return a.connected ? -1 : 1;
            }
            return 0;
        });

        // Find new players
        var previousNames = previousPlayers.map(function(p) { return p.name; });
        var newNames = sortedPlayers
            .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
            .map(function(p) { return p.name; });

        // Render player cards
        listEl.innerHTML = sortedPlayers.map(function(player) {
            var isNew = newNames.indexOf(player.name) !== -1;
            var isDisconnected = player.connected === false;
            var classes = ['dashboard-player-card'];
            if (isNew) classes.push('is-new');
            if (isDisconnected) classes.push('dashboard-player-card--disconnected');

            var awayBadge = isDisconnected ? '<span class="away-badge">(away)</span>' : '';

            return '<div class="' + classes.join(' ') + '">' +
                utils.escapeHtml(player.name) + awayBadge +
            '</div>';
        }).join('');

        // Remove is-new class after animation
        setTimeout(function() {
            var newCards = listEl.querySelectorAll('.is-new');
            for (var i = 0; i < newCards.length; i++) {
                newCards[i].classList.remove('is-new');
            }
        }, 2000);

        previousPlayers = players.slice();
    }

    // ============================================
    // Playing View (AC 10.4.3)
    // ============================================

    /**
     * Render playing view with blurred album art, timer, and leaderboard
     * @param {Object} data - State data
     */
    function renderPlayingView(data) {
        var song = data.song || {};
        var players = data.players || [];

        // Update round indicator
        var currentRound = document.getElementById('dashboard-current-round');
        var totalRounds = document.getElementById('dashboard-total-rounds');
        if (currentRound) currentRound.textContent = data.round || 1;
        if (totalRounds) totalRounds.textContent = data.total_rounds || 10;

        // Issue #23: Show/hide intro round badge
        var introBadge = document.getElementById('dashboard-intro-badge');
        if (introBadge) {
            if (data.is_intro_round) {
                introBadge.classList.remove('hidden');
                var badgeText = introBadge.querySelector('[data-i18n]');
                if (data.intro_stopped) {
                    introBadge.classList.add('intro-badge--stopped');
                    if (badgeText) {
                        badgeText.setAttribute('data-i18n', 'game.introStopped');
                        badgeText.textContent = utils.t('game.introStopped') || 'Intro complete!';
                    }
                } else {
                    introBadge.classList.remove('intro-badge--stopped');
                    if (badgeText) {
                        badgeText.setAttribute('data-i18n', 'game.introRound');
                        badgeText.textContent = utils.t('game.introRound') || 'INTRO ROUND';
                    }
                }
            } else {
                introBadge.classList.add('hidden');
                introBadge.classList.remove('intro-badge--stopped');
            }
        }

        // Issue #442: Show/hide Closest Wins badge
        var closestBadge = document.getElementById('dashboard-closest-wins-badge');
        if (closestBadge) {
            if (data.closest_wins_mode) {
                closestBadge.classList.remove('hidden');
            } else {
                closestBadge.classList.add('hidden');
            }
        }

        // Update album art (blurred - AC 10.4.3)
        // #1767: unchanged-src short-circuit (mirrors handleMetadataUpdate +
        // player-game.js/player-reveal.js). renderPlayingView runs on EVERY changed
        // PLAYING broadcast (each vote/submission tick passes the #1705 coalescer);
        // reassigning albumArt.src — even to the same URL — re-runs the image load
        // algorithm (re-decode + paint) on weak TV hardware. Track the last
        // requested URL on the element (album_art can be relative, so the resolved
        // .src is unreliable) and skip when unchanged.
        var albumArt = document.getElementById('dashboard-album-art');
        if (albumArt) {
            var newArtSrc = song.album_art || '/beatify/static/img/no-artwork.svg';
            if (albumArt._beatifyRequestedSrc !== newArtSrc) {
                albumArt._beatifyRequestedSrc = newArtSrc;
                albumArt.onerror = function() {
                    // Reset so a later retry with the same URL re-attempts the load.
                    this._beatifyRequestedSrc = null;
                    this.src = '/beatify/static/img/no-artwork.svg';
                };
                albumArt.src = newArtSrc;
            }
        }

        // Start countdown — #1705: (re)start ONLY when the round's deadline
        // actually changes. On a plain re-render (a submission/score update that
        // reuses the same deadline) the running 1Hz timer must keep ticking
        // instead of being torn down + recreated on every broadcast.
        if (data.deadline && data.deadline !== lastCountdownDeadline) {
            lastCountdownDeadline = data.deadline;
            // #1662: pass the server's relative seconds_remaining so the
            // countdown anchors to the client's own clock (skew-immune).
            startCountdown(data.deadline, data.seconds_remaining);
        }

        // Render leaderboard with submission indicators and bet badges
        renderLeaderboard(data.leaderboard || [], players, 'dashboard-leaderboard', true, true);

        // Update round statistics (Story 16.4)
        renderRoundStats(data, players);

        // Issue #827: Sudden-Death FINAL banner (2 players left).
        renderSuddenDeathFinalBanner(data, 'sd-final-banner-playing');
    }

    /**
     * Render round statistics below leaderboard (Story 16.4)
     * @param {Object} data - State data
     * @param {Array} players - Players array
     */
    function renderRoundStats(data, players) {
        debug('[Dashboard] renderRoundStats called, players:', players);
        debug('[Dashboard] data.players:', data.players);

        // Calculate submission count
        var submitted = 0;
        var total = players.length;
        players.forEach(function(p) {
            if (p.submitted) submitted++;
        });

        debug('[Dashboard] Submissions:', submitted, '/', total);

        var submissionsEl = document.getElementById('dashboard-submissions');
        if (submissionsEl) {
            submissionsEl.textContent = submitted + '/' + total;
            debug('[Dashboard] Updated submissions element');
        } else {
            console.warn('[Dashboard] dashboard-submissions element not found');
        }

        // Time remaining is already shown in the main timer, but we update the stat too
        var timeEl = document.getElementById('dashboard-time-remaining');
        if (timeEl && data.deadline) {
            // #1662: prefer the server's relative seconds_remaining (skew-immune)
            // over subtracting the server wall-clock deadline from a possibly
            // wrong client clock. Fall back to the absolute deadline if absent.
            var remaining = (typeof data.seconds_remaining === 'number')
                ? Math.max(0, data.seconds_remaining)
                : Math.max(0, Math.ceil((data.deadline - Date.now()) / 1000));
            timeEl.textContent = remaining + 's';
        }
    }

    /**
     * Start countdown timer (AC 10.4.3)
     * @param {number} deadline - Server deadline timestamp in milliseconds
     * @param {number} [secondsRemaining] - Server-computed *relative* seconds
     *   left. #1662: when present, the countdown re-anchors to the CLIENT's own
     *   clock (skew-immune) instead of subtracting the server wall-clock
     *   `deadline` from a possibly-wrong client `Date.now()`. Mirrors the
     *   TA-vote timer (player-reveal.js). Absent → fall back to raw `deadline`.
     */
    function startCountdown(deadline, secondsRemaining) {
        stopCountdown();

        var timerElement = document.getElementById('dashboard-timer');
        var timeStatEl = document.getElementById('dashboard-time-remaining');
        if (!timerElement) return;

        timerElement.classList.remove('timer--warning', 'timer--critical');

        // #1662: derive a CLIENT-LOCAL deadline from the server's relative
        // remaining seconds so a wrong client clock can't skew the countdown.
        var effectiveDeadline =
            (typeof secondsRemaining === 'number' && isFinite(secondsRemaining))
                ? Date.now() + secondsRemaining * 1000
                : deadline;

        function updateCountdown() {
            var now = Date.now();
            var remaining = Math.max(0, Math.ceil((effectiveDeadline - now) / 1000));

            timerElement.textContent = remaining;

            // Also update round stats time (Story 16.4)
            if (timeStatEl) {
                timeStatEl.textContent = remaining + 's';
            }

            // Update timer style based on remaining time (AC 10.4.3)
            if (remaining <= 5) {
                timerElement.classList.remove('timer--warning');
                timerElement.classList.add('timer--critical');
            } else if (remaining <= 10) {
                timerElement.classList.remove('timer--critical');
                timerElement.classList.add('timer--warning');
            } else {
                timerElement.classList.remove('timer--warning', 'timer--critical');
            }

            if (remaining <= 0) {
                stopCountdown();
            }
        }

        updateCountdown();
        countdownInterval = setInterval(updateCountdown, 1000);
    }

    /**
     * Stop countdown timer
     */
    function stopCountdown() {
        if (countdownInterval) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
        // #1705: forget the tracked deadline so the next PLAYING round always
        // (re)starts its countdown, even if it happens to reuse the same value.
        lastCountdownDeadline = null;
    }

    /**
     * Render leaderboard
     * @param {Array} leaderboard - Leaderboard entries
     * @param {Array} players - Players list (for submission status)
     * @param {string} containerId - Container element ID
     * @param {boolean} showSubmitted - Whether to show submission indicators
     * @param {boolean} showBet - Whether to show bet badges next to names
     */
    function renderLeaderboard(leaderboard, players, containerId, showSubmitted, showBet) {
        var container = document.getElementById(containerId);
        if (!container) return;

        // Build player submission and bet maps
        var submissionMap = {};
        var betMap = {};
        if (players) {
            players.forEach(function(p) {
                submissionMap[p.name] = p.submitted;
                betMap[p.name] = p.bet;
            });
        }

        // #1705: build keyed rows and diff them into the DOM instead of blowing
        // away the whole N-row list with innerHTML on every broadcast.
        var rows = leaderboard.map(function(entry) {
            var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';

            // Rank change animation class
            var animationClass = '';
            if (entry.rank_change > 0) {
                animationClass = 'leaderboard-entry--climbing';
            } else if (entry.rank_change < 0) {
                animationClass = 'leaderboard-entry--falling';
            }

            // Story 11.4: Disconnected player styling
            var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

            // Issue #827: Sudden-Death — eliminated players render dimmed with a
            // 💀 prefix. Reuses .leaderboard-entry--disconnected for the dim.
            var eliminatedClass = entry.eliminated ? 'leaderboard-entry--disconnected' : '';
            var skullPrefix = entry.eliminated ? '💀 ' : '';

            // Rank change indicator (AC 10.4.4 - with arrows)
            var changeIndicator = '';
            if (entry.rank_change > 0) {
                changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
            } else if (entry.rank_change < 0) {
                changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';
            }

            // Streak indicator (AC 10.4.3 - with fire emoji)
            var streakIndicator = '';
            if (entry.streak >= 2) {
                var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
                streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
            }

            // Bet badge next to name during playing phase
            var betBadge = '';
            if (showBet && betMap[entry.name]) {
                betBadge = '<span class="bet-badge">BET</span>';
            }

            // Submission indicator (AC 10.4.3)
            var submittedIndicator = '';
            if (showSubmitted) {
                var isSubmitted = submissionMap[entry.name] === true;
                submittedIndicator = '<div class="entry-submitted ' + (isSubmitted ? 'is-submitted' : '') + '"></div>';
            }

            var html = '<div class="leaderboard-entry ' + rankClass + ' ' + animationClass + ' ' + disconnectedClass + ' ' + eliminatedClass + '">' +
                '<span class="entry-rank">#' + entry.rank + '</span>' +
                '<span class="entry-name">' + skullPrefix + utils.escapeHtml(entry.name) + awayBadge + betBadge + '</span>' +
                '<span class="entry-meta">' +
                    streakIndicator +
                    changeIndicator +
                '</span>' +
                '<span class="entry-score">' + entry.score + '</span>' +
                submittedIndicator +
            '</div>';
            return { key: String(entry.name), html: html };
        });

        _reconcileRows(container, rows);
    }

    // ============================================
    // Reveal View (AC 10.4.4)
    // ============================================

    /**
     * Render reveal view with song info and leaderboard
     * @param {Object} data - State data
     */
    function renderRevealView(data) {
        var song = data.song || {};
        var players = data.players || [];

        // Update album art (clear - no blur)
        // #1767: unchanged-src short-circuit (see renderPlayingView). renderRevealView
        // reruns on every changed REVEAL broadcast during vote-heavy phases; skip the
        // src reassignment (re-decode + paint) when the requested URL is unchanged.
        var albumArt = document.getElementById('reveal-album-art');
        if (albumArt) {
            var newRevealArtSrc = song.album_art || '/beatify/static/img/no-artwork.svg';
            if (albumArt._beatifyRequestedSrc !== newRevealArtSrc) {
                albumArt._beatifyRequestedSrc = newRevealArtSrc;
                albumArt.onerror = function() {
                    // Reset so a later retry with the same URL re-attempts the load.
                    this._beatifyRequestedSrc = null;
                    this.src = '/beatify/static/img/no-artwork.svg';
                };
                albumArt.src = newRevealArtSrc;
            }
        }

        // Update song info
        var artistEl = document.getElementById('reveal-artist');
        var titleEl = document.getElementById('reveal-title');
        var yearEl = document.getElementById('reveal-year');

        if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';
        if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
        if (yearEl) yearEl.textContent = song.year || '????';

        // Lower-third announce: the YEAR is the hero in year mode; in Title &
        // Artist mode the year row hides and the TA banner carries the answer.
        var taMode = !!data.title_artist_mode;
        var yearRow = document.getElementById('reveal-year-row');
        if (yearRow) yearRow.classList.toggle('hidden', taMode);

        // Title & Artist mode (#1180): show truth banner + voting status on TV.
        renderDashboardTitleArtist(data);

        // Year mode: the guess-the-artist mini-game result (🎤 who got it).
        renderDashboardArtistChallenge(taMode ? null : data.artist_challenge);

        // Render fun fact (Story 16.4)
        renderFunFact(song);

        // Render top 3 guesses this round (AC 10.4.4)
        renderTopGuesses(players);

        // Render leaderboard with position changes
        renderRevealLeaderboard(data.leaderboard || []);

        // Issue #827: Sudden-Death — full-bleed "OUT" takeover for this round's
        // eliminations + FINAL banner (2 players left).
        renderSuddenDeathOut(data);
        renderSuddenDeathFinalBanner(data, 'sd-final-banner-reveal');

        // Render motivational message (Story 14.4)
        renderMotivationalMessage(data.game_performance);

        // #1185: Auto-advance countdown ring (Phone reveal already shows one;
        // TV dashboard didn't until @Dtrieb asked for it).
        updateRevealCountdown(data);

        // Render song difficulty rating (Story 15.1)
        renderSongDifficulty(data.song_difficulty);

        // Story 14.5 (AC1, AC2, AC7): Trigger celebration confetti on dashboard
        // M1 fix: Prioritize record over exact to avoid duplicate confetti
        if (data.game_performance && data.game_performance.is_new_record) {
            triggerConfetti('record');
        } else {
            // Check for any exact guesses this round
            var hasExactGuess = players.some(function(p) {
                return p.years_off === 0 && !p.missed_round;
            });
            if (hasExactGuess) {
                triggerConfetti('exact');
            }
        }
    }

    /**
     * Render the Title & Artist reveal banner on the TV (#1180): the truth
     * (correct_title — correct_artist) plus a "voting in progress" status when
     * the vote window is open. The standings leaderboard is rendered by the
     * existing renderRevealLeaderboard path and is unchanged.
     * @param {Object} data - State data (carries title_artist_mode + title_artist_challenge)
     */
    function renderDashboardTitleArtist(data) {
        var banner = document.getElementById('dashboard-ta-banner');
        if (!banner) return;

        var ta = data.title_artist_challenge || null;
        if (!data.title_artist_mode || !ta || !ta.correct_title) {
            banner.classList.add('hidden');
            _stopTaLiveCountdown();
            return;
        }
        banner.classList.remove('hidden');

        var titleEl = document.getElementById('dashboard-ta-title');
        var artistEl = document.getElementById('dashboard-ta-artist');
        if (titleEl) titleEl.textContent = ta.correct_title || '';
        if (artistEl) artistEl.textContent = ta.correct_artist || '';

        var votingOpen = !!ta.voting_open;
        var nearMisses = ta.near_misses || [];
        var outcomes = ta.near_miss_outcomes || [];
        var votingEl = document.getElementById('dashboard-ta-voting');
        var liveEl = document.getElementById('dashboard-ta-live');
        var outcomesEl = document.getElementById('dashboard-ta-outcomes');

        var fieldLabel = function(field) {
            return field === 'artist'
                ? utils.t('titleArtist.artistLabel', 'Artist')
                : utils.t('titleArtist.titleLabel', 'Song title');
        };

        // LIVE: while voting is open, show the running vote so the whole room can
        // watch it unfold — near-miss guesses + live 👍/👎 tally + countdown
        // (read-only; spectators vote on their phones) (#1180).
        if (votingOpen && nearMisses.length > 0 && liveEl) {
            if (votingEl) votingEl.classList.add('hidden');
            if (outcomesEl) { outcomesEl.innerHTML = ''; outcomesEl.classList.add('hidden'); }

            var cards = nearMisses.map(function(nm) {
                var pct = utils.taTallyPercents(nm.votes_yes, nm.votes_no);
                return '<div class="dashboard-ta-live-card">' +
                    '<div class="dashboard-ta-live-top">' +
                        '<span class="dashboard-ta-live-who">' + utils.escapeHtml(nm.player) + '</span>' +
                        '<span class="dashboard-ta-live-field">' + utils.escapeHtml(fieldLabel(nm.field)) + '</span>' +
                    '</div>' +
                    '<div class="dashboard-ta-live-guess">“' + utils.escapeHtml(nm.guess || '—') + '”</div>' +
                    '<div class="dashboard-ta-live-tally">' +
                        '<span class="dashboard-ta-live-y">👍 ' + (nm.votes_yes || 0) + '</span>' +
                        '<span class="dashboard-ta-live-track">' +
                            '<span class="dashboard-ta-live-fill dashboard-ta-live-fill--y" style="width:' + pct.yes + '%"></span>' +
                        '</span>' +
                        '<span class="dashboard-ta-live-n">👎 ' + (nm.votes_no || 0) + '</span>' +
                    '</div>' +
                '</div>';
            }).join('');

            liveEl.innerHTML =
                '<div class="dashboard-ta-live-head">' +
                    '<span class="dashboard-ta-deciding">' +
                        utils.escapeHtml(utils.t('titleArtist.dashboardDeciding', 'The room is deciding…')) +
                    '</span>' +
                    '<span id="dashboard-ta-live-cd" class="dashboard-ta-live-cd" aria-hidden="true"></span>' +
                '</div>' +
                '<div class="dashboard-ta-live-cards">' + cards + '</div>';
            liveEl.classList.remove('hidden');
            _startTaLiveCountdown(ta.vote_seconds_remaining);
            return;
        }

        // Not live: stop the ticker and clear the live view.
        _stopTaLiveCountdown();
        if (liveEl) { liveEl.innerHTML = ''; liveEl.classList.add('hidden'); }
        if (votingEl) votingEl.classList.add('hidden');

        // DECIDED: once voting closes, show the resolved verdicts so the room
        // sees what counted (#1180, #1243).
        if (outcomesEl) {
            if (!votingOpen && outcomes.length > 0) {
                var chips = outcomes.map(function(o) {
                    var accepted = !!o.accepted;
                    return '<div class="dashboard-ta-chip dashboard-ta-chip--' +
                            (accepted ? 'accepted' : 'rejected') + '">' +
                        '<span class="dashboard-ta-chip-who">' + utils.escapeHtml(o.player) + '</span>' +
                        '<span class="dashboard-ta-chip-field">' + utils.escapeHtml(fieldLabel(o.field)) + '</span>' +
                        '<span class="dashboard-ta-chip-verdict">' +
                            utils.escapeHtml(utils.taVerdictLabel(accepted, o.points)) +
                        '</span>' +
                    '</div>';
                }).join('');
                outcomesEl.innerHTML = '<div class="dashboard-ta-decided">' +
                    utils.escapeHtml(utils.t('titleArtist.closeCallsDecided', 'Close calls — decided')) +
                    '</div><div class="dashboard-ta-chips">' + chips + '</div>';
                outcomesEl.classList.remove('hidden');
            } else {
                outcomesEl.innerHTML = '';
                outcomesEl.classList.add('hidden');
            }
        }
    }

    /**
     * Year-mode artist-challenge result on the TV (the guess-the-artist
     * mini-game). Shows "🎤 The artist: <name>" + who got it (winner +bonus,
     * or a muted "nobody guessed"). Hidden when the challenge isn't active.
     * @param {Object|null} ac - data.artist_challenge { correct_artist, winner, bonus_points }
     */
    function renderDashboardArtistChallenge(ac) {
        var el = document.getElementById('reveal-artist-challenge');
        if (!el) return;
        if (!ac || !ac.correct_artist) {
            el.classList.add('hidden');
            el.innerHTML = '';
            return;
        }
        var label = utils.t('artistChallenge.theArtistWas', 'The artist');
        var resultHtml;
        if (ac.winner) {
            var pts = ac.bonus_points || 5;
            resultHtml = '<span class="reveal-ac-result reveal-ac-result--won">' +
                utils.escapeHtml(ac.winner) + ' +' + pts + '</span>';
        } else {
            resultHtml = '<span class="reveal-ac-result reveal-ac-result--none">' +
                utils.escapeHtml(utils.t('artistChallenge.noWinner', 'Nobody guessed it')) + '</span>';
        }
        el.innerHTML =
            '<span class="reveal-ac-ic" aria-hidden="true">🎤</span>' +
            '<span class="reveal-ac-label">' + utils.escapeHtml(label) + '</span>' +
            '<span class="reveal-ac-name">' + utils.escapeHtml(ac.correct_artist) + '</span>' +
            resultHtml;
        el.classList.remove('hidden');
    }

    // Local countdown ticker for the TV live-vote view. Anchored to the server's
    // vote_seconds_remaining (#1180) and re-synced on every broadcast.
    var _taLiveTick = null;
    function _startTaLiveCountdown(secondsRemaining) {
        _stopTaLiveCountdown();
        var el = document.getElementById('dashboard-ta-live-cd');
        if (!el) return;
        var remaining = (typeof secondsRemaining === 'number') ? secondsRemaining : 0;
        var endAt = Date.now() + remaining * 1000;
        function paint() {
            var r = Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
            el.textContent = r + 's';
            if (r <= 0) _stopTaLiveCountdown();
        }
        paint();
        _taLiveTick = setInterval(paint, 500);
    }
    function _stopTaLiveCountdown() {
        if (_taLiveTick) { clearInterval(_taLiveTick); _taLiveTick = null; }
    }

    /**
     * Render fun fact below year in reveal view (Story 16.4, 16.3)
     * @param {Object} song - Song data with optional fun_fact
     */
    function renderFunFact(song) {
        var container = document.getElementById('dashboard-fun-fact');
        var textEl = document.getElementById('dashboard-fun-fact-text');

        // Get localized fun fact (Story 16.3)
        var funFact = utils.getLocalizedSongField(song, 'fun_fact');

        debug('[Dashboard] renderFunFact called with song:', song);
        debug('[Dashboard] fun_fact value:', funFact || 'no fun fact');

        if (!container || !textEl) {
            console.warn('[Dashboard] Fun fact elements not found');
            return;
        }

        // Hide if no fun fact
        if (!funFact || funFact.trim() === '') {
            container.classList.add('hidden');
            debug('[Dashboard] No fun_fact, hiding container');
            return;
        }

        // Show fun fact
        textEl.textContent = funFact;
        container.classList.remove('hidden');
        debug('[Dashboard] Fun fact shown:', funFact);
    }

    /**
     * #1185: Drive the auto-advance countdown ring in the reveal chip strip.
     * Backend sends reveal_auto_advance (seconds, 0 = off) and reveal_started_at
     * (ms epoch). We render: remaining = max(0, started + duration*1000 - now).
     * Hidden when auto-advance is off OR when the round is idle-halted (no
     * submissions, game holds on REVEAL until manual advance).
     */
    var _countdownTick = null;
    function updateRevealCountdown(data) {
        var chip = document.getElementById('reveal-countdown');
        var numEl = document.getElementById('reveal-countdown-num');
        var fgCircle = chip ? chip.querySelector('.chip-countdown-fg') : null;
        if (!chip || !numEl || !fgCircle) return;

        // Stop any existing tick before re-binding state.
        if (_countdownTick !== null) {
            clearInterval(_countdownTick);
            _countdownTick = null;
        }

        var duration = data.reveal_auto_advance || 0;
        var startedAt = data.reveal_started_at || 0;
        var idleHalt = !!data.idle_halt;

        if (duration <= 0 || !startedAt || idleHalt) {
            chip.classList.add('hidden');
            return;
        }

        chip.classList.remove('hidden');
        // SVG circle r=25 → circumference 2πr ≈ 157.08
        var circumference = 157.08;
        fgCircle.style.strokeDasharray = circumference;

        function paint() {
            var remainingMs = Math.max(0, startedAt + duration * 1000 - Date.now());
            var remaining = Math.ceil(remainingMs / 1000);
            numEl.textContent = remaining;
            // Drained progress: ring is full at start, empties as time elapses.
            var pctRemaining = remainingMs / (duration * 1000);
            fgCircle.style.strokeDashoffset = String(circumference * (1 - pctRemaining));
            if (remainingMs <= 0 && _countdownTick !== null) {
                clearInterval(_countdownTick);
                _countdownTick = null;
            }
        }
        paint();
        _countdownTick = setInterval(paint, 500);
    }

    /**
     * Render motivational message during reveal phase (Story 14.4)
     * @param {Object|null} performance - Game performance data from state
     */
    function renderMotivationalMessage(performance) {
        var container = document.getElementById('reveal-motivational');
        if (!container) return;

        // Hide if no performance data or no message
        if (!performance || !performance.message) {
            container.classList.add('hidden');
            return;
        }

        var message = performance.message;
        var iconEl = container.querySelector('.motivational-icon');
        var textEl = container.querySelector('.motivational-text');

        // Set type-based styling and icon
        container.className = 'motivational-message motivational-message--' + message.type;

        // Icons for different message types
        var icons = {
            'first': '🌟',
            'record': '🏆',
            'strong': '🔥',
            'above': '📈',
            'close': '💪'
        };
        if (iconEl) iconEl.textContent = icons[message.type] || '';
        if (textEl) textEl.textContent = message.message || '';
    }

    /**
     * Render song difficulty rating (Story 15.1)
     * @param {Object|null} difficulty - Difficulty data with stars, label, accuracy, times_played
     */
    function renderSongDifficulty(difficulty) {
        var el = document.getElementById('song-difficulty');
        if (!el) return;

        // Hide if no difficulty data (AC4: insufficient plays)
        if (!difficulty) {
            el.classList.add('hidden');
            return;
        }

        // Build stars string
        var stars = '';
        for (var i = 0; i < difficulty.stars; i++) {
            stars += '<span class="star">&#9733;</span>';
        }

        // Render difficulty display
        el.innerHTML =
            '<div class="difficulty-stars difficulty-' + difficulty.stars + '">' + stars + '</div>' +
            '<span class="difficulty-label">' + utils.t('difficulty.' + difficulty.label) + '</span>' +
            '<span class="difficulty-accuracy">' + difficulty.accuracy + '% ' + utils.t('difficulty.accuracy') + '</span>';

        el.classList.remove('hidden');
    }

    /**
     * Render top 3 guesses this round
     * @param {Array} players - Players with round results
     */
    function renderTopGuesses(players) {
        var container = document.getElementById('reveal-top-guesses-list');
        if (!container) return;

        // Sort by round_score descending, take top 3
        var sorted = players
            .filter(function(p) { return !p.missed_round; })
            .sort(function(a, b) {
                return (b.round_score || 0) - (a.round_score || 0);
            })
            .slice(0, 3);

        var html = '';
        sorted.forEach(function(player, index) {
            // Show guessed year in brackets
            var yearDisplay = player.guess ? '<span class="top-guess-year">(' + player.guess + ')</span>' : '';

            // Show BET badge with outcome
            var betBadge = '';
            if (player.bet) {
                var badgeClass = 'bet-badge';
                if (player.bet_outcome === 'won') badgeClass += ' bet-badge--won';
                else if (player.bet_outcome === 'lost') badgeClass += ' bet-badge--lost';
                betBadge = '<span class="' + badgeClass + '">BET</span>';
            }

            html += '<div class="top-guess-entry">' +
                '<span class="top-guess-rank">#' + (index + 1) + '</span>' +
                '<span class="top-guess-name">' + utils.escapeHtml(player.name) + yearDisplay + '</span>' +
                '<span class="top-guess-points">+' + (player.round_score || 0) + betBadge + '</span>' +
            '</div>';
        });

        container.innerHTML = html;
    }

    /**
     * Render reveal leaderboard with position change indicators (AC 10.4.4)
     * @param {Array} leaderboard - Leaderboard entries
     */
    function renderRevealLeaderboard(leaderboard) {
        var container = document.getElementById('reveal-leaderboard');
        if (!container) return;

        // #1705: keyed row diff (reveal can re-broadcast during live TA voting).
        var rows = leaderboard.map(function(entry) {
            var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';

            // Rank change animation
            var animationClass = '';
            if (entry.rank_change > 0) {
                animationClass = 'leaderboard-entry--climbing';
            } else if (entry.rank_change < 0) {
                animationClass = 'leaderboard-entry--falling';
            }

            // Story 11.4: Disconnected player styling
            var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

            // Issue #827: Sudden-Death — eliminated players render dimmed with a
            // 💀 prefix. Reuses .leaderboard-entry--disconnected for the dim.
            var eliminatedClass = entry.eliminated ? 'leaderboard-entry--disconnected' : '';
            var skullPrefix = entry.eliminated ? '💀 ' : '';

            // Position change indicator (AC 10.4.4 - with arrows)
            var changeHtml = '';
            if (entry.rank_change > 0) {
                changeHtml = '<span class="entry-change is-positive">▲' + entry.rank_change + '</span>';
            } else if (entry.rank_change < 0) {
                changeHtml = '<span class="entry-change is-negative">▼' + Math.abs(entry.rank_change) + '</span>';
            }

            // Streak indicator (AC 10.4.3 - with fire emoji)
            var streakIndicator = '';
            if (entry.streak >= 2) {
                var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
                streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
            }

            var html = '<div class="leaderboard-entry ' + rankClass + ' ' + animationClass + ' ' + disconnectedClass + ' ' + eliminatedClass + '">' +
                '<span class="entry-rank">#' + entry.rank + '</span>' +
                '<span class="entry-name">' + skullPrefix + utils.escapeHtml(entry.name) + awayBadge + '</span>' +
                '<span class="entry-meta">' +
                    streakIndicator +
                    changeHtml +
                '</span>' +
                '<span class="entry-score">' + entry.score + '</span>' +
            '</div>';
            return { key: String(entry.name), html: html };
        });

        _reconcileRows(container, rows);
    }

    // ============================================
    // End View (AC 10.4.5)
    // ============================================

    /**
     * Render end view with podium and final leaderboard
     * @param {Object} data - State data
     */
    function renderEndView(data) {
        var leaderboard = data.leaderboard || [];

        // Issue #827: Sudden-Death "Last One Standing" hero above the podium.
        renderSuddenDeathLastStanding(data);

        // Update podium (AC 10.4.5) — name, score, and a colour-keyed avatar.
        [1, 2, 3].forEach(function(place) {
            var player = leaderboard.find(function(p) { return p.rank === place; });
            var nameEl = document.getElementById('end-podium-' + place + '-name');
            var scoreEl = document.getElementById('end-podium-' + place + '-score');
            var avatarEl = document.getElementById('end-podium-' + place + '-avatar');

            // #1402-B8: textContent already neutralizes markup, so feeding it
            // escapeHtml() output double-escapes — a name like "A&B" rendered
            // as "A&amp;B" on the podium. Assign the raw name directly.
            if (nameEl) nameEl.textContent = player ? player.name : '---';
            if (scoreEl) scoreEl.textContent = player ? player.score : '0';
            if (avatarEl) {
                var nm = player ? player.name : '';
                avatarEl.textContent = nm ? nm.trim().charAt(0).toUpperCase() : '';
                avatarEl.style.background = nm ? endAvatarGradient(nm) : 'transparent';
            }
        });

        // Header meta — rounds + players (icon-led so it needs no translation).
        var stats = data.game_stats || {};
        var roundsEl = document.getElementById('end-meta-rounds');
        var playersEl = document.getElementById('end-meta-players');
        if (roundsEl) roundsEl.textContent = '🎵 ' + (stats.total_rounds != null ? stats.total_rounds : leaderboard.length && data.round || 0);
        if (playersEl) playersEl.textContent = '👥 ' + (stats.total_players != null ? stats.total_players : leaderboard.length);

        // Render stats comparison (Story 14.4)
        renderStatsComparison(data.game_performance);

        // Render superlatives / fun awards (Story 15.2)
        renderSuperlatives(data.superlatives);

        // Issue #75: Game highlights reel (data was always sent, never shown).
        renderHighlights(data.highlights);

        // Story 14.5 (AC3, AC7): Trigger winner confetti on dashboard
        // H2 fix: Only trigger if there's a valid winner with score > 0
        var winner = leaderboard.find(function(p) { return p.rank === 1; });
        if (winner && winner.score > 0) {
            triggerConfetti('winner');
        }

        // Full standings panel — the players BELOW the podium (rank 4+). The
        // podium already celebrates the top 3; this completes the ranking.
        // Fallback to the whole board for small games (<=3 players) so the
        // panel is never empty.
        var container = document.getElementById('end-leaderboard');
        if (container) {
            var rest = leaderboard.filter(function(e) { return e.rank > 3; });
            var rows = rest.length ? rest : leaderboard;
            var html = '';
            rows.forEach(function(entry) {
                var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
                var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
                var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

                // Issue #827: Sudden-Death — eliminated players render dimmed with
                // a 💀 prefix. Reuses .leaderboard-entry--disconnected for the dim.
                var eliminatedClass = entry.eliminated ? 'leaderboard-entry--disconnected' : '';
                var skullPrefix = entry.eliminated ? '💀 ' : '';

                html += '<div class="leaderboard-entry ' + rankClass + ' ' + disconnectedClass + ' ' + eliminatedClass + '">' +
                    '<span class="entry-rank">#' + entry.rank + '</span>' +
                    '<span class="entry-name">' + skullPrefix + utils.escapeHtml(entry.name) + awayBadge + '</span>' +
                    '<span class="entry-score">' + entry.score + '</span>' +
                '</div>';
            });

            container.innerHTML = html;
        }
    }

    /**
     * Deterministic avatar gradient from a player name (matches the player
     * reveal standings palette).
     * @param {string} name
     * @returns {string} CSS gradient
     */
    function endAvatarGradient(name) {
        var palettes = [
            ['#ff2d6a', '#ff6600'], ['#00f5ff', '#7a5cff'], ['#39ff14', '#00f5ff'],
            ['#ff6600', '#ff0040'], ['#7a5cff', '#b3b3c2'], ['#ff2d6a', '#7a5cff']
        ];
        var h = 0;
        for (var i = 0; i < name.length; i++) { h = (h * 31 + name.charCodeAt(i)) >>> 0; }
        var p = palettes[h % palettes.length];
        return 'linear-gradient(140deg,' + p[0] + ',' + p[1] + ')';
    }

    /**
     * Render the game highlights reel (Issue #75). The server always sent
     * data.highlights (top ~3 moments) but nothing rendered it on the TV.
     * Each highlight: { type, round, player, emoji, description (i18n key),
     * description_params }. Localised via the "highlights.<description>" key.
     * @param {Array|null} highlights
     */
    function renderHighlights(highlights) {
        var container = document.getElementById('end-highlights');
        if (!container) return;
        if (!highlights || highlights.length === 0) {
            container.innerHTML = '';
            container.classList.add('hidden');
            return;
        }
        // Per-type accent for the card's left border.
        var accents = {
            exact_match: '#00f5ff', streak: '#ff6600', bet_win: '#39ff14',
            heartbreaker: '#ff2d6a', speed_record: '#00f5ff', comeback: '#39ff14',
            photo_finish: '#ffd34d'
        };
        var html = '';
        highlights.forEach(function(h, index) {
            var accent = accents[h.type] || '#ff2d6a';
            var text = utils.t('highlights.' + h.description, h.description_params || {}) || '';
            var roundBadge = h.round
                ? '<div class="hcard-round">' + (utils.t('game.roundLabel') || 'Round') + ' ' + h.round + '</div>'
                : '';
            html += '<div class="hcard" style="border-left-color:' + accent + ';animation-delay:' + (index * 0.12) + 's">' +
                '<div class="hcard-icon" aria-hidden="true">' + (h.emoji || '✨') + '</div>' +
                '<div class="hcard-body">' +
                    '<div class="hcard-text">' + utils.escapeHtml(text) + '</div>' +
                    roundBadge +
                '</div>' +
            '</div>';
        });
        container.innerHTML = html;
        container.classList.remove('hidden');
    }

    /**
     * Render stats comparison for end screen (Story 14.4)
     * @param {Object|null} performance - Game performance data from state
     */
    function renderStatsComparison(performance) {
        var container = document.getElementById('end-stats-comparison');
        if (!container) return;

        // Hide if no performance data
        if (!performance) {
            container.classList.add('hidden');
            return;
        }

        var iconEl = container.querySelector('.stats-comparison-icon');
        var textEl = container.querySelector('.stats-comparison-text');

        // Build comparison text based on performance
        var icon = '';
        var text = '';
        var cssClass = 'stats-comparison';

        if (performance.is_first_game) {
            icon = '🌟';
            text = 'First game recorded! Avg: ' + performance.current_avg.toFixed(1) + ' pts/round';
            cssClass += ' stats-comparison--first';
        } else if (performance.is_new_record) {
            icon = '🏆';
            text = 'NEW RECORD! ' + performance.current_avg.toFixed(1) + ' pts/round (prev: ' + performance.all_time_avg.toFixed(1) + ')';
            cssClass += ' stats-comparison--record';
        } else if (performance.is_above_average) {
            icon = '📈';
            text = performance.current_avg.toFixed(1) + ' pts/round (+' + performance.difference.toFixed(1) + ' vs all-time avg)';
            cssClass += ' stats-comparison--above';
        } else {
            icon = '📊';
            text = performance.current_avg.toFixed(1) + ' pts/round (' + performance.difference.toFixed(1) + ' vs all-time avg)';
            cssClass += ' stats-comparison--below';
        }

        container.className = cssClass;
        if (iconEl) iconEl.textContent = icon;
        if (textEl) textEl.textContent = text;
    }

    /**
     * Render superlatives / fun awards (Story 15.2)
     * @param {Array|null} superlatives - Array of award objects from state
     */
    function renderSuperlatives(superlatives) {
        var container = document.getElementById('superlatives-container');
        if (!container) return;

        // Hide if no superlatives
        if (!superlatives || superlatives.length === 0) {
            container.classList.add('hidden');
            return;
        }

        var html = '';
        superlatives.forEach(function(award, index) {
            var valueText = '';
            switch (award.value_label) {
                case 'avg_time':
                    valueText = award.value + 's ' + utils.t('superlatives.avgTime');
                    break;
                case 'streak':
                    valueText = award.value + ' ' + utils.t('superlatives.streak');
                    break;
                case 'bets':
                    valueText = award.value + ' ' + utils.t('superlatives.bets');
                    break;
                case 'points':
                    valueText = award.value + ' ' + utils.t('superlatives.points');
                    break;
                case 'close_guesses':
                    valueText = award.value + ' ' + utils.t('superlatives.closeGuesses');
                    break;
                default:
                    valueText = award.value;
            }

            html += '<div class="superlative-card superlative-card--' + award.id + '" style="animation-delay: ' + (index * 0.2) + 's">' +
                '<div class="superlative-emoji">' + award.emoji + '</div>' +
                '<div class="superlative-title">' + utils.t('superlatives.' + award.title) + '</div>' +
                '<div class="superlative-player">' + utils.escapeHtml(award.player_name) + '</div>' +
                '<div class="superlative-value">' + valueText + '</div>' +
            '</div>';
        });

        container.innerHTML = html;
        container.classList.remove('hidden');
    }

    // ============================================
    // Sudden Death (Issue #827)
    // ============================================

    /**
     * Issue #827: full-bleed "OUT" takeover (design S4-C). Called on REVEAL.
     * When sudden_death_mode is on and the state carries a non-empty
     * eliminated_this_round, flash the overlay with the eliminated name(s) for
     * ~2.5s. Deduped per (round, names) so re-renders/re-broadcasts of the same
     * REVEAL don't re-trigger it. This is a TV display — the overlay auto-hides
     * so it never permanently blocks the underlying reveal.
     * @param {Object} data - REVEAL state data
     */
    function renderSuddenDeathOut(data) {
        var overlay = document.getElementById('sd-out-overlay');
        if (!overlay) return;

        var names = data.sudden_death_mode ? (data.eliminated_this_round || []) : [];
        if (!names.length) {
            // No elimination this round — make sure the key resets so a future
            // elimination with the same names (different round) still fires.
            return;
        }

        var key = (data.round || 0) + ':' + names.join(',');
        if (key === sdLastOutKey) return;  // already shown for this elimination
        sdLastOutKey = key;

        // Big word uses the localized game.out (uppercased).
        var wordEl = overlay.querySelector('.sd-out__word');
        if (wordEl) wordEl.textContent = (utils.t('game.out', 'OUT') || 'OUT').toUpperCase();

        var nameEl = document.getElementById('sd-out-name');
        if (nameEl) nameEl.textContent = names.join(', ');

        overlay.classList.add('show');
        if (sdOutTimer) clearTimeout(sdOutTimer);
        sdOutTimer = setTimeout(function() {
            overlay.classList.remove('show');
            sdOutTimer = null;
        }, 2500);
    }

    /**
     * Issue #827: Sudden-Death FINAL banner (design S5-C). Shown in the
     * PLAYING and REVEAL chip strips when exactly 2 players are still in the
     * game (non-eliminated) AND sudden_death_mode is on. Hidden otherwise.
     * @param {Object} data - State data
     * @param {string} bannerId - id of the banner element for this phase
     */
    function renderSuddenDeathFinalBanner(data, bannerId) {
        var banner = document.getElementById(bannerId);
        if (!banner) return;

        var players = data.players || [];
        var alive = players.filter(function(p) { return !p.eliminated; });

        if (data.sudden_death_mode && alive.length === 2) {
            banner.textContent = '💀 ' + utils.t('game.finalShowdown', 'FINAL — SUDDEN DEATH');
            banner.classList.remove('hidden');
        } else {
            banner.classList.add('hidden');
        }
    }

    /**
     * Issue #827: END "Last One Standing" hero (design S6-C). Shown above the
     * podium/superlatives only in Sudden Death mode. The survivor is the single
     * non-eliminated entry in the final leaderboard, or — failing that — the
     * player_name from the last_one_standing superlative.
     * @param {Object} data - END state data
     */
    function renderSuddenDeathLastStanding(data) {
        var hero = document.getElementById('sd-last-standing');
        if (!hero) return;

        if (!data.sudden_death_mode) {
            hero.classList.add('hidden');
            return;
        }

        var leaderboard = data.leaderboard || [];
        var survivors = leaderboard.filter(function(e) { return !e.eliminated; });
        var winner = survivors.length ? survivors[0].name : null;

        // Fallback to the last_one_standing superlative's player_name.
        if (!winner && data.superlatives) {
            var award = data.superlatives.find(function(a) { return a.id === 'last_one_standing'; });
            if (award) winner = award.player_name;
        }

        if (!winner) {
            hero.classList.add('hidden');
            return;
        }

        var headlineEl = hero.querySelector('.sd-last-standing__headline');
        if (headlineEl) headlineEl.textContent = utils.t('game.lastOneStanding', 'Last One Standing');

        var winnerEl = document.getElementById('sd-last-standing-winner');
        if (winnerEl) winnerEl.textContent = winner;

        hero.classList.remove('hidden');
    }

    // ============================================
    // Confetti System (Story 14.5 - AC7)
    // ============================================

    // Track active animations for cleanup (M3 fix)
    var confettiAnimationId = null;
    var confettiIntervalId = null;

    /**
     * Trigger confetti celebration animation (Story 14.5)
     * Uses canvas-confetti library for various celebration types
     * @param {string} type - 'exact', 'record', 'winner', or 'perfect'
     */
    function triggerConfetti(type) {
        // AC5: Respect accessibility preference
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return;
        }

        // Check if confetti library is loaded
        if (typeof confetti === 'undefined') {
            console.warn('[Dashboard Confetti] Library not loaded');
            return;
        }

        // Stop any existing animation before starting new one (M3 fix)
        stopConfetti();

        type = type || 'exact';

        switch (type) {
            case 'exact':
                // AC1: Gold burst for exact guess, 2 seconds (H1 fix - enforced duration)
                var exactDuration = 2 * 1000;
                var exactEnd = Date.now() + exactDuration;
                (function exactFrame() {
                    confetti({
                        particleCount: 15,
                        spread: 70,
                        origin: { y: 0.6 },
                        colors: ['#FFD700', '#FFA500', '#FFEC8B']
                    });
                    if (Date.now() < exactEnd) {
                        confettiAnimationId = requestAnimationFrame(exactFrame);
                    }
                }());
                break;

            case 'record':
                // AC2: Rainbow shower for new record, 3 seconds (H1 fix - enforced duration)
                var recordDuration = 3 * 1000;
                var recordEnd = Date.now() + recordDuration;
                (function recordFrame() {
                    confetti({
                        particleCount: 10,
                        spread: 180,
                        origin: { y: 0.3, x: Math.random() },
                        colors: ['#ff0000', '#ff7f00', '#ffff00', '#00ff00', '#0000ff', '#8b00ff']
                    });
                    if (Date.now() < recordEnd) {
                        confettiAnimationId = requestAnimationFrame(recordFrame);
                    }
                }());
                break;

            case 'winner':
                // AC3: Dual-side fireworks for winner, 4 seconds
                var winnerDuration = 4 * 1000;
                var winnerEnd = Date.now() + winnerDuration;
                (function winnerFrame() {
                    confetti({
                        particleCount: 10,
                        angle: 60,
                        spread: 55,
                        origin: { x: 0 },
                        colors: ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00']
                    });
                    confetti({
                        particleCount: 10,
                        angle: 120,
                        spread: 55,
                        origin: { x: 1 },
                        colors: ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00']
                    });
                    if (Date.now() < winnerEnd) {
                        confettiAnimationId = requestAnimationFrame(winnerFrame);
                    }
                }());
                break;

            case 'perfect':
                // AC4: Epic celebration for perfect game, 5 seconds
                var perfectDuration = 5 * 1000;
                var perfectEnd = Date.now() + perfectDuration;

                // M4 fix: Use setInterval for reliable center bursts
                confettiIntervalId = setInterval(function() {
                    confetti({
                        particleCount: 30,
                        spread: 100,
                        origin: { y: 0.6 },
                        colors: ['#FFD700', '#FFA500', '#FFEC8B']
                    });
                }, 500);

                // Clear interval when duration ends
                setTimeout(function() {
                    if (confettiIntervalId) {
                        clearInterval(confettiIntervalId);
                        confettiIntervalId = null;
                    }
                }, perfectDuration);

                (function perfectFrame() {
                    confetti({
                        particleCount: 7,
                        angle: 60,
                        spread: 55,
                        origin: { x: 0 },
                        colors: ['#FFD700', '#ff2d6a', '#00f5ff', '#00ff88']
                    });
                    confetti({
                        particleCount: 7,
                        angle: 120,
                        spread: 55,
                        origin: { x: 1 },
                        colors: ['#FFD700', '#ff2d6a', '#00f5ff', '#00ff88']
                    });
                    if (Date.now() < perfectEnd) {
                        confettiAnimationId = requestAnimationFrame(perfectFrame);
                    }
                }());
                break;

            default:
                console.warn('[Dashboard Confetti] Unknown type:', type);
        }
    }

    /**
     * Stop any ongoing confetti animations (M3 fix - proper cleanup)
     */
    function stopConfetti() {
        if (confettiAnimationId) {
            cancelAnimationFrame(confettiAnimationId);
            confettiAnimationId = null;
        }
        if (confettiIntervalId) {
            clearInterval(confettiIntervalId);
            confettiIntervalId = null;
        }
        if (typeof confetti !== 'undefined' && confetti.reset) {
            confetti.reset();
        }
    }

    // ============================================
    // Live Reactions (Story 18.9)
    // ============================================

    /**
     * Show a floating reaction bubble on the dashboard
     * @param {string} playerName - Name of the player who reacted
     * @param {string} emoji - The emoji reaction
     */
    function showFloatingReaction(playerName, emoji) {
        var container = document.getElementById('reaction-container');
        if (!container) return;

        var bubble = document.createElement('div');
        bubble.className = 'reaction-bubble';
        bubble.textContent = playerName + ' ' + emoji;

        // Random horizontal position (20% to 80% of screen width)
        bubble.style.left = (20 + Math.random() * 60) + '%';

        container.appendChild(bubble);

        // Remove after animation completes (3s)
        setTimeout(function() {
            bubble.remove();
        }, 3000);
    }

    // ============================================
    // Initialization
    // ============================================

    /**
     * Initialize dashboard
     */
    async function init() {
        debug('[Dashboard] Initializing...');
        // Initialize i18n (Story 12.5)
        // Guard clause: wait for BeatifyI18n in case fallback script is loading
        var i18nAvailable = await utils.waitForI18n();
        if (!i18nAvailable) {
            console.error('[Dashboard] BeatifyI18n module failed to load - UI will use fallback text');
        } else {
            await BeatifyI18n.init();
            BeatifyI18n.initPageTranslations();
        }
        connectWebSocket();
        _initWakeBanner();  // #1285: wire the activation banner's tap handlers
        // #1122: keep TV/monitor display awake. On a passive iOS display the
        // native lock is gesture-gated and won't engage here, so surface the
        // #1285 banner that offers a one-tap re-try inside a trusted gesture.
        var locked = await requestWakeLock();
        if (!locked) _showWakeBanner();
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // ============================================
    // Service Worker Registration (Story 18.5)
    // ============================================

    /**
     * Register service worker for asset caching
     */
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function() {
            navigator.serviceWorker.register('/beatify/sw.js', {
                scope: '/beatify/'
            }).then(function(registration) {
                debug('[Dashboard] SW registered:', registration.scope);
            }).catch(function(error) {
                console.warn('[Dashboard] SW registration failed:', error);
            });
        });
    }

})();
