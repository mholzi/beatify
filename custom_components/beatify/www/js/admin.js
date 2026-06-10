/**
 * Beatify Admin Page
 * Vanilla JS - no frameworks
 *
 * #1279 Schritt 2/6: admin.js is now an ES module (`<script type="module">`).
 * Pure helpers live in ./admin/util.js; their previous top-level globals are
 * re-exposed on `window` below (compat shim) for classic scripts that still
 * read them. Token helpers read the live `adminState.currentGame` via a resolver
 * registered once at module init.
 */

// #1279 Schritt 5/6: centralized mutable setup-/game-state. Previously the ~24
// setup `let`s (incl. `currentGame`) lived as top-level bindings here. They are
// now a single shared `adminState` object exported from ./admin/state.js so the
// (read-only live-binding) module boundary doesn't block cross-module writes —
// the enabler for the deferred setup-section split (step 4b). Reads are
// `adminState.x`, writes `adminState.x = …`. Pure infra handles (timers,
// wake-lock, `_homeStartBtnHTML`, `rematchInProgress`) stay as admin.js `let`s.
import { adminState } from './admin/state.js';

// #1279 step 4b: shared constants (localStorage keys) extracted so both this
// core and the setup-section modules import the same literals.
import { STORAGE_LAST_PLAYER, STORAGE_GAME_SETTINGS } from './admin/constants.js';

import {
    setCurrentGameResolver,
    _getAdminToken,
    _setAdminToken,
    _adminHeaders,
    groupPlayersByPlatform,
    REQUEST_STATUS_LABELS,
    buildRequestRowHtml,
    escapeHtml,
} from './admin/util.js';

// #1279 Schritt 3/6: REST/WS hub layer. The admin WS connection lifecycle +
// message dispatch live in ./admin/api.js; admin.js keeps the view/game-state
// code and registers its callbacks + state setters once via initAdminApi()
// (below, after the state declarations). The ~18 sites that used to poke
// `adminWs` directly now call the exported accessors.
import {
    initAdminApi,
    connectAdminWebSocket,
    sendAdminCommand,
    isAdminWsOpen,
    sendAdminWs,
    closeAdminWs,
    resetReconnectAttempts,
} from './admin/api.js';

// #1279 Schritt 4/6: pure spectator-view render helpers. These are fully
// data-in / DOM-out (no admin-private state, no cross-refs) so they lift out
// cleanly into a unit-testable module. No window shims needed: every caller is
// inside admin.js (verified) and none of these were ever global.
import {
    renderAdminSubmissionDots,
    renderAdminLeaderboard,
    renderAdminResultCards,
    renderAdminChallengeOptions,
    _providerDisplayName,
} from './admin/sections/render-helpers.js';

// #1279 Schritt 4b/6: the four setup-sections (playlists, media-players,
// game-settings) now share the centralized `adminState` object (step 5), so
// they lift out into their own ES modules and read/write state directly — no DI
// closures. The start-game/lobby core (startGame, loadStatus, BeatifyHome) stays
// here and imports the section functions it drives. Circular-import-safe: every
// cross-module call is event/runtime-driven, none run at module init.
//
// playlists.js: list render + selection + tag-filter, plus the shared
// selection-summary / start-button-validation helpers. The intra-section
// callees (handlePlaylistToggle, filter-bar render, etc.) are wired up inside
// the module; admin.js core only drives the entry points below.
// `clearPlaylistFilters` is shimmed onto `window` (below) for the inline
// `onclick=` in the HTML the module generates.
import {
    renderPlaylists,
    clearPlaylistFilters,
    updateStartButtonState,
} from './admin/sections/playlists.js';

// media-players.js: speaker list render + radio-selection + platform-capability
// gate (updateProviderOptions toggles the music-service provider chips). No
// window shim: the no-players empty state's inline onclick="loadStatus()" resolves
// to the loadStatus core fn already shimmed onto window below. admin.js core
// drives renderMediaPlayers (from loadStatus) + handleMediaPlayerSelect (from
// BeatifyHome.hydrateFromStorage); the rest are intra-section.
import {
    renderMediaPlayers,
    handleMediaPlayerSelect,
} from './admin/sections/media-players.js';

// game-settings.js: chip/toggle wiring (language, timer, difficulty, bonus
// flags + the music-service provider chips), the localStorage load/save
// round-trip, the summary badge, and the Title&Artist-mode UI sync. admin.js
// core calls setupGameSettings() + loadSavedSettings() at init; the rest are
// intra-section. `loadSavedSettings` is shimmed onto window below for wizard.js.
import {
    setupGameSettings,
    loadSavedSettings,
} from './admin/sections/game-settings.js';

// Token helpers in util.js need the live `currentGame`. The resolver reads it
// off the shared `adminState` object (#1279 step 5), so it stays in sync across
// every `adminState.currentGame = …` without touching each assignment site.
setCurrentGameResolver(() => adminState.currentGame);

// Compat shim (#1279 step 2): admin.js is now a module, so its top-level
// helper declarations are no longer global. Classic scripts loaded after this
// module (party-lights.min.js, tts-settings.js) and module siblings that read
// these by name keep working by reading them off `window`. These helpers were
// implicitly global before the module migration; the shim makes that explicit.
window.escapeHtml = escapeHtml;
window.groupPlayersByPlatform = groupPlayersByPlatform;
window.buildRequestRowHtml = buildRequestRowHtml;
window._getAdminToken = _getAdminToken;
window._setAdminToken = _setAdminToken;
window._adminHeaders = _adminHeaders;
// #1279 step 4b: playlists.js generates HTML with inline onclick="clearPlaylistFilters()"
// (empty-filter "Clear Filters" button + active-filter "Clear" link), so the
// function must stay reachable as a window global.
window.clearPlaylistFilters = clearPlaylistFilters;

// Screen Wake Lock (#622, #1122)
// Layer 1: navigator.wakeLock — Safari ≥16.4, Chrome, Edge, Firefox.
// Layer 2: NoSleep.js silent-video fallback — iOS HA Companion WKWebView,
//          older Safari, anywhere Layer 1 is unavailable or rejected.
// NoSleep dependency loaded via /beatify/static/js/vendor/no-sleep.min.js
// in admin.html before this script runs.
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

async function _requestWakeLock() {
    if ('wakeLock' in navigator) {
        try {
            _wakeLock = await navigator.wakeLock.request('screen');
            _wakeLock.addEventListener('release', function() {
                console.debug('[BeatifyWakeLock] Layer 1 released by browser');
                _wakeLock = null;
            });
            console.debug('[BeatifyWakeLock] Layer 1 (native wakeLock) acquired');
            return;
        } catch (err) {
            console.debug('[BeatifyWakeLock] Layer 1 request failed:', err, '— trying Layer 2');
        }
    } else {
        console.debug('[BeatifyWakeLock] Layer 1 unavailable — using Layer 2');
    }
    var ns = _ensureNoSleep();
    if (!ns) {
        console.debug('[BeatifyWakeLock] Layer 2 unavailable (NoSleep vendor not loaded)');
        return;
    }
    if (_noSleepActive) return;
    try {
        var p = ns.enable();
        _noSleepActive = true;
        if (p && typeof p.catch === 'function') {
            p.catch(function(err) {
                console.debug('[BeatifyWakeLock] Layer 2 enable promise rejected:', err);
            });
        }
        console.debug('[BeatifyWakeLock] Layer 2 (NoSleep video) enabled');
    } catch (err) {
        console.debug('[BeatifyWakeLock] Layer 2 enable failed:', err);
        _noSleepActive = false;
    }
}

function _releaseWakeLock() {
    if (_wakeLock) {
        try { _wakeLock.release(); } catch (e) { /* may already be released */ }
        _wakeLock = null;
    }
    if (_noSleepActive && _noSleep) {
        try { _noSleep.disable(); } catch (e) { /* defensive */ }
        _noSleepActive = false;
        console.debug('[BeatifyWakeLock] Layer 2 (NoSleep) disabled');
    }
}

// #647: Re-acquire wake lock when admin tab becomes visible during an active game
// #648: Reconnect admin WS on tab return (e.g. after screen sleep)
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible' && adminState.currentGame && adminState.currentGame.phase !== 'END') {
        _requestWakeLock();
        // Reconnect WS if it died while tab was hidden
        if (!isAdminWsOpen()) {
            resetReconnectAttempts(); // reset backoff on user-initiated return
            connectAdminWebSocket();
        }
    }
});

// Module-level state
// #1279 step 5: the setup-/game-state (playlists, media-player, game settings,
// bonus flags, view, currentGame, lobby/admin-as-player) now lives in the shared
// `adminState` object (./admin/state.js) — see the import at the top. Only the
// admin-private infra handles below stay as plain `let`s (timers, the
// "Start game" button HTML stash); they never cross a module boundary.

// Lobby polling timer handle (Story 16.8)
let lobbyPollingInterval = null;

// #949: the home "Start game" button's pre-"Starting…" HTML, stashed so a WS
// start-failure error (MEDIA_PLAYER_UNAVAILABLE etc.) can un-stick the button.
let _homeStartBtnHTML = null;
let countdownInterval = null;

// #1279 step 3: register admin.js's live state readers, setters and view
// callbacks with the WS hub (./admin/api.js). Same DI pattern as the step-2
// `setCurrentGameResolver`: the hub never owns admin's mutable state — it reads
// it through these closures and writes via the setters. Functions referenced
// here (handleAdminStateUpdate, startLobbyPolling, …) are declared later but
// are only ever *invoked* at runtime, so hoisting makes this init-safe.
initAdminApi({
    debug: (...args) => debug(...args),
    getCurrentGame: () => adminState.currentGame,
    getCurrentView: () => adminState.currentView,
    getAdminPlayerName: () => adminState.adminPlayerName,
    setIsPlaying: (v) => { adminState.isPlaying = v; },
    setAdminPlayerName: (v) => { adminState.adminPlayerName = v; },
    setAdminSessionId: (v) => { adminState.adminSessionId = v; },
    handleAdminStateUpdate: (data) => handleAdminStateUpdate(data),
    startLobbyPolling: () => startLobbyPolling(),
    stopLobbyPolling: () => stopLobbyPolling(),
    showError: (msg) => showError(msg),
    resetHomeStartButton: () => resetHomeStartButton(),
});
// #1048: REVEAL auto-advance countdown on the sticky Next button
let revealAdvanceInterval = null;
let revealAdvanceOrigIcon = null;

// LocalStorage keys + PLATFORM_LABELS now live in ./admin/constants.js (#1279
// step 4b) so the setup-section modules and this core share the same literals.
// STORAGE keys are still read here (BeatifyHome hydrate, force-reset cleanup);
// PLATFORM_LABELS moved entirely into media-players.js with its renderer.

// Setup sections to hide/show as a group
const setupSections = ['media-players', 'music-service', 'playlists', 'game-settings', 'admin-actions', 'my-requests', 'party-lights', 'tts-settings', 'ha-entities'];

// Alias BeatifyUtils for convenience
const utils = window.BeatifyUtils || {};
const debug = utils.debug || function() {};

document.addEventListener('DOMContentLoaded', async () => {
    // #998: the admin console requires a logged-in Home Assistant user.
    // If not authenticated this redirects to HA login and never resolves,
    // so nothing below runs for an unauthenticated visitor.
    await BeatifyAuth.init({ requireAuth: true });

    // Initialize i18n based on browser language (Story 12.4)
    // Guard clause: wait for BeatifyI18n in case fallback script is loading
    const i18nAvailable = await utils.waitForI18n();
    if (!i18nAvailable) {
        console.error('[Beatify] BeatifyI18n module failed to load - UI will use fallback text');
    } else {
        await BeatifyI18n.init();
        BeatifyI18n.initPageTranslations();
        adminState.selectedLanguage = BeatifyI18n.getLanguage();
    }
    // Set initial language chip active state
    document.querySelectorAll('.chip[data-lang]').forEach(c => {
        c.classList.toggle('chip--active', c.dataset.lang === adminState.selectedLanguage);
    });

    // First-run wizard — initializes after i18n is ready (DESIGN.md ## Patterns)
    if (window.BeatifyWizard && typeof window.BeatifyWizard.init === 'function') {
        try { await window.BeatifyWizard.init(); } catch (e) { console.warn('[Beatify] wizard init failed:', e); }
    }

    // Expose loadStatus so wizard.js can ask admin to refresh after completion
    window.loadStatus = loadStatus;
    // Expose loadSavedSettings so wizard.js can re-sync the admin's in-memory game
    // settings (mode, difficulty, bonuses, language, playlists) from localStorage
    // after the wizard persists them. The admin only reads beatify_game_settings
    // once at page-init — without this refresh, start-game keeps the stale values
    // and ignores the wizard's choices, e.g. Title & Artist mode (#1180).
    window.loadSavedSettings = loadSavedSettings;

    // Home view — shown when setup is complete and no game is active (post-wizard landing)
    window.BeatifyHome = {
        enter() {
            document.body.classList.add('home-mode');
            const v = document.getElementById('home-view');
            if (v) v.classList.remove('hidden');
            this.refresh();
            // Two paths: configured user → auto-create LOBBY + show QR. Unconfigured
            // user → show the setup prompt hero and wait for them to tap Start setup.
            if (this.isConfigured()) {
                this.setMode('configured');
                // The wizard writes selections to localStorage but never touches the
                // legacy admin globals (adminState.selectedMediaPlayer / adminState.selectedPlaylists).
                // Hydrate them so startGame() has the data it needs to POST.
                this.hydrateFromStorage();
                if (adminState.currentGame && adminState.currentGame.phase === 'LOBBY' && adminState.currentGame.join_url) {
                    this.renderSession(adminState.currentGame);
                } else {
                    this.startSession();
                }
            } else {
                this.setMode('setup');
            }
        },
        // Bridge: read wizard-saved settings from localStorage into admin's module
        // globals. Safe to call repeatedly; only fills gaps left by the legacy
        // click-driven setup flow.
        hydrateFromStorage() {
            try {
                const lastPlayerId = localStorage.getItem(STORAGE_LAST_PLAYER);
                if (lastPlayerId && (!adminState.selectedMediaPlayer || !adminState.selectedMediaPlayer.entityId)) {
                    const radio = document.querySelector(
                        `.media-player-radio[data-entity-id="${CSS.escape(lastPlayerId)}"]`
                    );
                    if (radio) {
                        radio.checked = true;
                        handleMediaPlayerSelect(radio, true);
                    } else {
                        // Players list not rendered yet — populate a minimal stub
                        // so startGame() has an entityId. Capability flags default
                        // to false; backend will validate.
                        adminState.selectedMediaPlayer = { entityId: lastPlayerId, state: 'unknown', platform: 'unknown' };
                    }
                }
                const raw = localStorage.getItem(STORAGE_GAME_SETTINGS);
                if (raw) {
                    const s = JSON.parse(raw);
                    if (s.language) adminState.selectedLanguage = s.language;
                    if (s.duration) adminState.selectedDuration = s.duration;
                    if (typeof s.revealAutoAdvance === 'number') adminState.revealAutoAdvance = s.revealAutoAdvance;
                    if (s.difficulty) adminState.selectedDifficulty = s.difficulty;
                    if (s.provider) adminState.selectedProvider = s.provider;
                    if (typeof s.artistChallenge === 'boolean') adminState.artistChallengeEnabled = s.artistChallenge;
                    if (typeof s.movieQuiz === 'boolean') adminState.movieQuizEnabled = s.movieQuiz;
                    if (typeof s.introMode === 'boolean') adminState.introModeEnabled = s.introMode;
                    if (typeof s.closestWinsMode === 'boolean') adminState.closestWinsModeEnabled = s.closestWinsMode;
                    const wizPaths = Array.isArray(s.selectedPlaylists)
                        ? s.selectedPlaylists.map((p) => (typeof p === 'string' ? p : p.path)).filter(Boolean)
                        : [];
                    if (wizPaths.length && adminState.selectedPlaylists.length === 0) {
                        adminState.selectedPlaylists = wizPaths.map((path) => {
                            const meta = (adminState.playlistData || []).find((d) => d.path === path);
                            return { path, songCount: (meta && (meta.song_count || meta.songCount)) || 0 };
                        });
                    }
                }
            } catch (e) { console.warn('[Beatify] hydrateFromStorage failed:', e); }
        },
        // Swap the hero card + CTA bar contents based on whether the user has completed setup.
        setMode(mode) {
            const configured = mode === 'configured';
            document.getElementById('home-hero-configured')?.classList.toggle('hidden', !configured);
            document.getElementById('home-hero-setup')?.classList.toggle('hidden', configured);
            // Configured-mode CTAs
            document.getElementById('home-edit-setup')?.classList.toggle('hidden', !configured);
            document.getElementById('home-start-game')?.classList.toggle('hidden', !configured);
            // Unconfigured-mode CTA
            document.getElementById('home-start-setup')?.classList.toggle('hidden', configured);
            // Utility row — hide everything when unconfigured (no session, no QR, no lobby)
            if (!configured) {
                document.getElementById('home-dashboard-url')?.classList.add('hidden');
                document.getElementById('home-join-player')?.classList.add('hidden');
                document.getElementById('home-end-game')?.classList.add('hidden');
                // Meta + players are hidden too — no game state to summarize
                const meta = document.getElementById('home-meta');
                if (meta) meta.textContent = '';
                const players = document.getElementById('home-players');
                if (players) players.innerHTML = '';
            }
        },
        async startSession() {
            const loading = document.getElementById('home-qr-loading');
            if (loading) loading.classList.remove('hidden');
            try {
                // Guard: startGame() reads adminState.selectedPlaylists/adminState.selectedMediaPlayer from module globals.
                // Those globals are populated by loadStatus() on page load, which runs before enter().
                await startGame();
            } catch (err) {
                console.warn('[Beatify] Home auto-start failed:', err);
            }
        },
        renderSession(gameData) {
            const loading = document.getElementById('home-qr-loading');
            if (loading) loading.classList.add('hidden');

            // Render the actual QR using the shared QRCode library.
            const qrContainer = document.getElementById('home-qr-code');
            if (qrContainer && gameData.join_url && typeof QRCode !== 'undefined') {
                if (qrContainer.dataset.url !== gameData.join_url) {
                    qrContainer.innerHTML = '';
                    new QRCode(qrContainer, {
                        text: gameData.join_url,
                        width: 180,
                        height: 180,
                        colorDark: '#0a0a12',
                        colorLight: '#ffffff',
                        correctLevel: QRCode.CorrectLevel.M,
                    });
                    qrContainer.dataset.url = gameData.join_url;
                    qrContainer.setAttribute('role', 'button');
                    qrContainer.setAttribute('tabindex', '0');
                    qrContainer.style.cursor = 'pointer';
                }
                // Share the cached URL with the existing openQRModal() so tap-to-enlarge works
                adminState.cachedQRUrl = gameData.join_url;
            }
            const urlEl = document.getElementById('home-join-url');
            if (urlEl && gameData.join_url) urlEl.textContent = gameData.join_url;

            // "Open TV Dashboard" link — point at the spectator dashboard.
            // Prefer a server-provided URL; otherwise derive it from join_url:
            // the dashboard lives at /beatify/dashboard on the same host and
            // needs no game parameter (it observes whatever game is live).
            const castEl = document.getElementById('home-dashboard-url');
            if (castEl) {
                let dashboardUrl = gameData.dashboard_url;
                if (!dashboardUrl && gameData.join_url) {
                    dashboardUrl =
                        gameData.join_url.split('/beatify/play')[0] +
                        '/beatify/dashboard';
                }
                if (dashboardUrl) {
                    castEl.href = dashboardUrl;
                    castEl.classList.remove('hidden');
                } else {
                    castEl.classList.add('hidden');
                }
            }

            // End game is hidden while the game hasn't started (LOBBY) — ending a
            // lobby that nobody has joined is not a meaningful admin action. We only
            // want it for the rare case where admin lands on home-view while a
            // PLAYING session is already in flight (e.g. after a reload).
            const hasLobby = gameData.phase === 'LOBBY' && !!gameData.join_url;
            const isPlayingPhase = gameData.phase && gameData.phase !== 'LOBBY' && gameData.phase !== 'END';
            document.getElementById('home-end-game')?.classList.toggle('hidden', !isPlayingPhase);

            // Join-as-player: prominent next step — shown until the admin has
            // joined THIS game. Visibility is driven purely by authoritative
            // state: the current game's player list (adminInPlayers) and the
            // live adminState.isPlaying flag.
            //
            // It used to also consult sessionStorage 'beatify_admin_name', but
            // that marker is set on the admin's first-ever join and never
            // cleared per game — so once the host had joined any game, the
            // button vanished for every later game in the same tab, even a
            // brand-new empty lobby they had not joined. adminInPlayers already
            // answers "did the admin join THIS game" from the server's list.
            const adminInPlayers = (gameData.players || []).some((p) => p.is_admin);
            const canJoin = hasLobby && !adminInPlayers && !adminState.isPlaying;
            document.getElementById('home-join-player')?.classList.toggle('hidden', !canJoin);
            const startBtn = document.getElementById('home-start-game');
            if (startBtn) {
                startBtn.classList.toggle('btn-primary', !canJoin);
                startBtn.classList.toggle('btn-ghost', canJoin);
            }

            this.renderPlayers(gameData.players || []);
        },
        renderPlayers(players) {
            const el = document.getElementById('home-players');
            if (!el) return;
            if (!players.length) {
                // #815: was hard-coded English; now i18n with English fallback.
                const waitingText = (window.BeatifyI18n && BeatifyI18n.t('admin.home.waitingForGuests')) || 'Waiting for guests…';
                el.innerHTML = '<div class="home-players-waiting">' + waitingText + '</div>';
                return;
            }
            // Jackbox-style tile grid. Host always wears the pink-primary
            // variant with a 👑 crown badge; guests cycle through the brand
            // neon palette (cyan → green → orange → dim-cyan, then wrap)
            // so each player reads distinctly in a mixed lobby.
            const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
            }[c]));
            const guestVariants = ['c1', 'c2', 'c3', 'c4'];
            let guestIdx = 0;
            // Onboarding v2 gate: players render with a dashed outline + TOUR badge
            // until they flip `onboarded: true` server-side (see DESIGN.md §
            // "Player onboarding — post-QR education").
            el.innerHTML = players.map((p) => {
                const isHost = !!p.is_admin;
                const isLearning = !isHost && p.onboarded === false;
                const variant = isHost ? 'host' : guestVariants[guestIdx++ % guestVariants.length];
                const raw = (p.name || p.id || '?').trim();
                const initial = (raw.charAt(0) || '?').toUpperCase();
                const crown = isHost
                    ? '<span class="home-player-tile-crown" aria-hidden="true">👑</span>'
                    : '';
                const tour = isLearning
                    ? '<span class="home-player-tile-tour" aria-hidden="true">TOUR</span>'
                    : '';
                const cls = ['home-player-tile', `home-player-tile--${variant}`];
                if (isLearning) cls.push('home-player-tile--learning');
                return `<div class="${cls.join(' ')}">`
                    + `<span class="home-player-tile-initial">${esc(initial)}</span>`
                    + `<span class="home-player-tile-name">${esc(raw || 'Guest')}</span>`
                    + crown + tour
                    + `</div>`;
            }).join('');

            // Warning banner above the Start button when any non-admin player is still LEARNING.
            const learning = players.filter((p) => !p.is_admin && p.onboarded === false);
            const warningEl = document.getElementById('home-learning-warning');
            if (warningEl) {
                if (learning.length > 0) {
                    const count = learning.length;
                    const key = count === 1
                        ? 'onboarding.learningWarning'
                        : 'onboarding.learningWarningPlural';
                    const fallback = count === 1
                        ? `⚠️ ${count} player still learning the rules`
                        : `⚠️ ${count} players still learning the rules`;
                    const msg = (window.BeatifyI18n && BeatifyI18n.t)
                        ? BeatifyI18n.t(key, { count })
                        : fallback;
                    warningEl.textContent = (msg === key) ? fallback : msg;
                    warningEl.classList.remove('hidden');
                } else {
                    warningEl.classList.add('hidden');
                }
            }
        },
        exit() {
            document.body.classList.remove('home-mode');
            const v = document.getElementById('home-view');
            if (v) v.classList.add('hidden');
        },
        refresh() {
            try {
                const raw = localStorage.getItem(STORAGE_GAME_SETTINGS);
                const s = raw ? JSON.parse(raw) : {};
                const pls = Array.isArray(s.selectedPlaylists) ? s.selectedPlaylists : [];
                const playlistLabel = pls.length === 0 ? 'no playlist'
                    : pls.length === 1 ? (pls[0].path || pls[0]).split('/').pop().replace('.json', '').replace(/-/g, ' ')
                    : `${pls.length} playlists`;
                const autoAdv = typeof s.revealAutoAdvance === 'number' ? s.revealAutoAdvance : 0;
                const autoLabel = autoAdv > 0 ? `${autoAdv}s` : 'Off';
                const mode = `${s.difficulty || 'normal'} · ${s.duration || 45}s · ${(s.language || 'en').toUpperCase()} · ⏭️ ${autoLabel}`;
                const meta = `${playlistLabel} · ${mode}`;
                const metaEl = document.getElementById('home-meta');
                if (metaEl) metaEl.textContent = meta;
            } catch (e) { /* ignore */ }
        },
        isConfigured() {
            try {
                const hasPlayer = !!localStorage.getItem(STORAGE_LAST_PLAYER);
                const raw = localStorage.getItem(STORAGE_GAME_SETTINGS);
                const s = raw ? JSON.parse(raw) : {};
                const hasPlaylist = Array.isArray(s.selectedPlaylists) && s.selectedPlaylists.length > 0;
                return hasPlayer && hasPlaylist;
            } catch (e) { return false; }
        },
    };
    // Home-view: End game delegates to existing endGame()
    document.getElementById('home-end-game')?.addEventListener('click', () => {
        if (typeof endGame === 'function') endGame();
    });
    // Join as player — delegates to the existing admin-join modal flow
    document.getElementById('home-join-player')?.addEventListener('click', () => {
        if (typeof openAdminJoinModal === 'function') openAdminJoinModal();
    });

    // Home-view QR: tap to enlarge — reuses the existing #qr-modal infrastructure
    document.getElementById('home-qr-code')?.addEventListener('click', () => {
        if (typeof openQRModal === 'function') openQRModal();
    });
    document.getElementById('home-qr-code')?.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' || e.key === ' ') && typeof openQRModal === 'function') {
            e.preventDefault();
            openQRModal();
        }
    });

    document.getElementById('home-edit-setup')?.addEventListener('click', () => {
        // "Edit setup" re-opens the wizard at Step 1 (not the legacy admin sections).
        // The wizard re-hydrates all picks from localStorage, so the user sees
        // their current choices pre-selected and can change anything.
        window.BeatifyHome.exit();
        if (window.BeatifyWizard && typeof window.BeatifyWizard.show === 'function') {
            window.BeatifyWizard.show(1);
        }
    });
    document.getElementById('home-start-game')?.addEventListener('click', async () => {
        // #1122: Acquire the wake lock SYNCHRONOUSLY here, inside the click's
        // user-gesture window. The Layer 2 NoSleep.js silent-video fallback
        // needs an active user activation to call video.play() on iOS — and
        // iOS consumes that activation after the first `await`. Both start
        // paths below (startGameplay / startGame) only reach their existing
        // _requestWakeLock() calls *after* awaiting fetch()/loadStatus(), by
        // which point the gesture is gone and the video silently fails to
        // start, so admin/admin+player screens kept sleeping. This call runs
        // before any await; the later calls are idempotent re-affirms
        // (guarded by _noSleepActive).
        _requestWakeLock();
        // Home-mode auto-creates the LOBBY session on enter, so the user's Start
        // button triggers the actual "begin rounds" action (startGameplay).
        // #935: adminState.currentGame is null until the async loadStatus() fetch returns,
        // but this button renders immediately on page load. A click in that
        // window (or after any reload / tab-switch) would fall through to the
        // else-branch and call startGame() — the *create* endpoint — which
        // then 409s because the game already exists. Reconcile with the server
        // first so the LOBBY check below is decided against fresh state.
        if (!adminState.currentGame || adminState.currentGame.phase !== 'LOBBY') {
            await loadStatus();
        }
        if (adminState.currentGame && adminState.currentGame.phase === 'LOBBY') {
            // Require at least one player. Starting with 0 players renders a
            // game nobody can answer — previously this was allowed and the
            // server happily transitioned to PLAYING, leaving the admin
            // staring at an empty round with no way to progress.
            const players = adminState.currentGame.players || [];
            if (players.length === 0) {
                const msg = (window.BeatifyI18n && BeatifyI18n.t('admin.home.needPlayerToStart')) ||
                    'Join as player (or ask a guest to scan the QR) before starting.';
                showError(msg);
                return;
            }
            // Onboarding v2: confirm if any non-admin player is still on tour.
            // Host can override, but the friction prevents accidental starts (DESIGN.md).
            const learning = players.filter((p) => !p.is_admin && p.onboarded === false);
            if (learning.length > 0) {
                const count = learning.length;
                const key = count === 1
                    ? 'onboarding.startAnyway'
                    : 'onboarding.startAnywayPlural';
                const fallback = count === 1
                    ? `${count} player is still learning the rules. Start anyway?`
                    : `${count} players are still learning the rules. Start anyway?`;
                const rawMsg = (window.BeatifyI18n && BeatifyI18n.t)
                    ? BeatifyI18n.t(key, { count })
                    : fallback;
                const msg = (rawMsg === key) ? fallback : rawMsg;
                if (!window.confirm(msg)) return;
            }
            startGameplay();
        } else {
            startGame();
        }
    });

    // Start setup: clear the dismiss flag and open the wizard at Step 1.
    document.getElementById('home-start-setup')?.addEventListener('click', () => {
        try { localStorage.removeItem('beatify_wizard_state'); } catch (e) { /* private mode */ }
        window.BeatifyHome.exit();
        if (window.BeatifyWizard && typeof window.BeatifyWizard.show === 'function') {
            window.BeatifyWizard.show(1);
        }
    });

    // Wire event listeners
    document.getElementById('start-game')?.addEventListener('click', startGame);
    document.getElementById('print-qr')?.addEventListener('click', printQRCode);

    document.getElementById('end-game')?.addEventListener('click', endGame);
    document.getElementById('end-game-lobby')?.addEventListener('click', endGame);

    // QR modal close/backdrop/escape — wired once at init so the home-view
    // tap-to-enlarge and the admin-playing-view both share the same modal.
    setupQRModal();

    // Admin join setup
    setupAdminJoin();

    // Issue #477: Wire game phase control buttons
    document.getElementById('admin-stop-song')?.addEventListener('click', adminStopSong);
    document.getElementById('admin-vol-down')?.addEventListener('click', adminVolumeDown);
    document.getElementById('admin-vol-up')?.addEventListener('click', adminVolumeUp);
    document.getElementById('admin-end-game-playing')?.addEventListener('click', endGame);
    document.getElementById('admin-next-round')?.addEventListener('click', adminNextRound);
    document.getElementById('admin-skip-round')?.addEventListener('click', adminNextRound);
    document.getElementById('admin-confirm-intro')?.addEventListener('click', function() {
        sendAdminCommand({ type: 'admin', action: 'confirm_intro_splash' });
    });
    document.getElementById('admin-rematch')?.addEventListener('click', showRematchModal);
    document.getElementById('admin-new-game')?.addEventListener('click', adminDismissGame);

    // #805: Pause-recovery banner buttons (Resume / End game)
    document.getElementById('admin-resume-game')?.addEventListener('click', function() {
        sendAdminCommand({ type: 'admin', action: 'resume_game' });
    });
    document.getElementById('admin-end-game-paused')?.addEventListener('click', endGame);

    // End game modal setup (Story 9.10)
    setupEndGameModal();

    // Issue #108: Rematch modal setup
    setupRematchModal();

    // #777 follow-up: emergency reset button + modal
    setupResetModal();

    // Collapsible sections setup
    setupCollapsibleSections();

    // Game settings setup (language, timer, difficulty, artist challenge)
    setupGameSettings();

    // Playlist requests setup (Story 44.2, 44.3)
    setupPlaylistRequests();

    // Load saved game settings from localStorage
    await loadSavedSettings();

    await loadStatus();

    // #1098: enter home-mode only after loadStatus() has resolved.
    // Previously this ran before the status fetch, so adminState.currentGame was always
    // null at this point — BeatifyHome.enter() would auto-call startSession()
    // → POST /start-game, hit 409 GAME_IN_LOBBY on an existing lobby, and the
    // silent recovery would transition LOBBY → PLAYING (auto-starting the
    // game). Visible regression when navigating Analytics → Admin with a
    // lobby open.
    // - If loadStatus found an active LOBBY, it already called showLobbyView()
    //   which invokes BeatifyHome.renderSession() — no extra enter() needed.
    // - If there is no active game, adminState.currentGame stays null → enter() runs and
    //   (for a configured user) creates a fresh LOBBY, as before.
    if (!adminState.currentGame) {
        window.BeatifyHome.enter();
    }

    // Initialize playlist requests display (Story 44.3, 44.4)
    initPlaylistRequests();
});

/**
 * Fetch and render current status from the API
 */
async function loadStatus() {
    try {
        const response = await fetch('/beatify/api/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const status = await response.json();

        // #935 follow-up: the server embeds the active game's admin token in
        // the page (<meta name="beatify-admin-token">). Capture it before the
        // WS connects below, so an admin that *reconnected* to an existing
        // game (reload / second tab) has a token — without it, start-gameplay
        // and other token-gated REST calls 403. Runs before connectAdminWebSocket().
        if (status.active_game && status.active_game.game_id) {
            const embeddedToken = document
                .querySelector('meta[name="beatify-admin-token"]')?.content;
            if (embeddedToken) {
                _setAdminToken(embeddedToken, status.active_game.game_id);
            }
        }

        adminState.playlistDocsUrl = status.playlist_docs_url || '';
        adminState.mediaPlayerDocsUrl = status.media_player_docs_url || '';
        // Set Music Assistant availability from backend (not based on entity names)
        adminState.hasMusicAssistant = status.has_music_assistant === true;
        // Display version in footer and expose globally (Story 44.5)
        const versionEl = document.getElementById('app-version');
        if (versionEl && status.version) {
            versionEl.textContent = 'v' + status.version;
            window.BEATIFY_VERSION = status.version;
        }
        renderMediaPlayers(status.media_players);
        renderPlaylists(status.playlists, status.playlist_dir);
        updateStartButtonState();

        // Check for active game and show appropriate view
        if (status.active_game && status.active_game.phase === 'LOBBY') {
            adminState.currentGame = status.active_game;
            _requestWakeLock(); // #647: keep screen on when reconnecting to active game
            showLobbyView(status.active_game);
            // Issue #477: Reconnect admin WS if we have a token
            if (!isAdminWsOpen()) {
                connectAdminWebSocket();
            }
        } else if (status.active_game && status.active_game.phase !== 'END') {
            adminState.currentGame = status.active_game;
            // Issue #477: Connect WS and render phase directly instead of stub
            if (!isAdminWsOpen()) {
                connectAdminWebSocket();
            }
            // Show correct phase view — WS state update will refine it
            handleAdminStateUpdate(status.active_game);
        } else {
            showSetupView();
        }
    } catch (error) {
        console.error('Failed to load status:', error);
        const container = document.getElementById('media-players-list');
        if (container) {
            container.innerHTML = '<span class="status-error">Failed to load status</span>';
        }
    }
}

/**
 * Setup collapsible section toggles
 */
function setupCollapsibleSections() {
    // Generic collapsible section toggles — handles all .section-header-collapsible
    // buttons including media-players, game-settings, my-requests, Party Lights, etc.
    // Issue #550: Removed duplicate per-ID listeners that caused double-toggle (no-op).
    //
    // Uses event delegation on document.body instead of per-button listeners so
    // sections added to the DOM after page load (or that somehow missed the
    // initial forEach) still get click handling.
    document.body.addEventListener('click', function(ev) {
        const header = ev.target.closest('.section-header-collapsible');
        if (!header) return;
        const section = header.closest('.section-collapsible');
        if (!section) return;
        section.classList.toggle('collapsed');
        header.setAttribute('aria-expanded', !section.classList.contains('collapsed'));
    });
}

// Game-Settings section (setupGameSettings chip/toggle wiring incl. the
// music-service provider chips, loadSavedSettings/saveGameSettings persistence,
// updateGameSettingsSummary, syncTitleArtistModeUI) moved to
// ./admin/sections/game-settings.js (#1279 step 4b). Imported at top of file.

// Media-Players section (renderMediaPlayers, renderPlayerItem, selection
// handlers, updateProviderOptions/Warning, summary) moved to
// ./admin/sections/media-players.js (#1279 step 4b). Imported at top of file.

// Playlists section (renderPlaylists, handlePlaylistToggle, filter bar,
// selection-summary + start-button validation) moved to
// ./admin/sections/playlists.js (#1279 step 4b). Imported at top of file.

// escapeHtml moved to BeatifyUtils

// ==========================================
// View State Machine (Story 2.3)
// ==========================================

/**
 * Reset admin to no-game state.
 *
 * #1138: this used to "show the setup view" — the legacy flat layout with
 * Media Players, Music Service, Playlists, Game Settings sections. That
 * surface was superseded by the wizard + home-view post-rc15, but the
 * function kept calling `setupSections.forEach(removeClass('hidden'))`,
 * leaving returning users with no `LS_WIZARD_STATE` (the wizard never
 * auto-triggers for them) staring at the old layout instead of the
 * polished home-view. rc11 strips the legacy reveal; the function now
 * only does the cleanup (close WS, stop polling, hide game phases) and
 * the caller is expected to route into wizard or home-view next.
 */
function showSetupView() {
    adminState.currentView = 'setup';
    adminState.currentGame = null;
    _releaseWakeLock(); // #622: allow screen to sleep again

    // Stop lobby polling (Story 16.8)
    stopLobbyPolling();
    adminState.previousLobbyPlayers = [];

    // #1138: do NOT unhide the legacy flat setup sections — let CSS keep
    // them hidden via body.home-mode (set by BeatifyHome.enter() below).
    // The flat layout is dead UI in rc11+; the wizard + home-view replace it.

    // Hide other views
    // Issue #477: Hide game phase views
    document.getElementById('admin-playing-section')?.classList.add('hidden');
    document.getElementById('admin-reveal-section')?.classList.add('hidden');
    document.getElementById('admin-end-section')?.classList.add('hidden');

    // Issue #477: Close admin WS if switching to setup
    closeAdminWs();
    adminState.isPlaying = false;
    adminState.adminPlayerName = null;

    // #1138: route into the home-view (or its setup-prompt sub-mode if the
    // user isn't configured). The function above is now pure cleanup; this
    // call hands the screen back to BeatifyHome which decides between
    // "configured: QR + Start game" vs "unconfigured: tap to launch wizard".
    if (window.BeatifyHome && typeof window.BeatifyHome.enter === 'function') {
        try { window.BeatifyHome.enter(); } catch (e) {
            console.warn('[Beatify] BeatifyHome.enter failed in showSetupView:', e);
        }
    }
}

/**
 * Show lobby view — pure delegate to BeatifyHome. The legacy #lobby-section
 * render was removed in rc25; home-mode is now guaranteed to be on whenever
 * a LOBBY state arrives (see handleAdminStateUpdate).
 */
function showLobbyView(gameData) {
    adminState.currentView = 'lobby';
    adminState.currentGame = gameData;
    if (window.BeatifyHome) {
        window.BeatifyHome.renderSession(gameData);
    }
    // WS push is the primary source; fall back to REST polling if WS is down
    // so the home-view chips still update via renderLobbyPlayers → BeatifyHome.renderPlayers.
    if (!isAdminWsOpen()) {
        startLobbyPolling();
    }
}

// ==========================================
// QR Modal Functions (tap to enlarge)
// ==========================================

/**
 * Open QR modal with enlarged code
 */
function openQRModal() {
    if (!adminState.cachedQRUrl) return;

    var modal = document.getElementById('qr-modal');
    var modalCode = document.getElementById('qr-modal-code');
    if (!modal || !modalCode) return;

    // Clear and render larger QR
    modalCode.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(modalCode, {
            text: adminState.cachedQRUrl,
            width: 280,
            height: 280,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    }

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    // Focus close button for accessibility
    var closeBtn = document.getElementById('qr-modal-close');
    if (closeBtn) closeBtn.focus();
}

/**
 * Close QR modal
 */
function closeQRModal() {
    var modal = document.getElementById('qr-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

/**
 * Wire the QR modal once at init. The modal itself is shared between the
 * home-view tap-to-enlarge (BeatifyHome triggers openQRModal) and the
 * admin-playing view's QR preview, so only backdrop/close/escape are wired
 * here — the triggers live with each view.
 */
function setupQRModal() {
    var modal = document.getElementById('qr-modal');
    var backdrop = modal ? modal.querySelector('.qr-modal-backdrop') : null;
    var closeBtn = document.getElementById('qr-modal-close');

    if (backdrop) backdrop.addEventListener('click', closeQRModal);
    if (closeBtn) closeBtn.addEventListener('click', closeQRModal);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeQRModal();
        }
    });
}

// ==========================================
// Game Control Functions (Story 2.3)
// ==========================================

/**
 * Start a new game
 */
async function startGame() {
    const btn = document.getElementById('start-game');
    const inHomeMode = document.body.classList.contains('home-mode');
    // Bail only if a legacy button exists AND is already disabled, AND we're NOT
    // in home-mode. In home-mode the legacy button is disabled by default (no
    // click-path populates it), so we bypass its state and trust the hydrated
    // module globals (adminState.selectedMediaPlayer / adminState.selectedPlaylists) instead.
    if (btn && btn.disabled && !inHomeMode) return;

    let originalText;
    if (btn) {
        btn.disabled = true;
        originalText = btn.textContent;
        btn.textContent = BeatifyI18n.t('game.starting');
    }

    try {
        // #1180: Title & Artist mode replaces the year round, so the year-only
        // bonuses are suppressed here at payload-build time (NOT by mutating the
        // stored flags — that would corrupt the host's saved preferences on the
        // next reload). The in-memory flags remain the host's untouched choices.
        const rawBonusFlags = {
            artist_challenge_enabled: adminState.artistChallengeEnabled,  // Story 20.7
            movie_quiz_enabled: adminState.movieQuizEnabled,  // #947
            intro_mode_enabled: adminState.introModeEnabled,  // Issue #23
            closest_wins_mode: adminState.closestWinsModeEnabled  // Issue #442
        };
        const bonusFlags = (window.BeatifyTitleArtist && typeof window.BeatifyTitleArtist.applyTitleArtistBonusPrecedence === 'function')
            ? window.BeatifyTitleArtist.applyTitleArtistBonusPrecedence(rawBonusFlags, adminState.titleArtistModeEnabled)
            : { ...rawBonusFlags, ...(adminState.titleArtistModeEnabled ? { artist_challenge_enabled: false, closest_wins_mode: false } : {}) };  // #1180: must match YEAR_ROUND_BONUS_KEYS — movie quiz + intro stay ON in TA mode

        const response = await BeatifyAuth.fetch('/beatify/api/start-game', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                playlists: adminState.selectedPlaylists.map(p => p.path),
                media_player: adminState.selectedMediaPlayer?.entityId,
                language: adminState.selectedLanguage,
                round_duration: adminState.selectedDuration,  // Story 13.1
                reveal_auto_advance: adminState.revealAutoAdvance,  // #1012
                difficulty: adminState.selectedDifficulty,  // Story 14.1
                provider: adminState.selectedProvider,  // Story 17.2
                artist_challenge_enabled: bonusFlags.artist_challenge_enabled,  // Story 20.7 (#1180: suppressed in TA mode)
                movie_quiz_enabled: bonusFlags.movie_quiz_enabled,  // #947 (#1180: suppressed in TA mode)
                intro_mode_enabled: bonusFlags.intro_mode_enabled,  // Issue #23 (#1180: suppressed in TA mode)
                closest_wins_mode: bonusFlags.closest_wins_mode,  // Issue #442 (#1180: suppressed in TA mode)
                title_artist_mode: adminState.titleArtistModeEnabled,  // #1180
                party_lights: window._partyLightsConfig ? window._partyLightsConfig() : null,  // Issue #331
                tts: window._ttsConfig ? window._ttsConfig() : null  // Issue #447
            })
        });

        const data = await response.json();

        if (!response.ok) {
            // #935: a LOBBY game already exists — this create call raced ahead
            // of state hydration. Recover transparently by beginning gameplay
            // instead of dead-ending the host on "End current game first".
            if (data.code === 'GAME_IN_LOBBY') {
                await loadStatus();
                startGameplay();
                return;
            }
            // #864: prefer i18n-by-code over the backend's English message.
            // Matches the playlist-request pattern at line ~2964.
            let msg = data.message || 'Failed to start game';
            if (data.code && window.BeatifyI18n) {
                const key = 'errors.' + String(data.code).toUpperCase();
                const t = BeatifyI18n.t(key);
                if (t && t !== key) msg = t;
            }
            showError(msg);
            return;
        }

        if (data.warnings && data.warnings.length > 0) {
            console.warn('Game started with warnings:', data.warnings);
        }

        // Issue #386 + #477: Store admin token in localStorage for persistence
        if (data.admin_token) {
            _setAdminToken(data.admin_token, data.game_id);
        }

        showLobbyView(data);
        _requestWakeLock(); // #622: keep screen on during game

        // Issue #477: Connect admin WebSocket for real-time updates
        connectAdminWebSocket();

    } catch (err) {
        showError('Network error. Please try again.');
        console.error('Start game error:', err);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
        updateStartButtonState();
    }
}

/**
 * #949: un-stick the home "Start game" button after a failed start. The WS
 * path of startGameplay() sets it to "⏳ Starting…" and returns; on a start
 * rejection there is otherwise nothing to restore it.
 */
function resetHomeStartButton() {
    var b = document.getElementById('home-start-game');
    if (!b) return;
    b.disabled = false;
    if (_homeStartBtnHTML) b.innerHTML = _homeStartBtnHTML;
}

/**
 * Start gameplay from lobby — transitions LOBBY → PLAYING (Issue #228).
 * Called from the "Spiel starten" button in the lobby view.
 * Preserves admin session: admin can start the game without having to
 * re-join as a player after a rematch.
 */
async function startGameplay() {
    // The legacy #start-gameplay-btn was removed in rc25; the home-view's
    // #home-start-game is now the only entry point. Before rc27 this
    // function looked up the legacy id and returned early when it didn't
    // exist — so Spiel starten did nothing on click.
    const btn = document.getElementById('home-start-game');
    if (btn && btn.disabled) return;

    let originalHTML = null;
    if (btn) {
        btn.disabled = true;
        originalHTML = btn.innerHTML;
        _homeStartBtnHTML = originalHTML;  // #949: so a WS error can restore it
        btn.innerHTML = '<span class="btn-icon" aria-hidden="true">⏳</span> ' + BeatifyI18n.t('game.starting');
    }

    // Issue #477: Prefer WS for game commands
    if (isAdminWsOpen()) {
        sendAdminWs({ type: 'admin', action: 'start_game' });
        // State update will arrive via WS broadcast. handleAdminStateUpdate
        // exits home-mode on LOBBY → PLAYING, so the button is hidden.
        return;
    }

    // Fallback to REST
    try {
        const response = await BeatifyAuth.fetch('/beatify/api/start-gameplay', { method: 'POST' });
        const data = await response.json();

        if (!response.ok) {
            showError(data.message || 'Failed to start gameplay');
            return;
        }

        await loadStatus();

    } catch (err) {
        showError('Network error. Please try again.');
        console.error('Start gameplay error:', err);
    } finally {
        if (btn && originalHTML != null) {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }
}

/**
 * Show end game confirmation modal (Story 9.10)
 */
function showEndGameModal() {
    const modal = document.getElementById('end-game-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

/**
 * Close end game confirmation modal (Story 9.10)
 */
function closeEndGameModal() {
    const modal = document.getElementById('end-game-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * End the current game - shows confirmation modal (Story 9.10)
 */
function endGame() {
    showEndGameModal();
}

/**
 * Actually end the game after confirmation
 */
async function confirmEndGame() {
    closeEndGameModal();

    // Issue #477: Prefer WS for admin commands
    if (isAdminWsOpen()) {
        sendAdminWs({ type: 'admin', action: 'end_game' });
        return;
    }

    // Issue #569: Check for valid admin token before REST fallback
    if (!_getAdminToken()) {
        showError('Admin session expired. Please reload the page.');
        return;
    }

    try {
        const response = await BeatifyAuth.fetch('/beatify/api/end-game', { method: 'POST' });
        if (response.ok) {
            adminState.cachedQRUrl = null;
            showSetupView();
        } else {
            const data = await response.json();
            showError(data.message || 'Failed to end game');
        }
    } catch (err) {
        console.error('End game error:', err);
        showError('Network error. Please try again.');
    }
}

/**
 * Setup end game modal event listeners (Story 9.10)
 */
function setupEndGameModal() {
    const confirmBtn = document.getElementById('end-game-confirm-btn');
    const cancelBtn = document.getElementById('end-game-cancel-btn');
    const backdrop = document.querySelector('#end-game-modal .modal-backdrop');

    confirmBtn?.addEventListener('click', confirmEndGame);
    cancelBtn?.addEventListener('click', closeEndGameModal);
    backdrop?.addEventListener('click', closeEndGameModal);

    // ESC key handling added to global handler below
}

// ==========================================
// Force-Reset Modal (#777 follow-up)
// ==========================================

// localStorage keys Beatify writes — cleared on force-reset.
// Add new keys here if you introduce more, otherwise stuck state survives.
const _BEATIFY_LS_KEYS = [
    'beatify_wizard_state',
    'beatify_last_player',
    'beatify_game_settings',
    'beatify_party_lights',
    'beatify_tts',
    'beatify_admin_token',
    'beatify_admin_token_game_id',
];

function showResetModal() {
    document.getElementById('reset-modal')?.classList.remove('hidden');
}

function closeResetModal() {
    document.getElementById('reset-modal')?.classList.add('hidden');
}

/**
 * Force-reset Beatify: end any active game on the server, clear local
 * Beatify state, unregister the service worker, and reload. Designed to
 * recover from any stuck state — does NOT require an admin token. The
 * server endpoint is rate-limited per IP (3 per hour). On endpoint
 * failure we still clear local state + reload, because most stuck
 * symptoms are client-side and a reload often clears them anyway.
 */
async function confirmReset() {
    closeResetModal();

    // 1. Hit the server, but don't block local cleanup on its result.
    try {
        await BeatifyAuth.fetch('/beatify/api/force-reset', { method: 'POST' });
    } catch (err) {
        console.warn('[Reset] force-reset POST failed (continuing with local cleanup):', err);
    }

    // 2. Clear Beatify-owned localStorage entries.
    try {
        _BEATIFY_LS_KEYS.forEach((k) => localStorage.removeItem(k));
    } catch (err) {
        console.warn('[Reset] localStorage clear failed:', err);
    }

    // 3. Unregister the SW so a fresh registration happens on next load
    //    (matters since #780 fixed SW activation — stale caches can now
    //    actually exist).
    try {
        if ('serviceWorker' in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((r) => r.unregister()));
        }
    } catch (err) {
        console.warn('[Reset] SW unregister failed:', err);
    }

    // 4. Reload onto the admin entry point.
    window.location.replace('/beatify/admin');
}

function setupResetModal() {
    document.getElementById('reset-btn')?.addEventListener('click', showResetModal);
    document.getElementById('reset-confirm-btn')?.addEventListener('click', confirmReset);
    document.getElementById('reset-cancel-btn')?.addEventListener('click', closeResetModal);
    document.querySelector('#reset-modal .modal-backdrop')?.addEventListener('click', closeResetModal);
}

// ==========================================
// Rematch Functions (Issue #108)
// ==========================================

var rematchInProgress = false;  // Debounce flag

/**
 * Show rematch confirmation modal
 */
function showRematchModal() {
    var modal = document.getElementById('rematch-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

/**
 * Close rematch confirmation modal
 */
function closeRematchModal() {
    var modal = document.getElementById('rematch-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * Confirm rematch - calls API and transitions to setup
 */
async function confirmRematch() {
    if (rematchInProgress) return;  // Debounce
    rematchInProgress = true;

    // F8 fix: Show loading state on rematch button
    var rematchBtn = document.getElementById('rematch-game');
    var originalText = rematchBtn ? rematchBtn.textContent : '';
    if (rematchBtn) {
        rematchBtn.disabled = true;
        rematchBtn.textContent = '⏳';
    }

    closeRematchModal();

    // Issue #477: Prefer WS for rematch
    if (isAdminWsOpen()) {
        sendAdminWs({ type: 'admin', action: 'rematch_game' });
        // WS broadcast will trigger lobby view transition
        rematchInProgress = false;
        return;
    }

    try {
        var response = await BeatifyAuth.fetch('/beatify/api/rematch-game', { method: 'POST' });
        if (response.ok) {
            var data = await response.json();
            await loadStatus();
        } else {
            var errData = await response.json();
            alert(errData.message || 'Failed to start rematch');
        }
    } catch (error) {
        console.error('Rematch failed:', error);
        alert('Failed to start rematch');
    } finally {
        rematchInProgress = false;
        // Restore button state (in case of error)
        if (rematchBtn) {
            rematchBtn.disabled = false;
            rematchBtn.textContent = originalText;
        }
    }
}

/**
 * Setup rematch modal event listeners (Issue #108)
 */
function setupRematchModal() {
    var confirmBtn = document.getElementById('rematch-confirm-btn');
    var cancelBtn = document.getElementById('rematch-cancel-btn');
    var backdrop = document.querySelector('#rematch-modal .modal-backdrop');

    confirmBtn?.addEventListener('click', confirmRematch);
    cancelBtn?.addEventListener('click', closeRematchModal);
    backdrop?.addEventListener('click', closeRematchModal);

    // Also handle Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var rematchModal = document.getElementById('rematch-modal');
            if (rematchModal && !rematchModal.classList.contains('hidden')) {
                closeRematchModal();
            }
        }
    });
}

/**
 * Print QR code
 */
function printQRCode() {
    window.print();
}

/**
 * Show error message to user
 * @param {string} message
 */
function showError(message) {
    // Simple alert for now - can be enhanced with toast notifications
    alert(message);
}


// ==========================================
// Admin Join Functions (Story 3.5)
// ==========================================

/**
 * Open admin join modal
 */
function openAdminJoinModal() {
    // Issue #477: If already joined inline, just show a toast
    if (adminState.isPlaying && adminState.adminPlayerName) {
        showError(BeatifyI18n.t('admin.alreadyJoined') || 'Already joined as ' + adminState.adminPlayerName);
        return;
    }

    // Fix #228: If admin was already a player (sessionStorage has their name)
    // and no WS available, redirect to player page as fallback.
    if (!isAdminWsOpen()) {
        var adminName = null;
        try { adminName = sessionStorage.getItem('beatify_admin_name'); } catch(e) {}
        if (adminName && adminState.currentGame && adminState.currentGame.game_id) {
            window.location.href = '/beatify/play?game=' + encodeURIComponent(adminState.currentGame.game_id);
            return;
        }
    }

    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.remove('hidden');
        document.getElementById('admin-name-input')?.focus();
    }
}

/**
 * Close admin join modal
 */
function closeAdminJoinModal() {
    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
    // Reset form
    const nameInput = document.getElementById('admin-name-input');
    const joinBtn = document.getElementById('admin-join-btn');
    const errorMsg = document.getElementById('admin-name-error');
    if (nameInput) nameInput.value = '';
    if (joinBtn) {
        joinBtn.disabled = true;
        joinBtn.textContent = BeatifyI18n.t('admin.join');
    }
    if (errorMsg) errorMsg.classList.add('hidden');
}

/**
 * Setup admin join modal and button handlers
 */
function setupAdminJoin() {
    const cancelBtn = document.getElementById('admin-cancel-btn');
    const joinBtn = document.getElementById('admin-join-btn');
    const nameInput = document.getElementById('admin-name-input');
    const backdrop = document.querySelector('#admin-join-modal .modal-backdrop');

    cancelBtn?.addEventListener('click', closeAdminJoinModal);
    backdrop?.addEventListener('click', closeAdminJoinModal);

    nameInput?.addEventListener('input', function() {
        const name = this.value.trim();
        joinBtn.disabled = !name || name.length > 20;
    });

    nameInput?.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !joinBtn.disabled) {
            handleAdminJoin();
        }
    });

    joinBtn?.addEventListener('click', handleAdminJoin);

    // Close modals on Escape (Story 9.10: also handles end-game-modal)
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const adminModal = document.getElementById('admin-join-modal');
            const endGameModal = document.getElementById('end-game-modal');

            if (adminModal && !adminModal.classList.contains('hidden')) {
                closeAdminJoinModal();
            }
            if (endGameModal && !endGameModal.classList.contains('hidden')) {
                closeEndGameModal();
            }
        }
    });
}

/**
 * Handle admin join button click
 */
function handleAdminJoin() {
    const nameInput = document.getElementById('admin-name-input');
    const joinBtn = document.getElementById('admin-join-btn');
    const name = nameInput?.value.trim();

    if (!name) return;

    joinBtn.disabled = true;
    joinBtn.textContent = BeatifyI18n.t('game.joining');

    const inHomeMode = document.body.classList.contains('home-mode');
    const wsOpen = isAdminWsOpen();

    // Home-view path: keep admin on the new view. adminWs is already
    // authenticated via admin_connect; sending a join on the same socket
    // registers this ws as a player too (handle_join adds it to
    // game_state.players + set_admin). State broadcast then feeds back
    // through handleAdminStateUpdate → showLobbyView → BeatifyHome.renderSession
    // so the admin shows up in the player list without navigating away.
    if (inHomeMode) {
        const sendJoin = async () => {
            try {
                sessionStorage.setItem('beatify_admin_name', name);
                sessionStorage.setItem('beatify_is_admin', 'true');
                adminState.adminPlayerName = name;
                // #998: server validates ha_token before granting the admin
                // claim. Without this field handle_join returns ERR_UNAUTHORIZED
                // ("Home Assistant login required to host") and the host's
                // name never appears in the player list — even with a fresh
                // OAuth login, because admin_connect's ha_token doesn't carry
                // over to subsequent messages on the same socket. Match the
                // pattern player-core.js:459 uses.
                const token = await BeatifyAuth.ensureAuthenticated();
                sendAdminWs({
                    type: 'join',
                    name: name,
                    is_admin: true,
                    ha_token: token,
                });
                closeAdminJoinModal();
            } catch (err) {
                console.error('Admin join (home-mode) failed:', err);
                joinBtn.disabled = false;
                joinBtn.textContent = BeatifyI18n.t('admin.join');
            }
        };
        if (wsOpen) {
            sendJoin();
        } else {
            // WS not yet open — page just loaded, or auto-reconnect is in flight.
            // Do NOT fall through to the legacy /play redirect: that breaks the
            // "admin stays on home-view" promise and surfaces "No active game
            // found" when adminState.currentGame.game_id is stale. Instead, nudge the WS
            // open and send the join once it's ready.
            //
            // #814: bumped timeout from 5s to 20s. After a fresh HA restart
            // the WS server can take ~10s to be ready and 5s was tripping
            // false-positive "Reconnecting to game server" alerts. Also
            // moved the error from a native alert() into an inline message
            // on the modal, so the user can keep their typed name and just
            // click Join again.
            connectAdminWebSocket();
            joinBtn.textContent = (BeatifyI18n.t('admin.connecting') || 'Connecting…');
            const errorEl = document.getElementById('admin-name-error');
            if (errorEl) {
                errorEl.classList.add('hidden');
                errorEl.textContent = '';
            }
            const startedAt = Date.now();
            const poll = setInterval(() => {
                if (isAdminWsOpen()) {
                    clearInterval(poll);
                    sendJoin();
                } else if (Date.now() - startedAt > 20000) {
                    clearInterval(poll);
                    joinBtn.disabled = false;
                    joinBtn.textContent = BeatifyI18n.t('admin.join') || 'Join';
                    if (errorEl) {
                        errorEl.textContent = BeatifyI18n.t('admin.home.wsReconnecting') ||
                            'Reconnecting to game server — please try again.';
                        errorEl.classList.remove('hidden');
                    } else {
                        // No error element on this modal — fall back to alert.
                        showError(BeatifyI18n.t('admin.home.wsReconnecting') ||
                            'Reconnecting to game server — please try again.');
                    }
                }
            }, 100);
        }
        return;
    }

    // Legacy path (#653): redirect to the player page for the full game
    // experience — used when home-mode is off (e.g. rematch flow that
    // bypasses home-view) or the admin WS isn't ready.
    try {
        sessionStorage.setItem('beatify_admin_name', name);
        sessionStorage.setItem('beatify_is_admin', 'true');

        const gameId = adminState.currentGame?.game_id;
        if (gameId) {
            window.location.href = '/beatify/play?game=' + encodeURIComponent(gameId);
        } else {
            showError('No active game found');
            joinBtn.disabled = false;
            joinBtn.textContent = BeatifyI18n.t('admin.join');
        }
    } catch (err) {
        console.error('Admin join failed:', err);
        joinBtn.disabled = false;
        joinBtn.textContent = BeatifyI18n.t('admin.join');
    }
}

/**
 * Setup language selector buttons (Story 12.4)
 */
function setupLanguageSelector() {
    var langButtons = document.querySelectorAll('.lang-btn');

    langButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var lang = btn.getAttribute('data-lang');
            if (lang && lang !== adminState.selectedLanguage) {
                setLanguage(lang);
            }
        });
    });
}

/**
 * Update language button states (Story 12.4)
 * @param {string} lang - Language code ('en', 'de', or 'es')
 */
function updateLanguageButtons(lang) {
    var langButtons = document.querySelectorAll('.lang-btn');
    langButtons.forEach(function(btn) {
        var btnLang = btn.getAttribute('data-lang');
        if (btnLang === lang) {
            btn.classList.add('lang-btn--active');
        } else {
            btn.classList.remove('lang-btn--active');
        }
    });
}

/**
 * Set language and update UI (Story 12.4, 16.3)
 * @param {string} lang - Language code ('en', 'de', or 'es')
 */
async function setLanguage(lang) {
    if (lang !== 'en' && lang !== 'de' && lang !== 'es') {
        lang = 'en';
    }

    adminState.selectedLanguage = lang;
    updateLanguageButtons(lang);

    // Update i18n and re-render page
    await BeatifyI18n.setLanguage(lang);
    BeatifyI18n.initPageTranslations();
}

// ==========================================
// Timer Selector Functions (Story 13.1)
// ==========================================

/**
 * Setup timer selector buttons
 */
function setupTimerSelector() {
    var timerButtons = document.querySelectorAll('.timer-btn');

    timerButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var duration = parseInt(btn.getAttribute('data-duration'), 10);
            if (duration && duration !== adminState.selectedDuration) {
                setTimerDuration(duration);
            }
        });
    });
}

/**
 * Update timer button states
 * @param {number} duration - Duration in seconds (15, 30, or 45)
 */
function updateTimerButtons(duration) {
    var timerButtons = document.querySelectorAll('.timer-btn');
    timerButtons.forEach(function(btn) {
        var btnDuration = parseInt(btn.getAttribute('data-duration'), 10);
        if (btnDuration === duration) {
            btn.classList.add('timer-btn--active');
        } else {
            btn.classList.remove('timer-btn--active');
        }
    });
}

/**
 * Set timer duration
 * @param {number} duration - Duration in seconds (10-60 range)
 */
function setTimerDuration(duration) {
    // Validate duration is within valid range (matches backend: 10-60)
    if (typeof duration !== 'number' || duration < 10 || duration > 60) {
        duration = 30;
    }

    adminState.selectedDuration = duration;
    updateTimerButtons(duration);
}

// ==========================================
// Difficulty Selector Functions (Story 14.1)
// ==========================================

// Mapping of difficulty levels to their description i18n keys
const difficultyDescriptions = {
    easy: 'admin.difficultyEasyDesc',
    normal: 'admin.difficultyNormalDesc',
    hard: 'admin.difficultyHardDesc'
};

/**
 * Setup difficulty selector buttons
 */
function setupDifficultySelector() {
    var difficultyButtons = document.querySelectorAll('.difficulty-btn');

    difficultyButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var difficulty = btn.getAttribute('data-difficulty');
            if (difficulty && difficulty !== adminState.selectedDifficulty) {
                setDifficulty(difficulty);
            }
        });
    });
}

/**
 * Update difficulty button states
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function updateDifficultyButtons(difficulty) {
    var difficultyButtons = document.querySelectorAll('.difficulty-btn');
    difficultyButtons.forEach(function(btn) {
        var btnDifficulty = btn.getAttribute('data-difficulty');
        if (btnDifficulty === difficulty) {
            btn.classList.add('difficulty-btn--active');
        } else {
            btn.classList.remove('difficulty-btn--active');
        }
    });
}

/**
 * Set difficulty level and update UI
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function setDifficulty(difficulty) {
    // Validate difficulty
    var validDifficulties = ['easy', 'normal', 'hard'];
    if (validDifficulties.indexOf(difficulty) === -1) {
        difficulty = 'normal';
    }

    adminState.selectedDifficulty = difficulty;
    updateDifficultyButtons(difficulty);

    // Update description text
    var descriptionEl = document.getElementById('difficulty-description');
    if (descriptionEl) {
        var descKey = difficultyDescriptions[difficulty];
        descriptionEl.setAttribute('data-i18n', descKey);
        // Use i18n translation if available
        if (typeof BeatifyI18n !== 'undefined' && BeatifyI18n.t) {
            descriptionEl.textContent = BeatifyI18n.t(descKey);
        }
    }
}

/**
 * Update difficulty badge in lobby view
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function updateLobbyDifficultyBadge(difficulty) {
    var badge = document.getElementById('lobby-difficulty-badge');
    if (!badge) return;

    var labelKey = {
        easy: 'game.difficultyEasy',
        normal: 'game.difficultyNormal',
        hard: 'game.difficultyHard'
    }[difficulty] || 'game.difficultyNormal';

    var label = utils.t(labelKey);
    badge.textContent = label;
    badge.className = 'difficulty-badge difficulty-badge--' + (difficulty || 'normal');
}

// ==========================================
// Artist Challenge Toggle Functions (Story 20.7)
// ==========================================

/**
 * Setup artist challenge toggle
 */
function setupArtistChallengeToggle() {
    var toggle = document.getElementById('artist-challenge-toggle');
    if (!toggle) return;

    // Load saved preference
    var saved = localStorage.getItem('beatify_artist_challenge');
    if (saved !== null) {
        adminState.artistChallengeEnabled = saved === 'true';
        toggle.checked = adminState.artistChallengeEnabled;
    }

    toggle.addEventListener('change', function() {
        adminState.artistChallengeEnabled = toggle.checked;
        // Save preference
        localStorage.setItem('beatify_artist_challenge', adminState.artistChallengeEnabled.toString());
    });
}

// ==========================================
// Provider Selector Functions (Story 17.2)
// ==========================================

/**
 * Setup provider selector buttons
 */
function setupProviderSelector() {
    var providerButtons = document.querySelectorAll('.provider-btn');

    providerButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            // Don't allow clicking disabled buttons
            if (btn.classList.contains('provider-btn--disabled')) {
                return;
            }
            var provider = btn.getAttribute('data-provider');
            if (provider && provider !== adminState.selectedProvider) {
                setProvider(provider);
            }
        });
    });
}

/**
 * Update provider button states
 * @param {string} provider - Provider identifier ('spotify' or 'apple_music')
 */
function updateProviderButtons(provider) {
    var providerButtons = document.querySelectorAll('.provider-btn');
    providerButtons.forEach(function(btn) {
        var btnProvider = btn.getAttribute('data-provider');
        if (btnProvider === provider) {
            btn.classList.add('provider-btn--active');
        } else {
            btn.classList.remove('provider-btn--active');
        }
    });
}

/**
 * Set music provider and update UI
 * @param {string} provider - Provider identifier (only 'spotify' supported, Story 17.6)
 */
function setProvider(provider) {
    // Only Spotify is supported (Story 17.6: Apple Music removed)
    adminState.selectedProvider = 'spotify';
    updateProviderButtons('spotify');

    // Re-render playlists to show coverage for selected provider
    if (adminState.playlistData.length > 0) {
        renderPlaylists(adminState.playlistData, '');
    }
}

// ==========================================
// Lobby Player List Functions (Story 16.8)
// ==========================================

// t() moved to BeatifyUtils

/**
 * Render player list in admin lobby (analytics grid layout)
 * @param {Array} players - Array of player objects from game state
 */
function renderLobbyPlayers(players) {
    var listEl = document.getElementById('lobby-players');
    var countEl = document.getElementById('lobby-player-count');
    var summaryEl = document.getElementById('admin-players-summary');
    var emptyEl = document.getElementById('lobby-players-empty');

    players = players || [];

    // Mirror live player updates into the home-view pill row. If BeatifyHome
    // is active, this keeps the Variant A landing in sync with the real lobby.
    if (window.BeatifyHome && typeof window.BeatifyHome.renderPlayers === 'function') {
        window.BeatifyHome.renderPlayers(players);
    }

    if (!listEl) return;

    // Update player count (stat card value - just the number)
    if (countEl) {
        countEl.textContent = players.length;
    }

    // Update players section summary badge
    if (summaryEl) {
        summaryEl.textContent = players.length;
    }

    // Handle empty state visibility
    if (players.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        var startBtn = document.getElementById("start-gameplay-btn");
        if (startBtn) startBtn.classList.add("hidden");
        adminState.previousLobbyPlayers = [];
        return;
    }

    // Hide empty state when we have players
    if (emptyEl) emptyEl.classList.add('hidden');

    // Sort: connected first, disconnected last
    var sortedPlayers = players.slice().sort(function(a, b) {
        if (a.connected !== b.connected) {
            return a.connected ? -1 : 1;
        }
        return 0;
    });

    // Find new players by comparing with previous list
    var previousNames = adminState.previousLobbyPlayers.map(function(p) { return p.name; });
    var newNames = sortedPlayers
        .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
        .map(function(p) { return p.name; });

    // Render player cards (grid layout)
    listEl.innerHTML = sortedPlayers.map(function(player) {
        var isNew = newNames.indexOf(player.name) !== -1;
        var isDisconnected = player.connected === false;
        var isAdmin = player.is_admin === true;
        var canKick = isDisconnected && !isAdmin;
        var classes = [
            'player-card',
            isNew ? 'is-new' : '',
            isDisconnected ? 'player-card--disconnected' : ''
        ].filter(Boolean).join(' ');

        // Crown badge for admin
        var adminBadge = isAdmin ? '<span class="admin-badge">👑</span>' : '';
        // Badge for disconnected players
        var awayBadge = isDisconnected ? '<span class="away-badge">' + utils.t('lobby.away', 'away') + '</span>' : '';
        // Kick button for disconnected non-admin players (#659)
        var kickBtn = canKick
            ? '<button class="kick-player-btn" data-player="' + utils.escapeHtml(player.name) + '" title="' + (BeatifyI18n.t('admin.kickPlayerTitle') || 'Remove player') + '">×</button>'
            : '';

        return '<div class="' + classes + '" data-player="' + utils.escapeHtml(player.name) + '">' +
            '<span class="player-name">' +
                utils.escapeHtml(player.name) +
                adminBadge +
            '</span>' +
            awayBadge +
            kickBtn +
        '</div>';
    }).join('');

    // Wire up kick buttons (#659)
    listEl.querySelectorAll('.kick-player-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            handleKickPlayer(btn.dataset.player);
        });
    });

    // Remove .is-new class after animation
    setTimeout(function() {
        var newCards = listEl.querySelectorAll('.is-new');
        for (var i = 0; i < newCards.length; i++) {
            newCards[i].classList.remove('is-new');
        }
    }, 2000);

    // Show Start button when there are players. The admin page IS the admin
    // control surface — the host should always be able to start the game,
    // whether they joined as a player or not.
    var startBtn = document.getElementById("start-gameplay-btn");
    if (startBtn) {
        startBtn.classList.remove("hidden");
    }

    adminState.previousLobbyPlayers = players.slice();
}

/**
 * Handle kick player action — remove disconnected player from lobby (#659)
 */
function handleKickPlayer(playerName) {
    var message = (BeatifyI18n.t('admin.kickPlayerConfirm') || 'Remove {name} from the lobby?')
        .replace('{name}', playerName);
    if (!confirm(message)) return;

    if (isAdminWsOpen()) {
        sendAdminWs({
            type: 'admin',
            action: 'kick_player',
            player_name: playerName
        });
    }
}

/**
 * Start polling for lobby state updates
 */
function startLobbyPolling() {
    // Clear any existing interval
    stopLobbyPolling();

    // Poll every 3 seconds (balanced between responsiveness and server load)
    lobbyPollingInterval = setInterval(async function() {
        if (adminState.currentView !== 'lobby') {
            stopLobbyPolling();
            return;
        }

        try {
            var response = await fetch('/beatify/api/status');
            if (!response.ok) return;

            var status = await response.json();
            if (status.active_game && status.active_game.players) {
                renderLobbyPlayers(status.active_game.players);
            }
        } catch (err) {
            console.error('Lobby polling error:', err);
        }
    }, 3000);
}

/**
 * Stop polling for lobby state updates
 */
function stopLobbyPolling() {
    if (lobbyPollingInterval) {
        clearInterval(lobbyPollingInterval);
        lobbyPollingInterval = null;
    }
}

// ============================================
// Playlist Requests (Story 44)
// ============================================

/**
 * Setup event handlers for playlist request modal
 */
function setupPlaylistRequests() {
    const requestModal = document.getElementById('request-modal');
    const successModal = document.getElementById('request-success-modal');
    const urlInput = document.getElementById('spotify-url-input');
    const urlError = document.getElementById('spotify-url-error');
    const submitBtn = document.getElementById('request-submit-btn');

    // Open request modal from button
    document.getElementById('request-playlist-btn')?.addEventListener('click', () => {
        if (requestModal) {
            requestModal.classList.remove('hidden');
            urlInput?.focus();
        }
    });

    // Close request modal
    document.getElementById('request-cancel-btn')?.addEventListener('click', () => {
        closeRequestModal();
    });

    // Close on backdrop click
    requestModal?.querySelector('.modal-backdrop')?.addEventListener('click', () => {
        closeRequestModal();
    });

    // URL input validation
    urlInput?.addEventListener('input', () => {
        const url = urlInput.value.trim();
        const isValid = window.PlaylistRequests?.isValidSpotifyUrl(url);

        if (url && !isValid) {
            urlInput.classList.add('input-error');
            urlError?.classList.remove('hidden');
        } else {
            urlInput.classList.remove('input-error');
            urlError?.classList.add('hidden');
        }

        if (submitBtn) {
            submitBtn.disabled = !isValid;
        }
    });

    // Submit request
    submitBtn?.addEventListener('click', async () => {
        const url = urlInput?.value.trim();
        if (!url || !window.PlaylistRequests?.isValidSpotifyUrl(url)) return;

        // Show loading state
        submitBtn.classList.add('btn--loading');
        submitBtn.disabled = true;

        try {
            const result = await window.PlaylistRequests.submitRequest(url);

            // Close request modal
            closeRequestModal();

            // Show success modal
            const successName = document.getElementById('request-success-name');
            if (successName) {
                successName.textContent = result.playlist_name;
            }
            successModal?.classList.remove('hidden');

            // Refresh the requests list
            await renderRequestsList();

        } catch (error) {
            console.error('Failed to submit request:', error);
            urlInput?.classList.add('input-error');
            if (urlError) {
                // Map worker error.code (e.g. "github_error") to a localized hint
                // via BeatifyI18n. Worker uses lower_snake codes; i18n keys are
                // UPPER_SNAKE under errors.* (#835 follow-up).
                let hint = null;
                if (error.code && window.BeatifyI18n) {
                    const key = 'errors.' + String(error.code).toUpperCase();
                    const translated = BeatifyI18n.t(key);
                    if (translated && translated !== key) hint = translated;
                }
                urlError.textContent = hint || error.message || 'Failed to submit request';
                urlError.classList.remove('hidden');
            }
        } finally {
            submitBtn.classList.remove('btn--loading');
            // Re-enable based on input validity
            const isValid = window.PlaylistRequests?.isValidSpotifyUrl(urlInput?.value.trim() || '');
            submitBtn.disabled = !isValid;
        }
    });

    // Close success modal
    document.getElementById('request-success-close-btn')?.addEventListener('click', () => {
        successModal?.classList.add('hidden');
    });

    successModal?.querySelector('.modal-backdrop')?.addEventListener('click', () => {
        successModal?.classList.add('hidden');
    });

    function closeRequestModal() {
        requestModal?.classList.add('hidden');
        if (urlInput) {
            urlInput.value = '';
            urlInput.classList.remove('input-error');
        }
        urlError?.classList.add('hidden');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.classList.remove('btn--loading');
        }
    }
}

/**
 * Initialize playlist requests display.
 *
 * #939: previously also polled GitHub for issue-status updates, but that
 * fetch ran from the browser straight to api.github.com — unauthenticated,
 * rate-limited, and 403-spamming the console. Removed; the request list
 * still loads from the Beatify backend.
 */
async function initPlaylistRequests() {
    // Render existing requests (loads from backend)
    await renderRequestsList();
}

// REQUEST_STATUS_LABELS + buildRequestRowHtml moved to ./admin/util.js (#1279 step 2)

/**
 * Render the list of playlist requests
 */
async function renderRequestsList() {
    if (!window.PlaylistRequests) {
        document.getElementById('my-requests')?.classList.add('hidden');
        return;
    }

    // Load requests from backend (async)
    const requests = await window.PlaylistRequests.getRequestsForDisplayAsync();

    // Legacy #my-requests section — null-safe so the section can be deleted later
    const section = document.getElementById('my-requests');
    const listContainer = document.getElementById('my-requests-list');
    const emptyState = document.getElementById('my-requests-empty');
    const summary = document.getElementById('my-requests-summary');

    if (!section || !listContainer) return; // section deleted from DOM — home-view modal carries the load

    if (adminState.currentView === 'setup') section.classList.remove('hidden');
    if (summary) summary.textContent = requests.length.toString();

    if (requests.length === 0) {
        listContainer.innerHTML = '';
        emptyState?.classList.remove('hidden');
    } else {
        emptyState?.classList.add('hidden');
        listContainer.innerHTML = requests.map((r) => buildRequestRowHtml(r)).join('');
    }
}

// ============================================
// PWA Install Button (#226)
// ============================================

/**
 * Explicit PWA install prompt — shows 📲 button in admin header.
 * Android: captures beforeinstallprompt → native install dialog.
 * iOS Safari: shows manual "Add to Home Screen" hint.
 * Hidden when already installed (standalone mode).
 */
(function initPwaInstall() {
    const btn = document.getElementById('pwa-install-btn');
    const iosHint = document.getElementById('pwa-ios-hint');
    const iosClose = document.getElementById('pwa-ios-hint-close');
    if (!btn) return;

    // Already installed — stay hidden
    if (window.matchMedia('(display-mode: standalone)').matches ||
        window.navigator.standalone === true) {
        return;
    }

    let deferredPrompt = null;

    // Android / Chrome: capture the install prompt
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        btn.classList.remove('hidden');
    });

    // Hide after successful install
    window.addEventListener('appinstalled', () => {
        btn.classList.add('hidden');
        deferredPrompt = null;
        if (iosHint) iosHint.classList.add('hidden');
    });

    // iOS Safari detection — show button for manual instructions
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isSafari = /safari/i.test(navigator.userAgent) && !/chrome|crios|fxios/i.test(navigator.userAgent);
    if (isIos && isSafari) {
        btn.classList.remove('hidden');
    }

    btn.addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            debug('[PWA] Install outcome:', outcome);
            deferredPrompt = null;
            if (outcome === 'accepted') {
                btn.classList.add('hidden');
            }
        } else if (isIos && iosHint) {
            iosHint.classList.remove('hidden');
        }
    });

    // Close iOS hint
    if (iosClose && iosHint) {
        iosClose.addEventListener('click', () => {
            iosHint.classList.add('hidden');
        });
    }
})();

// ============================================
// Issue #477: Admin Game Phase Views
// ============================================
// (#1279 step 3: connectAdminWebSocket + handleAdminWsMessage moved to
// ./admin/api.js. They call back into admin.js via the initAdminApi() deps —
// notably handleAdminStateUpdate below.)
/**
 * Handle game state update from WebSocket — route to correct phase view.
 */
function handleAdminStateUpdate(data) {
    adminState.currentGame = data;

    // Restore adminState.isPlaying state from player list (survives page reload)
    if (data.players && !adminState.isPlaying) {
        var adminInList = data.players.find(function(p) { return p.is_admin; });
        if (adminInList) {
            adminState.isPlaying = true;
            adminState.adminPlayerName = adminState.adminPlayerName || adminInList.name;
            try { sessionStorage.setItem('beatify_admin_name', adminInList.name); } catch(e) {}
        }
    }

    // #660: Update playing mode banner
    updatePlayingModeBanner();

    // #647: Wake lock for all active game phases
    if (['LOBBY', 'PLAYING', 'REVEAL', 'PAUSED'].includes(data.phase)) {
        _requestWakeLock();
    } else {
        _releaseWakeLock();
    }

    // Hide all phase sections first
    var sections = ['setup-container',
                    'admin-playing-section', 'admin-reveal-section', 'admin-end-section',
                    'admin-control-bar'];
    sections.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // #1048: leaving REVEAL — make sure the auto-advance countdown is torn
    // down so the sticky Next button restores its icon for other phases.
    if (data.phase !== 'REVEAL') {
        _stopRevealAdvanceCountdown();
    }

    // Also hide setup sections
    setupSections.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // #651: Hide start button and validation messages (outside setupSections)
    document.getElementById('start-game')?.classList.add('hidden');
    document.getElementById('playlist-validation-msg')?.classList.add('hidden');
    document.getElementById('media-player-validation-msg')?.classList.add('hidden');

    // Home-view is the LOBBY landing. Once the game advances to PLAYING /
    // REVEAL / PAUSED / END, exit home-mode so the admin-playing-section
    // and admin-control-bar render cleanly instead of overlapping the QR.
    if (data.phase && data.phase !== 'LOBBY' && window.BeatifyHome) {
        window.BeatifyHome.exit();
    }
    // Symmetric re-entry: rematch creates a new LOBBY after END. home-mode
    // was exited on LOBBY → PLAYING, so if we're coming back to LOBBY (e.g.
    // Revanche), restore it so the admin lands back on the home-view (QR +
    // player chips) instead of the legacy #lobby-section.
    if (data.phase === 'LOBBY' && window.BeatifyHome &&
        !document.body.classList.contains('home-mode')) {
        window.BeatifyHome.enter();
    }

    switch (data.phase) {
        case 'LOBBY':
            showLobbyView(data);
            break;
        case 'PLAYING':
            // If the admin has joined as a player, flip them to the player UI
            // automatically instead of staying on the admin-playing view. The
            // player page carries its own slim admin-control-bar, so control
            // isn't lost — and the "Admin View" exit is available on /play.
            // Require adminState.adminSessionId so /play can reconnect via session_id
            // rather than a racey fresh join (ERR_NAME_TAKEN otherwise).
            if (adminState.adminPlayerName && adminState.adminSessionId && adminState.currentGame && adminState.currentGame.game_id) {
                handleSwitchToPlayerView();
                return;
            }
            showAdminPlayingView(data);
            break;
        case 'REVEAL':
            showAdminRevealView(data);
            break;
        case 'END':
            showAdminEndView(data);
            break;
        case 'PAUSED':
            showAdminPausedView(data);
            break;
        default:
            showSetupView();
    }
}

// ---- #660: Playing mode banner + switch button ----

/**
 * Show/hide the "You're playing as {name}" banner on admin page.
 */
function updatePlayingModeBanner() {
    var bannerIds = ['admin-playing-banner', 'admin-reveal-playing-banner'];
    var nameIds = ['admin-playing-name', 'admin-reveal-playing-name'];

    bannerIds.forEach(function(id, i) {
        var banner = document.getElementById(id);
        if (!banner) return;
        if (adminState.isPlaying && adminState.adminPlayerName) {
            var nameEl = document.getElementById(nameIds[i]);
            if (nameEl) nameEl.textContent = adminState.adminPlayerName;
            banner.classList.remove('hidden');
        } else {
            banner.classList.add('hidden');
        }
    });
}

/**
 * Handle switch-to-player-view button click (#660).
 */
function handleSwitchToPlayerView() {
    var gameId = adminState.currentGame && adminState.currentGame.game_id;
    if (gameId && adminState.adminPlayerName) {
        try {
            sessionStorage.setItem('beatify_admin_name', adminState.adminPlayerName);
            sessionStorage.setItem('beatify_is_admin', 'true');
            if (adminState.adminSessionId) {
                sessionStorage.setItem('beatify_session', adminState.adminSessionId);
            }
        } catch(e) {}
        // Pass session_id in the URL so /play can reconnect via
        // {type:'reconnect'} — avoids the name-collision race where the
        // old admin WS hasn't disconnected yet and the fresh join gets
        // ERR_NAME_TAKEN from player_registry.add_player.
        var url = '/beatify/play?game=' + encodeURIComponent(gameId);
        if (adminState.adminSessionId) {
            url += '&session=' + encodeURIComponent(adminState.adminSessionId);
        }
        window.location.href = url;
    }
}

// Wire up switch buttons
document.getElementById('switch-to-player-view')?.addEventListener('click', handleSwitchToPlayerView);
document.getElementById('switch-to-player-view-reveal')?.addEventListener('click', handleSwitchToPlayerView);

// ---- PLAYING phase view (#653: mirrors player layout) ----

function showAdminPlayingView(data) {
    var section = document.getElementById('admin-playing-section');
    if (!section) return;
    section.classList.remove('hidden');

    // #805: clear any pause-recovery banner left over from a prior PAUSED phase.
    _hidePauseRecoveryBanner();

    // Show fixed control bar (matches player admin-control-bar)
    var controlBar = document.getElementById('admin-control-bar');
    if (controlBar) controlBar.classList.remove('hidden');

    // Round info (player-style separate spans)
    var roundEl = document.getElementById('admin-current-round');
    var totalEl = document.getElementById('admin-total-rounds');
    if (roundEl) roundEl.textContent = data.round || '?';
    if (totalEl) totalEl.textContent = data.total_rounds || '?';

    // Difficulty badge
    var diffBadge = document.getElementById('admin-game-difficulty-badge');
    if (diffBadge && data.difficulty) {
        diffBadge.textContent = data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1);
    }

    // Album cover (large centered)
    var artEl = document.getElementById('admin-album-art');
    if (artEl && data.song && data.song.album_art) artEl.src = data.song.album_art;

    // Admin-only song details (year, fun fact) — only for spectator admin (#660).
    // Fair-play guard: hide if the admin is a participant. We OR three signals
    // so a reconnect race can't open a spoiler leak (#882):
    //   - adminState.isPlaying            — runtime flag, but resets to false on reconnect
    //                            until the player list is re-processed
    //   - sessionStorage name  — set the moment the admin joins as a player;
    //                            survives reload/reconnect, the durable signal
    //   - players[].is_admin   — the incoming list, may briefly lag
    // If ANY says "participant", spoilers stay hidden. A genuine spectator
    // never sets beatify_admin_name, so this can't wrongly hide from them.
    var yearEl = document.getElementById('admin-song-year');
    var factEl = document.getElementById('admin-song-funfact');
    var adminJoinedAsPlayer = false;
    try { adminJoinedAsPlayer = !!sessionStorage.getItem('beatify_admin_name'); } catch (e) { /* ignore */ }
    var adminIsParticipant = adminState.isPlaying
        || adminJoinedAsPlayer
        || (data.players || []).some(function(p) { return p.is_admin; });
    if (data.admin_song && !adminIsParticipant) {
        if (yearEl) {
            if (data.admin_song.year) {
                yearEl.textContent = '📅 ' + data.admin_song.year;
                yearEl.classList.remove('hidden');
            } else { yearEl.classList.add('hidden'); }
        }
        if (factEl) {
            var lang = BeatifyI18n.getLanguage();
            var fact = (lang !== 'en' && data.admin_song['fun_fact_' + lang])
                ? data.admin_song['fun_fact_' + lang] : data.admin_song.fun_fact;
            if (fact) {
                factEl.textContent = '💡 ' + fact;
                factEl.classList.remove('hidden');
            } else { factEl.classList.add('hidden'); }
        }
    } else {
        // Hide spoilers when admin is playing (fair play) (#660)
        if (yearEl) yearEl.classList.add('hidden');
        if (factEl) factEl.classList.add('hidden');
    }

    // Countdown timer (big centered, player style)
    startAdminCountdown(data.deadline);

    // Submission tracker (player dot format)
    renderAdminSubmissionDots(data.players);

    // Banners
    var lastBanner = document.getElementById('admin-last-round');
    if (lastBanner) lastBanner.classList.toggle('hidden', !data.last_round);
    var introBadge = document.getElementById('admin-intro-badge');
    if (introBadge) introBadge.classList.toggle('hidden', !data.is_intro_round);
    var closestBadge = document.getElementById('admin-closest-wins-badge');
    if (closestBadge) closestBadge.classList.toggle('hidden', !data.closest_wins_mode);

    // Intro splash overlay with confirm button
    var introSplash = document.getElementById('admin-intro-splash');
    if (introSplash) introSplash.classList.toggle('hidden', !data.intro_splash_pending);

    // Leaderboard (player-style entries)
    renderAdminLeaderboard(data.leaderboard);
}

/**
 * Render player-style submission dots (matches player-game.js renderSubmissionTracker).
 */
// renderAdminSubmissionDots moved to ./admin/sections/render-helpers.js (#1279 step 4)

function startAdminCountdown(deadline) {
    if (countdownInterval) clearInterval(countdownInterval);

    var timerEl = document.getElementById('admin-timer');
    if (!timerEl || !deadline) return;

    function tick() {
        var now = Date.now();
        var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));
        timerEl.textContent = remaining;
        // Use player CSS classes for timer states
        timerEl.classList.toggle('timer--warning', remaining <= 10);
        timerEl.classList.toggle('timer--critical', remaining <= 5);
        if (remaining <= 0) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
    }

    tick();
    countdownInterval = setInterval(tick, 1000);
}

// ---- REVEAL phase view (#653: mirrors player layout) ----

function showAdminRevealView(data) {
    var section = document.getElementById('admin-reveal-section');
    if (!section) return;
    section.classList.remove('hidden');

    // #805: clear any pause-recovery banner left over from a prior PAUSED phase.
    _hidePauseRecoveryBanner();

    // #1012 follow-up: idle-halt notice — the round ended with zero guesses,
    // playback has stopped, and the game is holding here until "Next round".
    var idleHalt = document.getElementById('admin-reveal-idle-halt');
    if (idleHalt) idleHalt.classList.toggle('hidden', !data.idle_halt);

    // Show control bar during reveal too (admin can skip, end game)
    var controlBar = document.getElementById('admin-control-bar');
    if (controlBar) controlBar.classList.remove('hidden');

    // #1048: replace the Next button icon with a 1-Hz auto-advance countdown
    // when one is running. Idle-halt and Off both keep the plain icon.
    _updateRevealAdvanceCountdown(data);

    // Emotion display (summary for spectator admin)
    var emotionEl = document.getElementById('admin-reveal-emotion');
    if (emotionEl && data.players) {
        var players = data.players || [];
        var exactCount = players.filter(function(p) { return p.years_off === 0 && !p.missed_round; }).length;
        var avgOff = 0;
        var guessers = players.filter(function(p) { return !p.missed_round && p.years_off != null; });
        if (guessers.length > 0) {
            avgOff = Math.round(guessers.reduce(function(s, p) { return s + (p.years_off || 0); }, 0) / guessers.length);
        }
        var emotionText = '';
        var emotionClass = 'reveal-emotion--wrong';
        if (exactCount > 0) {
            emotionText = '🎯 ' + exactCount + 'x ' + (BeatifyI18n.t('reveal.exact') || 'Exact!');
            emotionClass = 'reveal-emotion--exact';
        } else if (avgOff <= 3) {
            emotionText = '🔥 ' + (BeatifyI18n.t('reveal.soClose') || 'So close!');
            emotionClass = 'reveal-emotion--close';
        } else if (avgOff <= 10) {
            emotionText = '👀 Ø ' + (BeatifyI18n.t('reveal.yearsOff', { years: avgOff }) || avgOff + ' years off');
            emotionClass = 'reveal-emotion--wrong';
        } else {
            emotionText = '😅 Ø ' + (BeatifyI18n.t('reveal.yearsOff', { years: avgOff }) || avgOff + ' years off');
            emotionClass = 'reveal-emotion--wrong';
        }
        emotionEl.className = 'reveal-emotion-inline ' + emotionClass;
        emotionEl.innerHTML = '<span class="reveal-emotion-text">' + emotionText + '</span>';
        emotionEl.classList.remove('hidden');
    }

    // Round info
    var roundEl = document.getElementById('admin-reveal-round');
    var totalEl = document.getElementById('admin-reveal-total');
    if (roundEl) roundEl.textContent = data.round || '?';
    if (totalEl) totalEl.textContent = data.total_rounds || '?';

    // Song hero
    if (data.song) {
        var titleEl = document.getElementById('admin-reveal-song-title');
        var artistEl = document.getElementById('admin-reveal-song-artist');
        var yearEl = document.getElementById('admin-reveal-correct-year');
        var artEl = document.getElementById('admin-reveal-album-art');
        if (titleEl) titleEl.textContent = data.song.title || '';
        if (artistEl) artistEl.textContent = data.song.artist || '';
        if (yearEl) yearEl.textContent = data.song.year || '';
        if (artEl && data.song.album_art) artEl.src = data.song.album_art;
    }

    // Difficulty badge
    var diffBadge = document.getElementById('admin-reveal-difficulty-badge');
    if (diffBadge && data.difficulty) {
        diffBadge.textContent = data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1);
    }

    // Fun fact
    var funFactContainer = document.getElementById('admin-fun-fact-container');
    var funFactText = document.getElementById('admin-fun-fact-text');
    if (funFactContainer && data.song) {
        var lang = BeatifyI18n.getLanguage();
        var fact = (lang !== 'en' && data.song['fun_fact_' + lang])
            ? data.song['fun_fact_' + lang] : data.song.fun_fact;
        if (fact) {
            funFactText.textContent = fact;
            funFactContainer.classList.remove('hidden');
        } else {
            funFactContainer.classList.add('hidden');
        }
    }

    // Artist challenge reveal
    var artistReveal = document.getElementById('admin-artist-reveal-section');
    if (artistReveal) {
        if (data.artist_challenge && data.artist_challenge.correct_answer) {
            document.getElementById('admin-artist-reveal-name').textContent = data.artist_challenge.correct_answer;
            artistReveal.classList.remove('hidden');
        } else {
            artistReveal.classList.add('hidden');
        }
    }

    // Movie challenge reveal
    var movieReveal = document.getElementById('admin-movie-reveal-section');
    if (movieReveal) {
        if (data.movie_challenge && data.movie_challenge.correct_answer) {
            document.getElementById('admin-movie-reveal-name').textContent = data.movie_challenge.correct_answer;
            movieReveal.classList.remove('hidden');
        } else {
            movieReveal.classList.add('hidden');
        }
    }

    // #660: Personal result when admin is playing
    var personalEl = document.getElementById('admin-reveal-personal');
    if (personalEl) {
        if (adminState.isPlaying && adminState.adminPlayerName && data.players) {
            var adminPlayer = data.players.find(function(p) { return p.is_admin; });
            if (adminPlayer) {
                var guessEl = document.getElementById('admin-reveal-my-guess');
                var accuracyEl = document.getElementById('admin-reveal-my-accuracy');
                var scoreEl = document.getElementById('admin-reveal-my-score');

                if (adminPlayer.missed_round) {
                    if (guessEl) guessEl.textContent = '—';
                    if (accuracyEl) accuracyEl.textContent = BeatifyI18n.t('reveal.noGuessShort') || 'Missed';
                } else {
                    var yearsOff = adminPlayer.years_off || 0;
                    if (guessEl) guessEl.textContent = adminPlayer.guess || '—';
                    if (accuracyEl) {
                        accuracyEl.textContent = yearsOff === 0
                            ? (BeatifyI18n.t('reveal.exact') || 'Exact!')
                            : (BeatifyI18n.t('reveal.shortOff', { years: yearsOff }) || yearsOff + ' off');
                    }
                }
                if (scoreEl) scoreEl.textContent = '+' + (adminPlayer.round_score || 0);
                personalEl.classList.remove('hidden');
            } else {
                personalEl.classList.add('hidden');
            }
        } else {
            personalEl.classList.add('hidden');
        }
    }

    // All guesses grid (player-style result cards)
    renderAdminResultCards(data.players, data.closest_wins_mode, data.song ? data.song.year : null);

    // Leaderboard (player-style entries)
    renderAdminLeaderboard(data.leaderboard);
}

/**
 * #1048: 1-Hz countdown on the sticky Next button while REVEAL auto-advance
 * runs. Replaces the ⏭️ icon with the remaining seconds; falls back to the
 * icon when auto-advance is Off, idle-halt is active, or the deadline is
 * missing from the state payload.
 */
function _stopRevealAdvanceCountdown() {
    if (revealAdvanceInterval) {
        clearInterval(revealAdvanceInterval);
        revealAdvanceInterval = null;
    }
    var iconEl = document.querySelector('#admin-skip-round .control-icon');
    if (iconEl) {
        iconEl.classList.remove('is-countdown');
        if (revealAdvanceOrigIcon !== null) {
            iconEl.textContent = revealAdvanceOrigIcon;
        }
    }
}

function _updateRevealAdvanceCountdown(data) {
    var iconEl = document.querySelector('#admin-skip-round .control-icon');
    if (!iconEl) return;

    var advance = data.reveal_auto_advance || 0;
    var startedAt = data.reveal_started_at;
    if (advance <= 0 || data.idle_halt || !startedAt) {
        _stopRevealAdvanceCountdown();
        return;
    }

    if (revealAdvanceOrigIcon === null) {
        revealAdvanceOrigIcon = iconEl.textContent;
    }

    var deadline = startedAt + advance * 1000;

    function tick() {
        var remainingMs = deadline - Date.now();
        var remaining = Math.max(0, Math.ceil(remainingMs / 1000));
        iconEl.textContent = String(remaining);
        iconEl.classList.add('is-countdown');
        if (remaining <= 0 && revealAdvanceInterval) {
            // Stop ticking; the server will broadcast PLAYING shortly and
            // showAdminPlayingView's setup tears the countdown down.
            clearInterval(revealAdvanceInterval);
            revealAdvanceInterval = null;
        }
    }

    if (revealAdvanceInterval) clearInterval(revealAdvanceInterval);
    tick();
    revealAdvanceInterval = setInterval(tick, 1000);
}

// renderAdminLeaderboard, renderAdminResultCards, renderAdminChallengeOptions moved to ./admin/sections/render-helpers.js (#1279 step 4)

// ---- END phase view ----

function showAdminEndView(data) {
    var section = document.getElementById('admin-end-section');
    if (!section) return;
    section.classList.remove('hidden');

    // Podium (top 3 from leaderboard)
    if (data.leaderboard) {
        for (var i = 1; i <= 3; i++) {
            var entry = data.leaderboard.find(function(e) { return e.rank === i; });
            var nameEl = document.getElementById('admin-podium-' + i + '-name');
            var scoreEl = document.getElementById('admin-podium-' + i + '-score');
            if (nameEl) nameEl.textContent = entry ? entry.name : '---';
            if (scoreEl) scoreEl.textContent = entry ? entry.score : '0';
        }
    }

    // Final leaderboard (player-style entries)
    if (data.leaderboard) {
        renderAdminLeaderboard(data.leaderboard, 'admin-end-leaderboard');
    }

    // Clean up game state for admin
    adminState.isPlaying = false;
    adminState.adminPlayerName = null;
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}

// ---- PAUSED phase view ----

/**
 * #805: Show/hide the recovery banner based on pause_reason.
 *
 * Only error-driven pauses (media_player_error, no_songs_available) get the
 * recovery UI. Admin-disconnect pauses resume automatically on rejoin and
 * don't need a button.
 */
// _providerDisplayName moved to ./admin/sections/render-helpers.js (#1279 step 4)

function _renderPauseRecoveryBanner(data) {
    var banner = document.getElementById('admin-pause-recovery');
    if (!banner) return;
    var reason = data && data.pause_reason ? data.pause_reason : '';
    var detail = data && data.last_error_detail ? data.last_error_detail : '';
    var providerKey = data && data.provider ? data.provider : '';

    var isErrorPause = reason === 'media_player_error' || reason === 'no_songs_available';
    if (!isErrorPause) {
        banner.classList.add('hidden');
        return;
    }

    var msgEl = document.getElementById('admin-pause-recovery-message');
    if (msgEl) {
        var providerName = _providerDisplayName(providerKey);
        var msg;
        if (reason === 'no_songs_available') {
            msg = BeatifyI18n.t('admin.pauseRecovery.noSongsAvailable') ||
                'No playable songs left for this provider. Resume to retry, or end the game.';
        } else if (providerName) {
            // #808 follow-up: name the actual provider so the user knows
            // which one to re-authenticate in Music Assistant.
            var template = BeatifyI18n.t('admin.pauseRecovery.mediaPlayerError') ||
                'Playback did not start — the speaker is not responding. This often means {provider} in Music Assistant needs re-authentication — open Settings → Music Assistant → {provider} → Reconnect, then click Resume.';
            msg = template.replace(/\{provider\}/g, providerName);
        } else {
            msg = BeatifyI18n.t('admin.pauseRecovery.mediaPlayerErrorGeneric') ||
                'Playback did not start — the speaker is not responding. This often means your music provider in Music Assistant needs re-authentication — open Settings → Music Assistant → your provider → Reconnect, then click Resume.';
        }
        msgEl.textContent = msg;
    }

    var detailEl = document.getElementById('admin-pause-recovery-detail');
    if (detailEl) {
        if (detail) {
            detailEl.textContent = detail;
            detailEl.classList.remove('hidden');
        } else {
            detailEl.textContent = '';
            detailEl.classList.add('hidden');
        }
    }

    banner.classList.remove('hidden');
}

function _hidePauseRecoveryBanner() {
    var banner = document.getElementById('admin-pause-recovery');
    if (banner) banner.classList.add('hidden');
}

function showAdminPausedView(data) {
    // Reuse the playing section but show pause overlay
    var section = document.getElementById('admin-playing-section');
    if (!section) return;
    section.classList.remove('hidden');
    // Show control bar during pause
    var controlBar = document.getElementById('admin-control-bar');
    if (controlBar) controlBar.classList.remove('hidden');

    var timerEl = document.getElementById('admin-timer');
    if (timerEl) timerEl.textContent = '⏸ ' + (BeatifyI18n.t('game.paused') || 'Paused');
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }

    // #805: surface the recovery banner if the pause was caused by a
    // playback error. Admin-disconnect pauses leave the banner hidden.
    _renderPauseRecoveryBanner(data);
}

// ---- Admin game controls (sent via WS) ----
// (#1279 step 3: sendAdminCommand moved to ./admin/api.js — imported above.)

function adminNextRound() {
    sendAdminCommand({ type: 'admin', action: 'next_round' });
}

function adminStopSong() {
    sendAdminCommand({ type: 'admin', action: 'stop_song' });
}

function adminVolumeUp() {
    sendAdminCommand({ type: 'admin', action: 'set_volume', direction: 'up' });
}

function adminVolumeDown() {
    sendAdminCommand({ type: 'admin', action: 'set_volume', direction: 'down' });
}

function adminDismissGame() {
    if (isAdminWsOpen()) {
        sendAdminWs({ type: 'admin', action: 'dismiss_game' });
    }
    adminState.cachedQRUrl = null;
    adminState.isPlaying = false;
    adminState.adminPlayerName = null;
    // #1080: "Start New Game" gives Restart semantics — a fresh wizard with
    // no pre-selected speaker or playlists. The Rematch button is the
    // keep-state path (same players, same setup, back to lobby); this is
    // the fresh path. Without clearing the wizard re-hydrates speaker +
    // playlists from localStorage and the user sees their old picks
    // pre-selected, which reads as "the reset didn't work."
    try {
        localStorage.removeItem(STORAGE_LAST_PLAYER);
        localStorage.removeItem(STORAGE_GAME_SETTINGS);
        localStorage.removeItem('beatify_wizard_state');
    } catch (e) { /* private mode */ }
    if (window.BeatifyHome) window.BeatifyHome.exit();
    if (window.BeatifyWizard && typeof window.BeatifyWizard.show === 'function') {
        window.BeatifyWizard.show(1);
    } else {
        showSetupView(); // fallback if wizard module failed to load
    }
}


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
            debug('[Admin] SW registered:', registration.scope);
        }).catch(function(error) {
            console.warn('[Admin] SW registration failed:', error);
        });
    });
}
