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
let chosenPlaylist = null;
const chosenLevelUps = { lights: false, tts: false, tuning: false };

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

function _setProgress(step) {
    const segs = document.querySelectorAll('#wiz-progress .wiz-seg');
    segs.forEach((seg, i) => {
        const stepNum = i + 1;
        seg.classList.remove('filled', 'active');
        if (stepNum < step) seg.classList.add('filled');
        else if (stepNum === step) seg.classList.add('active');
    });
    const label = document.getElementById('wiz-step-count');
    if (label) {
        if (step <= 3) label.textContent = `Step ${step} of 3`;
        else if (step === 4) label.textContent = 'Optional';
        else label.textContent = 'All set';
    }
}

function _showFrame(n) {
    document.querySelectorAll('.wiz-frame').forEach((frame) => {
        const frameNum = parseInt(frame.dataset.frame, 10);
        if (frameNum === n) frame.removeAttribute('hidden');
        else frame.setAttribute('hidden', '');
    });
    currentStep = n;
    _setProgress(Math.min(n, 3));
    _updateCta();
    // Persist wizard state so refresh / revisit resumes at the right step.
    // Skip persisting step 5 (done) here — _advance() writes the final 'done' state.
    if (n >= 1 && n <= 4) {
        try { localStorage.setItem(LS_WIZARD_STATE, `step${n}`); } catch (e) { /* private mode */ }
    }
}

function _updateCta() {
    const nextBtn = document.getElementById('wiz-next');
    const backBtn = document.getElementById('wiz-back');
    const skipBtn = document.getElementById('wiz-skip');
    if (!nextBtn || !backBtn) return;

    backBtn.style.display = currentStep > 1 && currentStep < 5 ? '' : 'none';

    if (currentStep === 1) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenSpeaker;
    } else if (currentStep === 2) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenProvider;
    } else if (currentStep === 3) {
        nextBtn.textContent = _t('wizard.continue', 'Continue');
        nextBtn.disabled = !chosenPlaylist;
    } else if (currentStep === 4) {
        nextBtn.textContent = _t('wizard.finish', 'Finish');
        nextBtn.disabled = false;
    } else if (currentStep === 5) {
        nextBtn.textContent = _t('wizard.startGame', 'Start first game');
        nextBtn.disabled = false;
    }

    if (skipBtn) skipBtn.style.display = currentStep < 5 ? '' : 'none';
}

// ------------------------------------------------------------------
// Step renderers
// ------------------------------------------------------------------

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
          <div class="wiz-row-avatar"></div>
          <div class="wiz-row-text">
            <div class="wiz-row-name">${p.friendly_name || p.entity_id}</div>
            <div class="wiz-row-sub">${p.platform || p.state || ''}</div>
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
            const status = document.getElementById('wiz-oauth-status');
            if (status) {
                status.classList.remove('hidden');
                status.innerHTML = `<strong>${_t('wizard.step2.authPrompt', 'Authorize Beatify')}</strong><br>${_t(
                    'wizard.step2.authDetail',
                    'Close this wizard, authorize in the Music Service section, then re-open the wizard to continue.'
                )}`;
            }
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
            const selected = chosenPlaylist === id;
            return `<button type="button" class="wiz-row ${selected ? 'selected' : ''}" data-playlist-id="${id}">
          <div class="wiz-row-avatar"></div>
          <div class="wiz-row-text">
            <div class="wiz-row-name">${p.name || p.filename}</div>
            <div class="wiz-row-sub">${(p.song_count || p.count || 0)} songs</div>
          </div>
        </button>`;
        })
        .join('');
    list.querySelectorAll('[data-playlist-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
            chosenPlaylist = btn.dataset.playlistId;
            _renderPlaylists();
            _updateCta();
        });
    });
}

function _renderLevelUp() {
    const list = document.getElementById('wiz-levelup-list');
    if (!list || !cachedCapabilities) return;
    const caps = cachedCapabilities;
    const cards = [
        {
            key: 'lights',
            title: _t('wizard.step4.lights.title', 'Party lights'),
            desc: caps.has_lights
                ? _t('wizard.step4.lights.desc', 'Sync your Hue lights to the beat. Pulse on round changes, flash on winner.')
                : _t('wizard.step4.lights.unavailable', 'No lights found in Home Assistant.'),
            available: caps.has_lights,
        },
        {
            key: 'tts',
            title: _t('wizard.step4.tts.title', 'Voice announcements'),
            desc: caps.has_tts
                ? _t('wizard.step4.tts.desc', 'TTS calls out round numbers, winners, and fun facts.')
                : _t('wizard.step4.tts.unavailable', 'No TTS service registered in Home Assistant.'),
            available: caps.has_tts,
        },
        {
            key: 'tuning',
            title: _t('wizard.step4.tuning.title', 'Game tuning'),
            desc: _t('wizard.step4.tuning.desc', 'Default: 10 rounds, 45s, English. Tap to customize difficulty and language in admin settings.'),
            available: true,
        },
    ];
    list.innerHTML = cards
        .map((card) => {
            const on = chosenLevelUps[card.key] && card.available;
            return `<button type="button" class="wiz-lvl-card ${on ? 'on' : ''} ${!card.available ? 'unavailable' : ''}" data-levelup="${card.key}" ${!card.available ? 'disabled' : ''}>
          <div class="wiz-lvl-text">
            <div class="wiz-lvl-title">${card.title}</div>
            <div class="wiz-lvl-desc">${card.desc}</div>
          </div>
          <div class="wiz-lvl-toggle"></div>
        </button>`;
        })
        .join('');
    list.querySelectorAll('[data-levelup]').forEach((btn) => {
        if (btn.disabled) return;
        btn.addEventListener('click', () => {
            const key = btn.dataset.levelup;
            chosenLevelUps[key] = !chosenLevelUps[key];
            _renderLevelUp();
        });
    });
}

function _renderDoneSummary() {
    const el = document.getElementById('wiz-done-summary');
    if (!el) return;
    const parts = [];
    if (chosenSpeaker) parts.push(chosenSpeaker.replace('media_player.', ''));
    if (chosenProvider) parts.push(chosenProvider.replace('_', ' '));
    if (chosenPlaylist) parts.push(chosenPlaylist.split('/').pop().replace('.json', ''));
    const extras = [];
    if (chosenLevelUps.lights) extras.push('lights');
    if (chosenLevelUps.tts) extras.push('voice');
    if (extras.length) parts.push(extras.join(' + ') + ' on');
    el.textContent = parts.join(' · ') + '. Scan a QR code, start playing.';
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
        }
    } catch (e) { /* private mode or malformed JSON */ }
    _renderSpeakers();
    _renderProviders();
    _renderPlaylists();
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
    if (currentStep === 3) {
        if (!cachedCapabilities) cachedCapabilities = await _fetchCapabilities();
        _renderLevelUp();
        _showFrame(4);
        return;
    }
    if (currentStep === 4) {
        _renderDoneSummary();
        _showFrame(5);
        return;
    }
    if (currentStep === 5) {
        try { localStorage.setItem(LS_WIZARD_STATE, 'done'); } catch (e) { /* private mode */ }
        hide({ dismissed: false });
        if (typeof window !== 'undefined' && typeof window.loadStatus === 'function') {
            window.loadStatus();
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
