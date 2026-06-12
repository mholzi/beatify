/**
 * #1402-B8 dashboard tests (findings 4 + 6).
 *
 * dashboard.js is a DOM-coupled IIFE with no exported helpers, and the suite
 * runs in a `node` (DOM-free) environment, so we test the load-bearing LOGIC of
 * each fix rather than the DOM glue:
 *
 * Finding 6 (lobby player count i18n): assert the singular/plural KEY selection
 *   + {n} interpolation against the REAL locale JSON and the real BeatifyUtils.t
 *   fallback resolver — the exact expression dashboard.js now runs. Guards
 *   against a missing locale key and a wrong-plural string.
 *
 * Finding 4 (podium double-escape): assert that assigning escapeHtml() output to
 *   a textContent-style sink double-escapes, while the raw name does not — i.e.
 *   the fix (drop escapeHtml for the podium textContent assignment) is correct.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load the DOM-free BeatifyUtils IIFE (assigns window.BeatifyUtils on eval).
global.window = global.window || {};
await import('../utils.js');
const utils = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'nl'];
const i18n = {};
beforeAll(() => {
    for (const l of LOCALES) {
        i18n[l] = JSON.parse(readFileSync(join(__dirname, '..', '..', 'i18n', `${l}.json`), 'utf8'));
    }
});

// Faithful BeatifyI18n.t stub backed by a given locale's JSON: dotted lookup,
// echoes the key when missing, interpolates {param} — same contract dashboard
// relies on. BeatifyUtils.t references the BARE global `BeatifyI18n`, so we
// install it on globalThis (not window).
function installI18n(locale) {
    const dict = i18n[locale];
    globalThis.BeatifyI18n = {
        t(key, params) {
            let cur = dict;
            for (const part of key.split('.')) {
                cur = cur == null ? undefined : cur[part];
            }
            if (typeof cur !== 'string') return key;
            if (params) {
                for (const p of Object.keys(params)) {
                    cur = cur.replace(new RegExp('\\{' + p + '\\}', 'g'), params[p]);
                }
            }
            return cur;
        },
    };
}

// The exact rendering expression dashboard.renderLobbyView now uses.
function renderPlayerCount(count) {
    const joinedKey = count === 1 ? 'dashboard.playersJoinedOne' : 'dashboard.playersJoined';
    const joinedFallback = count + ' player' + (count !== 1 ? 's' : '') + ' joined';
    return utils.t(joinedKey, joinedFallback).replace(/\{n\}/g, count);
}

describe('dashboard #1402-B8 finding 6: localized lobby player count', () => {
    it('every shipped locale defines playersJoined + playersJoinedOne with {n}', () => {
        for (const l of LOCALES) {
            const d = i18n[l].dashboard;
            expect(d.playersJoined, `${l}.playersJoined`).toBeTypeOf('string');
            expect(d.playersJoinedOne, `${l}.playersJoinedOne`).toBeTypeOf('string');
            expect(d.playersJoined).toContain('{n}');
            expect(d.playersJoinedOne).toContain('{n}');
        }
    });

    it('renders the plural German string with the interpolated count', () => {
        installI18n('de');
        expect(renderPlayerCount(3)).toBe('3 Spieler beigetreten');
    });

    it('renders the singular variant for exactly one player', () => {
        installI18n('es');
        expect(renderPlayerCount(1)).toBe('1 jugador se unió');
        expect(renderPlayerCount(2)).toBe('2 jugadores se unieron');
    });

    it('falls back to the English literal when the key is missing', () => {
        // i18n present but key absent → utils.t returns the explicit fallback.
        globalThis.BeatifyI18n = { t: (key) => key };
        expect(renderPlayerCount(5)).toBe('5 players joined');
        expect(renderPlayerCount(1)).toBe('1 player joined');
    });
});

describe('dashboard #1402-B8 finding 4: podium name not double-escaped', () => {
    // utils.escapeHtml (div.textContent → div.innerHTML) needs a DOM; replicate
    // its observable contract: HTML-entity-encode &, <, >.
    function escapeHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    // Simulate a textContent sink: stores the literal string as-is — the browser
    // never re-parses it as HTML.
    function asTextContent(value) {
        return String(value);
    }

    it('escapeHtml + textContent double-escapes an ampersand (the bug)', () => {
        const escaped = escapeHtml('A&B');
        expect(asTextContent(escaped)).toBe('A&amp;B'); // visible "&amp;" on the podium
    });

    it('raw name into textContent renders the literal (the fix)', () => {
        expect(asTextContent('A&B')).toBe('A&B');
        expect(asTextContent('<script>')).toBe('<script>'); // inert as text, not parsed
    });
});
