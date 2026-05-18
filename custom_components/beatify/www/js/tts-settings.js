/**
 * TTS Announcements UI — Admin setup (#447)
 *
 * 23 per-event announcement toggles, plus verbosity presets (Minimal /
 * Standard / Full) that bulk-set them. Picking a preset sets every toggle;
 * editing a toggle by hand flips the preset to "Custom". The backend is
 * unaware of presets — _ttsConfig() always emits the 23 booleans.
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'beatify_tts';

    // All 23 announcement keys.
    var KEYS = [
        'announce_game_start', 'announce_round_start', 'announce_countdown',
        'announce_time_up', 'announce_correct_answer', 'announce_nobody_correct',
        'announce_exact_guess', 'announce_closest_guess', 'announce_streak_milestone',
        'announce_streak_broken', 'announce_leader_change', 'announce_tied_first',
        'announce_bet_won', 'announce_bet_lost', 'announce_player_join',
        'announce_player_reconnect', 'announce_last_round', 'announce_podium',
        'announce_rematch', 'announce_winner', 'announce_intro_round',
        'announce_steal_unlocked', 'announce_steal_used'
    ];

    // Verbosity presets (#2) — each lists the keys that are ON. Anything not
    // listed is OFF. "standard" is the default for a fresh setup.
    var PRESETS = {
        // Game/round boundaries only — no per-round chatter.
        minimal: [
            'announce_game_start', 'announce_round_start', 'announce_last_round',
            'announce_winner', 'announce_podium', 'announce_rematch',
            'announce_intro_round'
        ],
        // Minimal + the combined reveal narration + key drama.
        standard: [
            'announce_game_start', 'announce_round_start', 'announce_time_up',
            'announce_correct_answer', 'announce_nobody_correct',
            'announce_exact_guess', 'announce_closest_guess',
            'announce_streak_milestone', 'announce_leader_change',
            'announce_tied_first', 'announce_bet_won', 'announce_bet_lost',
            'announce_last_round', 'announce_podium', 'announce_rematch',
            'announce_winner', 'announce_intro_round', 'announce_steal_used'
        ],
        // Everything.
        full: KEYS.slice()
    };
    var PRESET_NAMES = ['minimal', 'standard', 'full'];

    var ttsEnabled = false;
    var ttsEntityId = '';
    var ttsPreset = 'standard';
    var announce = {};  // snake_case key -> bool

    function domId(key) {
        return 'tts-' + key.replace(/_/g, '-');
    }

    function presetValues(name) {
        var on = PRESETS[name] || [];
        var out = {};
        KEYS.forEach(function(k) { out[k] = on.indexOf(k) !== -1; });
        return out;
    }

    // Shared with the setup wizard (wizard.js step 5) so its verbosity chips
    // expand to the same 23 booleans without duplicating the preset table.
    window.BeatifyTtsPresets = {
        KEYS: KEYS,
        PRESETS: PRESETS,
        presetValues: presetValues
    };

    function detectPreset() {
        for (var i = 0; i < PRESET_NAMES.length; i++) {
            var pv = presetValues(PRESET_NAMES[i]);
            var match = KEYS.every(function(k) { return announce[k] === pv[k]; });
            if (match) return PRESET_NAMES[i];
        }
        return 'custom';
    }

    function loadState() {
        var defaults = presetValues('standard');
        try {
            var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            ttsEnabled = saved.enabled || false;
            ttsEntityId = saved.entity_id || '';
            KEYS.forEach(function(k) {
                announce[k] = (typeof saved[k] === 'boolean') ? saved[k] : defaults[k];
            });
            // Pre-#2 saved configs have no `preset` — derive it from the toggles.
            ttsPreset = saved.preset || detectPreset();
        } catch (e) {
            KEYS.forEach(function(k) { announce[k] = defaults[k]; });
            ttsPreset = 'standard';
        }
    }

    function saveState() {
        try {
            var payload = { enabled: ttsEnabled, entity_id: ttsEntityId, preset: ttsPreset };
            KEYS.forEach(function(k) { payload[k] = announce[k]; });
            localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } catch (e) { /* ignore */ }
    }

    function syncCheckboxes() {
        KEYS.forEach(function(k) {
            var el = document.getElementById(domId(k));
            if (el) el.checked = announce[k];
        });
    }

    function syncPresetChips() {
        ['minimal', 'standard', 'full', 'custom'].forEach(function(name) {
            var chip = document.getElementById('tts-preset-' + name);
            if (chip) chip.classList.toggle('chip--active', ttsPreset === name);
        });
    }

    function applyPreset(name) {
        var pv = presetValues(name);
        KEYS.forEach(function(k) { announce[k] = pv[k]; });
        ttsPreset = name;
        syncCheckboxes();
        syncPresetChips();
        saveState();
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

        // #2: verbosity preset chips. Picking one bulk-sets all 23 toggles.
        PRESET_NAMES.forEach(function(name) {
            var chip = document.getElementById('tts-preset-' + name);
            if (chip) {
                chip.addEventListener('click', function() { applyPreset(name); });
            }
        });

        // Per-event toggles. Editing one by hand re-derives the preset
        // (which usually flips it to "Custom"). The DOM IDs are optional —
        // a missing checkbox just falls back to the loaded value.
        KEYS.forEach(function(k) {
            var el = document.getElementById(domId(k));
            if (el) {
                el.checked = announce[k];
                el.addEventListener('change', function() {
                    announce[k] = this.checked;
                    ttsPreset = detectPreset();
                    syncPresetChips();
                    saveState();
                });
            }
        });
        syncPresetChips();

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

                BeatifyAuth.fetch('/beatify/api/tts-test', {
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

    // Expose for admin.js to read when starting game.
    window._ttsConfig = function() {
        var cfg = { enabled: ttsEnabled, entity_id: ttsEntityId };
        KEYS.forEach(function(k) { cfg[k] = announce[k]; });
        return cfg;
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
