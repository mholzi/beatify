/**
 * Beatify Admin — Crate Digger song correction dialog.
 *
 * A library game is played against the host's OWN metadata, so "wrong year?"
 * has a better answer here than "report it to whoever made the playlist": fix
 * it in place. The same dialog serves both entry points —
 *
 *   • during a round, from the reveal screen (fix it while you can hear it)
 *   • afterwards, from the Recently played list in the Crate Digger panel
 *
 * — because the useful moment differs per host, and the work is identical.
 *
 * Two kinds of wrongness are handled. A mis-DATED song just needs the right
 * year. A mis-IDENTIFIED one (the resolver matched a different recording, or
 * the file's tags were wrong to begin with) needs its title/artist corrected
 * first, and the candidate list re-searched under the corrected name — which
 * is why the search box is editable rather than a fixed label.
 */

let _dlg = null;
let _state = { uri: null, songTitle: '', songArtist: '', current: null, candidates: [], busy: false };

function _t(key, fallback) {
    // #2582: `BeatifyI18n.t()` gibt bei einem fehlenden Schluessel den
    // **Schluessel selbst** zurueck (i18n.js) — und der ist truthy, also kam
    // `fallback` nie zum Zug. Genau dieser Fehler wurde als #1402-B8 in
    // `playlist-hub.js` behoben; diese neuere Kopie hat ihn wieder eingebaut.
    // Heute latent, weil alle Schluessel in en.json stehen — aber vor dem
    // i18n-Load oder beim naechsten vergessenen Schluessel stuende
    // „admin.library.fixSave" im Dialog.
    var s = window.BeatifyI18n ? window.BeatifyI18n.t(key) : '';
    return !s || s === key ? fallback : s;
}

function _esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
}

function _fetch(url, opts) {
    return window.BeatifyAuth
        ? window.BeatifyAuth.fetch(url, opts)
        : fetch(url, opts);
}

function _ensureDialog() {
    if (_dlg) return _dlg;
    _dlg = document.createElement('div');
    _dlg.className = 'cd-fix-overlay hidden';
    _dlg.setAttribute('role', 'dialog');
    _dlg.setAttribute('aria-modal', 'true');
    _dlg.innerHTML = `
        <div class="cd-fix-panel">
            <button type="button" class="cd-fix-close" data-cd="close" aria-label="${_esc(_t('common.close', 'Close'))}">×</button>
            <h3 class="cd-fix-title">${_esc(_t('admin.library.fixTitle', 'Fix this song'))}</h3>
            <p class="cd-fix-current" data-cd="current"></p>

            <div class="cd-fix-search">
                <label class="cd-fix-field">
                    <span>${_esc(_t('admin.library.fixArtist', 'Artist'))}</span>
                    <input type="text" data-cd="artist" autocomplete="off">
                </label>
                <label class="cd-fix-field">
                    <span>${_esc(_t('admin.library.fixSongTitle', 'Title'))}</span>
                    <input type="text" data-cd="title" autocomplete="off">
                </label>
                <button type="button" class="lib-btn" data-cd="search">${_esc(_t('admin.library.fixSearch', 'Search again'))}</button>
            </div>
            <p class="hint-text">${_esc(_t('admin.library.fixSearchHint', 'Wrong song entirely? Correct the artist or title and search again.'))}</p>

            <div class="cd-fix-results" data-cd="results" aria-live="polite"></div>

            <div class="cd-fix-manual">
                <label class="cd-fix-field">
                    <span>${_esc(_t('admin.library.fixManualYear', 'Or set the year yourself'))}</span>
                    <input type="number" data-cd="year" min="1860" max="2100" class="input-compact">
                </label>
                <button type="button" class="lib-btn lib-btn--primary" data-cd="save">${_esc(_t('admin.library.fixSave', 'Save correction'))}</button>
            </div>
            <p class="hint-text" data-cd="status" aria-live="polite"></p>
        </div>`;
    document.body.appendChild(_dlg);

    _dlg.addEventListener('click', (ev) => {
        if (ev.target === _dlg || ev.target.closest('[data-cd="close"]')) _close();
    });
    _dlg.querySelector('[data-cd="search"]').addEventListener('click', () => _search());
    _dlg.querySelector('[data-cd="save"]').addEventListener('click', () => _save({}));
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape' && _dlg && !_dlg.classList.contains('hidden')) _close();
    });
    return _dlg;
}

function _status(msg, isError) {
    const el = _dlg && _dlg.querySelector('[data-cd="status"]');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('cd-fix-status--error', !!isError);
}

function _close() {
    if (_dlg) _dlg.classList.add('hidden');
    _state = { uri: null, songTitle: '', songArtist: '', current: null, candidates: [], busy: false };
}

function _renderCurrent() {
    const el = _dlg.querySelector('[data-cd="current"]');
    const c = _state.current || {};
    const source = c.year_source
        ? _t('admin.library.fixSourceLabel', 'source: {s}').replace('{s}', c.year_source)
        : '';
    let html = `<strong>${_esc(c.artist)} — ${_esc(c.title)}</strong>`;
    if (c.album) html += `<br><span class="cd-fix-album">${_esc(c.album)}</span>`;
    html += `<br>${_esc(_t('admin.library.fixCurrentYear', 'Currently'))}: <strong>${_esc(c.year || '—')}</strong>`;
    if (source) html += ` <span class="cd-fix-source">(${_esc(source)})</span>`;
    if (c.corrected) {
        html += `<br><span class="cd-fix-corrected">${_esc(_t('admin.library.fixAlready', 'You already corrected this song.'))}</span>`;
    }
    if (c.original_title || c.original_artist) {
        const orig = `${c.original_artist || c.artist} — ${c.original_title || c.title}`;
        html += `<br><span class="cd-fix-source">${_esc(_t('admin.library.fixWasTagged', 'Tagged as'))}: ${_esc(orig)}</span>`;
    }
    el.innerHTML = html;
}

function _renderCandidates() {
    const box = _dlg.querySelector('[data-cd="results"]');
    if (!_state.candidates.length) {
        box.innerHTML = `<p class="hint-text">${_esc(_t('admin.library.fixNoMatches', 'No matches found. Try correcting the artist or title, or set the year yourself.'))}</p>`;
        return;
    }
    box.innerHTML = _state.candidates.map((c, i) => `
        <button type="button" class="cd-fix-cand" data-cd-pick="${i}">
            <span class="cd-fix-cand-year">${_esc(c.year || '—')}</span>
            <span class="cd-fix-cand-main">
                <strong>${_esc(c.title)}</strong>
                <span>${_esc(c.artist || '')}</span>
                ${c.album ? `<span class="cd-fix-cand-album">${_esc(c.album)}</span>` : ''}
            </span>
        </button>`).join('');
    box.querySelectorAll('[data-cd-pick]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const cand = _state.candidates[Number(btn.dataset.cdPick)];
            if (!cand) return;
            // Picking a candidate corrects the identity too when it differs —
            // that is the whole point of showing what else this could be.
            _save({ year: cand.year, title: cand.title, artist: cand.artist });
        });
    });
}

async function _search() {
    if (_state.busy) return;
    _state.busy = true;
    _status(_t('admin.library.fixSearching', 'Searching MusicBrainz…'));
    try {
        const resp = await _fetch('/beatify/api/library-pool/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                uri: _state.uri,
                // song_* identify the POOL ENTRY; artist/title are the
                // (possibly corrected) terms to search MusicBrainz with.
                song_title: _state.songTitle,
                song_artist: _state.songArtist,
                artist: _dlg.querySelector('[data-cd="artist"]').value,
                title: _dlg.querySelector('[data-cd="title"]').value,
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _status(data.error || _t('admin.library.fixFailed', 'Lookup failed.'), true);
            return;
        }
        _state.current = data.current || _state.current;
        _state.candidates = data.candidates || [];
        _renderCurrent();
        _renderCandidates();
        _status('');
    } catch (err) {
        _status(_t('admin.library.fixFailed', 'Lookup failed.'), true);
    } finally {
        _state.busy = false;
    }
}

async function _save({ year, title, artist }) {
    if (_state.busy) return;
    const manual = _dlg.querySelector('[data-cd="year"]').value;
    const payload = {
        uri: _state.uri,
        song_title: _state.songTitle,
        song_artist: _state.songArtist,
    };
    if (year != null) payload.year = year;
    else if (manual !== '') payload.year = Number(manual);
    if (title) payload.title = title;
    if (artist) payload.artist = artist;
    if (payload.year == null && !payload.title && !payload.artist) {
        _status(_t('admin.library.fixNothing', 'Pick a match or enter a year first.'), true);
        return;
    }
    _state.busy = true;
    _status(_t('admin.library.fixSaving', 'Saving…'));
    try {
        const resp = await _fetch('/beatify/api/library-pool/correct', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _status(data.error || _t('admin.library.fixFailed', 'Could not save.'), true);
            return;
        }
        _status(_t('admin.library.fixSaved', 'Saved — future games will use your correction.'));
        setTimeout(_close, 1200);
    } catch (err) {
        _status(_t('admin.library.fixFailed', 'Could not save.'), true);
    } finally {
        _state.busy = false;
    }
}

/**
 * Open the correction dialog for one library song.
 * @param {{uri: string, title?: string, artist?: string}} song
 */
export function openSongCorrection(song) {
    // A URI is optional: the reveal screen knows the song only by name,
    // because the reveal payload withholds playable URIs from clients. The
    // server resolves the pool entry from title+artist in that case.
    if (!song || (!song.uri && !song.title)) return;
    const dlg = _ensureDialog();
    _state = {
        uri: song.uri || null,
        songTitle: song.title || '',
        songArtist: song.artist || '',
        current: song,
        candidates: [],
        busy: false,
    };
    dlg.querySelector('[data-cd="artist"]').value = song.artist || '';
    dlg.querySelector('[data-cd="title"]').value = song.title || '';
    dlg.querySelector('[data-cd="year"]').value = '';
    dlg.querySelector('[data-cd="results"]').innerHTML = '';
    _renderCurrent();
    _status('');
    dlg.classList.remove('hidden');
    _search();
}

// The reveal screen lives in the player bundle and has no module access to
// this one, so expose a global it can call.
if (typeof window !== 'undefined') {
    window.BeatifyCrateDiggerFix = { open: openSongCorrection };
}
