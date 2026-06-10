/**
 * Beatify Admin — shared constants (#1279 Schritt 4b/6).
 *
 * Extracted so the setup-section modules (playlists.js, media-players.js,
 * game-settings.js) and the admin.js core can all import the SAME literal
 * values instead of duplicating them. Previously these lived as top-level
 * `const`s inside admin.js; once the setup sections became their own ES
 * modules they needed a shared, side-effect-free home.
 *
 * Pure data only — no DOM, no state, no functions. Safe to import at module
 * init from anywhere.
 */

// localStorage keys (shared by admin.js core, media-players.js, playlists.js,
// game-settings.js).
export const STORAGE_LAST_PLAYER = 'beatify_last_player';
export const STORAGE_GAME_SETTINGS = 'beatify_game_settings';

// Media-player platform → display label/icon (media-players.js renderPlayerItem).
export const PLATFORM_LABELS = {
    music_assistant: { icon: '🎵', label: 'Music Assistant', recommended: true },
    sonos: { icon: '🔊', label: 'Sonos' },
    alexa_media: { icon: '📢', label: 'Alexa' },
    alexa: { icon: '📢', label: 'Alexa' },
};

// Playlist tag-filter categories (playlists.js renderPlaylistFilterBar, Issue #70).
export const TAG_CATEGORIES = {
    decade: {
        label: 'Decade',
        tags: ['1960s', '1970s', '1980s', '1990s', '2000s']
    },
    style: {
        label: 'Style',
        tags: ['rock', 'pop', 'ballads', 'electronic', 'eurodance', 'yacht-rock', 'soft-rock', 'pop-punk', 'schlager', 'party', 'britpop', 'british-invasion', 'classic-rock', 'dance', 'disco', 'funk', 'hip-hop', 'latin', 'merengue', 'motown', 'r&b', 'salsa', 'soul']
    },
    region: {
        label: 'Region',
        tags: ['international', 'german', 'dutch', 'spanish']
    },
    special: {
        label: 'Special',
        tags: ['movies', 'soundtrack', 'eurovision', 'carnival', 'classics', 'contest', 'mixed', 'one-hit', 'top-hits']
    }
};
