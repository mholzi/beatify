// Beatify Cloudflare Worker (#2526: keep this file pure ASCII).
//
// This worker is deployed by copying the file into the Cloudflare dashboard.
// That copy path has been round-tripped through a terminal-style buffer at
// least once, which read the UTF-8 bytes as Latin-1 and then wrote the
// resulting control characters back out in caret notation. Every non-ASCII
// literal in the source was destroyed by it, so the issues this worker files
// arrived titled "data: wrong year reported \xc3\xa2^@^T ..." instead of
// carrying an em dash.
//
// The fix is structural: no byte in this file may be >= 0x80. Characters that
// have to reach GitHub (em dash, en dash, the zero-width spaces that break
// @mentions, emoji) are written as \u escapes, which are themselves ASCII and
// therefore survive any such round trip untouched. The runtime output is
// unchanged. tests/unit/test_worker_ascii_only_2526.py enforces the rule.

// ===========================================================================
// Input hardening for the open Beatify routes (#2688).
//
// These routes stay unauthenticated on purpose: thousands of installed Home
// Assistant clients call them and cannot be updated at once, and any secret
// shipped in an open-source integration is public. So what is protected here is
// what an issue can CONTAIN, not who may file one.
// ===========================================================================
const BE_MAX_BODY_CHARS = 16384;
const BE_MAX_ARTIST = 200;
const BE_MAX_SONG_TITLE = 200;
const BE_MAX_REPORTER = 40;
const BE_MAX_PLAYLIST_FILE = 300;
const BE_MAX_PLAYLIST_NAME = 200;
const BE_MAX_SPOTIFY_URL = 300;
const BE_MAX_ISSUE_TITLE = 250; // GitHub rejects titles over 256 characters.
const BE_MAX_SEARCH_TERMS = 150; // GitHub rejects search queries over 256.
// C0/C1 controls, line separators and bidi overrides. A no-break space (real
// artist credits contain them) is deliberately not in this set.
// eslint-disable-next-line no-control-regex -- matching them is the point
const BE_UNSAFE_CHARS = /[\u0000-\u001F\u007F-\u009F\u200E\u200F\u2028-\u202E\u2066-\u2069]/g;
const BE_SPOTIFY_PLAYLIST_URL = /^https:\/\/open\.spotify\.com\/playlist\/[a-zA-Z0-9]+\/?(\?[A-Za-z0-9_.~%=&-]*)?$/;

/** Parse a capped JSON body. Returns a plain object, or null if it is not one. */
async function beReadJsonObject(request) {
  const raw = await request.text();
  if (raw.length > BE_MAX_BODY_CHARS) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Cap by code point, so an emoji is never cut into half a surrogate pair. */
function beCap(s, max) {
  return Array.from(s).slice(0, max).join('');
}

function beClean(value, max) {
  return beCap(String(value == null ? '' : value).replace(BE_UNSAFE_CHARS, ' ').trim(), max);
}

/** Text for an issue BODY. qzEsc covers mentions, #refs, tables and Markdown
 *  links; this adds what it leaves open: raw HTML (an <img> renders), entities,
 *  emphasis, bare-URL autolinks and GH-123 refs. Callers cap at 240 or less, so
 *  qzEsc's own 500-unit slice can never cut an escape in half. */
function beEsc(value, max) {
  return qzEsc(beClean(value, max))
    .replace(/&(?=#?\w+;)/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/[*_~]/g, '\\$&')
    .replace(/:\/\//g, ':\u200B//')
    .replace(/\bwww\./gi, (m) => `${m.slice(0, 3)}\u200B.`)
    .replace(/\bGH-(?=\d)/gi, '$&\u200B');
}

/** Text for an issue TITLE. GitHub does not render Markdown there, so backslash
 *  escapes would show up literally and "Song (Live)" would read "Song \(Live\)".
 *  Only what is live in a title is touched: refs, mentions and code spans. */
function beTitleText(value, max) {
  return beClean(value, max)
    .replace(/`/g, "'")
    .replace(/@/g, '@\u200B')
    .replace(/#(?=\d)/g, '#\u200B')
    .replace(/\bGH-(?=\d)/gi, '$&\u200B');
}

/** Required song text: a non-blank string, or a number (hand-written custom
 *  playlists are not schema-checked and may carry a title like 1979). */
function beIsSongText(value) {
  if (typeof value === 'number') return Number.isFinite(value);
  return typeof value === 'string' && beClean(value, BE_MAX_ARTIST) !== '';
}

/** Returns the year as display text, or null if malformed. The range is wider
 *  than the playlist schema (1900-2100) on purpose: this route exists to report
 *  wrong years, so an absurd but well-formed one must still get through. */
function beYearText(year) {
  if (year === undefined || year === null) return '?';
  if (typeof year === 'number') {
    return Number.isInteger(year) && year >= 0 && year <= 9999 ? String(year) : null;
  }
  return typeof year === 'string' && /^\d{1,4}$/.test(year) ? year : null;
}

/** Returns the playlist file, or null if malformed. Installed clients send a
 *  relative path or an absolute one (/config/beatify/playlists/...), on any OS,
 *  with any file name, plus the fallbacks below. The value is rendered inside a
 *  code span, so only what could leave that span or break the table is refused. */
function bePlaylistFile(value) {
  if (value === undefined || value === null) return 'unknown';
  if (typeof value !== 'string') return null;
  if (value === 'unknown' || value === 'library') return value;
  if (Array.from(value).length > BE_MAX_PLAYLIST_FILE) return null;
  if (beClean(value, BE_MAX_PLAYLIST_FILE) !== value) return null;
  return /^[^`|<>"*?]+\.json$/.test(value) ? value : null;
}

function beReportTitle(artist, title) {
  return beCap(`data: wrong year reported \u2014 ${artist} \u2013 ${title}`, BE_MAX_ISSUE_TITLE);
}

/** Find an open report of the same song from the same playlist file. Compares the
 *  file name only, because the same playlist has a different absolute path on
 *  each install. Fails open: an error here must never lose a player's report. */
async function beFindOpenReport(env, issueTitle, artist, title, playlistFile) {
  try {
    const terms = beCap(
      `${artist} ${title}`.replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim(),
      BE_MAX_SEARCH_TERMS
    );
    const q = `repo:mholzi/beatify is:issue is:open label:data-quality in:title ${terms}`;
    const res = await fetch(
      `https://api.github.com/search/issues?per_page=30&q=${encodeURIComponent(q)}`,
      {
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'Beatify-Bot',
        },
      }
    );
    if (!res.ok) return null;
    const data = await res.json();
    const fileName = playlistFile.split(/[\\/]/).pop();
    return (data.items || []).find(
      (item) => item.title === issueTitle && String(item.body || '').includes(`${fileName}\``)
    ) || null;
  } catch {
    return null;
  }
}

/** Only an image on Spotify's own CDN may be embedded in a public issue. */
function beSpotifyThumbnail(value) {
  if (typeof value !== 'string' || /[()\s]/.test(value)) return null;
  try {
    const parsed = new URL(value);
    const onCdn = /(^|\.)(scdn\.co|spotifycdn\.com)$/.test(parsed.hostname);
    return parsed.protocol === 'https:' && onCdn ? value : null;
  } catch {
    return null;
  }
}

async function handleReportData(request, env, corsHeaders) {
  // No browser calls this route: the guest's phone talks to Home Assistant over
  // a WebSocket and HA posts from the server, which always sends this type
  // (aiohttp json=). Dropping CORS alone would not stop a web page from SENDING
  // a form-encoded POST; requiring JSON forces a preflight, and that now fails.
  const contentType = (request.headers.get('Content-Type') || '').toLowerCase();
  if (!contentType.startsWith('application/json')) {
    return Response.json({ success: false, error: 'INVALID_CONTENT_TYPE' }, { status: 415, headers: corsHeaders });
  }
  const body = await beReadJsonObject(request);
  if (!body) {
    return Response.json({ success: false, error: 'INVALID_JSON' }, { status: 400, headers: corsHeaders });
  }
  if (!beIsSongText(body.artist) || !beIsSongText(body.title)) {
    return Response.json({ success: false, error: 'MISSING_FIELDS' }, { status: 400, headers: corsHeaders });
  }
  const yearText = beYearText(body.year);
  const playlistFile = bePlaylistFile(body.playlist_file);
  if (yearText === null || playlistFile === null) {
    return Response.json({ success: false, error: 'INVALID_FIELDS' }, { status: 400, headers: corsHeaders });
  }
  if (body.reporter !== undefined && body.reporter !== null && typeof body.reporter !== 'string') {
    return Response.json({ success: false, error: 'INVALID_FIELDS' }, { status: 400, headers: corsHeaders });
  }
  const songArtist = beEsc(body.artist, BE_MAX_ARTIST);
  const songTitle = beEsc(body.title, BE_MAX_SONG_TITLE);
  const reporter = beEsc(body.reporter, BE_MAX_REPORTER) || 'unknown';

  const issueTitle = beReportTitle(
    beTitleText(body.artist, BE_MAX_ARTIST),
    beTitleText(body.title, BE_MAX_SONG_TITLE)
  );
  const existing = await beFindOpenReport(
    env, issueTitle, beClean(body.artist, BE_MAX_ARTIST), beClean(body.title, BE_MAX_SONG_TITLE), playlistFile
  );
  if (existing) {
    return Response.json({ success: true, existing: true, issue_number: existing.number }, { headers: corsHeaders });
  }

  const issueBody = [
    '## Wrong Year Report', '', 'A player flagged incorrect data during a game.', '',
    '| Field | Value |', '|-------|-------|',
    `| **Song** | ${songArtist} \u2013 ${songTitle} |`,
    `| **Year in playlist** | ${yearText} |`,
    `| **Playlist file** | \`${playlistFile}\` |`,
    `| **Reported by** | ${reporter} |`, '',
    '### Next steps', `Look up the correct release year and update \`${playlistFile}\`.`,
    '', '---', '*Auto-reported by Beatify in-game data quality flag (Issue #911)*',
  ].join('\n');
  const ghRes = await fetch('https://api.github.com/repos/mholzi/beatify/issues', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GITHUB_PAT}`,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'Beatify-Bot',
    },
    body: JSON.stringify({ title: issueTitle, body: issueBody, labels: ['data-quality'] }),
  });
  if (!ghRes.ok) {
    console.error('GitHub API error:', await ghRes.text());
    return Response.json(
      { success: false, error: 'github_error', message: 'Failed to create issue' },
      { status: 500, headers: corsHeaders }
    );
  }
  const issue = await ghRes.json();
  return Response.json({ success: true, issue_number: issue.number }, { headers: corsHeaders });
}


// ===========================================================================
// Quizify community-pack submission (additive - Beatify logic above/below is
// untouched). Mounted on any path starting with `/quizify` (e.g.
// `/quizify/submit-pack`). Self-contained: own secret gate, own GitHub repo,
// own (no-)CORS policy. Ported from the standalone quizify-api worker so both
// HA integrations can share one deployed Worker.
//   Secrets:  SHARED_SECRET        (REQUIRED - fail-closed gate, #292/#316)
//             QUIZIFY_GITHUB_PAT   (Issues R+W on mholzi/quizify; falls back to
//                                   GITHUB_PAT if that token also covers quizify)
// ===========================================================================
const QUIZIFY_REPO = 'mholzi/quizify';
const QUIZIFY_ISSUES_API = `https://api.github.com/repos/${QUIZIFY_REPO}/issues`;
const QZ_MAX_QUESTIONS = 500;
const QZ_MIN_QUESTIONS = 1;
const QZ_ANSWERS_PER_QUESTION = 3;
const QZ_MAX_BYTES = 1_048_576; // 1 MiB
// No CORS: the Quizify HA integration calls server-side (aiohttp), never from a
// browser, so we emit no ACAO header (#292).
const QZ_CORS = {};

function qzJsonError(code, message, status) {
  return Response.json({ code, message }, { status, headers: QZ_CORS });
}

/** Constant-time string compare (#292): equal-length UTF-8 buffers via
 *  crypto.subtle.timingSafeEqual; a length mismatch is an immediate non-match. */
function qzTimingSafeEqualStr(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const enc = new TextEncoder();
  const bufA = enc.encode(a);
  const bufB = enc.encode(b);
  if (bufA.byteLength !== bufB.byteLength) return false;
  return crypto.subtle.timingSafeEqual(bufA, bufB);
}

/** Validate the pack against the #179 schema - mirrors
 *  server/pack_submission.py::validate_pack exactly. */
function qzValidatePack(pack) {
  if (!pack || typeof pack !== 'object' || Array.isArray(pack)) return 'Top-level JSON must be an object.';
  if (typeof pack.name !== 'string' || !pack.name.trim()) return "Field 'name' is required.";
  const lang = pack.language === undefined ? 'de' : pack.language;
  if (typeof lang !== 'string' || !lang.trim()) return "Field 'language' must be a non-empty string.";
  const qs = pack.questions;
  if (!Array.isArray(qs) || qs.length < QZ_MIN_QUESTIONS) return "Field 'questions' must be a non-empty list.";
  if (qs.length > QZ_MAX_QUESTIONS) return `Too many questions (max ${QZ_MAX_QUESTIONS}).`;
  const seenIds = new Set();
  for (let i = 0; i < qs.length; i++) {
    const q = qs[i];
    const p = `Question ${i + 1}`;
    if (!q || typeof q !== 'object') return `${p}: must be an object.`;
    if (typeof q.id !== 'string' || !q.id.trim()) return `${p}: 'id' is required.`;
    if (seenIds.has(q.id)) return `${p}: duplicate id '${q.id}'.`;
    seenIds.add(q.id);
    if (typeof q.question !== 'string' || !q.question.trim()) return `${p}: 'question' is required.`;
    if (!Array.isArray(q.answers) || q.answers.length !== QZ_ANSWERS_PER_QUESTION) {
      return `${p}: exactly ${QZ_ANSWERS_PER_QUESTION} answers are required.`;
    }
    let correct = 0;
    for (const a of q.answers) {
      if (!a || typeof a !== 'object') return `${p}: each answer must be an object.`;
      if (typeof a.text !== 'string' || !a.text.trim()) return `${p}: every answer needs non-empty 'text'.`;
      if (a.correct === true) correct += 1;
    }
    if (correct !== 1) return `${p}: exactly 1 answer must be marked correct (got ${correct}).`;
  }
  return null;
}

/** Neutralise Markdown / mention injection in user strings going into the issue
 *  (#305): break @mentions and #refs, escape table/code + link/image controls,
 *  collapse newlines. Escape backslash-family first, then the link/image set. */
function qzEsc(s) {
  return String(s == null ? '' : s)
    .replace(/[\r\n]+/g, ' ')
    .replace(/[`|\\]/g, '\\$&')
    .replace(/[[\]()!]/g, '\\$&')
    .replace(/@/g, '@\u200B')
    .replace(/#(?=\d)/g, '#\u200B')
    .slice(0, 500);
}

function qzBuildIssue(pack) {
  const qs = pack.questions || [];
  const title = `pack: ${qzEsc(pack.name)} (${qzEsc(pack.language || 'de')}) \u2014 ${qs.length} questions`;
  const lines = [
    '## Community pack submission', '',
    'A host submitted a community question pack from the in-app composer.', '',
    '| Field | Value |', '|-------|-------|',
    `| **Name** | ${qzEsc(pack.name)} |`,
    `| **Language** | ${qzEsc(pack.language || 'de')} |`,
    `| **Questions** | ${qs.length} |`,
    '', '### Questions', '',
  ];
  qs.forEach((q, i) => {
    lines.push(`**${i + 1}. ${qzEsc(q.question)}**`);
    (q.answers || []).forEach((a) => {
      lines.push(`- ${a && a.correct === true ? '\u2705 ' : ''}${qzEsc(a && a.text)}`);
    });
    lines.push('');
  });
  lines.push('---', '*Auto-filed by the Quizify in-app community-pack submission (#180).*');
  return { title: title.slice(0, 250), body: lines.join('\n'), labels: ['community-pack'] };
}

async function handleQuizifySubmit(request, env) {
  const pat = env.QUIZIFY_GITHUB_PAT || env.GITHUB_PAT;
  if (!pat) {
    return qzJsonError('GITHUB_ERROR', 'Worker is missing its GitHub PAT secret.', 500);
  }
  // Shared-secret gate - FAIL CLOSED (#292/#316): reject 401 if SHARED_SECRET is
  // unset OR the X-Quizify-Secret header is missing / doesn't match. The worker
  // must never be an open, unauthenticated proxy that files issues with the PAT.
  if (!env.SHARED_SECRET) {
    return qzJsonError('INVALID_FORMAT', 'Unauthorized.', 401);
  }
  const presented = request.headers.get('X-Quizify-Secret');
  if (!qzTimingSafeEqualStr(presented, env.SHARED_SECRET)) {
    return qzJsonError('INVALID_FORMAT', 'Unauthorized.', 401);
  }

  const raw = await request.text();
  if (raw.length > QZ_MAX_BYTES) return qzJsonError('INVALID_FORMAT', `Pack exceeds ${QZ_MAX_BYTES} bytes.`, 400);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return qzJsonError('INVALID_FORMAT', 'Body is not valid JSON.', 400);
  }
  const pack = body && typeof body === 'object' ? body.pack : null;
  const err = qzValidatePack(pack);
  if (err) return qzJsonError('INVALID_FORMAT', err, 400);

  const issue = qzBuildIssue(pack);
  const ghRes = await fetch(QUIZIFY_ISSUES_API, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${pat}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'Quizify-PackBot',
    },
    body: JSON.stringify(issue),
  });
  if (!ghRes.ok) {
    console.error('Quizify GitHub API error:', ghRes.status, await ghRes.text());
    return qzJsonError('GITHUB_ERROR', `Failed to create issue (HTTP ${ghRes.status}).`, 502);
  }
  const created = await ghRes.json();
  return Response.json({ issue_number: created.number, issue_url: created.html_url }, { headers: QZ_CORS });
}

export default {
  async fetch(request, env) {
    // Quizify community-pack route (additive). Fully self-contained - owns its
    // method guard, secret gate and (no-)CORS - so every non-/quizify request
    // falls through to the Beatify handling below byte-for-byte as before.
    const qzUrl = new URL(request.url);
    if (qzUrl.pathname.startsWith('/quizify')) {
      if (request.method !== 'POST') return qzJsonError('INVALID_FORMAT', 'POST only.', 405);
      try {
        return await handleQuizifySubmit(request, env);
      } catch (e) {
        console.error('Quizify worker error:', e);
        return qzJsonError('GITHUB_ERROR', 'Unexpected worker error.', 500);
      }
    }

    // /report-data has no browser caller, so it gets no CORS headers (#2688). The
    // playlist-request route is called from www/js/playlist-requests.js on each
    // host's own origin, which no allow-list can name, so it keeps the wildcard.
    const isReportData = qzUrl.pathname.endsWith('/report-data');
    const corsHeaders = isReportData ? {} : {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    if (request.method !== 'POST') {
      return Response.json({ error: 'POST only' }, { status: 405, headers: corsHeaders });
    }
    if (isReportData) {
      try {
        return await handleReportData(request, env, corsHeaders);
      } catch (e) {
        console.error('Worker error:', e);
        return Response.json({ success: false, error: 'server_error' }, { status: 500 });
      }
    }

    try {
      const requestBody = await beReadJsonObject(request);
      const spotify_url = requestBody ? requestBody.spotify_url : null;

      // Validate URL format. The query stays allowed: Spotify's share links carry
      // ?si=... or ?pi=..., and installed clients send them as pasted.
      if (
        typeof spotify_url !== 'string' ||
        spotify_url.length > BE_MAX_SPOTIFY_URL ||
        !BE_SPOTIFY_PLAYLIST_URL.test(spotify_url)
      ) {
        return Response.json(
          { success: false, error: 'invalid_format', message: 'Invalid Spotify playlist URL format' },
          { status: 400, headers: corsHeaders }
        );
      }

      // Validate playlist exists using Spotify oEmbed API (no auth required)
      const oembedRes = await fetch(
        `https://open.spotify.com/oembed?url=${encodeURIComponent(spotify_url)}`,
        { headers: { 'User-Agent': 'Beatify-Bot/1.0' } }
      );

      if (!oembedRes.ok) {
        return Response.json(
          { success: false, error: 'playlist_not_found', message: 'Playlist not found or is private' },
          { status: 404, headers: corsHeaders }
        );
      }

      const oembedData = await oembedRes.json();
      // Whoever creates a public Spotify playlist chooses this name, so it is as
      // untrusted as the request itself. Raw for the caller's own UI, escaped for
      // the issue.
      const display_name =
        (typeof oembedData.title === 'string' && beClean(oembedData.title, BE_MAX_PLAYLIST_NAME)) || 'Custom Playlist';
      const playlist_name = beTitleText(display_name, BE_MAX_PLAYLIST_NAME);
      const thumbnail_url = beSpotifyThumbnail(oembedData.thumbnail_url);

      // Check for duplicate request
      const searchRes = await fetch(
        `https://api.github.com/search/issues?q=repo:mholzi/beatify+"${encodeURIComponent(spotify_url)}"+label:playlist-request`,
        { headers: { 'Authorization': `Bearer ${env.GITHUB_PAT}`, 'User-Agent': 'Beatify-Bot' } }
      );
      const searchData = await searchRes.json();

      if (searchData.total_count > 0) {
        const existing = searchData.items[0];
        return Response.json({
          success: true,
          existing: true,
          issue_number: existing.number,
          issue_url: existing.html_url,
          playlist_name: display_name,
          message: 'This playlist was already requested'
        }, { headers: corsHeaders });
      }

      // Create GitHub issue
      const issueBody = `## \u{1F3B5} Playlist Request

**Playlist:** ${beEsc(display_name, BE_MAX_PLAYLIST_NAME)}
**Spotify URL:** ${spotify_url}
**Requested:** ${new Date().toISOString()}

${thumbnail_url ? `![Playlist Cover](${thumbnail_url})` : ''}

---

### Enrichment Checklist

- [ ] Fetch tracks from Spotify API
- [ ] Enrich with iTunes API (release years)
- [ ] Add alt_artists via Last.fm
- [ ] Generate fun_facts (optional)
- [ ] Add to \`playlists/community/\`
- [ ] Include in next release

**When complete:**
1. Add label \`playlist-ready\`
2. Add label with release version (e.g., \`v2.3.0\`)
3. Close issue`;

      const issueRes = await fetch('https://api.github.com/repos/mholzi/beatify/issues', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'User-Agent': 'Beatify-Bot',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: `\u{1F3B5} Playlist Request: ${playlist_name}`,
          body: issueBody,
          labels: ['playlist-request'],
        }),
      });

      if (!issueRes.ok) {
        const errorText = await issueRes.text();
        console.error('GitHub API error:', errorText);
        return Response.json(
          { success: false, error: 'github_error', message: 'Failed to create request' },
          { status: 500, headers: corsHeaders }
        );
      }

      const issue = await issueRes.json();
      return Response.json({
        success: true,
        issue_number: issue.number,
        issue_url: issue.html_url,
        playlist_name: display_name,
        thumbnail_url: thumbnail_url,
        message: 'Request submitted successfully'
      }, { headers: corsHeaders });

    } catch (e) {
      console.error('Worker error:', e);
      return Response.json(
        { success: false, error: 'server_error', message: 'Something went wrong' },
        { status: 500, headers: corsHeaders }
      );
    }
  },
};
