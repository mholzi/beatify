/**
 * #3160 — the "Select Speaker" button in the start-game error banner (#2269).
 *
 * The first version expanded and scrolled to `#media-players`, but the banner
 * only shows after a start from the home view, where
 * `body.home-mode #media-players { display: none !important }` hides that
 * section: the tap did nothing. The old test used fake nodes and could not see
 * the CSS. The action must leave the home view and open wizard step 1, like
 * "edit setup", so this suite asserts those calls and that both buttons use them.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { openSetupStepOne } from '../admin/util.js';

const ADMIN_JS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'admin.js'), 'utf8');

describe('openSetupStepOne (#3160)', () => {
    it('leaves the home view first, then opens wizard step 1', () => {
        const calls = [];
        openSetupStepOne({
            BeatifyHome: { exit: () => calls.push('home.exit') },
            BeatifyWizard: { show: (step) => calls.push(`wizard.show(${step})`) },
        });
        expect(calls).toEqual(['home.exit', 'wizard.show(1)']);
    });

    it('does not throw when the wizard or home view is not available', () => {
        expect(() => openSetupStepOne({})).not.toThrow();
    });
});

describe('start-failed banner wiring (#3160)', () => {
    it('points "Select Speaker" at the setup wizard, not the hidden section', () => {
        const fn = ADMIN_JS.slice(ADMIN_JS.indexOf('function showSpeakerSetupError'));
        const body = fn.slice(0, fn.indexOf('\n}\n'));
        expect(body).toContain('openSetupStepOne(window)');
        expect(body).not.toContain('expandMediaPlayersSection');
    });
});
