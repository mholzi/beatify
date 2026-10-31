/**
 * #2586 — timer and difficulty between two rounds, on both host surfaces.
 *
 * A chip tap sends the action and changes nothing locally: what the sheet shows
 * comes from the state broadcast. The row and the sheet are host-only, there is
 * no row on the last reveal, and the room's notice names only what changed.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { locale, readSource } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const {
    setupRoundSettings, renderRoundSettings, closeRoundSettings,
    roundSettingsRowText, roundSettingsAction,
} = await import('../round-settings.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

function setLocale(lang) {
    global.BeatifyI18n = translator(locale(lang));
}

/** Just enough DOM for the sheet: ids, classes, listeners, focus. */
function makeDoc() {
    const byId = {};
    const doc = { activeElement: null };
    function node(id) {
        const classes = new Set();
        const listeners = {};
        const n = {
            id, dataset: {}, attrs: {}, kids: [], textContent: '', isConnected: true,
            classList: {
                add: (c) => classes.add(c),
                remove: (c) => classes.delete(c),
                contains: (c) => classes.has(c),
                toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
            },
            setAttribute(k, v) { n.attrs[k] = v; },
            addEventListener(ev, fn) { listeners[ev] = fn; },
            fire(ev, arg) { listeners[ev](arg); },
            click() { listeners.click && listeners.click(); },
            focus() { doc.activeElement = n; },
            appendChild(kid) { n.kids.push(kid); return kid; },
            querySelector: (sel) => (sel === '.modal-backdrop' ? byId.backdrop : null),
            querySelectorAll: () => [],
        };
        if (id) byId[id] = n;
        return n;
    }
    ['round-settings-row', 'round-settings-row-text', 'round-settings-sheet', 'backdrop',
        'round-settings-timer', 'round-settings-difficulty', 'round-settings-difficulty-block',
        'round-settings-hint', 'round-settings-foot', 'round-settings-next', 'next']
        .forEach(node);
    byId['round-settings-sheet'].classList.add('hidden');
    doc.getElementById = (id) => byId[id] || null;
    doc.createElement = () => node(null);
    doc.querySelectorAll = (sel) => (sel.includes('timer')
        ? byId['round-settings-timer'].kids
        : byId['round-settings-difficulty'].kids);
    doc.byId = byId;
    return doc;
}

const REVEAL = {
    phase: 'REVEAL',
    round: 3,
    next_round_settings: { round_duration: 45, difficulty: 'normal' },
};

describe('#2586 row and sheet', () => {
    let doc;
    let sent;

    beforeEach(() => {
        setLocale('en');
        doc = makeDoc();
        sent = [];
        setupRoundSettings({ doc, send: (a) => sent.push(a), nextButtonId: 'next' });
    });

    const chip = (group, value) => doc.byId[`round-settings-${group}`].kids
        .find((k) => k.dataset.value === value);
    const sheetHidden = () => doc.byId['round-settings-sheet'].classList.contains('hidden');
    const rowHidden = () => doc.byId['round-settings-row'].classList.contains('hidden');

    it('names the current state in the closed row', () => {
        renderRoundSettings(REVEAL, true);
        expect(rowHidden()).toBe(false);
        expect(doc.byId['round-settings-row-text'].textContent).toBe('⏱ 45s · Normal');
    });

    it('offers 30/45/60 and Easy/Normal/Hard, marked with aria-pressed', () => {
        renderRoundSettings(REVEAL, true);
        expect(doc.byId['round-settings-timer'].kids.map((k) => k.textContent))
            .toEqual(['30s', '45s', '60s']);
        expect(doc.byId['round-settings-difficulty'].kids.map((k) => k.textContent))
            .toEqual(['Easy', 'Normal', 'Hard']);
        expect(chip('timer', '45').attrs['aria-pressed']).toBe('true');
        expect(chip('timer', '30').attrs['aria-pressed']).toBe('false');
        expect(chip('difficulty', 'normal').classList.contains('chip--active')).toBe(true);
    });

    it('a chip tap sends the action and repaints only from the broadcast', () => {
        renderRoundSettings(REVEAL, true);
        chip('timer', '30').click();
        expect(sent).toEqual([{ type: 'admin', action: 'set_round_settings', timer: 30 }]);
        expect(chip('timer', '30').attrs['aria-pressed']).toBe('false');

        renderRoundSettings({
            ...REVEAL, next_round_settings: { round_duration: 30, difficulty: 'normal' },
        }, true);
        expect(chip('timer', '30').attrs['aria-pressed']).toBe('true');
        expect(chip('timer', '45').attrs['aria-pressed']).toBe('false');
    });

    it('shows the band hint for the selected difficulty and the next round number', () => {
        renderRoundSettings({
            ...REVEAL, next_round_settings: { round_duration: 45, difficulty: 'hard' },
        }, true);
        expect(doc.byId['round-settings-hint'].textContent)
            .toBe('Sharp: 10 pts for an exact year, 3 pts within ±2 years, otherwise 0.');
        expect(doc.byId['round-settings-foot'].textContent)
            .toBe('Applies from round 4. Scores so far stay.');
    });

    it('stays away for a guest and on the last reveal, and closes an open sheet', () => {
        renderRoundSettings(REVEAL, false);
        expect(rowHidden()).toBe(true);

        renderRoundSettings(REVEAL, true);
        doc.byId['round-settings-row'].click();
        expect(sheetHidden()).toBe(false);
        renderRoundSettings({ ...REVEAL, next_round_settings: null }, true);
        expect(rowHidden()).toBe(true);
        expect(sheetHidden()).toBe(true);
    });

    it('title and artist mode has no difficulty row', () => {
        renderRoundSettings({ ...REVEAL, title_artist_mode: true }, true);
        expect(doc.byId['round-settings-row-text'].textContent).toBe('⏱ 45s');
        expect(doc.byId['round-settings-difficulty-block'].classList.contains('hidden')).toBe(true);
    });

    it('closes on a tap outside, on Escape and when the phase moves on', () => {
        renderRoundSettings(REVEAL, true);
        const row = doc.byId['round-settings-row'];
        row.click();
        doc.byId.backdrop.click();
        expect(sheetHidden()).toBe(true);

        row.click();
        doc.byId['round-settings-sheet'].fire('keydown', { key: 'Escape', preventDefault() {} });
        expect(sheetHidden()).toBe(true);

        row.click();
        closeRoundSettings();
        expect(sheetHidden()).toBe(true);
    });

    it('Next Round in the sheet clicks the surface button and closes', () => {
        renderRoundSettings(REVEAL, true);
        let clicked = 0;
        doc.byId.next.click = () => { clicked += 1; };
        doc.byId['round-settings-row'].click();
        doc.byId['round-settings-next'].click();
        expect(clicked).toBe(1);
        expect(sheetHidden()).toBe(true);
    });
});

describe('#2586 room notice', () => {
    const BOTH = { round_duration: 30, difficulty: 'hard', close_points: 3, close_range: 2 };

    beforeEach(() => setLocale('en'));

    it('phone wording', () => {
        expect(U.roundSettingsNoticeText(BOTH, false)).toBe('⏱ Now 30s · Hard');
    });

    it('TV wording', () => {
        expect(U.roundSettingsNoticeText(BOTH, true))
            .toBe('⏱ Now 30 seconds · Hard: 3 points within ±2 years');
    });

    it('mentions only what changed', () => {
        expect(U.roundSettingsNoticeText({ round_duration: 60 }, true)).toBe('⏱ Now 60 seconds');
        expect(U.roundSettingsNoticeText(
            { difficulty: 'easy', close_points: 5, close_range: 7 }, false,
        )).toBe('⏱ Now Easy');
    });

    it('says nothing without a notice', () => {
        expect(U.roundSettingsNoticeText(null, false)).toBe('');
        expect(U.roundSettingsNoticeText(undefined, true)).toBe('');
    });

    it.each(LOCALES)('%s renders whole, with no key or placeholder left', (lang) => {
        setLocale(lang);
        for (const long of [false, true]) {
            const text = U.roundSettingsNoticeText(BOTH, long);
            expect(text).not.toMatch(/[{}]|admin\./);
            expect(text).toContain('30');
        }
    });
});

describe('#2586 markup and copy', () => {
    it.each(['admin.html', 'player.html'])('%s carries the row and the sheet', (page) => {
        const html = readSource(`../${page}`);
        for (const id of ['round-settings-row', 'round-settings-sheet', 'round-settings-timer',
            'round-settings-difficulty', 'round-settings-hint', 'round-settings-foot',
            'round-settings-next']) {
            expect(html).toContain(`id="${id}"`);
        }
        expect(html.indexOf('id="round-settings-row"'))
            .toBeLessThan(html.indexOf('class="reveal-admin-buttons"'));
    });

    it('the action helper names the field', () => {
        expect(roundSettingsAction('difficulty', 'hard'))
            .toEqual({ type: 'admin', action: 'set_round_settings', difficulty: 'hard' });
    });

    it('row text falls back through the same labels', () => {
        setLocale('de');
        expect(roundSettingsRowText({ round_duration: 60, difficulty: 'hard' }, false))
            .toBe(`⏱ 60s · ${locale('de').admin.hard}`);
    });

    it.each(LOCALES)('%s has every new key', (lang) => {
        const { admin } = locale(lang);
        for (const key of ['roundSettingsChange', 'roundSettingsTitle', 'roundSettingsTime',
            'roundSettingsFoot', 'roundSettingsNotice', 'roundSettingsNoticeSeconds',
            'roundSettingsNoticeBands']) {
            expect(admin[key], key).toBeTruthy();
        }
        if (lang !== 'en') {
            expect(admin.roundSettingsTitle).not.toBe(locale('en').admin.roundSettingsTitle);
        }
    });
});
