/**
 * The smallest DOM the frontend tests need (#2701).
 *
 * vitest runs in the `node` environment here and the repo deliberately carries
 * no jsdom, so every suite that needs elements hand-rolls a few — see
 * `player-reveal-view.test.js` and `dashboard-2130-end-stage.test.js`. This is
 * that same hand-rolled DOM, in one place, so a test can assert on what lands
 * on the screen instead of on the source text that puts it there.
 *
 * It is deliberately not a DOM implementation. `innerHTML` is a string, not a
 * parser; `querySelector` is a lookup table you fill in. That is enough for the
 * renderers under test, which build strings and set properties.
 */

/** One element. `children` maps a selector to the element `querySelector` returns. */
export function el(id, { children = {}, closest = null } = {}) {
    const classes = new Set();
    const node = {
        id,
        tagName: 'DIV',
        textContent: '',
        innerHTML: '',
        className: '',
        style: {},
        hidden: false,
        children,
        appended: [],
        scrolledIntoView: null,
        attrs: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, force) => {
                const want = force === undefined ? !classes.has(c) : !!force;
                if (want) classes.add(c);
                else classes.delete(c);
                return want;
            },
        },
        classes,
        setAttribute: (k, v) => { node.attrs[k] = String(v); },
        getAttribute: (k) => (k in node.attrs ? node.attrs[k] : null),
        removeAttribute: (k) => { delete node.attrs[k]; },
        querySelector: (sel) => children[sel] || null,
        appendChild: (child) => { node.appended.push(child); return child; },
        closest: (sel) => (closest && closest.selector === sel ? closest.node : null),
        scrollIntoView: (opts) => { node.scrolledIntoView = opts; },
    };
    return node;
}

/**
 * A document over a fixed `{ id: element }` map.
 *
 * `lookedUp` records every id the code under test asked for — which turns
 * "does the markup carry the hooks the renderer wants?" from a grep over the
 * HTML into a question the renderer itself answers.
 */
export function doc(elements = {}, { createElement } = {}) {
    const lookedUp = [];
    return {
        lookedUp,
        elements,
        getElementById: (id) => {
            lookedUp.push(id);
            return elements[id] || null;
        },
        querySelector: (sel) => elements[sel] || null,
        querySelectorAll: (sel) => (elements[sel] ? [elements[sel]] : []),
        createElement: (tag) => {
            const node = el(null);
            node.tagName = String(tag).toUpperCase();
            node.created = String(tag);
            if (createElement) createElement(node);
            return node;
        },
    };
}

/**
 * A `utils`-shaped translator over a real locale file, with the same lookup and
 * `{placeholder}` interpolation `BeatifyI18n.t` performs — so a test that reads
 * German out of the DOM is reading the shipped German, not a fixture.
 */
export function translator(dict, { escapeHtml = (s) => String(s) } = {}) {
    function lookup(key) {
        return String(key)
            .split('.')
            .reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), dict);
    }
    return {
        escapeHtml,
        t(key, params) {
            const value = lookup(key);
            if (typeof value !== 'string') {
                // `t(key, fallback)` is the two-argument shape several call
                // sites use; `t(key, {…})` is the interpolating one.
                return typeof params === 'string' ? params : key;
            }
            if (!params || typeof params === 'string') return value;
            return Object.keys(params).reduce(
                (s, p) => s.replace(new RegExp(`\\{${p}\\}`, 'g'), params[p]),
                value,
            );
        },
    };
}
