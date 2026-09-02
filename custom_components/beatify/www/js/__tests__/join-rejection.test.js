/**
 * #2499 — telling a refused join apart from a mid-game error.
 *
 * When the server refuses a join it answers with an error code and keeps the
 * socket open. The client used to fall through to the generic handler, which
 * writes the message onto the submit button of the hidden game view, so the
 * guest saw nothing and the join button stayed disabled on "Joining…" for good.
 *
 * The fix is a recovery path, and the interesting part is its condition. The
 * obvious signal — state.playerName — does not work: player-core.js sets it
 * optimistically when the socket opens, before any acknowledgement, so it is
 * already truthy while the join is still in flight. A guard written against it
 * would never fire, and the bug would look fixed while nothing changed. These
 * tests pin that distinction so it cannot be reintroduced.
 */
import { describe, it, expect } from 'vitest';

global.window = global.window || {};
global.window.location = global.window.location || { search: '', href: '' };
global.window.matchMedia = global.window.matchMedia
    || (() => ({ matches: false, addEventListener: () => {} }));
global.document = global.document || { getElementById: () => null };
global.URLSearchParams = global.URLSearchParams || URLSearchParams;

const { isJoinRejection, JOIN_REJECTED_CODES, state } =
    await import('../player-utils.js');

describe('isJoinRejection — the four codes the server refuses a join with', () => {
    it.each(['NAME_TAKEN', 'NAME_INVALID', 'GAME_FULL', 'GAME_ENDED'])(
        'treats %s as a refused join while one is in flight',
        (code) => {
            expect(isJoinRejection(code, true)).toBe(true);
        },
    );

    it('lists exactly those four', () => {
        expect(JOIN_REJECTED_CODES).toEqual([
            'NAME_TAKEN',
            'NAME_INVALID',
            'GAME_FULL',
            'GAME_ENDED',
        ]);
    });
});

describe('isJoinRejection — codes that are not about joining', () => {
    it.each(['ROUND_EXPIRED', 'ALREADY_SUBMITTED', 'NOT_ADMIN', 'SESSION_TAKEOVER', 'ELIMINATED'])(
        'leaves %s to the in-game handlers even during a join',
        (code) => {
            expect(isJoinRejection(code, true)).toBe(false);
        },
    );
});

describe('isJoinRejection — the flag is what gates it', () => {
    it('does not treat GAME_ENDED as a refused join once the player is in', () => {
        // The same code arrives when a game finishes around a player who is
        // already playing. That must still land on the end view.
        expect(isJoinRejection('GAME_ENDED', false)).toBe(false);
    });

    it('ignores a rejection code when no join is pending', () => {
        expect(isJoinRejection('NAME_TAKEN', false)).toBe(false);
    });

    it('treats a missing flag as no join pending', () => {
        expect(isJoinRejection('NAME_TAKEN', undefined)).toBe(false);
    });
});

describe('the shared state carries the flag', () => {
    it('declares joinPending, defaulting to false', () => {
        // Declared rather than created implicitly on first assignment, so the
        // shape of the state object stays readable.
        expect(state).toHaveProperty('joinPending');
        expect(state.joinPending).toBe(false);
    });

    it('still carries playerName, which is why the flag is needed', () => {
        // playerName is set before the acknowledgement arrives, so its presence
        // cannot mean "the join succeeded". Kept as a reminder next to the flag.
        expect(state).toHaveProperty('playerName');
    });
});
