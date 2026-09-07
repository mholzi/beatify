/**
 * How many songs of a playlist one provider can play (#1590, #2713).
 *
 * Its own module rather than a function in playlists.js because the mixer
 * needs the same answer, and importing playlists.js for it drags in that
 * module's `window.BeatifyUtils` lookup. It used to be a second copy of the
 * switch instead, labelled "mirrors playlists.js logic" — which is the shape
 * of the bug #2713 is about, not a mitigation of it.
 *
 * Imports nothing but the generated provider registry, so it is safe to load
 * anywhere, browser or test runner.
 */

import { PROVIDERS_BY_ID } from '../providers.generated.js';

/**
 * @param {object} playlist  a playlist entry from adminState.playlistData
 * @param {string} provider  a provider id, e.g. adminState.selectedProvider
 * @returns {number}
 */
export function providerCountForPlaylist(playlist, provider) {
    const songCount = playlist.song_count || 0;
    // The registry says which providers are counted at all (`countKey`) and
    // which fall back to the raw song count when the count is missing
    // (`countFallback`: legacy playlists that predate `spotify_count`, and
    // Alexa text search, which plays anything). A provider with no count —
    // Crate Digger reads the host's own library — gets the song count, as an
    // unlisted provider always did through the old `default` branch.
    const spec = PROVIDERS_BY_ID[provider];
    if (!spec || !spec.countKey) return songCount;
    return playlist[spec.countKey] || (spec.countFallback ? songCount : 0);
}
