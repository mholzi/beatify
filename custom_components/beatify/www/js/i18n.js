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

    /**
     * Load translations for a specific language
     * @param {string} langCode - Language code ('en', 'de', 'es', or 'fr')
     * @returns {Promise<Object>} - Loaded translations
     */
    async function fetchTranslations(langCode) {
        try {
            var response = await fetch('/beatify/static/i18n/' + langCode + '.json');
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
        // Load English as fallback first
        if (Object.keys(fallbackTranslations).length === 0) {
            fallbackTranslations = await fetchTranslations('en');
        }

        // Load current language
        if (currentLanguage === 'en') {
            translations = fallbackTranslations;
        } else {
            translations = await fetchTranslations(currentLanguage);
        }

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
            if (value !== undefined) {
                console.warn('[i18n] Missing translation for "' + key + '" in ' + currentLanguage + ', using English');
            }
        }

        // Return key itself as last resort
        if (value === undefined) {
            console.warn('[i18n] Missing translation key: "' + key + '"');
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
        return t('errors.' + code) || t('errors.UNKNOWN');
    }

    /**
     * Supported languages (Story 16.3 - added Spanish)
     */
    var SUPPORTED_LANGUAGES = ['en', 'de', 'es', 'fr'];

    /**
     * Set the current language
     * @param {string} langCode - Language code ('en', 'de', 'es', or 'fr')
     * @returns {Promise<void>}
     */
    async function setLanguage(langCode) {
        // Validate language code (Story 16.3 - added Spanish support)
        if (SUPPORTED_LANGUAGES.indexOf(langCode) === -1) {
            console.warn('[i18n] Invalid language code: ' + langCode + ', defaulting to en');
            langCode = 'en';
        }

        if (langCode === currentLanguage && isLoaded) {
            return;
        }

        currentLanguage = langCode;
        await loadTranslations();
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
    }

    /**
     * Detect browser language and return 'de', 'es', or 'en' (Story 16.3)
     * Supports Spanish variants: es, es-ES, es-MX, es-AR, etc.
     * @returns {string} - Detected language code
     */
    function detectBrowserLanguage() {
        var browserLang = navigator.language || navigator.userLanguage || 'en';
        var langLower = browserLang.toLowerCase();
        // Check for German (de, de-DE, de-AT, etc.)
        if (langLower.startsWith('de')) {
            return 'de';
        }
        // Check for Spanish (es, es-ES, es-MX, es-AR, es-CO, etc.)
        if (langLower.startsWith('es')) {
            return 'es';
        }
        // Check for French (fr, fr-FR, fr-CA, fr-BE, fr-CH, etc.)
        if (langLower.startsWith('fr')) {
            return 'fr';
        }
        // Default to English
        return 'en';
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

    // Public API
    return {
        t: t,
        getErrorMessage: getErrorMessage,
        setLanguage: setLanguage,
        getLanguage: getLanguage,
        initPageTranslations: initPageTranslations,
        detectBrowserLanguage: detectBrowserLanguage,
        init: init,
        isReady: isReady
    };
})();

// Shorthand for translation function (use window to ensure global availability after minification)
window.t = window.BeatifyI18n.t;
