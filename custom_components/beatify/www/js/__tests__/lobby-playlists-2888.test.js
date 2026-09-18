/**
 * #2888 — the wizard's "Go to lobby" must carry the playlist selection.
 *
 * The update-lobby push patched the speaker, TTS, lights and the game options,
 * but not the playlists, so a host who changed playlists in the wizard got a
 * lobby playing the old pool while the home card showed the new selection.
 * These are the paths that push now sends.
 */
import { describe, it, expect } from 'vitest';

import { lobbyPlaylistPaths } from '../admin/util.js';

describe('lobbyPlaylistPaths', () => {
    it('sends the paths of the stored { path } entries the wizard writes', () => {
        const settings = {
            selectedPlaylists: [{ path: '80er-hits.json' }, { path: 'summer-party-anthems.json', songCount: 112 }],
        };
        expect(lobbyPlaylistPaths(settings)).toEqual(['80er-hits.json', 'summer-party-anthems.json']);
    });

    it('accepts bare path strings too', () => {
        expect(lobbyPlaylistPaths({ selectedPlaylists: ['80er-hits.json'] })).toEqual(['80er-hits.json']);
    });

    it('drops malformed entries instead of sending them', () => {
        expect(lobbyPlaylistPaths({ selectedPlaylists: [null, {}, '', { path: 'a.json' }] })).toEqual(['a.json']);
    });

    it('sends nothing when there is no selection, so the lobby keeps its songs', () => {
        expect(lobbyPlaylistPaths({ selectedPlaylists: [] })).toBeNull();
        expect(lobbyPlaylistPaths({ provider: 'ma_library' })).toBeNull();
        expect(lobbyPlaylistPaths(null)).toBeNull();
    });
});
