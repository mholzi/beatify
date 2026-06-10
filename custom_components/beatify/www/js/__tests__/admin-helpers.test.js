/**
 * Smoke-test safety net for the pure helpers in admin.js (#1279, Schritt 1/6).
 *
 * admin.js (4428 lines) is a classic global script with ZERO test coverage and
 * is slated for a 6-step modularisation. Step 1 (this file) pins down the
 * behaviour of the small, side-effect-free helper functions BEFORE any code is
 * moved, so the later extraction into `admin/util.js` / `admin/api.js` can be
 * verified against a green baseline.
 *
 * The helpers are not exported (admin.js stays untouched in step 1), so their
 * source text is lifted out of admin.js at runtime and eval'd in an isolated
 * scope — see admin-helpers-loader.js. The tests run the exact production
 * source.
 *
 * Helpers covered:
 *   - _getAdminToken()           (token resolution: per-game → global → null)
 *   - _setAdminToken(t, gameId)  (persistence to localStorage + sessionStorage cleanup)
 *   - _adminHeaders()            (REST header builder, Bearer iff token present)
 *   - groupPlayersByPlatform()   (pure grouping)
 *   - escapeHtml()               (XSS escaping via DOM textContent)
 *   - buildRequestRowHtml()      (request-card HTML, status-label lookup, escaping)
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { loadHelpers } from './admin-helpers-loader.js';

// --- minimal localStorage / sessionStorage stub ----------------------------
function makeStorage() {
    const map = new Map();
    return {
        getItem: (k) => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => { map.set(k, String(v)); },
        removeItem: (k) => { map.delete(k); },
        _map: map,
    };
}

// --- minimal document stub for escapeHtml (textContent → innerHTML) --------
// Mirrors the browser's HTML-escaping of textContent for the characters the
// helper guards against (&, <, >). Quotes are NOT escaped by textContent in a
// real browser, so we don't escape them here either.
function makeDocumentStub() {
    return {
        createElement() {
            const el = {
                _text: '',
                set textContent(v) { el._text = v == null ? '' : String(v); },
                get innerHTML() {
                    return el._text
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;');
                },
            };
            return el;
        },
    };
}

describe('admin.js pure helpers — token + headers (#1279 step 1)', () => {
    let localStorage;
    let sessionStorage;

    function load(currentGame) {
        return loadHelpers({
            functions: ['_getAdminToken', '_setAdminToken', '_adminHeaders'],
            globals: { currentGame, localStorage, sessionStorage },
        });
    }

    beforeEach(() => {
        localStorage = makeStorage();
        sessionStorage = makeStorage();
    });

    it('_getAdminToken returns null when nothing is stored', () => {
        const { _getAdminToken } = load({ game_id: 'g1' });
        expect(_getAdminToken()).toBeNull();
    });

    it('_getAdminToken prefers the per-game token over the global token', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        localStorage.setItem('beatify_admin_token_g1', 'PERGAME');
        const { _getAdminToken } = load({ game_id: 'g1' });
        expect(_getAdminToken()).toBe('PERGAME');
    });

    it('_getAdminToken falls back to the global token when no per-game token', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        const { _getAdminToken } = load({ game_id: 'g1' });
        expect(_getAdminToken()).toBe('GLOBAL');
    });

    it('_getAdminToken uses the global token when there is no current game', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        const { _getAdminToken } = load(undefined);
        expect(_getAdminToken()).toBe('GLOBAL');
    });

    it('_getAdminToken swallows storage exceptions and returns null', () => {
        const throwing = {
            getItem() { throw new Error('SecurityError'); },
        };
        const { _getAdminToken } = loadHelpers({
            functions: ['_getAdminToken'],
            globals: { currentGame: { game_id: 'g1' }, localStorage: throwing },
        });
        expect(_getAdminToken()).toBeNull();
    });

    it('_setAdminToken writes both per-game and global keys and clears sessionStorage', () => {
        sessionStorage.setItem('beatify_admin_token', 'STALE');
        const { _setAdminToken } = load({ game_id: 'g1' });
        _setAdminToken('TOKEN123', 'g1');
        expect(localStorage.getItem('beatify_admin_token_g1')).toBe('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token')).toBe('TOKEN123');
        expect(sessionStorage.getItem('beatify_admin_token')).toBeNull();
    });

    it('_setAdminToken writes only the global key when no gameId is given', () => {
        const { _setAdminToken } = load(undefined);
        _setAdminToken('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token')).toBe('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token_undefined')).toBeNull();
    });

    it('_adminHeaders includes a Bearer header when a token is present', () => {
        localStorage.setItem('beatify_admin_token', 'TOK');
        const { _adminHeaders } = load(undefined);
        expect(_adminHeaders()).toEqual({
            'Content-Type': 'application/json',
            Authorization: 'Bearer TOK',
        });
    });

    it('_adminHeaders omits Authorization when no token is present', () => {
        const { _adminHeaders } = load(undefined);
        const headers = _adminHeaders();
        expect(headers).toEqual({ 'Content-Type': 'application/json' });
        expect(headers.Authorization).toBeUndefined();
    });
});

describe('admin.js pure helpers — groupPlayersByPlatform (#1279 step 1)', () => {
    function load() {
        return loadHelpers({ functions: ['groupPlayersByPlatform'], globals: {} });
    }

    it('groups players by their platform field', () => {
        const { groupPlayersByPlatform } = load();
        const players = [
            { entity_id: 'a', platform: 'spotify' },
            { entity_id: 'b', platform: 'sonos' },
            { entity_id: 'c', platform: 'spotify' },
        ];
        const groups = groupPlayersByPlatform(players);
        expect(Object.keys(groups).sort()).toEqual(['sonos', 'spotify']);
        expect(groups.spotify.map((p) => p.entity_id)).toEqual(['a', 'c']);
        expect(groups.sonos.map((p) => p.entity_id)).toEqual(['b']);
    });

    it('buckets players with a missing platform under "unknown"', () => {
        const { groupPlayersByPlatform } = load();
        const groups = groupPlayersByPlatform([{ entity_id: 'x' }, { entity_id: 'y', platform: null }]);
        expect(groups.unknown.map((p) => p.entity_id)).toEqual(['x', 'y']);
    });

    it('returns an empty object for an empty list', () => {
        const { groupPlayersByPlatform } = load();
        expect(groupPlayersByPlatform([])).toEqual({});
    });
});

describe('admin.js pure helpers — escapeHtml (#1279 step 1)', () => {
    function load() {
        return loadHelpers({
            functions: ['escapeHtml'],
            globals: { document: makeDocumentStub() },
        });
    }

    it('escapes angle brackets and ampersands', () => {
        const { escapeHtml } = load();
        expect(escapeHtml('<script>alert("x")&</script>')).toBe(
            '&lt;script&gt;alert("x")&amp;&lt;/script&gt;',
        );
    });

    it('leaves plain text unchanged', () => {
        const { escapeHtml } = load();
        expect(escapeHtml('Hello World 123')).toBe('Hello World 123');
    });

    it('coerces nullish input to an empty string', () => {
        const { escapeHtml } = load();
        expect(escapeHtml(null)).toBe('');
        expect(escapeHtml(undefined)).toBe('');
    });
});

describe('admin.js pure helpers — buildRequestRowHtml (#1279 step 1)', () => {
    function load() {
        return loadHelpers({
            functions: ['buildRequestRowHtml', 'escapeHtml'],
            consts: ['REQUEST_STATUS_LABELS'],
            globals: { document: makeDocumentStub() },
            expose: ['buildRequestRowHtml'],
        });
    }

    it('renders the mapped status label and escaped playlist name', () => {
        const { buildRequestRowHtml } = load();
        const html = buildRequestRowHtml({
            status: 'ready',
            playlist_name: 'Rock & <Roll>',
            relative_time: '2h ago',
        });
        expect(html).toContain('Rock &amp; &lt;Roll&gt;');
        expect(html).toContain('✅ Ready');
        expect(html).toContain('request-status--ready');
        expect(html).toContain('2h ago');
    });

    it('falls back to the raw status when it is not in the label map', () => {
        const { buildRequestRowHtml } = load();
        const html = buildRequestRowHtml({ status: 'weird', playlist_name: 'X' });
        expect(html).toContain('request-status--weird');
        expect(html).toContain('>weird</span>');
    });

    it('uses the "Untitled request" fallback when no name is provided', () => {
        const { buildRequestRowHtml } = load();
        const html = buildRequestRowHtml({ status: 'pending' });
        expect(html).toContain('Untitled request');
        expect(html).toContain('⏳ Pending');
    });

    it('shows the update button only for ready+update_available requests', () => {
        const { buildRequestRowHtml } = load();
        const withUpdate = buildRequestRowHtml({
            status: 'ready',
            update_available: true,
            release_version: '4.1.0',
            playlist_name: 'P',
        });
        expect(withUpdate).toContain('Update to v4.1.0');

        const noUpdate = buildRequestRowHtml({ status: 'ready', playlist_name: 'P' });
        expect(noUpdate).not.toContain('request-update-btn');
    });

    it('renders the placeholder thumbnail when no thumbnail_url is set', () => {
        const { buildRequestRowHtml } = load();
        const html = buildRequestRowHtml({ status: 'pending', playlist_name: 'P' });
        expect(html).toContain('request-item-thumbnail-placeholder');
    });
});
