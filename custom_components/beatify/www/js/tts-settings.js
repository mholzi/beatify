/**
 * TTS Announcements UI — Admin setup (#447)
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'beatify_tts';
    var ttsEnabled = false;
    var ttsEntityId = '';
    var announceGameStart = true;
    var announceWinner = true;
    // #471 Phase 1: Game Flow toggles. Defaults match the most common host
    // expectation — round start + time's up + correct answer announced;
    // 3-2-1 countdown opt-in only because firing it every round is intrusive.
    var announceRoundStart = true;
    var announceCountdown = false;
    var announceTimeUp = true;
    var announceCorrectAnswer = true;
    var announceNobodyCorrect = true;
    // #840 Phase 2: Player Achievement toggles. streak-broken defaults off —
    // firing on every missed round mid-game is noisy.
    var announceExactGuess = true;
    var announceClosestGuess = true;
    var announceStreakMilestone = true;
    var announceStreakBroken = false;
    var announceLeaderChange = true;
    var announceTiedFirst = true;
    // #841 Phase 3: Betting & Game State toggles. player-reconnect defaults
    // off — phones re-establish the WS constantly (screen lock, network).
    var announceBetWon = true;
    var announceBetLost = true;
    var announcePlayerJoin = true;
    var announcePlayerReconnect = false;
    var announceLastRound = true;
    var announcePodium = true;
    var announceRematch = true;
    // #842 Phase 4: Special Modes toggles.
    var announceIntroRound = true;
    var announceStealUnlocked = true;
    var announceStealUsed = true;

    function loadState() {
        try {
            var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            ttsEnabled = saved.enabled || false;
            ttsEntityId = saved.entity_id || '';
            announceGameStart = saved.announce_game_start !== false;
            announceWinner = saved.announce_winner !== false;
            announceRoundStart = saved.announce_round_start !== false;
            announceCountdown = saved.announce_countdown === true;
            announceTimeUp = saved.announce_time_up !== false;
            announceCorrectAnswer = saved.announce_correct_answer !== false;
            announceNobodyCorrect = saved.announce_nobody_correct !== false;
            announceExactGuess = saved.announce_exact_guess !== false;
            announceClosestGuess = saved.announce_closest_guess !== false;
            announceStreakMilestone = saved.announce_streak_milestone !== false;
            announceStreakBroken = saved.announce_streak_broken === true;
            announceLeaderChange = saved.announce_leader_change !== false;
            announceTiedFirst = saved.announce_tied_first !== false;
            announceBetWon = saved.announce_bet_won !== false;
            announceBetLost = saved.announce_bet_lost !== false;
            announcePlayerJoin = saved.announce_player_join !== false;
            announcePlayerReconnect = saved.announce_player_reconnect === true;
            announceLastRound = saved.announce_last_round !== false;
            announcePodium = saved.announce_podium !== false;
            announceRematch = saved.announce_rematch !== false;
            announceIntroRound = saved.announce_intro_round !== false;
            announceStealUnlocked = saved.announce_steal_unlocked !== false;
            announceStealUsed = saved.announce_steal_used !== false;
        } catch (e) { /* ignore */ }
    }

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                enabled: ttsEnabled,
                entity_id: ttsEntityId,
                announce_game_start: announceGameStart,
                announce_winner: announceWinner,
                announce_round_start: announceRoundStart,
                announce_countdown: announceCountdown,
                announce_time_up: announceTimeUp,
                announce_correct_answer: announceCorrectAnswer,
                announce_nobody_correct: announceNobodyCorrect,
                announce_exact_guess: announceExactGuess,
                announce_closest_guess: announceClosestGuess,
                announce_streak_milestone: announceStreakMilestone,
                announce_streak_broken: announceStreakBroken,
                announce_leader_change: announceLeaderChange,
                announce_tied_first: announceTiedFirst,
                announce_bet_won: announceBetWon,
                announce_bet_lost: announceBetLost,
                announce_player_join: announcePlayerJoin,
                announce_player_reconnect: announcePlayerReconnect,
                announce_last_round: announceLastRound,
                announce_podium: announcePodium,
                announce_rematch: announceRematch,
                announce_intro_round: announceIntroRound,
                announce_steal_unlocked: announceStealUnlocked,
                announce_steal_used: announceStealUsed
            }));
        } catch (e) { /* ignore */ }
    }

    function updateSummary() {
        var summary = document.getElementById('tts-settings-summary');
        if (summary) {
            summary.textContent = ttsEnabled && ttsEntityId ? ttsEntityId : 'Off';
        }
    }

    function updateTestButton() {
        var testBtn = document.getElementById('tts-test');
        if (testBtn) {
            testBtn.disabled = !ttsEnabled || !ttsEntityId;
        }
    }

    // #793: tts.speak needs both a TTS entity AND a media player to route
    // through. Read the speaker from the same localStorage key the wizard
    // and admin home view write — falls back to game settings.
    function _selectedSpeaker() {
        try {
            var fromKey = localStorage.getItem('beatify_last_player');
            if (fromKey) return fromKey;
            var s = JSON.parse(localStorage.getItem('beatify_game_settings') || '{}');
            return s.media_player || '';
        } catch (e) { return ''; }
    }

    function init() {
        loadState();

        // Enable toggle
        var enableToggle = document.getElementById('tts-enable');
        if (enableToggle) {
            enableToggle.checked = ttsEnabled;
            enableToggle.addEventListener('change', function() {
                ttsEnabled = this.checked;
                updateSummary();
                updateTestButton();
                saveState();
            });
        }

        // Entity ID input
        var entityInput = document.getElementById('tts-entity-id');
        if (entityInput) {
            entityInput.value = ttsEntityId;
            entityInput.addEventListener('input', function() {
                ttsEntityId = this.value.trim();
                updateSummary();
                updateTestButton();
                saveState();
            });
        }

        // Announce game start toggle
        var gameStartToggle = document.getElementById('tts-announce-game-start');
        if (gameStartToggle) {
            gameStartToggle.checked = announceGameStart;
            gameStartToggle.addEventListener('change', function() {
                announceGameStart = this.checked;
                saveState();
            });
        }

        // Announce winner toggle
        var winnerToggle = document.getElementById('tts-announce-winner');
        if (winnerToggle) {
            winnerToggle.checked = announceWinner;
            winnerToggle.addEventListener('change', function() {
                announceWinner = this.checked;
                saveState();
            });
        }

        // #471 Phase 1: Game Flow toggles. Each toggle reads/writes the same
        // localStorage shape so admin.js / configure_tts can pick up the
        // settings at game-start without any further plumbing. The DOM IDs
        // are optional — if the HTML doesn't render a toggle for one, the
        // default from loadState() applies.
        [
            ['tts-announce-round-start', function(v) { announceRoundStart = v; }, function() { return announceRoundStart; }],
            ['tts-announce-countdown', function(v) { announceCountdown = v; }, function() { return announceCountdown; }],
            ['tts-announce-time-up', function(v) { announceTimeUp = v; }, function() { return announceTimeUp; }],
            ['tts-announce-correct-answer', function(v) { announceCorrectAnswer = v; }, function() { return announceCorrectAnswer; }],
            ['tts-announce-nobody-correct', function(v) { announceNobodyCorrect = v; }, function() { return announceNobodyCorrect; }],
            // #840 Phase 2: Player Achievement toggles
            ['tts-announce-exact-guess', function(v) { announceExactGuess = v; }, function() { return announceExactGuess; }],
            ['tts-announce-closest-guess', function(v) { announceClosestGuess = v; }, function() { return announceClosestGuess; }],
            ['tts-announce-streak-milestone', function(v) { announceStreakMilestone = v; }, function() { return announceStreakMilestone; }],
            ['tts-announce-streak-broken', function(v) { announceStreakBroken = v; }, function() { return announceStreakBroken; }],
            ['tts-announce-leader-change', function(v) { announceLeaderChange = v; }, function() { return announceLeaderChange; }],
            ['tts-announce-tied-first', function(v) { announceTiedFirst = v; }, function() { return announceTiedFirst; }],
            // #841 Phase 3: Betting & Game State toggles
            ['tts-announce-bet-won', function(v) { announceBetWon = v; }, function() { return announceBetWon; }],
            ['tts-announce-bet-lost', function(v) { announceBetLost = v; }, function() { return announceBetLost; }],
            ['tts-announce-player-join', function(v) { announcePlayerJoin = v; }, function() { return announcePlayerJoin; }],
            ['tts-announce-player-reconnect', function(v) { announcePlayerReconnect = v; }, function() { return announcePlayerReconnect; }],
            ['tts-announce-last-round', function(v) { announceLastRound = v; }, function() { return announceLastRound; }],
            ['tts-announce-podium', function(v) { announcePodium = v; }, function() { return announcePodium; }],
            ['tts-announce-rematch', function(v) { announceRematch = v; }, function() { return announceRematch; }],
            // #842 Phase 4: Special Modes toggles
            ['tts-announce-intro-round', function(v) { announceIntroRound = v; }, function() { return announceIntroRound; }],
            ['tts-announce-steal-unlocked', function(v) { announceStealUnlocked = v; }, function() { return announceStealUnlocked; }],
            ['tts-announce-steal-used', function(v) { announceStealUsed = v; }, function() { return announceStealUsed; }]
        ].forEach(function(pair) {
            var el = document.getElementById(pair[0]);
            if (el) {
                el.checked = pair[2]();
                el.addEventListener('change', function() {
                    pair[1](this.checked);
                    saveState();
                });
            }
        });

        // Test TTS button
        var testBtn = document.getElementById('tts-test');
        if (testBtn) {
            testBtn.addEventListener('click', function() {
                if (!ttsEntityId) return;
                var speaker = _selectedSpeaker();
                if (!speaker) {
                    testBtn.textContent = '✗ ' + (window.BeatifyI18n ? window.BeatifyI18n.t('admin.ttsTestNoSpeaker') : 'Pick a speaker first');
                    setTimeout(function() { testBtn.textContent = '🔊 Test TTS'; testBtn.disabled = false; }, 3000);
                    return;
                }
                testBtn.disabled = true;
                testBtn.textContent = '🔊 ...';

                fetch('/beatify/api/tts-test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        entity_id: ttsEntityId,
                        media_player_entity_id: speaker,
                        message: 'Beatify TTS test — this is working!'
                    })
                }).then(function(resp) {
                    if (!resp.ok) {
                        testBtn.textContent = '✗ ' + (window.BeatifyI18n ? window.BeatifyI18n.t('admin.ttsTestFailed') : 'Failed');
                        setTimeout(function() { testBtn.textContent = '🔊 Test TTS'; testBtn.disabled = false; }, 2000);
                        return;
                    }
                    testBtn.textContent = '✓ ' + (window.BeatifyI18n ? window.BeatifyI18n.t('admin.ttsTested') : 'Sent');
                    setTimeout(function() { testBtn.textContent = '🔊 Test TTS'; testBtn.disabled = false; }, 2000);
                }).catch(function() {
                    testBtn.textContent = '✗ ' + (window.BeatifyI18n ? window.BeatifyI18n.t('admin.ttsTestFailed') : 'Failed');
                    setTimeout(function() { testBtn.textContent = '🔊 Test TTS'; testBtn.disabled = false; }, 2000);
                });
            });
        }

        updateSummary();
        updateTestButton();
    }

    // Expose for admin.js to read when starting game
    window._ttsConfig = function() {
        return {
            enabled: ttsEnabled,
            entity_id: ttsEntityId,
            announce_game_start: announceGameStart,
            announce_winner: announceWinner,
            // #471 Phase 1: Game Flow toggles
            announce_round_start: announceRoundStart,
            announce_countdown: announceCountdown,
            announce_time_up: announceTimeUp,
            announce_correct_answer: announceCorrectAnswer,
            announce_nobody_correct: announceNobodyCorrect,
            // #840 Phase 2: Player Achievement toggles
            announce_exact_guess: announceExactGuess,
            announce_closest_guess: announceClosestGuess,
            announce_streak_milestone: announceStreakMilestone,
            announce_streak_broken: announceStreakBroken,
            announce_leader_change: announceLeaderChange,
            announce_tied_first: announceTiedFirst,
            // #841 Phase 3: Betting & Game State toggles
            announce_bet_won: announceBetWon,
            announce_bet_lost: announceBetLost,
            announce_player_join: announcePlayerJoin,
            announce_player_reconnect: announcePlayerReconnect,
            announce_last_round: announceLastRound,
            announce_podium: announcePodium,
            announce_rematch: announceRematch,
            // #842 Phase 4: Special Modes toggles
            announce_intro_round: announceIntroRound,
            announce_steal_unlocked: announceStealUnlocked,
            announce_steal_used: announceStealUsed
        };
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
