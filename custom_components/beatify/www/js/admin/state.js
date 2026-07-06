/**
 * Beatify Admin — centralized mutable setup-/game-state (#1279 Schritt 5/6).
 *
 * Third real ES module of the admin decomposition and the enabler for the
 * deferred setup-section split (step 4b). Previously these ~24 values lived as
 * top-level `let` bindings inside admin.js. Once admin.js became an ES module
 * (step 2), those bindings stopped being global — but they are also
 * *mutated* across module boundaries (the WS hub in api.js, and soon the
 * setup-section modules in step 4b).
 *
 * ES modules export `let` bindings as LIVE but READ-ONLY views: an importer
 * sees updates but cannot assign. So `import { selectedProvider }` + a later
 * `selectedProvider = x` in another module would throw ("Assignment to
 * constant variable"). To share *mutable* state across modules we therefore
 * export ONE plain mutable object, `adminState`. Every consumer reads
 * `adminState.x` and writes `adminState.x = …` — the object identity is
 * stable, so all modules see the same live values. This is the lowest-friction
 * pattern (no getter/setter pair per field, no DI wiring) and the one with the
 * fewest call-site shapes to touch.
 *
 * What is centralized here = the setup-/game-state the start-game/lobby core
 * and the setup-sections share. What is deliberately NOT here: pure infra
 * handles that are admin-private and never crossed a module boundary —
 * timer/interval ids (`lobbyPollingInterval`, `countdownInterval`,
 * `revealAdvanceInterval`, `revealAdvanceOrigIcon`), the wake-lock internals,
 * the `_homeStartBtnHTML` DOM stash and the `rematchInProgress` debounce flag.
 * Those stay as admin.js `let`s; moving them would add churn without unblocking
 * step 4b.
 *
 * `currentGame` note: api.js reads it via the injected `getCurrentGame()`
 * closure and util.js via the `setCurrentGameResolver()` closure. admin.js
 * keeps both registrations but now points them at `adminState.currentGame`, so
 * both keep seeing live updates after every `adminState.currentGame = …`.
 */

export const adminState = {
    // --- playlists / media-player setup ---
    selectedPlaylists: [],
    playlistData: [],
    playlistDocsUrl: '',
    activeFilterTags: ['all'],          // Tag filter state (Issue #70)
    selectedMediaPlayer: null,          // { entityId, state } or null
    mediaPlayerDocsUrl: '',
    mediaPlayers: [],                   // #1627: raw players payload from /api/status
    mediaPlayerTwinRemap: {},            // #1627: native entity_id → MA twin entity_id
    // Active filter state per category (Issue #70 filter bar)
    activeFilters: { decade: '', style: '', region: '', special: '' },

    // --- view / game ---
    currentView: 'setup',
    currentGame: null,
    cachedQRUrl: null,
    setupComplete: false,               // #1663: server-side "is configured?" flag

    // --- game settings ---
    selectedLanguage: 'en',             // Story 12.4
    selectedDuration: 45,               // Story 13.1
    revealAutoAdvance: 0,               // #1012 (0 = off, default)
    selectedDifficulty: 'normal',       // Story 14.1
    selectedProvider: 'spotify',        // Story 17.2
    hasMusicAssistant: false,

    // --- bonus / mode flags ---
    artistChallengeEnabled: true,       // Story 20.7
    movieQuizEnabled: true,             // #947
    introModeEnabled: false,            // Issue #23
    closestWinsModeEnabled: false,      // Issue #442
    titleArtistModeEnabled: false,      // #1180
    rampupOrderEnabled: false,          // Issue #1726
    finaleDoubleEnabled: false,         // Issue #1725
    finaleTiebreakerEnabled: false,     // Issue #1725

    // --- lobby / admin-as-player (#477) ---
    previousLobbyPlayers: [],           // Story 16.8
    adminPlayerName: null,              // set when admin joins as player
    adminSessionId: null,               // set on join_ack (reconnect token)
    isPlaying: false,                   // admin participating as a player
};
