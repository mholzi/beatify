async function handleReportData(request, env, corsHeaders) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ success: false, error: 'INVALID_JSON' }, { status: 400, headers: corsHeaders });
  }
  const { artist, title, year, playlist_file, reporter } = body;
  if (!artist || !title) {
    return Response.json({ success: false, error: 'MISSING_FIELDS' }, { status: 400, headers: corsHeaders });
  }
  const issueTitle = `data: wrong year reported — ${artist} – ${title}`;
  const issueBody = [
    '## Wrong Year Report', '', 'A player flagged incorrect data during a game.', '',
    '| Field | Value |', '|-------|-------|',
    `| **Song** | ${artist} – ${title} |`,
    `| **Year in playlist** | ${year ?? '?'} |`,
    `| **Playlist file** | \`${playlist_file}\` |`,
    `| **Reported by** | ${reporter} |`, '',
    '### Next steps', `Look up the correct release year and update \`${playlist_file}\`.`,
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
// Quizify community-pack submission (additive — Beatify logic above/below is
// untouched). Mounted on any path starting with `/quizify` (e.g.
// `/quizify/submit-pack`). Self-contained: own secret gate, own GitHub repo,
// own (no-)CORS policy. Ported from the standalone quizify-api worker so both
// HA integrations can share one deployed Worker.
//   Secrets:  SHARED_SECRET        (REQUIRED — fail-closed gate, #292/#316)
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

/** Validate the pack against the #179 schema — mirrors
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
    .replace(/@/g, '@​')
    .replace(/#(?=\d)/g, '#​')
    .slice(0, 500);
}

function qzBuildIssue(pack) {
  const qs = pack.questions || [];
  const title = `pack: ${qzEsc(pack.name)} (${qzEsc(pack.language || 'de')}) — ${qs.length} questions`;
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
      lines.push(`- ${a && a.correct === true ? '✅ ' : ''}${qzEsc(a && a.text)}`);
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
  // Shared-secret gate — FAIL CLOSED (#292/#316): reject 401 if SHARED_SECRET is
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
    // Quizify community-pack route (additive). Fully self-contained — owns its
    // method guard, secret gate and (no-)CORS — so every non-/quizify request
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

    const corsHeaders = {
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
    const url = new URL(request.url);
    if (url.pathname.endsWith('/report-data')) {
      return handleReportData(request, env, corsHeaders);
    }

    try {
      const { spotify_url } = await request.json();

      // Validate URL format
      if (!/^https:\/\/open\.spotify\.com\/playlist\/[a-zA-Z0-9]+/.test(spotify_url)) {
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
      const playlist_name = oembedData.title || 'Custom Playlist';
      const thumbnail_url = oembedData.thumbnail_url || null;

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
          playlist_name: playlist_name,
          message: 'This playlist was already requested'
        }, { headers: corsHeaders });
      }

      // Create GitHub issue
      const issueBody = `## 🎵 Playlist Request

**Playlist:** ${playlist_name}
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
          title: `🎵 Playlist Request: ${playlist_name}`,
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
        playlist_name: playlist_name,
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
