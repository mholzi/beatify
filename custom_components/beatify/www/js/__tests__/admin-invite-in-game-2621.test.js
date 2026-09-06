/**
 * #2621 — a late guest must be invitable while the game runs.
 *
 * The join QR had exactly one trigger on the host page: `#home-qr-code` inside
 * `#home-view` (admin.html), and `renderAdminState` exits home-mode the moment
 * the phase leaves LOBBY. So from round 1 onward the host had nothing to tap,
 * even though `game/player_registry.py` accepts late joins and the serializer
 * keeps sending `join_url` in PLAYING and REVEAL. The fix puts a person-plus
 * button in each round header and points it at the existing `#qr-modal`.
 *
 * Two halves are asserted, because either one alone can regress silently:
 *
 *   1. the WIRING — `setupInviteTriggers()` attaches the real `openQRModal`
 *      (function identity, not a lookalike) to both ids, and
 *      `syncInviteTriggers()` keeps them hidden while no join URL is cached,
 *   2. the MARKUP — the shipped admin.html really carries those ids, inside
 *      the playing and reveal sections respectively, and admin.js really calls
 *      the two helpers.
 *
 * The vitest env is `node` with no jsdom, so the wiring half runs against a
 * minimal fake `document` — the same approach as admin-view-visibility-1868 and
 * player-lobby-qr-guard. The markup half reads the served sources from disk, as
 * dashboard-2130-end-stage does, so the test goes red if the button is deleted
 * from the HTML without the test being touched.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
    INVITE_TRIGGER_IDS,
    openQRModal,
    setupInviteTriggers,
    syncInviteTriggers,
} from '../admin/sections/qr-modal.js';
import { adminState } from '../admin/state.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(join(__dirname, '..', '..', 'admin.html'), 'utf8');
const ADMIN_JS = readFileSync(join(__dirname, '..', 'admin.js'), 'utf8');

/** Minimal stand-in for one button: records listeners + `hidden` toggling. */
function makeButton(initial = ['hidden']) {
    const classes = new Set(initial);
    return {
        listeners: {},
        addEventListener(type, fn) {
            (this.listeners[type] = this.listeners[type] || []).push(fn);
        },
        classList: {
            toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
            contains: (name) => classes.has(name),
        },
    };
}

/** A fake document exposing exactly the two invite buttons. */
function makeDoc(buttons) {
    return { getElementById: (id) => buttons[id] || null };
}

let buttons;
let doc;

beforeEach(() => {
    buttons = {};
    for (const id of INVITE_TRIGGER_IDS) buttons[id] = makeButton();
    doc = makeDoc(buttons);
    adminState.cachedQRUrl = null;
});

describe('#2621 in-game invite — wiring', () => {
    it('covers both the playing and the reveal header', () => {
        expect(INVITE_TRIGGER_IDS).toEqual(['admin-invite-playing', 'admin-invite-reveal']);
    });

    it('hangs every trigger on the shared openQRModal', () => {
        setupInviteTriggers(doc);
        for (const id of INVITE_TRIGGER_IDS) {
            expect(buttons[id].listeners.click).toHaveLength(1);
            // Identity, not just "some handler": a second QR implementation on
            // the admin page is exactly what #1589 consolidated away.
            expect(buttons[id].listeners.click[0]).toBe(openQRModal);
        }
    });

    it('survives a section whose button is missing', () => {
        delete buttons['admin-invite-reveal'];
        expect(() => setupInviteTriggers(doc)).not.toThrow();
        expect(buttons['admin-invite-playing'].listeners.click).toHaveLength(1);
    });

    it('stays hidden while no join URL is cached', () => {
        syncInviteTriggers(doc);
        for (const id of INVITE_TRIGGER_IDS) {
            expect(buttons[id].classList.contains('hidden')).toBe(true);
        }
    });

    it('appears as soon as the state frame carried a join URL', () => {
        adminState.cachedQRUrl = 'http://homeassistant.local:8123/beatify/play?game=abc';
        syncInviteTriggers(doc);
        for (const id of INVITE_TRIGGER_IDS) {
            expect(buttons[id].classList.contains('hidden')).toBe(false);
        }
    });
});

/** The slice of admin.html between a section's opening id and the next section. */
function sectionOf(id, nextId) {
    const start = HTML.indexOf(`id="${id}"`);
    expect(start, `#${id} missing from admin.html`).toBeGreaterThan(-1);
    const end = nextId === null ? HTML.length : HTML.indexOf(`id="${nextId}"`);
    expect(end, `#${nextId} missing from admin.html`).toBeGreaterThan(start);
    return HTML.slice(start, end);
}

describe('#2621 in-game invite — shipped markup', () => {
    it('puts the playing trigger inside #admin-playing-section', () => {
        expect(sectionOf('admin-playing-section', 'admin-control-bar'))
            .toContain('id="admin-invite-playing"');
    });

    it('puts the reveal trigger inside #admin-reveal-section', () => {
        expect(sectionOf('admin-reveal-section', 'admin-end-section'))
            .toContain('id="admin-invite-reveal"');
    });

    it('gives each icon-only button a translated accessible name', () => {
        // The button carries no visible text, so the name comes from an sr-only
        // span. It is a `data-i18n` span rather than a hard-coded `aria-label`
        // because initPageTranslations() translates textContent and title, but
        // has no aria-label branch — an aria-label would ship English to all
        // six locales.
        for (const id of INVITE_TRIGGER_IDS) {
            const btn = HTML.slice(HTML.indexOf(`id="${id}"`));
            const markup = btn.slice(0, btn.indexOf('</button>'));
            expect(markup).toContain('data-i18n-title="lobby.invitePlayers"');
            expect(markup).toContain('<span class="sr-only" data-i18n="lobby.invitePlayers">');
        }
    });

    it('wires and syncs the triggers from admin.js', () => {
        expect(ADMIN_JS).toContain('setupInviteTriggers()');
        expect(ADMIN_JS).toContain('syncInviteTriggers()');
        // The cache the modal reads must be fed by the live state frame, not
        // only by the home-view renderer that is gone once the game starts.
        expect(ADMIN_JS).toContain('adminState.cachedQRUrl = data.join_url');
    });
});
