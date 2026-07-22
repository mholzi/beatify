/**
 * The lobby meta line must show the duration the SERVER is running (#1867).
 *
 * `round_duration` is fixed by `create_game` and no endpoint changes it for a
 * live game, so every settings edit made after the lobby was minted is inert.
 * The chip used to render those edits as though they had taken effect — first
 * from the stored blob, then (after the previous fix) from `selectedDuration`,
 * which the wizard also rewrites post-create. Both sources are client-side, so
 * neither could ever contradict the browser's own intent.
 */

import { describe, it, expect } from 'vitest';
import { roundDurationLabel } from '../admin/util.js';

describe('roundDurationLabel (#1867)', () => {
    it('shows the server value when a game is running', () => {
        const state = { selectedDuration: 45, currentGame: { round_duration: 30 } };
        expect(roundDurationLabel(state)).toBe('30s → 45s next');
    });

    it('shows one number when server and local intent agree', () => {
        const state = { selectedDuration: 45, currentGame: { round_duration: 45 } };
        expect(roundDurationLabel(state)).toBe('45s');
    });

    it('falls back to local intent when no game exists', () => {
        // Nothing to disagree with yet — the next game really will use this.
        const state = { selectedDuration: 60, currentGame: null };
        expect(roundDurationLabel(state)).toBe('60s');
    });

    it('falls back when the payload predates the server-side echo', () => {
        // A server that has not been updated sends active_game without the
        // field; showing "undefineds" would be worse than the old behaviour.
        const state = { selectedDuration: 45, currentGame: { phase: 'LOBBY' } };
        expect(roundDurationLabel(state)).toBe('45s');
    });

    it('renders a float duration as a whole number', () => {
        // The server types round_duration as float, so 45 can arrive as 45.0.
        const state = { selectedDuration: 45, currentGame: { round_duration: 45.0 } };
        expect(roundDurationLabel(state)).toBe('45s');
    });

    it('does not treat a non-numeric round_duration as truth', () => {
        const state = { selectedDuration: 45, currentGame: { round_duration: '30' } };
        expect(roundDurationLabel(state)).toBe('45s');
    });

    it('surfaces the divergence that #1867 could not show', () => {
        // The exact reported shape: lobby said 45, server ran 30. The old
        // label was "45s" and looked correct from every screen.
        const reported = { selectedDuration: 45, currentGame: { round_duration: 30.0 } };
        expect(roundDurationLabel(reported)).toContain('30s');
    });
});
