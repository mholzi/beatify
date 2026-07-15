/**
 * Beatify Admin — Game-Settings setup-section (#1279 Schritt 4b/6).
 *
 * Extracted from admin.js: the game-settings chip/toggle wiring (language,
 * timer, reveal-auto-advance, difficulty, bonus/mode flags, AND the
 * music-service provider chips) + the localStorage persistence round-trip
 * (load/save) + the settings-summary badge + the Title&Artist-mode UI sync.
 *
 * The live provider/music-service UI lives HERE (the `.chip[data-provider]`
 * handler) — there is no separate music-service module because that surface is
 * just these chips plus the capability gate in media-players.js (see PR body).
 *
 * State: reads/writes the shared `adminState` object (admin/state.js) directly.
 *
 * Cross-section: the provider-chip handler calls `renderPlaylists` (playlists.js)
 * to re-render coverage for the newly selected provider. Circular-import-safe:
 * it's an event-driven click handler, never runs at module init.
 *
 * `loadSavedSettings` is called from wizard.js via `window.loadSavedSettings`
 * (re-sync after the wizard persists settings), so admin.js shims it onto
 * `window`. `saveGameSettings` / `syncTitleArtistModeUI` have no cross-file
 * callers (verified: only comments/tests reference them) → no shim.
 */

import { adminState } from '../state.js';
import { STORAGE_GAME_SETTINGS } from '../constants.js';
import { renderPlaylists } from './playlists.js';

/**
 * #1583: Single-select chip a11y. The chips are native `<button>`s, so role,
 * focusability and Enter/Space activation are already provided by the browser —
 * the missing piece was `aria-pressed`, without which a screen reader can't tell
 * which chip in a group is selected. This helper syncs `aria-pressed` in lockstep
 * with the visual `chip--active` class so the two never drift, and is reused by
 * both the click handlers and the load-from-storage path.
 *
 * @param {string} groupSelector  selector matching every chip in the group
 * @param {(chip: Element) => boolean} isActive  true for the chip to mark selected
 */
export function selectChip(groupSelector, isActive) {
    document.querySelectorAll(groupSelector).forEach((chip) => {
        const active = isActive(chip);
        chip.classList.toggle('chip--active', active);
        chip.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

/**
 * Setup game settings controls (chips for language, timer, difficulty, toggle for artist challenge)
 */
export function setupGameSettings() {
    // Language chips
    document.querySelectorAll('.chip[data-lang]').forEach(chip => {
        chip.addEventListener('click', async function() {
            const lang = this.dataset.lang;
            selectChip('.chip[data-lang]', (c) => c === this);
            adminState.selectedLanguage = lang;
            if (window.BeatifyI18n) {
                await BeatifyI18n.setLanguage(lang);
                BeatifyI18n.initPageTranslations();
            }
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Timer chips
    document.querySelectorAll('.chip[data-duration]').forEach(chip => {
        chip.addEventListener('click', function() {
            const duration = parseInt(this.dataset.duration, 10);
            selectChip('.chip[data-duration]', (c) => c === this);
            adminState.selectedDuration = duration;
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Reveal auto-advance chips (#1012)
    document.querySelectorAll('.chip[data-reveal-advance]').forEach(chip => {
        chip.addEventListener('click', function() {
            adminState.revealAutoAdvance = parseInt(this.dataset.revealAdvance, 10) || 0;
            selectChip('.chip[data-reveal-advance]', (c) => c === this);
            saveGameSettings();
        });
    });

    // Difficulty chips
    document.querySelectorAll('.chip[data-difficulty]').forEach(chip => {
        chip.addEventListener('click', function() {
            const difficulty = this.dataset.difficulty;
            selectChip('.chip[data-difficulty]', (c) => c === this);
            adminState.selectedDifficulty = difficulty;
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Artist Challenge toggle
    document.getElementById('artist-challenge-toggle')?.addEventListener('change', function() {
        adminState.artistChallengeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Movie Quiz Bonus toggle (#947)
    document.getElementById('movie-quiz-toggle')?.addEventListener('change', function() {
        adminState.movieQuizEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Intro Mode toggle (Issue #23)
    document.getElementById('intro-mode-toggle')?.addEventListener('change', function() {
        adminState.introModeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Closest Wins toggle (Issue #442)
    document.getElementById('closest-wins-toggle')?.addEventListener('change', function() {
        adminState.closestWinsModeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Ramp-up Ordering toggle (Issue #1726)
    document.getElementById('rampup-order-toggle')?.addEventListener('change', function() {
        adminState.rampupOrderEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Finale ×2 toggle (Issue #1725)
    document.getElementById('finale-double-toggle')?.addEventListener('change', function() {
        adminState.finaleDoubleEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Finale Tiebreaker toggle (Issue #1725)
    document.getElementById('finale-tiebreaker-toggle')?.addEventListener('change', function() {
        adminState.finaleTiebreakerEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Comeback Token toggle (Issue #1724)
    document.getElementById('comeback-token-toggle')?.addEventListener('change', function() {
        adminState.comebackTokenEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Difficulty Bet Scaling toggle (Issue #1727)
    document.getElementById('difficulty-bet-scaling-toggle')?.addEventListener('change', function() {
        adminState.difficultyBetScalingEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Sabotage toggle (Issue #1665)
    document.getElementById('sabotage-toggle')?.addEventListener('change', function() {
        adminState.sabotageEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Title & Artist Mode toggle (#1180)
    document.getElementById('title-artist-mode-toggle')?.addEventListener('change', function() {
        adminState.titleArtistModeEnabled = this.checked;
        syncTitleArtistModeUI();
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Provider chips (Music Service)
    document.querySelectorAll('.chip[data-provider]').forEach(chip => {
        chip.addEventListener('click', function() {
            // Don't allow clicking disabled chips
            if (this.disabled || this.classList.contains('chip--disabled')) {
                return;
            }
            const provider = this.dataset.provider;
            selectChip('.chip[data-provider]', (c) => c === this);
            adminState.selectedProvider = provider;
            updateGameSettingsSummary();
            saveGameSettings();
            // Re-render playlists to show coverage for selected provider (preserve valid selections)
            if (adminState.playlistData.length > 0) {
                renderPlaylists(adminState.playlistData, '', true);
            }
        });
    });
}

/**
 * Load saved settings from localStorage
 */
export async function loadSavedSettings() {
    try {
        const saved = localStorage.getItem(STORAGE_GAME_SETTINGS);
        if (saved) {
            const settings = JSON.parse(saved);

            // Apply language
            if (settings.language) {
                adminState.selectedLanguage = settings.language;
                selectChip('.chip[data-lang]', (c) => c.dataset.lang === settings.language);
                if (window.BeatifyI18n) {
                    await BeatifyI18n.setLanguage(settings.language);
                    BeatifyI18n.initPageTranslations();
                }
            }

            // Apply timer
            if (settings.duration) {
                adminState.selectedDuration = settings.duration;
                selectChip('.chip[data-duration]', (c) => parseInt(c.dataset.duration, 10) === settings.duration);
            }

            // Apply reveal auto-advance (#1012)
            if (typeof settings.revealAutoAdvance === 'number') {
                adminState.revealAutoAdvance = settings.revealAutoAdvance;
                selectChip('.chip[data-reveal-advance]', (c) => parseInt(c.dataset.revealAdvance, 10) === settings.revealAutoAdvance);
            }

            // Apply difficulty
            if (settings.difficulty) {
                adminState.selectedDifficulty = settings.difficulty;
                selectChip('.chip[data-difficulty]', (c) => c.dataset.difficulty === settings.difficulty);
            }

            // Apply artist challenge
            if (typeof settings.artistChallenge === 'boolean') {
                adminState.artistChallengeEnabled = settings.artistChallenge;
                const toggle = document.getElementById('artist-challenge-toggle');
                if (toggle) toggle.checked = settings.artistChallenge;
            }

            // Apply movie quiz bonus (#947)
            if (typeof settings.movieQuiz === 'boolean') {
                adminState.movieQuizEnabled = settings.movieQuiz;
                const toggle = document.getElementById('movie-quiz-toggle');
                if (toggle) toggle.checked = settings.movieQuiz;
            }

            // Apply intro mode (Issue #23)
            if (typeof settings.introMode === 'boolean') {
                adminState.introModeEnabled = settings.introMode;
                const introToggle = document.getElementById('intro-mode-toggle');
                if (introToggle) introToggle.checked = settings.introMode;
            }

            // Apply closest wins mode (Issue #442)
            if (typeof settings.closestWinsMode === 'boolean') {
                adminState.closestWinsModeEnabled = settings.closestWinsMode;
                const closestToggle = document.getElementById('closest-wins-toggle');
                if (closestToggle) closestToggle.checked = settings.closestWinsMode;
            }

            // Apply ramp-up ordering (Issue #1726)
            if (typeof settings.rampupOrder === 'boolean') {
                adminState.rampupOrderEnabled = settings.rampupOrder;
                const rampupToggle = document.getElementById('rampup-order-toggle');
                if (rampupToggle) rampupToggle.checked = settings.rampupOrder;
            }

            // Apply Finale ×2 (Issue #1725)
            if (typeof settings.finaleDouble === 'boolean') {
                adminState.finaleDoubleEnabled = settings.finaleDouble;
                const finaleDoubleToggle = document.getElementById('finale-double-toggle');
                if (finaleDoubleToggle) finaleDoubleToggle.checked = settings.finaleDouble;
            }

            // Apply Finale Tiebreaker (Issue #1725)
            if (typeof settings.finaleTiebreaker === 'boolean') {
                adminState.finaleTiebreakerEnabled = settings.finaleTiebreaker;
                const finaleTbToggle = document.getElementById('finale-tiebreaker-toggle');
                if (finaleTbToggle) finaleTbToggle.checked = settings.finaleTiebreaker;
            }

            // Apply Comeback Token (Issue #1724)
            if (typeof settings.comebackToken === 'boolean') {
                adminState.comebackTokenEnabled = settings.comebackToken;
                const comebackToggle = document.getElementById('comeback-token-toggle');
                if (comebackToggle) comebackToggle.checked = settings.comebackToken;
            }

            // Apply Difficulty Bet Scaling (Issue #1727)
            if (typeof settings.difficultyBetScaling === 'boolean') {
                adminState.difficultyBetScalingEnabled = settings.difficultyBetScaling;
                const betScalingToggle = document.getElementById('difficulty-bet-scaling-toggle');
                if (betScalingToggle) betScalingToggle.checked = settings.difficultyBetScaling;
            }

            // Apply Sabotage (Issue #1665)
            if (typeof settings.sabotage === 'boolean') {
                adminState.sabotageEnabled = settings.sabotage;
                const sabotageToggle = document.getElementById('sabotage-toggle');
                if (sabotageToggle) sabotageToggle.checked = settings.sabotage;
            }

            // Apply Title & Artist mode (#1180)
            if (typeof settings.titleArtistMode === 'boolean') {
                adminState.titleArtistModeEnabled = settings.titleArtistMode;
                const taToggle = document.getElementById('title-artist-mode-toggle');
                if (taToggle) taToggle.checked = settings.titleArtistMode;
            }
            syncTitleArtistModeUI();

            // Apply provider
            if (settings.provider) {
                adminState.selectedProvider = settings.provider;
                selectChip('.chip[data-provider]', (c) => c.dataset.provider === settings.provider);
            }
        }
    } catch (e) {
        console.warn('Failed to load saved settings:', e);
    }
    // Always update summary (uses current state values)
    updateGameSettingsSummary();
}

/**
 * Save game settings to localStorage
 */
export function saveGameSettings() {
    try {
        const settings = {
            language: adminState.selectedLanguage,
            duration: adminState.selectedDuration,
            revealAutoAdvance: adminState.revealAutoAdvance,  // #1012
            difficulty: adminState.selectedDifficulty,
            artistChallenge: adminState.artistChallengeEnabled,
            movieQuiz: adminState.movieQuizEnabled,  // #947
            introMode: adminState.introModeEnabled,  // Issue #23
            closestWinsMode: adminState.closestWinsModeEnabled,  // Issue #442
            titleArtistMode: adminState.titleArtistModeEnabled,  // #1180
            rampupOrder: adminState.rampupOrderEnabled,  // Issue #1726
            finaleDouble: adminState.finaleDoubleEnabled,  // Issue #1725
            finaleTiebreaker: adminState.finaleTiebreakerEnabled,  // Issue #1725
            comebackToken: adminState.comebackTokenEnabled,  // Issue #1724
            difficultyBetScaling: adminState.difficultyBetScalingEnabled,  // Issue #1727
            sabotage: adminState.sabotageEnabled,  // Issue #1665
            provider: adminState.selectedProvider
        };
        localStorage.setItem(STORAGE_GAME_SETTINGS, JSON.stringify(settings));
    } catch (e) {
        console.warn('Failed to save settings:', e);
    }
}

/**
 * Update the game settings summary badge
 */
export function updateGameSettingsSummary() {
    const summary = document.getElementById('game-settings-summary');
    if (!summary) return;

    const difficultyLabels = { easy: 'Easy', normal: 'Normal', hard: 'Hard' };
    const langLabels = { en: 'EN', de: 'DE', es: 'ES' };
    // #1180: year-round bonuses are suppressed while TA mode is on, so the badge
    // hides their icons too — but the underlying flags stay the host's untouched
    // source of truth (so toggling TA off restores them).
    const yearRoundActive = !adminState.titleArtistModeEnabled;
    const artistIcon = (yearRoundActive && adminState.artistChallengeEnabled) ? ' • 🎤' : '';
    const movieIcon = (yearRoundActive && adminState.movieQuizEnabled) ? ' • 🎬' : '';  // #947
    const introIcon = (yearRoundActive && adminState.introModeEnabled) ? ' • ⚡' : '';  // Issue #23
    const closestIcon = (yearRoundActive && adminState.closestWinsModeEnabled) ? ' • 🎯' : '';  // Issue #442
    const taIcon = adminState.titleArtistModeEnabled ? ' • 🎵' : '';  // #1180
    // Issue #1726: ramp-up ordering is independent of the year-round bonuses
    // (it just reorders songs), so its icon shows regardless of TA mode.
    const rampupIcon = adminState.rampupOrderEnabled ? ' • 📈' : '';
    // Issue #1725: finale mechanics are mode-agnostic (end-game tension), so
    // their icons show regardless of TA mode.
    const finaleDoubleIcon = adminState.finaleDoubleEnabled ? ' • ✨' : '';
    const finaleTbIcon = adminState.finaleTiebreakerEnabled ? ' • ⚔️' : '';
    // Issue #1724: comeback token is mode-agnostic (rubber-banding), so its icon
    // shows regardless of TA mode.
    const comebackIcon = adminState.comebackTokenEnabled ? ' • 🎁' : '';
    // Issue #1727: difficulty bet scaling only affects the year-round bet, so
    // its icon shows only when year rounds are active (not in TA mode).
    const betScalingIcon = (yearRoundActive && adminState.difficultyBetScalingEnabled) ? ' • 🎲' : '';
    // Issue #1665: sabotage is mode-agnostic (hands out a token at game start
    // regardless of TA/year rounds), so its icon shows unconditionally.
    const sabotageIcon = adminState.sabotageEnabled ? ' • 💣' : '';

    summary.textContent = `${difficultyLabels[adminState.selectedDifficulty] || 'Normal'} • ${adminState.selectedDuration}s • ${langLabels[adminState.selectedLanguage] || 'EN'}${taIcon}${artistIcon}${movieIcon}${introIcon}${closestIcon}${rampupIcon}${finaleDoubleIcon}${finaleTbIcon}${comebackIcon}${betScalingIcon}${sabotageIcon}`;
}

/**
 * #1180: Title & Artist mode replaces the year round, so the year-only
 * bonuses (artist challenge, movie quiz, intro, closest wins) have nothing to
 * attach to. Hide and disable their setting-groups while TA mode is on.
 *
 * This is purely a visibility/disabled-state sync — it does NOT mutate the
 * year-round flags or the checkboxes. The host's real bonus preferences stay
 * the single source of truth (in the in-memory flags, the checkboxes, and
 * localStorage), so the save → reload → toggle-off cycle is lossless. The
 * actual suppression (forcing year-round bonuses off when TA mode is on) is
 * applied only when building the start-game payload, in startGame(), via
 * applyTitleArtistBonusPrecedence(). Forcing the flags off here instead would
 * persist false to localStorage and silently destroy the host's choices on
 * the next reload.
 */
export function syncTitleArtistModeUI() {
    // #1180: only the truly-incompatible modes are hidden in TA mode. Movie
    // quiz and intro mode are compatible bonuses, so they stay available.
    var ids = ['artist-challenge-toggle', 'closest-wins-toggle'];
    ids.forEach(function(id) {
        var input = document.getElementById(id);
        if (!input) return;
        var group = input.closest('.setting-group');
        if (group) group.classList.toggle('hidden', adminState.titleArtistModeEnabled);
        input.disabled = adminState.titleArtistModeEnabled;
    });
    // #1180 polish: year-distance difficulty doesn't apply in TA mode. Hide the
    // chips + year hint and show the fixed T&I scoring summary in their place.
    var diffRow = document.getElementById('admin-difficulty-row');
    if (diffRow) diffRow.classList.toggle('hidden', adminState.titleArtistModeEnabled);
    var diffHint = document.getElementById('admin-difficulty-hint');
    if (diffHint) diffHint.classList.toggle('hidden', adminState.titleArtistModeEnabled);
    var taSummary = document.getElementById('admin-difficulty-ta-summary');
    if (taSummary) taSummary.classList.toggle('hidden', !adminState.titleArtistModeEnabled);
}
