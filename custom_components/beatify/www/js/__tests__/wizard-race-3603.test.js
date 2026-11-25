/**
 * #3603: the wizard's race flag only counts while Title & Artist is on
 * (mirrors the admin rule from #3591).
 */
import { describe, it, expect } from 'vitest';
import { raceModeFor } from '../wizard.js';

describe('wizard #3603: raceModeFor', () => {
    it('saved race without Title & Artist is off (the bug)', () => {
        expect(raceModeFor(false, true)).toBe(false);
    });

    it('race stays on when Title & Artist is on', () => {
        expect(raceModeFor(true, true)).toBe(true);
    });

    it('race off stays off; missing values are off', () => {
        expect(raceModeFor(true, false)).toBe(false);
        expect(raceModeFor(true, undefined)).toBe(false);
        expect(raceModeFor(undefined, true)).toBe(false);
    });
});
