/**
 * #3056: the admin language chip has to tell the server, not only the admin
 * page — the TV and the TTS announcements read the lobby's language from the
 * server. The chip hands `{ language }` to saveGameSettings, which posts it to
 * update-lobby next to the other lobby-mutable settings.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const src = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '..', 'admin', 'sections', 'game-settings.js'),
    'utf8');

describe('language chip -> update-lobby (#3056)', () => {
    it('the chip handler passes the chosen language to saveGameSettings', () => {
        const start = src.indexOf("querySelectorAll('.chip[data-lang]')");
        const handler = src.slice(start, src.indexOf('// Timer chips', start));
        expect(handler).toContain('saveGameSettings({ language: lang })');
    });

    it('saveGameSettings merges the patch into the update-lobby body', () => {
        const start = src.indexOf('export function saveGameSettings(');
        const fn = src.slice(start, src.indexOf("localStorage", start));
        expect(fn).toContain('lobbyPatch');
        expect(fn).toContain('...lobbyPatch');
        expect(fn).toContain('/beatify/api/game/update-lobby');
    });
});
