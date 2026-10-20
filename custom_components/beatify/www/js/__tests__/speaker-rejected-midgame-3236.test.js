/**
 * #3236 — a speaker switch the server refuses during PLAYING or REVEAL.
 *
 * showSpeakerRejected() went through showSetupError(), which finds no Start
 * button mid-game and fell back to a transient toast: no title, no way back,
 * gone after a few seconds. Now (design Variant A) the #3223 banner docks above
 * the fixed control bar, which both phases show. It has no "Select Speaker"
 * button (the only speaker list is the setup wizard, which would leave the game
 * screen), closes with ×, clears on a switch that works or when the game ends,
 * and stays away entirely when the page re-sent the stored speaker by itself.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readSource, locale, declaration, evaluate } from './helpers/js-source.js';
import { speakerRejectedText, bannerAnchorFor, tr } from '../admin/util.js';

globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };

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
    message: 'Apple Music is not supported on this speaker. Use Music Assistant.',
    speaker: 'Küche',
    provider: 'Apple Music',
    updated: true,
    fields: [],
    media_player: 'media_player.wohnzimmer',
    current_speaker: 'Wohnzimmer',
};

const ADMIN = readSource('admin.js');

/** showSpeakerRejected with the in-game helpers, over stubs. */
function build({ phase, lang = 'en', startBtn = null }) {
    const t = i18n(lang);
    const bar = { id: 'admin-control-bar' };
    const banners = [];
    const toasts = [];
    const added = [];
    const win = { BeatifyI18n: { t }, BeatifyHome: { refresh: vi.fn() } };
    const show = evaluate(
        [
            'const SPEAKER_BANNER_GAME_PHASES = ' + ADMIN.match(/const SPEAKER_BANNER_GAME_PHASES = (\[[^\]]*\]);/)[1] + ';',
            'const INGAME_SPEAKER_BANNER_ID = ' + ADMIN.match(/const INGAME_SPEAKER_BANNER_ID = ('[^']+');/)[1] + ';',
            declaration(ADMIN, 'showSetupError', 'admin.js'),
            declaration(ADMIN, 'showInGameSpeakerBanner', 'admin.js'),
            declaration(ADMIN, 'showSpeakerRejected', 'admin.js'),
        ],
        'showSpeakerRejected',
        {
            window: win,
            BeatifyI18n: win.BeatifyI18n,
            document: {
                getElementById: (id) => {
                    if (id === 'admin-control-bar') return bar;
                    if (id === 'home-start-game') return startBtn;
                    return null;
                },
            },
            adminState: { mediaPlayers: [], currentGame: { phase } },
            speakerRejectedText,
            bannerAnchorFor,
            tr,
            openSetupStepOne: vi.fn(),
            showBanner: (message, opts) => {
                banners.push({ message, opts });
                return { classList: { add: (c) => added.push(c) } };
            },
            showToast: (message, opts) => toasts.push({ message, opts }),
        },
    );
    return { show, bar, banners, toasts, added };
}

describe('mid-game banner docks above the control bar (#3236)', () => {
    for (const phase of ['PLAYING', 'REVEAL']) {
        it(`in ${phase}`, () => {
            const { show, bar, banners, toasts, added } = build({ phase });
            show(REJECTION, { auto: false });

            expect(toasts).toHaveLength(0);
            expect(banners).toHaveLength(1);
            const { message, opts } = banners[0];
            expect(opts.parent).toBe(bar);
            expect(opts.id).toBe('ingame-speaker-banner');
            expect(opts.title).toBe('Speaker not changed');
            expect(message).toBe(
                "Küche can't play Apple Music. Switch to a Music Assistant speaker. The game stays on Wohnzimmer.");
            expect(added).toContain('beatify-banner--docked');
        });
    }

    it('has no "Select Speaker" button and keeps the × (dismissible)', () => {
        const { show, banners } = build({ phase: 'PLAYING' });
        show(REJECTION, { auto: false });
        expect(banners[0].opts.action).toBeUndefined();
        expect(banners[0].opts.dismissible).not.toBe(false);
    });

    it('in German', () => {
        const { show, banners } = build({ phase: 'REVEAL', lang: 'de' });
        show(REJECTION, { auto: false });
        expect(banners[0].opts.title).toBe('Lautsprecher nicht gewechselt');
        expect(banners[0].message).toMatch(/Das Spiel bleibt auf Wohnzimmer\.$/);
    });

    it('stays silent when the page re-sent the stored speaker by itself', () => {
        for (const phase of ['PLAYING', 'REVEAL']) {
            const { show, banners, toasts } = build({ phase });
            show(REJECTION, { auto: true });
            expect(banners).toHaveLength(0);
            expect(toasts).toHaveLength(0);
        }
    });

    it('leaves the lobby banner (#3223) as it was', () => {
        const startBtn = { closest: () => null, id: 'home-start-game' };
        const { show, banners } = build({ phase: 'LOBBY', startBtn });
        show(REJECTION, { auto: true });
        expect(banners).toHaveLength(1);
        expect(banners[0].opts.id).toBe('home-start-banner');
        expect(banners[0].opts.action.label).toBe('Select Speaker');
    });
});

describe('lifetime of the in-game banner (#3236)', () => {
    function lifecycle() {
        const clearBanner = vi.fn();
        const fns = evaluate(
            [
                'const SPEAKER_BANNER_GAME_PHASES = [\'PLAYING\', \'REVEAL\'];',
                'const INGAME_SPEAKER_BANNER_ID = \'ingame-speaker-banner\';',
                declaration(ADMIN, 'syncInGameSpeakerBanner', 'admin.js'),
                declaration(ADMIN, 'clearSpeakerRejectedBanners', 'admin.js'),
                'var __fns = { syncInGameSpeakerBanner, clearSpeakerRejectedBanners };',
            ],
            '__fns',
            { clearBanner },
        );
        return { ...fns, clearBanner };
    }

    it('survives PLAYING → REVEAL (and a pause), goes when the game ends', () => {
        const { syncInGameSpeakerBanner, clearBanner } = lifecycle();
        for (const phase of ['PLAYING', 'REVEAL', 'PAUSED']) syncInGameSpeakerBanner(phase);
        expect(clearBanner).not.toHaveBeenCalled();
        for (const phase of ['END', 'LOBBY', undefined]) syncInGameSpeakerBanner(phase);
        expect(clearBanner).toHaveBeenCalledTimes(3);
        expect(clearBanner).toHaveBeenCalledWith('ingame-speaker-banner');
    });

    it('is cleared by a speaker switch that works', () => {
        const { clearSpeakerRejectedBanners, clearBanner } = lifecycle();
        clearSpeakerRejectedBanners();
        expect(clearBanner).toHaveBeenCalledWith('home-start-banner');
        expect(clearBanner).toHaveBeenCalledWith('ingame-speaker-banner');
        const init = ADMIN.slice(ADMIN.indexOf('initMediaPlayers({'));
        expect(init.slice(0, init.indexOf('});'))).toContain('onSpeakerChanged: clearSpeakerRejectedBanners');
    });

    it('is synced on every render and cleared on the setup view', () => {
        expect(declaration(ADMIN, 'renderAdminState', 'admin.js')).toContain('syncInGameSpeakerBanner(data.phase)');
        expect(declaration(ADMIN, 'showSetupView', 'admin.js')).toContain('clearBanner(INGAME_SPEAKER_BANNER_ID)');
    });
});

describe('the × removes the docked banner (#3236)', () => {
    function el(tag) {
        const e = {
            tagName: tag, children: [], parentNode: null, attrs: {}, listeners: {},
            className: '', textContent: '', id: '', type: '',
            classList: { add(c) { e.className += ' ' + c; } },
            setAttribute(k, v) { e.attrs[k] = v; },
            appendChild(c) { c.parentNode = e; e.children.push(c); return c; },
            insertBefore(c) { return e.appendChild(c); },
            removeChild(c) { e.children = e.children.filter((x) => x !== c); c.parentNode = null; return c; },
            addEventListener(type, fn) { e.listeners[type] = fn; },
        };
        return e;
    }

    afterEach(() => { delete globalThis.document; vi.resetModules(); });

    it('closes on ×', async () => {
        const bar = el('div');
        globalThis.document = {
            createElement: el,
            getElementById: (id) => bar.children.find((c) => c.id === id) || null,
        };
        const { showBanner } = await import('../notify.js');
        const banner = showBanner('Küche can\'t play Apple Music.', {
            parent: bar, id: 'ingame-speaker-banner', title: 'Speaker not changed', type: 'error',
        });
        expect(bar.children).toContain(banner);
        const close = banner.children.find((c) => c.className === 'beatify-banner-close');
        expect(close).toBeTruthy();
        expect(banner.children.some((c) => c.className === 'beatify-banner-content'
            && c.children.some((x) => x.className === 'beatify-banner-action'))).toBe(false);
        close.listeners.click();
        expect(bar.children).not.toContain(banner);
    });
});

describe('the automatic re-send is marked as such (#3236)', () => {
    let fetchMock;
    let mp;

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
        const store = {};
        globalThis.window = globalThis;
        globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
        globalThis.BeatifyI18n = { t: (k) => k };
        globalThis.localStorage = {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
        };
        globalThis.document = {
            getElementById: () => null,
            querySelectorAll: () => [],
            querySelector: () => null,
        };
        fetchMock = vi.fn().mockResolvedValue({ ok: false, json: async () => REJECTION });
        globalThis.BeatifyAuth = { fetch: fetchMock };
        globalThis.BeatifyPersistSetup = vi.fn();
        mp = await import('../admin/sections/media-players.js');
    });

    afterEach(() => {
        for (const k of ['window', 'document', 'localStorage', 'BeatifyUtils', 'BeatifyI18n',
            'BeatifyAuth', 'BeatifyPersistSetup']) delete globalThis[k];
        vi.restoreAllMocks();
    });

    function radio() {
        const item = node({ querySelector: () => node({ textContent: 'Küche' }) });
        return node({
            dataset: { entityId: 'media_player.kueche', state: 'idle', platform: 'sonos' },
            closest: () => item,
        });
    }

    async function settle() {
        for (let i = 0; i < 5; i++) await Promise.resolve();
    }

    it('the stored speaker re-selected on render pushes with auto: true', async () => {
        const onSpeakerRejected = vi.fn();
        mp.initMediaPlayers({ onSpeakerRejected });
        mp.handleMediaPlayerSelect(radio(), true);
        await settle();
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(onSpeakerRejected).toHaveBeenCalledWith(REJECTION, { auto: true });
    });

    it('a host pick pushes with auto: false', async () => {
        const onSpeakerRejected = vi.fn();
        mp.initMediaPlayers({ onSpeakerRejected });
        mp.handleMediaPlayerSelect(radio());
        await settle();
        expect(onSpeakerRejected).toHaveBeenCalledWith(REJECTION, { auto: false });
    });
});
