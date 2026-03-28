/**
 * Party Lights UI — Admin setup and gameplay controls (#331)
 */
(function() {
    'use strict';

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    var STORAGE_KEY = 'beatify_party_lights';
    var selectedLights = [];
    var selectedIntensity = 'medium';
    var partyLightsEnabled = false;
    var lightsData = [];

    // Load saved state
    function loadState() {
        try {
            var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            selectedLights = saved.lights || [];
            selectedIntensity = saved.intensity || 'medium';
            partyLightsEnabled = saved.enabled || false;
        } catch (e) { /* ignore */ }
    }

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                lights: selectedLights,
                intensity: selectedIntensity,
                enabled: partyLightsEnabled
            }));
        } catch (e) { /* ignore */ }
    }

    // Fetch available lights from API
    async function fetchLights() {
        try {
            var resp = await fetch('/beatify/api/lights');
            var data = await resp.json();
            lightsData = data.lights || [];
            renderLightPicker();
        } catch (e) {
            console.warn('[PartyLights] Failed to fetch lights:', e);
            var list = document.getElementById('party-lights-list');
            if (list) list.innerHTML = '<span class="loading-text">No lights found</span>';
        }
    }

    function renderLightPicker() {
        var list = document.getElementById('party-lights-list');
        if (!list) return;

        if (lightsData.length === 0) {
            list.innerHTML = '<span class="loading-text">No lights found in Home Assistant</span>';
            return;
        }

        var capLabels = { rgb: 'RGB', ct: 'CT', dim: 'Dim', onoff: 'On/Off' };
        var stateIcons = { on: '🟢', off: '⚪', unavailable: '🔴' };

        list.innerHTML = lightsData.map(function(light) {
            var checked = selectedLights.indexOf(light.entity_id) !== -1 ? 'checked' : '';
            var cap = capLabels[light.capability] || 'On/Off';
            var icon = stateIcons[light.state] || '⚪';
            return '<label class="party-light-item">' +
                '<input type="checkbox" value="' + escapeHtml(light.entity_id) + '" ' + checked + '>' +
                '<span class="light-status">' + icon + '</span>' +
                '<span class="light-name">' + escapeHtml(light.friendly_name || light.entity_id) + '</span>' +
                '<span class="light-cap-badge">' + cap + '</span>' +
                '</label>';
        }).join('');

        // Bind checkboxes
        list.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
            cb.addEventListener('change', function() {
                updateSelection();
            });
        });

        updateCount();
    }

    function updateSelection() {
        var list = document.getElementById('party-lights-list');
        if (!list) return;
        selectedLights = [];
        list.querySelectorAll('input[type="checkbox"]:checked').forEach(function(cb) {
            selectedLights.push(cb.value);
        });
        updateCount();
        saveState();
    }

    function updateCount() {
        var countEl = document.getElementById('lights-selected-count');
        var previewBtn = document.getElementById('party-lights-preview');
        var summary = document.getElementById('party-lights-summary');

        if (countEl) countEl.textContent = selectedLights.length;
        if (previewBtn) previewBtn.disabled = selectedLights.length === 0;
        if (summary) {
            summary.textContent = partyLightsEnabled && selectedLights.length > 0
                ? selectedLights.length + ' lights'
                : 'Off';
        }
    }

    function init() {
        loadState();

        // Enable toggle
        var enableToggle = document.getElementById('party-lights-enable');
        if (enableToggle) {
            enableToggle.checked = partyLightsEnabled;
            enableToggle.addEventListener('change', function() {
                partyLightsEnabled = this.checked;
                updateCount();
                saveState();
            });
        }

        // Intensity chips
        document.querySelectorAll('.chip[data-intensity]').forEach(function(chip) {
            if (chip.dataset.intensity === selectedIntensity) {
                chip.classList.add('chip--active');
            } else {
                chip.classList.remove('chip--active');
            }
            chip.addEventListener('click', function() {
                document.querySelectorAll('.chip[data-intensity]').forEach(function(c) {
                    c.classList.remove('chip--active');
                });
                this.classList.add('chip--active');
                selectedIntensity = this.dataset.intensity;
                saveState();
            });
        });

        // Select all button
        var selectAllBtn = document.getElementById('lights-select-all');
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', function() {
                var list = document.getElementById('party-lights-list');
                if (!list) return;
                var allChecked = list.querySelectorAll('input[type="checkbox"]:checked').length === lightsData.length;
                list.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
                    cb.checked = !allChecked;
                });
                selectAllBtn.textContent = allChecked ? 'Select All' : 'Deselect All';
                updateSelection();
            });
        }

        // Preview button
        var previewBtn = document.getElementById('party-lights-preview');
        if (previewBtn) {
            previewBtn.addEventListener('click', function() {
                if (selectedLights.length === 0) return;
                previewBtn.disabled = true;
                previewBtn.textContent = '✨ Running...';

                fetch('/beatify/api/preview-lights', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ entity_ids: selectedLights, intensity: selectedIntensity })
                }).then(function(resp) {
                    if (!resp.ok) {
                        console.warn('[PartyLights] Preview failed:', resp.status);
                        previewBtn.textContent = '✨ Failed';
                        setTimeout(function() { previewBtn.textContent = '✨ Preview'; }, 3000);
                        return;
                    }
                    previewBtn.textContent = '✨ Preview';
                }).catch(function(err) {
                    console.warn('[PartyLights] Preview error:', err);
                    previewBtn.textContent = '✨ Error';
                    setTimeout(function() { previewBtn.textContent = '✨ Preview'; }, 3000);
                }).finally(function() {
                    previewBtn.disabled = false;
                });
            });
        }

        // Collapsible section toggle
        var toggle = document.getElementById('party-lights-toggle');
        if (toggle) {
            toggle.addEventListener('click', function() {
                var section = document.getElementById('party-lights');
                if (section) {
                    var isCollapsed = section.classList.toggle('collapsed');
                    toggle.setAttribute('aria-expanded', !isCollapsed);
                }
            });
        }

        // Fetch lights
        fetchLights();
    }

    // Expose for admin.js to read when starting game
    window._partyLightsConfig = function() {
        return {
            enabled: partyLightsEnabled,
            entity_ids: selectedLights,
            intensity: selectedIntensity
        };
    };

    // Init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
