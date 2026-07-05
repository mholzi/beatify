/**
 * #1764 — the player page regenerated the join QR on EVERY state broadcast.
 *
 * player-core:660 calls renderQRCode(data.join_url) for every state frame in
 * every phase, outside the #1706/#1707 coalescers. The old renderQRCode wiped
 * container.innerHTML and ran `new QRCode(...)` — a full Reed-Solomon encode +
 * DOM rebuild — per broadcast. A 20-player submission burst = 20 QR
 * regenerations per phone per round for a URL that never changes.
 *
 * The fix short-circuits when `joinUrl === currentJoinUrl && container.firstChild`.
 * These tests import the REAL renderQRCode and count how often the QRCode
 * constructor (the expensive encode) actually runs.
 *
 * The vitest env is `node` (no jsdom), so a minimal fake `document`/`window` and
 * a counting `QRCode` stub model just what renderQRCode touches.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// player-utils.js reads window.location + window.BeatifyUtils and calls
// document.getElementById at import time, so both globals must exist first.
globalThis.window = globalThis;
globalThis.window.BeatifyUtils = { t: (k) => k, escapeHtml: (s) => s };
globalThis.window.location = { search: '' };
// player-utils.js's AnimationUtils probes prefers-reduced-motion at import time.
globalThis.window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });

/** Minimal fake element modelling the QR container. */
function makeContainer() {
    let html = '';
    const children = [];
    return {
        _children: children,
        set innerHTML(v) {
            html = v;
            // Clearing removes children; any non-empty assignment is treated as
            // one child node (matches the vendor lib appending a <canvas>/<img>).
            children.length = 0;
            if (v) children.push({ tag: 'p' });
        },
        get innerHTML() { return html; },
        get firstChild() { return children[0] || null; },
        appendChild(node) { children.push(node); },
        onclick: null,
        onkeydown: null,
    };
}

let container;
let qrEncodeCount;

globalThis.document = {
    getElementById(id) {
        if (id === 'player-qr-code') return container;
        return null;
    },
};

// Counting QRCode stub: each construction = one Reed-Solomon encode + DOM append.
globalThis.QRCode = class {
    constructor(el) {
        qrEncodeCount += 1;
        if (el && el.appendChild) el.appendChild({ tag: 'canvas' });
    }
};
globalThis.QRCode.CorrectLevel = { M: 0 };

const { renderQRCode } = await import('../player-lobby.js');

beforeEach(() => {
    container = makeContainer();
    qrEncodeCount = 0;
});

describe('#1764 renderQRCode unchanged-url guard', () => {
    it('encodes once, then skips repeated broadcasts of the same join_url', () => {
        const url = 'https://ha.local/beatify/player?game=ABCD';
        renderQRCode(url);
        expect(qrEncodeCount).toBe(1);
        expect(container.firstChild).not.toBeNull();

        // Simulate a 20-player submission burst: 20 more state frames, same URL.
        for (let i = 0; i < 20; i++) renderQRCode(url);
        expect(qrEncodeCount).toBe(1); // still just the first encode
    });

    it('re-encodes when the join_url changes (e.g. new game_id)', () => {
        renderQRCode('https://ha.local/beatify/player?game=AAAA');
        expect(qrEncodeCount).toBe(1);
        renderQRCode('https://ha.local/beatify/player?game=BBBB');
        expect(qrEncodeCount).toBe(2);
    });

    it('re-encodes for the same url when the container was rebuilt (firstChild gone)', () => {
        const url = 'https://ha.local/beatify/player?game=CCCC';
        renderQRCode(url);
        expect(qrEncodeCount).toBe(1);

        // A view re-render wiped the QR container's children.
        container.innerHTML = '';
        renderQRCode(url);
        expect(qrEncodeCount).toBe(2);
    });

    it('ignores empty/missing join_url without touching the encoder', () => {
        renderQRCode('');
        renderQRCode(null);
        renderQRCode(undefined);
        expect(qrEncodeCount).toBe(0);
    });
});
