/**
 * #2504 — the join corner.
 *
 * The server admits latecomers throughout LOBBY, PLAYING and REVEAL
 * (`can_join` in server/serializers.py), but the QR code left the TV the moment
 * round one started: `renderQRCode` was only ever called from
 * `renderLobbyView`. The host's own phone held the only remaining way in.
 *
 * What is asserted here is the *rule*, not the markup. The issue asked for a
 * deterministic hide condition rather than a judgement call, because a
 * mid-party setting is a setting nobody makes:
 *
 *   - Sudden Death armed  -> hidden (whoever joins is out in the next round)
 *   - fewer than 3 songs  -> hidden (an inherited average cannot carry a game)
 *
 * Both values already ride along in every state broadcast, so the check is
 * client-side and needs no new server field.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, readSource, WWW_DIR } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');

/** Build the corner's DOM and run the real renderJoinCorner against it. */
function run(data) {
  const corner = el('dashboard-join-corner');
  // The markup ships hidden; the renderer is what turns it on.
  corner.classList.add('hidden');
  corner.setAttribute('aria-hidden', 'true');
  const qr = el('join-corner-qr');
  const url = el('join-corner-url');
  const document = doc({
    'dashboard-join-corner': corner,
    'join-corner-qr': qr,
    'join-corner-url': url,
  });

  const rendered = [];
  const fn = evaluate(declaration(DASHBOARD, 'renderJoinCorner'), 'renderJoinCorner', {
    document,
    // renderQRCode is exercised by the lobby already; here we only care that
    // the corner asks for a code at all, and at the smaller size.
    renderQRCode: (u, id, size) => rendered.push({ u, id, size }),
  });

  fn(data);
  return { corner, url, rendered };
}

const OPEN = {
  join_url: 'http://192.168.0.69:8123/beatify/play?game=abc',
  songs_remaining: 7,
  sudden_death_mode: false,
};

describe('#2504 join corner — when it shows', () => {
  it('is visible during a normal round', () => {
    const { corner, rendered } = run(OPEN);
    expect(corner.classList.contains('hidden')).toBe(false);
    expect(corner.getAttribute('aria-hidden')).toBe('false');
    expect(rendered).toHaveLength(1);
    expect(rendered[0].id).toBe('join-corner-qr');
  });

  it('asks for a smaller code than the lobby uses', () => {
    const { rendered } = run(OPEN);
    // The lobby draws 200px; the corner has to sit clear of artwork and timer.
    expect(rendered[0].size).toBeLessThan(200);
  });

  it('shortens the address, because the full one does not fit beside 96px', () => {
    const { url } = run(OPEN);
    expect(url.textContent).toBe('…/beatify/play?game=abc');
  });
});

describe('#2504 join corner — the deterministic hide rule', () => {
  it('hides once Sudden Death is armed', () => {
    const { corner, rendered } = run({ ...OPEN, sudden_death_mode: true });
    expect(corner.classList.contains('hidden')).toBe(true);
    expect(corner.getAttribute('aria-hidden')).toBe('true');
    // Nothing is drawn into a hidden panel.
    expect(rendered).toHaveLength(0);
  });

  it('hides under three songs remaining', () => {
    expect(run({ ...OPEN, songs_remaining: 2 }).corner.classList.contains('hidden')).toBe(true);
  });

  it('still shows at exactly three songs — the boundary belongs to the guest', () => {
    expect(run({ ...OPEN, songs_remaining: 3 }).corner.classList.contains('hidden')).toBe(false);
  });

  it('shows when the count is missing rather than guessing it is late', () => {
    const { corner } = run({ ...OPEN, songs_remaining: undefined });
    expect(corner.classList.contains('hidden')).toBe(false);
  });

  it('hides when there is no join URL at all', () => {
    expect(run({ ...OPEN, join_url: null }).corner.classList.contains('hidden')).toBe(true);
  });
});

describe('#2504 join corner — leaving the two phases', () => {
  it('showView hides the corner for every view except playing and reveal', () => {
    const src = declaration(DASHBOARD, 'showView');
    expect(src).toContain('dashboard-playing');
    expect(src).toContain('dashboard-reveal');
    expect(src).toContain('hideJoinCorner');
  });
});

describe('#2504 join corner — the stylesheet', () => {
  it('pins the panel to a corner so it cannot land on the artwork', () => {
    expect(CSS).toMatch(/\.join-corner\s*\{[^}]*position:\s*fixed/);
  });

  it('steps aside on a small screen instead of shrinking into illegibility', () => {
    expect(CSS).toMatch(/@media[^{]*max-width:\s*720px[^{]*\{[^}]*\.join-corner\s*\{\s*display:\s*none/s);
  });
});
