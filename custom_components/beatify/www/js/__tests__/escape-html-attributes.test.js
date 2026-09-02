/**
 * #2505 — escapeHtml must be safe in attribute context, not only in text nodes.
 *
 * It used to route through a detached div (textContent in, innerHTML out),
 * which encodes & < > and leaves the quote characters alone. That is correct
 * for a text node and wrong for an attribute value, where a quote ends the
 * value. Three call sites interpolate player names into attributes —
 * data-player on the lobby tile, data-name on the leaderboard row, aria-label
 * on the reveal dot axis — and a player name is free text: the server checks
 * only its length.
 *
 * There are two copies of the helper: the ES-module export in player-utils.js
 * and the IIFE global in utils.js, which the TV dashboard uses. Both are
 * covered here, because a fix to one and not the other leaves the dashboard
 * exposed.
 */
import { describe, it, expect } from 'vitest';

// Both modules read browser globals at eval time — utils.js assigns to
// window.BeatifyUtils, player-utils.js reads it back — so the global has to
// exist before either is loaded. Static imports are hoisted above this line,
// hence the dynamic imports.
global.window = global.window || {};
global.window.location = global.window.location || { search: '', href: '' };
global.URLSearchParams = global.URLSearchParams || URLSearchParams;
// player-utils.js caches a handful of elements at module scope; null is fine,
// nothing under test touches them.
global.document = global.document || { getElementById: () => null };
global.window.matchMedia = global.window.matchMedia
    || (() => ({ matches: false, addEventListener: () => {} }));
await import('../utils.js');
const globalEscape = global.window.BeatifyUtils.escapeHtml;
const { escapeHtml } = await import('../player-utils.js');

const IMPLEMENTATIONS = [
    ['player-utils.js (module)', escapeHtml],
    ['utils.js (global)', globalEscape],
];

describe.each(IMPLEMENTATIONS)('escapeHtml — %s', (_name, esc) => {
    it('still encodes the text-node characters', () => {
        expect(esc('<b>&</b>')).toBe('&lt;b&gt;&amp;&lt;/b&gt;');
    });

    it('encodes the ampersand first, so nothing is double-escaped', () => {
        // A naive order turns < into &lt; and then the & of &lt; into &amp;lt;
        expect(esc('&<')).toBe('&amp;&lt;');
    });

    it('encodes the double quote', () => {
        expect(esc('a"b')).toBe('a&quot;b');
    });

    it('encodes the single quote', () => {
        expect(esc("a'b")).toBe('a&#39;b');
    });

    it('leaves no bare quote in a name built from both', () => {
        const out = esc(`x"y'z`);
        expect(out).not.toContain('"');
        expect(out).not.toContain("'");
    });

    it('leaves an ordinary name untouched', () => {
        expect(esc('Anna')).toBe('Anna');
    });

    it('returns an empty string for null and undefined', () => {
        expect(esc(null)).toBe('');
        expect(esc(undefined)).toBe('');
    });
});

describe('escapeHtml — the property the call sites depend on', () => {
    // Rebuilt exactly as player-lobby.js:126 and player-utils.js:893 do it:
    // a double-quoted attribute value assembled by string concatenation.
    function tile(name) {
        return '<div class="player-tile" data-player="' + escapeHtml(name) + '">' +
            '<span>' + escapeHtml(name) + '</span></div>';
    }

    it('a name carrying a quote cannot close the attribute and open another', () => {
        const html = tile('x" data-injected="1');
        // The name's quote is encoded, so exactly one data-player attribute is
        // opened and closed, and the injected name never becomes markup.
        expect(html).toContain('data-player="x&quot; data-injected=&quot;1"');
        expect(html).not.toContain('data-injected="1"');
    });

    it('a name shaped like an event handler stays inside the value', () => {
        const html = tile(`x" onclick="boom()`);
        expect(html).not.toContain(' onclick="boom()"');
        expect(html).toContain('&quot; onclick=&quot;boom()');
    });

    it('an apostrophe in a real name survives as an entity, not as a break', () => {
        const html = tile("O'Brien");
        expect(html).toContain('data-player="O&#39;Brien"');
    });
});
