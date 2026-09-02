/**
 * #2506 — the join button must come back to life on every route to the join view.
 *
 * Tapping Join disables the button and relabels it "Joining…". Only the
 * join-timeout path ever put it back; leaving a game, a session takeover, a
 * failed reconnect and an unknown session all returned to the join view and
 * left a dead grey button still reading "Joining…". The guest's only way out
 * was to edit a letter of their own pre-filled name — and even then the label
 * stayed wrong.
 *
 * showView('join-view') now owns the reset, so these tests drive it there.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const joinBtn = { id: 'join-btn', disabled: true, textContent: 'Join Game' };
const nameInput = { id: 'name-input', value: '', focus: vi.fn() };
const views = {};

global.window = {
    BeatifyUtils: {
        t: (key) => (key === 'join.joinButton' ? 'Join Game' : key),
        showView: (all, id) => { views.shown = id; },
    },
    location: { search: '?game=abcd1234' },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: () => {},
};
global.document = {
    body: { classList: { toggle() {}, add() {}, remove() {} } },
    getElementById: (id) => {
        if (id === 'join-btn') return joinBtn;
        if (id === 'name-input') return nameInput;
        return null;
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
};
global.URLSearchParams = URLSearchParams;

const { showView, resetJoinButton, validateName } = await import('../player-utils.js');

/** The state the button is left in mid-join. */
function midJoin() {
    joinBtn.disabled = true;
    joinBtn.textContent = 'Joining...';
}

beforeEach(() => {
    nameInput.value = '';
    midJoin();
});

describe('#2506 showView(join-view) revives the button', () => {
    it('restores the label and enables it for a name that is still there', () => {
        nameInput.value = 'Alice';   // pre-filled after Leave

        showView('join-view');

        expect(joinBtn.textContent).toBe('Join Game');
        expect(joinBtn.disabled).toBe(false);
    });

    it('does not enable the button when the box is empty', () => {
        nameInput.value = '';

        showView('join-view');

        expect(joinBtn.textContent).toBe('Join Game');
        expect(joinBtn.disabled).toBe(true);
    });

    it('treats a box holding only spaces as empty', () => {
        nameInput.value = '   ';

        showView('join-view');

        expect(joinBtn.disabled).toBe(true);
    });

    it('leaves the button alone on any other view', () => {
        nameInput.value = 'Alice';

        showView('game-view');

        expect(joinBtn.textContent).toBe('Joining...');
        expect(joinBtn.disabled).toBe(true);
    });
});

describe('#2506 resetJoinButton on its own', () => {
    it('refuses a name that is too long, the same rule the input listener uses', () => {
        nameInput.value = 'x'.repeat(21);

        resetJoinButton();

        expect(joinBtn.disabled).toBe(true);
        expect(validateName(nameInput.value).valid).toBe(false);
    });

    it('accepts a name at the length limit', () => {
        nameInput.value = 'x'.repeat(20);

        resetJoinButton();

        expect(joinBtn.disabled).toBe(false);
    });
});
