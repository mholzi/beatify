/**
 * Beatify Playlist Hub — v3.3 wizard step 3 replacement.
 *
 * Renders the segmented Bundled / Community / Mine hub inside a host element.
 * Owns its own state (selection, active tab, search query, genre filter,
 * detail-sheet target, request-modal open flag) and re-renders the relevant
 * subtree on change. Host wizard gets a `selectionChange` callback + can
 * query `getSelection()` to persist the same way the old wiz-row picker did.
 *
 * Data sources (all local, no global stats):
 *   GET /beatify/api/status           → playlists + source tag
 *   GET /beatify/api/usage?kind=top   → Your most-played shelf
 *   GET /beatify/api/usage?kind=recent→ Recently played shelf
 *   window.PlaylistRequests           → Mine tab (existing module)
 *
 * Styling lives in css/styles.css under the .plh-* namespace.
 *
 * ES module. Loaded via <script type="module"> in admin.html.
 */

const API_STATUS = '/beatify/api/status';
const API_USAGE = '/beatify/api/usage';

const GENRE_TAXONOMY = [
    { id: 'all', key: 'playlistHub.chips.all', fallback: 'All genres', matches: () => true },
    { id: 'pop', key: 'playlistHub.chips.pop', fallback: 'Pop', matches: (t) => _hasTag(t, 'pop') },
    { id: 'rock', key: 'playlistHub.chips.rock', fallback: 'Rock', matches: (t) => _hasTag(t, 'rock') },
    { id: 'hiphop', key: 'playlistHub.chips.hiphop', fallback: 'Hip-Hop', matches: (t) => _hasTag(t, 'hip-hop') || _hasTag(t, 'rap') },
    { id: 'metal', key: 'playlistHub.chips.metal', fallback: 'Metal', matches: (t) => _hasTag(t, 'metal') || _hasTag(t, 'thrash') },
    { id: 'jazz', key: 'playlistHub.chips.jazz', fallback: 'Jazz', matches: (t) => _hasTag(t, 'jazz') },
    { id: 'electronic', key: 'playlistHub.chips.electronic', fallback: 'Electronic', matches: (t) => _hasTag(t, 'electronic') || _hasTag(t, 'eurodance') || _hasTag(t, 'disco') || _hasTag(t, 'techno') || _hasTag(t, 'house') },
    { id: 'latin', key: 'playlistHub.chips.latin', fallback: 'Latin', matches: (t) => _hasTag(t, 'latin') || _hasTag(t, 'salsa') || _hasTag(t, 'merengue') || _hasTag(t, 'reggaeton') },
    { id: 'schlager', key: 'playlistHub.chips.schlager', fallback: 'Schlager', matches: (t) => _hasTag(t, 'schlager') || _hasTag(t, 'carnival') },
    { id: 'soul', key: 'playlistHub.chips.soul', fallback: 'Soul / R&B', matches: (t) => _hasTag(t, 'soul') || _hasTag(t, 'r&b') || _hasTag(t, 'motown') || _hasTag(t, 'funk') },
];

const LANGUAGE_FLAGS = { en: '🇬🇧', de: '🇩🇪', es: '🇪🇸', fr: '🇫🇷', nl: '🇳🇱', it: '🇮🇹', pt: '🇵🇹', ja: '🇯🇵', ko: '🇰🇷' };

function _hasTag(tags, needle) {
    if (!Array.isArray(tags)) return false;
    const n = needle.toLowerCase();
    return tags.some((t) => typeof t === 'string' && t.toLowerCase().includes(n));
}

function _t(key, fallback) {
    try {
        if (window.BeatifyI18n && typeof window.BeatifyI18n.t === 'function') {
            const val = window.BeatifyI18n.t(key, fallback);
            if (val) return val;
        }
    } catch (e) { /* i18n not ready */ }
    return fallback;
}

function _escape(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _fetchJson(url) {
    return fetch(url, { credentials: 'same-origin' })
        .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        });
}

function _relTime(unixSec) {
    if (!unixSec) return '';
    const nowSec = Math.floor(Date.now() / 1000);
    const delta = Math.max(0, nowSec - unixSec);
    const day = 86400;
    if (delta < 60) return _t('playlistHub.time.justNow', 'just now');
    if (delta < 3600) return _t('playlistHub.time.minutesAgo', '{n}m ago').replace('{n}', Math.floor(delta / 60));
    if (delta < day) return _t('playlistHub.time.hoursAgo', '{n}h ago').replace('{n}', Math.floor(delta / 3600));
    if (delta < day * 7) return _t('playlistHub.time.daysAgo', '{n}d ago').replace('{n}', Math.floor(delta / day));
    if (delta < day * 30) return _t('playlistHub.time.weeksAgo', '{n}w ago').replace('{n}', Math.floor(delta / (day * 7)));
    const d = new Date(unixSec * 1000);
    return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
}

function _formatAddedDate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' }).toUpperCase();
    } catch (e) { return ''; }
}

function _coverTint(playlist) {
    const tags = (playlist.tags || []).map((t) => String(t).toLowerCase());
    if (tags.some((t) => t.includes('metal') || t.includes('thrash'))) return 'plh-tint-metal';
    if (tags.some((t) => t.includes('jazz'))) return 'plh-tint-jazz';
    if (tags.some((t) => t.includes('latin') || t.includes('salsa'))) return 'plh-tint-latin';
    if (tags.some((t) => t.includes('schlager') || t.includes('carnival'))) return 'plh-tint-schlager';
    if (tags.some((t) => t.includes('electronic') || t.includes('eurodance') || t.includes('house') || t.includes('techno'))) return 'plh-tint-eu';
    if (tags.some((t) => t.includes('hip-hop') || t.includes('rap'))) return 'plh-tint-hiphop';
    if (tags.some((t) => t.includes('soul') || t.includes('motown') || t.includes('funk'))) return 'plh-tint-soul';
    if (tags.some((t) => t.includes('rock') || t.includes('britpop'))) return 'plh-tint-rock';
    if (tags.some((t) => t.includes('pop'))) return 'plh-tint-pop';
    if (playlist.source === 'community') return 'plh-tint-purple';
    return 'plh-tint-pop';
}

function _coverGlyph(playlist) {
    const name = String(playlist.name || '');
    const decade = (playlist.tags || []).find((t) => /^\d{2,4}s?$/.test(String(t)));
    if (decade) return String(decade).replace(/^19/, '').replace(/^20/, '').replace('s', 's');
    const firstWord = name.split(/\s+/)[0] || '';
    if (firstWord.length <= 4) return firstWord;
    return firstWord.slice(0, 3) + '…';
}

function _shortName(name) {
    if (!name) return '';
    return name.length <= 22 ? name : name.slice(0, 20) + '…';
}

// ------------------------------------------------------------------
// Pure helpers — exported for vitest
// ------------------------------------------------------------------

export function matchesSearch(playlist, query) {
    if (!query) return true;
    const q = query.toLowerCase().trim();
    if (!q) return true;
    const hay = [
        playlist.name || '',
        (playlist.tags || []).join(' '),
        playlist.description || '',
        playlist.language || '',
        playlist.author || '',
    ].join(' ').toLowerCase();
    return hay.includes(q);
}

export function filterByGenre(playlists, genreId) {
    if (!genreId || genreId === 'all') return playlists;
    const g = GENRE_TAXONOMY.find((x) => x.id === genreId);
    if (!g) return playlists;
    return playlists.filter((p) => g.matches(p.tags || []));
}

export function groupByGenreShelves(playlists, limit = 4) {
    const buckets = new Map();
    for (const pl of playlists) {
        let assigned = false;
        for (const g of GENRE_TAXONOMY) {
            if (g.id === 'all') continue;
            if (g.matches(pl.tags || [])) {
                const b = buckets.get(g.id) || { genre: g, items: [] };
                if (b.items.length < 20) b.items.push(pl);
                buckets.set(g.id, b);
                assigned = true;
                break;
            }
        }
        if (!assigned) {
            const b = buckets.get('other') || { genre: { id: 'other', fallback: 'Other', key: 'playlistHub.chips.other' }, items: [] };
            b.items.push(pl);
            buckets.set('other', b);
        }
    }
    return Array.from(buckets.values())
        .filter((b) => b.items.length >= 2)
        .slice(0, limit);
}

export function rankLocalShelf(playlists, usageItems) {
    // Join usage by playlist name → playlist object. Preserves usage order.
    const byName = new Map();
    for (const p of playlists) byName.set(p.name, p);
    const out = [];
    for (const u of usageItems) {
        const pl = byName.get(u.name);
        if (pl) out.push({ playlist: pl, usage: u });
    }
    return out;
}

// ------------------------------------------------------------------
// Module state + lifecycle
// ------------------------------------------------------------------

const state = {
    mounted: false,
    root: null,
    options: null,
    playlists: [],
    topPlaylists: [],
    recentPlaylists: [],
    requests: [],
    currentTab: 'bundled',
    genreFilter: 'all',
    searchQuery: '',
    selectedPaths: new Set(),
    detailFor: null,
    requestModalOpen: false,
    loading: true,
    error: null,
};

export function mount(rootEl, options = {}) {
    if (!rootEl) throw new Error('PlaylistHub.mount: root element required');
    state.root = rootEl;
    state.options = Object.assign({
        onSelectionChange: null,          // (paths: string[]) => void
        onRequestClick: null,             // () => void — opens existing request modal
        initialSelected: [],              // string[] (playlist paths)
        initialPlaylists: null,           // if provided, skip the /api/status fetch
        locale: null,
    }, options);
    state.mounted = true;
    state.selectedPaths = new Set(state.options.initialSelected || []);
    if (Array.isArray(state.options.initialPlaylists)) {
        state.playlists = state.options.initialPlaylists;
    }
    rootEl.classList.add('plh-root');
    rootEl.setAttribute('role', 'region');
    rootEl.setAttribute('aria-label', _t('playlistHub.title', 'Playlist Hub'));

    _attachDelegates(rootEl);
    _renderAll();
    _loadData();
}

export function unmount() {
    if (!state.mounted) return;
    _detachDelegates(state.root);
    if (state.root) state.root.innerHTML = '';
    state.mounted = false;
    state.root = null;
}

export function getSelection() {
    return Array.from(state.selectedPaths);
}

export function setSelection(paths) {
    state.selectedPaths = new Set(paths || []);
    _renderTabBody();
    _renderCtaBar();
    _emitSelectionChange();
}

export function refresh() {
    _loadData();
}

export function getPlaylistByPath(path) {
    if (!path) return null;
    return (state.playlists || []).find((p) => (p.path || p.filename || p.name) === path) || null;
}

// ------------------------------------------------------------------
// Data loading
// ------------------------------------------------------------------

async function _loadData() {
    state.loading = state.playlists.length === 0;
    state.error = null;
    _renderTabBody();
    try {
        // Skip the /api/status fetch when the host (wizard) already has the
        // playlist list in memory and passed it via initialPlaylists.
        const skipStatus = Array.isArray(state.options && state.options.initialPlaylists);
        const [statusResp, topResp, recentResp] = await Promise.all([
            skipStatus
                ? Promise.resolve(null)
                : _fetchJson(API_STATUS).catch((e) => { console.warn('[PlaylistHub] status fetch failed:', e); return null; }),
            _fetchJson(`${API_USAGE}?kind=top&limit=8`).catch(() => ({ items: [] })),
            _fetchJson(`${API_USAGE}?kind=recent&limit=12`).catch(() => ({ items: [] })),
        ]);
        if (!skipStatus) {
            state.playlists = (statusResp && Array.isArray(statusResp.playlists)) ? statusResp.playlists : [];
        }
        state.topPlaylists = (topResp && Array.isArray(topResp.items)) ? topResp.items : [];
        state.recentPlaylists = (recentResp && Array.isArray(recentResp.items)) ? recentResp.items : [];
        // Mine tab: pull cached requests synchronously, then refresh async
        if (window.PlaylistRequests) {
            const cached = window.PlaylistRequests.loadRequests();
            state.requests = Array.isArray(cached.requests) ? cached.requests : [];
            window.PlaylistRequests.getRequestsForDisplayAsync()
                .then((rs) => { state.requests = rs || []; if (state.currentTab === 'mine') _renderTabBody(); })
                .catch((e) => console.warn('[PlaylistHub] requests load failed:', e));
        }
    } catch (e) {
        state.error = e && e.message ? e.message : 'Failed to load';
    } finally {
        state.loading = false;
        _renderHeader();
        _renderTabBody();
        _renderCtaBar();
    }
}

// ------------------------------------------------------------------
// Event delegation
// ------------------------------------------------------------------

function _attachDelegates(rootEl) {
    rootEl.addEventListener('click', _onClick);
    rootEl.addEventListener('input', _onInput);
    rootEl.addEventListener('keydown', _onKeyDown);
}

function _detachDelegates(rootEl) {
    if (!rootEl) return;
    rootEl.removeEventListener('click', _onClick);
    rootEl.removeEventListener('input', _onInput);
    rootEl.removeEventListener('keydown', _onKeyDown);
}

function _onClick(e) {
    const tab = e.target.closest('[data-plh-tab]');
    if (tab) {
        state.currentTab = tab.dataset.plhTab;
        state.detailFor = null;
        _renderHeader();
        _renderTabBody();
        _renderCtaBar();
        return;
    }
    const chip = e.target.closest('[data-plh-chip]');
    if (chip) {
        state.genreFilter = chip.dataset.plhChip;
        _renderChips();
        _renderTabBody();
        return;
    }
    const clearSearch = e.target.closest('[data-plh-action="clear-search"]');
    if (clearSearch) {
        state.searchQuery = '';
        const input = state.root.querySelector('[data-plh-search]');
        if (input) input.value = '';
        _renderTabBody();
        return;
    }
    const removeFilter = e.target.closest('[data-plh-action="remove-genre"]');
    if (removeFilter) {
        state.genreFilter = 'all';
        _renderChips();
        _renderTabBody();
        return;
    }
    const card = e.target.closest('[data-plh-card]');
    if (card && !e.target.closest('[data-plh-check]')) {
        const path = card.dataset.plhCard;
        const pl = state.playlists.find((p) => p.path === path);
        if (pl) { state.detailFor = pl; _renderDetailSheet(); }
        return;
    }
    const check = e.target.closest('[data-plh-check]');
    if (check) {
        e.stopPropagation();
        const path = check.dataset.plhCheck;
        _toggleSelected(path);
        _renderTabBody();
        _renderCtaBar();
        return;
    }
    const detailClose = e.target.closest('[data-plh-action="close-detail"]');
    if (detailClose) { state.detailFor = null; _renderDetailSheet(); return; }
    const detailSelect = e.target.closest('[data-plh-action="detail-select"]');
    if (detailSelect) {
        const path = detailSelect.dataset.plhPath;
        _toggleSelected(path);
        state.detailFor = null;
        _renderDetailSheet();
        _renderTabBody();
        _renderCtaBar();
        return;
    }
    const requestNew = e.target.closest('[data-plh-action="request-new"]');
    if (requestNew) {
        if (state.options && typeof state.options.onRequestClick === 'function') {
            state.options.onRequestClick();
        }
        return;
    }
    const refresh = e.target.closest('[data-plh-action="refresh"]');
    if (refresh) { _loadData(); return; }
    const retry = e.target.closest('[data-plh-action="retry"]');
    if (retry) { _loadData(); return; }
    const switchTab = e.target.closest('[data-plh-action="switch-tab"]');
    if (switchTab) {
        state.currentTab = switchTab.dataset.plhTab;
        _renderHeader();
        _renderTabBody();
        _renderCtaBar();
        return;
    }
    const start = e.target.closest('[data-plh-action="start"]');
    if (start) {
        _emitSelectionChange();
        return;
    }
}

function _onInput(e) {
    if (e.target.matches && e.target.matches('[data-plh-search]')) {
        state.searchQuery = e.target.value || '';
        _renderTabBody();
    }
}

function _onKeyDown(e) {
    if (e.key === 'Escape') {
        if (state.detailFor) { state.detailFor = null; _renderDetailSheet(); }
    }
}

function _toggleSelected(path) {
    if (state.selectedPaths.has(path)) state.selectedPaths.delete(path);
    else state.selectedPaths.add(path);
    _emitSelectionChange();
}

function _emitSelectionChange() {
    if (state.options && typeof state.options.onSelectionChange === 'function') {
        try { state.options.onSelectionChange(Array.from(state.selectedPaths)); }
        catch (e) { console.error('[PlaylistHub] onSelectionChange threw:', e); }
    }
}

// ------------------------------------------------------------------
// Rendering
// ------------------------------------------------------------------

function _renderAll() {
    if (!state.root) return;
    state.root.innerHTML = `
        <div class="plh-header" data-plh-header></div>
        <div class="plh-body" data-plh-body></div>
        <div class="plh-cta-bar" data-plh-cta></div>
        <div class="plh-sheet-host" data-plh-sheet></div>
    `;
    _renderHeader();
    _renderChips();
    _renderTabBody();
    _renderCtaBar();
}

function _renderHeader() {
    const host = state.root && state.root.querySelector('[data-plh-header]');
    if (!host) return;
    const counts = _counts();
    host.innerHTML = `
        <div class="plh-titlebar">
            <div class="plh-wordmark">${_escape(_t('playlistHub.title', 'Playlist Hub'))}</div>
        </div>
        <div class="plh-search" role="search">
            <svg class="plh-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input type="search" data-plh-search value="${_escape(state.searchQuery)}" placeholder="${_escape(_t('playlistHub.search.placeholder', 'Search playlists, artists, years…'))}" aria-label="${_escape(_t('playlistHub.search.placeholder', 'Search'))}" />
            ${state.searchQuery ? `<button class="plh-search-clear" data-plh-action="clear-search" aria-label="Clear search">×</button>` : ''}
        </div>
        <div class="plh-segmented" role="tablist">
            <button class="plh-seg ${state.currentTab === 'bundled' ? 'active' : ''}" role="tab" aria-selected="${state.currentTab === 'bundled'}" data-plh-tab="bundled">
                <span class="plh-seg-num">${counts.bundled}</span>
                <span class="plh-seg-label">${_escape(_t('playlistHub.tabs.bundled', 'Bundled'))}</span>
            </button>
            <button class="plh-seg plh-seg-community ${state.currentTab === 'community' ? 'active' : ''}" role="tab" aria-selected="${state.currentTab === 'community'}" data-plh-tab="community">
                <span class="plh-seg-num">${counts.community}</span>
                <span class="plh-seg-label">${_escape(_t('playlistHub.tabs.community', 'Community'))}</span>
            </button>
            <button class="plh-seg plh-seg-mine ${state.currentTab === 'mine' ? 'active' : ''}" role="tab" aria-selected="${state.currentTab === 'mine'}" data-plh-tab="mine">
                <span class="plh-seg-num">${counts.mine}</span>
                <span class="plh-seg-label">${_escape(_t('playlistHub.tabs.mine', 'Mine'))}</span>
            </button>
        </div>
        <div class="plh-chips" data-plh-chips></div>
    `;
    _renderChips();
}

function _renderChips() {
    const host = state.root && state.root.querySelector('[data-plh-chips]');
    if (!host) return;
    if (state.currentTab === 'mine') { host.innerHTML = ''; host.style.display = 'none'; return; }
    host.style.display = '';
    host.innerHTML = GENRE_TAXONOMY.map((g) => `
        <button class="plh-chip ${state.genreFilter === g.id ? 'active' : ''}" data-plh-chip="${_escape(g.id)}">${_escape(_t(g.key, g.fallback))}</button>
    `).join('');
}

function _counts() {
    const playlists = state.playlists || [];
    const bundled = playlists.filter((p) => p.source !== 'community').length;
    const community = playlists.filter((p) => p.source === 'community').length;
    const mine = (state.requests || []).length;
    return { bundled, community, mine };
}

function _renderTabBody() {
    const host = state.root && state.root.querySelector('[data-plh-body]');
    if (!host) return;
    if (state.loading) {
        host.innerHTML = `<div class="plh-loading">${_escape(_t('playlistHub.loading', 'Loading…'))}</div>`;
        return;
    }
    if (state.error) {
        host.innerHTML = `
            <div class="plh-empty">
                <div class="plh-empty-icon">⚠</div>
                <h2 class="plh-empty-title">${_escape(_t('playlistHub.error.title', 'Could not load playlists'))}</h2>
                <p class="plh-empty-body">${_escape(state.error)}</p>
                <button class="plh-btn plh-btn-primary" data-plh-action="retry">${_escape(_t('playlistHub.retry', 'Retry'))}</button>
            </div>`;
        return;
    }
    switch (state.currentTab) {
        case 'community': _renderCommunity(host); break;
        case 'mine': _renderMine(host); break;
        default: _renderBundled(host);
    }
}

// ---------- Bundled view ----------

function _renderBundled(host) {
    const all = (state.playlists || []).filter((p) => p.source !== 'community');
    const filtered = filterByGenre(all.filter((p) => matchesSearch(p, state.searchQuery)), state.genreFilter);

    if (state.searchQuery) {
        if (filtered.length === 0) {
            host.innerHTML = _renderNoSearchResults('bundled');
            return;
        }
        host.innerHTML = `
            <div class="plh-shelf">
                <div class="plh-shelf-head">
                    <div class="plh-shelf-title">${_escape(_t('playlistHub.shelves.searchResults', 'Results'))}</div>
                    <div class="plh-shelf-meta">${filtered.length}</div>
                </div>
                <div class="plh-cards">${filtered.map((p) => _cardHtml(p)).join('')}</div>
            </div>`;
        return;
    }

    const html = [];
    const topRanked = rankLocalShelf(state.playlists || [], state.topPlaylists || []);
    if (topRanked.length > 0) {
        html.push(_shelfHtml({
            title: _t('playlistHub.shelves.yourMostPlayed', 'Your most-played'),
            local: true,
            see: `${topRanked.length}`,
            cards: topRanked.map(({ playlist, usage }) =>
                _cardHtml(playlist, { extra: `<div class="plh-card-local"><b>${usage.play_count}×</b> ${_escape(_t('playlistHub.played', 'played'))} · ${_escape(_relTime(usage.last_played))}</div>` })
            ),
        }));
    }
    const recentRanked = rankLocalShelf(state.playlists || [], state.recentPlaylists || []);
    if (recentRanked.length > 0) {
        html.push(_shelfHtml({
            title: _t('playlistHub.shelves.recentlyPlayed', 'Recently played'),
            local: true,
            see: `${recentRanked.length}`,
            cards: recentRanked.map(({ playlist, usage }) => {
                const mins = Math.round((usage.duration_seconds || 0) / 60);
                const sub = `<b>${_escape(_relTime(usage.started_at))}</b> · ${usage.player_count || 0} ${_escape(_t('playlistHub.players', 'players'))} · ${mins} ${_escape(_t('playlistHub.min', 'min'))}`;
                return _cardHtml(playlist, { extra: `<div class="plh-card-local plh-card-local-when">${sub}</div>` });
            }),
        }));
    }

    // Editor's Picks — featured (sorted by song_count desc, top 5)
    const featured = [...filtered].sort((a, b) => (b.song_count || 0) - (a.song_count || 0)).slice(0, 5);
    if (featured.length > 0) {
        html.push(_shelfHtml({
            title: `✨ ${_t('playlistHub.shelves.editorsPicks', "Editor's Picks")}`,
            featured: true,
            see: _t('playlistHub.seeAll', 'See all'),
            cards: featured.map((p) => _cardHtml(p, { featured: true })),
        }));
    }

    // Genre shelves (up to 4)
    const genreShelves = groupByGenreShelves(filtered, 4);
    for (const g of genreShelves) {
        html.push(_shelfHtml({
            title: _t(g.genre.key, g.genre.fallback),
            see: `${g.items.length}`,
            cards: g.items.slice(0, 8).map((p) => _cardHtml(p)),
        }));
    }

    // Community peek (bottom of bundled)
    const community = (state.playlists || []).filter((p) => p.source === 'community');
    if (community.length > 0) {
        const peek = community.slice(0, 6);
        html.push(_shelfHtml({
            title: _t('playlistHub.shelves.fromCommunity', 'From the Community'),
            see: `${_t('playlistHub.seeAll', 'See all')} ${community.length} →`,
            seeTab: 'community',
            cards: peek.map((p) => _cardHtml(p, { community: true })),
        }));
    }

    if (html.length === 0) {
        host.innerHTML = _renderNoFilterResults();
    } else {
        host.innerHTML = html.join('');
    }
}

// ---------- Community view ----------

function _renderCommunity(host) {
    const all = (state.playlists || []).filter((p) => p.source === 'community');
    const filtered = filterByGenre(all.filter((p) => matchesSearch(p, state.searchQuery)), state.genreFilter);

    if (all.length === 0) {
        host.innerHTML = `
            <div class="plh-empty">
                <div class="plh-empty-icon">📡</div>
                <h2 class="plh-empty-title">${_escape(_t('playlistHub.empty.communityEmpty.title', 'No community playlists installed'))}</h2>
                <p class="plh-empty-body">${_escape(_t('playlistHub.empty.communityEmpty.body', 'Community playlists ship with Beatify. Update the integration to get the latest batch.'))}</p>
            </div>`;
        return;
    }
    if (state.searchQuery && filtered.length === 0) {
        host.innerHTML = _renderNoSearchResults('community');
        return;
    }
    if (!state.searchQuery && state.genreFilter !== 'all' && filtered.length === 0) {
        host.innerHTML = _renderNoFilterResults();
        return;
    }

    const html = [];
    // Request banner
    html.push(`
        <div class="plh-banner plh-banner-community" data-plh-action="request-new" role="button" tabindex="0">
            <div class="plh-banner-icon">✉</div>
            <div class="plh-banner-body">
                <div class="plh-banner-title">${_escape(_t('playlistHub.community.banner.title', 'Nothing here for you? Request a playlist.'))}</div>
                <div class="plh-banner-sub">${_escape(_t('playlistHub.community.banner.sub', 'Describe the genre, era, vibe. A maintainer ships it in 24–48h.'))}</div>
            </div>
            <div class="plh-banner-arrow">›</div>
        </div>
    `);

    if (state.searchQuery || state.genreFilter !== 'all') {
        html.push(_shelfHtml({
            title: _t('playlistHub.shelves.searchResults', 'Results'),
            see: `${filtered.length}`,
            cards: filtered.map((p) => _cardHtml(p, { community: true, showAuthor: true })),
        }));
    } else {
        // Editor's Picks: all community playlists sorted by song_count desc (top 5)
        const picks = [...all].sort((a, b) => (b.song_count || 0) - (a.song_count || 0)).slice(0, 5);
        html.push(_shelfHtml({
            title: `✨ ${_t('playlistHub.shelves.editorsPicks', "Editor's Picks")}`,
            featured: true,
            see: _t('playlistHub.seeAll', 'See all'),
            cards: picks.map((p) => _cardHtml(p, { community: true, featured: true, showAuthor: true })),
        }));

        // Popular in Deutsch (language == 'de')
        const byLang = new Map();
        for (const p of all) {
            const lang = (p.language || '').toLowerCase();
            if (!lang) continue;
            if (!byLang.has(lang)) byLang.set(lang, []);
            byLang.get(lang).push(p);
        }
        for (const [lang, items] of byLang) {
            if (items.length < 2) continue;
            const flag = LANGUAGE_FLAGS[lang] || '';
            const langName = _languageName(lang);
            html.push(_shelfHtml({
                title: `${flag} ${_t('playlistHub.shelves.popularIn', 'Popular in')} ${langName}`,
                see: `${items.length}`,
                cards: items.slice(0, 8).map((p) => _cardHtml(p, { community: true, showAuthor: true })),
            }));
        }

        // Recently added (sorted by added_date desc — items with added_date only)
        const dated = all.filter((p) => !!p.added_date);
        if (dated.length >= 2) {
            dated.sort((a, b) => (b.added_date || '').localeCompare(a.added_date || ''));
            html.push(_shelfHtml({
                title: _t('playlistHub.shelves.recentlyAdded', 'Recently added'),
                see: `${dated.length}`,
                cards: dated.slice(0, 8).map((p) => _cardHtml(p, {
                    community: true,
                    showAuthor: true,
                    badgeOverride: _formatAddedDate(p.added_date),
                })),
            }));
        }

        // Regional & Specialty (by genre tag "regional" or anything without a top-level match)
        const regional = all.filter((p) => {
            const tags = (p.tags || []).map((t) => String(t).toLowerCase());
            return tags.some((t) => t.includes('regional') || t.includes('folk') || t.includes('carnival'));
        });
        if (regional.length >= 2) {
            html.push(_shelfHtml({
                title: _t('playlistHub.shelves.regional', 'Regional & Specialty'),
                see: `${regional.length}`,
                cards: regional.slice(0, 8).map((p) => _cardHtml(p, { community: true, showAuthor: true })),
            }));
        }
    }

    host.innerHTML = html.join('');
}

function _languageName(code) {
    const names = { en: 'English', de: 'Deutsch', es: 'Español', fr: 'Français', nl: 'Nederlands', it: 'Italiano', pt: 'Português', ja: '日本語', ko: '한국어' };
    return names[code] || code.toUpperCase();
}

// ---------- Mine view (wraps window.PlaylistRequests) ----------

function _renderMine(host) {
    const reqs = state.requests || [];
    if (reqs.length === 0) {
        host.innerHTML = `
            <div class="plh-mine-empty">
                <div class="plh-empty-emoji">📮</div>
                <h2 class="plh-mine-title">${_escape(_t('playlistHub.mine.empty.title', 'No requests yet'))}</h2>
                <p class="plh-mine-body">${_escape(_t('playlistHub.mine.empty.body', 'Missing a genre, era or regional scene? Request it. A maintainer adds it in 24–48h.'))}</p>
                <div class="plh-request-cta">
                    <div class="plh-request-head">
                        <div class="plh-request-icon">✉</div>
                        <div class="plh-request-titles">
                            <div class="plh-request-t1">${_escape(_t('playlistHub.mine.request.title', 'Request a playlist'))}</div>
                            <div class="plh-request-t2">${_escape(_t('playlistHub.mine.request.sub', 'Paste a Spotify playlist URL and submit.'))}</div>
                        </div>
                    </div>
                    <button class="plh-btn plh-btn-cyan" data-plh-action="request-new">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                        ${_escape(_t('playlistHub.mine.request.cta', 'Start a request'))}
                    </button>
                </div>
                <div class="plh-meanwhile" data-plh-action="switch-tab" data-plh-tab="community">
                    <div class="plh-meanwhile-icon">✨</div>
                    <div class="plh-meanwhile-body">
                        <div class="plh-meanwhile-t1">${_escape(_t('playlistHub.mine.meanwhile.title', 'Meanwhile, browse community playlists'))}</div>
                        <div class="plh-meanwhile-t2">${_escape(_t('playlistHub.mine.meanwhile.sub', 'User-contributed picks, installable in one tap.'))}</div>
                    </div>
                    <div class="plh-meanwhile-arrow">›</div>
                </div>
            </div>
        `;
        return;
    }

    const done = reqs.filter((r) => r.status === 'installed' || r.status === 'ready').length;
    const inFlight = reqs.filter((r) => r.status === 'pending').length;

    const rows = reqs.map((r) => _requestRowHtml(r)).join('');
    host.innerHTML = `
        <div class="plh-mine-head">
            <div class="plh-mine-count"><b>${reqs.length}</b> ${_escape(_t('playlistHub.mine.requests', 'REQUESTS'))} · ${done} ${_escape(_t('playlistHub.mine.done', 'DONE'))} · ${inFlight} ${_escape(_t('playlistHub.mine.inFlight', 'IN FLIGHT'))}</div>
        </div>
        <div class="plh-new-request" data-plh-action="request-new" role="button" tabindex="0">
            <div class="plh-new-plus">+</div>
            <div>
                <div class="plh-new-t1">${_escape(_t('playlistHub.mine.newRequest.title', 'Request another playlist'))}</div>
                <div class="plh-new-t2">${_escape(_t('playlistHub.mine.newRequest.sub', 'Paste a Spotify URL, we take it from there.'))}</div>
            </div>
        </div>
        <div class="plh-req-list">${rows}</div>
    `;
}

function _requestRowHtml(r) {
    const status = (r.status || 'pending').toLowerCase();
    const statusClass = status === 'installed' || status === 'ready' ? 'done'
        : status === 'declined' ? 'declined'
        : status === 'in_progress' || status === 'building' ? 'building'
        : 'pending';
    const statusLabel = statusClass === 'done' ? _t('playlistHub.status.done', 'Done')
        : statusClass === 'declined' ? _t('playlistHub.status.declined', 'Declined')
        : statusClass === 'building' ? _t('playlistHub.status.building', 'Building')
        : _t('playlistHub.status.pending', 'Pending');
    const progress = statusClass === 'done' ? 4 : statusClass === 'building' ? 3 : statusClass === 'pending' ? 1 : 0;
    const progressHtml = [0, 1, 2, 3].map((i) => `<div class="plh-seg-pill ${i < progress ? 'filled-' + statusClass : ''}"></div>`).join('');
    const issueLink = r.issue_number
        ? `<a class="plh-req-link" href="https://github.com/mholzi/beatify/issues/${encodeURIComponent(r.issue_number)}" target="_blank" rel="noopener">issue #${_escape(r.issue_number)} ↗</a>`
        : '';
    const name = r.playlist_name || r.name || _t('playlistHub.mine.untitled', 'Untitled request');
    const when = r.requested_at ? _relTime(Math.floor(new Date(r.requested_at).getTime() / 1000)) : '';
    return `
        <div class="plh-req-card plh-req-${statusClass}">
            <div class="plh-req-row1">
                <div class="plh-req-body">
                    <div class="plh-req-name">${_escape(name)}</div>
                    <div class="plh-req-desc">${_escape(r.spotify_url || '')}</div>
                    <div class="plh-req-meta"><b>${_escape(_t('playlistHub.mine.submitted', 'Submitted'))}</b> ${_escape(when)} · ${issueLink}</div>
                </div>
                <div class="plh-status-badge ${statusClass}"><span class="plh-sb-dot"></span>${_escape(statusLabel)}</div>
            </div>
            <div class="plh-progress">${progressHtml}</div>
            <div class="plh-steps-row">
                <span${progress >= 1 ? ' class="active"' : ''}>${_escape(_t('playlistHub.mine.step.submitted', 'Submitted'))}</span>
                <span${progress >= 2 ? ' class="active"' : ''}>${_escape(_t('playlistHub.mine.step.reviewed', 'Reviewed'))}</span>
                <span${progress >= 3 ? ' class="active"' : ''}>${_escape(_t('playlistHub.mine.step.building', 'Building'))}</span>
                <span${progress >= 4 ? ' class="active"' : ''}>${_escape(_t('playlistHub.mine.step.inBundled', 'In Bundled'))}</span>
            </div>
        </div>
    `;
}

// ---------- Shelf + card rendering helpers ----------

function _shelfHtml({ title, see, seeTab, cards, featured, local }) {
    const cls = ['plh-shelf'];
    if (featured) cls.push('plh-featured');
    if (local) cls.push('plh-local');
    const seeHtml = see
        ? (seeTab
            ? `<button class="plh-shelf-see" data-plh-action="switch-tab" data-plh-tab="${_escape(seeTab)}">${_escape(see)}</button>`
            : `<span class="plh-shelf-see">${_escape(see)}</span>`)
        : '';
    const localBadge = local ? `<span class="plh-local-badge">${_escape(_t('playlistHub.local', 'Local'))}</span>` : '';
    const localDot = local ? `<span class="plh-local-dot" aria-hidden="true"></span>` : '';
    return `
        <div class="${cls.join(' ')}">
            <div class="plh-shelf-head">
                <div class="plh-shelf-title">${localDot}${_escape(title)}${localBadge}</div>
                ${seeHtml}
            </div>
            <div class="plh-cards">${cards.join('')}</div>
        </div>
    `;
}

function _cardHtml(playlist, opts = {}) {
    const path = playlist.path || playlist.filename || playlist.name;
    const selected = state.selectedPaths.has(path);
    const tintClass = _coverTint(playlist);
    const glyph = _coverGlyph(playlist);
    const nameShort = _shortName(playlist.name);
    const count = playlist.song_count || 0;
    const cls = ['plh-card'];
    if (opts.featured) cls.push('plh-card-featured');
    if (opts.community) cls.push('plh-card-community');
    if (selected) cls.push('plh-card-selected');
    const badge = opts.badgeOverride
        ? `<span class="plh-cover-badge">${_escape(opts.badgeOverride)}</span>`
        : (opts.community
            ? `<span class="plh-cover-badge plh-cover-badge-purple">${_escape(_t('playlistHub.community.tag', 'COMMUNITY'))}</span>`
            : '');
    const subMeta = opts.extra
        ? opts.extra
        : (opts.showAuthor && playlist.author
            ? `<div class="plh-card-sub">${_escape(_t('playlistHub.by', 'by'))} <b>${_escape(playlist.author)}</b> · ${count} ${_escape(_t('playlistHub.songs', 'songs'))}</div>`
            : `<div class="plh-card-sub"><b>${count}</b> ${_escape(_t('playlistHub.songs', 'songs'))}${playlist.language ? ` · ${_escape(playlist.language.toUpperCase())}` : ''}</div>`);
    return `
        <div class="${cls.join(' ')}" data-plh-card="${_escape(path)}" role="button" tabindex="0" aria-label="${_escape(playlist.name)}">
            <button class="plh-check" data-plh-check="${_escape(path)}" aria-label="${selected ? 'Deselect' : 'Select'}" aria-pressed="${selected}">
                ${selected ? '✓' : ''}
            </button>
            <div class="plh-cover ${tintClass}">
                ${badge}
                <div class="plh-cover-inner">
                    <div class="plh-cover-glyph">${_escape(glyph)}</div>
                    <div class="plh-cover-sub">${_escape(nameShort)}</div>
                </div>
            </div>
            <div class="plh-card-meta">
                <div class="plh-card-name">${_escape(nameShort)}</div>
                ${subMeta}
            </div>
        </div>
    `;
}

// ---------- Empty states ----------

function _renderNoSearchResults(tabHint) {
    const otherTab = tabHint === 'bundled' ? 'community' : 'bundled';
    const otherCount = otherTab === 'bundled' ? _counts().bundled : _counts().community;
    const otherLabel = otherTab === 'bundled' ? _t('playlistHub.tabs.bundled', 'Bundled') : _t('playlistHub.tabs.community', 'Community');
    return `
        <div class="plh-empty">
            <div class="plh-empty-icon plh-empty-icon-search">🔎</div>
            <h2 class="plh-empty-title">${_escape(_t('playlistHub.empty.noSearch.title', 'No matches for'))}<br><span class="plh-cyan">"${_escape(state.searchQuery)}"</span></h2>
            <p class="plh-empty-body">${_escape(_t('playlistHub.empty.noSearch.body', 'Nothing here matches. Try a different query, or check the other tab.'))}</p>
            <div class="plh-action-stack">
                <button class="plh-btn plh-btn-primary" data-plh-action="switch-tab" data-plh-tab="${otherTab}">${_escape(_t('playlistHub.empty.noSearch.searchOther', 'Search'))} ${_escape(otherLabel)} (${otherCount})</button>
                <button class="plh-btn plh-btn-cyan" data-plh-action="request-new">${_escape(_t('playlistHub.empty.noSearch.request', 'Request this playlist'))}</button>
                <button class="plh-btn plh-btn-ghost" data-plh-action="clear-search">${_escape(_t('playlistHub.empty.noSearch.clear', 'Clear search'))}</button>
            </div>
        </div>
    `;
}

function _renderNoFilterResults() {
    const genreLabel = GENRE_TAXONOMY.find((g) => g.id === state.genreFilter);
    const genreName = genreLabel ? _t(genreLabel.key, genreLabel.fallback) : state.genreFilter;
    return `
        <div class="plh-empty">
            <div class="plh-empty-icon">🎯</div>
            <h2 class="plh-empty-title">${_escape(_t('playlistHub.empty.noFilter.title', 'No playlists match'))}<br><span class="plh-cyan">${_escape(genreName)}</span></h2>
            <p class="plh-empty-body">${_escape(_t('playlistHub.empty.noFilter.body', 'Try removing the filter or requesting this genre.'))}</p>
            <div class="plh-action-stack">
                <button class="plh-btn plh-btn-primary" data-plh-action="remove-genre">${_escape(_t('playlistHub.empty.noFilter.clear', 'Clear genre filter'))}</button>
                <button class="plh-btn plh-btn-cyan" data-plh-action="request-new">${_escape(_t('playlistHub.empty.noFilter.request', 'Request this genre'))}</button>
            </div>
        </div>
    `;
}

// ---------- Detail sheet ----------

function _renderDetailSheet() {
    const host = state.root && state.root.querySelector('[data-plh-sheet]');
    if (!host) return;
    if (!state.detailFor) {
        host.innerHTML = '';
        host.classList.remove('open');
        return;
    }
    const p = state.detailFor;
    const path = p.path || p.filename || p.name;
    const selected = state.selectedPaths.has(path);
    const community = p.source === 'community';
    const tintClass = _coverTint(p);
    const glyph = _coverGlyph(p);
    const tags = (p.tags || []).slice(0, 8);
    const addedDisplay = _formatAddedDate(p.added_date);
    const ctaLabel = selected
        ? _t('playlistHub.detail.remove', 'Remove from round')
        : _t('playlistHub.detail.add', 'Add to round');
    host.innerHTML = `
        <div class="plh-scrim" data-plh-action="close-detail"></div>
        <div class="plh-sheet ${community ? 'plh-sheet-community' : ''}" role="dialog" aria-modal="true" aria-labelledby="plh-sheet-title">
            <button class="plh-sheet-close" data-plh-action="close-detail" aria-label="${_escape(_t('playlistHub.close', 'Close'))}">✕</button>
            <div class="plh-sheet-head">
                <div class="plh-sheet-cover ${tintClass}">
                    ${community ? `<span class="plh-cover-badge plh-cover-badge-purple">${_escape(_t('playlistHub.community.tag', 'COMMUNITY'))}</span>` : ''}
                    <div class="plh-sheet-cover-glyph">${_escape(glyph)}</div>
                    <div class="plh-sheet-cover-sub">${_escape(_shortName(p.name))}</div>
                </div>
                <div class="plh-sheet-info">
                    <h2 class="plh-sheet-title" id="plh-sheet-title">${_escape(p.name)}</h2>
                    <div class="plh-sheet-author">
                        ${p.author ? `${_escape(_t('playlistHub.by', 'by'))} <b>${_escape(p.author)}</b>` : `<b>${_escape(_t('playlistHub.bundledBy', 'Beatify Team'))}</b>`}
                        ${p.version ? ` · v${_escape(p.version)}` : ''}
                        · ${community ? _escape(_t('playlistHub.sources.community', 'Community')) : _escape(_t('playlistHub.sources.bundled', 'Bundled'))}
                    </div>
                </div>
            </div>
            <div class="plh-sheet-stats">
                <div class="plh-stat"><div class="plh-stat-val">${p.song_count || 0}</div><div class="plh-stat-lbl">${_escape(_t('playlistHub.songs', 'Songs'))}</div></div>
                ${addedDisplay ? `<div class="plh-stat"><div class="plh-stat-val plh-stat-val-cyan">${_escape(addedDisplay)}</div><div class="plh-stat-lbl">${_escape(_t('playlistHub.detail.added', 'Added'))}</div></div>` : ''}
                ${p.language ? `<div class="plh-stat"><div class="plh-stat-val plh-stat-val-pink">${_escape(p.language.toUpperCase())}</div><div class="plh-stat-lbl">${_escape(_t('playlistHub.detail.language', 'Language'))}</div></div>` : ''}
            </div>
            <div class="plh-sheet-scroll">
                ${p.description ? `<div class="plh-sheet-desc">${_escape(p.description)}</div>` : ''}
                ${tags.length > 0 ? `
                    <div class="plh-sheet-sec-title">${_escape(_t('playlistHub.detail.tags', 'Tags'))}</div>
                    <div class="plh-sheet-tags">${tags.map((t) => `<span class="plh-sheet-tag">${_escape(t)}</span>`).join('')}</div>
                ` : ''}
                ${(p.spotify_count || p.apple_music_count || p.youtube_music_count || p.tidal_count || p.deezer_count) ? `
                    <div class="plh-sheet-sec-title">${_escape(_t('playlistHub.detail.streaming', 'Streaming coverage'))}</div>
                    <div class="plh-sheet-providers">
                        ${p.spotify_count ? `<div class="plh-sheet-provider">Spotify <b>${p.spotify_count}</b>/${p.song_count || 0}</div>` : ''}
                        ${p.apple_music_count ? `<div class="plh-sheet-provider">Apple <b>${p.apple_music_count}</b>/${p.song_count || 0}</div>` : ''}
                        ${p.youtube_music_count ? `<div class="plh-sheet-provider">YouTube <b>${p.youtube_music_count}</b>/${p.song_count || 0}</div>` : ''}
                        ${p.tidal_count ? `<div class="plh-sheet-provider">Tidal <b>${p.tidal_count}</b>/${p.song_count || 0}</div>` : ''}
                        ${p.deezer_count ? `<div class="plh-sheet-provider">Deezer <b>${p.deezer_count}</b>/${p.song_count || 0}</div>` : ''}
                    </div>
                ` : ''}
            </div>
            <div class="plh-sheet-foot">
                <button class="plh-btn ${selected ? 'plh-btn-neon' : 'plh-btn-primary'}" data-plh-action="detail-select" data-plh-path="${_escape(path)}">${_escape(ctaLabel)}</button>
            </div>
        </div>
    `;
    host.classList.add('open');
}

// ---------- CTA bar ----------

function _renderCtaBar() {
    const host = state.root && state.root.querySelector('[data-plh-cta]');
    if (!host) return;
    const count = state.selectedPaths.size;
    if (count === 0) {
        host.innerHTML = `
            <button class="plh-cta-fab" data-plh-action="request-new" aria-label="${_escape(_t('playlistHub.mine.newRequest.title', 'Request a playlist'))}">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            </button>
            <div class="plh-cta-count">0 ✓</div>
            <button class="plh-cta-start plh-cta-start-disabled" disabled>${_escape(_t('playlistHub.cta.pickSome', 'Pick some →'))}</button>
        `;
        return;
    }
    host.innerHTML = `
        <button class="plh-cta-fab" data-plh-action="request-new" aria-label="${_escape(_t('playlistHub.mine.newRequest.title', 'Request a playlist'))}">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
        </button>
        <div class="plh-cta-count">${count} ✓</div>
        <button class="plh-cta-start" data-plh-action="start">
            ${_escape(_t('playlistHub.cta.start', 'Continue'))}
            <span class="plh-cta-start-count">${count}</span>
            →
        </button>
    `;
}
