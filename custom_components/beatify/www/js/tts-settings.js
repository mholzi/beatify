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

    function loadState() {
        try {
            var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            ttsEnabled = saved.enabled || false;
            ttsEntityId = saved.entity_id || '';
            announceGameStart = saved.announce_game_start !== false;
            announceWinner = saved.announce_winner !== false;
        } catch (e) { /* ignore */ }
    }

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                enabled: ttsEnabled,
                entity_id: ttsEntityId,
                announce_game_start: announceGameStart,
                announce_winner: announceWinner
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
            announce_winner: announceWinner
        };
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
