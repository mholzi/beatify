/**
 * Beatify Admin — AI playlist curation from Crate Digger.
 *
 * Same trust model as the existing Playlist Generator (#1052): Beatify never
 * calls an LLM itself. The flow is BYO-model — works with ChatGPT, Claude, a
 * local Ollama, anything:
 *
 *   1. User enters a playlist name + a theme ("90s road trip", "songs about
 *      rain", …) and clicks "Copy prompt". We fetch the compact library index
 *      (GET /beatify/api/library-pool/export — artist/title/year/fame only,
 *      no URIs to hallucinate against) and put a templated prompt on the
 *      clipboard.
 *   2. User runs it in their own LLM and pastes the JSON answer back.
 *   3. "Check & preview" POSTs the picks to
 *      /beatify/api/library-playlists/resolve, which matches them against the
 *      pool and attaches verified years + playable URIs server-side; the
 *      modal shows matched/unmatched per row.
 *   4. "Save playlist" stores the resolved playlist through the same
 *      SavePlaylistView every user playlist uses → appears in Playlists→Mine.
 *
 * The prompt builder is exported pure for unit tests.
 */

function _t(key, fallback) {
    const i18n = window.BeatifyI18n;
    if (i18n && typeof i18n.t === 'function') {
        const v = i18n.t(key);
        if (v && v !== key) return v;
    }
    return fallback;
}

function _fetch(url, opts) {
    const f = (window.BeatifyAuth && window.BeatifyAuth.fetch) || fetch;
    return f(url, opts);
}

/* ------------------------------------------------------------------ *
 *  Pure helpers (unit-tested)
 * ------------------------------------------------------------------ */

/**
 * Build the LLM prompt. Deliberately English (prompt-engineering payload, not
 * user-visible chrome — same convention as playlist-generator.js).
 * @param {{tracks: Array<{artist:string,title:string,year:number,fame:string}>, truncated?: boolean}} exportIndex
 * @param {string} theme
 * @param {number} count
 */
export function buildLibraryPrompt(exportIndex, theme, count) {
    const lines = (exportIndex.tracks || []).map(
        (t) => `${t.artist} — ${t.title} (${t.year}, ${t.fame})`
    );
    const truncNote = exportIndex.truncated
        ? '\n(Note: this is the most popular subset of a larger library.)'
        : '';
    return [
        'You are curating a party playlist for a music year-guessing game.',
        `Pick up to ${count} songs strictly FROM THE LIBRARY LIST below that best fit this theme:`,
        `THEME: ${theme}`,
        '',
        'Rules:',
        '- Only pick songs that appear in the list. Do not invent songs.',
        '- Prefer a spread of decades and mostly well-known ("mainstream"/"known") songs unless the theme says otherwise.',
        '- Answer with ONLY a JSON object, no prose, in exactly this shape:',
        '  {"songs": [{"artist": "...", "title": "..."}]}',
        '- Copy artist and title EXACTLY as written in the list.',
        '',
        `LIBRARY LIST (${lines.length} songs):${truncNote}`,
        ...lines,
    ].join('\n');
}

/**
 * Parse the LLM's pasted answer into picks. Tolerates ```json fences and
 * stray prose around the JSON object. Returns [] when nothing parseable.
 */
export function parseAiAnswer(text) {
    if (typeof text !== 'string') return [];
    let t = text.trim();
    const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fence) t = fence[1].trim();
    // Fall back to the outermost {...} (or bare [...]) if there's prose
    // around it. Arrays are checked first so a bare `[{...}]` answer isn't
    // truncated to its first inner object.
    if (!t.startsWith('{') && !t.startsWith('[')) {
        const os = t.indexOf('{');
        const oe = t.lastIndexOf('}');
        const as = t.indexOf('[');
        const ae = t.lastIndexOf(']');
        if (as >= 0 && ae > as && (os < 0 || as < os)) t = t.slice(as, ae + 1);
        else if (os >= 0 && oe > os) t = t.slice(os, oe + 1);
    }
    try {
        const obj = JSON.parse(t);
        const songs = Array.isArray(obj) ? obj : obj.songs;
        if (!Array.isArray(songs)) return [];
        return songs
            .filter((s) => s && typeof s === 'object')
            .map((s) => ({ artist: String(s.artist || ''), title: String(s.title || '') }))
            .filter((s) => s.artist && s.title);
    } catch (e) {
        return [];
    }
}

/* ------------------------------------------------------------------ *
 *  Modal
 * ------------------------------------------------------------------ */

let _modal = null;
let _resolved = null; // last successfully resolved playlist (ready to save)

function _ensureModal() {
    if (_modal) return _modal;
    const wrap = document.createElement('div');
    wrap.id = 'library-ai-modal';
    wrap.className = 'library-ai-modal hidden';
    wrap.innerHTML = `
      <div class="library-ai-modal__backdrop" data-ai="close"></div>
      <div class="library-ai-modal__card" role="dialog" aria-modal="true" aria-labelledby="library-ai-title">
        <div class="library-ai-modal__head">
          <h3 id="library-ai-title" data-i18n="admin.libraryAi.title">Create a playlist with AI</h3>
          <button type="button" class="library-ai-modal__close" data-ai="close" aria-label="Close">✕</button>
        </div>
        <p class="hint-text" data-i18n="admin.libraryAi.intro">Beatify never contacts an AI itself. Copy the prompt into any chatbot or local model you trust, then paste its answer back.</p>

        <div class="library-ai-row">
          <label class="library-label" data-i18n="admin.libraryAi.name">Playlist name</label>
          <input type="text" class="text-input" data-ai="name" maxlength="100" placeholder="Summer BBQ bangers">
        </div>
        <div class="library-ai-row">
          <label class="library-label" data-i18n="admin.libraryAi.theme">Theme for the AI</label>
          <input type="text" class="text-input" data-ai="theme" maxlength="200" placeholder="upbeat summer hits, mostly 80s-00s">
        </div>
        <div class="library-ai-row library-ai-row--split">
          <label class="library-label" data-i18n="admin.libraryAi.count">Songs</label>
          <select class="select-input" data-ai="count">
            <option value="15">15</option><option value="20">20</option>
            <option value="30" selected>30</option><option value="50">50</option>
          </select>
          <button type="button" class="btn btn--secondary btn--small" data-ai="copy">
            <span data-i18n="admin.libraryAi.copy">Copy prompt</span>
          </button>
        </div>
        <p class="hint-text hidden" data-ai="copy-status" aria-live="polite"></p>

        <div class="library-ai-row">
          <label class="library-label" data-i18n="admin.libraryAi.paste">Paste the AI's answer</label>
          <textarea class="text-input library-ai-paste" data-ai="paste" rows="5" placeholder='{"songs": [{"artist": "...", "title": "..."}]}'></textarea>
        </div>
        <div class="library-ai-actions">
          <button type="button" class="btn btn--secondary btn--small" data-ai="resolve">
            <span data-i18n="admin.libraryAi.resolve">Check &amp; preview</span>
          </button>
          <button type="button" class="btn btn--primary btn--small" data-ai="save" disabled>
            <span data-i18n="admin.libraryAi.save">Save playlist</span>
          </button>
        </div>
        <div class="library-ai-result hidden" data-ai="result" aria-live="polite"></div>
      </div>`;
    document.body.appendChild(wrap);
    if (window.BeatifyI18n && typeof window.BeatifyI18n.apply === 'function') {
        try { window.BeatifyI18n.apply(wrap); } catch (e) { /* pre-init */ }
    }

    const $ = (sel) => wrap.querySelector(`[data-ai="${sel}"]`);
    wrap.addEventListener('click', (e) => {
        if (e.target.closest('[data-ai="close"]')) _close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !wrap.classList.contains('hidden')) _close();
    });

    $('copy').addEventListener('click', async () => {
        const status = $('copy-status');
        const theme = ($('theme').value || '').trim() || 'a fun, varied party mix';
        const count = parseInt($('count').value, 10) || 30;
        try {
            const resp = await _fetch('/beatify/api/library-pool/export?limit=2000');
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                status.textContent = data.message || _t('admin.libraryAi.needScan', 'Scan your library first.');
                status.classList.remove('hidden');
                return;
            }
            const prompt = buildLibraryPrompt(data, theme, count);
            await navigator.clipboard.writeText(prompt);
            status.textContent = _t('admin.libraryAi.copied', 'Prompt copied — paste it into your AI, then paste the answer below.');
            status.classList.remove('hidden');
        } catch (e) {
            status.textContent = _t('admin.libraryAi.copyFailed', 'Could not copy — is the page allowed to use the clipboard?');
            status.classList.remove('hidden');
        }
    });

    $('resolve').addEventListener('click', async () => {
        const result = $('result');
        const saveBtn = $('save');
        _resolved = null;
        saveBtn.disabled = true;
        const picks = parseAiAnswer($('paste').value);
        if (!picks.length) {
            result.innerHTML = `<p class="library-ai-bad">${_t('admin.libraryAi.parseFail', "Couldn't read any songs from that answer — expected JSON like") } {"songs":[{"artist":"…","title":"…"}]}</p>`;
            result.classList.remove('hidden');
            return;
        }
        const name = ($('name').value || '').trim() || _t('admin.libraryAi.defaultName', 'AI Mix');
        try {
            const resp = await _fetch('/beatify/api/library-playlists/resolve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, picks }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                result.innerHTML = `<p class="library-ai-bad">${data.message || 'Resolve failed'}</p>`;
                result.classList.remove('hidden');
                return;
            }
            const unmatched = data.unmatched || [];
            const matched = data.matched || 0;
            let html = `<p class="library-ai-good">${_t('admin.libraryAi.matched', 'Matched in your library: ')}<strong>${matched}</strong></p>`;
            if (unmatched.length) {
                html += `<p class="library-ai-bad">${_t('admin.libraryAi.unmatched', 'Not found (skipped): ')}${unmatched.length}</p><ul class="library-ai-unmatched">`;
                for (const u of unmatched.slice(0, 12)) {
                    html += `<li>${_esc(u.artist)} — ${_esc(u.title)}</li>`;
                }
                if (unmatched.length > 12) html += `<li>…</li>`;
                html += '</ul>';
            }
            result.innerHTML = html;
            result.classList.remove('hidden');
            if (matched > 0 && data.playlist) {
                _resolved = data.playlist;
                saveBtn.disabled = false;
            }
        } catch (e) {
            result.innerHTML = `<p class="library-ai-bad">${_t('admin.libraryAi.resolveFailed', 'Could not check the songs — is Home Assistant reachable?')}</p>`;
            result.classList.remove('hidden');
        }
    });

    $('save').addEventListener('click', async () => {
        if (!_resolved) return;
        const result = $('result');
        const saveBtn = $('save');
        saveBtn.disabled = true;
        try {
            const resp = await _fetch('/beatify/api/playlists/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ playlist: _resolved }),
            });
            const data = await resp.json().catch(() => ({}));
            if (resp.ok) {
                result.innerHTML = `<p class="library-ai-good">${_t('admin.libraryAi.saved', 'Saved! Find it under Playlists → Mine.')}</p>`;
                // #2637: same dead `window.loadPlaylists?.()` nudge as in
                // library.js — the global has never existed, so the refresh
                // never happened. Removed; the missing refresh is tracked
                // separately.
            } else {
                result.innerHTML = `<p class="library-ai-bad">${data.message || 'Save failed'}</p>`;
                saveBtn.disabled = false;
            }
        } catch (e) {
            result.innerHTML = `<p class="library-ai-bad">Save failed</p>`;
            saveBtn.disabled = false;
        }
    });

    _modal = wrap;
    return wrap;
}

function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _close() {
    if (_modal) _modal.classList.add('hidden');
}

export function openLibraryAiModal() {
    const m = _ensureModal();
    m.classList.remove('hidden');
    m.querySelector('[data-ai="name"]')?.focus();
}
