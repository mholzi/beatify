/**
 * #2649 — the client half: three steps and a line that reports first.
 *
 * Two decisions are worth holding still here.
 *
 * **The two "on" steps carry the entity list back.** Switching the lights off
 * drops the service on the server, and the entity list lives inside it. If the
 * payload for "subtle" or "full show" omitted the ids, off would be a one-way
 * door — the host silences the hallway at 10pm and cannot bring the lights
 * back. That is the issue's own trap, pointing the other way.
 *
 * **A step name that is not "subtle" is the full show, never a third thing.**
 * `intensity` reaches `configure_party_lights` unchecked; an unknown value
 * would produce lights in a state no design ever described.
 *
 * The rendering itself is DOM-bound and is held by the markup assertions —
 * the decisions were deliberately moved out of it.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// player-game.js is a page module; stub the browser globals before importing.
global.WebSocket = global.WebSocket || { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.window = global.window || {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { search: '' },
};
global.URLSearchParams = global.URLSearchParams || URLSearchParams;
global.IntersectionObserver = global.IntersectionObserver || class {
    observe() {}
    disconnect() {}
};
global.document = global.document || {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} }, style: {} }),
    body: { classList: { add() {}, remove() {} } },
};

const { partyLightPayload, prettifyEntityId } = await import('../player-game.js');

const __dirname = dirname(fileURLToPath(import.meta.url));
const BEATIFY = join(__dirname, '..', '..', '..');
const PLAYER_HTML = readFileSync(join(BEATIFY, 'www', 'player.html'), 'utf8');
const PLAYER_GAME = readFileSync(join(BEATIFY, 'www', 'js', 'player-game.js'), 'utf8');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const locale = (code) =>
    JSON.parse(readFileSync(join(BEATIFY, 'www', 'i18n', `${code}.json`), 'utf8'));

const LIGHTS = { configured: true, active: true, intensity: 'party', entity_ids: ['light.flur', 'light.wohnzimmer'] };

describe('#2649 the light steps', () => {
    it('off asks the server to disable, and asks for nothing else', () => {
        const msg = partyLightPayload('off', LIGHTS);
        expect(msg.action).toBe('set_party_lights');
        expect(msg.enabled).toBe(false);
        // No entity list: the server's disable path takes none, and sending
        // one would invite a reader to think it re-configures.
        expect(msg.entity_ids).toBeUndefined();
    });

    it('subtle sends the stored entity list back', () => {
        const msg = partyLightPayload('subtle', LIGHTS);
        expect(msg.enabled).toBe(true);
        expect(msg.intensity).toBe('subtle');
        expect(msg.entity_ids).toEqual(['light.flur', 'light.wohnzimmer']);
    });

    it('full show sends them too — otherwise off is a one-way door', () => {
        const msg = partyLightPayload('party', LIGHTS);
        expect(msg.enabled).toBe(true);
        expect(msg.intensity).toBe('party');
        expect(msg.entity_ids).toEqual(['light.flur', 'light.wohnzimmer']);
    });

    it('an unknown step is the full show, never a third intensity', () => {
        // `intensity` reaches configure_party_lights unchecked.
        expect(partyLightPayload('bright', LIGHTS).intensity).toBe('party');
    });

    it('survives a state block with no entity list', () => {
        expect(partyLightPayload('subtle', {}).entity_ids).toEqual([]);
        expect(partyLightPayload('subtle', null).entity_ids).toEqual([]);
    });
});

describe('#2649 naming the rooms', () => {
    it('turns an entity id into something a host recognises', () => {
        expect(prettifyEntityId('light.wohnzimmer')).toBe('Wohnzimmer');
        expect(prettifyEntityId('light.flur_decke')).toBe('Flur decke');
    });

    it('does not blow up on nonsense', () => {
        expect(prettifyEntityId('')).toBe('');
        expect(prettifyEntityId(null)).toBe('');
    });
});

describe('#2649 the line and the row', () => {
    it('the line sits above the round and is a button, not a label', () => {
        // It reports first and is the way in second — so it has to be pressable.
        expect(PLAYER_HTML).toMatch(/<button[^>]*id="party-lights-line"/);
    });

    it('the line is host-only', () => {
        const fn = PLAYER_GAME.match(
            /export function renderPartyLightsLine\(data\)[\s\S]*?\n}/
        );
        expect(fn).not.toBeNull();
        expect(fn[0]).toContain('!state.isAdmin');
    });

    it('nothing is drawn when lights were never configured', () => {
        const fn = PLAYER_GAME.match(
            /export function renderPartyLightsLine\(data\)[\s\S]*?\n}/
        );
        expect(fn[0]).toContain('lights.configured');
    });

    it('the row lands in the drawer built for it by #2723', () => {
        const fn = PLAYER_GAME.match(/function _renderPartyLightsRow\([\s\S]*?\n}\n/);
        expect(fn).not.toBeNull();
        expect(fn[0]).toContain("getElementById('host-drawer-body')");
        // The drawer was built as a container precisely so this costs a row.
        expect(fn[0]).toContain('body.appendChild(row)');
    });

    it('names the rooms only while they still fit on a line', () => {
        const fn = PLAYER_GAME.match(
            /export function renderPartyLightsLine\(data\)[\s\S]*?\n}/
        );
        expect(fn[0]).toMatch(/names\.length <= 3/);
    });
});

describe('#2649 copy exists in every locale', () => {
    const KEYS = [
        'lightsRowTitle', 'lightsOff', 'lightsSubtle', 'lightsFull',
        'lightsOffSub', 'lightsSubtleSub', 'lightsFullSub',
        'lightsLineOff', 'lightsLineOnRooms', 'lightsLineOnCount',
    ];

    it.each(LOCALES)('%s carries every key', (code) => {
        const admin = locale(code).admin;
        for (const k of KEYS) {
            expect(admin?.[k], `admin.${k} missing in ${code}`).toBeTruthy();
        }
    });

    it.each(LOCALES)('%s keeps the count placeholder', (code) => {
        expect(locale(code).admin.lightsLineOnCount).toContain('{count}');
    });

    it.each(LOCALES)('%s keeps the strings free of markup', (code) => {
        // A translated string carrying <b> is a trap for the next locale that
        // gets it slightly wrong; the emphasis is applied by the renderer.
        for (const k of KEYS) {
            expect(locale(code).admin[k]).not.toMatch(/<[a-z]/i);
        }
    });

    it.each(LOCALES.filter((c) => c !== 'en'))(
        '%s translated the middle step rather than copying English',
        (code) => {
            // "Subtle" is the step the whole issue turns on. An untranslated
            // copy leaves five rooms out of six without the option that helps.
            expect(locale(code).admin.lightsSubtleSub).not.toBe(
                locale('en').admin.lightsSubtleSub
            );
        }
    );
});
