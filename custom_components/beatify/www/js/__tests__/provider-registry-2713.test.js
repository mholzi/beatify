/**
 * The admin's provider list is the integration's provider list (#2713).
 *
 * Before this issue the list was typed out again in `wizard.js` (the chips),
 * `media-players.js` (six `data-supports-*` attributes, six chip lookups, six
 * "fall back to Spotify" blocks), `playlists.js` and `mix.js` (two copies of
 * the per-playlist count switch), `render-helpers.js` and `playlist-hub.js`.
 * A provider added in Python reached the browser only if somebody remembered
 * every one of them, and a forgotten file was never an error — just a chip
 * that never enabled.
 *
 * `providers.generated.js` is now generated from `providers.py`, and
 * `tests/unit/test_provider_registry_2713.py` fails when it has drifted. This
 * file covers the other half: that the modules actually READ it, so
 * regenerating the mirror is enough to move the whole admin.
 *
 * The vitest env is `node`, so the DOM these tests need is hand-rolled — the
 * same approach as media-players-autorestore.test.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { PROVIDERS, PROVIDERS_BY_ID, PROVIDER_IDS, providersForPlatform } from '../providers.generated.js';
import { providerCountForPlaylist } from '../admin/provider-counts.js';

describe('providers.generated.js', () => {
    it('carries every provider the integration knows', () => {
        // Not a copy of the Python list — a floor. The Python-side drift test
        // is what pins the exact contents; this catches a mirror that was
        // emptied or truncated.
        expect(PROVIDER_IDS).toContain('spotify');
        expect(PROVIDER_IDS).toContain('amazon_music');
        expect(PROVIDER_IDS).toContain('ma_library');
        expect(PROVIDER_IDS).toContain('ytmusic_free');
    });

    it('gives every provider the three spellings the admin needs', () => {
        for (const p of PROVIDERS) {
            expect(p.id, 'id').toBeTruthy();
            expect(p.label, `label for ${p.id}`).toBeTruthy();
            expect(p.supportsKey, `supportsKey for ${p.id}`).toBe(`supports_${p.id}`);
            expect(Array.isArray(p.platforms), `platforms for ${p.id}`).toBe(true);
            expect(p.platforms.length, `platforms for ${p.id}`).toBeGreaterThan(0);
        }
    });

    it('folds the alexa alias when asked which providers a platform serves', () => {
        const media = providersForPlatform('alexa_media').map((p) => p.id);
        const alias = providersForPlatform('alexa').map((p) => p.id);
        expect(alias).toEqual(media);
        expect(media).toContain('amazon_music');
        expect(media).not.toContain('tidal');
    });
});

describe('providerCountForPlaylist reads the registry (#1590, #2713)', () => {
    const playlist = {
        song_count: 30,
        spotify_count: 25,
        apple_music_count: 20,
        youtube_music_count: 0,
        tidal_count: 5,
        deezer_count: 3,
        amazon_music_count: 30,
    };

    it('matches the hand-written switch it replaced', () => {
        expect(providerCountForPlaylist(playlist, 'spotify')).toBe(25);
        expect(providerCountForPlaylist(playlist, 'apple_music')).toBe(20);
        expect(providerCountForPlaylist(playlist, 'youtube_music')).toBe(0);
        expect(providerCountForPlaylist(playlist, 'tidal')).toBe(5);
        expect(providerCountForPlaylist(playlist, 'deezer')).toBe(3);
        expect(providerCountForPlaylist(playlist, 'amazon_music')).toBe(30);
        // Legacy playlist with no per-provider counts: Spotify falls back.
        expect(providerCountForPlaylist({ song_count: 8 }, 'spotify')).toBe(8);
        // An unknown provider still gets the full song count.
        expect(providerCountForPlaylist(playlist, 'whatever')).toBe(30);
    });

    it('gives a provider that keeps no count the full song count', () => {
        // Crate Digger builds its songs from the host's own library, so a
        // per-playlist coverage number would describe a catalogue it does not
        // play from.
        expect(PROVIDERS_BY_ID.ma_library.countKey).toBeNull();
        expect(providerCountForPlaylist(playlist, 'ma_library')).toBe(30);
    });
});

// ---------------------------------------------------------------------------
// media-players.js renders and reads one attribute per registered provider
// ---------------------------------------------------------------------------

function makeChip() {
    return {
        disabled: false,
        classes: new Set(),
        classList: {
            add(c) { this.owner.classes.add(c); },
            remove(c) { this.owner.classes.delete(c); },
            toggle(c, on) { on ? this.owner.classes.add(c) : this.owner.classes.delete(c); },
            contains(c) { return this.owner.classes.has(c); },
        },
    };
}

function chipFactory(ids) {
    const chips = {};
    for (const id of ids) {
        const chip = makeChip();
        chip.classList.owner = chip;
        chips[id] = chip;
    }
    return chips;
}

describe('media-players.js derives its chips from the registry', () => {
    let chips;

    beforeEach(() => {
        vi.resetModules();
        globalThis.window = globalThis;
        globalThis.CSS = { escape: (s) => String(s) };
        globalThis.BeatifyUtils = { escapeHtml: (v) => String(v ?? '') };
        chips = chipFactory(PROVIDER_IDS);
        globalThis.document = {
            getElementById: () => null,
            querySelector: (sel) => {
                const m = /\.chip\[data-provider="([^"]+)"\]/.exec(sel);
                return m ? (chips[m[1]] || null) : null;
            },
            querySelectorAll: () => [],
        };
    });

    it('renders a data-supports-* attribute for every provider', async () => {
        const { renderPlayerItem } = await import('../admin/sections/media-players.js');
        const player = { entity_id: 'media_player.x', platform: 'sonos', state: 'idle', friendly_name: 'X' };
        for (const p of PROVIDERS) player[p.supportsKey] = p.platforms.includes('sonos');

        const html = renderPlayerItem(player);
        for (const p of PROVIDERS) {
            const attr = `data-supports-${p.id.replace(/_/g, '-')}`;
            expect(html, `${attr} missing`).toContain(`${attr}="`);
        }
        // ...and the values follow the registry, not a hard-coded list.
        expect(html).toContain('data-supports-spotify="true"');
        expect(html).toContain('data-supports-tidal="false"');
        expect(html).toContain('data-supports-ma-library="false"');
    });

    it.each(['music_assistant', 'sonos', 'alexa_media'])(
        'dims the chip of every provider a %s speaker cannot serve',
        async (platform) => {
            const mod = await import('../admin/sections/media-players.js');
            const supports = {};
            for (const p of PROVIDERS) supports[p.id] = p.platforms.includes(platform);

            mod.updateProviderOptions({ supports });

            for (const p of PROVIDERS) {
                const expected = !supports[p.id];
                expect(chips[p.id].disabled, `${p.id} disabled`).toBe(expected);
                expect(chips[p.id].classes.has('chip--disabled'), `${p.id} class`).toBe(expected);
            }
        },
    );

    it('dims Crate Digger on a Sonos, which the hand-written blocks never did', async () => {
        // admin.html has shipped a `data-provider="ma_library"` chip since
        // #1590 and none of the six `const xBtn = …` lookups it replaced knew
        // about it, so on a Sonos it stayed bright and clickable.
        const mod = await import('../admin/sections/media-players.js');
        const supports = {};
        for (const p of PROVIDERS) supports[p.id] = p.platforms.includes('sonos');

        mod.updateProviderOptions({ supports });

        expect(chips.ma_library.disabled).toBe(true);
        expect(chips.spotify.disabled).toBe(false);
    });

    it('reads every attribute back off the selected radio', async () => {
        const mod = await import('../admin/sections/media-players.js');
        const { adminState } = await import('../admin/state.js');

        const dataset = { entityId: 'media_player.echo', state: 'idle', platform: 'alexa_media' };
        // Exactly what renderPlayerItem writes, as the browser would expose it.
        dataset.supportsSpotify = 'true';
        dataset.supportsAppleMusic = 'true';
        dataset.supportsAmazonMusic = 'true';
        dataset.supportsYoutubeMusic = 'false';
        dataset.supportsTidal = 'false';
        dataset.supportsDeezer = 'false';
        dataset.supportsMaLibrary = 'false';
        dataset.supportsYtmusicFree = 'false';

        const item = {
            classList: { add() {}, remove() {}, toggle() {} },
            querySelector: () => null,
        };
        mod.handleMediaPlayerSelect({ dataset, closest: () => item }, true);

        // This is the chip that could not enable before #2713:
        // supports_amazon_music was read here but never sent by the backend.
        expect(adminState.selectedMediaPlayer.supports.amazon_music).toBe(true);
        expect(adminState.selectedMediaPlayer.supports.tidal).toBe(false);
        expect(Object.keys(adminState.selectedMediaPlayer.supports).sort())
            .toEqual([...PROVIDER_IDS].sort());
    });
});
