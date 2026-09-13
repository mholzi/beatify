/**
 * #2820 — duplicate rows in the TV leaderboard.
 *
 * `_reconcileRows` keeps a row's DOM node while its HTML is unchanged and builds
 * a new one when it changed. The new node was pushed into the desired list, but
 * the old one with the same `data-row-key` was never taken out: the cleanup pass
 * only removes keys that are no longer wanted at all. Every score change left
 * one more copy of the row on the waiting and reveal screens. Reported and
 * diagnosed by @slangreck.
 *
 * The function is cut out of the shipped dashboard.js and run against a small
 * DOM with real sibling links, so the test sees the child list the TV sees.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

/** A parent/child DOM just deep enough for the reconciler. */
function node(tag = 'div') {
    const n = {
        tagName: tag.toUpperCase(),
        attrs: {},
        childNodes: [],
        parentNode: null,
        setAttribute(k, v) { n.attrs[k] = String(v); },
        getAttribute(k) { return k in n.attrs ? n.attrs[k] : null; },
        get children() { return n.childNodes; },
        get firstElementChild() { return n.childNodes[0] || null; },
        get nextElementSibling() {
            if (!n.parentNode) return null;
            const sib = n.parentNode.childNodes;
            return sib[sib.indexOf(n) + 1] || null;
        },
        removeChild(c) {
            const i = n.childNodes.indexOf(c);
            if (i === -1) throw new Error('removeChild: not a child');
            n.childNodes.splice(i, 1);
            c.parentNode = null;
            return c;
        },
        insertBefore(c, ref) {
            if (c.parentNode) c.parentNode.removeChild(c);
            const i = ref ? n.childNodes.indexOf(ref) : -1;
            if (i === -1) n.childNodes.push(c);
            else n.childNodes.splice(i, 0, c);
            c.parentNode = n;
            return c;
        },
        replaceChild(fresh, old) {
            const i = n.childNodes.indexOf(old);
            if (i === -1) throw new Error('replaceChild: not a child');
            if (fresh.parentNode) fresh.parentNode.removeChild(fresh);
            n.childNodes[i] = fresh;
            fresh.parentNode = n;
            old.parentNode = null;
            return old;
        },
        // `innerHTML` on the scratch div: one element per assignment, which
        // is all the reconciler ever parses.
        set innerHTML(html) {
            n.childNodes = [];
            const child = node();
            child.html = html;
            child.parentNode = n;
            n.childNodes.push(child);
        },
    };
    return n;
}

const reconcile = evaluate(
    [declaration(readSource('dashboard.js'), '_reconcileRows')],
    '_reconcileRows',
    { document: { createElement: (tag) => node(tag) } },
);

const keys = (c) => c.childNodes.map((x) => x.getAttribute('data-row-key'));
const row = (name, score) => ({ key: name, html: `<div class="leaderboard-entry">${name} ${score}</div>` });

describe('#2820 _reconcileRows', () => {
    it('keeps one node per key when a row changes', () => {
        const c = node();
        const names = ['Anna', 'Ben', 'Clara', 'David', 'Emma', 'Felix', 'Greta', 'Hannes'];
        reconcile(c, names.map((n, i) => row(n, 50 - i)));
        expect(keys(c)).toEqual(names);

        // Clara scores and climbs to the top; Felix changes in place.
        const second = [row('Clara', 60), row('Anna', 50), row('Ben', 45), row('Felix', 42),
            row('David', 35), row('Emma', 30), row('Greta', 20), row('Hannes', 15)];
        reconcile(c, second);
        expect(c.childNodes).toHaveLength(8);
        expect(new Set(keys(c)).size).toBe(8);
        expect(keys(c)).toEqual(second.map((r) => r.key));
        // The node for a changed row carries the new html, not the stale one.
        expect(c.childNodes[0].html).toBe(second[0].html);
    });

    it('stays at one node per key over repeated changed renders', () => {
        const c = node();
        for (let s = 0; s < 5; s++) {
            reconcile(c, [row('Anna', s), row('Ben', 10 - s)]);
        }
        expect(keys(c).sort()).toEqual(['Anna', 'Ben']);
    });

    it('reuses the node for an unchanged row', () => {
        const c = node();
        reconcile(c, [row('Anna', 1), row('Ben', 2)]);
        const ben = c.childNodes[1];
        reconcile(c, [row('Anna', 9), row('Ben', 2)]);
        expect(c.childNodes[1]).toBe(ben);
    });
});
