/**
 * #3396 — after a network error while creating the room, the home card kept
 * saying "Creating room…", Start stayed enabled and the speaker line showed the
 * raw entity id.
 *
 * The room-card settle step is cut out of the shipped admin.js and run against
 * a small DOM fake; the pure helpers are imported.
 */
import { describe, it, expect } from 'vitest';
import { readSource, block, evaluate } from './helpers/js-source.js';
import { roomCardFailure, readableEntityId, speakerLabelFor } from '../admin/setup-sync.js';

const ADMIN = readSource('admin.js');

function el() {
    const classes = new Set();
    const attrs = {};
    const listeners = {};
    return {
        textContent: '', disabled: false, dataset: {},
        classList: {
            add: (c) => classes.add(c), remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
        setAttribute: (k, v) => { attrs[k] = v; },
        removeAttribute: (k) => { delete attrs[k]; },
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
        addEventListener: (t, fn) => { listeners[t] = fn; },
        // A disabled button swallows clicks, as in the browser.
        click() { if (!this.disabled && listeners.click) listeners.click(); },
        listeners,
    };
}

function room({ game = null, inFlight = false, failure = null } = {}) {
    const dom = { 'home-qr-loading': el(), 'home-start-game': el() };
    dom['home-qr-loading'].textContent = 'Creating room…';
    const adminState = { currentGame: game, _startInFlight: inFlight, _createFailure: failure };
    const calls = { retried: 0 };
    const home = evaluate(
        [`const home = { ${block(ADMIN, 'settleRoomCard() {', 'admin.js')} };`],
        'home',
        {
            adminState, roomCardFailure,
            tr: (_k, fallback) => fallback,
            document: { getElementById: (id) => dom[id] },
            window: { BeatifyHome: { startSession: () => { calls.retried += 1; } } },
        },
    );
    return { dom, home, calls };
}

describe('#3396 room card after a failed create', () => {
    it('network error: shows the error, keeps Start off, offers a retry', () => {
        const { dom, home, calls } = room({ failure: 'network' });
        dom['home-start-game'].disabled = true;
        home.settleRoomCard();
        const loading = dom['home-qr-loading'];
        expect(loading.textContent).toBe('Network error. Please try again.');
        expect(loading.classList.contains('hidden')).toBe(false);
        expect(dom['home-start-game'].disabled).toBe(true);
        loading.listeners.click();
        expect(calls.retried).toBe(1);
    });

    it('a rejected create stops saying "Creating room…" and leaves Start as the retry', () => {
        const { dom, home } = room({ failure: null });
        dom['home-start-game'].disabled = true;
        home.settleRoomCard();
        expect(dom['home-qr-loading'].classList.contains('hidden')).toBe(true);
        expect(dom['home-start-game'].disabled).toBe(false);
    });

    it('does nothing while a create is still pending or a room exists', () => {
        for (const opts of [{ inFlight: true }, { game: { join_url: 'http://x/play' } }]) {
            const { dom, home } = room(opts);
            home.settleRoomCard();
            expect(dom['home-qr-loading'].textContent).toBe('Creating room…');
        }
        expect(roomCardFailure(null, true, 'network')).toBe('none');
    });
});

describe('#3396 speaker line without a friendly name', () => {
    it('reads the entity id as words instead of printing it raw', () => {
        expect(readableEntityId('media_player.esszimmer')).toBe('Esszimmer');
        expect(readableEntityId('media_player.living_room')).toBe('Living Room');
        expect(speakerLabelFor('media_player.esszimmer', [])).toBe('🔊 Esszimmer');
    });

    it('still prefers the friendly name', () => {
        const players = [{ entity_id: 'media_player.esszimmer', friendly_name: 'Dining Room' }];
        expect(speakerLabelFor('media_player.esszimmer', players)).toBe('🔊 Dining Room');
    });
});
