/**
 * #1402-B8 finding 9 regression test for wizard.js lights hydration.
 *
 * Re-entering the wizard must NOT re-enable party lights the user explicitly
 * disabled (stored enabled:false). The lights level-up should only hydrate ON
 * when explicitly enabled, or when entities are configured with no explicit
 * flag at all (legacy/implied-on) — mirroring the TTS hydration rule.
 */
import { describe, it, expect } from 'vitest';
import { lightsLevelUpEnabledFromStored } from '../wizard.js';

describe('wizard #1402-B8: lightsLevelUpEnabledFromStored', () => {
    it('explicit enabled:true → on', () => {
        expect(lightsLevelUpEnabledFromStored({ enabled: true, lights: [] })).toBe(true);
    });

    it('explicit enabled:false with configured lights → OFF (the bug)', () => {
        // The old condition returned true here, silently re-enabling lights.
        expect(lightsLevelUpEnabledFromStored({ enabled: false, lights: ['light.a', 'light.b'] })).toBe(false);
    });

    it('no explicit flag + configured lights → implied on (legacy)', () => {
        expect(lightsLevelUpEnabledFromStored({ lights: ['light.a'] })).toBe(true);
    });

    it('no explicit flag + no lights → off', () => {
        expect(lightsLevelUpEnabledFromStored({ lights: [] })).toBe(false);
        expect(lightsLevelUpEnabledFromStored({})).toBe(false);
    });

    it('null / undefined store → off', () => {
        expect(lightsLevelUpEnabledFromStored(null)).toBe(false);
        expect(lightsLevelUpEnabledFromStored(undefined)).toBe(false);
    });
});
