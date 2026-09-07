/**
 * Party Lights UI — Admin setup and gameplay controls (#331)
 */

// #2637: like tts-settings.js, this was a classic `<script>` publishing
// `window._partyLightsConfig` for admin.js to read back. It is now an ES module
// imported by admin.js, so the bundle check covers it.

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Translate, with the English wording as the fallback (#2704).
 *
 * init() runs at DOMContentLoaded while admin.js is still awaiting
 * BeatifyI18n.init(), so the first paint happens before any locale is loaded —
 * BeatifyI18n.t() would hand back the raw key. The static markup carries
 * data-i18n and is fixed up by initPageTranslations(); the labels this module
 * composes are refreshed by refreshPartyLightsLabels(), which admin.js calls
 * once translations are in.
 */
function tr(key, fallback, params) {
    var i18n = typeof window !== 'undefined' ? window.BeatifyI18n : null;
    if (!i18n || typeof i18n.t !== 'function' || !i18n.isReady()) return fallback;
    var value = i18n.t(key, params);
    return value === key ? fallback : value;
}

var STORAGE_KEY = 'beatify_party_lights';
var selectedLights = [];
var selectedIntensity = 'medium';
var selectedLightMode = 'dynamic';
var wledPresets = {};
var partyLightsEnabled = false;
var lightsData = [];

// Load saved state
function loadState() {
    try {
        var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
        selectedLights = saved.lights || [];
        selectedIntensity = saved.intensity || 'medium';
        selectedLightMode = saved.light_mode || 'dynamic';
        wledPresets = saved.wled_presets || {};
        // #1011 follow-up: legacy payloads written by pre-#1031 wizard runs
        // are missing the `enabled` key entirely. Without recovery the
        // admin panel hydrates the toggle as off even though the user
        // had configured lights, and the game-start request carries
        // `enabled: false`. Treat "has lights but no explicit enabled
        // flag" as implied enabled. Explicit `false` still wins.
        if (typeof saved.enabled === 'boolean') {
            partyLightsEnabled = saved.enabled;
        } else {
            partyLightsEnabled = selectedLights.length > 0;
        }
    } catch (e) { /* ignore */ }
}

function saveState() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            lights: selectedLights,
            intensity: selectedIntensity,
            light_mode: selectedLightMode,
            wled_presets: wledPresets,
            enabled: partyLightsEnabled
        }));
    } catch (e) { /* ignore */ }
}

// Fetch available lights from API
async function fetchLights() {
    try {
        var resp = await BeatifyAuth.fetch('/beatify/api/lights');
        var data = await resp.json();
        lightsData = data.lights || [];
        renderLightPicker();
    } catch (e) {
        console.warn('[PartyLights] Failed to fetch lights:', e);
        var list = document.getElementById('party-lights-list');
        if (list) {
            list.innerHTML = '<span class="loading-text">'
                + escapeHtml(tr('wizard.step5.lights.noneFound', 'No lights available'))
                + '</span>';
        }
    }
}

function renderLightPicker() {
    var list = document.getElementById('party-lights-list');
    if (!list) return;

    if (lightsData.length === 0) {
        list.innerHTML = '<span class="loading-text">'
            + escapeHtml(tr('wizard.step5.lights.unavailable', 'No lights found in Home Assistant.'))
            + '</span>';
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
    var n = selectedLights.length;

    if (countEl) {
        countEl.textContent = tr(
            'admin.partyLights.selected', n + ' lights selected', { n: n });
    }
    if (previewBtn) previewBtn.disabled = n === 0;
    if (summary) {
        summary.textContent = partyLightsEnabled && n > 0
            ? tr('admin.partyLights.lights', n + ' lights', { n: n })
            : tr('admin.partyLights.off', 'Off');
    }
}

/**
 * Re-render the labels this module owns after a locale change (#2704).
 *
 * initPageTranslations() only reaches elements carrying a data-i18n
 * attribute; the selection count, the section summary and the select-all
 * toggle are composed here, so admin.js and the language chips call this
 * alongside it — the same arrangement game-settings.js uses for the
 * auto-advance chips and the difficulty hint.
 */
export function refreshPartyLightsLabels() {
    updateCount();
    var selectAllBtn = document.getElementById('lights-select-all');
    var list = document.getElementById('party-lights-list');
    if (selectAllBtn && list) {
        var boxes = list.querySelectorAll('input[type="checkbox"]');
        var allChecked = boxes.length > 0
            && list.querySelectorAll('input[type="checkbox"]:checked').length === boxes.length;
        selectAllBtn.textContent = allChecked
            ? tr('admin.partyLights.deselectAll', 'Deselect All')
            : tr('admin.partyLights.selectAll', 'Select All');
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

    // Light mode chips
    document.querySelectorAll('.chip[data-light-mode]').forEach(function(chip) {
        if (chip.dataset.lightMode === selectedLightMode) {
            chip.classList.add('chip--active');
        } else {
            chip.classList.remove('chip--active');
        }
        chip.addEventListener('click', function() {
            document.querySelectorAll('.chip[data-light-mode]').forEach(function(c) {
                c.classList.remove('chip--active');
            });
            this.classList.add('chip--active');
            selectedLightMode = this.dataset.lightMode;
            // Show/hide WLED preset inputs
            var wledRow = document.getElementById('party-lights-wled-presets');
            if (wledRow) {
                wledRow.classList.toggle('hidden', selectedLightMode !== 'wled');
            }
            saveState();
        });
    });

    // WLED preset inputs
    var wledRow = document.getElementById('party-lights-wled-presets');
    if (wledRow) {
        wledRow.classList.toggle('hidden', selectedLightMode !== 'wled');
        wledRow.querySelectorAll('input[data-wled-phase]').forEach(function(input) {
            var phase = input.dataset.wledPhase;
            if (wledPresets[phase] !== undefined) {
                input.value = wledPresets[phase];
            }
            input.addEventListener('change', function() {
                var val = parseInt(this.value, 10);
                if (!isNaN(val) && val >= 0) {
                    wledPresets[this.dataset.wledPhase] = val;
                } else {
                    delete wledPresets[this.dataset.wledPhase];
                }
                saveState();
            });
        });
    }

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
            selectAllBtn.textContent = allChecked
                ? tr('admin.partyLights.selectAll', 'Select All')
                : tr('admin.partyLights.deselectAll', 'Deselect All');
            updateSelection();
        });
    }

    // Preview button
    var previewBtn = document.getElementById('party-lights-preview');
    function resetPreviewLabel() {
        if (previewBtn) previewBtn.textContent = tr('admin.partyLights.preview', '✨ Preview');
    }
    if (previewBtn) {
        previewBtn.addEventListener('click', function() {
            if (selectedLights.length === 0) return;
            previewBtn.disabled = true;
            previewBtn.textContent = tr('admin.partyLights.previewRunning', '✨ Running…');

            BeatifyAuth.fetch('/beatify/api/preview-lights', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_ids: selectedLights, intensity: selectedIntensity })
            }).then(function(resp) {
                if (!resp.ok) {
                    console.warn('[PartyLights] Preview failed:', resp.status);
                    previewBtn.textContent = tr('admin.partyLights.previewFailed', '✨ Failed');
                    setTimeout(resetPreviewLabel, 3000);
                    return;
                }
                resetPreviewLabel();
            }).catch(function(err) {
                console.warn('[PartyLights] Preview error:', err);
                previewBtn.textContent = tr('admin.partyLights.previewError', '✨ Error');
                setTimeout(resetPreviewLabel, 3000);
            }).finally(function() {
                previewBtn.disabled = false;
            });
        });
    }

    // Fetch lights
    fetchLights();
}

/**
 * The party-lights block of the start-game / update-lobby payload.
 *
 * Re-loads from localStorage so wizard-written values (saved after this
 * module's init ran) are picked up. Without this, the start-game payload
 * carries the stale page-load defaults (enabled:false, no lights) and the
 * backend skips configure_party_lights, leaving the lights dark. Mirrors the
 * same fix in tts-settings.js (#1011 follow-up).
 *
 * #2637: was `window._partyLightsConfig`; admin.js imports it now.
 *
 * @returns {Object} enabled/entity_ids/intensity/light_mode (+ wled_presets)
 */
export function partyLightsConfig() {
    loadState();
    var config = {
        enabled: partyLightsEnabled,
        entity_ids: selectedLights,
        intensity: selectedIntensity,
        light_mode: selectedLightMode
    };
    if (selectedLightMode === 'wled' && Object.keys(wledPresets).length > 0) {
        config.wled_presets = wledPresets;
    }
    return config;
}

// #2637: as a bundle module this file is now reachable from the DOM-less vitest
// environment (a test importing game-settings.js pulls it in). Guard the
// auto-init on `document` so importing the config getter costs nothing outside a
// browser. In a browser the guard is always true and the timing is what it was:
// the bundle is a deferred module, so parsing is finished and `init()` runs
// straight away, exactly where the old classic script's DOMContentLoaded
// listener would have fired.
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}
