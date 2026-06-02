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
    var ttsPreRoundDelay = 0;  // #1211: seconds to add to deadline for TTS overhead

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
            ttsEntityId = saved.entity_id || '';
            // #1011 follow-up: legacy payloads from older wizards have
            // entity_id but no `enabled` key. Treat "entity selected with
            // no explicit enabled flag" as implied on. Explicit false wins.
            if (typeof saved.enabled === 'boolean') {
                ttsEnabled = saved.enabled;
            } else {
                ttsEnabled = !!ttsEntityId;
            }
            KEYS.forEach(function(k) {
                announce[k] = (typeof saved[k] === 'boolean') ? saved[k] : defaults[k];
            });
            // Pre-#2 saved configs have no `preset` — derive it from the toggles.
            ttsPreset = saved.preset || detectPreset();
            // #1211: load pre-round delay (0 = no offset, backward-compatible default).
            ttsPreRoundDelay = parseFloat(saved.tts_pre_round_delay) || 0;
        } catch (e) {
            KEYS.forEach(function(k) { announce[k] = defaults[k]; });
            ttsPreset = 'standard';
            ttsPreRoundDelay = 0;
        }
    }

    function saveState() {
        try {
            var payload = {
                enabled: ttsEnabled,
                entity_id: ttsEntityId,
                preset: ttsPreset,
                tts_pre_round_delay: ttsPreRoundDelay  // #1211
            };
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

    // #1073: replace free-text entity_id with a picker. Falls back gracefully
    // when the API errors or returns no entities — the user keeps whatever
    // they had before, and (in the empty case) sees a hint to add TTS in HA.
    function populateEntityDropdown(selectEl) {
        var emptyOption = selectEl.querySelector('option[value=""]');
        var emptyLabel = emptyOption ? emptyOption.textContent : '';
        var i18n = window.BeatifyI18n;
        var fetcher = (window.BeatifyAuth && window.BeatifyAuth.fetch)
            ? window.BeatifyAuth.fetch.bind(window.BeatifyAuth)
            : fetch;
        fetcher('/beatify/api/tts-entities').then(function(resp) {
            if (!resp.ok) return { entities: [] };
            return resp.json();
        }).then(function(data) {
            var entities = (data && data.entities) || [];
            // Clear old options except the placeholder.
            while (selectEl.options.length > (emptyOption ? 1 : 0)) {
                selectEl.remove(selectEl.options.length - 1);
            }
            if (entities.length === 0) {
                if (emptyOption) {
                    emptyOption.textContent = i18n && i18n.t
                        ? i18n.t('admin.ttsEntityNone')
                        : 'No TTS entities — add one in HA first';
                }
                selectEl.value = '';
                return;
            }
            if (emptyOption) emptyOption.textContent = emptyLabel;
            var seen = {};
            entities.forEach(function(e) {
                var opt = document.createElement('option');
                opt.value = e.entity_id;
                opt.textContent = e.friendly_name === e.entity_id
                    ? e.entity_id
                    : e.friendly_name + ' (' + e.entity_id + ')';
                selectEl.appendChild(opt);
                seen[e.entity_id] = true;
            });
            // Preserve a previously-saved entity that no longer exists (renamed
            // or removed in HA) so the user can see what they had configured.
            if (ttsEntityId && !seen[ttsEntityId]) {
                var staleOpt = document.createElement('option');
                staleOpt.value = ttsEntityId;
                staleOpt.textContent = ttsEntityId + ' '
                    + (i18n && i18n.t ? i18n.t('admin.ttsEntityStale') : '(not currently registered)');
                selectEl.appendChild(staleOpt);
            }
            selectEl.value = ttsEntityId || '';
        }).catch(function() { /* leave dropdown with just the placeholder */ });
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

        // Entity picker (#1073) — dropdown populated from /beatify/api/tts-entities.
        // The element is a <select> in admin.html; older browsers / tests with a
        // bare <input> still work because we only touch .value/.addEventListener.
        var entityInput = document.getElementById('tts-entity-id');
        if (entityInput) {
            entityInput.value = ttsEntityId;
            entityInput.addEventListener('change', function() {
                ttsEntityId = this.value.trim();
                updateSummary();
                updateTestButton();
                saveState();
            });
            // Keep the legacy text-input behaviour for environments that
            // still render an <input> (placeholder for tests / fallback).
            entityInput.addEventListener('input', function() {
                ttsEntityId = this.value.trim();
                updateSummary();
                updateTestButton();
                saveState();
            });
            if (entityInput.tagName === 'SELECT') {
                populateEntityDropdown(entityInput);
            }
        }

        // #1211: pre-round delay — seconds added to deadline for TTS overhead.
        var delayInput = document.getElementById('tts-pre-round-delay');
        if (delayInput) {
            delayInput.value = ttsPreRoundDelay;
            delayInput.addEventListener('change', function() {
                ttsPreRoundDelay = Math.max(0, parseFloat(this.value) || 0);
                this.value = ttsPreRoundDelay;
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
    // Re-load from localStorage so wizard-written values (saved after
    // this module's init ran) are picked up. Without this, the start-game
    // payload carries the stale page-load defaults (enabled:false) and the
    // backend skips configure_tts, leaving the game silent.
    window._ttsConfig = function() {
        loadState();
        var cfg = {
            enabled: ttsEnabled,
            entity_id: ttsEntityId,
            tts_pre_round_delay: ttsPreRoundDelay  // #1211
        };
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
