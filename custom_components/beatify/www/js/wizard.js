/**
 * Beatify first-run wizard.
 *
 * Documented in DESIGN.md (## Patterns → First-run wizard).
 * State is driven by localStorage — we do NOT rely on /api/status fields that
 * don't exist (media_players[].selected, credentials.any). The wizard tracks
 * its own progress explicitly.
 *
 * ES module. Loaded via <script type="module"> in admin.html.
 * Pure helpers are also imported by custom_components/beatify/www/js/__tests__/wizard.test.js.
 */

const LS_WIZARD_STATE = 'beatify_wizard_state';   // 'step1'|'step2'|'step3'|'step4'|'done'|'dismissed'
const LS_SELECTED_PLAYER = 'beatify_last_player'; // set by admin.js when a speaker is picked
const LS_GAME_SETTINGS = 'beatify_game_settings'; // set by admin.js, contains {provider, ...}

// ------------------------------------------------------------------
// Pure helpers — exported for vitest
// ------------------------------------------------------------------

function _safeGet(ls, key) {
    try { return ls ? ls.getItem(key) : null; } catch (e) { return null; }
}

/**
 * Figure out the first incomplete required step (1-3) from localStorage signals.
 * Returns null once all three required steps are complete. Pure function.
 */
export function resumeAtStep(localStorage) {
    const state = _safeGet(localStorage, LS_WIZARD_STATE);
    if (state === 'done') return null;

    // Fast path: explicit step stored
    if (state === 'step2') return 2;
    if (state === 'step3') return 3;
    if (state === 'step4') return 4;
    if (state === 'step5') return 5;

    // Otherwise infer from the admin's own signals
    if (!_safeGet(localStorage, LS_SELECTED_PLAYER)) return 1;

    const settingsRaw = _safeGet(localStorage, LS_GAME_SETTINGS);
    let hasProvider = false;
    try {
        if (settingsRaw) hasProvider = !!JSON.parse(settingsRaw).provider;
    } catch (e) { /* malformed — treat as no provider */ }
    if (!hasProvider) return 2;

    return 3;
}

/**
 * Decide whether the wizard should appear on admin load.
 * True when the user has neither completed nor explicitly dismissed it.
 */
export function shouldTrigger(localStorage) {
    const state = _safeGet(localStorage, LS_WIZARD_STATE);
    if (state === 'done' || state === 'dismissed') return false;

    // Fresh user OR partial progress → show
    if (!state) {
        // No wizard state at all — show only if nothing was configured yet via the regular admin
        const hasPlayer = !!_safeGet(localStorage, LS_SELECTED_PLAYER);
        return !hasPlayer;
    }
    return true;
}

/**
 * "Finish setup" pill is visible when the user dismissed the wizard AND
 * required steps (inferred from localStorage) are still incomplete.
 */
export function shouldShowPill(localStorage) {
    const state = _safeGet(localStorage, LS_WIZARD_STATE);
    if (state !== 'dismissed') return false;
    return resumeAtStep(localStorage) !== null;
}

// ------------------------------------------------------------------
// DOM-driven controller (browser-only below this line)
// ------------------------------------------------------------------

let currentStep = 1;
let cachedStatus = null;
let cachedCapabilities = null;
let chosenSpeaker = null;
let chosenProvider = null;
const chosenPlaylists = new Set(); // paths — multi-select
// Step 4 (game mode) — default to what admin.js uses when beatify_game_settings is empty
let chosenDifficulty = 'normal';
let chosenDuration = 45;
let chosenLanguage = 'en';
// Game-mode toggles (defaults match admin.js: artistChallenge on, intro off, closestWins off)
let chosenArtistChallenge = true;
let chosenIntroMode = false;
let chosenClosestWins = false;
const chosenLevelUps = { lights: false, tts: false };
// Details the user sets when a level-up is toggled on
let cachedLights = null; // HA lights from /api/lights
const chosenLightEntityIds = new Set();
let chosenLightIntensity = 'medium'; // subtle | medium | party
let chosenLightMode = 'dynamic'; // static | dynamic | wled
const chosenWledPresets = {}; // { LOBBY: 1, PLAYING: 2, ... }
const WLED_PHASES = ['LOBBY', 'PLAYING', 'REVEAL', 'STREAK', 'COUNTDOWN', 'END'];
let chosenTtsEntityId = '';
let chosenTtsAnnounceStart = true;
let chosenTtsAnnounceWinner = true;

const TOTAL_STEPS = 5; // 1:speakers 2:music 3:playlist 4:game-mode 5:level-up (+ done frame)

function _t(key, fallback) {
    if (typeof window !== 'undefined' && window.BeatifyI18n && typeof window.BeatifyI18n.translate === 'function') {
        return window.BeatifyI18n.translate(key) || fallback;
    }
    return fallback;
}

async function _fetchStatus() {
    try {
        const r = await fetch('/beatify/api/status');
        if (!r.ok) return null;
        return await r.json();
    } catch (e) {
        return null;
    }
}

async function _fetchCapabilities() {
    try {
        const r = await fetch('/beatify/api/capabilities');
        if (!r.ok) return { has_lights: true, has_tts: true };
        return await r.json();
    } catch (e) {
        return { has_lights: true, has_tts: true };
    }
}

async function _fetchLights() {
    try {
        const r = await fetch('/beatify/api/lights');
        if (!r.ok) return [];
        const data = await r.json();
        return (data && data.lights) || [];
    } catch (e) {
        return [];
    }
}

// Hydrate level-up details from the existing admin localStorage shapes
function _hydrateLevelUpDetails() {
    try {
        const rawL = localStorage.getItem('beatify_party_lights');
        if (rawL) {
            const s = JSON.parse(rawL);
            if (Array.isArray(s.lights)) s.lights.forEach((id) => chosenLightEntityIds.add(id));
            if (s.intensity) chosenLightIntensity = s.intensity;
            if (s.light_mode) chosenLightMode = s.light_mode;
            if (s.wled_presets && typeof s.wled_presets === 'object') {
                Object.assign(chosenWledPresets, s.wled_presets);
            }
        }
        const rawT = localStorage.getItem('beatify_tts');
        if (rawT) {
            const s = JSON.parse(rawT);
            if (s.entity_id) chosenTtsEntityId = s.entity_id;
            if (typeof s.announce_game_start === 'boolean') chosenTtsAnnounceStart = s.announce_game_start;
            if (typeof s.announce_winner === 'boolean') chosenTtsAnnounceWinner = s.announce_winner;
            if (typeof s.enabled === 'boolean' && s.enabled) chosenLevelUps.tts = true;
        }
    } catch (e) { /* ignore */ }
}

function _setProgress(step) {
    const segs = document.querySelectorAll('#wiz-progress .wiz-seg');
    segs.forEach((seg, i) => {
        const stepNum = i + 1;
        seg.classList.remove('filled', 'active');
        if (stepNum < step) seg.classList.add('filled');
        else if (stepNum === step) seg.classList.add('active');
    });
}

function _showFrame(n) {
    document.querySelectorAll('.wiz-frame').forEach((frame) => {
        const frameNum = parseInt(frame.dataset.frame, 10);
        if (frameNum === n) frame.removeAttribute('hidden');
        else frame.setAttribute('hidden', '');
    });
    currentStep = n;
    _setProgress(Math.min(n, TOTAL_STEPS));
    _updateCta();
    // Persist wizard state so refresh / revisit resumes at the right step.
    // Skip step 6 (done) here — _advance() writes the final 'done' state.
    if (n >= 1 && n <= 5) {
        try { localStorage.setItem(LS_WIZARD_STATE, `step${n}`); } catch (e) { /* private mode */ }
    }
}

function _updateCta() {
    const nextBtn = document.getElementById('wiz-next');
    const backBtn = document.getElementById('wiz-back');
    const skipBtn = document.getElementById('wiz-skip');
    if (!nextBtn || !backBtn) return;

    backBtn.style.display = currentStep > 1 ? '' : 'none';

    if (currentStep === 1) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenSpeaker;
    } else if (currentStep === 2) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenProvider;
    } else if (currentStep === 3) {
        const n = chosenPlaylists.size;
        nextBtn.textContent = n > 1
            ? `${_t('wizard.continue', 'Continue')} (${n})`
            : _t('wizard.continue', 'Continue');
        nextBtn.disabled = n === 0;
    } else if (currentStep === 4) {
        // Game-mode step: always has valid defaults, Continue is always enabled
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = false;
    } else if (currentStep === 5) {
        nextBtn.textContent = _t('wizard.finish', 'Finish');
        nextBtn.disabled = false;
    } else if (currentStep === 6) {
        nextBtn.textContent = _t('wizard.goToLobby', 'Go to lobby');
        nextBtn.disabled = false;
    }

    if (skipBtn) skipBtn.style.display = currentStep < 6 ? '' : 'none';
}

// ------------------------------------------------------------------
// Step renderers
// ------------------------------------------------------------------

// Match admin.js:126 PLATFORM_LABELS so the wizard shows "Sonos" / "Music Assistant"
// instead of the raw lowercase HA platform slug.
const PLATFORM_LABELS = {
    music_assistant: 'Music Assistant',
    sonos: 'Sonos',
    alexa_media: 'Alexa',
    alexa: 'Alexa',
};

function _platformLabel(raw) {
    if (!raw) return '';
    return PLATFORM_LABELS[raw] || raw;
}

// SVG icon for the speaker-row avatar. Single generic speaker silhouette —
// the platform name already appears below, no need to disambiguate by icon.
const SPEAKER_ICON = `<svg class="wiz-row-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="15" r="3"/><line x1="12" y1="7" x2="12.01" y2="7"/></svg>`;
const PLAYLIST_ICON = `<svg class="wiz-row-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`;

function _renderSpeakers() {
    const list = document.getElementById('wiz-speaker-list');
    if (!list) return;
    const players = (cachedStatus && cachedStatus.media_players) || [];
    if (players.length === 0) {
        list.innerHTML = `<div class="wiz-row" style="cursor:default"><div class="wiz-row-text"><div class="wiz-row-name">${_t(
            'wizard.step1.empty',
            'No speakers found yet'
        )}</div><div class="wiz-row-sub">${_t(
            'wizard.step1.emptyHint',
            'Install Music Assistant and refresh'
        )}</div></div></div>`;
        return;
    }
    list.innerHTML = players
        .map((p) => {
            const selected = chosenSpeaker === p.entity_id;
            return `<button type="button" class="wiz-row ${selected ? 'selected' : ''}" data-entity-id="${p.entity_id}">
          <div class="wiz-row-avatar">${SPEAKER_ICON}</div>
          <div class="wiz-row-text">
            <div class="wiz-row-name">${p.friendly_name || p.entity_id}</div>
            <div class="wiz-row-sub">${_platformLabel(p.platform) || p.state || ''}</div>
          </div>
          ${selected ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" class="wiz-row-check"><path d="M5 12l5 5L20 7"/></svg>' : ''}
        </button>`;
        })
        .join('');
    list.querySelectorAll('.wiz-row[data-entity-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
            chosenSpeaker = btn.dataset.entityId;
            try { localStorage.setItem(LS_SELECTED_PLAYER, chosenSpeaker); } catch (e) { /* private mode */ }
            _renderSpeakers();
            _updateCta();
        });
    });
}

const PROVIDERS = [
    { id: 'spotify', label: 'Spotify' },
    { id: 'apple_music', label: 'Apple Music' },
    { id: 'youtube_music', label: 'YouTube Music' },
    { id: 'tidal', label: 'Tidal' },
    { id: 'deezer', label: 'Deezer' },
];

function _renderProviders() {
    const list = document.getElementById('wiz-provider-list');
    if (!list) return;
    list.innerHTML = PROVIDERS.map((p) => {
        const active = chosenProvider === p.id;
        return `<button type="button" class="wiz-provider-chip ${active ? 'active' : ''}" data-provider="${p.id}">${p.label}</button>`;
    }).join('');
    list.querySelectorAll('[data-provider]').forEach((btn) => {
        btn.addEventListener('click', () => {
            chosenProvider = btn.dataset.provider;
            _renderProviders();
            _updateCta();
        });
    });
}

function _renderPlaylists() {
    const list = document.getElementById('wiz-playlist-list');
    if (!list) return;
    const playlists = (cachedStatus && cachedStatus.playlists) || [];
    if (playlists.length === 0) {
        list.innerHTML = `<div class="wiz-row" style="cursor:default"><div class="wiz-row-text"><div class="wiz-row-name">${_t(
            'wizard.step3.empty',
            'No playlists bundled'
        )}</div></div></div>`;
        return;
    }
    list.innerHTML = playlists
        .map((p) => {
            const id = p.path || p.filename || p.name;
            const selected = chosenPlaylists.has(id);
            const count = p.song_count || p.count || 0;
            const name = p.name || p.filename || id;
            const decade = p.decade || p.tags || '';
            return `<button type="button" class="wiz-row ${selected ? 'selected' : ''}" data-playlist-id="${id}" aria-pressed="${selected}">
          <div class="wiz-row-avatar">${PLAYLIST_ICON}</div>
          <div class="wiz-row-text">
            <div class="wiz-row-name">${name}</div>
            <div class="wiz-row-sub">${decade}</div>
          </div>
          <div class="wiz-row-count">${count}</div>
          ${selected ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" class="wiz-row-check"><path d="M5 12l5 5L20 7"/></svg>' : ''}
        </button>`;
        })
        .join('');
    list.querySelectorAll('[data-playlist-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.playlistId;
            if (chosenPlaylists.has(id)) chosenPlaylists.delete(id);
            else chosenPlaylists.add(id);
            _renderPlaylists();
            _updateCta();
        });
    });
}

const DIFFICULTIES = [
    { id: 'easy', labelKey: 'wizard.step3.easy', labelFallback: 'Easy' },
    { id: 'normal', labelKey: 'wizard.step3.normal', labelFallback: 'Normal' },
    { id: 'hard', labelKey: 'wizard.step3.hard', labelFallback: 'Hard' },
];

// Mirrors DIFFICULTY_SCORING in custom_components/beatify/const.py — keep in sync.
// Scoring tiers: exact match, "close" band, "near" band.
const DIFFICULTY_HINTS = {
    easy: {
        fallback: 'Forgiving: 10 pts for an exact year, 5 pts within ±7 years, 1 pt within ±10 years.',
        key: 'wizard.step4.difficultyHintEasy',
    },
    normal: {
        fallback: 'Balanced: 10 pts for an exact year, 5 pts within ±3 years, 1 pt within ±5 years.',
        key: 'wizard.step4.difficultyHintNormal',
    },
    hard: {
        fallback: 'Sharp: 10 pts for an exact year, 3 pts within ±2 years, otherwise 0.',
        key: 'wizard.step4.difficultyHintHard',
    },
};
const DURATIONS = [15, 30, 45, 60]; // seconds per round
const LANGUAGES = [
    { id: 'en', label: 'English' },
    { id: 'de', label: 'Deutsch' },
    { id: 'es', label: 'Español' },
    { id: 'fr', label: 'Français' },
    { id: 'nl', label: 'Nederlands' },
];

function _renderChipGroup(elId, items, active, onPick) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = items
        .map((item) => {
            const id = typeof item === 'object' ? item.id : item;
            const label = typeof item === 'object'
                ? (item.labelKey ? _t(item.labelKey, item.labelFallback) : item.label)
                : `${item}s`;
            const isActive = id === active;
            return `<button type="button" class="wiz-chip ${isActive ? 'active' : ''}" data-value="${id}">${label}</button>`;
        })
        .join('');
    el.querySelectorAll('.wiz-chip').forEach((btn) => {
        btn.addEventListener('click', () => {
            const raw = btn.dataset.value;
            // Duration is numeric
            onPick(items[0] && typeof items[0] === 'number' ? parseInt(raw, 10) : raw);
        });
    });
}

const GAME_MODES = [
    {
        key: 'artist',
        icon: '🎤',
        titleKey: 'admin.artistChallenge',
        titleFallback: 'Artist Challenge',
        hintKey: 'admin.artistChallengeHint',
        hintFallback: 'After each round, players can guess the artist for bonus points. First correct guess earns +5 points.',
        get: () => chosenArtistChallenge,
        set: (v) => { chosenArtistChallenge = v; },
    },
    {
        key: 'intro',
        icon: '⚡',
        titleKey: 'admin.introMode',
        titleFallback: 'Intro Mode',
        hintKey: 'admin.introModeHint',
        hintFallback: '~20% of rounds play only the song intro. Players must guess the year from just the opening seconds. Requires at least 3 rounds.',
        get: () => chosenIntroMode,
        set: (v) => { chosenIntroMode = v; },
    },
    {
        key: 'closest',
        icon: '🎯',
        titleKey: 'admin.closestWinsMode',
        titleFallback: 'Closest Wins',
        hintKey: 'admin.closestWinsHint',
        hintFallback: 'Only the player with the closest guess scores points each round. All-or-nothing showdown.',
        get: () => chosenClosestWins,
        set: (v) => { chosenClosestWins = v; },
    },
];

function _renderGameModes() {
    const el = document.getElementById('wiz-modes');
    if (!el) return;
    el.innerHTML = GAME_MODES.map((m) => {
        const on = m.get();
        return `<div class="wiz-mode-card ${on ? 'on' : ''}" data-mode="${m.key}" role="button" tabindex="0">
            <div class="wiz-mode-icon" aria-hidden="true">${m.icon}</div>
            <div class="wiz-mode-body">
                <div class="wiz-mode-title">${_t(m.titleKey, m.titleFallback)}</div>
                <div class="wiz-mode-hint">${_t(m.hintKey, m.hintFallback)}</div>
            </div>
            <div class="wiz-lvl-toggle"></div>
        </div>`;
    }).join('');
    el.querySelectorAll('[data-mode]').forEach((card) => {
        card.addEventListener('click', () => {
            const mode = GAME_MODES.find((m) => m.key === card.dataset.mode);
            if (!mode) return;
            mode.set(!mode.get());
            _renderGameModes();
        });
    });
}

function _renderDifficultyHint() {
    const el = document.getElementById('wiz-difficulty-hint');
    if (!el) return;
    const hint = DIFFICULTY_HINTS[chosenDifficulty] || DIFFICULTY_HINTS.normal;
    el.textContent = _t(hint.key, hint.fallback);
}

function _renderGameMode() {
    _renderChipGroup('wiz-difficulty', DIFFICULTIES, chosenDifficulty, (val) => {
        chosenDifficulty = val;
        _renderGameMode();
    });
    _renderDifficultyHint();
    _renderChipGroup('wiz-timer', DURATIONS, chosenDuration, (val) => {
        chosenDuration = val;
        _renderGameMode();
    });
    _renderChipGroup('wiz-language', LANGUAGES, chosenLanguage, (val) => {
        chosenLanguage = val;
        _renderGameMode();
    });
    _renderGameModes();
}

function _lightsDetailHtml() {
    const lights = cachedLights || [];
    const rows = lights.length
        ? lights.map((l) => {
              const checked = chosenLightEntityIds.has(l.entity_id) ? 'checked' : '';
              return `<label class="wiz-detail-check">
            <input type="checkbox" data-light-id="${l.entity_id}" ${checked}>
            <span class="wiz-detail-check-name">${l.friendly_name || l.entity_id}</span>
          </label>`;
          }).join('')
        : `<div class="wiz-detail-empty">${_t('wizard.step5.lights.noneFound', 'No lights available')}</div>`;
    const chip = (id, label, group) => `<button type="button" class="wiz-chip ${(group === 'intensity' ? chosenLightIntensity : chosenLightMode) === id ? 'active' : ''}" data-${group}="${id}">${label}</button>`;

    const wledBlock = chosenLightMode === 'wled'
        ? `<div class="wiz-field">
             <span class="wiz-field-label">${_t('wizard.step5.lights.wledPresets', 'WLED preset per phase')}</span>
             <div class="wiz-wled-grid">
               ${WLED_PHASES.map((phase) => {
                   const val = chosenWledPresets[phase] !== undefined ? chosenWledPresets[phase] : '';
                   return `<label class="wiz-wled-row">
                     <span class="wiz-wled-phase">${phase}</span>
                     <input type="number" min="0" class="wiz-detail-input wiz-wled-input" data-wled-phase="${phase}" value="${val}" placeholder="—">
                   </label>`;
               }).join('')}
             </div>
             <span class="wiz-field-hint">${_t('wizard.step5.lights.wledHint', 'Enter the WLED preset slot number (0–16) to trigger for each game phase.')}</span>
           </div>`
        : '';

    return `
        <div class="wiz-detail">
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.lights.pickLabel', 'Lights to sync')}</span>
            <div class="wiz-detail-checks">${rows}</div>
          </div>
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.lights.intensity', 'Intensity')}</span>
            <div class="wiz-chip-group">
              ${chip('subtle', _t('wizard.step5.lights.subtle', 'Subtle'), 'intensity')}
              ${chip('medium', _t('wizard.step5.lights.medium', 'Medium'), 'intensity')}
              ${chip('party', _t('wizard.step5.lights.party', 'Party'), 'intensity')}
            </div>
          </div>
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.lights.mode', 'Mode')}</span>
            <div class="wiz-chip-group">
              ${chip('static', _t('wizard.step5.lights.modeStatic', 'Static'), 'lightMode')}
              ${chip('dynamic', _t('wizard.step5.lights.modeDynamic', 'Dynamic'), 'lightMode')}
              ${chip('wled', 'WLED', 'lightMode')}
            </div>
          </div>
          ${wledBlock}
        </div>`;
}

function _ttsDetailHtml() {
    const announce = (key, label, val) => `<label class="wiz-detail-check">
        <input type="checkbox" data-tts-flag="${key}" ${val ? 'checked' : ''}>
        <span class="wiz-detail-check-name">${label}</span>
      </label>`;
    return `
        <div class="wiz-detail">
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.tts.entityLabel', 'TTS service (entity ID)')}</span>
            <input type="text" id="wiz-tts-entity" class="wiz-detail-input" placeholder="tts.google_en_com" value="${chosenTtsEntityId}">
            <span class="wiz-field-hint">${_t('wizard.step5.tts.entityHint', 'Copy from Home Assistant → Developer Tools → States (filter: tts.)')}</span>
            <button type="button" id="wiz-tts-test" class="btn btn-ghost wiz-detail-test" ${chosenTtsEntityId ? '' : 'disabled'}>
              🔊 ${_t('wizard.step5.tts.test', 'Send test announcement')}
            </button>
          </div>
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.tts.announce', 'Announce')}</span>
            <div class="wiz-detail-checks">
              ${announce('start', _t('wizard.step5.tts.announceStart', 'Game start'), chosenTtsAnnounceStart)}
              ${announce('winner', _t('wizard.step5.tts.announceWinner', 'Round winner'), chosenTtsAnnounceWinner)}
            </div>
          </div>
        </div>`;
}

function _renderLevelUp() {
    const list = document.getElementById('wiz-levelup-list');
    if (!list || !cachedCapabilities) return;
    const caps = cachedCapabilities;
    const cards = [
        {
            key: 'lights',
            title: _t('wizard.step5.lights.title', 'Party lights'),
            desc: caps.has_lights
                ? _t('wizard.step5.lights.desc', 'Sync your Hue lights to the beat. Pulse on round changes, flash on winner.')
                : _t('wizard.step5.lights.unavailable', 'No lights found in Home Assistant.'),
            available: caps.has_lights,
            detail: _lightsDetailHtml,
        },
        {
            key: 'tts',
            title: _t('wizard.step5.tts.title', 'Voice announcements'),
            desc: caps.has_tts
                ? _t('wizard.step5.tts.desc', 'TTS calls out round numbers, winners, and fun facts.')
                : _t('wizard.step5.tts.unavailable', 'No TTS service registered in Home Assistant.'),
            available: caps.has_tts,
            detail: _ttsDetailHtml,
        },
    ];
    list.innerHTML = cards
        .map((card) => {
            const on = chosenLevelUps[card.key] && card.available;
            const disabled = !card.available ? 'aria-disabled="true"' : '';
            return `<div class="wiz-lvl-card ${on ? 'on' : ''} ${!card.available ? 'unavailable' : ''}" data-levelup="${card.key}" ${disabled}>
          <div class="wiz-lvl-head" role="button" tabindex="0">
            <div class="wiz-lvl-text">
              <div class="wiz-lvl-title">${card.title}</div>
              <div class="wiz-lvl-desc">${card.desc}</div>
            </div>
            <div class="wiz-lvl-toggle"></div>
          </div>
          ${on ? card.detail() : ''}
        </div>`;
        })
        .join('');

    // Card toggle — head is the clickable area (not the whole card, so clicks inside the detail panel don't collapse it)
    list.querySelectorAll('.wiz-lvl-card').forEach((card) => {
        if (card.getAttribute('aria-disabled')) return;
        const head = card.querySelector('.wiz-lvl-head');
        if (!head) return;
        head.addEventListener('click', () => {
            const key = card.dataset.levelup;
            chosenLevelUps[key] = !chosenLevelUps[key];
            _renderLevelUp();
        });
    });

    // Light checkboxes + intensity
    list.querySelectorAll('[data-light-id]').forEach((cb) => {
        cb.addEventListener('change', () => {
            const id = cb.dataset.lightId;
            if (cb.checked) chosenLightEntityIds.add(id);
            else chosenLightEntityIds.delete(id);
        });
    });
    list.querySelectorAll('[data-intensity]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            chosenLightIntensity = btn.dataset.intensity;
            _renderLevelUp();
        });
    });
    list.querySelectorAll('[data-light-mode]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            chosenLightMode = btn.dataset.lightMode;
            _renderLevelUp();
        });
    });
    list.querySelectorAll('[data-wled-phase]').forEach((input) => {
        input.addEventListener('input', () => {
            const phase = input.dataset.wledPhase;
            const v = parseInt(input.value, 10);
            if (Number.isFinite(v) && v >= 0) chosenWledPresets[phase] = v;
            else delete chosenWledPresets[phase];
        });
    });

    // TTS fields
    const ttsInput = document.getElementById('wiz-tts-entity');
    const ttsTestBtn = document.getElementById('wiz-tts-test');
    if (ttsInput) {
        ttsInput.addEventListener('input', () => {
            chosenTtsEntityId = ttsInput.value.trim();
            if (ttsTestBtn) ttsTestBtn.disabled = !chosenTtsEntityId;
        });
    }
    if (ttsTestBtn) {
        ttsTestBtn.addEventListener('click', async () => {
            if (!chosenTtsEntityId) return;
            const orig = ttsTestBtn.innerHTML;
            ttsTestBtn.disabled = true;
            ttsTestBtn.innerHTML = '🔊 …';
            try {
                const r = await fetch('/beatify/api/tts-test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ entity_id: chosenTtsEntityId, message: 'Beatify TTS test — this is working!' }),
                });
                ttsTestBtn.innerHTML = r.ok
                    ? '✓ ' + _t('wizard.step5.tts.testOk', 'Sent')
                    : '✗ ' + _t('wizard.step5.tts.testFail', 'Failed');
            } catch (e) {
                ttsTestBtn.innerHTML = '✗ ' + _t('wizard.step5.tts.testFail', 'Failed');
            }
            setTimeout(() => {
                ttsTestBtn.innerHTML = orig;
                ttsTestBtn.disabled = !chosenTtsEntityId;
            }, 2000);
        });
    }
    list.querySelectorAll('[data-tts-flag]').forEach((cb) => {
        cb.addEventListener('change', () => {
            if (cb.dataset.ttsFlag === 'start') chosenTtsAnnounceStart = cb.checked;
            else if (cb.dataset.ttsFlag === 'winner') chosenTtsAnnounceWinner = cb.checked;
        });
    });
}

function _persistLevelUpDetails() {
    try {
        if (chosenLevelUps.lights) {
            const payload = {
                lights: Array.from(chosenLightEntityIds),
                intensity: chosenLightIntensity,
                light_mode: chosenLightMode,
            };
            if (chosenLightMode === 'wled' && Object.keys(chosenWledPresets).length > 0) {
                payload.wled_presets = chosenWledPresets;
            }
            localStorage.setItem('beatify_party_lights', JSON.stringify(payload));
        }
        localStorage.setItem('beatify_tts', JSON.stringify({
            enabled: chosenLevelUps.tts,
            entity_id: chosenTtsEntityId,
            announce_game_start: chosenTtsAnnounceStart,
            announce_winner: chosenTtsAnnounceWinner,
        }));
    } catch (e) { /* private mode */ }
}

function _speakerLabel(entityId) {
    if (!entityId) return '—';
    // Prefer the friendly_name from /api/status over deriving from the entity_id.
    // Sonos speakers in particular often have entity_ids like "media_player.unnamed_room"
    // while the friendly_name is the actual room name ("Esszimmer", "Küche", etc.).
    const players = (cachedStatus && cachedStatus.media_players) || [];
    const match = players.find((p) => p.entity_id === entityId);
    if (match && match.friendly_name) return match.friendly_name;
    return entityId.replace('media_player.', '').replace(/_/g, ' ');
}

function _renderDoneSummary() {
    const el = document.getElementById('wiz-done-summary');
    if (!el) return;
    const speaker = _speakerLabel(chosenSpeaker);
    const providerMatch = chosenProvider ? PROVIDERS.find((p) => p.id === chosenProvider) : null;
    const provider = providerMatch ? providerMatch.label : (chosenProvider ? chosenProvider.replace(/_/g, ' ') : '—');
    const extras = [];
    if (chosenLevelUps.lights) extras.push('lights');
    if (chosenLevelUps.tts) extras.push('voice');
    const atmosphere = extras.length ? extras.join(' + ') : 'none';

    // Playlists: compact single name when one picked, count + preview when many
    let playlistLabel = '—';
    if (chosenPlaylists.size === 1) {
        playlistLabel = _playlistName(Array.from(chosenPlaylists)[0]);
    } else if (chosenPlaylists.size > 1) {
        const first = _playlistName(Array.from(chosenPlaylists)[0]);
        playlistLabel = `${chosenPlaylists.size} picked · ${first} + more`;
    }

    el.innerHTML = `
        <div class="wiz-done-line"><span>Speaker</span><strong>${speaker}</strong></div>
        <div class="wiz-done-line"><span>Service</span><strong>${provider}</strong></div>
        <div class="wiz-done-line"><span>Playlist</span><strong>${playlistLabel}</strong></div>
        <div class="wiz-done-line"><span>Mode</span><strong>${chosenDifficulty} · ${chosenDuration}s · ${chosenLanguage.toUpperCase()}</strong></div>
        <div class="wiz-done-line"><span>Atmosphere</span><strong>${atmosphere}</strong></div>
    `;
}

function _playlistName(id) {
    if (!id) return '—';
    const playlists = (cachedStatus && cachedStatus.playlists) || [];
    const match = playlists.find((p) => (p.path || p.filename || p.name) === id);
    if (match) return match.name || match.filename || id;
    // Fallback: strip path + .json
    return id.split('/').pop().replace('.json', '').replace(/-/g, ' ');
}

// Merge wizard choices into beatify_game_settings so admin.js picks them up on load.
// Preserves existing keys (artistChallenge, introMode, closestWinsMode) the wizard doesn't touch.
function _persistGameSettings() {
    try {
        const raw = localStorage.getItem(LS_GAME_SETTINGS);
        const existing = raw ? JSON.parse(raw) : {};
        const merged = {
            ...existing,
            provider: chosenProvider || existing.provider,
            difficulty: chosenDifficulty,
            duration: chosenDuration,
            language: chosenLanguage,
            artistChallenge: chosenArtistChallenge,
            introMode: chosenIntroMode,
            closestWinsMode: chosenClosestWins,
        };
        if (chosenPlaylists.size > 0) {
            // admin.js stores selectedPlaylists as [{ path, songCount }]; include minimally.
            merged.selectedPlaylists = Array.from(chosenPlaylists).map((path) => ({ path }));
        }
        localStorage.setItem(LS_GAME_SETTINGS, JSON.stringify(merged));
    } catch (e) { /* private mode */ }
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

export async function show(stepOverride) {
    if (!cachedStatus) cachedStatus = await _fetchStatus();
    const root = document.getElementById('wizard-root');
    if (!root) return;
    root.classList.remove('hidden');
    root.setAttribute('aria-hidden', 'false');
    document.body.classList.add('wizard-active');
    const ls = typeof window !== 'undefined' ? window.localStorage : null;
    const start = stepOverride || resumeAtStep(ls) || 1;
    // Hydrate chosen values from admin's localStorage so Continue works immediately
    try {
        chosenSpeaker = ls ? ls.getItem(LS_SELECTED_PLAYER) : null;
        const rawSettings = ls ? ls.getItem(LS_GAME_SETTINGS) : null;
        if (rawSettings) {
            const s = JSON.parse(rawSettings);
            if (s.provider) chosenProvider = s.provider;
            if (s.difficulty) chosenDifficulty = s.difficulty;
            if (s.duration) chosenDuration = s.duration;
            if (s.language) chosenLanguage = s.language;
            if (typeof s.artistChallenge === 'boolean') chosenArtistChallenge = s.artistChallenge;
            if (typeof s.introMode === 'boolean') chosenIntroMode = s.introMode;
            if (typeof s.closestWinsMode === 'boolean') chosenClosestWins = s.closestWinsMode;
            if (Array.isArray(s.selectedPlaylists)) {
                s.selectedPlaylists.forEach((entry) => {
                    const path = typeof entry === 'string' ? entry : entry && entry.path;
                    if (path) chosenPlaylists.add(path);
                });
            }
        }
    } catch (e) { /* private mode or malformed JSON */ }
    _hydrateLevelUpDetails();
    _renderSpeakers();
    _renderProviders();
    _renderPlaylists();
    _renderGameMode();
    _showFrame(start);
}

export function hide({ dismissed } = {}) {
    const root = document.getElementById('wizard-root');
    if (!root) return;
    root.classList.add('hidden');
    root.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('wizard-active');
    if (dismissed) {
        try { localStorage.setItem(LS_WIZARD_STATE, 'dismissed'); } catch (e) { /* private mode */ }
    }
    _updatePill();
}

function _updatePill() {
    const pill = document.getElementById('finish-setup-pill');
    if (!pill) return;
    const ls = typeof window !== 'undefined' ? window.localStorage : null;
    if (shouldShowPill(ls)) pill.classList.remove('hidden');
    else pill.classList.add('hidden');
}

async function _advance() {
    // Persist on every advance past the config steps so admin's next read of
    // beatify_game_settings reflects every wizard choice.
    if (currentStep === 2 || currentStep === 3 || currentStep === 4) {
        _persistGameSettings();
    }
    if (currentStep === 4) {
        // Leaving game-mode → fetch capabilities + lights so Step 5 can render details
        if (!cachedCapabilities) cachedCapabilities = await _fetchCapabilities();
        if (cachedCapabilities && cachedCapabilities.has_lights && cachedLights === null) {
            cachedLights = await _fetchLights();
        }
        _renderLevelUp();
        _showFrame(5);
        return;
    }
    if (currentStep === 5) {
        _persistLevelUpDetails();
        _renderDoneSummary();
        _showFrame(6);
        return;
    }
    if (currentStep === 6) {
        // "Go to lobby" — mark done, close wizard, flip admin into home-mode
        // (the lobby landing card with Start Game + Edit setup), then refresh status.
        try { localStorage.setItem(LS_WIZARD_STATE, 'done'); } catch (e) { /* private mode */ }
        hide({ dismissed: false });
        if (typeof window !== 'undefined' && typeof window.loadStatus === 'function') {
            window.loadStatus();
        }
        if (typeof window !== 'undefined' && window.BeatifyHome) {
            window.BeatifyHome.enter();
        }
        return;
    }
    _showFrame(currentStep + 1);
}

export async function init() {
    const nextBtn = document.getElementById('wiz-next');
    const backBtn = document.getElementById('wiz-back');
    const skipBtn = document.getElementById('wiz-skip');
    const pill = document.getElementById('finish-setup-pill');

    if (nextBtn) nextBtn.addEventListener('click', _advance);
    if (backBtn) backBtn.addEventListener('click', () => {
        if (currentStep > 1) _showFrame(currentStep - 1);
    });
    if (skipBtn) skipBtn.addEventListener('click', () => hide({ dismissed: true }));
    const reqBtn = document.getElementById('wiz-request-playlist');
    if (reqBtn) reqBtn.addEventListener('click', () => {
        const modal = document.getElementById('request-modal');
        if (modal) {
            modal.classList.remove('hidden');
            document.getElementById('spotify-url-input')?.focus();
        }
    });
    if (pill) pill.addEventListener('click', async () => {
        // Reopen: clear "dismissed" so the wizard can run again, then resume
        try { localStorage.removeItem(LS_WIZARD_STATE); } catch (e) { /* private mode */ }
        cachedStatus = await _fetchStatus();
        show();
    });

    const ls = typeof window !== 'undefined' ? window.localStorage : null;
    if (shouldTrigger(ls)) {
        show();
    } else {
        _updatePill();
    }
}

// Expose globally so admin.js (not an ES module) can call BeatifyWizard.init()
if (typeof window !== 'undefined') {
    window.BeatifyWizard = { init, show, hide };
}
