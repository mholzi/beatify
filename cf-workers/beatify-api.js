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


export default {
  async fetch(request, env) {
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
