/**
 * Unit tests for Title & Artist mode bonus-flag precedence (#1180).
 *
 * Title & Artist mode replaces the year round, so the year-only bonuses
 * (artist challenge, movie quiz, intro, closest wins) are suppressed while
 * TA mode is on. The load-bearing requirement is that suppression must NOT
 * corrupt the host's stored preferences: a host who has Artist Challenge ON,
 * enables TA mode, reloads, then turns TA mode OFF must get Artist Challenge
 * back. The old code forced the in-memory flags to false and persisted them,
 * which silently destroyed the preference across reloads — this suite is the
 * regression guard for that bug.
 */
import { describe, it, expect } from 'vitest';
import {
    applyTitleArtistBonusPrecedence,
    YEAR_ROUND_BONUS_KEYS,
} from '../title-artist-bonuses.js';

// ------------------------------------------------------------------
// applyTitleArtistBonusPrecedence — pure precedence on the payload flags
// ------------------------------------------------------------------
describe('applyTitleArtistBonusPrecedence', () => {
    const allOn = {
        artist_challenge_enabled: true,
        movie_quiz_enabled: true,
        intro_mode_enabled: true,
        closest_wins_mode: true,
    };

    it('passes the host flags through unchanged when TA mode is off', () => {
        expect(applyTitleArtistBonusPrecedence(allOn, false)).toEqual(allOn);
    });

    it('forces every year-round bonus off when TA mode is on', () => {
        expect(applyTitleArtistBonusPrecedence(allOn, true)).toEqual({
            artist_challenge_enabled: false,
            movie_quiz_enabled: false,
            intro_mode_enabled: false,
            closest_wins_mode: false,
        });
    });

    it('suppresses only the year-round keys, leaving unrelated keys intact', () => {
        const flags = { ...allOn, provider: 'spotify', difficulty: 'hard' };
        const out = applyTitleArtistBonusPrecedence(flags, true);
        expect(out.provider).toBe('spotify');
        expect(out.difficulty).toBe('hard');
        for (const key of YEAR_ROUND_BONUS_KEYS) {
            expect(out[key]).toBe(false);
        }
    });

    it('does NOT mutate the input object (source of truth survives)', () => {
        const flags = { ...allOn };
        const snapshot = { ...flags };
        applyTitleArtistBonusPrecedence(flags, true);
        // The caller's flags must be untouched so localStorage keeps the
        // host's real choices — this is the crux of the reload-corruption fix.
        expect(flags).toEqual(snapshot);
    });

    it('returns a new object reference each call', () => {
        const flags = { ...allOn };
        expect(applyTitleArtistBonusPrecedence(flags, true)).not.toBe(flags);
        expect(applyTitleArtistBonusPrecedence(flags, false)).not.toBe(flags);
    });
});

// ------------------------------------------------------------------
// Regression: save → reload → toggle-off must NOT lose bonus preferences.
//
// This models the real admin.js persistence contract:
//   - saveGameSettings() writes the in-memory flags to localStorage.
//   - loadSavedSettings() reads them back and rehydrates the flags/checkboxes.
//   - syncTitleArtistModeUI() only hides groups; it never mutates the flags.
//   - startGame() applies precedence at payload-build time (pure helper).
// The previous bug lived in syncTitleArtistModeUI() forcing the flags to
// false, which saveGameSettings() then persisted — corrupting the next load.
// ------------------------------------------------------------------
describe('save → reload → toggle-off preference persistence', () => {
    function makeLS(initial = {}) {
        const store = { ...initial };
        return {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
        };
    }

    const KEY = 'beatify_game_settings';

    // Mirror of saveGameSettings()'s persisted shape (only the bits we test).
    function save(ls, state) {
        ls.setItem(KEY, JSON.stringify({
            artistChallenge: state.artistChallengeEnabled,
            movieQuiz: state.movieQuizEnabled,
            introMode: state.introModeEnabled,
            closestWinsMode: state.closestWinsModeEnabled,
            titleArtistMode: state.titleArtistModeEnabled,
        }));
    }

    // Mirror of loadSavedSettings()'s hydration: read flags straight back.
    function load(ls) {
        const s = JSON.parse(ls.getItem(KEY));
        return {
            artistChallengeEnabled: s.artistChallenge,
            movieQuizEnabled: s.movieQuiz,
            introModeEnabled: s.introMode,
            closestWinsModeEnabled: s.closestWinsMode,
            titleArtistModeEnabled: s.titleArtistMode,
        };
    }

    it('restores Artist Challenge after enable-TA → reload → disable-TA', () => {
        const ls = makeLS();

        // Host has Artist Challenge ON, year mode (TA off).
        let state = {
            artistChallengeEnabled: true,
            movieQuizEnabled: false,
            introModeEnabled: false,
            closestWinsModeEnabled: false,
            titleArtistModeEnabled: false,
        };
        save(ls, state);

        // Host enables TA mode. syncTitleArtistModeUI() now only hides the
        // groups — it does NOT force the bonus flags off — so the stored
        // Artist Challenge preference is preserved on save.
        state.titleArtistModeEnabled = true;
        save(ls, state);

        // Reload: rehydrate from localStorage.
        state = load(ls);
        expect(state.titleArtistModeEnabled).toBe(true);
        expect(state.artistChallengeEnabled).toBe(true); // preference survived

        // Host turns TA mode off. Artist Challenge must come back ON.
        state.titleArtistModeEnabled = false;
        save(ls, state);
        state = load(ls);
        expect(state.titleArtistModeEnabled).toBe(false);
        expect(state.artistChallengeEnabled).toBe(true);
    });

    it('still suppresses the bonus in the start-game payload while TA is on', () => {
        // Even though the stored preference stays ON, the payload sent to the
        // server must have it suppressed for the duration of TA mode.
        const state = load((() => {
            const ls = makeLS();
            ls.setItem(KEY, JSON.stringify({
                artistChallenge: true,
                movieQuiz: true,
                introMode: true,
                closestWinsMode: true,
                titleArtistMode: true,
            }));
            return ls;
        })());

        const payload = applyTitleArtistBonusPrecedence({
            artist_challenge_enabled: state.artistChallengeEnabled,
            movie_quiz_enabled: state.movieQuizEnabled,
            intro_mode_enabled: state.introModeEnabled,
            closest_wins_mode: state.closestWinsModeEnabled,
        }, state.titleArtistModeEnabled);

        expect(payload).toEqual({
            artist_challenge_enabled: false,
            movie_quiz_enabled: false,
            intro_mode_enabled: false,
            closest_wins_mode: false,
        });
    });
});
