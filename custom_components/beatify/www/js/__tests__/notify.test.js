/**
 * #1663 item 1 — non-blocking notifications (notify.js).
 *
 * Covers the two surfaces that replace blocking alert():
 *   - showToast(): appended to a top-center live-region container, auto-dismisses
 *     after its duration, and carries a glowing progress bar + close button.
 *   - showBanner(): docked directly ABOVE a primary-action anchor, role="alert"
 *     (in the screen-reader flow), replaces (not stacks) a same-id banner.
 *
 * vitest runs in the node env, so we stand up a tiny DOM stub — the same
 * approach the other __tests__ use (no jsdom dependency).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// --- Minimal DOM ---------------------------------------------------------
function makeNode(tag) {
    var node = {
        tagName: (tag || 'div').toUpperCase(),
        children: [],
        parentNode: null,
        _attrs: {},
        style: {},
        textContent: '',
        _listeners: {},
        classList: {
            _set: new Set(),
            add() { for (var i = 0; i < arguments.length; i++) this._set.add(arguments[i]); },
            remove() { for (var i = 0; i < arguments.length; i++) this._set.delete(arguments[i]); },
            contains(c) { return this._set.has(c); },
        },
        get className() { return Array.from(this.classList._set).join(' '); },
        set className(v) {
            this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean));
        },
        setAttribute(k, v) { this._attrs[k] = String(v); if (k === 'id') this.id = String(v); },
        getAttribute(k) { return this._attrs[k]; },
        appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
        insertBefore(child, ref) {
            child.parentNode = this;
            var idx = this.children.indexOf(ref);
            if (idx === -1) this.children.push(child);
            else this.children.splice(idx, 0, child);
            return child;
        },
        removeChild(child) {
            var idx = this.children.indexOf(child);
            if (idx !== -1) this.children.splice(idx, 1);
            child.parentNode = null;
            return child;
        },
        addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); },
        _fire(type) { (this._listeners[type] || []).forEach((fn) => fn({})); },
        querySelector() { return null; },
    };
    return node;
}

let body, registry;
function installDom() {
    registry = {};
    body = makeNode('body');
    global.window = { BeatifyI18n: { t: (k) => k } };
    global.document = {
        body,
        createElement: (tag) => makeNode(tag),
        getElementById: (id) => registry[id] || findById(body, id),
    };
    global.requestAnimationFrame = (fn) => fn();
}
function findById(node, id) {
    if (node.id === id) return node;
    for (var i = 0; i < node.children.length; i++) {
        var hit = findById(node.children[i], id);
        if (hit) return hit;
    }
    return null;
}

const { showToast, showBanner, clearBanner } = await import('../notify.js');

describe('#1663 item 1 — showToast', () => {
    beforeEach(() => { installDom(); vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    it('appends a toast into a top-center live-region container', () => {
        const toast = showToast('Rematch failed');
        expect(toast).toBeTruthy();
        const container = findById(body, 'beatify-toast-container');
        expect(container).toBeTruthy();
        expect(container.getAttribute('aria-live')).toBe('polite');
        expect(container.children).toContain(toast);
        expect(toast.classList.contains('beatify-toast--error')).toBe(true);
    });

    it('renders a draining progress bar for the auto-dismiss window', () => {
        const toast = showToast('x', { duration: 4000 });
        const bar = toast.children.find((c) => c.classList.contains('beatify-toast-progress'));
        expect(bar).toBeTruthy();
        expect(bar.style.animationDuration).toBe('4000ms');
    });

    it('auto-dismisses after its duration', () => {
        const toast = showToast('bye', { duration: 4000 });
        const container = findById(body, 'beatify-toast-container');
        expect(container.children).toContain(toast);
        vi.advanceTimersByTime(4000); // dismiss timer fires
        vi.advanceTimersByTime(300);  // leave transition removes the node
        expect(container.children).not.toContain(toast);
    });

    it('a sticky toast (duration 0) has no progress bar and does not auto-dismiss', () => {
        const toast = showToast('stay', { duration: 0 });
        expect(toast.children.find((c) => c.classList.contains('beatify-toast-progress'))).toBeFalsy();
        const container = findById(body, 'beatify-toast-container');
        vi.advanceTimersByTime(100000);
        expect(container.children).toContain(toast);
    });

    it('close button dismisses on demand', () => {
        const toast = showToast('closable', { duration: 0 });
        const container = findById(body, 'beatify-toast-container');
        const closeBtn = toast.children.find((c) => c.classList.contains('beatify-toast-close'));
        closeBtn._fire('click');
        vi.advanceTimersByTime(300);
        expect(container.children).not.toContain(toast);
    });
});

describe('#1663 item 1 — showBanner', () => {
    beforeEach(() => { installDom(); });

    it('docks the banner directly above the anchor with role="alert"', () => {
        const parent = makeNode('div');
        const anchor = makeNode('button');
        anchor.setAttribute('id', 'home-start-game');
        parent.appendChild(anchor);
        body.appendChild(parent);

        const banner = showBanner('Speaker does not support Apple Music', {
            anchor, title: 'Cannot start', id: 'home-start-banner',
        });
        expect(banner).toBeTruthy();
        expect(banner.getAttribute('role')).toBe('alert');
        // Inserted BEFORE the anchor (docked above the primary action).
        expect(parent.children.indexOf(banner)).toBeLessThan(parent.children.indexOf(anchor));
        // Title line present.
        const title = banner.children.find((c) => c.classList && c.classList.contains('beatify-banner-content'));
        expect(title).toBeTruthy();
    });

    it('replaces a same-id banner instead of stacking duplicates', () => {
        const parent = makeNode('div');
        const anchor = makeNode('button');
        anchor.setAttribute('id', 'home-start-game');
        parent.appendChild(anchor);
        body.appendChild(parent);

        showBanner('first', { anchor, id: 'home-start-banner' });
        showBanner('second', { anchor, id: 'home-start-banner' });
        const banners = parent.children.filter((c) => c.id === 'home-start-banner');
        expect(banners.length).toBe(1);
    });

    it('clearBanner removes the banner', () => {
        const parent = makeNode('div');
        const anchor = makeNode('button');
        anchor.setAttribute('id', 'home-start-game');
        parent.appendChild(anchor);
        body.appendChild(parent);
        showBanner('gone soon', { anchor, id: 'home-start-banner' });
        clearBanner('home-start-banner');
        expect(parent.children.some((c) => c.id === 'home-start-banner')).toBe(false);
    });
});
