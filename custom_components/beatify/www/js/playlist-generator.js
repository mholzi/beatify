/**
 * Beatify Playlist Generator (#1052).
 *
 * Bridge between a Spotify playlist URL and Beatify's bundled-format JSON,
 * without Beatify itself calling any LLM. The flow is:
 *
 *   1. User pastes a Spotify playlist URL.
 *   2. User clicks "Copy prompt" → templated LLM prompt lands on clipboard.
 *   3. User runs the prompt in their own LLM, copies the JSON back.
 *   4. User pastes the JSON, clicks Validate.
 *   5. Per-row table shows ✓/✗ per field; suspicious-looking IDs are warned.
 *   6. When valid → "Submit as issue" opens a pre-filled GitHub issue with the JSON.
 *
 * v1 omits the "Save locally" path — that needs a new backend endpoint and
 * playlist-registry reload, both of which are out of scope for the first
 * iteration. The disabled placeholder explains this.
 *
 * Loaded as a classic IIFE (not an ES module) so it works without import
 * plumbing inside admin.html.
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------
    // Pure helpers — exported via window.PlaylistGenerator for vitest.
    // -----------------------------------------------------------------

    const SPOTIFY_TRACK_RE = /^spotify:track:[A-Za-z0-9]{22}$/;
    const APPLE_MUSIC_RE = /^applemusic:\/\/track\/\d+$/;
    const YT_MUSIC_RE = /^https:\/\/music\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{6,}$/;
    const DEEZER_RE = /^deezer:\/\/track\/\d+$/;
    // ISRC: 2 letters (country) + 3 alphanumeric (registrant) + 7 digits (year+designation) = 12 chars.
    const ISRC_RE = /^[A-Z]{2}[A-Z0-9]{3}\d{7}$/;
    const APPLE_REGIONS = ['us', 'de', 'gb', 'fr', 'es', 'nl', 'it'];
    const TOP_LEVEL_FIELDS = ['name', 'version', 'tags', 'language', 'author', 'added_date', 'description', 'songs'];
    const SONG_FIELDS = [
        'artist', 'title', 'year', 'isrc',
        'uri', 'uri_apple_music', 'uri_apple_music_by_region',
        'uri_youtube_music', 'uri_tidal', 'uri_deezer',
        'fun_fact', 'fun_fact_de', 'fun_fact_es', 'fun_fact_fr', 'fun_fact_nl',
    ];

    function currentYear() {
        return new Date().getUTCFullYear();
    }

    function parseSpotifyPlaylistId(url) {
        if (!url || typeof url !== 'string') return null;
        // Accept open.spotify.com/playlist/<id> with optional ?si=... and locale prefix.
        const m = url.match(/playlist\/([A-Za-z0-9]{22})/);
        return m ? m[1] : null;
    }

    function slugify(name) {
        return String(name || '')
            .toLowerCase()
            .normalize('NFKD')
            .replace(/[̀-ͯ]/g, '')
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 60) || 'untitled-playlist';
    }

    function buildPrompt(spotifyUrl, options) {
        const playlistId = parseSpotifyPlaylistId(spotifyUrl) || '';
        const fieldList = SONG_FIELDS.map((f) => `\`${f}\``).join(', ');
        const goldStandard = JSON.stringify({
            artist: 'U96',
            title: 'Das Boot',
            year: 1991,
            isrc: 'DEPI81403435',
            uri: 'spotify:track:5A3IdgGphzKS2etiGFB73S',
            uri_apple_music: 'applemusic://track/965771834',
            uri_apple_music_by_region: {
                us: 'applemusic://track/965253293',
                de: 'applemusic://track/965253293',
                gb: 'applemusic://track/965253293',
                fr: 'applemusic://track/965253293',
                es: 'applemusic://track/965253293',
                nl: 'applemusic://track/965253293',
                it: 'applemusic://track/965253293',
            },
            uri_youtube_music: 'https://music.youtube.com/watch?v=0snTYLgg9w0',
            uri_tidal: null,
            uri_deezer: 'deezer://track/94877938',
            fun_fact: 'A trance and dance-floor classic (1991).',
            fun_fact_de: 'Ein Trance- und Dancefloor-Klassiker (1991).',
            fun_fact_es: 'Un clásico del trance y la pista de baile (1991).',
            fun_fact_fr: 'Un classique de la trance et du dancefloor (1991).',
            fun_fact_nl: 'Een trance- en dancefloorklassieker (1991).',
        }, null, 2);
        const todayIso = new Date().toISOString().slice(0, 10);
        const yMax = currentYear();
        const tracksHint = options && options.trackList && options.trackList.length
            ? `\n\nTracks in this playlist (artist — title):\n${options.trackList.map((t, i) => `${i + 1}. ${t.artist} — ${t.title}`).join('\n')}`
            : '';
        return `You are filling a Beatify playlist JSON file from a Spotify playlist.

Spotify playlist URL: ${spotifyUrl || '(not provided)'}
Spotify playlist ID: ${playlistId || '(unknown)'}${tracksHint}

OUTPUT FORMAT
Return a single JSON object, no markdown fences, no commentary. The object MUST have these top-level fields:
${TOP_LEVEL_FIELDS.map((f) => `- ${f}`).join('\n')}

- name: human-readable playlist name (e.g. "Trance Classics")
- version: "1.0" for a first release
- tags: array of lowercase strings (genres, eras). Include decade tags like "1990s", "2000s".
- language: ISO 639-1 code of the songs' primary language ("en", "de", "es", "fr", "nl", "it", "pt", "ja", "ko"…)
- author: string — credit yourself or "Beatify Community"
- added_date: today's date in YYYY-MM-DD format. Use ${todayIso}.
- description: 1-2 sentences describing the playlist (era, vibe, count, region).
- songs: array of song objects.

Each song MUST have ALL of these fields (${fieldList}):
- artist: string
- title: string
- year: integer, 1900-${yMax}
- isrc: 12-char International Standard Recording Code (e.g. "DEPI81403435"). Pattern: 2 letters + 3 alphanumeric + 7 digits.
- uri: Spotify track URI, exactly "spotify:track:<22 base62 chars>"
- uri_apple_music: "applemusic://track/<digits>" — Apple Music track ID (US storefront is fine here)
- uri_apple_music_by_region: object with ALL these keys: ${APPLE_REGIONS.join(', ')}. Each value is "applemusic://track/<digits>" for that storefront.
- uri_youtube_music: "https://music.youtube.com/watch?v=<id>"
- uri_tidal: Tidal track URL or null if not available
- uri_deezer: "deezer://track/<digits>" or null
- fun_fact: 1-2 sentence trivia about the song in English.
- fun_fact_de: same fact translated to German.
- fun_fact_es: same fact translated to Spanish.
- fun_fact_fr: same fact translated to French.
- fun_fact_nl: same fact translated to Dutch.

GOLD STANDARD EXAMPLE (one song from Trance Classics):
${goldStandard}

RULES
- Every song must contain all 15 fields. uri_tidal may be null. Everything else must be populated.
- Do NOT invent ISRC or Apple Music IDs you are not sure of. If unsure, still fill the field but mark the playlist's description with "(LLM-generated identifiers — verify with the Beatify URI resolver)".
- Output ONLY JSON. No preamble, no closing remarks, no markdown code fences.`;
    }

    // -----------------------------------------------------------------
    // Validator
    // -----------------------------------------------------------------

    function _typeOf(v) {
        if (v === null) return 'null';
        if (Array.isArray(v)) return 'array';
        return typeof v;
    }

    function _checkUri(value, re, allowNull) {
        if (value === null || value === undefined || value === '') return allowNull ? 'ok' : 'missing';
        if (typeof value !== 'string') return 'bad-type';
        return re.test(value) ? 'ok' : 'bad-shape';
    }

    function validateSong(song, idx) {
        const result = { index: idx, fields: {}, errors: [], warnings: [] };
        if (!song || typeof song !== 'object' || Array.isArray(song)) {
            result.errors.push({ field: '*', message: `Song #${idx + 1} is not an object` });
            for (const f of SONG_FIELDS) result.fields[f] = false;
            return result;
        }
        // artist / title
        for (const f of ['artist', 'title']) {
            const ok = typeof song[f] === 'string' && song[f].trim().length > 0;
            result.fields[f] = ok;
            if (!ok) result.errors.push({ field: f, message: `${f} must be a non-empty string` });
        }
        // year
        const y = song.year;
        const yMax = currentYear();
        const yearOk = Number.isInteger(y) && y >= 1900 && y <= yMax;
        result.fields.year = yearOk;
        if (!yearOk) result.errors.push({ field: 'year', message: `year must be an integer 1900-${yMax}` });
        // isrc
        const isrcOk = typeof song.isrc === 'string' && ISRC_RE.test(song.isrc);
        result.fields.isrc = isrcOk;
        if (!isrcOk) result.errors.push({ field: 'isrc', message: 'isrc must match pattern AA000NNNNNNN (12 chars)' });
        // uri (spotify)
        {
            const status = _checkUri(song.uri, SPOTIFY_TRACK_RE, false);
            const ok = status === 'ok';
            result.fields.uri = ok;
            if (!ok) result.errors.push({ field: 'uri', message: 'uri must look like spotify:track:<22 base62>' });
        }
        // apple music single + by_region
        {
            const status = _checkUri(song.uri_apple_music, APPLE_MUSIC_RE, false);
            const ok = status === 'ok';
            result.fields.uri_apple_music = ok;
            if (!ok) result.errors.push({ field: 'uri_apple_music', message: 'uri_apple_music must look like applemusic://track/<digits>' });
        }
        {
            const r = song.uri_apple_music_by_region;
            let regionOk = r && typeof r === 'object' && !Array.isArray(r);
            const missing = [];
            const bad = [];
            const seen = new Set();
            if (regionOk) {
                for (const k of APPLE_REGIONS) {
                    const v = r[k];
                    if (typeof v !== 'string' || !APPLE_MUSIC_RE.test(v)) {
                        if (v === null || v === undefined || v === '') missing.push(k);
                        else bad.push(k);
                        regionOk = false;
                    } else {
                        seen.add(v);
                    }
                }
            }
            result.fields.uri_apple_music_by_region = regionOk;
            if (!regionOk) {
                const parts = [];
                if (missing.length) parts.push(`missing for ${missing.join(',')}`);
                if (bad.length) parts.push(`malformed for ${bad.join(',')}`);
                result.errors.push({
                    field: 'uri_apple_music_by_region',
                    message: parts.length ? parts.join('; ') : 'must be an object with all 7 regions',
                });
            }
            // Heuristic: if every region IS valid but they all resolve to the same ID,
            // the LLM probably hallucinated. Warn — don't fail.
            if (regionOk && seen.size === 1) {
                result.warnings.push({
                    field: 'uri_apple_music_by_region',
                    message: 'all regions share the same Apple Music ID — may be a hallucinated guess (storefronts usually differ)',
                });
            }
        }
        // YouTube Music
        {
            const status = _checkUri(song.uri_youtube_music, YT_MUSIC_RE, false);
            const ok = status === 'ok';
            result.fields.uri_youtube_music = ok;
            if (!ok) result.errors.push({ field: 'uri_youtube_music', message: 'uri_youtube_music must look like https://music.youtube.com/watch?v=<id>' });
        }
        // Tidal — nullable, anything string-ish accepted (Tidal URI shapes vary)
        {
            const v = song.uri_tidal;
            const ok = v === null || v === undefined || typeof v === 'string';
            result.fields.uri_tidal = ok;
            if (!ok) result.errors.push({ field: 'uri_tidal', message: 'uri_tidal must be a string or null' });
        }
        // Deezer — nullable, but if present must match
        {
            const status = _checkUri(song.uri_deezer, DEEZER_RE, true);
            const ok = status === 'ok';
            result.fields.uri_deezer = ok;
            if (!ok) result.errors.push({ field: 'uri_deezer', message: 'uri_deezer must be null or deezer://track/<digits>' });
        }
        // fun_facts (all required)
        for (const f of ['fun_fact', 'fun_fact_de', 'fun_fact_es', 'fun_fact_fr', 'fun_fact_nl']) {
            const ok = typeof song[f] === 'string' && song[f].trim().length > 0;
            result.fields[f] = ok;
            if (!ok) result.errors.push({ field: f, message: `${f} must be a non-empty string` });
        }
        return result;
    }

    function validatePlaylist(jsonText) {
        const out = {
            ok: false,
            parseError: null,
            topErrors: [],
            songResults: [],
            warnings: [],
        };
        let data;
        try {
            data = JSON.parse(jsonText);
        } catch (e) {
            out.parseError = e && e.message ? e.message : String(e);
            return out;
        }
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            out.parseError = 'Top-level JSON must be an object';
            return out;
        }
        // Top-level required fields + types
        const TYPE_EXPECT = {
            name: 'string', version: 'string', tags: 'array',
            language: 'string', author: 'string', added_date: 'string',
            description: 'string', songs: 'array',
        };
        for (const f of TOP_LEVEL_FIELDS) {
            if (!(f in data)) {
                out.topErrors.push({ field: f, message: `missing top-level field "${f}"` });
                continue;
            }
            const actual = _typeOf(data[f]);
            if (actual !== TYPE_EXPECT[f]) {
                out.topErrors.push({ field: f, message: `"${f}" must be ${TYPE_EXPECT[f]}, got ${actual}` });
            }
        }
        if (data.added_date && !/^\d{4}-\d{2}-\d{2}$/.test(String(data.added_date))) {
            out.topErrors.push({ field: 'added_date', message: 'added_date must be YYYY-MM-DD' });
        }
        // Validate songs (only when songs[] is an array)
        if (Array.isArray(data.songs)) {
            if (data.songs.length === 0) {
                out.topErrors.push({ field: 'songs', message: 'songs[] must not be empty' });
            }
            const isrcSeen = new Map();
            data.songs.forEach((song, idx) => {
                const r = validateSong(song, idx);
                out.songResults.push(r);
                if (r.fields.isrc && typeof song.isrc === 'string') {
                    const prev = isrcSeen.get(song.isrc);
                    if (prev !== undefined) {
                        // Hallucination tell: same ISRC across multiple songs.
                        r.warnings.push({
                            field: 'isrc',
                            message: `ISRC ${song.isrc} also appears on song #${prev + 1} — almost certainly hallucinated`,
                        });
                    } else {
                        isrcSeen.set(song.isrc, idx);
                    }
                }
            });
        }
        out.ok = out.topErrors.length === 0
            && out.songResults.length > 0
            && out.songResults.every((r) => r.errors.length === 0);
        return out;
    }

    // -----------------------------------------------------------------
    // Submit-as-issue URL builder
    // -----------------------------------------------------------------

    function buildSubmitIssueUrl(json) {
        // GitHub issue compose with pre-filled title + body. The user lands on
        // an unauthenticated "New issue" form; they finish by clicking
        // "Submit". GitHub treats the entire compose URL as a redirect target,
        // so very long JSON bodies may be truncated — we surface that risk in
        // the UI and offer "Copy JSON to clipboard" as a fallback.
        const name = (json && typeof json === 'object' && json.name) ? String(json.name) : 'New playlist';
        const slug = slugify(name);
        const title = `Community playlist submission: ${name}`;
        const bodyHeader = `**Playlist:** ${name}
**Suggested filename:** \`community/${slug}.json\`
**Songs:** ${(json && Array.isArray(json.songs)) ? json.songs.length : 'unknown'}

Generated via the Playlist Generator (#1052). JSON validated client-side. ISRC / Apple Music IDs were LLM-generated and need a pass through Beatify's URI resolver before merge.

<details>
<summary>Playlist JSON</summary>

\`\`\`json
__JSON__
\`\`\`

</details>`;
        const body = bodyHeader.replace('__JSON__', JSON.stringify(json, null, 2));
        const params = new URLSearchParams();
        params.set('title', title);
        params.set('body', body);
        params.set('labels', 'community-playlist-submission');
        return `https://github.com/mholzi/beatify/issues/new?${params.toString()}`;
    }

    // -----------------------------------------------------------------
    // UI (modal)
    // -----------------------------------------------------------------

    function _esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const state = {
        rootEl: null,
        lastJsonText: '',
        lastValidation: null,
    };

    function _renderResultsTable(validation) {
        if (!validation) return '';
        if (validation.parseError) {
            return `<div class="plg-error">JSON parse failed: ${_esc(validation.parseError)}</div>`;
        }
        const blocks = [];
        if (validation.topErrors.length) {
            blocks.push(`
                <div class="plg-block plg-block-err">
                    <h4>Top-level errors</h4>
                    <ul>${validation.topErrors.map((e) => `<li><b>${_esc(e.field)}</b> — ${_esc(e.message)}</li>`).join('')}</ul>
                </div>
            `);
        }
        const songCount = validation.songResults.length;
        if (songCount > 0) {
            const allFields = SONG_FIELDS;
            const rows = validation.songResults.map((r) => {
                const tds = allFields.map((f) => {
                    const ok = !!r.fields[f];
                    return `<td class="plg-cell plg-cell-${ok ? 'ok' : 'bad'}" title="${_esc(f)}">${ok ? '✓' : '✗'}</td>`;
                }).join('');
                const songErrors = (r.errors || []).map((e) => `<li>${_esc(e.field)}: ${_esc(e.message)}</li>`).join('');
                const songWarns = (r.warnings || []).map((w) => `<li>${_esc(w.field)}: ${_esc(w.message)}</li>`).join('');
                const details = (songErrors || songWarns)
                    ? `<tr class="plg-row-details"><td colspan="${allFields.length + 1}"><ul class="plg-err-list">${songErrors}</ul>${songWarns ? `<ul class="plg-warn-list">${songWarns}</ul>` : ''}</td></tr>`
                    : '';
                return `<tr class="plg-row ${r.errors.length ? 'plg-row-bad' : 'plg-row-ok'}"><td class="plg-row-idx">#${r.index + 1}</td>${tds}</tr>${details}`;
            }).join('');
            blocks.push(`
                <div class="plg-block">
                    <h4>Per-song validation (${songCount} songs)</h4>
                    <div class="plg-table-wrap">
                        <table class="plg-table">
                            <thead><tr><th>#</th>${allFields.map((f) => `<th title="${_esc(f)}">${_esc(f.replace(/^uri_/, '').replace(/^fun_fact_?/, 'ff_').replace(/_by_region$/, '·rgn'))}</th>`).join('')}</tr></thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                </div>
            `);
        }
        const verdict = validation.ok
            ? `<div class="plg-verdict plg-verdict-ok">✓ Validation passed — ready to submit.</div>`
            : `<div class="plg-verdict plg-verdict-bad">✗ Validation failed — fix the rows highlighted above and re-validate.</div>`;
        return verdict + blocks.join('');
    }

    function _renderModal() {
        if (!state.rootEl) return;
        const v = state.lastValidation;
        const canSubmit = !!(v && v.ok);
        state.rootEl.innerHTML = `
            <div class="plg-scrim" data-plg-action="close"></div>
            <div class="plg-modal" role="dialog" aria-modal="true" aria-labelledby="plg-title">
                <button class="plg-close" data-plg-action="close" aria-label="Close">✕</button>
                <h2 class="plg-title" id="plg-title">Playlist Generator</h2>
                <p class="plg-sub">Paste a Spotify playlist URL → copy a prompt → run it in your own LLM (ChatGPT, Claude.ai, local) → paste the JSON back → validate → submit. <b>No LLM calls leave Beatify.</b></p>

                <label class="plg-label">Spotify playlist URL</label>
                <input type="url" class="plg-input" data-plg-field="spotify_url" placeholder="https://open.spotify.com/playlist/…" />
                <div class="plg-row">
                    <button class="plg-btn plg-btn-primary" data-plg-action="copy-prompt">Copy prompt</button>
                    <span class="plg-hint" data-plg-hint></span>
                </div>

                <label class="plg-label">Paste the LLM's JSON output here</label>
                <textarea class="plg-textarea" data-plg-field="json" placeholder='{"name": "…", "version": "1.0", "songs": [ … ]}' spellcheck="false"></textarea>
                <div class="plg-row">
                    <button class="plg-btn plg-btn-secondary" data-plg-action="validate">Validate</button>
                    <button class="plg-btn plg-btn-ghost" data-plg-action="clear">Clear</button>
                </div>

                <div class="plg-results" data-plg-results>${_renderResultsTable(v)}</div>

                <div class="plg-actions">
                    <button class="plg-btn plg-btn-success" data-plg-action="submit-issue" ${canSubmit ? '' : 'disabled'} title="${canSubmit ? 'Open a new GitHub issue with the JSON pre-filled' : 'Validate first'}">Submit as GitHub issue</button>
                    <button class="plg-btn plg-btn-secondary" data-plg-action="copy-json" ${canSubmit ? '' : 'disabled'}>Copy validated JSON</button>
                    <button class="plg-btn plg-btn-disabled" disabled title="Coming in v1.1 — needs backend support">Save locally (v1.1)</button>
                </div>

                <div class="plg-footer">
                    <p><b>Known limitation:</b> LLMs hallucinate ISRC and per-region Apple Music IDs. The validator checks <i>shape</i>, not real-world existence. Run the URI resolver after merge to replace any guessed IDs with verified ones.</p>
                </div>
            </div>
        `;
    }

    function _onClick(e) {
        const a = e.target.closest('[data-plg-action]');
        if (!a) return;
        const action = a.dataset.plgAction;
        if (action === 'close') {
            close();
            return;
        }
        if (action === 'copy-prompt') {
            const urlEl = state.rootEl.querySelector('[data-plg-field="spotify_url"]');
            const url = urlEl ? urlEl.value.trim() : '';
            const prompt = buildPrompt(url);
            _copyToClipboard(prompt)
                .then(() => _setHint('Prompt copied to clipboard — paste it into your LLM.'))
                .catch(() => _setHint('Could not access clipboard — select the prompt manually below.'));
            return;
        }
        if (action === 'validate') {
            const ta = state.rootEl.querySelector('[data-plg-field="json"]');
            const txt = ta ? ta.value : '';
            state.lastJsonText = txt;
            state.lastValidation = validatePlaylist(txt);
            _renderResults();
            return;
        }
        if (action === 'clear') {
            const ta = state.rootEl.querySelector('[data-plg-field="json"]');
            if (ta) ta.value = '';
            state.lastJsonText = '';
            state.lastValidation = null;
            _renderResults();
            return;
        }
        if (action === 'submit-issue') {
            if (!state.lastValidation || !state.lastValidation.ok) return;
            try {
                const data = JSON.parse(state.lastJsonText);
                const url = buildSubmitIssueUrl(data);
                window.open(url, '_blank', 'noopener,noreferrer');
            } catch (err) {
                _setHint('Could not parse JSON for submission: ' + err.message);
            }
            return;
        }
        if (action === 'copy-json') {
            if (!state.lastJsonText) return;
            try {
                const data = JSON.parse(state.lastJsonText);
                _copyToClipboard(JSON.stringify(data, null, 2))
                    .then(() => _setHint('Pretty-printed JSON copied.'))
                    .catch(() => _setHint('Could not access clipboard.'));
            } catch (err) {
                _setHint('JSON is not parseable: ' + err.message);
            }
            return;
        }
    }

    function _renderResults() {
        const host = state.rootEl && state.rootEl.querySelector('[data-plg-results]');
        if (host) host.innerHTML = _renderResultsTable(state.lastValidation);
        // Refresh submit-button enablement.
        const submit = state.rootEl && state.rootEl.querySelector('[data-plg-action="submit-issue"]');
        const copy = state.rootEl && state.rootEl.querySelector('[data-plg-action="copy-json"]');
        const can = !!(state.lastValidation && state.lastValidation.ok);
        if (submit) submit.disabled = !can;
        if (copy) copy.disabled = !can;
    }

    function _setHint(msg) {
        const h = state.rootEl && state.rootEl.querySelector('[data-plg-hint]');
        if (h) h.textContent = msg;
    }

    function _copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve, reject) => {
            try {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.top = '-1000px';
                document.body.appendChild(ta);
                ta.select();
                const ok = document.execCommand('copy');
                document.body.removeChild(ta);
                ok ? resolve() : reject(new Error('copy failed'));
            } catch (e) { reject(e); }
        });
    }

    function open() {
        if (state.rootEl) return; // already open
        const host = document.createElement('div');
        host.className = 'plg-host';
        document.body.appendChild(host);
        state.rootEl = host;
        state.lastValidation = null;
        state.lastJsonText = '';
        _renderModal();
        host.addEventListener('click', _onClick);
        document.addEventListener('keydown', _onKeyDown, true);
    }

    function close() {
        if (!state.rootEl) return;
        try { state.rootEl.removeEventListener('click', _onClick); } catch (e) { /* noop */ }
        document.removeEventListener('keydown', _onKeyDown, true);
        if (state.rootEl.parentNode) state.rootEl.parentNode.removeChild(state.rootEl);
        state.rootEl = null;
    }

    function _onKeyDown(e) {
        if (e.key === 'Escape' && state.rootEl) close();
    }

    // -----------------------------------------------------------------
    // Public surface
    // -----------------------------------------------------------------

    window.PlaylistGenerator = {
        open,
        close,
        // exported for tests
        _internals: {
            buildPrompt,
            validatePlaylist,
            validateSong,
            buildSubmitIssueUrl,
            parseSpotifyPlaylistId,
            slugify,
        },
    };
})();
