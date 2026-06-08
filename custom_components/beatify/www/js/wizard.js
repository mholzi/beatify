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

import {
    mount as plhMount,
    setSelection as plhSetSelection,
    refresh as plhRefresh,
    getPlaylistByPath as plhGetPlaylistByPath,
} from './playlist-hub.js';

const LS_WIZARD_STATE = 'beatify_wizard_state';   // 'step1'|'step2'|'step3'|'step4'|'done'|'dismissed'
const LS_SELECTED_PLAYER = 'beatify_last_player'; // set by admin.js when a speaker is picked
const LS_GAME_SETTINGS = 'beatify_game_settings'; // set by admin.js, contains {provider, ...}

let _hubMounted = false;

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

/**
 * #1180: Step 4 game-mode toggle precedence.
 *
 * Title & Artist mode replaces the year round, so it's mutually exclusive with
 * the four year-round bonuses (artist challenge, movie quiz, intro, closest
 * wins). The exclusivity is ASYMMETRIC, mirroring admin.js's contract:
 *
 *   - Turning a year-round bonus ON turns TA mode OFF. TA is the replaceable
 *     round, so re-enabling a year bonus cleanly exits TA mode.
 *   - Turning TA mode ON does NOT touch the year-round flags. They stay the
 *     host's untouched source of truth so the wizard never persists `false`
 *     over a previously-true bonus into beatify_game_settings (admin.js reads
 *     that same key). Suppression while TA is on is applied later, only at
 *     start-game-payload build time, by admin.js's
 *     applyTitleArtistBonusPrecedence(). Forcing the flags off here instead
 *     would silently destroy the host's saved choices on the next admin reload.
 *
 * Pure function: returns a NEW flags object, never mutates the input. Exported
 * for vitest (the wizard module-internal state isn't otherwise testable).
 *
 * @param {Object} flags - { artistChallenge, movieQuiz, introMode,
 *   closestWinsMode, titleArtistMode } booleans (the wizard's chosen* state).
 * @param {string} key - which toggle the user flipped: 'artist' | 'movie' |
 *   'intro' | 'closest' | 'titleArtist'.
 * @param {boolean} value - the new value for that toggle.
 * @returns {Object} a new flags object with precedence applied.
 */
export function applyGameModeTogglePrecedence(flags, key, value) {
    const next = { ...flags };
    switch (key) {
        case 'artist':
            next.artistChallenge = value;
            if (value) next.titleArtistMode = false;
            break;
        case 'movie':
            // #1180: movie quiz is a per-song bonus, compatible with TA mode.
            next.movieQuiz = value;
            break;
        case 'intro':
            // #1180: intro mode (shorter clip) is compatible with TA mode.
            next.introMode = value;
            break;
        case 'closest':
            next.closestWinsMode = value;
            if (value) next.titleArtistMode = false;
            break;
        case 'titleArtist':
            // #1180: Turning TA mode ON must NOT touch the year-round flags.
            // They stay the host's source of truth so the wizard never persists
            // `false` over a previously-true bonus into beatify_game_settings
            // (admin.js reads that same key). Suppression while TA is on is
            // applied later, only at start-game-payload build time, by
            // admin.js's applyTitleArtistBonusPrecedence(). Zeroing here would
            // silently destroy the host's saved choices on the next reload.
            next.titleArtistMode = value;
            break;
    }
    return next;
}

/**
 * Decide how the Step-4 difficulty area renders for the chosen core mode.
 * In Title & Artist mode the year-distance scoring bands don't apply, so the
 * Leicht/Normal/Schwer chips are hidden and a fixed T&I scoring summary is
 * shown in their place. Pure — no DOM, exported for vitest.
 *
 * @param {boolean} titleArtistMode
 * @returns {{ showChips: boolean, summaryKey: string|null }}
 */
export function difficultyDisplayFor(titleArtistMode) {
    return titleArtistMode
        ? { showChips: false, summaryKey: 'wizard.step4.taScoring' }
        : { showChips: true, summaryKey: null };
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
let chosenRevealAutoAdvance = 0; // #1028: REVEAL auto-advance seconds (0 = off, default)
let chosenLanguage = 'en';
// Game-mode toggles (defaults match admin.js: artistChallenge on, movieQuiz on, intro off, closestWins off)
let chosenArtistChallenge = true;
let chosenMovieQuiz = true;
let chosenIntroMode = false;
let chosenClosestWins = false;
let chosenTitleArtistMode = false; // #1180
const chosenLevelUps = { lights: false, tts: false };
// Details the user sets when a level-up is toggled on
let cachedLights = null; // HA lights from /api/lights
const chosenLightEntityIds = new Set();
let chosenLightIntensity = 'medium'; // subtle | medium | party
let chosenLightMode = 'dynamic'; // static | dynamic | wled
const chosenWledPresets = {}; // { LOBBY: 1, PLAYING: 2, ... }
const WLED_PHASES = ['LOBBY', 'PLAYING', 'REVEAL', 'STREAK', 'COUNTDOWN', 'END'];
let chosenTtsEntityId = '';
let chosenTtsPreset = 'standard'; // minimal | standard | full | custom
let cachedTtsEntities = null; // #1073: [{entity_id, friendly_name}], lazy-fetched

const TOTAL_STEPS = 5; // 1:speakers 2:music 3:playlist 4:game-mode 5:level-up (+ done frame)

// Lookup a translated string. The optional `params` object is forwarded to
// BeatifyI18n.t for {placeholder} interpolation inside the translation. When
// the i18n module isn't loaded (tests, early boot), we fall back to the
// English default and interpolate `{placeholder}` locally so callers don't
// care about load state.
function _t(key, fallback, params) {
    let translated;
    if (typeof window !== 'undefined' && window.BeatifyI18n && typeof window.BeatifyI18n.t === 'function') {
        translated = window.BeatifyI18n.t(key, params);
        // BeatifyI18n returns the key itself when the translation is missing —
        // that's our cue to use the fallback instead of showing "wizard.step1.capAll"
        // in the UI.
        if (translated && translated !== key) return translated;
    }
    let out = fallback;
    if (params && typeof out === 'string') {
        Object.keys(params).forEach((p) => {
            out = out.replace(new RegExp('\\{' + p + '\\}', 'g'), params[p]);
        });
    }
    return out;
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
        const r = await BeatifyAuth.fetch('/beatify/api/capabilities');
        if (!r.ok) return { has_lights: true, has_tts: true };
        return await r.json();
    } catch (e) {
        return { has_lights: true, has_tts: true };
    }
}

async function _fetchLights() {
    try {
        const r = await BeatifyAuth.fetch('/beatify/api/lights');
        if (!r.ok) return [];
        const data = await r.json();
        return (data && data.lights) || [];
    } catch (e) {
        return [];
    }
}

// #1073: list registered tts.* entities for the Step 5 dropdown picker.
async function _fetchTtsEntities() {
    try {
        const r = await BeatifyAuth.fetch('/beatify/api/tts-entities');
        if (!r.ok) return [];
        const data = await r.json();
        return (data && data.entities) || [];
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
            // #1011 follow-up: hydrate the lights-on toggle when the user
            // previously configured lights. Without this, re-entering the
            // wizard with existing lights leaves chosenLevelUps.lights=false,
            // so _persistLevelUpDetails skips the lights branch and the
            // `enabled: true` fix from PR #1031 never gets written to
            // localStorage. Mirror of the TTS hydration on line below.
            if (s.enabled === true || (Array.isArray(s.lights) && s.lights.length > 0)) {
                chosenLevelUps.lights = true;
            }
        }
        const rawT = localStorage.getItem('beatify_tts');
        if (rawT) {
            const s = JSON.parse(rawT);
            if (s.entity_id) chosenTtsEntityId = s.entity_id;
            // `preset` is written by both the admin TTS panel and this wizard.
            // Pre-preset configs simply fall back to the 'standard' default.
            if (s.preset) chosenTtsPreset = s.preset;
            // #1011 follow-up: legacy payloads have entity_id but no
            // explicit `enabled` key. Treat "entity selected with no
            // explicit flag" as implied on, mirroring the lights hydrate.
            if (s.enabled === true || (s.enabled === undefined && !!s.entity_id)) {
                chosenLevelUps.tts = true;
            }
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

    // Step 3 hands the entire CTA to the Playlist Hub — hide the legacy
    // wiz-next AND wiz-back so we don't stack chrome. Hub renders its
    // own Back + Continue in a single row.
    if (currentStep === 3) {
        nextBtn.style.display = 'none';
        backBtn.style.display = 'none';
    } else {
        nextBtn.style.display = '';
        backBtn.style.display = currentStep > 1 ? '' : 'none';
    }

    if (currentStep === 1) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenSpeaker;
    } else if (currentStep === 2) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        // Block Continue unless the picked provider is supported on the picked
        // speaker — prevents #772-style silent failures at playback time.
        nextBtn.disabled = !chosenProvider || !_providerSupported(chosenProvider);
    } else if (currentStep === 3) {
        // Not shown — hub's Continue takes over. Keep the disabled/text
        // logic so if CSS ever un-hides it the behavior is correct.
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

// Summarize a speaker's service capabilities for the Step 1 badge.
function _capabilityBadge(player) {
    return capabilityBadgeForPlayer(player, PROVIDERS, {
        none: _t('wizard.step1.capNone', 'No services'),
        all: _t('wizard.step1.capAll', 'All services'),
        onlyTemplate: _t('wizard.step1.capOnlyTemplate', '{provider} only'),
    });
}

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
            const platform = _platformLabel(p.platform) || p.state || '';
            const badge = _capabilityBadge(p);
            const badgeHtml = badge
                ? `<span class="cap-dot" aria-hidden="true"></span><span class="cap-badge ${badge.cls}">${badge.label}</span>`
                : '';
            return `<button type="button" class="wiz-row ${selected ? 'selected' : ''}" data-entity-id="${p.entity_id}">
          <div class="wiz-row-avatar">${SPEAKER_ICON}</div>
          <div class="wiz-row-text">
            <div class="wiz-row-name">${p.friendly_name || p.entity_id}</div>
            <div class="wiz-row-sub">${platform}${badgeHtml}</div>
          </div>
          ${selected ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" class="wiz-row-check"><path d="M5 12l5 5L20 7"/></svg>' : ''}
        </button>`;
        })
        .join('');
    list.querySelectorAll('.wiz-row[data-entity-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const newSpeaker = btn.dataset.entityId;
            const speakerChanged = chosenSpeaker !== newSpeaker;
            chosenSpeaker = newSpeaker;
            try { localStorage.setItem(LS_SELECTED_PLAYER, chosenSpeaker); } catch (e) { /* private mode */ }
            // Switching speakers invalidates the provider step — stale explainer
            // would reference the previous platform, and a previously-picked
            // provider may no longer be supported.
            _hideProviderExplainer();
            if (speakerChanged && chosenProvider && !_providerSupported(chosenProvider)) {
                // Clear the now-unsupported provider so Step 2 doesn't trap the
                // user with a selection they can't complete.
                chosenProvider = null;
            }
            _renderSpeakers();
            // Capability set changed — Step 2's chip dimming must be recomputed
            // or users see stale lock icons from the previous speaker.
            _renderProviders();
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
    { id: 'amazon_music', label: 'Amazon Music' },
];

// Lock icon SVG for dimmed provider chips (#772 UX).
const CHIP_LOCK_ICON = `<svg class="chip-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`;

// Look up the currently selected speaker record (with supports_* flags).
function _selectedPlayer() {
    if (!chosenSpeaker) return null;
    const players = (cachedStatus && cachedStatus.media_players) || [];
    return players.find((p) => p.entity_id === chosenSpeaker) || null;
}

// Pure: does the player record say this provider plays on this speaker?
// No player = treat as supported (user hasn't chosen a speaker yet, don't
// hide real options). Exported for tests.
export function providerSupportedForPlayer(player, providerId) {
    if (!player) return true;
    const key = `supports_${providerId}`;
    return player[key] !== false;
}

function _providerSupported(providerId) {
    return providerSupportedForPlayer(_selectedPlayer(), providerId);
}

// Pure: summarize a player's service capabilities into a badge descriptor.
// Returns { cls, label } or null. Exported for tests.
//
// labels.onlyTemplate is a format string containing `{provider}`. The word
// order of "only" vs. the provider name differs per language — English
// suffixes ("Spotify only") but German, Spanish, Dutch prefix ("nur Spotify",
// "solo Spotify", "alleen Spotify"). Using a template lets each locale pick.
export function capabilityBadgeForPlayer(player, providers, labels = {}) {
    if (!player) return null;
    const supported = providers.filter((p) => player[`supports_${p.id}`]);
    if (supported.length === 0) return { cls: 'none', label: labels.none || 'No services' };
    if (supported.length === providers.length) {
        return { cls: 'full', label: labels.all || 'All services' };
    }
    if (supported.length === 1) {
        const template = labels.onlyTemplate || '{provider} only';
        return { cls: 'partial', label: template.replace('{provider}', supported[0].label) };
    }
    return { cls: 'partial', label: supported.map((p) => p.label).join(', ') };
}

function _renderProviders() {
    const list = document.getElementById('wiz-provider-list');
    if (!list) return;
    list.innerHTML = PROVIDERS.map((p) => {
        const active = chosenProvider === p.id;
        const supported = _providerSupported(p.id);
        const classes = ['wiz-provider-chip'];
        if (active && supported) classes.push('active');
        if (!supported) classes.push('disabled');
        const lock = supported ? '' : CHIP_LOCK_ICON;
        const aria = supported ? '' : 'aria-disabled="true"';
        return `<button type="button" class="${classes.join(' ')}" data-provider="${p.id}" ${aria}><span>${p.label}</span>${lock}</button>`;
    }).join('');
    list.querySelectorAll('[data-provider]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.provider;
            if (!_providerSupported(id)) {
                // Dimmed chips open the explainer instead of being selected.
                _showProviderExplainer(id);
                return;
            }
            chosenProvider = id;
            _hideProviderExplainer();
            _renderProviders();
            _updateCta();
        });
    });
}

function _showProviderExplainer(providerId) {
    const host = document.getElementById('wiz-provider-explainer');
    if (!host) return;
    const player = _selectedPlayer();
    const platform = player ? _platformLabel(player.platform) : _t('wizard.step2.explainer.yourSpeaker', 'your speaker');
    const provider = (PROVIDERS.find((p) => p.id === providerId) || {}).label || providerId;
    const vars = { provider, platform };
    const ghost = _t('wizard.step2.explainer.ghost', 'Pick a different service');

    let innerHtml;
    if (providerId === 'amazon_music') {
        const title = _t('wizard.step2.explainer.amazonTitle', 'Amazon Music needs an Amazon Echo', vars);
        const body = _t(
            'wizard.step2.explainer.amazonBody',
            'Amazon Music is not available through Music Assistant. To use it, select an Amazon Echo device (via the alexa_media integration) as your speaker.',
            vars,
        );
        const step1 = _t('wizard.step2.explainer.amazonStep1', 'Install the <strong>Alexa Media Player</strong> integration in Home Assistant');
        const step2 = _t('wizard.step2.explainer.amazonStep2', 'Link your Amazon account and Echo device');
        const step3 = _t('wizard.step2.explainer.amazonStep3', 'Come back — your Echo appears as an available speaker');
        const primary = _t('wizard.step2.explainer.amazonPrimary', 'Set up Alexa Media Player →');
        innerHtml = `
            <div class="wiz-explainer-title">
                <span class="icon" aria-hidden="true">⚠️</span>
                <span>${title}</span>
            </div>
            <p class="wiz-explainer-body">${body}</p>
            <ol class="wiz-explainer-steps">
                <li>${step1}</li>
                <li>${step2}</li>
                <li>${step3}</li>
            </ol>
            <div class="wiz-explainer-actions">
                <a class="btn btn-primary" href="https://github.com/alandtse/alexa_media_player" target="_blank" rel="noopener">${primary}</a>
                <button type="button" class="btn btn-ghost" id="wiz-explainer-dismiss">${ghost}</button>
            </div>
        `;
    } else {
        const title = _t('wizard.step2.explainer.title', '{provider} on {platform} needs Music Assistant', vars);
        const body = _t(
            'wizard.step2.explainer.body',
            "{platform} plays Spotify directly from Home Assistant. {provider} and other streaming services need the Music Assistant add-on to route the track — it handles the login and format conversion {platform} can't do on its own.",
            vars,
        );
        const step1 = _t('wizard.step2.explainer.step1', 'Install <strong>Music Assistant</strong> from HACS');
        const step2 = _t('wizard.step2.explainer.step2', 'Add your {provider} account in MA → Providers', vars);
        const step3 = _t('wizard.step2.explainer.step3', 'Come back — your {platform} appears as a Music Assistant speaker', vars);
        const primary = _t('wizard.step2.explainer.primary', 'Set up Music Assistant →');
        const footer = _t('wizard.step2.explainer.footer', 'Prefer Spotify? It works on {platform} directly — no add-on needed.', vars);
        innerHtml = `
            <div class="wiz-explainer-title">
                <span class="icon" aria-hidden="true">⚠️</span>
                <span>${title}</span>
            </div>
            <p class="wiz-explainer-body">${body}</p>
            <ol class="wiz-explainer-steps">
                <li>${step1}</li>
                <li>${step2}</li>
                <li>${step3}</li>
            </ol>
            <div class="wiz-explainer-actions">
                <a class="btn btn-primary" href="https://www.home-assistant.io/integrations/music_assistant/" target="_blank" rel="noopener">${primary}</a>
                <button type="button" class="btn btn-ghost" id="wiz-explainer-dismiss">${ghost}</button>
            </div>
            <div class="wiz-explainer-footer">${footer}</div>
        `;
    }
    host.innerHTML = innerHtml;
    host.hidden = false;
    const dismiss = document.getElementById('wiz-explainer-dismiss');
    if (dismiss) {
        dismiss.addEventListener('click', () => {
            _hideProviderExplainer();
            const firstEnabled = document.querySelector('#wiz-provider-list .wiz-provider-chip:not(.disabled)');
            if (firstEnabled) firstEnabled.focus();
        });
    }
}

function _hideProviderExplainer() {
    const host = document.getElementById('wiz-provider-explainer');
    if (!host) return;
    host.hidden = true;
    host.innerHTML = '';
}

function _renderPlaylists() {
    // v3.3: delegate to PlaylistHub module. The legacy flat wiz-row picker
    // is gone; PlaylistHub handles search, filters, shelves, detail sheet,
    // and the Mine / Community surfaces. We only sync selection state
    // with chosenPlaylists (Set) so the rest of the wizard still reads
    // it as a source of truth.
    const root = document.getElementById('playlist-hub-root');
    if (!root) return;
    if (_hubMounted) {
        plhSetSelection(Array.from(chosenPlaylists));
        return;
    }
    plhMount(root, {
        initialSelected: Array.from(chosenPlaylists),
        // Hand the hub the playlist list we already fetched — saves a round-trip.
        initialPlaylists: (cachedStatus && Array.isArray(cachedStatus.playlists)) ? cachedStatus.playlists : null,
        // rc3: the hub owns both Continue AND Back on step 3 so the whole
        // nav lives in one row at the bottom instead of stacking with the
        // wizard's own chrome.
        showBack: true,
        backLabel: _t('wizard.back', 'Back'),
        onSelectionChange(paths) {
            chosenPlaylists.clear();
            for (const p of paths) chosenPlaylists.add(p);
            _updateCta();
        },
        onContinue(paths) {
            // Hub owns the Continue button on step 3. Sync selection, then
            // reuse the wizard's normal advance path so persistence + step
            // transitions stay in one place.
            chosenPlaylists.clear();
            for (const p of paths) chosenPlaylists.add(p);
            _advance();
        },
        onBack() {
            // Mirrors the handler on #wiz-back (line ~926).
            if (currentStep > 1) _showFrame(currentStep - 1);
        },
        onRequestClick() {
            // Reuse the existing request modal — it's mounted on admin.html
            // and already wired up via the legacy #wiz-request-playlist path.
            const modal = document.getElementById('request-modal');
            if (modal) {
                modal.classList.remove('hidden');
                const input = document.getElementById('spotify-url-input');
                if (input) input.focus();
            }
        },
    });
    _hubMounted = true;
}

export function refreshPlaylistHub() {
    // Called from admin.js after a new request lands so the Mine tab
    // re-pulls data. Idempotent — safe to call when not mounted.
    if (_hubMounted) plhRefresh();
}

const DIFFICULTIES = [
    { id: 'easy', labelKey: 'wizard.step4.easy', labelFallback: 'Easy' },
    { id: 'normal', labelKey: 'wizard.step4.normal', labelFallback: 'Normal' },
    { id: 'hard', labelKey: 'wizard.step4.hard', labelFallback: 'Hard' },
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
const AUTO_ADVANCE_OPTIONS = [
    { id: 0, labelKey: 'wizard.step4.autoAdvanceOff', labelFallback: 'Off' },
    { id: 30, label: '30s' },
    { id: 60, label: '60s' },
    { id: 90, label: '90s' },
];
const LANGUAGES = [
    { id: 'en', label: 'English' },
    { id: 'de', label: 'Deutsch' },
    { id: 'es', label: 'Español' },
    { id: 'fr', label: 'Français' },
    { id: 'nl', label: 'Nederlands' },
];

/**
 * Build a wizard chip button. Pure helper so the attribute contract is testable
 * (#1228 regression: the `data-<group>` name must stay kebab-case so the
 * `[data-light-mode]` click binding + `dataset.lightMode` read keep matching —
 * a `data-lightMode` typo silently unbinds the Static/Dynamic/WLED chips).
 * @param {string} id - chip value, written into data-<group>
 * @param {string} label - visible text
 * @param {string} group - kebab-case attribute group (e.g. "light-mode")
 * @param {string} activeId - currently-selected id; adds "active" when it matches
 * @returns {string} button HTML
 */
export function buildWizChip(id, label, group, activeId) {
    const active = activeId === id ? ' active' : '';
    return `<button type="button" class="wiz-chip${active}" data-${group}="${id}">${label}</button>`;
}

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

// Apply a Step-4 toggle through the pure precedence helper and write the
// result back into the module's chosen* state. Centralizes the mutual-
// exclusion so the four year-round setters and the TA setter share one
// (tested) rule. Crucially, turning TA on does NOT zero the year-round flags
// (see applyGameModeTogglePrecedence) — that would persist false over the
// host's saved bonus choices in beatify_game_settings.
function _setGameModeToggle(key, value) {
    const next = applyGameModeTogglePrecedence(
        {
            artistChallenge: chosenArtistChallenge,
            movieQuiz: chosenMovieQuiz,
            introMode: chosenIntroMode,
            closestWinsMode: chosenClosestWins,
            titleArtistMode: chosenTitleArtistMode,
        },
        key,
        value,
    );
    chosenArtistChallenge = next.artistChallenge;
    chosenMovieQuiz = next.movieQuiz;
    chosenIntroMode = next.introMode;
    chosenClosestWins = next.closestWinsMode;
    chosenTitleArtistMode = next.titleArtistMode;
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
        set: (v) => { _setGameModeToggle('artist', v); },
    },
    {
        key: 'movie',
        icon: '🎬',
        titleKey: 'admin.movieQuiz',
        titleFallback: 'Movie Quiz Bonus',
        hintKey: 'admin.movieQuizHint',
        hintFallback: 'For soundtrack songs, players guess the movie for tiered bonus points. Only triggers on songs with movie metadata.',
        get: () => chosenMovieQuiz,
        set: (v) => { _setGameModeToggle('movie', v); },
    },
    {
        key: 'intro',
        icon: '⚡',
        titleKey: 'admin.introMode',
        titleFallback: 'Intro Mode',
        hintKey: 'admin.introModeHint',
        hintFallback: '~20% of rounds play only the song intro. Players must guess the year from just the opening seconds. Requires at least 3 rounds.',
        get: () => chosenIntroMode,
        set: (v) => { _setGameModeToggle('intro', v); },
    },
    {
        key: 'closest',
        icon: '🎯',
        titleKey: 'admin.closestWinsMode',
        titleFallback: 'Closest Wins',
        hintKey: 'admin.closestWinsHint',
        hintFallback: 'Only the player with the closest guess scores points each round. All-or-nothing showdown.',
        get: () => chosenClosestWins,
        set: (v) => { _setGameModeToggle('closest', v); },
    },
];

// Core game mode — exactly one selected. Backed by the chosenTitleArtistMode
// boolean (Jahr = false, Titel & Interpret = true). Clicking routes through the
// tested precedence helper so T&I auto-clears the incompatible year-modifiers.
const CORE_MODES = [
    {
        key: 'year',
        icon: '📅',
        accent: 'pink',
        titleKey: 'wizard.step4.modeYear',
        titleFallback: 'Year mode',
        hintKey: 'wizard.step4.modeYearHint',
        hintFallback: "Guess each song's release year.",
        selected: () => !chosenTitleArtistMode,
        pick: () => { _setGameModeToggle('titleArtist', false); },
    },
    {
        key: 'titleArtist',
        icon: '✍️',
        accent: 'cyan',
        titleKey: 'wizard.step4.modeTitleArtist',
        titleFallback: 'Title & Artist',
        hintKey: 'wizard.step4.modeTitleArtistHint',
        hintFallback: 'Type the song title + artist.',
        selected: () => chosenTitleArtistMode,
        pick: () => { _setGameModeToggle('titleArtist', true); },
    },
];

function _renderCoreMode() {
    const el = document.getElementById('wiz-coremode');
    if (!el) return;
    el.innerHTML = CORE_MODES.map((m) => {
        const sel = m.selected();
        const badge = sel
            ? `<span class="wiz-coremode-badge">${_t('wizard.step4.modePlaying', 'Playing')}</span>`
            : '';
        return `<div class="wiz-coremode-card wiz-coremode-card--${m.accent} ${sel ? 'selected' : 'dim'}" data-coremode="${m.key}" role="button" tabindex="0" aria-pressed="${sel}">
            ${badge}
            <div class="wiz-mode-icon" aria-hidden="true">${m.icon}</div>
            <div class="wiz-mode-body">
                <div class="wiz-mode-title">${_t(m.titleKey, m.titleFallback)}</div>
                <div class="wiz-mode-hint">${_t(m.hintKey, m.hintFallback)}</div>
            </div>
        </div>`;
    }).join('');
    el.querySelectorAll('[data-coremode]').forEach((card) => {
        card.addEventListener('click', () => {
            const m = CORE_MODES.find((x) => x.key === card.dataset.coremode);
            if (!m) return;
            m.pick();
            // A mode change cascades into the difficulty + bonus sections.
            _renderCoreMode();
            _renderDifficulty();
            _renderGameModes();
        });
    });
}

function _renderGameModes() {
    const el = document.getElementById('wiz-modes');
    if (!el) return;
    el.innerHTML = GAME_MODES.map((m) => {
        const on = m.get();
        // #1180: hide modes incompatible with Title & Artist mode (artist
        // challenge + closest wins). Movie quiz and intro stay (compatible).
        if (chosenTitleArtistMode && (m.key === 'artist' || m.key === 'closest')) {
            return '';
        }
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

// Difficulty area depends on the core mode. Jahr: year-distance chips + hint.
// Title & Artist: chips hidden, a fixed scoring summary shown instead.
function _renderDifficulty() {
    const display = difficultyDisplayFor(chosenTitleArtistMode);
    const group = document.getElementById('wiz-difficulty');
    const hintEl = document.getElementById('wiz-difficulty-hint');
    const summaryEl = document.getElementById('wiz-difficulty-summary');
    if (group) group.classList.toggle('hidden', !display.showChips);
    if (hintEl) hintEl.classList.toggle('hidden', !display.showChips);
    if (summaryEl) {
        summaryEl.classList.toggle('hidden', display.showChips);
        if (display.summaryKey) {
            summaryEl.textContent = _t(display.summaryKey, 'Title 10 · Artist 5 · Partial 5/3');
        }
    }
    if (display.showChips) {
        _renderChipGroup('wiz-difficulty', DIFFICULTIES, chosenDifficulty, (val) => {
            chosenDifficulty = val;
            _renderDifficulty();
        });
        _renderDifficultyHint();
    }
}

function _renderGameMode() {
    _renderCoreMode();
    _renderDifficulty();
    _renderChipGroup('wiz-timer', DURATIONS, chosenDuration, (val) => {
        chosenDuration = val;
        _renderGameMode();
    });
    _renderChipGroup('wiz-autoadvance', AUTO_ADVANCE_OPTIONS, chosenRevealAutoAdvance, (val) => {
        chosenRevealAutoAdvance = parseInt(val, 10) || 0;
        _renderGameMode();
    });
    _renderChipGroup('wiz-language', LANGUAGES, chosenLanguage, async (val) => {
        chosenLanguage = val;
        // Switch the UI language immediately so the user sees the wizard in the
        // language they just picked. Without this, "Ansagesprache" only took
        // effect after the wizard closed + the page reloaded.
        if (typeof window !== 'undefined' && window.BeatifyI18n && typeof window.BeatifyI18n.setLanguage === 'function') {
            try {
                await window.BeatifyI18n.setLanguage(val);
                if (typeof window.BeatifyI18n.initPageTranslations === 'function') {
                    window.BeatifyI18n.initPageTranslations();
                }
            } catch (e) { console.warn('[Beatify] language switch failed:', e); }
        }
        _renderGameMode();
    });
    _renderGameModes();
}

function _lightsDetailHtml() {
    const lights = cachedLights || [];
    const rows = lights.length
        ? lights.map((l) => {
              const checked = chosenLightEntityIds.has(l.entity_id) ? 'checked' : '';
              const searchable = `${l.friendly_name || ''} ${l.entity_id}`.toLowerCase();
              return `<label class="wiz-detail-check" data-light-search="${searchable.replace(/"/g, '&quot;')}">
            <input type="checkbox" data-light-id="${l.entity_id}" ${checked}>
            <span class="wiz-detail-check-name">${l.friendly_name || l.entity_id}</span>
          </label>`;
          }).join('')
        : `<div class="wiz-detail-empty">${_t('wizard.step5.lights.noneFound', 'No lights available')}</div>`;
    // #1039: search input above the entity list — long HA installs have 10+
    // light.* entities, alphabetical scroll is the only way to find one today.
    // Filter is applied via class toggle so chosenLightEntityIds (the source
    // of truth for selection state) is untouched when rows hide/show.
    const searchInput = lights.length > 1
        ? `<input type="text" id="wiz-light-search" class="wiz-detail-input wiz-light-search"
             placeholder="${_t('wizard.step5.lights.searchPlaceholder', 'Search lights…')}"
             aria-label="${_t('wizard.step5.lights.searchPlaceholder', 'Search lights…')}">`
        : '';
    const chip = (id, label, group) => buildWizChip(id, label, group, group === 'intensity' ? chosenLightIntensity : chosenLightMode);

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
            ${searchInput}
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
              ${chip('static', _t('wizard.step5.lights.modeStatic', 'Static'), 'light-mode')}
              ${chip('dynamic', _t('wizard.step5.lights.modeDynamic', 'Dynamic'), 'light-mode')}
              ${chip('wled', 'WLED', 'light-mode')}
            </div>
          </div>
          ${wledBlock}
        </div>`;
}

function _ttsDetailHtml() {
    // Verbosity presets mirror the admin TTS panel. Picking one here expands
    // to the same 23 announce_* booleans on save (see _persistLevelUpDetails).
    const presetChip = (id, label) => `<button type="button" class="wiz-chip ${chosenTtsPreset === id ? 'active' : ''}" data-tts-preset="${id}">${label}</button>`;
    // A hand-tuned config (preset 'custom', set in the admin panel) shows a
    // non-selectable Custom chip so the user sees their tuning is preserved.
    const customChip = chosenTtsPreset === 'custom'
        ? `<button type="button" class="wiz-chip active" aria-disabled="true" data-tts-preset-custom>${_t('wizard.step5.tts.presetCustom', 'Custom')}</button>`
        : '';
    // #1073: dropdown of registered tts.* entities instead of a free-text
    // field. Falls back to the legacy text input only if the API failed to
    // load any entities (e.g. offline or older HA) so the wizard never
    // becomes un-completable.
    const entities = cachedTtsEntities || [];
    const escapeAttr = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const escapeText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const known = new Set(entities.map((e) => e.entity_id));
    const optsHtml = entities.map((e) => {
        const label = e.friendly_name && e.friendly_name !== e.entity_id
            ? `${e.friendly_name} (${e.entity_id})`
            : e.entity_id;
        const selected = e.entity_id === chosenTtsEntityId ? ' selected' : '';
        return `<option value="${escapeAttr(e.entity_id)}"${selected}>${escapeText(label)}</option>`;
    }).join('');
    // Preserve renamed/removed entities so the saved value is visible.
    const staleOpt = (chosenTtsEntityId && !known.has(chosenTtsEntityId))
        ? `<option value="${escapeAttr(chosenTtsEntityId)}" selected>${escapeText(chosenTtsEntityId)} ${_t('wizard.step5.tts.entityStale', '(not currently registered)')}</option>`
        : '';
    const placeholderLabel = entities.length === 0
        ? _t('wizard.step5.tts.entityNone', 'No TTS entities — add one in HA first')
        : _t('wizard.step5.tts.entityPlaceholder', '— Select TTS entity —');
    const entityFieldHtml = `
            <select id="wiz-tts-entity" class="wiz-detail-input">
              <option value=""${chosenTtsEntityId ? '' : ' selected'}>${escapeText(placeholderLabel)}</option>
              ${optsHtml}
              ${staleOpt}
            </select>`;
    return `
        <div class="wiz-detail">
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.tts.entityLabel', 'TTS service (entity ID)')}</span>
            ${entityFieldHtml}
            <span class="wiz-field-hint">${_t('wizard.step5.tts.entityHint', "No TTS service yet? In Home Assistant: Settings → Devices & Services → Add Integration → 'Google Translate text-to-speech' (free, no API key). It will then appear in this list.")}</span>
            <button type="button" id="wiz-tts-test" class="btn btn-ghost wiz-detail-test" ${chosenTtsEntityId ? '' : 'disabled'}>
              🔊 ${_t('wizard.step5.tts.test', 'Send test announcement')}
            </button>
          </div>
          <div class="wiz-field">
            <span class="wiz-field-label">${_t('wizard.step5.tts.verbosity', 'Verbosity')}</span>
            <div class="wiz-chip-group">
              ${presetChip('minimal', _t('wizard.step5.tts.presetMinimal', 'Minimal'))}
              ${presetChip('standard', _t('wizard.step5.tts.presetStandard', 'Standard'))}
              ${presetChip('full', _t('wizard.step5.tts.presetFull', 'Full'))}
              ${customChip}
            </div>
            <span class="wiz-field-hint">${_t('wizard.step5.tts.verbosityHint', 'How much the game announces. Fine-tune individual events later in admin settings.')}</span>
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
    // #1039: filter light rows by substring match on friendly_name/entity_id.
    // Hide via inline display so chosenLightEntityIds is unaffected — clearing
    // the search restores rows with their original checkbox state intact.
    const lightSearch = list.querySelector('#wiz-light-search');
    if (lightSearch) {
        lightSearch.addEventListener('input', () => {
            const q = lightSearch.value.trim().toLowerCase();
            list.querySelectorAll('[data-light-search]').forEach((row) => {
                const hay = row.getAttribute('data-light-search') || '';
                row.style.display = !q || hay.includes(q) ? '' : 'none';
            });
        });
    }
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

    // TTS fields — #1073 made wiz-tts-entity a <select>; listen for change.
    const ttsInput = document.getElementById('wiz-tts-entity');
    const ttsTestBtn = document.getElementById('wiz-tts-test');
    if (ttsInput) {
        const ttsOnPick = () => {
            chosenTtsEntityId = (ttsInput.value || '').trim();
            if (ttsTestBtn) ttsTestBtn.disabled = !chosenTtsEntityId;
        };
        ttsInput.addEventListener('change', ttsOnPick);
        // Keep 'input' too for older fallback environments.
        ttsInput.addEventListener('input', ttsOnPick);
    }
    if (ttsTestBtn) {
        ttsTestBtn.addEventListener('click', async () => {
            if (!chosenTtsEntityId) return;
            // #793: tts.speak needs both a TTS entity AND a media player.
            // Use the speaker the user picked in Step 1 — announcements
            // come out of the same speaker as the music.
            if (!chosenSpeaker) {
                ttsTestBtn.innerHTML = '✗ ' + _t('wizard.step5.tts.testNoSpeaker', 'Pick a speaker first');
                setTimeout(() => {
                    ttsTestBtn.innerHTML = '🔊 ' + _t('wizard.step5.tts.test', 'Test');
                    ttsTestBtn.disabled = !chosenTtsEntityId;
                }, 3000);
                return;
            }
            const orig = ttsTestBtn.innerHTML;
            ttsTestBtn.disabled = true;
            ttsTestBtn.innerHTML = '🔊 …';
            try {
                const r = await BeatifyAuth.fetch('/beatify/api/tts-test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        entity_id: chosenTtsEntityId,
                        media_player_entity_id: chosenSpeaker,
                        message: 'Beatify TTS test — this is working!',
                    }),
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
    list.querySelectorAll('[data-tts-preset]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            chosenTtsPreset = btn.dataset.ttsPreset;
            _renderLevelUp();
        });
    });
}

function _persistLevelUpDetails() {
    try {
        if (chosenLevelUps.lights) {
            // #1011: include `enabled: true` so party-lights.js hydrates the
            // toggle state (it reads `saved.enabled || false`). Without this,
            // the wizard saved lights + entities but the admin start-game
            // request sent `enabled: false`, and the server skipped
            // configure_party_lights — lights never reacted during the game.
            const payload = {
                enabled: true,
                lights: Array.from(chosenLightEntityIds),
                intensity: chosenLightIntensity,
                light_mode: chosenLightMode,
            };
            if (chosenLightMode === 'wled' && Object.keys(chosenWledPresets).length > 0) {
                payload.wled_presets = chosenWledPresets;
            }
            localStorage.setItem('beatify_party_lights', JSON.stringify(payload));
        }
        // Write a complete config: enabled + entity + preset + all 23
        // announce_* booleans, so the admin TTS panel and game engine read a
        // consistent state. BeatifyTtsPresets is exposed by tts-settings.js.
        const ttsPayload = {
            enabled: chosenLevelUps.tts,
            entity_id: chosenTtsEntityId,
            preset: chosenTtsPreset,
        };
        const presets = window.BeatifyTtsPresets;
        if (presets && chosenTtsPreset !== 'custom') {
            const vals = presets.presetValues(chosenTtsPreset);
            presets.KEYS.forEach((k) => { ttsPayload[k] = vals[k]; });
        } else if (presets && chosenTtsPreset === 'custom') {
            // Preserve hand-tuned toggles from the admin panel — don't clobber.
            const prev = JSON.parse(localStorage.getItem('beatify_tts') || '{}');
            presets.KEYS.forEach((k) => {
                if (typeof prev[k] === 'boolean') ttsPayload[k] = prev[k];
            });
        }
        localStorage.setItem('beatify_tts', JSON.stringify(ttsPayload));
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

    // #1180: lead the mode line with the core game mode so the host can confirm
    // Title & Artist vs Year at a glance. Difficulty is year-only, so it's
    // dropped in T&I mode (where it doesn't affect scoring).
    const coreModeLabel = chosenTitleArtistMode
        ? _t('wizard.step4.modeTitleArtist', 'Title & Artist')
        : _t('wizard.step4.modeYear', 'Year mode');
    const modeSummary = chosenTitleArtistMode
        ? `${coreModeLabel} · ${chosenDuration}s · ${chosenLanguage.toUpperCase()}`
        : `${coreModeLabel} · ${chosenDifficulty} · ${chosenDuration}s · ${chosenLanguage.toUpperCase()}`;

    el.innerHTML = `
        <div class="wiz-done-line"><span>${_t('wizard.summary.speaker', 'Speaker')}</span><strong>${speaker}</strong></div>
        <div class="wiz-done-line"><span>${_t('wizard.summary.service', 'Service')}</span><strong>${provider}</strong></div>
        <div class="wiz-done-line"><span>${_t('wizard.summary.playlist', 'Playlist')}</span><strong>${playlistLabel}</strong></div>
        <div class="wiz-done-line"><span>${_t('wizard.summary.mode', 'Mode')}</span><strong>${modeSummary}</strong></div>
        <div class="wiz-done-line"><span>${_t('wizard.summary.atmosphere', 'Atmosphere')}</span><strong>${atmosphere}</strong></div>
    `;
}

function _playlistName(id) {
    if (!id) return '—';
    // Prefer the hub's lookup — it's the authoritative source after step 3.
    // Falls back to cachedStatus for the case where the summary renders
    // before the hub has ever been mounted (shouldn't happen, defensive).
    const hubMatch = plhGetPlaylistByPath(id);
    if (hubMatch) return hubMatch.name || hubMatch.filename || id;
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
            revealAutoAdvance: chosenRevealAutoAdvance,
            language: chosenLanguage,
            artistChallenge: chosenArtistChallenge,
            movieQuiz: chosenMovieQuiz,
            introMode: chosenIntroMode,
            closestWinsMode: chosenClosestWins,
            titleArtistMode: chosenTitleArtistMode,  // #1180
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
            if (typeof s.revealAutoAdvance === 'number') chosenRevealAutoAdvance = s.revealAutoAdvance;
            // #815 + #822: prefer the BROWSER's language as the game-language
            // default. Saved value only wins if browser detection isn't
            // available.
            //
            // Why navigator.language (via detectBrowserLanguage), not
            // BeatifyI18n.getLanguage()?  Earlier rc15/rc17 attempts used
            // getLanguage() but `admin.js:loadSavedSettings()` calls
            // BeatifyI18n.setLanguage(settings.language) on every page
            // load — which silently overrides the auto-detected language
            // with whatever's in localStorage. A user with `navigator
            // .language='de-DE'` plus stale settings.language='en' from a
            // pre-rc15 wizard run would see currentLanguage='en' by the
            // time the wizard opened, and the rc17 fix returned 'en' too.
            // detectBrowserLanguage() is a pure read of navigator.language
            // — no session state, no race.
            //
            // Power users who actually want game-language ≠ browser-
            // language can tap the chip during the wizard; that explicit
            // tap re-saves and persists across reloads via the chip
            // handler in wizard.js's _renderChipGroup callback.
            let _resolvedLang = null;
            try {
                if (window.BeatifyI18n && typeof window.BeatifyI18n.detectBrowserLanguage === 'function') {
                    _resolvedLang = window.BeatifyI18n.detectBrowserLanguage();
                }
            } catch (e) { /* ignore */ }
            if (!_resolvedLang && s.language) _resolvedLang = s.language;
            if (_resolvedLang) chosenLanguage = _resolvedLang;
            if (typeof s.artistChallenge === 'boolean') chosenArtistChallenge = s.artistChallenge;
            if (typeof s.movieQuiz === 'boolean') chosenMovieQuiz = s.movieQuiz;
            if (typeof s.introMode === 'boolean') chosenIntroMode = s.introMode;
            if (typeof s.closestWinsMode === 'boolean') chosenClosestWins = s.closestWinsMode;
            if (typeof s.titleArtistMode === 'boolean') chosenTitleArtistMode = s.titleArtistMode;
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
        // #1073: prefetch TTS entities so the picker renders synchronously
        // alongside the lights detail. Cheap call, gated on has_tts.
        if (cachedCapabilities && cachedCapabilities.has_tts && cachedTtsEntities === null) {
            cachedTtsEntities = await _fetchTtsEntities();
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
        // Sync the admin's in-memory game settings from the choices the wizard
        // just persisted (mode, difficulty, bonuses, language, playlists) BEFORE
        // refreshing status + entering home. The admin reads beatify_game_settings
        // only once at page-init, so without this the start-game payload would
        // ignore the wizard's selections (e.g. Title & Artist mode) and run with
        // stale/default values. See window.loadSavedSettings in admin.js (#1180).
        if (typeof window !== 'undefined' && typeof window.loadSavedSettings === 'function') {
            try { await window.loadSavedSettings(); } catch (e) { /* non-fatal */ }
        }
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
    window.BeatifyWizard = { init, show, hide, refreshPlaylistHub };
}
