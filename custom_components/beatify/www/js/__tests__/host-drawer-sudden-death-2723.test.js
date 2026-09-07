/**
 * #2723 — Sudden Death is reachable from the host's phone, and the guest can
 * see where they stand.
 *
 * Two halves, and they fail for different reasons:
 *
 *  1. **The drawer exists as a container.** The control bar carried six
 *     elements on 270 px and three issues of the same week (#2723, #2649,
 *     #2646) each wanted a seventh. The fix is not a seventh button but a
 *     drawer below the bar, and the test that matters is that it is built as a
 *     *container* — a body that further rows drop into — rather than as a
 *     Sudden Death control wearing a lid. If a later change collapses the body
 *     into the one row, the next issue is back to arguing about bar space.
 *
 *  2. **The standing line's model.** `suddenDeathStandingModel()` decides who
 *     counts and when names stop helping. Both are easy to get wrong in a way
 *     that only shows on somebody's phone during a party:
 *       - counting playoff spectators (#2612) reports "4 of 9 standing" in a
 *         game where five people were never eliminable,
 *       - printing nine names turns a line into a paragraph and pushes the
 *         reveal — the thing the guest is looking at — off the screen.
 *
 * The renderers themselves are DOM-bound and are covered by the markup
 * assertions below rather than a stubbed document; the decisions worth
 * guarding were deliberately moved out of them.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BEATIFY = join(__dirname, '..', '..', '..');

const PLAYER_HTML = readFileSync(join(BEATIFY, 'www', 'player.html'), 'utf8');
const PLAYER_GAME = readFileSync(join(BEATIFY, 'www', 'js', 'player-game.js'), 'utf8');
const PLAYER_CORE = readFileSync(join(BEATIFY, 'www', 'js', 'player-core.js'), 'utf8');
const STYLES = readFileSync(join(BEATIFY, 'www', 'css', 'styles.css'), 'utf8');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const locale = (code) =>
    JSON.parse(readFileSync(join(BEATIFY, 'www', 'i18n', `${code}.json`), 'utf8'));

// player-reveal.js reaches for browser globals at module scope (it is a page
// module, not a library), so the node env needs them stubbed BEFORE the import.
// Same approach player-game-state.test.js takes.
global.window = global.window || {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { search: '', href: 'http://localhost/beatify/player' },
};
global.URLSearchParams = global.URLSearchParams || URLSearchParams;
global.document = global.document || {
    getElementById: () => null,
    querySelector: () => null,
    createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} } }),
};
global.IntersectionObserver = global.IntersectionObserver || class {
    observe() {}
    disconnect() {}
};

// The model is pure; import it directly rather than through the DOM renderer.
const { suddenDeathStandingModel, SD_NAME_CAP } = await import('../player-reveal.js');

const player = (name, extra = {}) => ({ name, eliminated: false, ...extra });

describe('#2723 host drawer — built as a container, not a lid on one switch', () => {
    it('player.html carries a drawer body that is separate from its rows', () => {
        expect(PLAYER_HTML).toContain('id="host-drawer"');
        expect(PLAYER_HTML).toContain('id="host-drawer-grip"');
        expect(PLAYER_HTML).toContain('id="host-drawer-body"');
    });

    it('ships the body EMPTY in the markup — rows are rendered, not hard-coded', () => {
        // The moment a row is baked into the HTML, the drawer stops being a
        // container and #2649/#2646 are back to needing their own home.
        const body = PLAYER_HTML.match(
            /<div id="host-drawer-body"[^>]*>([\s\S]*?)<\/div>/
        );
        expect(body, 'host-drawer-body must exist as its own element').not.toBeNull();
        expect(body[1].trim()).toBe('');
    });

    it('the drawer sits above the control bar via a token, not a magic number', () => {
        // The bar's height and the drawer's offset have to move together; a
        // literal in one of the two places is how the drawer ends up covering
        // the buttons on the next padding change.
        expect(STYLES).toContain('--control-bar-h:');
        expect(STYLES).toMatch(/bottom:\s*calc\(var\(--control-bar-h\)/);
    });

    it('hiding the control bar also collapses the drawer', () => {
        // Otherwise a lobby gets a control panel for a game that is not running.
        const fn = PLAYER_GAME.match(
            /export function hideAdminControlBar\(\)[\s\S]*?\n}/
        );
        expect(fn).not.toBeNull();
        expect(fn[0]).toContain('hideHostDrawer()');
    });

    it('renders only for the host', () => {
        const fn = PLAYER_GAME.match(
            /export function renderHostDrawer\(data\)[\s\S]*?\n}/
        );
        expect(fn).not.toBeNull();
        expect(fn[0]).toMatch(/!state\.isAdmin/);
    });

    it('posts the inverse of the SERVER flag, never an optimistic local flip', () => {
        // Same rule as admin.js's toggle: the WS broadcast repaints, so a local
        // guess can only produce a switch that disagrees with the game.
        const fn = PLAYER_GAME.match(/function _renderSuddenDeathRow\([\s\S]*?\n}\n/);
        expect(fn).not.toBeNull();
        expect(fn[0]).toContain("'/beatify/api/sudden-death'");
        expect(fn[0]).toMatch(/classList\.contains\('is-on'\)/);
    });

    it('keeps the admin page floor: no arming below three survivors', () => {
        const fn = PLAYER_GAME.match(/function _renderSuddenDeathRow\([\s\S]*?\n}\n/);
        expect(fn[0]).toMatch(/remaining < 3/);
    });

    it('is re-rendered when the locale lands, because its subtitle is a sentence', () => {
        // A label can be swapped in place; generated prose has to be rebuilt.
        const block = PLAYER_CORE.match(
            /BeatifyI18n\.setLanguage\(data\.language\)[\s\S]*?\}\);/
        );
        expect(block).not.toBeNull();
        expect(block[0]).toContain('renderHostDrawer(data)');
    });
});

describe('#2723 standing line — who counts', () => {
    it('is silent when Sudden Death is off', () => {
        expect(
            suddenDeathStandingModel({ players: [player('Ana')] }, null)
        ).toBeNull();
    });

    it('counts survivors against contenders', () => {
        const data = {
            sudden_death_mode: true,
            players: [
                player('Markus'),
                player('Ana'),
                player('Lena', { eliminated: true }),
                player('Tom', { eliminated: true }),
            ],
        };
        const m = suddenDeathStandingModel(data, data.players[0]);
        expect(m.alive).toBe(2);
        expect(m.total).toBe(4);
        expect(m.amOut).toBe(false);
    });

    it('leaves playoff spectators out of BOTH numbers (#2612)', () => {
        // The regression this guards: counting them reports "2 of 5 standing"
        // in a game where three people were never eliminable to begin with.
        const data = {
            sudden_death_mode: true,
            players: [
                player('Markus'),
                player('Ana'),
                player('Lena', { eliminated: true }),
                player('Sam', { playoff_spectator: true }),
                player('Ute', { playoff_spectator: true }),
            ],
        };
        const m = suddenDeathStandingModel(data, data.players[0]);
        expect(m.alive).toBe(2);
        expect(m.total).toBe(3);
        expect(m.outNames).toEqual(['Lena']);
    });

    it('says nothing at all when every player is a spectator', () => {
        const data = {
            sudden_death_mode: true,
            players: [player('Sam', { playoff_spectator: true })],
        };
        expect(suddenDeathStandingModel(data, null)).toBeNull();
    });

    it('reports the reader as out when they are out', () => {
        const me = player('Tom', { eliminated: true });
        const data = { sudden_death_mode: true, players: [player('Ana'), me] };
        expect(suddenDeathStandingModel(data, me).amOut).toBe(true);
    });
});

describe('#2723 standing line — when names stop helping', () => {
    const withEliminated = (n) => ({
        sudden_death_mode: true,
        players: [
            player('Ana'),
            ...Array.from({ length: n }, (_, i) =>
                player(`Out${i + 1}`, { eliminated: true })
            ),
        ],
    });

    it('spells the names out up to the cap', () => {
        const m = suddenDeathStandingModel(withEliminated(SD_NAME_CAP), null);
        expect(m.outNames).toHaveLength(SD_NAME_CAP);
    });

    it('drops them one past it, keeping the counts', () => {
        const m = suddenDeathStandingModel(withEliminated(SD_NAME_CAP + 1), null);
        expect(m.outNames).toEqual([]);
        // The information is not lost — it moved into the count in front.
        expect(m.alive).toBe(1);
        expect(m.total).toBe(SD_NAME_CAP + 2);
    });

    it('has no names to print in the first round', () => {
        const m = suddenDeathStandingModel(withEliminated(0), null);
        expect(m.outNames).toEqual([]);
        expect(m.alive).toBe(1);
    });
});

describe('#2723 strings exist in every locale', () => {
    const ADMIN_KEYS = [
        'drawerTitle',
        'drawerOn',
        'drawerOff',
        'suddenDeathOnSub',
        'suddenDeathOffSub',
    ];
    const GAME_KEYS = ['sdYouAreIn', 'sdYouAreOut', 'sdStanding', 'sdOutNames'];

    it.each(LOCALES)('%s carries every new key', (code) => {
        const d = locale(code);
        for (const k of ADMIN_KEYS) {
            expect(d.admin?.[k], `admin.${k} missing in ${code}`).toBeTruthy();
        }
        for (const k of GAME_KEYS) {
            expect(d.game?.[k], `game.${k} missing in ${code}`).toBeTruthy();
        }
    });

    it.each(LOCALES)('%s keeps the placeholders the renderer substitutes', (code) => {
        const d = locale(code);
        expect(d.game.sdStanding).toContain('{alive}');
        expect(d.game.sdStanding).toContain('{total}');
        expect(d.game.sdOutNames).toContain('{names}');
    });

    it.each(LOCALES.filter((c) => c !== 'en'))(
        '%s actually translated the subtitle rather than copying English',
        (code) => {
            // The subtitle is the sentence that tells the host a non-submitter
            // counts as the slowest player. An untranslated copy leaves five of
            // six locales with the bare label the row exists to replace.
            expect(d(code).admin.suddenDeathOffSub).not.toBe(
                locale('en').admin.suddenDeathOffSub
            );
        }
    );

    function d(code) {
        return locale(code);
    }
});
