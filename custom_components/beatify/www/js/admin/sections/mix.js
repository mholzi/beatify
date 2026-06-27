/**
 * Beatify Admin — Smart Playlist Mixer section (#1538, design option 1 "chip-cloud").
 *
 * Adds a "Mix" tab to the playlist section: pick decade/style/region/special
 * tag chips + a target song count (30/50/100), live-preview how many songs and
 * playlists the selection would yield, then "Start mix" — which asks the backend
 * (`POST /beatify/api/playlists/mix`) to assemble + de-dupe a transient playlist
 * and starts the game with it through the EXISTING start-game path (we reuse the
 * admin core's `startGame`, no payload duplication).
 *
 * Taxonomy: reuses `TAG_CATEGORIES` from constants.js (the SAME tags that drive
 * the Issue #70 playlist filter bar) — only the tags actually present across the
 * discovered playlists are shown as chips, so empty categories disappear.
 *
 * State: reads the shared `adminState` (admin/state.js) directly — same pattern
 * as playlists.js. The mixer's own selection lives in module-local state because
 * it never crosses a module boundary.
 */

import { adminState } from '../state.js';
import { TAG_CATEGORIES } from '../constants.js';

const utils = (typeof window !== 'undefined' && window.BeatifyUtils) || {};

/**
 * HTML-escape for the data-driven tracklist preview (#1586). Prefers the shared
 * BeatifyUtils.escapeHtml when present (browser), but falls back to a pure
 * regex escape so the markup builders stay testable in the DOM-less vitest env.
 */
const escapeHtml = (value) => {
    if (utils && typeof utils.escapeHtml === 'function') return utils.escapeHtml(value);
    return String(value === null || value === undefined ? '' : value)
        .replace(/[&<>"']/g, (ch) => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
        ));
};

// Module-local mixer selection (does not cross a module boundary).
const mixState = {
    selectedTags: new Set(),
    targetCount: 50,
    _previewTimer: null,
    _startGame: null,        // injected admin-core startGame()
};

const t = (key, fallback) =>
    (typeof window !== 'undefined' && window.BeatifyI18n && window.BeatifyI18n.t)
        ? (window.BeatifyI18n.t(key) !== key ? window.BeatifyI18n.t(key) : fallback)
        : fallback;

/**
 * Per-category accent so chips read as "Decade=cyan, Style=pink, …" — matches
 * the option-1 mockup (80s/90s cyan-active, Pop pink-active). Falls back to the
 * cyan filter-chip default for any category without an explicit accent.
 */
const CATEGORY_ACCENT = {
    decade: 'cyan',
    style: 'pink',
    region: 'indigo',
    special: 'cyan',
};

/**
 * Build the chip-cloud rows from the tags present across discovered playlists.
 * Called on each playlist (re)load so the chips always reflect the real catalogue.
 */
export function renderMixChipCloud() {
    const cloud = document.getElementById('mix-chip-cloud');
    if (!cloud) return;

    // Which tags actually exist across the discovered playlists.
    const available = new Set();
    (adminState.playlistData || []).forEach((p) => {
        (p.tags || []).forEach((tag) => available.add(tag));
    });

    // Drop selected tags that no longer exist (catalogue changed).
    mixState.selectedTags.forEach((tag) => {
        if (!available.has(tag)) mixState.selectedTags.delete(tag);
    });

    const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

    let html = '';
    Object.entries(TAG_CATEGORIES).forEach(([key, category]) => {
        const tags = category.tags.filter((tag) => available.has(tag));
        if (tags.length === 0) return;
        const accent = CATEGORY_ACCENT[key] || 'cyan';
        html += `
            <div class="mix-chip-row">
                <span class="mix-chip-rowlabel">${utils.escapeHtml(category.label)}</span>
                <div class="mix-chip-group" data-accent="${accent}">
                    ${tags.map((tag) => {
                        const active = mixState.selectedTags.has(tag);
                        return `<button type="button" class="mix-chip${active ? ' active' : ''}"
                                    aria-pressed="${active}"
                                    data-mix-tag="${utils.escapeHtml(tag)}">${utils.escapeHtml(cap(tag))}</button>`;
                    }).join('')}
                </div>
            </div>`;
    });

    if (!html) {
        html = `<p class="mix-empty">${utils.escapeHtml(
            t('admin.mixNoTags', 'No tagged playlists found to mix from.'),
        )}</p>`;
    }

    cloud.innerHTML = html;

    cloud.querySelectorAll('.mix-chip').forEach((chip) => {
        chip.addEventListener('click', () => toggleTag(chip));
    });

    updateMixPreview();
}

function toggleTag(chip) {
    const tag = chip.dataset.mixTag;
    if (mixState.selectedTags.has(tag)) {
        mixState.selectedTags.delete(tag);
        chip.classList.remove('active');
        chip.setAttribute('aria-pressed', 'false');
    } else {
        mixState.selectedTags.add(tag);
        chip.classList.add('active');
        chip.setAttribute('aria-pressed', 'true');
    }
    scheduleMixPreview();
}

function setTargetCount(count) {
    mixState.targetCount = count;
    document.querySelectorAll('.mix-seg').forEach((seg) => {
        const active = parseInt(seg.dataset.mixCount, 10) === count;
        seg.classList.toggle('active', active);
        seg.setAttribute('aria-checked', active ? 'true' : 'false');
    });
    updateMixPreview();
}

/**
 * Local, instant preview estimate. Counts how many discovered playlists match
 * ANY selected tag (union semantics, mirrors the backend) and sums their songs
 * for the selected provider, then caps at the target. This is an UPPER bound
 * (no cross-playlist dedup client-side); the backend returns the exact figure
 * after assembly. Cheap enough to run on every toggle — no network call.
 */
function updateMixPreview() {
    const textEl = document.getElementById('mix-preview-text');
    const startBtn = document.getElementById('mix-start');
    const previewBtn = document.getElementById('mix-preview-btn');
    if (!textEl) return;

    // Any selection change makes a previously-fetched tracklist stale — collapse
    // it so the host never sees a preview that no longer matches the chips.
    hideMixTracklist();

    const enableActions = (on) => {
        if (startBtn) startBtn.disabled = !on;
        if (previewBtn) previewBtn.disabled = !on;
    };

    const tags = mixState.selectedTags;
    if (tags.size === 0) {
        textEl.textContent = t('admin.mixPreviewEmpty', 'Select tags to preview your mix.');
        enableActions(false);
        return;
    }

    let matchedPlaylists = 0;
    let songSum = 0;
    (adminState.playlistData || []).forEach((p) => {
        if (!p.is_valid) return;
        const pTags = p.tags || [];
        if (!pTags.some((tag) => tags.has(tag))) return;
        matchedPlaylists += 1;
        songSum += providerCountFor(p);
    });

    if (matchedPlaylists === 0) {
        textEl.textContent = t('admin.mixPreviewNone', 'No playlists match these tags.');
        enableActions(false);
        return;
    }

    const est = Math.min(songSum, mixState.targetCount);
    const tmpl = t('admin.mixPreview', '≈ {songs} songs from {playlists} playlists · duplicates removed');
    textEl.textContent = tmpl
        .replace('{songs}', String(est))
        .replace('{playlists}', String(matchedPlaylists));
    enableActions(true);
}

function scheduleMixPreview() {
    clearTimeout(mixState._previewTimer);
    mixState._previewTimer = setTimeout(updateMixPreview, 60);
}

/**
 * Build the tracklist-preview markup from the backend's `preview` response
 * (#1586). Pure (no DOM / no globals beyond the i18n + escape helpers) so it
 * stays unit-testable in the DOM-less vitest env. `tracks` is the array of
 * `{ title, artist, year }` the mix endpoint returns for `preview: true`.
 */
export function _mixTracklistHtml(tracks) {
    const list = Array.isArray(tracks) ? tracks : [];
    if (list.length === 0) {
        return `<p class="mix-tracklist-empty">${escapeHtml(
            t('admin.mixTracklistEmpty', 'No tracks to preview.'),
        )}</p>`;
    }

    const heading = t('admin.mixTracklistHeading', '{count} tracks in this mix')
        .replace('{count}', String(list.length));

    const items = list.map((track) => {
        const title = escapeHtml(track.title || '');
        const artist = escapeHtml(track.artist || '');
        const year = track.year
            ? ` <span class="mix-track-year">${escapeHtml(String(track.year))}</span>`
            : '';
        return `<li class="mix-track">`
            + `<span class="mix-track-title">${title}</span>`
            + `<span class="mix-track-artist">${artist}</span>${year}</li>`;
    }).join('');

    return `<p class="mix-tracklist-head">${escapeHtml(heading)}</p>`
        + `<ol class="mix-track-list">${items}</ol>`;
}

/** Render (and reveal) the tracklist preview into the hub-rendered container. */
function renderMixTracklist(tracks) {
    const el = document.getElementById('mix-tracklist');
    if (!el) return;
    el.innerHTML = _mixTracklistHtml(tracks);
    el.classList.remove('hidden');
    document.getElementById('mix-preview-btn')?.setAttribute('aria-expanded', 'true');
}

/** Collapse + empty the tracklist preview (selection changed / not yet fetched). */
function hideMixTracklist() {
    const el = document.getElementById('mix-tracklist');
    if (!el) return;
    el.classList.add('hidden');
    el.innerHTML = '';
    document.getElementById('mix-preview-btn')?.setAttribute('aria-expanded', 'false');
}

/**
 * "Preview tracklist": ask the backend to assemble + de-dupe the mix in
 * preview mode (no file written) and render the resulting tracklist so the host
 * sees exactly which songs land in the mix before committing (#1586). Reuses
 * the same `/beatify/api/playlists/mix` endpoint + payload as `startMix`, only
 * with `preview: true`.
 */
async function previewMixTracklist() {
    clearMixError();
    const btn = document.getElementById('mix-preview-btn');

    if (mixState.selectedTags.size === 0) {
        showMixError(t('admin.mixNoTagsSelected', 'Select at least one tag.'));
        return;
    }

    const origText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = t('admin.mixPreviewLoading', 'Loading preview…');
    }

    try {
        const auth = window.BeatifyAuth;
        const fetcher = (auth && typeof auth.fetch === 'function')
            ? auth.fetch.bind(auth)
            : window.fetch.bind(window);

        const response = await fetcher('/beatify/api/playlists/mix', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tags: Array.from(mixState.selectedTags),
                target_count: mixState.targetCount,
                provider: adminState.selectedProvider,
                preview: true,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            let msg = data.message || t('admin.mixFailed', 'Failed to assemble mix.');
            if (data.code && window.BeatifyI18n) {
                const key = 'errors.' + String(data.code).toUpperCase();
                const tr = BeatifyI18n.t(key);
                if (tr && tr !== key) msg = tr;
            }
            showMixError(msg);
            return;
        }

        renderMixTracklist(data.tracks || []);
    } catch (err) {
        console.error('[Beatify] previewMixTracklist failed:', err);
        showMixError(t('admin.mixFailed', 'Failed to assemble mix.'));
    } finally {
        if (btn) {
            btn.textContent = origText;
            btn.disabled = false;
        }
    }
}

/** Provider-specific song count for a playlist (mirrors playlists.js logic). */
function providerCountFor(p) {
    const songCount = p.song_count || 0;
    switch (adminState.selectedProvider) {
        case 'spotify': return p.spotify_count || songCount;
        case 'apple_music': return p.apple_music_count || 0;
        case 'youtube_music': return p.youtube_music_count || 0;
        case 'tidal': return p.tidal_count || 0;
        case 'deezer': return p.deezer_count || 0;
        case 'amazon_music': return p.amazon_music_count || songCount;
        default: return songCount;
    }
}

function showMixError(msg) {
    const el = document.getElementById('mix-error');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearMixError() {
    document.getElementById('mix-error')?.classList.add('hidden');
}

/**
 * #1619: Resolve the active media player into `adminState.selectedMediaPlayer`
 * from the same unified source the rest of the app uses, before the start gate.
 *
 * Inside the setup wizard the chosen speaker lives only in
 * `localStorage.beatify_last_player` (`chosenSpeaker` in wizard.js); the wizard
 * never writes the legacy admin global, and `BeatifyHome.hydrateFromStorage()`
 * only runs in the post-wizard Home view — not at wizard step 3 where the Mix
 * tab is rendered. Without this, "Mix starten" inside the wizard falsely reports
 * "Select a media player first" even though a speaker was picked in step 1.
 *
 * Idempotent: only fills the gap when the global is empty. Uses `globalThis`
 * (=== window in the browser) so it stays unit-testable in the node test env.
 */
export function ensureMediaPlayerHydrated() {
    if (adminState.selectedMediaPlayer && adminState.selectedMediaPlayer.entityId) {
        return;
    }
    // Prefer the tested admin bridge when present (also wires the radio + caps).
    try {
        globalThis.BeatifyHome?.hydrateFromStorage?.();
    } catch (e) { /* noop — fall through to the storage fallback */ }
    if (adminState.selectedMediaPlayer && adminState.selectedMediaPlayer.entityId) {
        return;
    }
    // Fallback: minimal stub from the wizard's saved speaker. Capability flags
    // default to false; the backend validates the player at start.
    let lastPlayerId = null;
    try {
        lastPlayerId = globalThis.localStorage?.getItem('beatify_last_player') || null;
    } catch (e) { /* private mode / no storage */ }
    if (lastPlayerId) {
        adminState.selectedMediaPlayer = { entityId: lastPlayerId, state: 'unknown', platform: 'unknown' };
    }
}

/**
 * "Start mix": ask the backend to assemble + de-dupe the mix, then start the
 * game through the existing admin-core start path. We deliberately funnel
 * through `startGame()` so every validated start-game concern (provider checks,
 * platform capabilities, wake-lock acquisition) is reused untouched.
 */
async function startMix() {
    clearMixError();
    const btn = document.getElementById('mix-start');

    if (mixState.selectedTags.size === 0) {
        showMixError(t('admin.mixNoTagsSelected', 'Select at least one tag.'));
        return;
    }
    // #1619: hydrate the wizard's saved speaker before gating, so the Mix tab
    // works at wizard step 3 (not just in the post-wizard Home view).
    ensureMediaPlayerHydrated();
    if (!adminState.selectedMediaPlayer) {
        showMixError(t('admin.mixNoMediaPlayer', 'Select a media player first.'));
        return;
    }

    const saveAsCommunity = !!document.getElementById('mix-save-community')?.checked;
    const origText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = t('admin.mixAssembling', 'Assembling…');
    }

    try {
        const auth = window.BeatifyAuth;
        const fetcher = (auth && typeof auth.fetch === 'function')
            ? auth.fetch.bind(auth)
            : window.fetch.bind(window);

        const response = await fetcher('/beatify/api/playlists/mix', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tags: Array.from(mixState.selectedTags),
                target_count: mixState.targetCount,
                provider: adminState.selectedProvider,
                save_as_community: saveAsCommunity,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            let msg = data.message || t('admin.mixFailed', 'Failed to assemble mix.');
            if (data.code && window.BeatifyI18n) {
                const key = 'errors.' + String(data.code).toUpperCase();
                const tr = BeatifyI18n.t(key);
                if (tr && tr !== key) msg = tr;
            }
            showMixError(msg);
            return;
        }

        // Feed the assembled playlist into the existing selection + start path.
        adminState.selectedPlaylists = [
            { path: data.path, songCount: data.song_count || 0 },
        ];

        if (saveAsCommunity && typeof window.loadStatus === 'function') {
            // Refresh so the new community playlist appears in the list tab.
            try { await window.loadStatus(); } catch (e) { /* non-fatal */ }
            // loadStatus re-renders playlists and would reset selection — re-apply.
            adminState.selectedPlaylists = [
                { path: data.path, songCount: data.song_count || 0 },
            ];
        }

        if (typeof mixState._startGame === 'function') {
            await mixState._startGame();
        } else {
            showMixError(t('admin.mixStartUnavailable', 'Mix assembled but the game could not be started.'));
        }
    } catch (err) {
        console.error('[Beatify] startMix failed:', err);
        showMixError(t('admin.mixFailed', 'Failed to assemble mix.'));
    } finally {
        if (btn) {
            btn.textContent = origText;
            btn.disabled = false;
        }
    }
}

/**
 * Bind the Mix-panel controls to whatever markup is currently in the DOM.
 *
 * #1568: the Mix panel markup is owned + rendered by the Playlist Hub
 * (playlist-hub.js) so it appears in EVERY hub mount — including the wizard
 * step-3 picker, which is the live first-run surface. The old flat
 * `#playlist-panel-mix` in admin.html was dead UI (the flat-setup sections are
 * `display:none` since rc11/#1138), so the Mix tab was unreachable. This binds
 * the target-count segmented control + the Start button and (re)builds the chip
 * cloud against the hub-rendered markup. Tab-switching is now owned by the hub
 * (no more `.playlist-tab` wiring here). Safe to call when the panel isn't
 * mounted yet — it no-ops.
 */
export function bindMixPanel() {
    const startBtn = document.getElementById('mix-start');
    if (!startBtn) return; // panel not in the DOM yet

    document.querySelectorAll('.mix-seg').forEach((seg) => {
        seg.addEventListener('click', () => setTargetCount(parseInt(seg.dataset.mixCount, 10)));
    });
    startBtn.addEventListener('click', startMix);
    document.getElementById('mix-preview-btn')?.addEventListener('click', previewMixTracklist);

    // Chips populate once loadStatus() has filled adminState.playlistData;
    // renderMixChipCloud is also called from admin.js on each (re)load and by
    // the hub when the Mix tab is shown.
    renderMixChipCloud();
}

/**
 * Wire the Mix tab once at admin init.
 * @param {{ startGame: Function }} deps - admin-core startGame, injected so the
 *   mixer reuses the validated start-game path without duplicating its payload.
 */
export function initMixTab(deps = {}) {
    mixState._startGame = deps.startGame || null;

    // The Mix panel now lives inside the component-owned Playlist Hub, which
    // renders its markup on mount — long after admin init runs. Expose the
    // binder + chip-cloud refresher on a global so the hub can wire the panel
    // once it has rendered the markup (mirrors window.PlaylistRequests etc.).
    window.BeatifyMixPanel = { bind: bindMixPanel, renderChips: renderMixChipCloud };

    // Bind now in case the panel is already present (defensive — normally the
    // hub calls bind() after it renders).
    bindMixPanel();
}
