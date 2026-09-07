/**
 * Beatify Internationalization (i18n) Module
 * Provides translation functionality for all UI text
 */
// Use window.BeatifyI18n to ensure global availability after minification (IIFE wrapping)
window.BeatifyI18n = (function() {
    'use strict';

    // Current language code
    var currentLanguage = 'en';

    // Loaded translations
    var translations = {};

    // Fallback translations (English)
    var fallbackTranslations = {};

    // Loading state
    var isLoaded = false;
    var loadPromise = null;

    // #1399: concurrency guard. setLanguage() is called from several places
    // (admin loadSavedSettings, the wizard language chip, dashboard
    // state-driven switches) and each one awaits an async fetch. Without a
    // generation token a slower in-flight fetch can resolve AFTER a newer
    // setLanguage() and clobber `translations` with the wrong locale (stale
    // de.json landing while currentLanguage is already 'en'). _loadGen is
    // bumped on every loadTranslations() entry; a fetch only commits its
    // result if its captured gen is still the latest.
    var _loadGen = 0;
    // Promise that resolves when the most recent setLanguage()/init() load
    // settles. Callers (e.g. dashboard handleStateUpdate) can await this to
    // avoid rendering with empty/stale translations while a load is in flight.
    var languageReadyPromise = Promise.resolve();

    /**
     * Load translations for a specific language
     * @param {string} langCode - Language code ('en', 'de', 'es', or 'fr')
     * @returns {Promise<Object>} - Loaded translations
     */
    /**
     * Read the page's version (set via <meta name="beatify-version" ...>) so
     * we can cache-bust the i18n fetch URL. Without this, the service-worker
     * cache-first strategy serves a stale en.json from a prior rc — a user
     * who updates from rc14 to rc18 would still see raw keys like
     * "admin.home.waitingForGuests" because the new admin.min.js refers to
     * keys that the cached en.json doesn't have. (#824)
     */
    function getVersionForCacheBust() {
        if (typeof document === 'undefined') return '';
        // Prefer the asset-fingerprint version (#1266): it moves whenever any
        // i18n JSON changes, so editing de.json without a manifest bump still
        // busts the SW cache. Fall back to the plain version for older cached
        // shells that predate the beatify-asset-version meta tag (#824).
        var assetMeta = document.querySelector('meta[name="beatify-asset-version"]');
        var assetVer = assetMeta ? assetMeta.getAttribute('content') || '' : '';
        if (assetVer) return assetVer;
        var meta = document.querySelector('meta[name="beatify-version"]');
        return meta ? meta.getAttribute('content') || '' : '';
    }

    async function fetchTranslations(langCode) {
        var v = getVersionForCacheBust();
        var qs = v ? ('?v=' + encodeURIComponent(v)) : '';
        try {
            var response = await fetch('/beatify/static/i18n/' + langCode + '.json' + qs);
            if (!response.ok) {
                console.warn('[i18n] Failed to load ' + langCode + '.json:', response.status);
                return {};
            }
            return await response.json();
        } catch (err) {
            console.warn('[i18n] Error loading ' + langCode + '.json:', err);
            return {};
        }
    }

    /**
     * Load translations for current language
     * @returns {Promise<void>}
     */
    async function loadTranslations() {
        // #1399: capture this load's generation + target locale up front.
        // A newer setLanguage() bumps _loadGen, so a slower fetch started here
        // can detect it is stale and refuse to commit its (now wrong) result.
        var gen = ++_loadGen;
        var targetLang = currentLanguage;

        // Load English as fallback first
        if (Object.keys(fallbackTranslations).length === 0) {
            var fb = await fetchTranslations('en');
            // Fallback is locale-independent, so a superseding load doesn't
            // invalidate it — always keep it once fetched.
            if (Object.keys(fallbackTranslations).length === 0) {
                fallbackTranslations = fb;
            }
        }

        // Load current language
        var data;
        if (targetLang === 'en') {
            data = fallbackTranslations;
        } else {
            data = await fetchTranslations(targetLang);
        }

        // #1399: bail if a newer setLanguage() has superseded this load while
        // our fetch was in flight — committing now would clobber the active
        // locale with stale data.
        if (gen !== _loadGen) {
            return;
        }

        translations = data;
        isLoaded = true;
    }

    /**
     * Get nested value from object using dot notation
     * @param {Object} obj - Object to traverse
     * @param {string} key - Dot-separated key path
     * @returns {string|undefined} - Found value or undefined
     */
    function getNestedValue(obj, key) {
        if (!obj || !key) return undefined;

        var parts = key.split('.');
        var current = obj;

        for (var i = 0; i < parts.length; i++) {
            if (current === undefined || current === null) {
                return undefined;
            }
            current = current[parts[i]];
        }

        return current;
    }

    /**
     * Translate a key to the current language
     * @param {string} key - Translation key (e.g., 'lobby.title')
     * @param {Object} [params] - Optional parameters for interpolation
     * @returns {string} - Translated string
     */
    function t(key, params) {
        // Try current language first
        var value = getNestedValue(translations, key);

        // Fall back to English if not found
        if (value === undefined && currentLanguage !== 'en') {
            value = getNestedValue(fallbackTranslations, key);
            if (value !== undefined && isLoaded) {
                // Only warn after initial load — pre-init t() calls would
                // spam the console with false positives. initPageTranslations()
                // re-renders data-i18n elements after load, replacing any
                // raw-key text the user briefly saw.
                console.warn('[i18n] Missing translation for "' + key + '" in ' + currentLanguage + ', using English');
            }
        }

        // Return key itself as last resort
        if (value === undefined) {
            if (isLoaded) {
                console.warn('[i18n] Missing translation key: "' + key + '"');
            }
            return key;
        }

        // Interpolate parameters if provided
        if (params && typeof value === 'string') {
            Object.keys(params).forEach(function(param) {
                value = value.replace(new RegExp('\\{' + param + '\\}', 'g'), params[param]);
            });
        }

        return value;
    }

    /**
     * Get error message for error code
     * @param {string} code - Error code from server
     * @returns {string} - Translated error message
     */
    function getErrorMessage(code) {
        // #1402-B8: t() returns the key itself when a translation is missing —
        // it never returns a falsy value — so the old `|| t('errors.UNKNOWN')`
        // fallback was dead code (an unknown code yielded the raw "errors.FOO"
        // string instead of the generic message). Compare against the key.
        var key = 'errors.' + code;
        var msg = t(key);
        return msg === key ? t('errors.UNKNOWN') : msg;
    }

    /**
     * Supported languages (Story 16.3 - added Spanish)
     */
    var SUPPORTED_LANGUAGES = ['en', 'de', 'es', 'fr', 'nl', 'it'];

    /**
     * How each supported language names itself (#2585).
     *
     * Deliberately NOT in the translation JSON: a language's own name is the
     * same on every phone in the room. The Dutch au pair looking at a German
     * host's party should read "Nederlands", not "Niederländisch" — the point
     * of the chip is that she can recognise it without reading the rest of the
     * screen. So this is data, not translated text.
     *
     * `__tests__/guest-language-2585.test.js` asserts that every code in
     * SUPPORTED_LANGUAGES has an entry here, so adding Polish (#2475) fails a
     * test rather than shipping a bare "PL" chip.
     */
    var LANGUAGE_ENDONYMS = {
        en: { label: 'English', flag: '🇬🇧' },
        de: { label: 'Deutsch', flag: '🇩🇪' },
        es: { label: 'Español', flag: '🇪🇸' },
        fr: { label: 'Français', flag: '🇫🇷' },
        nl: { label: 'Nederlands', flag: '🇳🇱' },
        it: { label: 'Italiano', flag: '🇮🇹' }
    };

    /**
     * The supported codes, as a copy so a caller can't reorder the original.
     * @returns {string[]}
     */
    function getSupportedLanguages() {
        return SUPPORTED_LANGUAGES.slice();
    }

    /**
     * One entry per supported language, in SUPPORTED_LANGUAGES order (#2585).
     * A code with no endonym still renders — as its own uppercased code — so a
     * seventh locale added in a hurry degrades instead of throwing.
     * @returns {Array<{code: string, label: string, flag: string}>}
     */
    function getLanguageOptions() {
        return SUPPORTED_LANGUAGES.map(function(code) {
            var meta = LANGUAGE_ENDONYMS[code] || {};
            return {
                code: code,
                label: meta.label || code.toUpperCase(),
                flag: meta.flag || '🌐'
            };
        });
    }

    /**
     * Reduce a BCP-47 tag to a supported two-letter code, or null (#2585).
     *
     * 'nl-BE' -> 'nl', 'PT-br' -> null. Replaces the hand-listed
     * startsWith() ladder detectBrowserLanguage used to carry, which had to
     * grow a branch per locale and silently answered 'en' for anything the
     * ladder had not been taught.
     *
     * @param {string} tag - e.g. navigator.language
     * @returns {string|null} - supported code, or null when nothing matches
     */
    function normalizeLanguage(tag) {
        if (!tag || typeof tag !== 'string') {
            return null;
        }
        var base = tag.toLowerCase().trim().split('-')[0].split('_')[0];
        return SUPPORTED_LANGUAGES.indexOf(base) === -1 ? null : base;
    }

    /**
     * The first supported language this browser asks for, or null (#2585).
     *
     * Reads navigator.languages (the ordered preference list) before
     * navigator.language, so a phone set to Portuguese with English second
     * lands on English rather than on nothing.
     *
     * Returns null — not 'en' — when no entry matches, because the caller has
     * to tell "this phone speaks a language we ship" apart from "we have no
     * idea"; the join screen answers the second case by following the host.
     *
     * @returns {string|null}
     */
    function matchBrowserLanguage() {
        var tags = [];
        if (typeof navigator !== 'undefined' && navigator) {
            if (Array.isArray(navigator.languages)) {
                tags = tags.concat(navigator.languages);
            }
            if (navigator.language) {
                tags.push(navigator.language);
            }
            if (navigator.userLanguage) {
                tags.push(navigator.userLanguage);
            }
        }
        for (var i = 0; i < tags.length; i++) {
            var code = normalizeLanguage(tags[i]);
            if (code) {
                return code;
            }
        }
        return null;
    }

    /**
     * Set the current language
     * @param {string} langCode - Language code ('en', 'de', 'es', or 'fr')
     * @returns {Promise<string>} - The effectively-applied (normalized) code.
     *   An unsupported code resolves to 'en'; callers that drive a render off
     *   the requested code (dashboard handleStateUpdate) MUST compare against
     *   THIS resolved value, not the raw request — otherwise a game state
     *   carrying an unsupported language (e.g. 'pt') would loop forever:
     *   getLanguage() can never equal 'pt', so each re-render re-invokes
     *   setLanguage → resolve → re-render → ... (#1402-B8).
     */
    async function setLanguage(langCode) {
        // Validate language code (Story 16.3 - added Spanish support)
        if (SUPPORTED_LANGUAGES.indexOf(langCode) === -1) {
            console.warn('[i18n] Invalid language code: ' + langCode + ', defaulting to en');
            langCode = 'en';
        }

        if (langCode === currentLanguage && isLoaded) {
            return langCode;
        }

        currentLanguage = langCode;

        // #1177: keep <html lang="..."> in sync so Android Chrome doesn't auto-translate
        // German UI ("Tipp abgeben" → "Trinkgeld abgeben") because the static lang="en"
        // attribute disagrees with the rendered locale.
        if (typeof document !== 'undefined' && document.documentElement) {
            document.documentElement.lang = langCode;
        }

        // #1399: expose the in-flight load so callers (e.g. dashboard's
        // handleStateUpdate) can await it instead of rendering early with
        // empty/stale translations — getLanguage() already returns the new
        // code synchronously, so without this a concurrent render would skip
        // its wait branch and flash raw keys / the previous locale.
        languageReadyPromise = loadTranslations();
        await languageReadyPromise;
        return langCode;
    }

    /**
     * Get current language code
     * @returns {string} - Current language code
     */
    function getLanguage() {
        return currentLanguage;
    }

    /**
     * Initialize page translations by replacing data-i18n elements
     * Call this after translations are loaded and DOM is ready
     */
    function initPageTranslations() {
        var elements = document.querySelectorAll('[data-i18n]');
        elements.forEach(function(el) {
            var key = el.getAttribute('data-i18n');
            if (key) {
                var translated = t(key);
                // Only update if we got a real translation (not the key back)
                if (translated !== key) {
                    el.textContent = translated;
                }
            }
        });

        // Handle placeholders
        var placeholderElements = document.querySelectorAll('[data-i18n-placeholder]');
        placeholderElements.forEach(function(el) {
            var key = el.getAttribute('data-i18n-placeholder');
            if (key) {
                var translated = t(key);
                if (translated !== key) {
                    el.placeholder = translated;
                }
            }
        });

        // Handle title attributes
        var titleElements = document.querySelectorAll('[data-i18n-title]');
        titleElements.forEach(function(el) {
            var key = el.getAttribute('data-i18n-title');
            if (key) {
                var translated = t(key);
                if (translated !== key) {
                    el.title = translated;
                }
            }
        });

        // Handle aria-labels (#2705). player.html has carried
        // data-i18n-aria-label on eight controls since the reveal sheet
        // landed, but nothing ever read the attribute — every screen reader
        // heard "Fire reaction" and "Next round countdown" in English no
        // matter the locale. admin.html's icon-only buttons need the same.
        var ariaElements = document.querySelectorAll('[data-i18n-aria-label]');
        ariaElements.forEach(function(el) {
            var key = el.getAttribute('data-i18n-aria-label');
            if (key) {
                var translated = t(key);
                if (translated !== key) {
                    el.setAttribute('aria-label', translated);
                }
            }
        });
    }

    /**
     * Detect the browser language, defaulting to English (Story 16.3).
     *
     * #2585: the per-locale startsWith() ladder became
     * matchBrowserLanguage(), which is derived from SUPPORTED_LANGUAGES.
     * This wrapper keeps the old contract — always a usable code — for
     * init() and every existing caller.
     *
     * @returns {string} - Detected language code, 'en' when nothing matches
     */
    function detectBrowserLanguage() {
        return matchBrowserLanguage() || 'en';
    }

    /**
     * Initialize i18n with optional language
     * @param {string} [langCode] - Language code, or auto-detect if not provided
     * @returns {Promise<void>}
     */
    async function init(langCode) {
        if (loadPromise) {
            return loadPromise;
        }

        var lang = langCode || detectBrowserLanguage();
        loadPromise = setLanguage(lang);
        await loadPromise;
    }

    /**
     * Check if translations are loaded
     * @returns {boolean}
     */
    function isReady() {
        return isLoaded;
    }

    /**
     * #1399: resolve once the most recent setLanguage()/init() load settles.
     * Callers that react to state broadcasts (dashboard handleStateUpdate)
     * should `await BeatifyI18n.languageReady()` before rendering dynamic
     * content so an in-flight locale switch doesn't render raw keys.
     * @returns {Promise<void>}
     */
    function languageReady() {
        return languageReadyPromise;
    }

    // Public API
    return {
        t: t,
        getErrorMessage: getErrorMessage,
        setLanguage: setLanguage,
        getLanguage: getLanguage,
        initPageTranslations: initPageTranslations,
        detectBrowserLanguage: detectBrowserLanguage,
        matchBrowserLanguage: matchBrowserLanguage,
        normalizeLanguage: normalizeLanguage,
        getSupportedLanguages: getSupportedLanguages,
        getLanguageOptions: getLanguageOptions,
        init: init,
        isReady: isReady,
        languageReady: languageReady
    };
})();

// Shorthand for translation function (use window to ensure global availability after minification)
window.t = window.BeatifyI18n.t;
