/**
 * Beatify Admin — reconcile the server-side setup blob with this browser (#1927).
 *
 * #1663 persists the host's picks (speaker + game settings) on the HA server so
 * a new device does not look unconfigured. That seed only ever ran for a
 * *pristine* browser:
 *
 *     const hasLocal = !!localStorage.getItem(STORAGE_LAST_PLAYER)
 *         || !!localStorage.getItem(STORAGE_GAME_SETTINGS);
 *     if (!hasLocal) { ...adopt server values... }
 *
 * A browser that already held ANY Beatify state therefore kept its own speaker
 * forever, and a selection made later on another device stayed invisible to it.
 * In #1927 that shipped audio into the wrong room: the wizard on the phone saved
 * `media_player.esszimmer`, the Mac that started the game still held a months-old
 * pick which `ensureMediaPlayerHydrated()` faithfully twin-healed to
 * `media_player.kuche_2` — a correct heal of the wrong speaker.
 *
 * The rule here is deliberately mechanical: **for the speaker, the server blob
 * wins whenever it has one.** Combined with the write-through in
 * `media-players.js` (every local pick is mirrored to the server right away),
 * there is exactly one source of truth and a local value can only ever be
 * stale. Comparing timestamps was the other candidate and was rejected: the two
 * blobs are stamped by different machines, so "newer" would hinge on two clocks
 * agreeing — a coin flip dressed up as a rule.
 *
 * Game settings keep the seed-only semantics (adopting a whole settings object
 * from another device would silently reshuffle provider/playlists mid-session),
 * but the check is now per key: a browser holding only `beatify_game_settings`
 * no longer loses the saved speaker.
 *
 * Pure + storage-injected so it is testable under the `node` vitest env.
 */

import { STORAGE_LAST_PLAYER, STORAGE_GAME_SETTINGS } from './constants.js';

/**
 * Bring this browser's localStorage in line with the server's setup blob.
 *
 * @param {Object|null|undefined} savedSetup - `status.saved_setup` from /beatify/api/status.
 * @param {Storage} storage - localStorage (injected for testability).
 * @returns {{ playerAdopted: string|null, settingsSeeded: boolean }}
 *   `playerAdopted` is the entity_id taken over from the server (null when the
 *   local value already matched or the server had none); `settingsSeeded` says
 *   whether the settings blob was filled in from the server.
 */
export function reconcileSavedSetup(savedSetup, storage) {
    const result = { playerAdopted: null, settingsSeeded: false };

    if (!savedSetup || typeof savedSetup !== 'object' || !storage) {
        return result;
    }

    try {
        // Speaker: server wins. Self-heal localStorage so every later reader
        // (isConfigured, hydrateFromStorage, ensureMediaPlayerHydrated) sees the
        // same entity without knowing this reconcile happened.
        const serverPlayer = savedSetup.last_player || null;
        if (serverPlayer && storage.getItem(STORAGE_LAST_PLAYER) !== serverPlayer) {
            storage.setItem(STORAGE_LAST_PLAYER, serverPlayer);
            result.playerAdopted = serverPlayer;
        }

        // Settings: seed only, and independent of the speaker key (#1927).
        if (savedSetup.game_settings && !storage.getItem(STORAGE_GAME_SETTINGS)) {
            storage.setItem(
                STORAGE_GAME_SETTINGS,
                JSON.stringify(savedSetup.game_settings)
            );
            result.settingsSeeded = true;
        }
    } catch (e) {
        // Private mode / storage disabled — the server flag still drives
        // setup_complete, exactly as before.
    }

    return result;
}

/**
 * Human-readable label for the speaker a game would start on (#1927).
 *
 * Falls back to the raw entity_id when the player list has not loaded yet (or
 * the saved entity is gone) — showing `media_player.kuche_2` is still far more
 * useful than showing nothing, which is what the home view did before.
 *
 * @param {string|null|undefined} entityId - Resolved speaker entity_id.
 * @param {Array<{entity_id: string, friendly_name?: string}>} mediaPlayers - `adminState.mediaPlayers`.
 * @returns {string} e.g. `🔊 Esszimmer`
 */
export function speakerLabelFor(entityId, mediaPlayers) {
    if (!entityId) {
        return '🔊 no speaker';
    }
    const match = (mediaPlayers || []).find((p) => p && p.entity_id === entityId);
    return `🔊 ${(match && match.friendly_name) || entityId}`;
}
