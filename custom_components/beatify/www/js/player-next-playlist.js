/**
 * Beatify Player — "what's next" picker (#2648)
 *
 * After ten rounds of 80s somebody shouts "now the 90s!". Until this module the
 * end screen answered that with two buttons: Rematch, which replayed the same
 * playlist, and New Game, which sent the host to the admin page and told every
 * guest to scan the QR code again — at the exact moment the room was at its
 * best.
 *
 * The design gate picked variant B: the end screen IS the start screen. There
 * is no menu after the podium, there is the choice itself — a grid of playlist
 * tiles with the one just played marked at the top, a way into the whole
 * catalogue, and one primary button that says what it will do. The way back
 * into the admin page still exists, as a quiet line under the grid; it is no
 * longer a second main exit.
 *
 * Everything here is host-side. The guest half of variant B — "<host> is
 * picking the next playlist" instead of the rescan hint — lives in
 * `player-end.js` next to the rest of the end view.
 *
 * The rule that decides WHICH playlists get a tile is deliberately not here.
 * It lives in `game/playlist.py` (`build_next_playlist_tiles`) and arrives
 * over `/beatify/api/next-playlists`, so it can be reasoned about and tested
 * as one mechanical rule rather than as rendering.
 */

var utils = window.BeatifyUtils || {};

/** How many search results the list shows before it stops (a phone, at a party). */
export var SEARCH_RESULT_LIMIT = 30;

/**
 * The picker's whole state. `selected` holds playlist paths, because that is
 * what the server speaks — a tile is only ever a view of some paths.
 */
var picker = {
    tiles: [],
    all: [],
    current: [],
    selected: [],
    searchOpen: false,
    loaded: false,
};

/** i18n lookup with a real fallback: `t()` returns the KEY on a miss (#1402-B8). */
function tx(key, paramsOrFallback, fallback) {
    var s = typeof utils.t === 'function' ? utils.t(key, paramsOrFallback) : '';
    var miss = !s || String(s) === key;
    if (!miss) return String(s);
    if (typeof paramsOrFallback === 'string') return paramsOrFallback;
    return fallback || key;
}

/** Two path lists naming the same playlists, order included. */
export function samePaths(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) return false;
    }
    return true;
}

/**
 * Fold a name down to something a one-handed search can match: lower case,
 * accents dropped. "Röyksopp" has to be findable by typing "roy".
 */
export function foldForSearch(text) {
    var s = String(text == null ? '' : text).toLowerCase();
    if (typeof s.normalize === 'function') {
        s = s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }
    return s;
}

/**
 * The catalogue entries matching `query`, best first.
 *
 * "Best first" is two buckets, not a score: a playlist whose name STARTS with
 * what was typed comes before one that merely contains it, and inside each
 * bucket the catalogue's own order is kept. An empty query returns the head of
 * the catalogue rather than nothing, so opening search shows a list to scroll
 * instead of a blank panel.
 */
export function filterPlaylists(all, query, limit) {
    var cap = typeof limit === 'number' ? limit : SEARCH_RESULT_LIMIT;
    var list = Array.isArray(all) ? all : [];
    var needle = foldForSearch(query).trim();
    if (!needle) return list.slice(0, cap);

    var starts = [];
    var contains = [];
    list.forEach(function(entry) {
        var hay = foldForSearch(entry && entry.name);
        var at = hay.indexOf(needle);
        if (at === 0) starts.push(entry);
        else if (at > 0) contains.push(entry);
    });
    return starts.concat(contains).slice(0, cap);
}

/**
 * The line under a tile's name: what the playlist just played says about
 * itself, and how big every other one is.
 */
export function tileSubtitle(tile) {
    if (!tile) return '';
    if (tile.extra > 0) {
        return tx('leaderboard.nextMorePlaylists', { count: tile.extra });
    }
    if (tile.reason === 'current') {
        return tx('leaderboard.nextJustPlayed', 'just played');
    }
    return tx('leaderboard.nextSongCount', { count: tile.song_count || 0 });
}

/** The primary button's label — it names the playlist it will start. */
export function goLabel(tile) {
    if (!tile) return tx('admin.rematch', 'Rematch');
    return tx('leaderboard.nextGo', { name: tile.name });
}

/** The tile currently selected, or null while the payload is still loading. */
export function selectedTile() {
    for (var i = 0; i < picker.tiles.length; i++) {
        if (samePaths(picker.tiles[i].paths, picker.selected)) return picker.tiles[i];
    }
    if (picker.selected.length) {
        // A search result is a tile too, it just is not in the grid.
        var entry = null;
        for (var j = 0; j < picker.all.length; j++) {
            if (picker.all[j].path === picker.selected[0]) { entry = picker.all[j]; break; }
        }
        if (entry) {
            return {
                paths: [entry.path],
                name: entry.name,
                extra: 0,
                song_count: entry.song_count,
                reason: 'search',
            };
        }
    }
    return null;
}

/**
 * What the rematch request should carry.
 *
 * Returns null when the selection is the playlist that was just played: that
 * is the historic rematch, and sending it down the swap path would reload the
 * same songs for nothing. The server treats a missing `playlists` key as "same
 * music", so null is not an absence of an answer — it IS the answer.
 */
export function selectedPlaylists() {
    if (!picker.selected.length) return null;
    if (samePaths(picker.selected, picker.current)) return null;
    return picker.selected.slice();
}

/** Test seam: install a payload without going near the network. */
export function setPickerState(payload) {
    picker.tiles = (payload && payload.suggested) || [];
    picker.all = (payload && payload.all) || [];
    picker.current = (payload && payload.current) || [];
    picker.selected = picker.tiles.length ? picker.tiles[0].paths.slice() : [];
    picker.searchOpen = false;
    picker.loaded = true;
    return picker;
}

/** Read-only view of the picker, for tests and for the end view's wiring. */
export function pickerState() {
    return picker;
}

/**
 * Draw the tile grid.
 *
 * Built with createElement rather than an innerHTML string: a playlist name is
 * data — it comes off a JSON file a user may have written — and data must not
 * be parsed as markup.
 */
export function renderTiles(container, tiles, selected, onSelect) {
    if (!container) return;
    container.innerHTML = '';
    (tiles || []).forEach(function(tile) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'next-tile' + (samePaths(tile.paths, selected) ? ' is-selected' : '');
        if (tile.reason === 'current') btn.className += ' next-tile--current';
        btn.setAttribute('aria-pressed', samePaths(tile.paths, selected) ? 'true' : 'false');

        var name = document.createElement('span');
        name.className = 'next-tile-name';
        name.textContent = tile.name;
        btn.appendChild(name);

        var sub = document.createElement('span');
        sub.className = 'next-tile-sub';
        sub.textContent = tileSubtitle(tile);
        btn.appendChild(sub);

        btn.onclick = function() { if (onSelect) onSelect(tile); };
        container.appendChild(btn);
    });

    // The last tile is always the way into the rest of the catalogue. It is a
    // tile and not a link because it is one of the six things to tap, and the
    // grid is the only place the eye goes after the podium.
    var searchTile = document.createElement('button');
    searchTile.type = 'button';
    searchTile.className = 'next-tile next-tile--search';
    searchTile.id = 'next-playlist-search-tile';
    var searchName = document.createElement('span');
    searchName.className = 'next-tile-name';
    searchName.textContent = tx('leaderboard.nextSearchAll', { count: picker.all.length });
    searchTile.appendChild(searchName);
    var searchSub = document.createElement('span');
    searchSub.className = 'next-tile-sub';
    searchSub.textContent = tx('leaderboard.nextSearchSub', 'browse');
    searchTile.appendChild(searchSub);
    searchTile.onclick = function() { if (onSelect) onSelect(null); };
    container.appendChild(searchTile);
}

/** Draw the search results list. */
export function renderResults(container, entries, selected, onSelect) {
    if (!container) return;
    container.innerHTML = '';
    if (!entries || !entries.length) {
        var empty = document.createElement('p');
        empty.className = 'next-search-empty';
        empty.textContent = tx('leaderboard.nextNoResults', 'No playlist matches that');
        container.appendChild(empty);
        return;
    }
    entries.forEach(function(entry) {
        var row = document.createElement('button');
        row.type = 'button';
        row.className = 'next-result' + (samePaths([entry.path], selected) ? ' is-selected' : '');
        var name = document.createElement('span');
        name.className = 'next-result-name';
        name.textContent = entry.name;
        row.appendChild(name);
        var count = document.createElement('span');
        count.className = 'next-result-count';
        count.textContent = tx('leaderboard.nextSongCount', { count: entry.song_count || 0 });
        row.appendChild(count);
        row.onclick = function() { if (onSelect) onSelect(entry); };
        container.appendChild(row);
    });
}

/** Repaint grid, search panel and the primary button from the current state. */
export function refreshPicker() {
    var grid = document.getElementById('next-playlist-grid');
    var panel = document.getElementById('next-playlist-search');
    var input = document.getElementById('next-playlist-search-input');
    var results = document.getElementById('next-playlist-results');
    var goBtn = document.getElementById('player-rematch-btn');

    renderTiles(grid, picker.tiles, picker.selected, function(tile) {
        if (!tile) {
            picker.searchOpen = true;
            refreshPicker();
            var reopened = document.getElementById('next-playlist-search-input');
            if (reopened && typeof reopened.focus === 'function') reopened.focus();
            return;
        }
        picker.selected = tile.paths.slice();
        picker.searchOpen = false;
        refreshPicker();
    });

    if (panel) panel.classList.toggle('hidden', !picker.searchOpen);
    if (picker.searchOpen && results) {
        renderResults(
            results,
            filterPlaylists(picker.all, input ? input.value : ''),
            picker.selected,
            function(entry) {
                picker.selected = [entry.path];
                refreshPicker();
            }
        );
    }

    if (goBtn) {
        goBtn.textContent = goLabel(selectedTile());
        goBtn.disabled = !picker.selected.length;
    }
}

/**
 * Load the payload and draw the picker. Failure is not fatal: the button falls
 * back to a plain "Rematch" over the historic same-playlist path, because a
 * host who cannot reach this endpoint should still be able to play again.
 */
export async function loadNextPlaylists(fetchJson) {
    var grid = document.getElementById('next-playlist-grid');
    var goBtn = document.getElementById('player-rematch-btn');
    // `updateEndView` runs again on every state broadcast that reaches the end
    // screen — a guest closing their tab is enough. Re-fetching there would
    // reset `selected` back to the first tile, so a host who had already
    // tapped "90s Hits" and was reaching for the button would silently be back
    // on "80s Hits". Load once per end screen; `invalidateNextPlaylists`
    // clears the flag when a new game begins.
    if (picker.loaded) {
        refreshPicker();
        return;
    }
    try {
        var payload = await (fetchJson || defaultFetch)();
        setPickerState(payload);
        refreshPicker();
    } catch (err) {
        console.warn('[Beatify] Next-playlist picker unavailable:', err);
        picker.tiles = [];
        picker.all = [];
        picker.selected = [];
        picker.loaded = false;
        if (grid) grid.innerHTML = '';
        if (goBtn) {
            goBtn.textContent = tx('admin.rematch', 'Rematch');
            goBtn.disabled = false;
        }
    }
}

function defaultFetch() {
    return fetch('/beatify/api/next-playlists', { credentials: 'same-origin' })
        .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        });
}

/** Wire the search box. Called once, when the end view first renders. */
export function bindSearchInput() {
    var input = document.getElementById('next-playlist-search-input');
    if (!input || input._beatifyBound) return;
    input._beatifyBound = true;
    input.oninput = function() { refreshPicker(); };
}

/**
 * Forget the loaded payload so the next end screen fetches a fresh one.
 *
 * Called when a game starts, because by the time the room sees a podium again
 * the just-played playlist is a different one and the history has moved on.
 */
export function invalidateNextPlaylists() {
    picker.loaded = false;
    picker.searchOpen = false;
}

/** Put the primary button back after a rematch attempt (spinner → label). */
export function resetGoButton() {
    var goBtn = document.getElementById('player-rematch-btn');
    if (!goBtn) return;
    goBtn.disabled = false;
    goBtn.textContent = goLabel(selectedTile());
}
