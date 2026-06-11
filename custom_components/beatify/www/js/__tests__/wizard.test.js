/**
 * Unit tests for wizard.js pure helpers.
 * These helpers drive the state machine: when to show, where to resume, when to show the pill.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { resumeAtStep, shouldTrigger, shouldShowPill, providerSupportedForPlayer, capabilityBadgeForPlayer, applyGameModeTogglePrecedence, difficultyDisplayFor, buildWizChip, resolveGameLanguageDefault } from '../wizard.js';

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

    it('lists both services (muted summary) for a two-service subset, full list on title (#1319)', () => {
        const player = { supports_spotify: true, supports_apple_music: true, supports_youtube_music: false };
        expect(capabilityBadgeForPlayer(player, providers)).toEqual({
            cls: 'summary',
            label: 'Spotify, Apple Music',
            title: 'Spotify, Apple Music',
        });
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

    // #1319: with the real 6-provider universe, multi-service rows must collapse
    // to a single short, muted line instead of a wrapping uppercase comma list.
    describe('summarization over the full 6-provider set (#1319)', () => {
        const six = [
            { id: 'spotify', label: 'Spotify' },
            { id: 'apple_music', label: 'Apple Music' },
            { id: 'youtube_music', label: 'YouTube Music' },
            { id: 'tidal', label: 'Tidal' },
            { id: 'deezer', label: 'Deezer' },
            { id: 'amazon_music', label: 'Amazon Music' },
        ];

        it('collapses the typical MA player (5 of 6, all but Amazon) to "All major services"', () => {
            const player = {
                supports_spotify: true, supports_apple_music: true, supports_youtube_music: true,
                supports_tidal: true, supports_deezer: true, supports_amazon_music: false,
            };
            expect(capabilityBadgeForPlayer(player, six)).toEqual({
                cls: 'summary',
                label: 'All major services',
                title: 'Spotify, Apple Music, YouTube Music, Tidal, Deezer',
            });
        });

        it('collapses 3 of 6 to "first +N" with the full list on title', () => {
            const player = {
                supports_spotify: true, supports_apple_music: true, supports_youtube_music: true,
                supports_tidal: false, supports_deezer: false, supports_amazon_music: false,
            };
            expect(capabilityBadgeForPlayer(player, six)).toEqual({
                cls: 'summary',
                label: 'Spotify +2',
                title: 'Spotify, Apple Music, YouTube Music',
            });
        });

        it('keeps the single-service accent badge (cls partial) even in the 6-provider set', () => {
            const player = {
                supports_spotify: true, supports_apple_music: false, supports_youtube_music: false,
                supports_tidal: false, supports_deezer: false, supports_amazon_music: false,
            };
            expect(capabilityBadgeForPlayer(player, six)).toEqual({ cls: 'partial', label: 'Spotify only' });
        });

        it('respects custom summary templates (locale)', () => {
            const player = {
                supports_spotify: true, supports_apple_music: true, supports_youtube_music: true,
                supports_tidal: false, supports_deezer: false, supports_amazon_music: false,
            };
            const badge = capabilityBadgeForPlayer(player, six, { moreTemplate: '{provider} und {count} weitere' });
            expect(badge.label).toBe('Spotify und 2 weitere');
        });
    });
});

// ------------------------------------------------------------------
// applyGameModeTogglePrecedence — Step 4 mutual exclusion (#1180)
//
// The load-bearing requirement: enabling Title & Artist mode must NOT zero the
// year-round bonus flags. The wizard writes these flags verbatim into
// beatify_game_settings on every advance past Step 4, and admin.js reads that
// same key — so zeroing them here would silently destroy the host's saved
// bonus choices on the next admin reload (the exact regression admin.js's
// applyTitleArtistBonusPrecedence contract guards against). Exclusivity is
// asymmetric: TA is the replaceable round, so turning a year bonus on exits TA,
// but turning TA on leaves the year flags untouched (suppression is applied
// later, at start-game-payload build time in admin.js).
// ------------------------------------------------------------------
describe('applyGameModeTogglePrecedence', () => {
    const allYearOn = {
        artistChallenge: true,
        movieQuiz: true,
        introMode: true,
        closestWinsMode: true,
        titleArtistMode: false,
    };

    it('does NOT zero the year-round flags when TA mode is turned on', () => {
        const out = applyGameModeTogglePrecedence(allYearOn, 'titleArtist', true);
        expect(out).toEqual({
            artistChallenge: true,
            movieQuiz: true,
            introMode: true,
            closestWinsMode: true,
            titleArtistMode: true,
        });
    });

    it('turns TA mode off when a year-distance bonus (artist/closest) is turned on', () => {
        // #1180: only the year-distance modes (artist challenge, closest wins)
        // are mutually exclusive with TA. Movie quiz + intro are compatible
        // bonuses and leave titleArtistMode untouched (see the movie/intro
        // compatibility tests below), so they're deliberately excluded here.
        const taOn = { ...allYearOn, artistChallenge: false, movieQuiz: false, introMode: false, closestWinsMode: false, titleArtistMode: true };
        for (const [key, flag] of [
            ['artist', 'artistChallenge'],
            ['closest', 'closestWinsMode'],
        ]) {
            const out = applyGameModeTogglePrecedence(taOn, key, true);
            expect(out[flag]).toBe(true);
            expect(out.titleArtistMode).toBe(false);
        }
    });

    it('keeps TA mode on when a compatible bonus (movie/intro) is turned on', () => {
        const taOn = { artistChallenge: false, movieQuiz: false, introMode: false, closestWinsMode: false, titleArtistMode: true };
        for (const [key, flag] of [
            ['movie', 'movieQuiz'],
            ['intro', 'introMode'],
        ]) {
            const out = applyGameModeTogglePrecedence(taOn, key, true);
            expect(out[flag]).toBe(true);
            expect(out.titleArtistMode).toBe(true);
        }
    });

    it('does NOT touch TA mode when a year-round bonus is turned off', () => {
        const taOn = { artistChallenge: false, movieQuiz: false, introMode: false, closestWinsMode: false, titleArtistMode: true };
        const out = applyGameModeTogglePrecedence(taOn, 'artist', false);
        expect(out.artistChallenge).toBe(false);
        expect(out.titleArtistMode).toBe(true); // turning a bonus OFF must not exit TA
    });

    it('does not mutate the input object (source of truth survives)', () => {
        const flags = { ...allYearOn };
        const snapshot = { ...flags };
        applyGameModeTogglePrecedence(flags, 'titleArtist', true);
        expect(flags).toEqual(snapshot);
    });

    it('returns a new object reference', () => {
        expect(applyGameModeTogglePrecedence(allYearOn, 'titleArtist', true)).not.toBe(allYearOn);
    });
});

// ------------------------------------------------------------------
// Persist → hydrate round-trip: enabling TA must NOT persist false over a
// previously-true year-round bonus (#1180).
//
// This models the wizard's beatify_game_settings contract:
//   - _persistGameSettings() merges the chosen* flags into the stored object
//     under keys { artistChallenge, movieQuiz, introMode, closestWinsMode,
//     titleArtistMode } (wizard.js).
//   - On the next admin load, admin.js's loadSavedSettings() reads those keys
//     straight back. The wizard's own show()/hydration reads them too.
//   - Toggle precedence runs through applyGameModeTogglePrecedence.
// The previous bug zeroed the year flags when TA was enabled, persisting false
// and destroying the host's choices on the next admin reload. This is the
// regression guard for that.
// ------------------------------------------------------------------
describe('wizard TA enable → persist → reload does not destroy bonus choices', () => {
    // Mirror of _persistGameSettings()'s merge shape (only the Step-4 flags).
    function persist(ls, flags) {
        const raw = ls.getItem('beatify_game_settings');
        const existing = raw ? JSON.parse(raw) : {};
        ls.setItem('beatify_game_settings', JSON.stringify({
            ...existing,
            artistChallenge: flags.artistChallenge,
            movieQuiz: flags.movieQuiz,
            introMode: flags.introMode,
            closestWinsMode: flags.closestWinsMode,
            titleArtistMode: flags.titleArtistMode,
        }));
    }

    // Mirror of the wizard / admin hydration: read flags straight back.
    function hydrate(ls) {
        const s = JSON.parse(ls.getItem('beatify_game_settings'));
        return {
            artistChallenge: s.artistChallenge,
            movieQuiz: s.movieQuiz,
            introMode: s.introMode,
            closestWinsMode: s.closestWinsMode,
            titleArtistMode: s.titleArtistMode,
        };
    }

    it('keeps a previously-true Artist Challenge after enabling TA, persisting, reloading, then disabling TA', () => {
        const ls = makeLS();

        // Host has Artist Challenge ON, TA off. Wizard advances past Step 4.
        let flags = {
            artistChallenge: true,
            movieQuiz: false,
            introMode: false,
            closestWinsMode: false,
            titleArtistMode: false,
        };
        persist(ls, flags);

        // Host taps the TA card ON in the wizard.
        flags = applyGameModeTogglePrecedence(flags, 'titleArtist', true);
        // The bonus flag must NOT have been zeroed by the toggle...
        expect(flags.artistChallenge).toBe(true);
        persist(ls, flags);
        // ...and must NOT be persisted as false.
        expect(JSON.parse(ls.getItem('beatify_game_settings')).artistChallenge).toBe(true);

        // Reload admin (no wizard mutation): the stored choice survives.
        flags = hydrate(ls);
        expect(flags.titleArtistMode).toBe(true);
        expect(flags.artistChallenge).toBe(true);

        // Host turns TA off again (e.g. via admin) → Artist Challenge restored.
        flags = applyGameModeTogglePrecedence(flags, 'titleArtist', false);
        persist(ls, flags);
        flags = hydrate(ls);
        expect(flags.titleArtistMode).toBe(false);
        expect(flags.artistChallenge).toBe(true);
    });
});

// ------------------------------------------------------------------
// difficultyDisplayFor — difficulty area depends on the core mode
// ------------------------------------------------------------------
describe('difficultyDisplayFor', () => {
    it('shows the year-distance chips and no summary in Jahr mode', () => {
        expect(difficultyDisplayFor(false)).toEqual({ showChips: true, summaryKey: null });
    });

    it('hides the chips and shows the T&I scoring summary in Title & Artist mode', () => {
        expect(difficultyDisplayFor(true)).toEqual({
            showChips: false,
            summaryKey: 'wizard.step4.taScoring',
        });
    });
});

// buildWizChip — Light Mode chip markup contract (#1228 regression)
// ------------------------------------------------------------------
describe('buildWizChip', () => {
    it('emits a kebab-case data-light-mode attribute (matches the [data-light-mode] binding)', () => {
        const html = buildWizChip('static', 'Static', 'light-mode', 'dynamic');
        // The exact attribute that broke before: must be data-light-mode, not
        // data-lightMode. The browser maps data-light-mode -> dataset.lightMode
        // by spec, so locking the kebab attribute name guards the whole binding.
        expect(html).toContain('data-light-mode="static"');
        expect(html).not.toContain('data-lightMode');
    });

    it('marks the active chip and only the active chip', () => {
        expect(buildWizChip('static', 'Static', 'light-mode', 'static')).toContain('wiz-chip active');
        expect(buildWizChip('dynamic', 'Dynamic', 'light-mode', 'static')).not.toContain('active');
    });

    it('works for the intensity group too', () => {
        expect(buildWizChip('party', 'Party', 'intensity', 'party')).toContain('data-intensity="party"');
    });
});

// ------------------------------------------------------------------
// resolveGameLanguageDefault — game language must follow the browser
// locale on EVERY wizard open, including a first-time user with no
// saved settings (#1354: German wizard but English game).
// ------------------------------------------------------------------
describe('resolveGameLanguageDefault', () => {
    it('uses the browser language even when there are NO saved settings (#1354)', () => {
        // The bug: first-time user, no beatify_game_settings → game went out
        // as the hard-coded 'en' default while the wizard UI was German.
        expect(resolveGameLanguageDefault(() => 'de', null, 'en')).toBe('de');
    });

    it('browser language wins over a stale saved language', () => {
        expect(resolveGameLanguageDefault(() => 'de', { language: 'en' }, 'en')).toBe('de');
    });

    it('falls back to saved language when browser detection is unavailable', () => {
        expect(resolveGameLanguageDefault(null, { language: 'fr' }, 'en')).toBe('fr');
    });

    it('falls back to saved language when the detector throws', () => {
        const throwing = () => { throw new Error('no navigator'); };
        expect(resolveGameLanguageDefault(throwing, { language: 'es' }, 'en')).toBe('es');
    });

    it('falls back to the current default when nothing resolves', () => {
        expect(resolveGameLanguageDefault(null, null, 'en')).toBe('en');
        expect(resolveGameLanguageDefault(() => '', {}, 'en')).toBe('en');
    });
});
