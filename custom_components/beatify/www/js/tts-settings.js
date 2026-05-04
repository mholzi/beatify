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
                announce_nobody_correct: announceNobodyCorrect
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
            ['tts-announce-nobody-correct', function(v) { announceNobodyCorrect = v; }, function() { return announceNobodyCorrect; }]
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
            announce_nobody_correct: announceNobodyCorrect
        };
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
