/**
 * Play without a speaker: the TV screen or this phone plays the round's
 * 30-second preview (design gate 2026-11-08, variant B).
 *
 *   - browser-audio.js: plays what the server sends, reports back, waits for
 *     the one tap a browser needs before sound, ducks under announcements;
 *   - admin/browser-playback.js: the phone registers with the authenticated
 *     admin socket and wakes the audio inside the host's taps; the TV-row
 *     watcher stops once the TV page is open;
 *   - the step-1 group (wizard) and the speaker-list group (admin): label,
 *     badges and the plain-text source note, in every shipped language;
 *   - dashboard.js: when the "Sound on" prompt shows;
 *   - sw.js: preview and announcement audio never reaches the cache.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';
import { createPhonePlayback, createTvConnectionWatch, PHONE_TARGET } from '../admin/browser-playback.js';
import { browserTargetGroupHtml, isBrowserTargetId } from '../wizard.js';

global.window = global.window || {};
await import('../browser-audio.js');
const Lib = global.window.BeatifyBrowserAudio;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const CLIP = 'https://cdnt-preview.dzcdn.net/api/1/1/a/b/c/0/clip.mp3';

/** An <audio> stand-in whose play() outcome the test decides. */
function fakeAudio(outcome = () => Promise.resolve()) {
    const el = {
        src: '',
        volume: 1,
        paused: true,
        played: [],
        play: vi.fn(() => {
            el.played.push(el.src);
            el.paused = false;
            return outcome(el);
        }),
        pause: vi.fn(() => { el.paused = true; }),
        onended: null,
        onerror: null,
    };
    return el;
}

function notAllowed() {
    const err = new Error('play() needs a user gesture');
    err.name = 'NotAllowedError';
    return Promise.reject(err);
}

function player({ outcomes } = {}) {
    const sent = [];
    const elements = [];
    const needs = [];
    let i = 0;
    const p = Lib.createBrowserAudio({
        send: (frame) => sent.push(frame),
        onNeedsTap: (v) => needs.push(v),
        createAudio: () => {
            const outcome = (outcomes && outcomes[i]) || (() => Promise.resolve());
            i += 1;
            const el = fakeAudio(outcome);
            elements.push(el);
            return el;
        },
    });
    return { p, sent, music: elements[0], voice: elements[1], needs };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('browser-audio.js', () => {
    it('plays the clip and reports it started, with the request id', async () => {
        const { p, sent, music } = player();
        expect(p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 7 })).toBe(true);
        await flush();
        expect(music.src).toBe(CLIP);
        expect(sent).toEqual([{ type: 'playback_report', state: 'playing', id: 7 }]);
    });

    it('a clip before the first tap is reported blocked and starts with the tap', async () => {
        let blocked = true;
        const { p, sent, music, needs } = player({
            outcomes: [() => (blocked ? notAllowed() : Promise.resolve())],
        });
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 3 });
        await flush();
        expect(sent).toEqual([{ type: 'playback_report', state: 'blocked', id: 3 }]);
        expect(p.needsTap()).toBe(true);
        expect(needs).toEqual([true]);

        blocked = false;
        p.unlock();
        await flush();
        expect(music.play).toHaveBeenCalledTimes(2);
        expect(sent[1]).toEqual({ type: 'playback_report', state: 'playing', id: 3 });
        expect(p.needsTap()).toBe(false);
        expect(p.isUnlocked()).toBe(true);
    });

    it('a clip that will not load is an error', async () => {
        const broken = () => {
            const err = new Error('404');
            err.name = 'NotSupportedError';
            return Promise.reject(err);
        };
        const { p, sent } = player({ outcomes: [broken] });
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 });
        await flush();
        expect(sent).toEqual([{ type: 'playback_report', state: 'error', id: 1 }]);
    });

    it('refuses anything but an https clip', () => {
        const { p, sent, music } = player();
        p.handle({ type: 'browser_audio', action: 'play', url: 'javascript:alert(1)', id: 2 });
        expect(music.play).not.toHaveBeenCalled();
        expect(sent).toEqual([{ type: 'playback_report', state: 'error', id: 2 }]);
    });

    it('reports the end of the clip, which the reveal auto-advance reads', async () => {
        const { p, sent, music } = player();
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 });
        await flush();
        music.onended();
        expect(sent.at(-1)).toEqual({ type: 'playback_report', state: 'ended' });
    });

    it('stop pauses, resume plays the same clip again', async () => {
        const { p, sent, music } = player();
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 });
        await flush();
        p.handle({ type: 'browser_audio', action: 'stop' });
        expect(music.pause).toHaveBeenCalled();
        expect(sent.at(-1)).toEqual({ type: 'playback_report', state: 'paused' });
        p.handle({ type: 'browser_audio', action: 'resume' });
        expect(music.played).toEqual([CLIP, CLIP]);
    });

    it('an announcement ducks the music and lets it back up afterwards', async () => {
        const { p, music, voice } = player();
        p.handle({ type: 'browser_audio', action: 'volume', level: 0.8 });
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 });
        await flush();
        p.handle({ type: 'browser_audio', action: 'announce', url: '/api/tts_proxy/x.mp3' });
        expect(voice.src).toBe('/api/tts_proxy/x.mp3');
        expect(music.volume).toBeCloseTo(0.8 * Lib.DUCK_FACTOR);
        voice.onended();
        expect(music.volume).toBeCloseTo(0.8);
    });

    it('volume is clamped to 0..1', () => {
        const { p } = player();
        p.handle({ type: 'browser_audio', action: 'volume', level: 4 });
        expect(p.getVolume()).toBe(1);
        p.handle({ type: 'browser_audio', action: 'volume', level: -1 });
        expect(p.getVolume()).toBe(0);
    });

    it('release stops everything when another page takes over', async () => {
        const { p, music, voice } = player();
        p.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 });
        await flush();
        p.release();
        expect(music.pause).toHaveBeenCalled();
        expect(voice.pause).toHaveBeenCalled();
        // Nothing to resume after a release.
        p.handle({ type: 'browser_audio', action: 'resume' });
        expect(music.played).toEqual([CLIP]);
    });

    it('ignores frames that are not for it', () => {
        const { p } = player();
        expect(p.handle({ type: 'state' })).toBe(false);
        expect(p.handle({ type: 'browser_audio', action: 'dance' })).toBe(false);
    });

    it('knows the two targets', () => {
        expect(Lib.isBrowserTarget('beatify_browser.tv')).toBe(true);
        expect(Lib.isBrowserTarget(PHONE_TARGET)).toBe(true);
        expect(Lib.isBrowserTarget('media_player.kitchen')).toBe(false);
    });
});

describe('admin/browser-playback.js: this phone as the speaker', () => {
    function hub(selected = PHONE_TARGET) {
        const sent = [];
        const audio = { handle: vi.fn(() => true), unlock: vi.fn(), release: vi.fn(), isUnlocked: vi.fn(() => false) };
        const lib = { createBrowserAudio: vi.fn(() => audio) };
        const state = { selected };
        const h = createPhonePlayback({
            send: (f) => { sent.push(f); return true; },
            getSelectedEntityId: () => state.selected,
            lib,
        });
        return { h, sent, audio, lib, state };
    }

    it('registers as the phone once the admin socket is authenticated', () => {
        const { h, sent } = hub();
        expect(h.onConnected()).toBe(true);
        expect(sent).toEqual([{ type: 'playback_register', role: 'phone', claim: true }]);
    });

    it('stays out of it while another speaker is picked', () => {
        const { h, sent } = hub('media_player.kitchen');
        expect(h.onConnected()).toBe(false);
        h.onTap();
        expect(sent).toEqual([]);
    });

    it('registers when a game turns out to play on the phone', () => {
        const { h, sent } = hub('media_player.kitchen');
        h.handle({ type: 'state', browser_playback: 'phone' });
        expect(sent).toEqual([{ type: 'playback_register', role: 'phone', claim: true }]);
        // The same state again does not register twice.
        h.handle({ type: 'playback_registered', role: 'phone', active: true });
        h.handle({ type: 'state', browser_playback: 'phone' });
        expect(sent).toHaveLength(1);
        expect(h.holdsRole()).toBe(true);
    });

    it('hands browser_audio frames to the player and consumes them', () => {
        const { h, audio } = hub();
        expect(h.handle({ type: 'browser_audio', action: 'play', url: CLIP, id: 1 })).toBe(true);
        expect(audio.handle).toHaveBeenCalled();
        // A state frame is read, never consumed: the admin still renders it.
        expect(h.handle({ type: 'state', browser_playback: 'phone' })).toBe(false);
    });

    it('a tap wakes the audio, the tap on Start game included', () => {
        const { h, audio } = hub();
        const listeners = {};
        h.armUnlockOnTap({ addEventListener: (type, fn, capture) => { listeners[type] = { fn, capture }; } });
        expect(listeners.click.capture).toBe(true);
        expect(listeners.keydown).toBeDefined();
        listeners.click.fn();
        expect(audio.unlock).toHaveBeenCalledTimes(1);
    });

    it('stops when another admin page took the role', () => {
        const { h, audio } = hub();
        h.handle({ type: 'browser_audio', action: 'stop' });
        expect(h.handle({ type: 'playback_released', role: 'phone' })).toBe(true);
        expect(audio.release).toHaveBeenCalled();
        expect(h.handle({ type: 'playback_released', role: 'tv' })).toBe(false);
    });
});

describe('TV connection watch', () => {
    function watch(answers) {
        let tick = null;
        const onConnected = vi.fn();
        let now = 0;
        const w = createTvConnectionWatch({
            fetchFn: vi.fn(async () => ({ ok: true, json: async () => answers.shift() })),
            onConnected,
            now: () => now,
            setIntervalFn: (fn) => { tick = fn; return 1; },
            clearIntervalFn: () => { tick = null; },
        });
        return { w, onConnected, run: () => tick && tick(), advance: (ms) => { now += ms; } };
    }

    it('calls back once the TV page is open and stops asking', async () => {
        const { w, onConnected, run } = watch([{ tv: false }, { tv: true }]);
        w.start();
        await run();
        expect(onConnected).not.toHaveBeenCalled();
        await run();
        expect(onConnected).toHaveBeenCalledTimes(1);
        expect(w.isRunning()).toBe(false);
    });

    it('gives up after its time budget', async () => {
        const { w, onConnected, run, advance } = watch([{ tv: true }]);
        w.start();
        advance(11 * 60 * 1000);
        await run();
        expect(onConnected).not.toHaveBeenCalled();
        expect(w.isRunning()).toBe(false);
    });
});

const TARGETS = [
    { entity_id: 'beatify_browser.tv', browser_target: 'tv', connected: true },
    { entity_id: 'beatify_browser.phone', browser_target: 'phone', connected: true },
];

function tFor(lang) {
    const { t } = translator(locale(lang));
    return (key, fallback) => {
        const out = t(key);
        return out === key ? fallback : out;
    };
}

describe('step 1 group (wizard)', () => {
    it('reads like the approved draft in German', () => {
        const html = browserTargetGroupHtml(TARGETS, 'beatify_browser.tv', tFor('de'));
        expect(html).toContain('Ohne Lautsprecher · 30-s-Ausschnitte');
        expect(html).toContain('TV-Bildschirm');
        expect(html).toContain('Ton aus dem Fernseher');
        expect(html).toContain('verbunden');
        expect(html).toContain('Dieses Handy');
        expect(html).toContain('Dieses Gerät');
        expect(html).toContain('Für kleine Runden');
        expect(html).toContain('Ausschnitte: Deezer');
        // The selected row carries the check.
        expect(html).toMatch(/class="wiz-row selected" data-entity-id="beatify_browser\.tv"/);
    });

    it('a TV without its page says how to connect it', () => {
        const html = browserTargetGroupHtml(
            [{ ...TARGETS[0], connected: false }], null, tFor('en'));
        expect(html).toContain('Open the TV page on it');
        expect(html).not.toContain('target-badge--ok');
    });

    it('nothing to render without targets', () => {
        expect(browserTargetGroupHtml([], null, tFor('en'))).toBe('');
    });

    it('every shipped language has its own words, no English leaks', () => {
        const en = browserTargetGroupHtml(TARGETS, null, tFor('en'));
        for (const lang of LOCALES.filter((l) => l !== 'en')) {
            const html = browserTargetGroupHtml(TARGETS, null, tFor(lang));
            expect(html, lang).not.toContain('Without a speaker');
            expect(html, lang).not.toBe(en);
            // The source note is plain text naming Deezer: no logo, no image.
            expect(html, lang).toContain('Deezer');
            expect(html, lang).not.toMatch(/<img/);
        }
    });

    it('knows its ids', () => {
        expect(isBrowserTargetId('beatify_browser.phone')).toBe(true);
        expect(isBrowserTargetId('media_player.tv')).toBe(false);
    });
});

describe('admin speaker list group', () => {
    const SRC = readSource('admin/sections/media-players.js');
    const utils = { escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;') };

    function render(targets, lang) {
        const t = tFor(lang);
        const fn = evaluate(
            [
                declaration(SRC, 'renderBrowserTargetItem', 'media-players.js'),
                declaration(SRC, 'renderBrowserTargetGroup', 'media-players.js'),
            ],
            'renderBrowserTargetGroup',
            { tr: t, utils, supportsAttributes: () => 'data-supports-deezer="true"' },
        );
        return fn(targets);
    }

    it('keeps the radio markup a speaker has, so selection works unchanged', () => {
        const html = render(TARGETS, 'de');
        expect(html.match(/class="media-player-radio"/g)).toHaveLength(2);
        expect(html).toContain('data-platform');
        expect(html).toContain('Ohne Lautsprecher · 30-s-Ausschnitte');
        expect(html).toContain('Ausschnitte: Deezer');
    });

    it('falls back to the first service the speaker plays', () => {
        const PROVIDERS = [{ id: 'spotify' }, { id: 'apple_music' }, { id: 'deezer' }];
        const fn = evaluate(
            [
                declaration(SRC, 'playerSupports', 'media-players.js'),
                declaration(SRC, 'fallbackProvider', 'media-players.js'),
            ],
            'fallbackProvider',
            { PROVIDERS },
        );
        expect(fn({ supports: { spotify: false, apple_music: false, deezer: true } })).toBe('deezer');
        expect(fn({ supports: { spotify: true, deezer: true } })).toBe('spotify');
    });
});

describe('dashboard "Sound on" prompt', () => {
    const SRC = readSource('dashboard.js');
    let visible;
    beforeEach(() => {
        visible = evaluate([declaration(SRC, 'soundGateVisible', 'dashboard.js')], 'soundGateVisible', {});
    });

    it('shows while the game plays on the TV and this screen is not switched on', () => {
        expect(visible({ targetActive: true, soundOn: false, holdsRole: true })).toBe(true);
    });

    it('shows on a second TV page so its tap can claim the sound', () => {
        expect(visible({ targetActive: true, soundOn: true, holdsRole: false })).toBe(true);
    });

    it('hides once this screen plays', () => {
        expect(visible({ targetActive: true, soundOn: true, holdsRole: true })).toBe(false);
    });

    it('never shows for a game on a real speaker', () => {
        expect(visible({ targetActive: false, soundOn: false, holdsRole: false })).toBe(false);
    });

    it('a clip waiting for the tap always shows it', () => {
        expect(visible({ targetActive: false, soundOn: true, holdsRole: true, clipWaiting: true })).toBe(true);
    });

    it('the TV prompt is translated everywhere', () => {
        for (const lang of LOCALES) {
            const gate = locale(lang).dashboard.soundGate;
            expect(gate.title, lang).toBeTruthy();
            expect(gate.button, lang).toBeTruthy();
            expect(gate.hint, lang).toBeTruthy();
        }
        expect(locale('de').dashboard.soundGate).toEqual({
            title: 'Musik läuft über diesen Bildschirm',
            button: 'Ton an',
            hint: 'Einmal mit der Fernbedienung bestätigen',
        });
    });
});

describe('sw.js keeps preview audio out of the cache (Deezer terms)', () => {
    const SRC = readSource('../sw.js');
    const isUncacheable = evaluate(
        [
            'var PREVIEW_AUDIO_HOSTS = /(^|\\.)(dzcdn\\.net|deezer\\.com|itunes\\.apple\\.com|mzstatic\\.com)$/;',
            declaration(SRC, 'isUncacheableAudio', 'sw.js'),
        ],
        'isUncacheableAudio',
        {},
    );
    const req = (destination = '') => ({ destination });

    it('skips every audio element request', () => {
        expect(isUncacheable(req('audio'), new URL('https://ha.local/beatify/static/x.mp3'))).toBe(true);
    });

    it('skips the preview hosts and the TTS proxy', () => {
        expect(isUncacheable(req(), new URL(CLIP))).toBe(true);
        expect(isUncacheable(req(), new URL('https://audio-ssl.itunes.apple.com/a.m4a'))).toBe(true);
        expect(isUncacheable(req(), new URL('https://ha.local/api/tts_proxy/abc.mp3'))).toBe(true);
    });

    it('leaves the app shell alone', () => {
        expect(isUncacheable(req('script'), new URL('https://ha.local/beatify/static/js/admin.min.js'))).toBe(false);
    });

    it('the shipped pattern is the one tested here', () => {
        expect(SRC).toContain('var PREVIEW_AUDIO_HOSTS = /(^|\\.)(dzcdn\\.net|deezer\\.com|itunes\\.apple\\.com|mzstatic\\.com)$/;');
    });
});
