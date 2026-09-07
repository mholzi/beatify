/**
 * The guest's own language on the join screen (#2585).
 *
 * The host picks one language in the wizard and the server repeats it in every
 * `state` frame. player-core used to hand each frame straight to
 * `BeatifyI18n.setLanguage()`, so the Dutch au pair at a German host's party
 * read a German phone all evening — even though nl.json has shipped for a year.
 *
 * The rule this module implements, in order:
 *
 *   1. a stored choice   — the guest tapped a chip on this device
 *   2. the browser guess — the first supported entry in navigator.languages
 *   3. the host language — whatever the state frame carries
 *
 * Steps 1 and 2 are `guestLanguage()`; step 3 is the caller's fallback. A phone
 * whose language we do not ship (pt-BR) produces null at both of the first two
 * steps and therefore follows the host — the rest of the room speaks it, and it
 * is a better answer than the English `setLanguage()` would otherwise fall back
 * to.
 *
 * Only the phone follows its owner. TTS and the TV stay on the host's language,
 * so the room keeps one voice.
 *
 * The join screen states the result rather than asking for it: "🇳🇱 Nederlands ·
 * andere taal", rendered in the language it names. Tapping the link reveals the
 * other chips. A statement that can be contradicted, not a question.
 */

/**
 * Where the tapped choice lives. Separate from `beatify_language`, which
 * player-core uses to remember the language the last *game* on this device ran
 * in — that one is a cache of the host's pick and must not outrank the guest.
 */
export var STORAGE_KEY_GUEST_LANGUAGE = 'beatify_guest_language';

/**
 * `localStorage`, or null when it is unavailable.
 *
 * The access itself is inside the try, not just the get/set: Safari in private
 * mode has historically thrown on the property read, and this module runs
 * before anything else on the join screen.
 * @returns {Storage|null}
 */
function defaultStorage() {
    try {
        return typeof localStorage === 'undefined' ? null : localStorage;
    } catch (e) {
        return null;
    }
}

/** The i18n module, or null if it failed to load. @returns {Object|null} */
function i18nModule() {
    if (typeof window !== 'undefined' && window.BeatifyI18n) {
        return window.BeatifyI18n;
    }
    return null;
}

/**
 * Read the stored choice, validated against the languages we currently ship.
 *
 * The validation is the point: a stored 'pl' from a build where Polish existed
 * (#2475) would otherwise pin the phone to a locale whose JSON is gone —
 * `setLanguage()` would normalise it to English and the guest would be stuck
 * there, with the host's language locked out too. An unsupported stored value
 * is treated as no value at all, so the phone falls through to the host.
 *
 * @param {Storage} [storage] - injectable for tests
 * @returns {string|null}
 */
export function readStoredLanguage(storage) {
    var store = storage === undefined ? defaultStorage() : storage;
    if (!store) {
        return null;
    }
    var raw;
    try {
        raw = store.getItem(STORAGE_KEY_GUEST_LANGUAGE);
    } catch (e) {
        return null;
    }
    var i18n = i18nModule();
    if (!i18n || typeof i18n.normalizeLanguage !== 'function') {
        return null;
    }
    // normalizeLanguage also rejects anything that is not a supported code, so
    // a hand-edited localStorage value cannot reach setLanguage().
    return i18n.normalizeLanguage(raw);
}

/**
 * Persist the guest's tapped choice.
 *
 * No expiry on purpose. The line sits on the join screen of every game this
 * device ever joins and always names the language in force, so a wrong value
 * costs one tap to correct — while an expiry would silently revert a *right*
 * value on the au pair's own phone, which is the case this issue exists for.
 * The shared-tablet case is handled by the same line: the next guest reads a
 * language they do not speak and taps.
 *
 * @param {string} code
 * @param {Storage} [storage] - injectable for tests
 * @returns {boolean} - whether the value was written
 */
export function storeGuestLanguage(code, storage) {
    var i18n = i18nModule();
    var normalized = i18n && typeof i18n.normalizeLanguage === 'function'
        ? i18n.normalizeLanguage(code)
        : null;
    if (!normalized) {
        return false;
    }
    var store = storage === undefined ? defaultStorage() : storage;
    if (!store) {
        return false;
    }
    try {
        store.setItem(STORAGE_KEY_GUEST_LANGUAGE, normalized);
        return true;
    } catch (e) {
        // Private mode / quota. The choice still applies to this page load.
        return false;
    }
}

/**
 * The language this phone speaks for its own sake, or null to follow the host.
 *
 * @param {Storage} [storage] - injectable for tests
 * @returns {string|null}
 */
export function guestLanguage(storage) {
    var stored = readStoredLanguage(storage);
    if (stored) {
        return stored;
    }
    var i18n = i18nModule();
    if (i18n && typeof i18n.matchBrowserLanguage === 'function') {
        return i18n.matchBrowserLanguage();
    }
    return null;
}

/**
 * Which language a `state` frame should actually apply on this phone (#2585).
 *
 * Pure, so the one decision the whole issue turns on is testable without a DOM:
 * the host's pick is the room's default, not a command.
 *
 * @param {string|null} guest - result of guestLanguage()
 * @param {string|null} hostLanguage - data.language from the state frame
 * @returns {string|null}
 */
export function resolveStateLanguage(guest, hostLanguage) {
    return guest || hostLanguage || null;
}

/**
 * Redraw the language line: the statement, and the chips for the others.
 *
 * The chip labels are endonyms and never change with the locale, but the *set*
 * does — the language currently in force is named in the line above and is not
 * repeated as a chip — so this runs after every switch, including the one a
 * state frame triggers on a phone that follows the host.
 */
export function renderGuestLanguage() {
    if (typeof document === 'undefined') {
        return;
    }
    var root = document.getElementById('join-language');
    if (!root) {
        return;
    }
    var i18n = i18nModule();
    if (!i18n || typeof i18n.getLanguageOptions !== 'function') {
        // i18n never loaded; a row that cannot name a language is worse than
        // no row, and the join button above it still works.
        root.classList.add('hidden');
        return;
    }

    var current = i18n.getLanguage();
    var options = i18n.getLanguageOptions();
    var currentOption = null;
    for (var i = 0; i < options.length; i++) {
        if (options[i].code === current) {
            currentOption = options[i];
        }
    }

    var currentEl = document.getElementById('join-language-current');
    if (currentEl) {
        currentEl.textContent = currentOption
            ? currentOption.flag + ' ' + currentOption.label
            : String(current || '').toUpperCase();
    }

    var chips = document.getElementById('join-language-chips');
    if (chips) {
        chips.innerHTML = '';
        options.forEach(function(option) {
            if (option.code === current) {
                return;
            }
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'join-language-chip';
            btn.setAttribute('data-lang', option.code);
            btn.setAttribute('lang', option.code);
            btn.textContent = option.flag + ' ' + option.label;
            btn.addEventListener('click', function() {
                chooseGuestLanguage(option.code);
            });
            chips.appendChild(btn);
        });
    }

    root.classList.remove('hidden');
}

/** Collapse the chip row and put the toggle back in its unexpanded state. */
function collapseChips() {
    if (typeof document === 'undefined') {
        return;
    }
    var chips = document.getElementById('join-language-chips');
    var toggle = document.getElementById('join-language-toggle');
    if (chips) {
        chips.classList.add('hidden');
    }
    if (toggle) {
        toggle.setAttribute('aria-expanded', 'false');
    }
}

/**
 * Apply and remember a language the guest tapped.
 * @param {string} code
 * @returns {Promise<void>}
 */
export function chooseGuestLanguage(code) {
    var i18n = i18nModule();
    if (!i18n || typeof i18n.setLanguage !== 'function') {
        return Promise.resolve();
    }
    storeGuestLanguage(code);
    return i18n.setLanguage(code).then(function() {
        if (typeof i18n.initPageTranslations === 'function') {
            i18n.initPageTranslations();
        }
        collapseChips();
        renderGuestLanguage();
    });
}

/** Wire the "other language" link and draw the line for the first time. */
export function setupGuestLanguage() {
    if (typeof document === 'undefined') {
        return;
    }
    var toggle = document.getElementById('join-language-toggle');
    var chips = document.getElementById('join-language-chips');
    if (toggle && chips) {
        // The markup ships collapsed; say so here too, so the state the
        // listener toggles is always one this module set.
        chips.classList.add('hidden');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.addEventListener('click', function() {
            var opening = chips.classList.contains('hidden');
            chips.classList.toggle('hidden', !opening);
            toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
        });
    }
    renderGuestLanguage();
}
