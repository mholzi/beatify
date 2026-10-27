/**
 * #3261 — "Play a different song" on the "End round N" card.
 *
 * The fourth choice sits directly above "Do not score it" so the host sees
 * both exits with what each costs. It resolves to 'swap', both host surfaces
 * send `skip_song` for it, and it is disabled with a reason once the pool has
 * no unplayed song left.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    resetRoundState, openRoundEndChoice, swapConsequence, canSwapSong,
} from '../round-end-choice.js';

const here = dirname(fileURLToPath(import.meta.url));
const www = join(here, '..', '..');

function t(key, fallback, params) {
    let out = fallback;
    if (params) {
        Object.keys(params).forEach((name) => {
            out = out.split(`{${name}}`).join(String(params[name]));
        });
    }
    return out;
}

function makeEl(id) {
    const listeners = {};
    const attrs = {};
    const el = {
        id,
        _text: '',
        hidden: false,
        disabled: false,
        dataset: {},
        children: [],
        classList: {
            _set: new Set(id === 'round-end-modal' ? ['hidden'] : []),
            add(c) { this._set.add(c); },
            remove(c) { this._set.delete(c); },
            contains(c) { return this._set.has(c); },
            toggle(c, on) { if (on) this.add(c); else this.remove(c); },
        },
        setAttribute(k, v) { attrs[k] = v; },
        getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
        addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
        removeEventListener(ev, fn) {
            listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn);
        },
        appendChild(child) { this.children.push(child); },
        querySelector() { return null; },
        click() { (listeners.click || []).slice().forEach((fn) => fn()); },
    };
    Object.defineProperty(el, 'textContent', {
        get() { return el._text; },
        set(v) { el._text = v; el.children = []; },
    });
    return el;
}

function makeDoc() {
    const els = {};
    [
        'round-end-modal', 'round-end-title', 'round-end-sub', 'round-end-score',
        'round-end-score-sub', 'round-end-swap', 'round-end-swap-sub',
        'round-end-void', 'round-end-keep', 'round-end-reasons',
    ].forEach((id) => { els[id] = makeEl(id); });
    return {
        getElementById: (id) => els[id] || null,
        createElement: () => makeEl(''),
        _el: (id) => els[id],
    };
}

const PREVIEW = { round: 4, player_count: 5, submitted_count: 3, songs_left: 12 };

describe('the swap choice on the card (#3261)', () => {
    beforeEach(() => resetRoundState());

    it('resolves to swap', async () => {
        const doc = makeDoc();
        const answer = openRoundEndChoice({ doc, t, preview: PREVIEW, round: 4, secondsLeft: 23 });
        expect(doc._el('round-end-swap').disabled).toBe(false);
        doc._el('round-end-swap').click();
        await expect(answer).resolves.toEqual({ choice: 'swap', reason: null });
    });

    it('names the cost with the number of guesses', () => {
        const doc = makeDoc();
        openRoundEndChoice({ doc, t, preview: PREVIEW, round: 4, secondsLeft: 23 });
        expect(doc._el('round-end-swap-sub').textContent).toBe(
            'Same round, new song from the playlist. The timer restarts, the 3 guesses are deleted, no points lost.',
        );
        doc._el('round-end-keep').click();
    });

    it('is disabled with a reason when no unplayed song is left', async () => {
        const doc = makeDoc();
        const answer = openRoundEndChoice({
            doc, t, preview: { ...PREVIEW, songs_left: 0 }, round: 4, secondsLeft: 23,
        });
        const btn = doc._el('round-end-swap');
        expect(btn.disabled).toBe(true);
        expect(doc._el('round-end-swap-sub').textContent).toBe('No unplayed songs left');
        // A click that slips through a disabled button still does nothing.
        btn.click();
        doc._el('round-end-keep').click();
        await expect(answer).resolves.toEqual({ choice: 'keep', reason: null });
    });

    it('singular, plural and none read differently', () => {
        expect(swapConsequence({ submitted_count: 1 }, t)).toContain('1 guess is deleted');
        expect(swapConsequence({ submitted_count: 4 }, t)).toContain('the 4 guesses are deleted');
        expect(swapConsequence({ submitted_count: 0 }, t)).not.toContain('deleted');
    });

    it('stays open when an older server sends no count', () => {
        expect(canSwapSong({})).toBe(true);
        expect(canSwapSong(null)).toBe(true);
        expect(canSwapSong({ songs_left: 0 })).toBe(false);
    });
});

describe('both host surfaces (#3261)', () => {
    const read = (rel) => readFileSync(join(www, ...rel.split('/')), 'utf8');

    ['admin.html', 'player.html'].forEach((page) => {
        it(`${page} puts the swap choice directly above "Do not score it"`, () => {
            const html = read(page);
            const swap = html.indexOf('id="round-end-swap"');
            const voidBtn = html.indexOf('id="round-end-void"');
            const score = html.indexOf('id="round-end-score"');
            expect(swap).toBeGreaterThan(score);
            expect(swap).toBeLessThan(voidBtn);
            const between = html.slice(swap, voidBtn);
            expect(between.match(/<button/g)).toHaveLength(1);
            expect(html).toContain('id="round-end-swap-sub"');
        });
    });

    ['js/admin.js', 'js/player-game.js'].forEach((file) => {
        it(`${file} sends skip_song for the swap choice`, () => {
            const src = read(file);
            const at = src.indexOf("answer.choice === 'swap'");
            expect(at).toBeGreaterThan(-1);
            const body = file === 'js/admin.js'
                ? src.slice(at, at + 400)
                : src.slice(src.indexOf('function sendSkipSong'), src.indexOf('function sendSkipSong') + 400);
            expect(body).toContain("action: 'skip_song'");
        });
    });

    it('the phone resets the guess and shows the toast on song_skipped', () => {
        const src = read('js/player-core.js');
        const at = src.indexOf("data.type === 'song_skipped'");
        expect(at).toBeGreaterThan(-1);
        const body = src.slice(at, at + 600);
        expect(body).toContain('resetSubmissionState()');
        expect(body).toContain("game.songSkippedToast");
    });
});

describe('new strings in every locale (#3261)', () => {
    const KEYS = [
        ['admin', 'roundEndSwap'], ['admin', 'roundEndSwapSub'],
        ['admin', 'roundEndSwapSubOne'], ['admin', 'roundEndSwapSubNone'],
        ['admin', 'roundEndSwapEmpty'], ['game', 'songSkippedToast'],
    ];
    ['en', 'de', 'es', 'fr', 'it', 'nl'].forEach((locale) => {
        it(`${locale} has them`, () => {
            const data = JSON.parse(readFileSync(join(www, 'i18n', `${locale}.json`), 'utf8'));
            KEYS.forEach(([section, key]) => {
                expect(typeof data[section][key]).toBe('string');
                expect(data[section][key].length).toBeGreaterThan(0);
            });
            expect(data.game.songSkippedToast).toContain('{n}');
            expect(data.admin.roundEndSwapSub).toContain('{n}');
            expect(data.errors.host.SKIP_SONG_PLAYING_ONLY).toBeTruthy();
            expect(data.errors.host.NO_SONGS_LEFT_TO_SKIP).toBeTruthy();
        });
    });

    it('German says what the design says', () => {
        const de = JSON.parse(readFileSync(join(www, 'i18n', 'de.json'), 'utf8'));
        expect(de.admin.roundEndSwap).toBe('Anderen Song spielen');
        expect(de.admin.roundEndSwapSub.split('{n}').join('3')).toBe(
            'Gleiche Runde, neuer Song aus der Playlist. Uhr startet neu, die 3 Tipps werden gelöscht, keine Punkte weg.',
        );
        expect(de.game.songSkippedToast.split('{n}').join('4')).toBe('Neuer Song · Runde 4 läuft neu');
    });
});
