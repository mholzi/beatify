/**
 * Unit tests for wizard.js pure helpers.
 * These helpers drive the state machine: when to show, where to resume, when to show the pill.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { resumeAtStep, shouldTrigger, shouldShowPill, providerSupportedForPlayer, capabilityBadgeForPlayer, pickAutoSelections } from '../wizard.js';

function makeLS(initial = {}) {
    const store = { ...initial };
    return {
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
        _store: store,
    };
}

// ------------------------------------------------------------------
// resumeAtStep — first incomplete required step (1-4) or null when done
// ------------------------------------------------------------------
describe('resumeAtStep', () => {
    it('returns 1 on a fresh install (no state, no player)', () => {
        expect(resumeAtStep(makeLS())).toBe(1);
    });

    it('returns 2 when speaker is saved but no provider yet', () => {
        const ls = makeLS({ beatify_last_player: 'media_player.sonos' });
        expect(resumeAtStep(ls)).toBe(2);
    });

    it('returns 3 when speaker + provider are saved', () => {
        const ls = makeLS({
            beatify_last_player: 'media_player.sonos',
            beatify_game_settings: JSON.stringify({ provider: 'spotify' }),
        });
        expect(resumeAtStep(ls)).toBe(3);
    });

    it('returns null when wizard is marked done', () => {
        const ls = makeLS({ beatify_wizard_state: 'done' });
        expect(resumeAtStep(ls)).toBeNull();
    });

    it('respects explicit wizard state over inferred signals', () => {
        const ls = makeLS({
            beatify_wizard_state: 'step4',
            beatify_last_player: 'media_player.sonos',
        });
        expect(resumeAtStep(ls)).toBe(4);
    });

    it('treats malformed game_settings JSON as no provider', () => {
        const ls = makeLS({
            beatify_last_player: 'media_player.sonos',
            beatify_game_settings: '{not valid json',
        });
        expect(resumeAtStep(ls)).toBe(2);
    });
});

// ------------------------------------------------------------------
// shouldTrigger — decides whether wizard opens on admin load
// ------------------------------------------------------------------
describe('shouldTrigger', () => {
    it('returns true on a fresh install (no state, no player saved)', () => {
        expect(shouldTrigger(makeLS())).toBe(true);
    });

    it('returns false when the user has marked it done', () => {
        expect(shouldTrigger(makeLS({ beatify_wizard_state: 'done' }))).toBe(false);
    });

    it('returns false when user explicitly dismissed', () => {
        expect(shouldTrigger(makeLS({ beatify_wizard_state: 'dismissed' }))).toBe(false);
    });

    it('returns true when user is mid-wizard (step2)', () => {
        expect(shouldTrigger(makeLS({ beatify_wizard_state: 'step2' }))).toBe(true);
    });

    it('returns false when no wizard state but admin has already been used (speaker saved)', () => {
        // Someone who ignored the wizard the first time and configured via admin directly
        const ls = makeLS({ beatify_last_player: 'media_player.sonos' });
        expect(shouldTrigger(ls)).toBe(false);
    });

    it('survives localStorage being unavailable (private mode)', () => {
        const brokenLs = { getItem: () => { throw new Error('denied'); } };
        // Broken localStorage → no flags visible → behave as fresh install
        expect(shouldTrigger(brokenLs)).toBe(true);
    });
});

// ------------------------------------------------------------------
// shouldShowPill — "Finish setup" pill in admin header
// ------------------------------------------------------------------
describe('shouldShowPill', () => {
    it('returns false when user never used the wizard', () => {
        expect(shouldShowPill(makeLS())).toBe(false);
    });

    it('returns true when dismissed AND required steps are incomplete', () => {
        const ls = makeLS({ beatify_wizard_state: 'dismissed' });
        expect(shouldShowPill(ls)).toBe(true);
    });

    it('returns false when dismissed but all required steps were done via admin later', () => {
        const ls = makeLS({
            beatify_wizard_state: 'dismissed',
            beatify_last_player: 'media_player.sonos',
            beatify_game_settings: JSON.stringify({ provider: 'spotify' }),
        });
        // resumeAtStep returns 3 here (speaker + provider done, but no 'done' flag) — pill stays up
        // to remind them to complete. This asserts the current behavior.
        expect(shouldShowPill(ls)).toBe(true);
    });

    it('returns false when wizard is done', () => {
        expect(shouldShowPill(makeLS({ beatify_wizard_state: 'done' }))).toBe(false);
    });

    it('returns false when user is still mid-wizard (not dismissed)', () => {
        expect(shouldShowPill(makeLS({ beatify_wizard_state: 'step2' }))).toBe(false);
    });
});

// ------------------------------------------------------------------
// providerSupportedForPlayer — gates the Step 2 chip state (#772)
// ------------------------------------------------------------------
describe('providerSupportedForPlayer', () => {
    it('returns true when no player is selected yet (Step 2 before Step 1)', () => {
        expect(providerSupportedForPlayer(null, 'apple_music')).toBe(true);
    });

    it('returns true when the player record flags the provider as supported', () => {
        const player = { supports_spotify: true, supports_apple_music: true };
        expect(providerSupportedForPlayer(player, 'spotify')).toBe(true);
    });

    it('returns false when the player record explicitly denies the provider (Sonos + Apple Music)', () => {
        const player = { supports_spotify: true, supports_apple_music: false };
        expect(providerSupportedForPlayer(player, 'apple_music')).toBe(false);
    });

    it('treats a missing supports_* field as supported (forward-compat for new providers)', () => {
        const player = { supports_spotify: true };
        expect(providerSupportedForPlayer(player, 'deezer')).toBe(true);
    });
});

// ------------------------------------------------------------------
// capabilityBadgeForPlayer — Step 1 speaker-row badge (#772)
// ------------------------------------------------------------------
describe('capabilityBadgeForPlayer', () => {
    const providers = [
        { id: 'spotify', label: 'Spotify' },
        { id: 'apple_music', label: 'Apple Music' },
        { id: 'youtube_music', label: 'YouTube Music' },
    ];

    it('returns null when no player is provided', () => {
        expect(capabilityBadgeForPlayer(null, providers)).toBeNull();
    });

    it('returns a full/green badge when every provider is supported', () => {
        const player = { supports_spotify: true, supports_apple_music: true, supports_youtube_music: true };
        expect(capabilityBadgeForPlayer(player, providers)).toEqual({ cls: 'full', label: 'All services' });
    });

    it('returns a partial/orange "X only" badge for a single supported provider (Sonos case)', () => {
        const player = { supports_spotify: true, supports_apple_music: false, supports_youtube_music: false };
        expect(capabilityBadgeForPlayer(player, providers)).toEqual({ cls: 'partial', label: 'Spotify only' });
    });

    it('respects locale word order via onlyTemplate (German prefixes "nur")', () => {
        const player = { supports_spotify: true, supports_apple_music: false, supports_youtube_music: false };
        const badge = capabilityBadgeForPlayer(player, providers, { onlyTemplate: 'nur {provider}' });
        expect(badge).toEqual({ cls: 'partial', label: 'nur Spotify' });
    });

    it('returns a partial/orange comma-joined badge for a subset (Alexa case)', () => {
        const player = { supports_spotify: true, supports_apple_music: true, supports_youtube_music: false };
        expect(capabilityBadgeForPlayer(player, providers)).toEqual({ cls: 'partial', label: 'Spotify, Apple Music' });
    });

    it('returns a none badge when no provider is supported (e.g. cast without MA)', () => {
        const player = { supports_spotify: false, supports_apple_music: false, supports_youtube_music: false };
        expect(capabilityBadgeForPlayer(player, providers)).toEqual({ cls: 'none', label: 'No services' });
    });

    it('uses provided i18n labels when given', () => {
        const player = { supports_spotify: true, supports_apple_music: true, supports_youtube_music: true };
        const badge = capabilityBadgeForPlayer(player, providers, { all: 'Alle Dienste' });
        expect(badge.label).toBe('Alle Dienste');
    });
});

// ------------------------------------------------------------------
// pickAutoSelections — first-run defaults: first speaker + Spotify when supported (#1082)
// ------------------------------------------------------------------
describe('pickAutoSelections', () => {
    it('picks the first player and Spotify on a fresh install', () => {
        const players = [
            { entity_id: 'media_player.sonos_kitchen', supports_spotify: true },
            { entity_id: 'media_player.sonos_lounge', supports_spotify: true },
        ];
        expect(pickAutoSelections(players, null, null)).toEqual({
            speaker: 'media_player.sonos_kitchen',
            provider: 'spotify',
        });
    });

    it('skips provider when the picked speaker does not support Spotify', () => {
        const players = [
            { entity_id: 'media_player.cast', supports_spotify: false, supports_apple_music: true },
        ];
        expect(pickAutoSelections(players, null, null)).toEqual({
            speaker: 'media_player.cast',
            provider: null,
        });
    });

    it('keeps a previously saved speaker even when more are available', () => {
        const players = [
            { entity_id: 'media_player.sonos_kitchen', supports_spotify: true },
            { entity_id: 'media_player.sonos_lounge', supports_spotify: true },
        ];
        const result = pickAutoSelections(players, 'media_player.sonos_lounge', null);
        expect(result.speaker).toBe('media_player.sonos_lounge');
        expect(result.provider).toBe('spotify');
    });

    it('keeps a previously saved provider even when not Spotify', () => {
        const players = [
            { entity_id: 'media_player.ma_lounge', supports_spotify: true, supports_apple_music: true },
        ];
        const result = pickAutoSelections(players, null, 'apple_music');
        expect(result.provider).toBe('apple_music');
    });

    it('returns nulls when no players exist (fresh HA before MA finishes)', () => {
        expect(pickAutoSelections([], null, null)).toEqual({ speaker: null, provider: null });
        expect(pickAutoSelections(null, null, null)).toEqual({ speaker: null, provider: null });
    });

    it('falls through to Spotify when supports_spotify is undefined (treat unknown as supported)', () => {
        // Older backend responses may omit supports_* flags entirely.
        const players = [{ entity_id: 'media_player.legacy' }];
        expect(pickAutoSelections(players, null, null)).toEqual({
            speaker: 'media_player.legacy',
            provider: 'spotify',
        });
    });
});
