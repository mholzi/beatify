/**
 * Beatify Playlist Generator (#1052, #1057).
 *
 * Bridge between a Spotify playlist URL and Beatify's bundled-format JSON,
 * without Beatify itself calling any LLM. The flow is:
 *
 *   1. User pastes a Spotify playlist URL.
 *   2. User clicks "Copy prompt" → templated LLM prompt lands on clipboard.
 *   3. User runs the prompt in their own LLM, copies the JSON back.
 *   4. User pastes the JSON, clicks Validate.
 *   5. Per-row table shows ✓/✗ per field; suspicious-looking IDs are warned.
 *   6. When valid → either "Save locally" (writes to <config>/beatify/playlists/user/)
 *      or "Submit as GitHub issue" (opens pre-filled compose URL, then prompts
 *      the user to paste back the resulting issue URL so the submission shows
 *      up alongside existing playlist requests in the Mine tab).
 *
 * Loaded as a classic IIFE (not an ES module) so it works without import
 * plumbing inside admin.html.
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------
    // i18n shim. window.BeatifyI18n is loaded from i18n.js earlier in
    // admin.html; we read it lazily because the IIFE itself runs at
    // script-tag time (before user interaction). Falls back to the
    // English literal when a key is unknown or i18n isn't ready.
    //
    // The prompt itself (buildPrompt) and the LLM refinement brief
    // (formatValidationForLLM) deliberately stay English: both are
    // prompt-engineering payloads sent to an LLM, not user-visible
    // chrome. Beatify already passes English to LLMs in this feature,
    // and English is the strongest instruction-following channel.
    // -----------------------------------------------------------------
    function _t(key, fallback, args) {
        let val = fallback;
        try {
            if (window.BeatifyI18n && typeof window.BeatifyI18n.t === 'function') {
                const got = window.BeatifyI18n.t(key, fallback);
                if (got) val = got;
            }
        } catch (e) { /* i18n not ready */ }
        if (args && typeof val === 'string') {
            for (const [k, v] of Object.entries(args)) {
                val = val.replace(new RegExp('\\{' + k + '\\}', 'g'), String(v));
            }
        }
        return val;
    }

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
    // Paste-corruption sanitizer.
    //
    // Some chat renderers (Telegram and friends) wrap bare URLs inside
    // code blocks with Markdown autolink syntax `<URL>`. When the user
    // copy-pastes JSON from chat into Beatify's textarea, those angle
    // brackets travel along as part of the JSON string value, breaking
    // shape validation on every URI field. We can't fix the chat
    // renderer; we CAN strip the wrappers transparently before
    // validation and write the cleaned JSON back to the textarea so
    // the user sees what was changed.
    //
    // Limited to known URI fields (Spotify/Apple/YouTube/Tidal/Deezer)
    // because stripping `<>` from arbitrary strings would silently
    // mutate legitimate content (e.g. a fun_fact that mentions
    // "<Sandstorm>" in quotes).
    // -----------------------------------------------------------------

    const URI_FIELD_NAMES = ['uri', 'uri_apple_music', 'uri_youtube_music', 'uri_tidal', 'uri_deezer'];

    function _stripWrappers(v) {
        if (typeof v !== 'string') return v;
        let s = v;
        if (s.length >= 2 && s.startsWith('<') && s.endsWith('>')) s = s.slice(1, -1);
        s = s.replace(/^\s+|\s+$/g, '');
        return s;
    }

    // Pre-parse cleanup. LLMs ignore "no markdown fences" rules; users
    // paste back the validation brief by accident; some chat renderers
    // add a heading line. The common shape: real JSON is nested inside
    // non-JSON wrapping. Try (a) extracting between ``` fences, then
    // (b) trimming everything before the first `{` and after the last
    // `}`. Both heuristics are safe because a Beatify playlist is a
    // single JSON object — text outside the outermost braces cannot be
    // part of it.
    function _stripMarkdownWrapper(text) {
        if (typeof text !== 'string') return { text, changed: false };
        let s = text;
        let changed = false;
        const fenceMatch = s.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/i);
        if (fenceMatch) {
            s = fenceMatch[1];
            changed = true;
        }
        const first = s.indexOf('{');
        const last = s.lastIndexOf('}');
        if (first > 0 || (last !== -1 && last < s.length - 1)) {
            if (first !== -1 && last > first) {
                const candidate = s.slice(first, last + 1);
                if (candidate !== s) {
                    s = candidate;
                    changed = true;
                }
            }
        }
        return { text: s, changed };
    }

    function sanitizePlaylistText(jsonText) {
        const out = { text: jsonText, changes: 0, parseError: null, strippedWrapper: false };
        if (typeof jsonText !== 'string' || jsonText.trim() === '') return out;
        let working = jsonText;
        const stripped = _stripMarkdownWrapper(working);
        if (stripped.changed) {
            working = stripped.text;
            out.strippedWrapper = true;
        }
        let data;
        try { data = JSON.parse(working); } catch (e) {
            out.parseError = e && e.message ? e.message : String(e);
            if (out.strippedWrapper) out.text = working;
            return out;
        }
        let changes = 0;
        if (data && typeof data === 'object' && Array.isArray(data.songs)) {
            for (const song of data.songs) {
                if (!song || typeof song !== 'object') continue;
                for (const f of URI_FIELD_NAMES) {
                    if (f in song) {
                        const before = song[f];
                        const after = _stripWrappers(before);
                        if (after !== before) {
                            song[f] = after;
                            changes += 1;
                        }
                    }
                }
                const r = song.uri_apple_music_by_region;
                if (r && typeof r === 'object' && !Array.isArray(r)) {
                    for (const k of Object.keys(r)) {
                        const before = r[k];
                        const after = _stripWrappers(before);
                        if (after !== before) {
                            r[k] = after;
                            changes += 1;
                        }
                    }
                }
            }
        }
        out.changes = changes;
        out.text = (changes > 0 || out.strippedWrapper)
            ? JSON.stringify(data, null, 2)
            : jsonText;
        return out;
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

    // Echo the value the LLM returned alongside each shape-error so a
    // paste-corruption issue (smart quotes, non-breaking spaces in the
    // middle of a URL, etc.) is one glance away from being diagnosed
    // instead of looking like a regex/data mystery.
    function _echo(value) {
        if (value === undefined) return ' Got: (missing)';
        if (value === null) return ' Got: null';
        if (typeof value === 'string') {
            const safe = value.length > 80 ? value.slice(0, 77) + '…' : value;
            return ` Got: ${JSON.stringify(safe)}`;
        }
        if (typeof value === 'object') {
            const j = JSON.stringify(value);
            return ` Got: ${j.length > 100 ? j.slice(0, 97) + '…' : j}`;
        }
        return ` Got: ${JSON.stringify(value)}`;
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
            if (!ok) result.errors.push({ field: 'uri', message: 'uri must look like spotify:track:<22 base62>.' + _echo(song.uri) });
        }
        // apple music single + by_region
        {
            const status = _checkUri(song.uri_apple_music, APPLE_MUSIC_RE, false);
            const ok = status === 'ok';
            result.fields.uri_apple_music = ok;
            if (!ok) result.errors.push({ field: 'uri_apple_music', message: 'uri_apple_music must look like applemusic://track/<digits>.' + _echo(song.uri_apple_music) });
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
            if (!ok) result.errors.push({ field: 'uri_youtube_music', message: 'uri_youtube_music must look like https://music.youtube.com/watch?v=<id>.' + _echo(song.uri_youtube_music) });
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
            if (!ok) result.errors.push({ field: 'uri_deezer', message: 'uri_deezer must be null or deezer://track/<digits>.' + _echo(song.uri_deezer) });
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
    // Validation → Markdown brief for an LLM (refinement round-trip).
    // Users paste this back into the same LLM session that produced the
    // original JSON, so it can return a corrected object.
    // -----------------------------------------------------------------

    function _summarizeValue(v) {
        if (v === undefined) return '(missing)';
        if (v === null) return 'null';
        if (typeof v === 'string') {
            const trimmed = v.length > 120 ? v.slice(0, 117) + '…' : v;
            return JSON.stringify(trimmed);
        }
        if (typeof v === 'object') {
            const json = JSON.stringify(v);
            return json.length > 200 ? json.slice(0, 197) + '…' : json;
        }
        return JSON.stringify(v);
    }

    function formatValidationForLLM(validation, originalJsonText) {
        if (!validation) return '';
        if (validation.parseError) {
            return [
                'The JSON you returned could not be parsed.',
                '',
                `Parser error: ${validation.parseError}`,
                '',
                'Common causes: leading or trailing markdown fences (```json … ```), preamble text before `{`, trailing commas, smart quotes instead of `"`.',
                '',
                'Return a single valid JSON object that conforms to the Beatify playlist schema you were originally given. No markdown fences, no commentary.',
            ].join('\n');
        }

        // The validator already ran on this text — re-parse only to look up
        // actual values per field. If somehow this fails we degrade
        // gracefully and skip the value echoes.
        let data = null;
        if (typeof originalJsonText === 'string') {
            try { data = JSON.parse(originalJsonText); } catch (e) { data = null; }
        }

        const errorLines = [];
        const warningLines = [];

        // The validator already appends a `Got: ...` echo to most shape
        // errors (see _echo), so we don't append a second echo here for
        // top-level + per-song errors. For warnings we still echo the
        // current value because warnings don't carry one yet.

        for (const e of validation.topErrors) {
            const actual = data && data !== null && (e.field in data) ? data[e.field] : undefined;
            const echo = /Got:/.test(e.message) ? '' : ` Got: ${_summarizeValue(actual)}`;
            errorLines.push(`- \`${e.field}\` — ${e.message}${echo}`);
        }

        const songs = data && Array.isArray(data.songs) ? data.songs : null;
        for (const r of validation.songResults) {
            const song = songs ? songs[r.index] : null;
            const ref = song && typeof song === 'object'
                ? `${song.artist || '?'} / ${song.title || '?'}`
                : '';
            const songPath = `songs[${r.index}]`;
            for (const e of r.errors) {
                const actual = song && typeof song === 'object' && (e.field in song) ? song[e.field] : undefined;
                const echo = /Got:/.test(e.message) ? '' : ` Got: ${_summarizeValue(actual)}`;
                errorLines.push(`- \`${songPath}.${e.field}\`${ref ? ` (${ref})` : ''} — ${e.message}${echo}`);
            }
            for (const w of r.warnings) {
                const actual = song && typeof song === 'object' && (w.field in song) ? song[w.field] : undefined;
                warningLines.push(`- \`${songPath}.${w.field}\`${ref ? ` (${ref})` : ''} — ${w.message}. Current value: ${_summarizeValue(actual)}`);
            }
        }

        const totalSongs = validation.songResults.length;
        const cleanSongs = validation.songResults.filter((r) => r.errors.length === 0 && r.warnings.length === 0).length;
        const cleanIndices = validation.songResults
            .filter((r) => r.errors.length === 0 && r.warnings.length === 0)
            .map((r) => r.index);

        const parts = [];
        parts.push('# Beatify playlist JSON — validation feedback');
        parts.push('');
        parts.push(`You returned a playlist with ${totalSongs} song${totalSongs === 1 ? '' : 's'}. The validator found **${errorLines.length} error${errorLines.length === 1 ? '' : 's'}** and **${warningLines.length} warning${warningLines.length === 1 ? '' : 's'}**.`);
        parts.push('');

        if (errorLines.length) {
            parts.push('## Errors — these must be fixed');
            parts.push(...errorLines);
            parts.push('');
        }

        if (warningLines.length) {
            parts.push('## Warnings — likely hallucinated identifiers');
            parts.push('These passed shape validation but match patterns that usually indicate the LLM guessed. Double-check against the actual streaming services if you can; if you cannot find verified IDs, leave the field as-is and append `(LLM-generated identifiers — verify with the Beatify URI resolver)` to the playlist `description`.');
            parts.push('');
            parts.push(...warningLines);
            parts.push('');
        }

        if (cleanSongs > 0 && cleanSongs < totalSongs) {
            const refList = cleanIndices.map((i) => `songs[${i}]`).join(', ');
            parts.push(`The following entries validated cleanly — **do not modify them**: ${refList} (${cleanSongs}/${totalSongs} songs).`);
            parts.push('');
        }

        if (errorLines.length === 0 && warningLines.length === 0) {
            parts.push('No errors or warnings — your JSON validated cleanly. You probably do not need to send this back. Sending it anyway is fine if you want the LLM to extend the playlist with more songs in the same shape.');
            parts.push('');
        }

        // Embed the original JSON so the LLM can patch in place without
        // having to remember every field it produced — saves a round-trip
        // when the user's chat history is truncated or compressed.
        if (data !== null) {
            parts.push('## Your previous JSON (patch this; do not regenerate from scratch)');
            parts.push('```json');
            parts.push(JSON.stringify(data, null, 2));
            parts.push('```');
            parts.push('');
        }

        parts.push('## Output instructions');
        parts.push('- Return ONLY the corrected JSON object.');
        parts.push('- No markdown code fences, no preamble, no closing remarks.');
        parts.push('- Keep every field that validated cleanly exactly as it was.');
        parts.push('- For each error above: replace the bad value with a correctly-shaped one.');
        parts.push('- For each warning above: either replace with a verified value or follow the description-note convention above.');
        return parts.join('\n');
    }

    // -----------------------------------------------------------------
    // Issue URL parser (#1057): pull the issue number out of a GitHub
    // issue URL the user pastes back after submitting on github.com.
    // Accepts:
    //   https://github.com/<owner>/<repo>/issues/<n>
    //   https://github.com/<owner>/<repo>/issues/<n>#issuecomment-...
    //   github.com/.../issues/<n>
    // -----------------------------------------------------------------

    function parseIssueNumberFromUrl(url) {
        if (!url || typeof url !== 'string') return null;
        const m = url.match(/github\.com\/[\w.-]+\/[\w.-]+\/issues\/(\d+)/i);
        return m ? parseInt(m[1], 10) : null;
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
        // After the user clicks "Submit as GitHub issue" we open the compose
        // URL in a new tab and surface a follow-up panel that asks them to
        // paste the resulting issue URL — that's the only way we can recover
        // the issue number for tracking (the compose URL gives us no
        // round-trip). null until submitted; while truthy the paste panel
        // is visible.
        pendingSubmission: null,
        // Set once the issue-paste form has been resolved successfully so
        // we can show a confirmation rather than re-prompting the user.
        capturedIssueNumber: null,
        // Set after a successful Save locally so we can confirm in-modal.
        savedFilename: null,
    };

    function _renderResultsTable(validation) {
        if (!validation) return '';
        if (validation.parseError) {
            return `<div class="plg-error">${_esc(_t('playlistGenerator.results.parseFailed', 'JSON parse failed: {error}', { error: validation.parseError }))}</div>`;
        }
        const blocks = [];
        if (validation.topErrors.length) {
            blocks.push(`
                <div class="plg-block plg-block-err">
                    <h4>${_esc(_t('playlistGenerator.results.topErrors', 'Top-level errors'))}</h4>
                    <ul>${validation.topErrors.map((e) => `<li><b>${_esc(e.field)}</b> — ${_esc(e.message)}</li>`).join('')}</ul>
                </div>
            `);
        }
        // Per-song details: only show songs that have actual issues.
        // The per-row ✓/✗ checkmark grid was removed — on narrow mobile
        // viewports the cells stacked vertically (because the table was
        // wider than the viewport with horizontal scroll), and on any
        // viewport a green tick-grid told the user nothing they didn't
        // already see in the verdict line.
        const songsWithIssues = validation.songResults.filter((r) => (r.errors && r.errors.length) || (r.warnings && r.warnings.length));
        if (songsWithIssues.length > 0) {
            const songBlocks = songsWithIssues.map((r) => {
                const errs = (r.errors || []).map((e) => `<li class="plg-err-item"><b>${_esc(e.field)}</b>: ${_esc(e.message)}</li>`).join('');
                const warns = (r.warnings || []).map((w) => `<li class="plg-warn-item"><b>${_esc(w.field)}</b>: ${_esc(w.message)}</li>`).join('');
                const heading = _t('playlistGenerator.results.songLabel', 'Song #{n}', { n: r.index + 1 });
                return `<div class="plg-song-issue"><div class="plg-song-issue-head">${_esc(heading)}</div>${errs ? `<ul class="plg-err-list">${errs}</ul>` : ''}${warns ? `<ul class="plg-warn-list">${warns}</ul>` : ''}</div>`;
            }).join('');
            const headerText = _t('playlistGenerator.results.songIssues', 'Songs with issues ({n})', { n: songsWithIssues.length });
            blocks.push(`
                <div class="plg-block plg-block-err">
                    <h4>${_esc(headerText)}</h4>
                    ${songBlocks}
                </div>
            `);
        }
        const verdict = validation.ok
            ? `<div class="plg-verdict plg-verdict-ok">${_esc(_t('playlistGenerator.verdict.ok', '✓ Validation passed — ready to submit.'))}</div>`
            : `<div class="plg-verdict plg-verdict-bad">${_esc(_t('playlistGenerator.verdict.fail', '✗ Validation failed — fix the rows highlighted above and re-validate.'))}</div>`;
        const copyForLlm = `
            <div class="plg-row plg-results-actions">
                <button class="plg-btn plg-btn-secondary" data-plg-action="copy-result">${_esc(_t('playlistGenerator.actions.copyResult', 'Copy result for LLM'))}</button>
                <span class="plg-hint plg-hint-inline">${_esc(_t('playlistGenerator.hints.copyResultHint', 'Paste this back into your LLM to ask for a corrected JSON.'))}</span>
            </div>
        `;
        return verdict + copyForLlm + blocks.join('');
    }

    function _renderModal() {
        if (!state.rootEl) return;
        const v = state.lastValidation;
        const canSubmit = !!(v && v.ok);
        const submitTooltip = canSubmit
            ? _t('playlistGenerator.hints.submitTooltip', 'Open a new GitHub issue with the JSON pre-filled')
            : _t('playlistGenerator.hints.submitDisabledTooltip', 'Validate first');
        const saveLocalTooltip = canSubmit
            ? _t('playlistGenerator.hints.saveLocalTooltip', 'Save this playlist to your Home Assistant — it appears in the Community tab.')
            : _t('playlistGenerator.hints.submitDisabledTooltip', 'Validate first');
        state.rootEl.innerHTML = `
            <div class="plg-scrim" data-plg-action="close"></div>
            <div class="plg-modal" role="dialog" aria-modal="true" aria-labelledby="plg-title">
                <button class="plg-close" data-plg-action="close" aria-label="${_esc(_t('playlistGenerator.actions.close', 'Close'))}">✕</button>
                <h2 class="plg-title" id="plg-title">${_esc(_t('playlistGenerator.title', 'Playlist Generator'))}</h2>
                <p class="plg-sub">${_t('playlistGenerator.intro', 'Paste a Spotify playlist URL → copy a prompt → run it in your own LLM (ChatGPT, Claude.ai, local) → paste the JSON back → validate → submit. <b>No LLM calls leave Beatify.</b>')}</p>

                <label class="plg-label">${_esc(_t('playlistGenerator.fields.spotifyUrl', 'Spotify playlist URL'))}</label>
                <input type="url" class="plg-input" data-plg-field="spotify_url" placeholder="${_esc(_t('playlistGenerator.placeholders.spotifyUrl', 'https://open.spotify.com/playlist/…'))}" />
                <div class="plg-row">
                    <button class="plg-btn plg-btn-primary" data-plg-action="copy-prompt">${_esc(_t('playlistGenerator.actions.copyPrompt', 'Copy prompt'))}</button>
                    <span class="plg-hint" data-plg-hint></span>
                </div>

                <label class="plg-label">${_esc(_t('playlistGenerator.fields.jsonPaste', "Paste the LLM's JSON output here"))}</label>
                <textarea class="plg-textarea" data-plg-field="json" placeholder='${_esc(_t('playlistGenerator.placeholders.json', '{"name": "…", "version": "1.0", "songs": [ … ]}'))}' spellcheck="false"></textarea>
                <div class="plg-row">
                    <button class="plg-btn plg-btn-secondary" data-plg-action="validate">${_esc(_t('playlistGenerator.actions.validate', 'Validate'))}</button>
                    <button class="plg-btn plg-btn-ghost" data-plg-action="clear">${_esc(_t('playlistGenerator.actions.clear', 'Clear'))}</button>
                </div>

                <div class="plg-results" data-plg-results>${_renderResultsTable(v)}</div>

                <div class="plg-actions">
                    <button class="plg-btn plg-btn-success" data-plg-action="submit-issue" ${canSubmit ? '' : 'disabled'} title="${_esc(submitTooltip)}">${_esc(_t('playlistGenerator.actions.submitIssue', 'Submit as GitHub issue'))}</button>
                    <button class="plg-btn plg-btn-secondary" data-plg-action="copy-json" ${canSubmit ? '' : 'disabled'}>${_esc(_t('playlistGenerator.actions.copyJson', 'Copy validated JSON'))}</button>
                    <button class="plg-btn plg-btn-primary" data-plg-action="save-local" ${canSubmit ? '' : 'disabled'} title="${_esc(saveLocalTooltip)}">${_esc(_t('playlistGenerator.actions.saveLocal', 'Save locally'))}</button>
                </div>

                <div class="plg-followup" data-plg-followup>${_renderFollowup()}</div>

                <div class="plg-footer">
                    <p><b>${_esc(_t('playlistGenerator.footer.limitation', 'Known limitation:'))}</b> ${_t('playlistGenerator.footer.limitationBody', 'LLMs hallucinate ISRC and per-region Apple Music IDs. The validator checks <i>shape</i>, not real-world existence. Run the URI resolver after merge to replace any guessed IDs with verified ones.')}</p>
                </div>
            </div>
        `;
    }

    function _renderFollowup() {
        // Submission paste-back + save confirmation banners (#1057).
        // Both blocks are inert when their state slot is empty so the
        // modal stays clean for first-time users.
        const blocks = [];
        if (state.savedFilename) {
            blocks.push(`
                <div class="plg-banner plg-banner-ok">
                    ${_esc(_t(
                        'playlistGenerator.saveLocal.success',
                        'Saved as {filename}. It will show up in Playlist Hub → Community on the next refresh.',
                        { filename: state.savedFilename }
                    ))}
                </div>
            `);
        }
        if (state.pendingSubmission && !state.capturedIssueNumber) {
            blocks.push(`
                <div class="plg-banner plg-banner-info">
                    <p>${_esc(_t(
                        'playlistGenerator.submit.pasteIssuePrompt',
                        'Finish the issue on GitHub, then paste the issue URL here so it shows up in your Mine tab alongside existing playlist requests.'
                    ))}</p>
                    <div class="plg-row">
                        <input type="url" class="plg-input" data-plg-field="issue_url"
                            placeholder="https://github.com/mholzi/beatify/issues/…" />
                        <button class="plg-btn plg-btn-primary" data-plg-action="capture-issue">${_esc(_t('playlistGenerator.actions.captureIssue', 'Track this submission'))}</button>
                        <button class="plg-btn plg-btn-ghost" data-plg-action="dismiss-submission">${_esc(_t('playlistGenerator.actions.dismissSubmission', 'Skip'))}</button>
                    </div>
                    <span class="plg-hint" data-plg-followup-hint></span>
                </div>
            `);
        }
        if (state.capturedIssueNumber) {
            blocks.push(`
                <div class="plg-banner plg-banner-ok">
                    ${_esc(_t(
                        'playlistGenerator.submit.captured',
                        'Tracked as issue #{n}. Check progress in Playlist Hub → Mine.',
                        { n: state.capturedIssueNumber }
                    ))}
                </div>
            `);
        }
        return blocks.join('');
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
                .then(() => _setHint(_t('playlistGenerator.hints.promptCopied', 'Prompt copied to clipboard — paste it into your LLM.')))
                .catch(() => _setHint(_t('playlistGenerator.hints.clipboardUnavailable', 'Could not access clipboard — select the prompt manually below.')));
            return;
        }
        if (action === 'validate') {
            const ta = state.rootEl.querySelector('[data-plg-field="json"]');
            let txt = ta ? ta.value : '';
            // Two layers of paste-corruption cleanup before validation:
            //  1) Strip markdown wrappers (``` fences or # heading +
            //     trailing prose) so the JSON parses at all.
            //  2) Strip <URL> autolink wrappers from URI fields.
            // Both edits are written back to the textarea so the user
            // sees exactly what changed.
            const sanitized = sanitizePlaylistText(txt);
            const wrapperStripped = sanitized.strippedWrapper;
            const fieldChanges = sanitized.changes;
            if ((wrapperStripped || fieldChanges > 0) && !sanitized.parseError) {
                if (ta) ta.value = sanitized.text;
                txt = sanitized.text;
                if (wrapperStripped && fieldChanges > 0) {
                    _setHint(_t(
                        'playlistGenerator.hints.sanitizedBoth',
                        'Auto-cleaned: stripped a Markdown wrapper around the JSON and {n} URL wrapper(s) before validating.',
                        { n: fieldChanges }
                    ));
                } else if (wrapperStripped) {
                    _setHint(_t(
                        'playlistGenerator.hints.sanitizedWrapper',
                        'Auto-cleaned: stripped a Markdown wrapper around the JSON before validating.'
                    ));
                } else {
                    _setHint(_t(
                        'playlistGenerator.hints.sanitized',
                        'Auto-cleaned {n} URL wrapper(s) before validating (Markdown autolink artifacts).',
                        { n: fieldChanges }
                    ));
                }
            }
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
                const spotifyEl = state.rootEl.querySelector('[data-plg-field="spotify_url"]');
                state.pendingSubmission = {
                    playlist_name: (data && data.name) ? String(data.name) : 'Generated playlist',
                    spotify_url: spotifyEl ? spotifyEl.value.trim() : '',
                };
                state.capturedIssueNumber = null;
                const url = buildSubmitIssueUrl(data);
                window.open(url, '_blank', 'noopener,noreferrer');
                _renderFollowupOnly();
            } catch (err) {
                _setHint('Could not parse JSON for submission: ' + err.message);
            }
            return;
        }
        if (action === 'save-local') {
            if (!state.lastValidation || !state.lastValidation.ok) return;
            let data;
            try {
                data = JSON.parse(state.lastJsonText);
            } catch (err) {
                _setHint('Could not parse JSON for save: ' + err.message);
                return;
            }
            _saveLocally(data).catch((err) => {
                _setHint(_t(
                    'playlistGenerator.saveLocal.error',
                    'Save failed: {error}',
                    { error: (err && err.message) || 'unknown error' }
                ));
            });
            return;
        }
        if (action === 'capture-issue') {
            _captureIssueSubmission().catch((err) => {
                _setFollowupHint(_t(
                    'playlistGenerator.submit.captureError',
                    'Could not record submission: {error}',
                    { error: (err && err.message) || 'unknown error' }
                ));
            });
            return;
        }
        if (action === 'dismiss-submission') {
            state.pendingSubmission = null;
            state.capturedIssueNumber = null;
            _renderFollowupOnly();
            return;
        }
        if (action === 'copy-result') {
            if (!state.lastValidation) return;
            const md = formatValidationForLLM(state.lastValidation, state.lastJsonText);
            _copyToClipboard(md)
                .then(() => _setHint('Validation feedback copied — paste it back into your LLM.'))
                .catch(() => _setHint('Could not access clipboard.'));
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
        // Refresh action-button enablement (#1057: save-local follows the same
        // gate as submit/copy — needs a passing validation).
        const submit = state.rootEl && state.rootEl.querySelector('[data-plg-action="submit-issue"]');
        const copy = state.rootEl && state.rootEl.querySelector('[data-plg-action="copy-json"]');
        const save = state.rootEl && state.rootEl.querySelector('[data-plg-action="save-local"]');
        const can = !!(state.lastValidation && state.lastValidation.ok);
        if (submit) submit.disabled = !can;
        if (copy) copy.disabled = !can;
        if (save) save.disabled = !can;
    }

    function _renderFollowupOnly() {
        const host = state.rootEl && state.rootEl.querySelector('[data-plg-followup]');
        if (host) host.innerHTML = _renderFollowup();
    }

    function _setFollowupHint(msg) {
        const h = state.rootEl && state.rootEl.querySelector('[data-plg-followup-hint]');
        if (h) h.textContent = msg;
    }

    // -----------------------------------------------------------------
    // Save locally (#1057)
    //
    // POST the validated playlist to /beatify/api/playlists/save. The
    // server validates again, writes to <config>/beatify/playlists/user/
    // and returns the resolved filename. We surface the filename in the
    // confirmation banner so the user can find it on disk if needed.
    // -----------------------------------------------------------------

    async function _saveLocally(playlist) {
        const resp = await fetch('/beatify/api/playlists/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ playlist }),
        });
        if (!resp.ok) {
            let detail = '';
            try {
                const body = await resp.json();
                detail = body && (body.message || body.error) || '';
            } catch (e) { /* non-JSON body */ }
            throw new Error(detail || ('HTTP ' + resp.status));
        }
        const data = await resp.json();
        state.savedFilename = data && data.filename ? String(data.filename) : null;
        _renderFollowupOnly();
    }

    // -----------------------------------------------------------------
    // Capture GitHub submission (#1057, Part B)
    //
    // After the user finishes the issue on github.com they paste the
    // resulting URL into the follow-up panel. We parse out the issue
    // number, then append a record to /beatify/api/playlist-requests so
    // the existing PlaylistRequestsView GitHub-sync (#970) advances the
    // status from SUBMITTED → REVIEWED → BUILDING → IN BUNDLED without
    // any other code changes. The record carries `source: "generator"`
    // so the Mine tab can distinguish it from the existing request-modal
    // entries if it ever wants to.
    // -----------------------------------------------------------------

    async function _captureIssueSubmission() {
        const sub = state.pendingSubmission;
        if (!sub) return;
        const input = state.rootEl && state.rootEl.querySelector('[data-plg-field="issue_url"]');
        const url = input ? input.value.trim() : '';
        const issueNumber = parseIssueNumberFromUrl(url);
        if (!issueNumber) {
            _setFollowupHint(_t(
                'playlistGenerator.submit.invalidIssueUrl',
                'That does not look like a GitHub issue URL. Expected something like https://github.com/mholzi/beatify/issues/123.'
            ));
            return;
        }

        // Read-modify-write against the same backend store the existing
        // request-modal flow uses (BACKEND_API = /beatify/api/playlist-requests).
        // POST replaces the full list; we GET first so we don't drop existing
        // requests on append.
        const getResp = await fetch('/beatify/api/playlist-requests');
        let store = { requests: [], last_poll: null };
        if (getResp.ok) {
            try { store = await getResp.json(); } catch (e) { /* keep default */ }
        }
        if (!store || !Array.isArray(store.requests)) {
            store = { requests: [], last_poll: store ? store.last_poll : null };
        }

        const existing = store.requests.findIndex((r) => r && r.issue_number === issueNumber);
        const record = {
            issue_number: issueNumber,
            spotify_url: sub.spotify_url || '',
            playlist_name: sub.playlist_name || 'Generated playlist',
            thumbnail_url: null,
            requested_at: new Date().toISOString(),
            status: 'pending',
            release_version: null,
            decline_reason: null,
            last_checked: null,
            source: 'generator',
        };
        if (existing >= 0) {
            store.requests[existing] = Object.assign({}, store.requests[existing], record);
        } else {
            store.requests.push(record);
        }

        const postResp = await fetch('/beatify/api/playlist-requests', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(store),
        });
        if (!postResp.ok) {
            throw new Error('HTTP ' + postResp.status);
        }

        state.capturedIssueNumber = issueNumber;
        state.pendingSubmission = null;
        _renderFollowupOnly();
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
            formatValidationForLLM,
            sanitizePlaylistText,
            parseSpotifyPlaylistId,
            parseIssueNumberFromUrl,
            slugify,
        },
    };
})();
