/**
 * #2646 — the "End round N" card behind Next.
 *
 * The host taps Next in the middle of round 5 because the song is a cover, or
 * because Music Assistant is playing silence. That tap used to go straight to
 * `end_round()`: everyone who had not answered counted as wrong, their streaks
 * reset, and in Sudden Death one of them was eliminated — with no warning.
 *
 * Two things have to hold for the card to be worth its interruption:
 *
 *  1. It asks ONLY while the round is still running. Asking after the timer
 *     expired would put three choices in front of the host every round, which
 *     is the cost the design weighed and rejected.
 *  2. It names the consequence before it happens, with the server's numbers —
 *     and says the weaker sentence, rather than a wrong name, when the server
 *     could not work out who would go out.
 *
 * The module is injectable (clock, document), so these run against a fake DOM
 * and a fake clock — no jsdom.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
    noteRoundState, resetRoundState, secondsLeftNow, shouldAskBeforeEnding,
    subtitleFor, scoreConsequence, openRoundEndChoice, closeRoundEndChoice,
    renderVoidedBanner, VOID_REASON_LABELS,
} from '../round-end-choice.js';
import { VOID_ROUND_REASONS } from '../game-constants.js';

/** `t(key, fallback, params)` that renders the English fallback verbatim. */
function t(key, fallback, params) {
    let out = fallback;
    if (params) {
        Object.keys(params).forEach((name) => {
            out = out.split(`{${name}}`).join(String(params[name]));
        });
    }
    return out;
}

// --- a fake DOM, just wide enough for the card ------------------------------

function makeEl(id) {
    const listeners = {};
    const attrs = {};
    const el = {
        id,
        _text: '',
        hidden: false,
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
        _listenerCount(ev) { return (listeners[ev] || []).length; },
    };
    // Faithful enough for the one place it matters: setting textContent to ''
    // is how the chip row is emptied before it is repainted, and in a real DOM
    // that drops the children.
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
        'round-end-score-sub', 'round-end-void', 'round-end-keep',
        'round-end-reasons',
    ].forEach((id) => { els[id] = makeEl(id); });
    const backdrop = makeEl('backdrop');
    els['round-end-modal'].querySelector = (sel) =>
        (sel === '.modal-backdrop' ? backdrop : null);
    return {
        _backdrop: backdrop,
        getElementById: (id) => els[id] || null,
        createElement: () => makeEl(''),
        _el: (id) => els[id],
    };
}

const PREVIEW = {
    round: 5,
    player_count: 8,
    submitted_count: 3,
    counting_wrong: 5,
    streaks_breaking: 4,
    eliminated: 'Tom',
    elimination_possible: true,
};

function playing(overrides) {
    return Object.assign({
        phase: 'PLAYING',
        round: 5,
        seconds_remaining: 22,
        admin_round_end_preview: PREVIEW,
    }, overrides || {});
}

// ---------------------------------------------------------------------------

describe('when Next asks first (#2646)', () => {
    beforeEach(() => resetRoundState());

    it('asks while the round is still running', () => {
        noteRoundState(playing(), 1000);
        expect(shouldAskBeforeEnding(1000)).toBe(true);
    });

    it('does not ask once the timer has run out', () => {
        noteRoundState(playing({ seconds_remaining: 3 }), 1000);
        // Four seconds of wall time later: the round is over on its own terms.
        expect(shouldAskBeforeEnding(5000)).toBe(false);
    });

    it('does not ask on the reveal screen', () => {
        noteRoundState(playing(), 1000);
        noteRoundState({ phase: 'REVEAL', round: 5 }, 1100);
        expect(shouldAskBeforeEnding(1100)).toBe(false);
    });

    it('does not ask before any round has been seen', () => {
        expect(shouldAskBeforeEnding(1000)).toBe(false);
    });

    it('counts the round down between broadcasts', () => {
        // Broadcasts are event-driven; between two of them the server's
        // `seconds_remaining` goes stale by exactly the wall time that passed.
        noteRoundState(playing({ seconds_remaining: 22 }), 1000);
        expect(secondsLeftNow(1000)).toBe(22);
        expect(secondsLeftNow(11000)).toBe(12);
        expect(secondsLeftNow(99000)).toBe(0);
    });
});

describe('what the card says (#2646)', () => {
    it('names the consequences with the real numbers', () => {
        expect(scoreConsequence(PREVIEW, t)).toBe(
            '5 players count as wrong · 4 streaks break · Tom is eliminated',
        );
    });

    it('says somebody goes out when the server could not say who', () => {
        // Everybody answered: who is cut really does depend on the scoring
        // pass, so the weaker sentence is the honest one.
        const preview = Object.assign({}, PREVIEW, {
            eliminated: null, submitted_count: 8, counting_wrong: 0,
            streaks_breaking: 0,
        });
        expect(scoreConsequence(preview, t)).toBe(
            'in Sudden Death somebody is eliminated',
        );
    });

    it('does not threaten an elimination when Sudden Death is off', () => {
        const preview = Object.assign({}, PREVIEW, {
            eliminated: null, elimination_possible: false,
        });
        expect(scoreConsequence(preview, t)).toBe(
            '5 players count as wrong · 4 streaks break',
        );
    });

    it('says nothing rather than something wrong with no preview', () => {
        expect(scoreConsequence(null, t)).toBe('');
    });

    it('leads with the time left and how many have answered', () => {
        expect(subtitleFor(PREVIEW, 22, t)).toBe('22 seconds left · 3 of 8 have answered');
    });
});

describe('the three exits (#2646)', () => {
    let doc;

    beforeEach(() => {
        resetRoundState();
        doc = makeDoc();
        noteRoundState(playing(), 1000);
    });

    function open() {
        return openRoundEndChoice({ doc, t, secondsLeft: 22 });
    }

    it('heads the card with the running round', async () => {
        const answer = open();
        expect(doc._el('round-end-title').textContent).toBe('End round 5');
        doc._el('round-end-keep').click();
        await answer;
    });

    it('resolves "score" and sends no reason', async () => {
        const answer = open();
        doc._el('round-end-score').click();
        expect(await answer).toEqual({ choice: 'score', reason: null });
    });

    it('resolves "void" with no reason when the chips are skipped', async () => {
        const answer = open();
        doc._el('round-end-void').click();
        expect(await answer).toEqual({ choice: 'void', reason: null });
    });

    it('carries the picked reason chip', async () => {
        const answer = open();
        doc._el('round-end-reasons').children[1].click();
        doc._el('round-end-void').click();
        expect(await answer).toEqual({ choice: 'void', reason: VOID_ROUND_REASONS[1] });
    });

    it('lets a mis-tapped chip be taken back', async () => {
        const answer = open();
        const chip = doc._el('round-end-reasons').children[0];
        chip.click();
        chip.click();
        doc._el('round-end-void').click();
        expect(await answer).toEqual({ choice: 'void', reason: null });
    });

    it('keeps only one chip picked at a time', async () => {
        const answer = open();
        const chips = doc._el('round-end-reasons').children;
        chips[0].click();
        chips[2].click();
        doc._el('round-end-void').click();
        expect(await answer).toEqual({ choice: 'void', reason: VOID_ROUND_REASONS[2] });
        expect(chips[0].getAttribute('aria-pressed')).toBe('false');
    });

    it('resolves "keep" — the misfire exit sends nothing', async () => {
        const answer = open();
        doc._el('round-end-keep').click();
        expect(await answer).toEqual({ choice: 'keep', reason: null });
    });

    it('treats a backdrop tap as "keep"', async () => {
        const answer = open();
        doc._backdrop.click();
        expect(await answer).toEqual({ choice: 'keep', reason: null });
    });

    it('treats Escape (via closeRoundEndChoice) as "keep"', async () => {
        const answer = open();
        closeRoundEndChoice();
        expect(await answer).toEqual({ choice: 'keep', reason: null });
    });

    it('hides the card and drops its listeners once answered', async () => {
        const answer = open();
        expect(doc._el('round-end-modal').classList.contains('hidden')).toBe(false);
        doc._el('round-end-score').click();
        await answer;
        expect(doc._el('round-end-modal').classList.contains('hidden')).toBe(true);
        expect(doc._el('round-end-score')._listenerCount('click')).toBe(0);
        expect(doc._el('round-end-reasons').children[0]._listenerCount('click')).toBe(0);
    });

    it('offers exactly the reasons the server accepts', () => {
        open();
        const chips = doc._el('round-end-reasons').children;
        expect(chips.map((c) => c.dataset.reason)).toEqual(VOID_ROUND_REASONS);
        expect(chips.map((c) => c.textContent)).toEqual(
            VOID_ROUND_REASONS.map((r) => VOID_REASON_LABELS[r].fallback),
        );
        closeRoundEndChoice();
    });

    it('repaints the chips instead of stacking them across opens', async () => {
        let answer = open();
        doc._el('round-end-keep').click();
        await answer;
        answer = open();
        expect(doc._el('round-end-reasons').children).toHaveLength(
            VOID_ROUND_REASONS.length,
        );
        doc._el('round-end-keep').click();
        await answer;
    });

    it('falls back to scoring when the markup is missing', async () => {
        // An old cached page has no card. Silently doing nothing would leave
        // the host tapping a dead button; scoring is what Next always did.
        const bare = { getElementById: () => null, createElement: makeEl };
        expect(await openRoundEndChoice({ doc: bare, t })).toEqual({
            choice: 'score', reason: null,
        });
    });
});

describe('the reveal banner (#2646)', () => {
    it('shows only for a voided round', () => {
        const doc = makeDoc();
        const banner = makeEl('reveal-voided');
        banner.classList.add('hidden');
        doc.getElementById = (id) => (id === 'reveal-voided' ? banner : null);

        renderVoidedBanner(doc, 'reveal-voided', { round_voided: true });
        expect(banner.classList.contains('hidden')).toBe(false);

        renderVoidedBanner(doc, 'reveal-voided', { round_voided: false });
        expect(banner.classList.contains('hidden')).toBe(true);
    });

    it('is a no-op when the element is absent', () => {
        const doc = { getElementById: () => null };
        expect(() => renderVoidedBanner(doc, 'nope', { round_voided: true })).not.toThrow();
    });
});
