/**
 * #3055 — the TV answer counter counted eliminated, spectator and sat-out
 * players. The phone (player-game.js) and the server (player_registry.py)
 * both leave them out, so in Sudden Death or after the host sat somebody out
 * the TV showed e.g. "5/8" and never filled up. The shipped renderRoundStats
 * runs here for real (see helpers/js-source.js).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');
const SNIPPETS = [declaration(DASHBOARD, 'renderRoundStats', 'dashboard.js')];

let submissionsEl;
let meterEl;
let render;

beforeEach(() => {
    submissionsEl = { textContent: '' };
    meterEl = {
        hidden: false,
        classList: { toggle: (cls, on) => { if (cls === 'hidden') meterEl.hidden = !!on; } },
    };
    render = evaluate(SNIPPETS, 'renderRoundStats', {
        document: { getElementById: (id) => (id === 'dashboard-submissions' ? submissionsEl : id === 'dashboard-submissions-meter' ? meterEl : null) },
        debug: () => {},
    });
});

const p = (name, extra) => ({ name, submitted: false, ...extra });

describe('#3055 TV answer counter', () => {
    it('counts every player in a plain game', () => {
        const players = [p('A', { submitted: true }), p('B'), p('C', { submitted: true })];
        render({ players }, players);
        expect(submissionsEl.textContent).toBe('2/3');
    });

    it('leaves out eliminated players', () => {
        const players = [p('A', { submitted: true }), p('B', { submitted: true }), p('C', { eliminated: true })];
        render({ players }, players);
        expect(submissionsEl.textContent).toBe('2/2');
    });

    it('leaves out playoff spectators', () => {
        const players = [p('A', { submitted: true }), p('B', { submitted: true }), p('C', { playoff_spectator: true })];
        render({ players }, players);
        expect(submissionsEl.textContent).toBe('2/2');
    });

    it('leaves out guests the host sat out', () => {
        const players = [p('A', { submitted: true }), p('B', { sat_out_by_host: true })];
        render({ players }, players);
        expect(submissionsEl.textContent).toBe('1/1');
    });

    it('does not count a submission from an out-of-round player', () => {
        const players = [p('A'), p('B', { eliminated: true, submitted: true })];
        render({ players }, players);
        expect(submissionsEl.textContent).toBe('0/1');
    });
});

describe('#3563 submissions chip in Title & Artist race mode', () => {
    const players = [p('A'), p('B', { submitted: true })];

    it('hides the whole chip when race mode is on', () => {
        render({ players, title_artist_mode: true, title_artist_race_mode: true }, players);
        expect(meterEl.hidden).toBe(true);
    });

    it('shows the chip with the count when race mode is off', () => {
        render({ players, title_artist_mode: true, title_artist_race_mode: false }, players);
        expect(meterEl.hidden).toBe(false);
        expect(submissionsEl.textContent).toBe('1/2');
    });

    it('shows the chip when the race field is absent', () => {
        render({ players }, players);
        expect(meterEl.hidden).toBe(false);
        expect(submissionsEl.textContent).toBe('1/2');
    });

    it('shows the chip again in the next non-race round', () => {
        render({ players, title_artist_mode: true, title_artist_race_mode: true }, players);
        expect(meterEl.hidden).toBe(true);
        render({ players }, players);
        expect(meterEl.hidden).toBe(false);
    });
});
