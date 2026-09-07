/**
 * The host's pause, and the announcement that goes with it (#2645).
 *
 * Pausing is not a switch, it is a message to the room. The screens invert the
 * usual hierarchy: the *reason* is the headline ("Pizza is here") and the word
 * "Pause" sits small underneath it. Twenty people then know what is happening
 * without the host having to shout over the music.
 *
 * Everything a screen needs to draw that announcement lives here, in one list,
 * because three surfaces draw it — the host's phone, the guest's phone and the
 * TV — and a fourth reason added in only two of them is a reason that renders
 * as a raw code on the third.
 *
 * `dashboard.js` cannot import this: it is a standalone IIFE bundle, not part
 * of the two ESM bundles. It keeps its own copy of the codes, and
 * `__tests__/host-pause-2645.test.js` fails the moment the two lists disagree.
 */

/** What a bare Pause tap sends. The screens then just say "Pause". */
export const HOST_PAUSE_GENERIC = 'host_pause';

/**
 * The named announcements, in the order the host reads them.
 *
 * All three have the *same* consequence sentence on purpose — that sentence is
 * what separates them from Stop, and repeating it under each tile is cheaper
 * than making the host remember which of the four behaves differently.
 */
export const HOST_PAUSE_TILES = [
    { code: 'host_pause_food', emoji: '🍕', titleKey: 'game.pauseReasonFood' },
    { code: 'host_pause_door', emoji: '🚪', titleKey: 'game.pauseReasonDoor' },
    { code: 'host_pause_away', emoji: '⏸️', titleKey: 'game.pauseReasonAway' },
];

/** Every reason an admin socket may set — mirrors const.py HOST_PAUSE_REASONS. */
export const HOST_PAUSE_CODES = [HOST_PAUSE_GENERIC].concat(
    HOST_PAUSE_TILES.map(function(tile) { return tile.code; })
);

/**
 * Did the host set this pause, or did the server?
 *
 * The difference decides whether a screen may re-write the pause at all: a
 * speaker that stopped answering must never end up announced as "Pizza is
 * here", because the room would then wait for a host who is waiting for a
 * speaker. The server enforces the same rule; this is the client half.
 *
 * @param {string} [reason] - `pause_reason` from the state payload
 * @returns {boolean}
 */
export function isHostPause(reason) {
    return HOST_PAUSE_CODES.indexOf(reason) !== -1;
}

/**
 * The announcement for a host pause: what the screens put in poster size.
 *
 * @param {string} [reason] - `pause_reason` from the state payload
 * @param {function(string): string} t - translator (returns the key on a miss)
 * @returns {{emoji: string, headline: string, named: boolean}|null}
 *   `null` for a pause the server owns — those keep their existing rendering.
 */
export function hostPauseAnnouncement(reason, t) {
    if (!isHostPause(reason)) return null;
    for (var i = 0; i < HOST_PAUSE_TILES.length; i++) {
        if (HOST_PAUSE_TILES[i].code === reason) {
            return {
                emoji: HOST_PAUSE_TILES[i].emoji,
                headline: t(HOST_PAUSE_TILES[i].titleKey),
                named: true,
            };
        }
    }
    // Paused without picking a tile. The host who opened the door has still
    // paused; the room is simply told that much and no more.
    return { emoji: '⏸️', headline: t('game.paused'), named: false };
}
