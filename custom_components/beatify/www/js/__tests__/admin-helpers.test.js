/**
 * Smoke-test safety net for the pure helpers extracted into admin/util.js
 * (#1279, Schritt 2/6).
 *
 * Step 1 (#1310) pinned these helpers' behaviour by lifting their SOURCE TEXT
 * out of the then-classic admin.js (eval-based admin-helpers-loader.js). Step 2
 * extracts them into a real ES module `admin/util.js`, so this test now imports
 * them directly — the eval loader is gone.
 *
 * Helpers covered:
 *   - _getAdminToken()           (token resolution: per-game → global → null)
 *   - _setAdminToken(t, gameId)  (persistence to localStorage + sessionStorage cleanup)
 *   - _adminHeaders()            (REST header builder, Bearer iff token present)
 *   - groupPlayersByPlatform()   (pure grouping)
 *   - escapeHtml()               (XSS escaping via DOM textContent)
 *   - buildRequestRowHtml()      (request-card HTML, status-label lookup, escaping)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
    setCurrentGameResolver,
    _getAdminToken,
    _setAdminToken,
    _adminHeaders,
    groupPlayersByPlatform,
    escapeHtml,
    buildRequestRowHtml,
    applyStoredGameSettings,
} from '../admin/util.js';

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

describe('admin/util.js pure helpers — token + headers (#1279 step 2)', () => {
    let localStorage;
    let sessionStorage;

    function setGame(currentGame) {
        setCurrentGameResolver(() => currentGame);
    }

    beforeEach(() => {
        localStorage = makeStorage();
        sessionStorage = makeStorage();
        vi.stubGlobal('localStorage', localStorage);
        vi.stubGlobal('sessionStorage', sessionStorage);
        setCurrentGameResolver(() => null);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        setCurrentGameResolver(() => null);
    });

    it('_getAdminToken returns null when nothing is stored', () => {
        setGame({ game_id: 'g1' });
        expect(_getAdminToken()).toBeNull();
    });

    it('_getAdminToken prefers the per-game token over the global token', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        localStorage.setItem('beatify_admin_token_g1', 'PERGAME');
        setGame({ game_id: 'g1' });
        expect(_getAdminToken()).toBe('PERGAME');
    });

    it('_getAdminToken falls back to the global token when no per-game token', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        setGame({ game_id: 'g1' });
        expect(_getAdminToken()).toBe('GLOBAL');
    });

    it('_getAdminToken uses the global token when there is no current game', () => {
        localStorage.setItem('beatify_admin_token', 'GLOBAL');
        setGame(undefined);
        expect(_getAdminToken()).toBe('GLOBAL');
    });

    it('_getAdminToken swallows storage exceptions and returns null', () => {
        const throwing = {
            getItem() { throw new Error('SecurityError'); },
        };
        vi.stubGlobal('localStorage', throwing);
        setGame({ game_id: 'g1' });
        expect(_getAdminToken()).toBeNull();
    });

    it('_setAdminToken writes both per-game and global keys and clears sessionStorage', () => {
        sessionStorage.setItem('beatify_admin_token', 'STALE');
        setGame({ game_id: 'g1' });
        _setAdminToken('TOKEN123', 'g1');
        expect(localStorage.getItem('beatify_admin_token_g1')).toBe('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token')).toBe('TOKEN123');
        expect(sessionStorage.getItem('beatify_admin_token')).toBeNull();
    });

    it('_setAdminToken writes only the global key when no gameId is given', () => {
        setGame(undefined);
        _setAdminToken('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token')).toBe('TOKEN123');
        expect(localStorage.getItem('beatify_admin_token_undefined')).toBeNull();
    });

    it('_adminHeaders includes a Bearer header when a token is present', () => {
        localStorage.setItem('beatify_admin_token', 'TOK');
        setGame(undefined);
        expect(_adminHeaders()).toEqual({
            'Content-Type': 'application/json',
            Authorization: 'Bearer TOK',
        });
    });

    it('_adminHeaders omits Authorization when no token is present', () => {
        setGame(undefined);
        const headers = _adminHeaders();
        expect(headers).toEqual({ 'Content-Type': 'application/json' });
        expect(headers.Authorization).toBeUndefined();
    });
});

describe('admin/util.js pure helpers — groupPlayersByPlatform (#1279 step 2)', () => {
    it('groups players by their platform field', () => {
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
        const groups = groupPlayersByPlatform([{ entity_id: 'x' }, { entity_id: 'y', platform: null }]);
        expect(groups.unknown.map((p) => p.entity_id)).toEqual(['x', 'y']);
    });

    it('returns an empty object for an empty list', () => {
        expect(groupPlayersByPlatform([])).toEqual({});
    });
});

describe('admin/util.js pure helpers — escapeHtml (#1279 step 2)', () => {
    beforeEach(() => {
        vi.stubGlobal('document', makeDocumentStub());
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('escapes angle brackets and ampersands', () => {
        expect(escapeHtml('<script>alert("x")&</script>')).toBe(
            '&lt;script&gt;alert("x")&amp;&lt;/script&gt;',
        );
    });

    it('leaves plain text unchanged', () => {
        expect(escapeHtml('Hello World 123')).toBe('Hello World 123');
    });

    it('coerces nullish input to an empty string', () => {
        expect(escapeHtml(null)).toBe('');
        expect(escapeHtml(undefined)).toBe('');
    });
});

describe('admin/util.js pure helpers — buildRequestRowHtml (#1279 step 2)', () => {
    beforeEach(() => {
        vi.stubGlobal('document', makeDocumentStub());
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('renders the mapped status label and escaped playlist name', () => {
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
        const html = buildRequestRowHtml({ status: 'weird', playlist_name: 'X' });
        expect(html).toContain('request-status--weird');
        expect(html).toContain('>weird</span>');
    });

    it('uses the "Untitled request" fallback when no name is provided', () => {
        const html = buildRequestRowHtml({ status: 'pending' });
        expect(html).toContain('Untitled request');
        expect(html).toContain('⏳ Pending');
    });

    it('shows the update button only for ready+update_available requests', () => {
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
        const html = buildRequestRowHtml({ status: 'pending', playlist_name: 'P' });
        expect(html).toContain('request-item-thumbnail-placeholder');
    });
});

describe('applyStoredGameSettings — settings → adminState hydration', () => {
    // Regression for #1180: the wizard saved titleArtistMode:true but the
    // home→start hydration path dropped it, so "name the song" started as a
    // year game (players got the year input instead of title/artist fields).
    it('hydrates title_artist_mode (the missed flag) from saved settings', () => {
        const adminState = { titleArtistModeEnabled: false };
        applyStoredGameSettings(adminState, { titleArtistMode: true });
        expect(adminState.titleArtistModeEnabled).toBe(true);
    });

    it('hydrates every game-mode flag from saved settings', () => {
        const adminState = {
            artistChallengeEnabled: false, movieQuizEnabled: false,
            introModeEnabled: false, closestWinsModeEnabled: false,
            titleArtistModeEnabled: false, rampupOrderEnabled: false,
            finaleDoubleEnabled: false, finaleTiebreakerEnabled: false,
            comebackTokenEnabled: false,
        };
        applyStoredGameSettings(adminState, {
            artistChallenge: true, movieQuiz: true, introMode: true,
            closestWinsMode: true, titleArtistMode: true, rampupOrder: true,
            finaleDouble: true, finaleTiebreaker: true, comebackToken: true,
        });
        expect(adminState).toMatchObject({
            artistChallengeEnabled: true, movieQuizEnabled: true,
            introModeEnabled: true, closestWinsModeEnabled: true,
            titleArtistModeEnabled: true, rampupOrderEnabled: true,  // #1726
            finaleDoubleEnabled: true, finaleTiebreakerEnabled: true,  // #1725
            comebackTokenEnabled: true,  // #1724
        });
    });

    it('hydrates scalar settings (language, duration, difficulty, provider, autoadvance)', () => {
        const adminState = {};
        applyStoredGameSettings(adminState, {
            language: 'de', duration: 45, revealAutoAdvance: 30,
            difficulty: 'hard', provider: 'spotify',
        });
        expect(adminState).toMatchObject({
            selectedLanguage: 'de', selectedDuration: 45, revealAutoAdvance: 30,
            selectedDifficulty: 'hard', selectedProvider: 'spotify',
        });
    });

    it('leaves flags untouched for absent / wrong-typed keys (partial / legacy payloads)', () => {
        const adminState = { titleArtistModeEnabled: true, artistChallengeEnabled: true };
        applyStoredGameSettings(adminState, { titleArtistMode: 'yes' /* not boolean */ });
        expect(adminState.titleArtistModeEnabled).toBe(true);   // unchanged
        expect(adminState.artistChallengeEnabled).toBe(true);   // absent key, unchanged
    });

    it('is a no-op for null / non-object input', () => {
        const adminState = { titleArtistModeEnabled: false };
        applyStoredGameSettings(adminState, null);
        applyStoredGameSettings(null, { titleArtistMode: true });
        expect(adminState.titleArtistModeEnabled).toBe(false);
    });
});
