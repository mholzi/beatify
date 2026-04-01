/**
 * TTS Announcements UI — Admin setup (#447)
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'beatify_tts';
    var ttsEnabled = false;
    var ttsEntityId = '';

    function loadState() {
        try {
            var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            ttsEnabled = saved.enabled || false;
            ttsEntityId = saved.entity_id || '';
        } catch (e) { /* ignore */ }
    }

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                enabled: ttsEnabled,
                entity_id: ttsEntityId
            }));
        } catch (e) { /* ignore */ }
    }

    function updateSummary() {
        var summary = document.getElementById('tts-settings-summary');
        if (summary) {
            summary.textContent = ttsEnabled && ttsEntityId ? ttsEntityId : 'Off';
        }
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
                saveState();
            });
        }

        // Collapsible section toggle
        var toggle = document.getElementById('tts-settings-toggle');
        if (toggle) {
            toggle.addEventListener('click', function() {
                var section = document.getElementById('tts-settings');
                if (section) {
                    var isCollapsed = section.classList.toggle('collapsed');
                    toggle.setAttribute('aria-expanded', !isCollapsed);
                }
            });
        }

        updateSummary();
    }

    // Expose for admin.js to read when starting game
    window._ttsConfig = function() {
        return {
            enabled: ttsEnabled,
            entity_id: ttsEntityId
        };
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
