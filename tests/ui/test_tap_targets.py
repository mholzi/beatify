"""Tap-target sizes and spacing on the real HTML and CSS (#3391).

Loads player.html, admin.html, dashboard.html and launcher.html in one headless
Chromium at phone width with the shipped stylesheets and no JavaScript, shows
each view with every hidden part revealed, rebuilds the JS-rendered rows
(leaderboard, language chips, tiles) from the classes the code uses, and
measures every target with ``getBoundingClientRect``:

* every button, link, field and ``[role=button]`` is at least 44 x 44 px,
* two neighbouring targets are at least 8 px apart,
* the year track is wide enough to drag (P1 of the interaction review).

Exceptions are listed below with their reason. An entry that no longer
matches anything fails too, so the list can only shrink.

There is no layout engine in vitest/jsdom, so this needs a real browser. CI
runs it in its own non-blocking job (``tap-targets`` in test.yml); the main
``pytest tests/unit tests/integration`` jobs never collect it. Locally it runs
with the rest of ``pytest`` and skips when Playwright or a Chromium is missing.

Nothing listens on a port: every request is answered by ``page.route`` from
the files on disk.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

# BEATIFY_WWW points the test at another tree, e.g. an export of main, to see
# what a change fixed.
WWW = Path(
    os.environ.get("BEATIFY_WWW")
    or Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"
)

MIN_TARGET = 44
MIN_GAP = 8
# P1: at 375 px the track was 81 px. Full width at 360 px is ~285 px.
MIN_YEAR_TRACK = {360: 240, 375: 260}

PAGES = {
    "player": (
        "player.html",
        [
            "join-view",
            "tour-view",
            "lobby-view",
            "game-view",
            "reveal-view",
            "paused-view",
            "end-view",
            "connection-lost-view",
            "session-takeover-view",
        ],
    ),
    "admin": (
        "admin.html",
        [
            "wizard-root",
            "home-view",
            "admin-playing-section",
            "admin-reveal-section",
            "admin-end-section",
            "end-game-modal",
            "kick-player-modal",
            "sit-out-modal",
            "round-end-modal",
            "new-game-modal",
            "reset-modal",
            "admin-join-modal",
        ],
    ),
    "dashboard": ("dashboard.html", ["__page"]),
    "launcher": ("launcher.html", ["__page"]),
}

# key -> (minimum size it must still keep, reason). The key is the element's
# id, or its first class when it has none.
SIZE_EXEMPT: dict[str, tuple[int, str]] = {
    # The range input is as tall as its 32 px thumb; what matters for dragging
    # is the length of the track, checked in test_year_track_is_wide_enough.
    "year-slider": (32, "range input: 32 px thumb on a full-width track"),
    # Text links in running text may stay small (WCAG 2.2, 2.5.8 inline
    # exception), but not below one line of text.
    "wizard.step1.hintLink": (14, "help link in running text"),
    "admin.starHintLink": (14, "help link in running text"),
    # Interaction review P5: small, but outside this issue's scope. Each one
    # holds at its current size until its own fix lands.
    "home-dashboard-url": (28, "TV link on the admin home, once per evening"),
    "player-dashboard-url": (30, "Cast to TV link in the guest lobby"),
    "new-game-btn": (22, "host-only link on the guest end screen"),
    "paused-admin-link": (18, "host-only link in the pause view"),
    "admin-star-hint-dismiss": (24, "x of a one-time hint"),
    "next-playlist-search-input": (38, "search field on the guest end screen"),
    "wiz-rounds-custom input": (35, "number field in the setup wizard"),
}

# Pairs (sorted keys) allowed closer than MIN_GAP, with the reason.
GAP_EXEMPT: dict[tuple[str, str], str] = {}

INJECT = r"""
(() => {
 const put=(id,html)=>{const e=document.getElementById(id); if(e) e.innerHTML=html;};
 const names=['Anna','Ben','Clara','David'];
 put('join-language-chips', ['English','Deutsch','Español','Français','Italiano','Nederlands']
   .map(l=>`<button type="button" class="join-language-chip">${l}</button>`).join(''));
 put('artist-options', ['Queen','ABBA','Toto']
   .map(n=>`<button type="button" class="artist-option-btn">${n}</button>`).join(''));
 put('movie-options', ['Top Gun','Grease','Dirty Dancing']
   .map(n=>`<button type="button" class="movie-option-btn">${n}</button>`).join(''));
 const lb = names.map((n,i)=>`<div class="leaderboard-entry"><span class="entry-rank">#${i+1}</span>`
   + `<span class="entry-name">${n}</span><span class="entry-meta"></span><span class="entry-score">${40-i*5}</span>`
   + `<button type="button" class="entry-host-action" data-action="sit-out" aria-label="Sit ${n} out">⋮</button></div>`).join('');
 put('admin-playing-leaderboard-list', lb);
 put('admin-reveal-leaderboard', lb);
})();
"""

MEASURE = r"""
(target) => {
 const all = ['loading-view','starting-view','not-found-view','ended-view','in-progress-view','join-view',
   'tour-view','ready-view','lobby-view','game-view','reveal-view','paused-view','end-view',
   'connection-lost-view','session-takeover-view','wizard-root','home-view','admin-playing-section',
   'admin-reveal-section','admin-end-section','admin-control-bar','admin-join-modal','round-settings-sheet',
   'round-end-modal','end-game-modal','rematch-modal','new-game-modal','start-anyway-modal','sit-out-modal',
   'kick-player-modal','reset-modal','qr-modal','request-modal','request-success-modal','pwa-ios-hint'];
 let roots = target === '__page' ? [document.body] : [document.getElementById(target)];
 if (target === 'admin-playing-section') roots.push(document.getElementById('admin-control-bar'));
 roots = roots.filter(Boolean);
 if (target !== '__page') all.forEach(id => {
   const e = document.getElementById(id);
   if (e && !roots.includes(e)) e.style.setProperty('display', 'none', 'important');
 });
 roots.forEach(r => {
   let a = r;
   while (a) {
     if (a.classList) a.classList.remove('hidden');
     if (a.removeAttribute) { a.removeAttribute('hidden'); a.removeAttribute('aria-hidden'); }
     a = a.parentElement;
   }
   r.querySelectorAll('.hidden,[hidden]').forEach(e => { e.classList.remove('hidden'); e.removeAttribute('hidden'); });
   r.querySelectorAll('.collapsed').forEach(e => e.classList.remove('collapsed'));
 });
 const sel = 'button,a[href],input:not([type=hidden]),select,textarea,[role=button],summary';
 const out = []; const seen = new Set();
 roots.forEach(r => r.querySelectorAll(sel).forEach(el => {
   if (seen.has(el)) return; seen.add(el);
   const cs = getComputedStyle(el); const b = el.getBoundingClientRect();
   if (b.width < 1 || b.height < 1 || cs.visibility === 'hidden' || cs.display === 'none'
       || parseFloat(cs.opacity) === 0 || cs.pointerEvents === 'none') return;
   // A checkbox/radio inside its <label> is hit through the label: measure that.
   let box = b;
   const lab = (el.type === 'checkbox' || el.type === 'radio') ? el.closest('label') : null;
   if (lab) box = lab.getBoundingClientRect();
   const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/)[0] || '';
   // Name: id, else first class, else its i18n key, else "<parent id> <tag>".
   const owner = el.parentElement ? el.parentElement.closest('[id]') : null;
   const key = el.id || cls || el.getAttribute('data-i18n')
     || ((owner ? owner.id + ' ' : '') + el.tagName.toLowerCase());
   out.push({ key: key,
     text: (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || '').trim().replace(/\s+/g, ' ').slice(0, 30),
     x: box.left, y: box.top + scrollY, w: box.width, h: box.height });
 }));
 for (let i = 0; i < out.length; i++) {
   let best = 1e9, who = '';
   for (let j = 0; j < out.length; j++) {
     if (i === j) continue; const a = out[i], c = out[j];
     const dx = Math.max(0, Math.max(a.x, c.x) - Math.min(a.x + a.w, c.x + c.w));
     const dy = Math.max(0, Math.max(a.y, c.y) - Math.min(a.y + a.h, c.y + c.h));
     // Overlapping boxes (one target inside another, or two states of the same
     // control shown at once by the reveal-everything step) are not neighbours.
     if (dx === 0 && dy === 0) continue;
     const d = Math.hypot(dx, dy); if (d < best) { best = d; who = c.key; }
   }
   out[i].gap = best; out[i].nb = who;
 }
 const track = document.querySelector('#year-slider');
 return { els: out, yearTrack: track ? track.getBoundingClientRect().width : null };
}
"""

_INLINE_SCRIPT = re.compile(rb"<script(?![^>]*src)[^>]*>.*?</script>", re.S)


def _route(route):
    url = route.request.url
    m = re.match(r"https?://beatify\.test(/[^?#]*)", url)
    if not m:
        return route.abort()
    path = m.group(1)
    if path.endswith(".js"):
        return route.fulfill(status=200, body="", content_type="application/javascript")
    rel = (
        path[len("/beatify/static/") :]
        if path.startswith("/beatify/static/")
        else path.lstrip("/")
    )
    f = WWW / rel
    if not f.is_file():
        return route.fulfill(status=404, body="")
    body = f.read_bytes()
    if f.suffix == ".html":
        body = _INLINE_SCRIPT.sub(b"", body)
        ctype = "text/html"
    elif f.suffix == ".css":
        ctype = "text/css"
    else:
        ctype = "application/octet-stream"
    return route.fulfill(status=200, body=body, content_type=ctype)


@pytest.fixture(scope="module")
def browser():
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as err:  # noqa: BLE001  # pragma: no cover - environment dependent
        pytest.skip(f"Playwright unavailable: {err}")
    b = None
    for kwargs in ({}, {"channel": "chrome"}):
        try:
            b = pw.chromium.launch(headless=True, **kwargs)
            break
        except Exception:  # noqa: BLE001, S112 - try the next launcher
            continue
    if b is None:  # pragma: no cover - environment dependent
        pw.stop()
        pytest.skip("No Chromium for Playwright (run: playwright install chromium)")
    yield b
    b.close()
    pw.stop()


def _measure(browser, filename, view, width=375):
    ctx = browser.new_context(
        viewport={"width": width, "height": 812},
        device_scale_factor=2,
        has_touch=True,
        is_mobile=True,
    )
    try:
        page = ctx.new_page()
        page.route("**/*", _route)
        page.goto(f"http://beatify.test/{filename}", wait_until="load")
        page.add_style_tag(
            content="*,*::before,*::after{animation:none!important;transition:none!important}"
        )
        page.evaluate(INJECT)
        return page.evaluate(MEASURE, view)
    finally:
        ctx.close()


CASES = [(name, fn, view) for name, (fn, views) in PAGES.items() for view in views]


@pytest.fixture(scope="module")
def results(browser):
    return {f"{n}/{v}": _measure(browser, fn, v) for n, fn, v in CASES}


@pytest.mark.parametrize("case", [f"{n}/{v}" for n, _, v in CASES])
def test_targets_are_44px(results, case):
    bad = []
    for el in results[case]["els"]:
        need = SIZE_EXEMPT.get(el["key"], (MIN_TARGET, ""))[0]
        if el["w"] + 0.5 < need or el["h"] + 0.5 < need:
            bad.append(
                f"{el['key']} '{el['text']}' {el['w']:.0f}x{el['h']:.0f} (min {need})"
            )
    assert not bad, f"{case}: targets below minimum:\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("case", [f"{n}/{v}" for n, _, v in CASES])
def test_targets_are_8px_apart(results, case):
    bad = []
    for el in results[case]["els"]:
        pair = tuple(sorted((el["key"], el["nb"])))
        if el["gap"] + 0.5 < MIN_GAP and pair not in GAP_EXEMPT:
            bad.append(
                f"{el['key']} '{el['text']}' is {el['gap']:.1f}px from {el['nb']}"
            )
    assert not bad, f"{case}: targets closer than {MIN_GAP}px:\n  " + "\n  ".join(bad)


def test_exemptions_still_apply(results):
    """An exception that matches nothing (or no longer needs to) must go."""
    seen: dict[str, float] = {}
    for res in results.values():
        for el in res["els"]:
            seen[el["key"]] = min(seen.get(el["key"], 1e9), el["w"], el["h"])
    stale = [
        f"{key} ({'not found' if key not in seen else f'now {seen[key]:.0f}px'})"
        for key in SIZE_EXEMPT
        if key not in seen or seen[key] + 0.5 >= MIN_TARGET
    ]
    assert not stale, "remove from SIZE_EXEMPT: " + ", ".join(stale)


@pytest.mark.parametrize("width", sorted(MIN_YEAR_TRACK))
def test_year_track_is_wide_enough_to_drag(browser, width):
    res = _measure(browser, "player.html", "game-view", width)
    assert res["yearTrack"] is not None
    assert res["yearTrack"] >= MIN_YEAR_TRACK[width], (
        f"year track {res['yearTrack']:.0f}px at {width}px viewport"
    )
