/**
 * #2688: the Cloudflare worker files public issues with the maintainer's token
 * from unauthenticated requests, so nothing a caller sends may be live in them.
 * GitHub and Spotify are stubbed; no test touches the network.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../../../../../cf-workers/beatify-api.js';

const ENV = { GITHUB_PAT: 'test-token' };
const ZWSP = '\u200B';
let created;
let searchItems;
let searchOk;
let oembed;

function post(path, payload, headers = { 'Content-Type': 'application/json' }) {
    const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
    return worker.fetch(new Request(`https://w.example${path}`, { method: 'POST', headers, body }), ENV);
}

const report = (over = {}) => post('/report-data', {
    artist: 'Muse',
    title: 'Uprising',
    year: 2009,
    playlist_file: 'playlists/rock.json',
    reporter: 'Anna',
    ...over,
});

beforeEach(() => {
    created = [];
    searchItems = [];
    searchOk = true;
    oembed = { title: 'Roadtrip', thumbnail_url: 'https://image-cdn-ak.spotifycdn.com/image/abc' };
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
        const u = String(url);
        if (u.includes('/search/issues')) {
            return Response.json({ total_count: searchItems.length, items: searchItems }, { status: searchOk ? 200 : 403 });
        }
        if (u.includes('open.spotify.com/oembed')) return Response.json(oembed);
        created.push(JSON.parse(init.body));
        return Response.json({ number: 42, html_url: 'https://github.com/x/y/issues/42' });
    }));
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('/report-data contract automation relies on', () => {
    it('keeps the title prefix, label and body rows for a normal report', async () => {
        const res = await report();
        expect(res.status).toBe(200);
        expect(await res.json()).toEqual({ success: true, issue_number: 42 });
        expect(created).toHaveLength(1);
        expect(created[0].title).toBe('data: wrong year reported \u2014 Muse \u2013 Uprising');
        expect(created[0].labels).toEqual(['data-quality']);
        expect(created[0].body).toContain('| **Year in playlist** | 2009 |');
        expect(created[0].body).toContain('| **Playlist file** | `playlists/rock.json` |');
    });

    it('leaves real song names readable in the title', async () => {
        await report({ artist: 'Simon & Garfunkel', title: "Tu t'en vas (Live) \u2013 P!nk" });
        expect(created[0].title).toContain("Simon & Garfunkel \u2013 Tu t'en vas (Live) \u2013 P!nk");
    });

    it('keeps a no-break space from a real artist credit', async () => {
        await report({ artist: 'Vladimir Cosma,\u00A0Guy Marchand' });
        expect(created[0].title).toContain('Cosma,\u00A0Guy');
    });

    it.each([
        ['absolute path as sent by installed clients', '/config/beatify/playlists/community/hitster-100-francais.json'],
        ['relative path', 'community/80er hits.json'],
        ['non-ASCII file name', 'community/m\u00FCsik.json'],
        ['windows path', 'C:\\ha\\beatify\\p.json'],
        ['fallback', 'unknown'],
        ['library fallback', 'library'],
    ])('accepts playlist_file: %s', async (_name, file) => {
        expect((await report({ playlist_file: file })).status).toBe(200);
    });

    it.each([[null, '?'], [undefined, '?'], [1984, '1984'], [1984.0, '1984'], ['1999', '1999'], [2099, '2099'], [0, '0']])(
        'accepts year %s, including wrong ones, since that is the point of the route',
        async (year, shown) => {
            expect((await report({ year })).status).toBe(200);
            expect(created[0].body).toContain(`| **Year in playlist** | ${shown} |`);
        }
    );
});

describe('/report-data neutralises what a caller sends', () => {
    it.each(['artist', 'title'])('%s cannot mention, link, embed or break the table', async (field) => {
        const hostile = '@someone #123 GH-77 [x](https://e.example) ![i](https://e.example/a.png) <img src=x> a|b `c` *d* www.e.example &#64;f &commat;g\nline';
        await report({ [field]: hostile });
        const row = created[0].body.split('\n').find((l) => l.startsWith('| **Song**'));
        expect(row).toContain(`@${ZWSP}someone`);
        expect(row).toContain(`#${ZWSP}123`);
        expect(row).toContain(`GH-${ZWSP}77`);
        expect(row).toContain('\\[x\\]\\(https:');
        expect(row).toContain('\\!\\[i\\]');
        expect(row).toContain(`:${ZWSP}//`);
        expect(row).toContain('&lt;img');
        expect(row).not.toContain('<img');
        expect(row).toContain('a\\|b');
        expect(row).toContain('\\`c\\`');
        expect(row).toContain('\\*d\\*');
        expect(row).toContain(`www${ZWSP}.e`);
        expect(row).toContain(`&#${ZWSP}64;`);
        expect(row).toContain('&amp;commat;');
        expect(created[0].body.split('\n')).toHaveLength(16); // the newline did not add a row
    });

    it('reporter, the field a party guest types, cannot mention, embed or break the table', async () => {
        await report({ reporter: '@someone <img src=x> a|b\nc' });
        expect(created[0].body).toContain(`| **Reported by** | @${ZWSP}someone &lt;img src=x&gt; a\\|b c |`);
    });

    it('neutralises mentions and refs in the title without visible backslashes', async () => {
        await report({ artist: '@someone', title: '#123 `x`\nnext' });
        expect(created[0].title).toContain(`@${ZWSP}someone`);
        expect(created[0].title).toContain(`#${ZWSP}123`);
        expect(created[0].title).not.toContain('`');
        expect(created[0].title).not.toContain('\n');
        expect(created[0].title).not.toContain('\\');
    });

    it('strips bidi overrides', async () => {
        await report({ reporter: 'a\u202Eb' });
        expect(created[0].body).not.toContain('\u202E');
    });

    it('caps fields and keeps the title under the GitHub limit', async () => {
        await report({ artist: 'a'.repeat(5000), title: 'b'.repeat(5000), reporter: 'c'.repeat(5000) });
        expect(created[0].title.length).toBeLessThanOrEqual(250);
        expect(created[0].body).not.toContain('a'.repeat(201));
        expect(created[0].body).not.toContain('c'.repeat(41));
    });

    it('does not cut an emoji in half at the cap', async () => {
        await report({ artist: '\u{1F3B5}'.repeat(300) });
        expect(created[0].title.isWellFormed()).toBe(true);
    });
});

describe('/report-data rejects malformed input before touching GitHub', () => {
    it.each([
        ['invalid JSON', '{nope'],
        ['JSON null', 'null'],
        ['JSON array', '[]'],
        ['oversized body', JSON.stringify({ artist: 'a', title: 'b', x: 'y'.repeat(20000) })],
    ])('%s', async (_name, raw) => {
        expect((await post('/report-data', raw)).status).toBe(400);
        expect(fetch).not.toHaveBeenCalled();
    });

    it.each([
        ['missing artist', { artist: undefined }],
        ['blank title', { title: '   ' }],
        ['object artist', { artist: { a: 1 } }],
        ['array title', { title: ['x'] }],
        ['year text', { year: 'nineteen' }],
        ['year too long', { year: 12345 }],
        ['year fraction', { year: 1984.5 }],
        ['year bool', { year: true }],
        ['file not json', { playlist_file: 'a.txt' }],
        ['file with backtick', { playlist_file: 'a`b.json' }],
        ['file with pipe', { playlist_file: 'a|b.json' }],
        ['file with newline', { playlist_file: 'a\nb.json' }],
        ['file too long', { playlist_file: `${'a'.repeat(400)}.json` }],
        ['file object', { playlist_file: {} }],
        ['reporter object', { reporter: {} }],
    ])('%s', async (_name, over) => {
        expect((await report(over)).status).toBe(400);
        expect(fetch).not.toHaveBeenCalled();
    });
});

describe('/report-data has no browser surface', () => {
    it('sends no CORS headers on POST or preflight', async () => {
        expect((await report()).headers.get('Access-Control-Allow-Origin')).toBeNull();
        const pre = await worker.fetch(new Request('https://w.example/report-data', { method: 'OPTIONS' }), ENV);
        expect(pre.headers.get('Access-Control-Allow-Origin')).toBeNull();
    });

    it('refuses the form-encoded POST a web page can send without a preflight', async () => {
        const res = await post('/report-data', { artist: 'a', title: 'b' }, { 'Content-Type': 'text/plain' });
        expect(res.status).toBe(415);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('accepts a charset suffix', async () => {
        const res = await post('/report-data', { artist: 'a', title: 'b' }, { 'Content-Type': 'application/json; charset=utf-8' });
        expect(res.status).toBe(200);
    });
});

describe('/report-data duplicate guard', () => {
    const title = 'data: wrong year reported \u2014 Muse \u2013 Uprising';

    it('reuses an open report of the same song and playlist file across installs', async () => {
        searchItems = [{ number: 7, title, body: '| **Playlist file** | `/config/beatify/playlists/rock.json` |' }];
        const res = await report();
        expect(await res.json()).toEqual({ success: true, existing: true, issue_number: 7 });
        expect(created).toHaveLength(0);
    });

    it('files when the song matches but the playlist file differs', async () => {
        searchItems = [{ number: 7, title, body: '`playlists/pop.json`' }];
        await report();
        expect(created).toHaveLength(1);
    });

    it('files when the search only found a similar title', async () => {
        searchItems = [{ number: 7, title: `${title} (Live)`, body: '`playlists/rock.json`' }];
        await report();
        expect(created).toHaveLength(1);
    });

    it('fails open so a search outage never loses a report', async () => {
        searchOk = false;
        expect((await report()).status).toBe(200);
        expect(created).toHaveLength(1);
    });

    it('keeps the search query inside the GitHub length limit', async () => {
        await report({ artist: 'a '.repeat(200), title: 'b '.repeat(200) });
        const q = new URL(fetch.mock.calls[0][0]).searchParams.get('q');
        expect(q.length).toBeLessThanOrEqual(256);
    });
});

describe('playlist-request route', () => {
    const URL_OK = 'https://open.spotify.com/playlist/31j4SWqROfsFS2jT44Td1i';

    it.each([
        URL_OK,
        `${URL_OK}?si=a8272e7aaaf04802`,
        `${URL_OK}?pi=LsruxkavT42xl`,
        `${URL_OK}/`,
        `${URL_OK}?si=a_b-c&utm_source=copy-link`,
    ])('accepts the share link %s', async (spotify_url) => {
        const res = await post('/', { spotify_url });
        expect(res.status).toBe(200);
        expect(created[0].body).toContain(`**Spotify URL:** ${spotify_url}\n`);
    });

    it.each([
        ['trailing payload', `${URL_OK} @someone`],
        ['trailing markdown', `${URL_OK})![x](https://e.example/a.png)`],
        ['newline', `${URL_OK}\n@someone`],
        ['extra path', `${URL_OK}/../../x`],
        ['array that stringifies to a valid URL', [URL_OK]],
        ['too long', `${URL_OK}?si=${'a'.repeat(400)}`],
        ['missing', undefined],
    ])('rejects %s', async (_name, spotify_url) => {
        const res = await post('/', { spotify_url });
        expect(res.status).toBe(400);
        expect((await res.json()).error).toBe('invalid_format');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('answers invalid JSON with 400 rather than 500', async () => {
        expect((await post('/', '{nope')).status).toBe(400);
    });

    it('keeps CORS for the browser caller', async () => {
        const res = await post('/', { spotify_url: URL_OK });
        expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*');
    });

    it('escapes the Spotify-side playlist name in the issue, not for the caller', async () => {
        oembed.title = '@someone <img src=x> #5';
        const res = await post('/', { spotify_url: URL_OK });
        expect(created[0].title).toContain(`@${ZWSP}someone`);
        expect(created[0].title).toContain(`#${ZWSP}5`);
        expect(created[0].body).toContain(`**Playlist:** @${ZWSP}someone &lt;img src=x&gt; #${ZWSP}5`);
        expect((await res.json()).playlist_name).toBe('@someone <img src=x> #5');
    });

    it.each([
        'https://e.example/a.png',
        'http://i.scdn.co/a',
        'https://i.scdn.co/a) [x](https://e.example',
        'https://scdn.co.e.example/a',
    ])('does not embed the thumbnail %s', async (thumb) => {
        oembed.thumbnail_url = thumb;
        await post('/', { spotify_url: URL_OK });
        expect(created[0].body).not.toContain('![Playlist Cover]');
    });

    it('still embeds a Spotify CDN thumbnail', async () => {
        await post('/', { spotify_url: URL_OK });
        expect(created[0].body).toContain('![Playlist Cover](https://image-cdn-ak.spotifycdn.com/image/abc)');
    });

    it('keeps the issue label', async () => {
        await post('/', { spotify_url: URL_OK });
        expect(created[0].labels).toEqual(['playlist-request']);
    });
});

describe('Quizify route stays gated', () => {
    it('is refused without the shared secret', async () => {
        const res = await post('/quizify/submit-pack', { pack: {} });
        expect(res.status).toBe(401);
        expect(fetch).not.toHaveBeenCalled();
    });
});
