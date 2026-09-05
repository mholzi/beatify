/**
 * Beatify Admin — Crate Digger (ma_library provider) panel.
 *
 * A root-scoped FACTORY: `mountLibraryPanel(rootEl, opts)` injects the panel
 * markup into any container and wires it, querying only within that root — so
 * the same panel mounts both in the admin settings section and in the setup
 * wizard's step 3 without ID collisions. All instances read/write the shared
 * `adminState` (single source of truth), so a value changed in the wizard is
 * what the admin panel shows later, and vice versa.
 *
 * Panel contents:
 *   - scan status (pool built? building? "N of M songs game-ready") with an
 *     existing-pool presentation: if a pool is already on the server (scans
 *     are server-side and shared across devices) the panel says so and offers
 *     "Rescan" instead of forcing a re-scan;
 *   - "Scan library" with live progress (server runs it in the background —
 *     MusicBrainz throttles to ~1 req/s, so first scans take a while; the
 *     wizard can be continued while it runs);
 *   - familiarity slider (worldwide fame: crowd-pleasers … deep cuts),
 *     songs-per-game, year-accuracy gate;
 *   - (admin mode) tools: "Save a fresh mix as playlist" and "Create with AI"
 *     (opens the library AI curation modal, js/admin/sections/library-ai.js).
 *
 * Endpoints: GET/POST /beatify/api/library-pool[/build],
 *            POST /beatify/api/library-playlists/generate.
 */

import { adminState } from '../state.js';
import { openLibraryAiModal } from './library-ai.js';

const POLL_INTERVAL_MS = 2000;

/** Auth-aware fetch: BeatifyAuth handles HA tokens; plain fetch as fallback. */
function _fetch(url, opts) {
    const f = (window.BeatifyAuth && window.BeatifyAuth.fetch) || fetch;
    return f(url, opts);
}

function _t(key, fallback) {
    const i18n = window.BeatifyI18n;
    if (i18n && typeof i18n.t === 'function') {
        const v = i18n.t(key);
        if (v && v !== key) return v;
    }
    return fallback;
}

// #2583: `difficultyLabelFor` mapped the slider value to its human label
// and was exported with no consumer anywhere.

/** The library settings for the start-game payload. */
export function getLibraryConfig() {
    return {
        popularity_percent: adminState.libraryPopPercent,
        size: adminState.librarySize,
        year_gate: adminState.libraryYearGate,
        genres: adminState.libraryGenres || [],
    };
}

/* ------------------------------------------------------------------ *
 *  Panel factory
 * ------------------------------------------------------------------ */

const _instances = [];

function _panelHtml(mode) {
    const tools = mode === 'admin' ? `
        <div class="library-settings__row library-tools">
            <span class="library-label" data-i18n="admin.library.tools">Playlists from your library</span>
            <div class="library-tools__buttons">
                <button type="button" class="lib-btn" data-lib="save-mix">
                    <span data-i18n="admin.library.saveMix">Save a fresh mix as playlist</span>
                </button>
                <button type="button" class="lib-btn" data-lib="ai-create">
                    <span data-i18n="admin.library.aiCreate">Create with AI…</span>
                </button>
            </div>
            <p class="hint-text" data-lib="tools-hint" data-i18n="admin.library.toolsHint">Saved playlists appear under Playlists, where they can be picked for games or deleted.</p>
        </div>` : '';
    return `
    <div class="library-card">
        <div class="library-card__title" data-i18n="admin.library.cardGame">Game settings</div>
        <div class="library-settings__row">
            <label class="library-label">
                <span data-i18n="admin.library.popularity">Song popularity</span>
                <span class="library-value" data-lib="pop-value">Top 50%</span>
            </label>
            <input type="range" class="lib-range" data-lib="pop-range" min="1" max="100" step="1" value="51">
            <div class="library-slider-legend">
                <span data-i18n="admin.library.popHard">Whole library</span>
                <span data-i18n="admin.library.popEasy">Only the biggest hits</span>
            </div>
            <p class="hint-text library-match-count" data-lib="match-count"></p>
            <p class="hint-text" data-i18n="admin.library.difficultyHint">Draws from the most popular slice of your library (worldwide popularity — guests never need to know the host's favourites).</p>
        </div>

        <div class="library-settings__row">
            <label class="library-label" data-i18n="admin.library.size">Songs per game</label>
            <select class="lib-input" data-lib="size">
                <option value="15">15</option>
                <option value="20">20</option>
                <option value="30">30</option>
                <option value="50">50</option>
                <option value="75">75</option>
            </select>
        </div>

        <div class="library-settings__row">
            <label class="library-label" data-i18n="admin.library.genres">Music genres</label>
            <div class="genre-chips" data-lib="genres">
                <span class="hint-text" data-i18n="admin.library.genresLoading">Genres appear here after a scan.</span>
            </div>
            <p class="hint-text" data-i18n="admin.library.genresHint">Pick none to allow everything. Genres come from your Plex/Jellyfin tags — rescan once after updating to collect them.</p>
        </div>
        ${tools}
        <p class="hint-text library-toast hidden" data-lib="toast" aria-live="polite"></p>
    </div>

    <div class="library-card">
        <div class="library-card__title" data-i18n="admin.library.cardScan">Your library</div>
        <div class="library-settings__status">
            <div class="library-pool-summary">
                <span class="spinner-inline hidden" data-lib="spinner" aria-hidden="true"></span>
                <span data-lib="status-text" data-i18n="admin.library.statusLoading">Checking your library…</span>
            </div>
        </div>
        <div class="library-scan-progress hidden" data-lib="progress">
            <div class="progress-track"><div class="progress-fill" data-lib="bar" style="width:0%"></div></div>
            <span class="hint-text" data-lib="progress-label"></span>
        </div>
        <div class="library-stats hidden" data-lib="stats"></div>

        <div class="library-settings__row">
            <label class="library-label" data-i18n="admin.library.scanSize">Songs to prepare when scanning</label>
            <div class="library-inline-row">
                <select class="lib-input" data-lib="scan-size">
                    <option value="1000">1,000 (~20 min)</option>
                    <option value="2500" selected>2,500 (~45 min)</option>
                    <option value="5000">5,000 (~1.5 h)</option>
                    <option value="10000">10,000 (~3 h)</option>
                    <option value="25000">25,000 (~8 h)</option>
                    <option value="0" data-i18n="admin.library.scanAll">Entire library (can take days)</option>
                </select>
                <button type="button" class="lib-btn" data-lib="scan-btn">
                    <span data-lib="scan-btn-label" data-i18n="admin.library.scanBtn">Scan library</span>
                </button>
            </div>
            <p class="hint-text" data-i18n="admin.library.scanSizeHint">Year verification is rate-limited to ~1 song/second by MusicBrainz. Each rescan keeps what's already prepared and adds more.</p>
        </div>

        <div class="library-settings__row">
            <label class="library-label" data-i18n="admin.library.yearGate">Year accuracy</label>
            <select class="lib-input" data-lib="year-gate">
                <option value="strict" data-i18n="admin.library.gateStrict">Strict — verified years only (recommended)</option>
                <option value="balanced" data-i18n="admin.library.gateBalanced">Balanced — also use Deezer years</option>
                <option value="tags_ok" data-i18n="admin.library.gateTags">Relaxed — also trust file tags</option>
            </select>
            <p class="hint-text" data-i18n="admin.library.yearGateHint">The game scores year guesses, so stricter is fairer. Relax only if too few songs qualify.</p>
        </div>

        <div class="library-settings__row library-refresh-row hidden" data-lib="refresh-row">
            <div class="library-inline-row">
                <span class="hint-text" data-lib="refresh-status"></span>
                <button type="button" class="lib-btn lib-btn--ghost" data-lib="refresh-btn">
                    <span data-i18n="admin.library.refreshBtn">Improve existing songs</span>
                </button>
            </div>
            <p class="hint-text" data-i18n="admin.library.refreshHint">Re-checks years and popularity of already-scanned songs with the newest, more accurate matching. Runs in the background and can take a few hours; you can scan or play meanwhile.</p>
        </div>
        <div class="library-settings__row library-recent-row" data-lib="recent-row">
            <div class="library-inline-row">
                <button type="button" class="lib-btn lib-btn--ghost" data-lib="recent-btn">
                    <span data-i18n="admin.library.recentBtn">Recently played — fix a song</span>
                </button>
            </div>
            <p class="hint-text" data-i18n="admin.library.recentHint">Spotted a wrong year during a game? Fix it here and every future game uses your correction.</p>
            <div data-lib="recent-list" class="library-recent-list hidden" aria-live="polite"></div>
        </div>
        <div class="library-settings__row library-backup-row" data-lib="backup-row">
            <div class="library-inline-row">
                <button type="button" class="lib-btn lib-btn--ghost" data-lib="backup-btn">
                    <span data-i18n="admin.library.backupBtn">Download backup</span>
                </button>
                <button type="button" class="lib-btn lib-btn--ghost" data-lib="restore-btn">
                    <span data-i18n="admin.library.restoreBtn">Restore from backup…</span>
                </button>
                <input type="file" accept=".gz,.json,application/gzip,application/json"
                       data-lib="restore-file" hidden>
            </div>
            <p class="hint-text" data-i18n="admin.library.backupHint">A scanned library is hours of lookups. The backup contains your scanned songs and these settings, so you can restore them after a reinstall or move them to another Home Assistant.</p>
            <p class="hint-text" data-lib="backup-status" aria-live="polite"></p>
        </div>
        <p class="hint-text library-version" data-lib="provider-version"></p>
    </div>`;
}

/**
 * Mount the library panel into `rootEl`.
 * @param {HTMLElement} rootEl  empty container to render into
 * @param {{mode?: 'admin'|'wizard', onChanged?: () => void}} opts
 * @returns {{refresh: () => void, destroy: () => void}}
 */
export function mountLibraryPanel(rootEl, opts = {}) {
    const mode = opts.mode || 'admin';
    const onChanged = opts.onChanged || null;
    rootEl.classList.add('library-settings');
    rootEl.innerHTML = _panelHtml(mode);
    if (window.BeatifyI18n && typeof window.BeatifyI18n.apply === 'function') {
        try { window.BeatifyI18n.apply(rootEl); } catch (e) { /* pre-init */ }
    }

    const $ = (sel) => rootEl.querySelector(`[data-lib="${sel}"]`);
    const inst = { root: rootEl, pollTimer: null, mode };

    // --- controls -> adminState (shared across instances) ---
    const popRange = $('pop-range');
    const popValue = $('pop-value');
    const size = $('size');
    const gate = $('year-gate');
    const scanSize = $('scan-size');

    function _popLabel(p) {
        return _t('admin.library.topPercent', 'Top {p}%').replace('{p}', String(p));
    }

    // The slider is INVERTED for intuitiveness (user request): right = "only
    // the biggest hits" (top 5%), left = "whole library" (top 100%).
    // stored percent = 105 - slider value, so both stay on the 5..100 grid.
    const _POP_FLIP = 101;

    function syncControls() {
        if (popRange) popRange.value = String(_POP_FLIP - adminState.libraryPopPercent);
        if (popValue) popValue.textContent = _popLabel(adminState.libraryPopPercent);
        if (size) size.value = String(adminState.librarySize);
        if (gate) gate.value = adminState.libraryYearGate;
        if (scanSize) scanSize.value = String(adminState.libraryScanSize);
        _renderGenreSelection(inst);
    }

    popRange?.addEventListener('input', function () {
        const v = parseInt(this.value, 10);
        adminState.libraryPopPercent = Number.isFinite(v) ? (_POP_FLIP - v) : 50;
        if (popValue) popValue.textContent = _popLabel(adminState.libraryPopPercent);
        _refreshMatchCount();
    });
    popRange?.addEventListener('change', function () {
        _syncSiblings(inst); if (onChanged) onChanged();
    });

    // Genre chips: delegated toggle handler (chips render from scan stats).
    rootEl.querySelector('[data-lib="genres"]')?.addEventListener('click', (e) => {
        const chip = e.target.closest('[data-genre]');
        if (!chip) return;
        const g = chip.getAttribute('data-genre');
        const cur = new Set(adminState.libraryGenres || []);
        if (cur.has(g)) cur.delete(g); else cur.add(g);
        adminState.libraryGenres = Array.from(cur);
        chip.classList.toggle('genre-chip--on', cur.has(g));
        _syncSiblings(inst); if (onChanged) onChanged();
    });
    size?.addEventListener('change', function () {
        adminState.librarySize = parseInt(this.value, 10) || 30;
        _syncSiblings(inst); if (onChanged) onChanged();
    });
    gate?.addEventListener('change', function () {
        adminState.libraryYearGate = this.value;
        _syncSiblings(inst); if (onChanged) onChanged();
    });
    scanSize?.addEventListener('change', function () {
        adminState.libraryScanSize = parseInt(this.value, 10);
        if (Number.isNaN(adminState.libraryScanSize)) adminState.libraryScanSize = 2500;
        _syncSiblings(inst); if (onChanged) onChanged();
    });

    // --- scan + status ---
    $('scan-btn')?.addEventListener('click', async () => {
        const btn = $('scan-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await _fetch('/beatify/api/library-pool/build', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // year_fallback follows the year-accuracy setting so a
                // "Balanced" game actually has the Deezer years it relies on.
                body: JSON.stringify({
                    use_musicbrainz: true,
                    year_fallback: adminState.libraryYearGate !== 'strict',
                    target_size: adminState.libraryScanSize,
                }),
            });
            if (!resp.ok && resp.status !== 409) {
                const data = await resp.json().catch(() => ({}));
                _setStatusText(inst, data.message || _t('admin.library.scanFailed', 'Scan could not start'));
            }
        } catch (e) {
            _setStatusText(inst, _t('admin.library.scanFailed', 'Scan could not start'));
        }
        _startPolling(inst);
    });

    // --- refresh (separate background pass: re-check years + popularity) ---
    $('refresh-btn')?.addEventListener('click', async () => {
        const btn = $('refresh-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await _fetch('/beatify/api/library-pool/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
            });
            if (!resp.ok && resp.status !== 409) {
                const data = await resp.json().catch(() => ({}));
                _setStatusText(inst, data.message || _t('admin.library.refreshFailed', 'Refresh could not start'));
                if (btn) btn.disabled = false;
            }
        } catch (e) {
            if (btn) btn.disabled = false;
        }
        _startPolling(inst);
    });
    if (mode === 'admin') {
        rootEl.querySelector('[data-lib="save-mix"]')?.addEventListener('click', async () => {
            const btn = rootEl.querySelector('[data-lib="save-mix"]');
            if (btn) btn.disabled = true;
            try {
                const resp = await _fetch('/beatify/api/library-playlists/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(getLibraryConfig()),
                });
                const data = await resp.json().catch(() => ({}));
                if (resp.ok && data.saved) {
                    _toast(inst, _t('admin.library.mixSaved', 'Saved as playlist: ') + data.name + ` (${data.songs})`);
                    // Mine tab lists from the server; nudge a refresh if the
                    // playlists section is mounted.
                    if (typeof window.loadPlaylists === 'function') { try { window.loadPlaylists(); } catch (e) { /* optional */ } }
                } else {
                    _toast(inst, data.message || _t('admin.library.mixSaveFailed', 'Could not save mix'));
                }
            } catch (e) {
                _toast(inst, _t('admin.library.mixSaveFailed', 'Could not save mix'));
            }
            if (btn) btn.disabled = false;
        });
        rootEl.querySelector('[data-lib="ai-create"]')?.addEventListener('click', () => {
            openLibraryAiModal();
        });
    }

    inst.refresh = () => refreshStatus(inst);
    inst.syncControls = syncControls;
    inst.destroy = () => {
        _stopPolling(inst);
        const i = _instances.indexOf(inst);
        if (i >= 0) _instances.splice(i, 1);
        rootEl.innerHTML = '';
    };

    _instances.push(inst);
    syncControls();
    _wireBackup(inst);
    _wireRecent(inst);
    _loadServerSettings(inst).finally(() => refreshStatus(inst));
    return inst;
}

/** Keep other mounted instances' controls in step after a change here. */
let _saveTimer = null;
let _previewTimer = null;

function _wireRecent(inst) {
    const root = inst.root;
    const btn = root.querySelector('[data-lib="recent-btn"]');
    const list = root.querySelector('[data-lib="recent-list"]');
    if (!btn || !list) return;

    const render = (songs) => {
        if (!songs.length) {
            list.innerHTML = `<p class="hint-text">${_t('admin.library.recentEmpty', 'No games played yet.')}</p>`;
            return;
        }
        list.innerHTML = songs.map((s_, i) => `
            <button type="button" class="library-recent-item${s_.flagged && !s_.corrected ? ' library-recent-item--flagged' : ''}" data-recent="${i}">
                <span class="library-recent-year${s_.corrected ? ' library-recent-year--fixed' : ''}">${s_.year || '—'}</span>
                <span class="library-recent-main">
                    <strong>${_escapeHtml(s_.title || '')}</strong>
                    <span>${_escapeHtml(s_.artist || '')}</span>
                </span>
                <span class="library-recent-action">${s_.corrected
                    ? _t('admin.library.recentFixed', 'fixed')
                    : (s_.flagged
                        ? '⚑ ' + _t('admin.library.recentFlagged', 'players flagged this')
                        : _t('admin.library.recentFix', 'fix'))}</span>
            </button>`).join('');
        list.querySelectorAll('[data-recent]').forEach((el) => {
            el.addEventListener('click', () => {
                const song = songs[Number(el.dataset.recent)];
                if (song && window.BeatifyCrateDiggerFix) {
                    window.BeatifyCrateDiggerFix.open(song);
                }
            });
        });
    };

    btn.addEventListener('click', async () => {
        const open = !list.classList.contains('hidden');
        if (open) { list.classList.add('hidden'); return; }
        list.classList.remove('hidden');
        list.innerHTML = `<p class="hint-text">${_t('admin.library.recentLoading', 'Loading…')}</p>`;
        try {
            const resp = await _fetch('/beatify/api/library-pool/recent');
            const data = await resp.json().catch(() => ({}));
            render((data && data.songs) || []);
        } catch (e) {
            list.innerHTML = `<p class="hint-text">${_t('admin.library.recentFailed', 'Could not load recent songs.')}</p>`;
        }
    });
}

function _wireBackup(inst) {
    const root = inst.root;
    const dlBtn = root.querySelector('[data-lib="backup-btn"]');
    const rsBtn = root.querySelector('[data-lib="restore-btn"]');
    const file = root.querySelector('[data-lib="restore-file"]');
    const status = root.querySelector('[data-lib="backup-status"]');
    const say = (msg, isError) => {
        if (!status) return;
        status.textContent = msg || '';
        status.classList.toggle('library-backup-status--error', !!isError);
    };

    if (dlBtn) dlBtn.addEventListener('click', async () => {
        dlBtn.disabled = true;
        say(_t('admin.library.backupWorking', 'Preparing backup\u2026'));
        try {
            const resp = await _fetch('/beatify/api/library-pool/backup');
            if (!resp.ok) {
                let detail = '';
                try { detail = (await resp.json()).error || ''; } catch (e) { /* ignore */ }
                say(detail || _t('admin.library.backupFailed', 'Backup failed.'), true);
                return;
            }
            // The endpoint is authenticated, so a plain <a href> would 401 —
            // fetch it with credentials, then hand the browser a temporary
            // object URL to save.
            const blob = await resp.blob();
            const disp = resp.headers.get('Content-Disposition') || '';
            const m = disp.match(/filename="?([^"]+)"?/);
            const name = (m && m[1]) || 'beatify-library-backup.json.gz';
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = name;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
            const songs = resp.headers.get('X-Beatify-Songs');
            say(_t('admin.library.backupDone', 'Backup downloaded ({n} songs).')
                .replace('{n}', Number(songs || 0).toLocaleString()));
        } catch (err) {
            say(_t('admin.library.backupFailed', 'Backup failed.'), true);
        } finally {
            dlBtn.disabled = false;
        }
    });

    if (rsBtn && file) {
        rsBtn.addEventListener('click', () => file.click());
        file.addEventListener('change', async () => {
            const f = file.files && file.files[0];
            file.value = '';
            if (!f) return;
            const merge = window.confirm(_t('admin.library.restoreMergeAsk',
                'Merge this backup into your current library?'));
            if (!merge && !window.confirm(_t('admin.library.restoreReplaceConfirm',
                'Replace your current scanned library with this backup? Your current pool is saved aside first.'))) {
                return;
            }
            rsBtn.disabled = true;
            say(_t('admin.library.restoreWorking', 'Restoring\u2026'));
            try {
                const resp = await _fetch(
                    '/beatify/api/library-pool/restore?mode=' + (merge ? 'merge' : 'replace'),
                    { method: 'POST', body: f }
                );
                let data = {};
                try { data = await resp.json(); } catch (e) { /* ignore */ }
                if (!resp.ok) {
                    say(data.error || _t('admin.library.restoreFailed', 'Restore failed.'), true);
                    return;
                }
                const st = data.stats || {};
                let msg = _t('admin.library.restoreDone',
                    'Restored: {total} songs ({added} new, {improved} improved).')
                    .replace('{total}', Number(st.total || 0).toLocaleString())
                    .replace('{added}', Number(st.added || 0).toLocaleString())
                    .replace('{improved}', Number(st.improved || 0).toLocaleString());
                if (data.foreign_source) {
                    msg += ' ' + _t('admin.library.restoreForeign',
                        'Note: this backup came from a different Music Assistant server, so some songs may need a rescan to play.');
                }
                say(msg);
                refreshStatus(inst);
            } catch (err) {
                say(_t('admin.library.restoreFailed', 'Restore failed.'), true);
            } finally {
                rsBtn.disabled = false;
            }
        });
    }
}

function _refreshMatchCount() {
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(async () => {
        try {
            const q = new URLSearchParams({
                pop: String(adminState.libraryPopPercent),
                genres: (adminState.libraryGenres || []).join(','),
                gate: adminState.libraryYearGate,
            });
            const resp = await _fetch('/beatify/api/library-pool/preview?' + q.toString());
            if (!resp.ok) return;
            const data = await resp.json();
            const n = Number(data.eligible ?? 0);
            const low = n < (adminState.librarySize || 30);
            _instances.forEach((i) => {
                const el = i.root.querySelector('[data-lib="match-count"]');
                if (!el) return;
                let txt = _t('admin.library.matchCount', '{n} songs match these settings')
                    .replace('{n}', n.toLocaleString());
                if (low) {
                    txt += ' — ' + _t('admin.library.matchLow',
                        'not enough for a full game; the rest will come from related genres and the most popular matches');
                }
                el.textContent = txt;
                el.classList.toggle('library-match-count--low', low);
            });
        } catch (e) { /* transient */ }
    }, 350);
}

function _saveServerSettings() {
    _refreshMatchCount();
    // Debounced push of the shared settings (slider drags fire many changes).
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(async () => {
        try {
            await _fetch('/beatify/api/library-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    popularity_percent: adminState.libraryPopPercent,
                    size: adminState.librarySize,
                    year_gate: adminState.libraryYearGate,
                    scan_size: adminState.libraryScanSize,
                    genres: adminState.libraryGenres || [],
                }),
            });
        } catch (e) { /* transient — next change retries */ }
    }, 400);
}

async function _loadServerSettings(inst) {
    // SERVER-SIDE settings are the source of truth (localStorage is
    // per-device: a game started from another PC silently used that PC's
    // defaults — the "slider/genres ignored" mystery). Server values override
    // local ones when present.
    try {
        const resp = await _fetch('/beatify/api/library-settings');
        if (!resp.ok) return;
        const s = await resp.json();
        if (Number.isFinite(s.popularity_percent)) adminState.libraryPopPercent = s.popularity_percent;
        if (Number.isFinite(s.size)) adminState.librarySize = s.size;
        if (typeof s.year_gate === 'string' && s.year_gate) adminState.libraryYearGate = s.year_gate;
        if (Number.isFinite(s.scan_size)) adminState.libraryScanSize = s.scan_size;
        if (Array.isArray(s.genres)) adminState.libraryGenres = s.genres;
        _instances.forEach((i) => { try { i.syncControls(); } catch (e) {} });
        _refreshMatchCount();
    } catch (e) { /* server settings optional; local values remain */ }
}

function _syncSiblings(changed) {
    _saveServerSettings();
    for (const inst of _instances) {
        if (inst !== changed && inst.syncControls) inst.syncControls();
    }
}

/* ------------------------------------------------------------------ *
 *  Status + polling (per instance; server state is shared)
 * ------------------------------------------------------------------ */

async function refreshStatus(inst) {
    try {
        const resp = await _fetch('/beatify/api/library-pool');
        if (!resp.ok) return;
        const data = await resp.json();
        _renderProviderVersion(inst, data.provider_version);
        _renderStatus(inst, data);
        _renderRefreshRow(inst, data.refresh);
        if (data.building || (data.refresh && data.refresh.running)) _startPolling(inst);
        else _stopPolling(inst);
    } catch (e) { /* transient — next poll or reopen retries */ }
}

function _startPolling(inst) {
    if (inst.pollTimer) return;
    inst.pollTimer = setInterval(() => refreshStatus(inst), POLL_INTERVAL_MS);
}

function _stopPolling(inst) {
    if (inst.pollTimer) { clearInterval(inst.pollTimer); inst.pollTimer = null; }
}

function _setStatusText(inst, text) {
    const el = inst.root.querySelector('[data-lib="status-text"]');
    if (el) el.textContent = text;
}

function _toast(inst, text) {
    const el = inst.root.querySelector('[data-lib="toast"]');
    if (!el) return;
    el.textContent = text;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 6000);
}

function _renderStatus(inst, data) {
    const root = inst.root;
    // Chips/stats stay visible DURING scans too — an active genre filter must
    // never be invisible (a stale hidden 'Dance' chip silently filtered a
    // user's games while a scan hid the chips).
    if (data.stats) {
        _renderStats(inst, data);
        _renderGenreChips(inst, (data.stats && data.stats.genres) || []);
    }
    const spinner = root.querySelector('[data-lib="spinner"]');
    const progressWrap = root.querySelector('[data-lib="progress"]');
    const bar = root.querySelector('[data-lib="bar"]');
    const label = root.querySelector('[data-lib="progress-label"]');
    const scanBtn = root.querySelector('[data-lib="scan-btn"]');
    const scanBtnLabel = root.querySelector('[data-lib="scan-btn-label"]');

    if (data.building) {
        spinner?.classList.remove('hidden');
        progressWrap?.classList.remove('hidden');
        if (scanBtn) scanBtn.disabled = true;
        const done = (data.progress && data.progress.done) || 0;
        const total = (data.progress && data.progress.total) || 0;
        const phase = (data.progress && data.progress.phase) || '';
        // Reading a huge library out of Music Assistant takes minutes before
        // enrichment starts — show that phase explicitly so it never looks dead.
        if (phase === 'enumerate' || (total === 0 && done > 0)) {
            spinner?.classList.remove('hidden');
            progressWrap?.classList.remove('hidden');
            if (scanBtn) scanBtn.disabled = true;
            if (bar) bar.style.width = '2%';
            if (label) {
                label.textContent = _t('admin.library.reading', 'Reading your library…')
                    + ` ${done.toLocaleString()} ` + _t('admin.library.songsFound', 'songs found');
            }
            _setStatusText(inst, _t('admin.library.statusScanning', 'Scanning your library in the background — you can continue.'));
            return;
        }
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        if (bar) bar.style.width = pct + '%';
        // Stable ETA: cumulative rate since THIS phase began (a sliding
        // window over polls mixed phases and jittered wildly — user report).
        const now = Date.now();
        const phaseKey = `${phase}|${total}`;
        if (inst._etaPhase !== phaseKey || done < (inst._etaDone || 0)) {
            inst._etaPhase = phaseKey;      // phase changed or counter reset
            inst._etaT0 = now;
            inst._etaD0 = done;
        }
        inst._etaDone = done;
        let eta = '';
        const elapsed = (now - inst._etaT0) / 1000;
        const progressed = done - inst._etaD0;
        // Only estimate once we have a meaningful baseline (>=20s and >=10 songs).
        if (total > done && elapsed >= 20 && progressed >= 10) {
            const rate = progressed / elapsed; // songs/s, cumulative this phase
            const secs = Math.round((total - done) / rate);
            const h = Math.floor(secs / 3600);
            const m = Math.round((secs % 3600) / 60);
            eta = ' · ~' + (h > 0 ? `${h}h ${m}m` : `${m} min`) + ' ' + _t('admin.library.left', 'left');
        }
        if (label) {
            label.textContent = total > 0
                ? _t('admin.library.scanning', 'Scanning…') + ` ${done}/${total} (${pct}%)${eta}`
                : _t('admin.library.scanningStart', 'Starting scan…');
        }
        _setStatusText(inst, _t('admin.library.statusScanning', 'Scanning your library in the background — you can continue.'));
        return;
    }

    spinner?.classList.add('hidden');
    progressWrap?.classList.add('hidden');
    if (scanBtn) scanBtn.disabled = false;

    if (data.error) {
        _setStatusText(inst, _t('admin.library.statusError', 'Last scan failed: ') + data.error);
        if (scanBtnLabel) scanBtnLabel.textContent = _t('admin.library.scanBtn', 'Scan library');
        return;
    }
    if (!data.built) {
        _setStatusText(inst, _t(
            'admin.library.statusEmpty',
            'Your library hasn\u2019t been scanned yet — start a scan to play from your own music.'
        ));
        if (scanBtnLabel) scanBtnLabel.textContent = _t('admin.library.scanBtn', 'Scan library');
        return;
    }
    // Pool exists (server-side, shared across devices): present it as the
    // default and relabel the action as "Rescan" — a device that didn't run
    // the original scan should never feel forced to redo it.
    const stats = data.stats || {};
    const usable = stats.usable || 0;
    const total = stats.total || 0;
    const template = _t(
        'admin.library.statusReady',
        'Library ready: {usable} of {total} songs game-ready (verified years).'
    );
    _setStatusText(inst, template.replace('{usable}', String(usable)).replace('{total}', String(total)));
    if (scanBtnLabel) scanBtnLabel.textContent = _t('admin.library.rescanBtn', 'Rescan');

}

/* ------------------------------------------------------------------ *
 *  Stats grid + genre chips (fed by the status payload)
 * ------------------------------------------------------------------ */

function _fmt(n) {
    return (typeof n === 'number') ? n.toLocaleString() : '—';
}

function _renderRefreshRow(inst, refresh) {
    const row = inst.root.querySelector('[data-lib="refresh-row"]');
    const status = inst.root.querySelector('[data-lib="refresh-status"]');
    const btn = inst.root.querySelector('[data-lib="refresh-btn"]');
    if (!row || !refresh) return;
    // Only relevant once a pool exists and there's a backlog OR it's running.
    const backlog = refresh.backlog || 0;
    if (refresh.running) {
        row.classList.remove('hidden');
        if (btn) btn.disabled = true;
        const p = refresh.progress || {};
        const done = p.done || 0;
        const total = p.total || 0;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        if (status) {
            status.textContent = total > 0
                ? _t('admin.library.refreshing', 'Improving songs…') + ` ${done.toLocaleString()}/${total.toLocaleString()} (${pct}%)`
                : _t('admin.library.refreshing', 'Improving songs…');
        }
        return;
    }
    if (backlog > 0) {
        row.classList.remove('hidden');
        if (btn) btn.disabled = false;
        if (status) {
            status.textContent = _t('admin.library.refreshBacklog', '{n} songs can be improved')
                .replace('{n}', backlog.toLocaleString());
        }
    } else {
        row.classList.add('hidden');
    }
}

function _renderStats(inst, data) {
    const el = inst.root.querySelector('[data-lib="stats"]');
    if (!el) return;
    const st = data.stats || {};
    const rows = [
        ['admin.library.stLibraryTotal', 'Songs in your library', data.library_total],
        ['admin.library.stPrepared', 'Prepared (scanned)', st.total],
        ['admin.library.stStrict', 'Verified years (strict)', st.verified_strict],
        ['admin.library.stBalanced', 'Usable at "Balanced"', st.verified_balanced],
        ['admin.library.stTags', 'Usable at "Relaxed"', st.verified_tags],
        ['admin.library.stScored', 'With popularity data', st.scored],
        ['admin.library.stGenres', 'With genre tags', st.genre_coverage],
    ];
    let html = '';
    for (const [key, fallback, val] of rows) {
        html += `<div class="library-stats__row"><span>${_t(key, fallback)}</span><strong>${_fmt(val)}</strong></div>`;
    }
    if (data.built_at) {
        const when = new Date(data.built_at * 1000).toLocaleString();
        html += `<div class="library-stats__row"><span>${_t('admin.library.stBuiltAt', 'Last scan finished')}</span><strong>${when}</strong></div>`;
    }
    const lg = data.last_generate;
    if (lg && lg.ts) {
        let desc;
        if (lg.skipped_playlists) {
            desc = _t('admin.library.lgPlaylists', '{n} saved playlist(s) — settings not applied')
                .replace('{n}', String(lg.skipped_playlists));
        } else {
            const parts = [];
            if (Number.isFinite(lg.pop_percent)) parts.push(_t('admin.library.topPercent', 'Top {p}%').replace('{p}', String(lg.pop_percent)));
            if (lg.genres && lg.genres.length) parts.push(lg.genres.join(', '));
            parts.push(`${lg.eligible ?? '—'} → ${lg.chosen ?? '—'}`);
            if (lg.genres_expanded && lg.genres_expanded.length) {
                parts.push(_t('admin.library.lgExpanded', '+ related: {g}')
                    .replace('{g}', lg.genres_expanded.join(', ')));
            }
            if (lg.widened) parts.push(_t('admin.library.lgWidened', 'expanded to best available'));
            desc = parts.join(' · ');
        }
        const t = new Date(lg.ts * 1000).toLocaleTimeString();
        html += `<div class="library-stats__row"><span>${_t('admin.library.stLastGame', 'Last game generated')}</span><strong>${_escapeHtml(desc)} (${t})</strong></div>`;
    }
    el.innerHTML = html;
    el.classList.remove('hidden');
}

let _lastGenreKey = '';

function _renderGenreChips(inst, genres) {
    const el = inst.root.querySelector('[data-lib="genres"]');
    if (!el) return;
    const key = JSON.stringify(genres.map((g) => g.name));
    // re-render only when the genre list itself changes (polling shouldn't
    // wipe an in-progress selection)
    if (key === _lastGenreKey && el.querySelector('[data-genre]')) {
        _renderGenreSelection(inst);
        return;
    }
    _lastGenreKey = key;
    if (!genres.length) {
        el.innerHTML = `<span class="hint-text">${_t('admin.library.genresNone', 'No genre tags found yet — rescan once with v0.6+ to collect them from Plex/Jellyfin.')}</span>`;
        return;
    }
    el.innerHTML = genres.map((g) =>
        `<button type="button" class="genre-chip" data-genre="${_escapeAttr(g.name)}">${_escapeHtml(g.name)} <em>${g.count}</em></button>`
    ).join('');
    _renderGenreSelection(inst);
}

function _renderGenreSelection(inst) {
    const sel = new Set(adminState.libraryGenres || []);
    inst.root.querySelectorAll('[data-genre]').forEach((chip) => {
        chip.classList.toggle('genre-chip--on', sel.has(chip.getAttribute('data-genre')));
    });
}

function _escapeHtml(x) {
    return String(x).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function _escapeAttr(x) { return _escapeHtml(x); }

/* ------------------------------------------------------------------ *
 *  Footer version tag: append the library-provider version to the
 *  "Beatify vX.Y.Z" footer so installs are visually verifiable.
 * ------------------------------------------------------------------ */

function _renderProviderVersion(inst, version) {
    // Shown inside the panel (user request) instead of patching the global
    // footer — keeps upstream chrome untouched and is visible exactly where
    // updates matter.
    if (!version) return;
    const el = inst.root.querySelector('[data-lib="provider-version"]');
    if (el) el.textContent = 'Crate Digger engine v' + version + ' \u00b7 by DMW';
}

/* ------------------------------------------------------------------ *
 *  Back-compat exports for game-settings.js (admin settings section)
 * ------------------------------------------------------------------ */

let _adminInstance = null;

/** Mount (once) into the admin settings panel root. */
export function setupLibrarySettings(onChanged) {
    const root = document.getElementById('library-settings');
    if (!root) return;
    if (!_adminInstance) {
        _adminInstance = mountLibraryPanel(root, { mode: 'admin', onChanged });
    }
    updateLibraryPanelVisibility();
}

export function syncLibraryControls() {
    if (_adminInstance) _adminInstance.syncControls();
}

/** Show the admin panel only while the ma_library provider is selected. */
export function updateLibraryPanelVisibility() {
    const panel = document.getElementById('library-settings');
    if (!panel) return;
    const active = adminState.selectedProvider === 'ma_library';
    panel.classList.toggle('hidden', !active);
    if (active && _adminInstance) _adminInstance.refresh();
}
