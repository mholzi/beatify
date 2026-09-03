/**
 * #2534 — an empty podium stand must be hidden in ALL THREE views.
 *
 * Beatify renders the same podium three times: the player page
 * (`player-end.js`), the TV dashboard (`dashboard.js`) and the host's own admin
 * page (`admin.js`). #2130 fixed the first two. The third kept showing "---"
 * and 0 on a plinth nobody stood on, and every test written for #2130 stayed
 * green — they only ever looked at the two files that had been touched.
 *
 * So this file is deliberately not another per-view test. It asserts the same
 * behaviour across all three, and it guards the mechanism each view uses:
 *
 *   - `player-end.js`  -> `hidden`               (styles.css)
 *   - `dashboard.js`   -> `podium-place--empty`  (dashboard.css)
 *   - `admin.js`       -> `hidden`               (styles.css)
 *
 * The class-vs-stylesheet guard is the one that matters most. admin.html loads
 * styles.min.css and library.min.css — NOT dashboard.css — so copying
 * dashboard's `podium-place--empty` into admin.js would toggle a class with no
 * rule behind it: green in a naive test, unchanged on screen.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const js = (f) => readFileSync(join(__dirname, '..', f), 'utf8');
const css = (f) => readFileSync(join(__dirname, '..', '..', 'css', f), 'utf8');
const html = (f) => readFileSync(join(__dirname, '..', '..', f), 'utf8');

const ADMIN_JS = js('admin.js');
const DASHBOARD_JS = js('dashboard.js');
const PLAYER_END_JS = js('player-end.js');
const STYLES_CSS = css('styles.css');
const DASHBOARD_CSS = css('dashboard.css');
const ADMIN_HTML = html('admin.html');

/** One podium slot, close enough to the DOM for the three renderers. */
function makeSlot(place) {
    const classes = new Set(['podium-place', `podium-${place}`]);
    const placeEl = {
        classList: {
            toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
            contains: (name) => classes.has(name),
        },
    };
    const child = () => ({
        textContent: '',
        closest: (sel) => (sel === '.podium-place' ? placeEl : null),
    });
    return { placeEl, nameEl: child(), scoreEl: child(), avatarEl: child() };
}

/** Verbatim per-place body of showAdminEndView() — admin.js. */
function renderAdmin(slot, entry) {
    const { nameEl, scoreEl } = slot;
    if (nameEl) nameEl.textContent = entry ? entry.name : '---';
    if (scoreEl) scoreEl.textContent = entry ? entry.score : '0';
    let placeEl = (nameEl || scoreEl);
    placeEl = placeEl && placeEl.closest ? placeEl.closest('.podium-place') : null;
    if (placeEl) placeEl.classList.toggle('hidden', !entry);
}

/** Verbatim per-place body of renderEndView() — dashboard.js. */
function renderDashboard(slot, player) {
    const { nameEl, scoreEl, avatarEl } = slot;
    if (nameEl) nameEl.textContent = player ? player.name : '---';
    if (scoreEl) scoreEl.textContent = player ? player.score : '0';
    let placeEl = (nameEl || scoreEl || avatarEl);
    placeEl = placeEl && placeEl.closest ? placeEl.closest('.podium-place') : null;
    if (placeEl) placeEl.classList.toggle('podium-place--empty', !player);
}

/** Verbatim per-place body of updateEndView() — player-end.js. */
function renderPlayer(slot, player) {
    const { nameEl, scoreEl, placeEl } = slot;
    if (placeEl) placeEl.classList.toggle('hidden', !player);
    if (nameEl) nameEl.textContent = player ? player.name : '---';
    if (scoreEl) scoreEl.textContent = player ? player.score : '0';
}

const VIEWS = [
    { name: 'admin', render: renderAdmin, marker: 'hidden' },
    { name: 'dashboard', render: renderDashboard, marker: 'podium-place--empty' },
    { name: 'player', render: renderPlayer, marker: 'hidden' },
];

/** Which of the three stands end up hidden for a given leaderboard. */
function hiddenStands(view, leaderboard) {
    const out = [];
    [1, 2, 3].forEach((place) => {
        const slot = makeSlot(place);
        view.render(slot, leaderboard.find((p) => p.rank === place));
        if (slot.placeEl.classList.contains(view.marker)) out.push(place);
    });
    return out;
}

describe.each(VIEWS)('#2534 — empty stands in the $name view', (view) => {
    it('hides the third stand in a two-player game', () => {
        expect(hiddenStands(view, [
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
        ])).toEqual([3]);
    });

    it('hides the second and third stand in a one-player game', () => {
        expect(hiddenStands(view, [{ rank: 1, name: 'Sandra', score: 162 }])).toEqual([2, 3]);
    });

    it('hides nothing once three ranks are filled', () => {
        expect(hiddenStands(view, [
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
            { rank: 3, name: 'Kim', score: 90 },
        ])).toEqual([]);
    });

    it('hides both lower stands when two players tie for first', () => {
        // Ranks skip on a tie (see game/state_leaderboard.py): [80, 80] gives
        // ranks [1, 1] and no rank 2 at all. This is the case the live test
        // walked into — a full room and two empty plinths.
        expect(hiddenStands(view, [
            { rank: 1, name: 'Sandra', score: 80 },
            { rank: 1, name: 'Aaron', score: 80 },
        ])).toEqual([2, 3]);
    });

    it('still writes the placeholders it always wrote', () => {
        // Hiding the stand is a display decision; what it holds is unchanged.
        const slot = makeSlot(3);
        view.render(slot, undefined);
        expect(slot.nameEl.textContent).toBe('---');
        expect(slot.scoreEl.textContent).toBe('0');
    });
});

describe('#2534 — the shipped code carries the fix in all three views', () => {
    it('admin.js hides the stand', () => {
        expect(ADMIN_JS).toContain("closest('.podium-place')");
        expect(ADMIN_JS).toContain("classList.toggle('hidden', !entry)");
    });

    it('dashboard.js still hides the stand', () => {
        expect(DASHBOARD_JS).toContain("classList.toggle('podium-place--empty', !player)");
    });

    it('player-end.js still hides the stand', () => {
        expect(PLAYER_END_JS).toContain("classList.toggle('hidden', !player)");
    });
});

describe('#2534 — every toggled class has a rule on the page that toggles it', () => {
    it('styles.css defines .hidden strongly enough to beat .podium-place', () => {
        // .podium-place is display:flex, so a plain `display:none` would lose.
        expect(STYLES_CSS).toMatch(/\.hidden\s*\{\s*display:\s*none\s*!important;?\s*\}/);
    });

    it('admin.html loads the stylesheet that defines .hidden', () => {
        expect(ADMIN_HTML).toMatch(/css\/styles(\.min)?\.css/);
    });

    it('admin.html does NOT load dashboard.css', () => {
        // The reason admin.js must not borrow `podium-place--empty`: the class
        // would carry no rule here, and the stand would stay visible while the
        // code looked fixed.
        expect(ADMIN_HTML).not.toMatch(/css\/dashboard(\.min)?\.css/);
    });

    it('dashboard.css defines the class dashboard.js toggles', () => {
        expect(DASHBOARD_CSS).toMatch(/\.podium-place--empty\s*\{\s*display:\s*none;?\s*\}/);
    });
});
