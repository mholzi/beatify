/**
 * #3223 — a speaker switch the server refuses in the lobby.
 *
 * update-lobby was fire-and-forget: the admin kept the refused speaker selected
 * while the game stayed on the old one, and only "Start game" showed the
 * banner. Now the answer is read: the selection goes back to the speaker the
 * server kept, and the existing banner above "Start game" appears right away
 * (design Variant C) with "Select Speaker" back to wizard step 1.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readSource, locale, declaration, evaluate } from './helpers/js-source.js';
import { speakerRejectedText, bannerAnchorFor, tr } from '../admin/util.js';

globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };

/** BeatifyI18n.t over a real locale file: dotted keys, {name} params. */
function i18n(lang) {
    const dict = locale(lang);
    return (key, params) => {
        const v = key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), dict);
        if (typeof v !== 'string') return key;
        return v.replace(/\{(\w+)\}/g, (m, n) => (params && params[n] != null ? String(params[n]) : m));
    };
}

const REJECTION = {
    code: 'PROVIDER_NOT_SUPPORTED',
    error: 'PROVIDER_NOT_SUPPORTED',
    message: 'Apple Music is not supported on this speaker. Use a Music Assistant speaker.',
    speaker: 'Küche',
    provider: 'Apple Music',
    updated: true,
    fields: ['tts'],
    media_player: 'media_player.wohnzimmer',
    current_speaker: 'Wohnzimmer',
};

describe('banner text (#3223)', () => {
    it('reuses the rejection text and names the speaker the game stays on (EN)', () => {
        const text = speakerRejectedText(REJECTION, [], i18n('en'));
        expect(text.title).toBe('Speaker not changed');
        expect(text.message).toBe(
            "Küche can't play Apple Music. Switch to a Music Assistant speaker. The game stays on Wohnzimmer.");
    });

    it('in German', () => {
        const text = speakerRejectedText(REJECTION, [], i18n('de'));
        expect(text.title).toBe('Lautsprecher nicht gewechselt');
        expect(text.message).toBe(
            'Küche kann Apple Music nicht abspielen. Wechsle zu einem Music-Assistant-Lautsprecher. '
            + 'Das Spiel bleibt auf Wohnzimmer.');
    });

    it('prefers the friendly name from the admin player list', () => {
        const text = speakerRejectedText(REJECTION,
            [{ entity_id: 'media_player.wohnzimmer', friendly_name: 'Living room' }], i18n('en'));
        expect(text.message).toMatch(/The game stays on Living room\.$/);
    });

    it('covers a speaker that is gone (MEDIA_PLAYER_NOT_FOUND)', () => {
        const text = speakerRejectedText({
            code: 'INVALID_REQUEST', message_key: 'MEDIA_PLAYER_NOT_FOUND',
            message: 'Media player not found', fields: [], media_player: 'media_player.wohnzimmer',
            current_speaker: 'Wohnzimmer',
        }, [], i18n('en'));
        expect(text.message).toBe('Media player not found. The game stays on Wohnzimmer.');
    });

    it('has both new keys in all six languages', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            const block = locale(lang).admin.speakerChangeRejected;
            expect(block.title, lang).toBeTruthy();
            expect(block.kept, lang).toContain('{speaker}');
        }
    });
});

describe('the banner above "Start game" appears on rejection (#3223)', () => {
    const ADMIN = readSource('admin.js');

    afterEach(() => { delete globalThis.window; });

    it('docks the start banner with its own title and a way back to wizard step 1', () => {
        const t = i18n('en');
        globalThis.window = { BeatifyI18n: { t } };
        const startBtn = { closest: () => null, id: 'home-start-game' };
        const banners = [];
        const openSetupStepOne = vi.fn();
        const refresh = vi.fn();
        const win = { BeatifyI18n: { t }, BeatifyHome: { refresh } };
        const show = evaluate(
            [declaration(ADMIN, 'showSetupError', 'admin.js'),
                declaration(ADMIN, 'showSpeakerRejected', 'admin.js')],
            'showSpeakerRejected',
            {
                window: win,
                BeatifyI18n: win.BeatifyI18n,
                document: { getElementById: (id) => (id === 'home-start-game' ? startBtn : null) },
                adminState: { mediaPlayers: [] },
                speakerRejectedText,
                bannerAnchorFor,
                tr,
                openSetupStepOne,
                showBanner: (message, opts) => banners.push({ message, opts }),
                showToast: () => { throw new Error('the lobby has a Start button: banner, not toast'); },
            },
        );

        show(REJECTION);

        expect(banners).toHaveLength(1);
        const { message, opts } = banners[0];
        expect(opts.id).toBe('home-start-banner');
        expect(opts.anchor).toBe(startBtn);
        expect(opts.title).toBe('Speaker not changed');
        expect(message).toContain('The game stays on Wohnzimmer.');
        expect(opts.action.label).toBe('Select Speaker');
        opts.action.onClick();
        expect(openSetupStepOne).toHaveBeenCalledTimes(1);
        expect(refresh).toHaveBeenCalled();  // the meta line shows the kept speaker again
    });

    it('is wired to the media-players section', () => {
        const init = ADMIN.slice(ADMIN.indexOf('initMediaPlayers({'));
        expect(init.slice(0, init.indexOf('});'))).toContain('onSpeakerRejected: showSpeakerRejected');
    });
});

describe('postLobbyUpdate reverts a refused speaker (#3223)', () => {
    let store;
    let fetchMock;
    let radioOld;
    let mp;
    let state;

    function node(extra = {}) {
        return {
            checked: false, dataset: {},
            classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
            setAttribute() {}, removeAttribute() {},
            querySelector: () => null, querySelectorAll: () => [],
            closest: () => null, addEventListener() {}, textContent: '',
            ...extra,
        };
    }

    beforeEach(async () => {
        store = { beatify_last_player: 'media_player.kueche' };
        globalThis.window = globalThis;
        globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
        globalThis.BeatifyI18n = { t: (k) => k };
        globalThis.localStorage = {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
        };
        const item = node({ querySelector: () => node({ textContent: 'Wohnzimmer' }) });
        radioOld = node({
            dataset: { entityId: 'media_player.wohnzimmer', state: 'idle', platform: 'music_assistant' },
            closest: () => item,
        });
        globalThis.document = {
            getElementById: () => null,
            querySelectorAll: () => [],
            querySelector: (sel) => (sel.includes('media_player.wohnzimmer') ? radioOld : null),
        };
        fetchMock = vi.fn();
        globalThis.BeatifyAuth = { fetch: fetchMock };
        globalThis.BeatifyPersistSetup = vi.fn();
        mp = await import('../admin/sections/media-players.js');
        state = await import('../admin/state.js');
        state.adminState.selectedMediaPlayer = {
            entityId: 'media_player.kueche', state: 'idle', platform: 'sonos',
        };
    });

    afterEach(() => {
        for (const k of ['window', 'document', 'localStorage', 'BeatifyUtils', 'BeatifyI18n',
            'BeatifyAuth', 'BeatifyPersistSetup']) delete globalThis[k];
        vi.restoreAllMocks();
    });

    it('puts the selection, the stored pick and the server setup back, then reports', async () => {
        fetchMock.mockResolvedValue({ ok: false, json: async () => REJECTION });
        const onSpeakerRejected = vi.fn();
        const onSpeakerChanged = vi.fn();
        mp.initMediaPlayers({ onSpeakerRejected, onSpeakerChanged });

        await mp.postLobbyUpdate({ media_player: 'media_player.kueche', tts: null });

        expect(state.adminState.selectedMediaPlayer.entityId).toBe('media_player.wohnzimmer');
        expect(radioOld.checked).toBe(true);
        expect(store.beatify_last_player).toBe('media_player.wohnzimmer');
        expect(globalThis.BeatifyPersistSetup).toHaveBeenCalled();
        expect(onSpeakerRejected).toHaveBeenCalledWith(REJECTION);
        // The revert itself does not push again: the game is on that speaker.
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(onSpeakerChanged).not.toHaveBeenCalled();
    });

    it('keeps the banner for the revert push and clears it once a switch works', async () => {
        const onSpeakerChanged = vi.fn();
        mp.initMediaPlayers({ onSpeakerRejected: () => {}, onSpeakerChanged });
        fetchMock.mockResolvedValueOnce({ ok: false, json: async () => REJECTION });
        await mp.postLobbyUpdate({ media_player: 'media_player.kueche' });

        // The status poll re-selects the stored (reverted) speaker and pushes it.
        fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ updated: true, fields: ['media_player'] }) });
        await mp.postLobbyUpdate({ media_player: 'media_player.wohnzimmer' });
        expect(onSpeakerChanged).not.toHaveBeenCalled();

        fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ updated: true, fields: ['media_player'] }) });
        await mp.postLobbyUpdate({ media_player: 'media_player.bad' });
        expect(onSpeakerChanged).toHaveBeenCalledTimes(1);
    });

    it('leaves other errors alone', async () => {
        const onSpeakerRejected = vi.fn();
        mp.initMediaPlayers({ onSpeakerRejected });
        fetchMock.mockResolvedValue({ ok: false, json: async () => ({ code: 'INVALID_REQUEST', message: 'Invalid JSON' }) });

        await mp.postLobbyUpdate({ media_player: 'media_player.kueche' });

        expect(onSpeakerRejected).not.toHaveBeenCalled();
        expect(state.adminState.selectedMediaPlayer.entityId).toBe('media_player.kueche');
    });
});
