# Design System — Beatify

> **Always read this file before making any visual or UI change.** The tokens live in [custom_components/beatify/www/css/styles.css](custom_components/beatify/www/css/styles.css). This file is the authoritative prose behind those tokens.

## Product Context

- **What this is:** An open-source multiplayer music trivia party game for Home Assistant. A song plays through the host's existing smart speakers; guests scan a QR code, race to guess the release year on their phones, and a TV shows the scoreboard.
- **Who it's for:** Home Assistant users hosting dinner parties, game nights, and gatherings. Technical enough to run HA; non-technical guests must be able to play from a phone without installing anything.
- **Space/industry:** Music-trivia party games. Peers: Hitster (physical + Spotify QR), Jackbox (social party games), SongPop, Kahoot, Guezzer.
- **Project type:** Multi-surface UI shipped as a Home Assistant custom component.
  - Spectator dashboard (landscape TV, kiosk-mode)
  - Player screen (mobile-first, portrait)
  - Launcher (host controls)
  - Admin dashboard (config + content management)
  - Analytics dashboard (history + leaderboards)

## Aesthetic Direction

**Direction:** Neon party show — high-energy game-show feel, dark stage with glowing accents. Sits between Jackbox's cartoon warmth and Hitster's studio-lights glow, with a tech-forward edge that earns its place inside Home Assistant's dark-dashboard world.

**Decoration level:** Intentional. Glow effects on key moments, gradient wordmark as brand signature, subtle neon borders on leading elements. No decorative blobs, no purple gradients as default accent, no stock-photo heroes.

**Mood:** Showtime. The dashboard should feel like a small, private game-show stage — lights dimmed, numbers glowing, the room looking up at the screen when the year reveals.

## Typography

| Role | Font | Weight | Rationale |
|------|------|--------|-----------|
| Display / hero / wordmark | **Outfit** | 900 | Personality at extreme weight; modern geometric without feeling corporate. Gradient fill holds up at 72px+. |
| Headings | **Outfit** | 600–700 | Same family as display keeps brand coherent; medium weights work at mid scale. |
| Body / UI labels | **Inter** | 400–500 | Readable at TV distance and on small phones. Yes, it's overused — it's also the right tool for legibility in data-dense admin views. |
| Data / scoreboards | **Inter** with `font-variant-numeric: tabular-nums` | 600–700 | Numbers align in columns. |
| Mono (rare) | system monospace | 400 | Only for hex values, debug output. |

**Loading:** Google Fonts CDN. Preconnect in `<head>`. Display=swap.

**Bespoke oversize scale** — these tokens exist because these are the moments the game is about. Never use for anything else:

- `--font-size-year: 56px` — year reveal on spectator dashboard
- `--font-size-timer: 64px` — countdown on player screen + dashboard
- `--font-size-hero: 72px` — wordmark and hero-level moments

**Standard scale:**

| Token | px |
|-------|-----|
| `--font-size-xs` | 10 |
| `--font-size-sm` | 12 |
| `--font-size-base` | 14 |
| `--font-size-md` | 16 |
| `--font-size-lg` | 18 |
| `--font-size-xl` | 20 |
| `--font-size-2xl` | 24 |
| `--font-size-3xl` | 28 |
| `--font-size-4xl` | 32 |

**Weights:** 400 / 500 / 600 / 700 / 800 / 900.

## Color

**Approach:** Restrained-with-drama. One warm accent + one cool accent against deep navy. Semantic colors stay neon-saturated because TVs eat contrast across the room.

### Background / Surface

| Token | Value | Usage |
|-------|-------|-------|
| `--color-bg-primary` | `#0a0a12` | Every dark surface. The stage. |
| `--color-bg-surface` | `rgba(255,255,255,0.05)` | Cards, panels, song card on dashboard. |
| `--color-dark-surface-hover` | `rgba(255,255,255,0.08)` | Hover state on dark surfaces. |
| `--color-bg-light` | `#f5f5f5` | Admin pages (light theme only). |
| `--color-bg-white` | `#ffffff` | Admin cards. |

### Accents

| Token | Value | Usage |
|-------|-------|-------|
| `--color-accent-primary` | `#ff2d6a` | Hot pink. Brand color. Year reveals, leader highlights, primary CTAs, wordmark gradient start. |
| `--color-accent-secondary` | `#00f5ff` | Cyan. Data deltas, timer, secondary CTAs, wordmark gradient end. |
| `--color-accent-brand` | `#6366f1` | Indigo. Neutral brand accent for links, focus rings in admin. |
| `--color-neon-purple` | `#9d4edd` | Analytics accent + steal power-up. Do not use elsewhere. |

### Semantic (kept neon for TV visibility)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-success-neon` | `#39ff14` | Score gains, correct answers. |
| `--color-success` | `#10b981` | Admin UI (muted success). |
| `--color-warning-alt` | `#ff6600` | Slow answer warning. |
| `--color-warning` | `#f59e0b` | Admin UI (muted warning). |
| `--color-error-neon` | `#ff0040` | Wrong answer, destructive action. |
| `--color-error` | `#ef4444` | Admin UI (muted error). |

### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--color-text-white` | `#ffffff` | Default on dark. |
| `--color-text-neon-muted` | `#b3b3c2` | Secondary text on dark. |
| `--color-text-primary` | `#1f2937` | Default on light (admin). |
| `--color-text-muted` | `#6b7280` | Secondary text on light. |
| `--color-text-dim` | `#6b6b7a` | Labels, captions on dark. |

### Dark vs. light

Spectator dashboard, player screen, launcher, analytics → **dark theme is default**. Admin dashboard → **light theme is default** with dark accent components.

## Spacing

**Base unit:** 4px. **Density:** comfortable on dashboard and player; compact on admin tables.

| Token | px |
|-------|-----|
| `--space-xs` | 4 |
| `--space-sm` | 8 |
| `--space-md` | 16 |
| `--space-lg` | 24 |
| `--space-xl` | 32 |
| `--space-2xl` | 48 |

## Layout

**Approach:** Hybrid.

- **Spectator dashboard:** composition-first. Year reveal fills the upper viewport like a poster, not a card. The big numbers ARE the layout.
- **Player screen:** mobile-first portrait; timer and choice buttons are the only two things that matter.
- **Admin / analytics:** grid-disciplined. Data-dense, scannable, conventional.

**Max content width (admin):** 1280px.

**Border radius scale:**

| Token | px |
|-------|-----|
| `--radius-sm` | 4 |
| `--radius-md` | 8 |
| `--radius-lg` | 12 |
| `--radius-xl` | 16 |
| `--radius-2xl` | 20 |
| `--radius-full` | 9999 |

## Motion

**Approach:** Intentional. Motion reinforces game moments, never decorates.

**Durations:**

| Token | ms | Usage |
|-------|-----|-------|
| `--transition-fast` | 150 | Hover, focus, small state changes. |
| `--transition-normal` | 300 | Panel transitions, score reveals. |
| `--transition-slow` | 500 | Year reveal entrance, round transitions. |

**Keyframes:**

- `logo-pulse` (2s, ease-in-out, infinite) — loading state only.
- `rotate-hint` (2s, ease-in-out, infinite) — portrait-orientation warning on spectator view.
- Score deltas animate +N from 0 over ~500ms with `ease-out`.

**Accessibility:** Always respect `prefers-reduced-motion: reduce`. All keyframe animations are gated behind the media query.

## Effects

**Glow tokens** — use on neon moments, not decoratively:

- `--glow-primary: 0 0 20px var(--color-accent-primary)` — on primary buttons, leader highlights.
- `--glow-secondary: 0 0 20px var(--color-accent-secondary)` — on timer, data deltas.
- `--glow-success: 0 0 20px var(--color-success-neon)` — on score-gain animations.
- `--glow-warning: 0 0 20px var(--color-warning)` — slow-answer badge.
- `--glow-error: 0 0 20px var(--color-error)` — wrong answer, destructive action.

**Wordmark signature:**

```css
.wordmark-gradient {
  background: linear-gradient(90deg, var(--color-accent-primary), var(--color-accent-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.wordmark-hero {
  text-shadow: 0 0 40px rgba(255, 45, 106, 0.5);
}
```

Use only on the wordmark, only in hero placements. Never apply the pink→cyan gradient to UI elements, body text, or decorative flourishes.

## Risk log — deliberate departures from category norms

These are choices we've made on purpose. If someone proposes undoing one, it should be because the tradeoff changed, not because they didn't know we made the call.

| Risk | Category norm | Beatify's choice | Rationale |
|------|---------------|------------------|-----------|
| Neon cyber over warm retro | Hitster / Jackbox lean warm (orange stage lights, cartoon palettes) | Deep navy + hot pink + cyan | Beatify lives inside Home Assistant dashboards (dark-first audience). Warm tones muddy on TVs at distance; neon reads from across the room. The hot-pink primary keeps warmth in the palette. |
| Bespoke oversize type scale | Category uses one heading scale + hero ~48px | Dedicated 56 / 64 / 72px tokens for year / timer / hero | These are the moments the game is about. The type scale literally encodes the game's priorities. |
| Gradient wordmark as brand signature | Most HA integrations have no brand | Pink→cyan gradient wordmark, used sparingly | HACS and GitHub are a sea of grey favicons. Beatify has a face. Low cost when confined to hero moments. |
| Kiosk-first spectator view with portrait warning | Most web apps responsive everywhere | Landscape-only spectator with keyframe animation telling you to rotate | The TV IS landscape. Fighting this would compromise the hero moment. |

## Patterns

### Player onboarding — post-QR education

**Status:** Pattern documented, not yet implemented. Full storyboard at `~/.gstack/projects/mholzi-beatify/designs/player-onboarding-20260418/preview.html`.

**When to use:** First-time player lands on `player.html` after scanning the host's QR code. Goal: turn "I just scanned a random QR code at a dinner party" into "I know what this game is about and I'm ready to play" before the host starts the first round. Parallels the admin first-run wizard (see below) but scoped hard for tipsy guests on a phone.

**Structure:** Name entry + 4-card swipeable tour + Ready screen + Lobby. 7 player-facing screens total, plus a host-side visibility gate that changes how the admin sees the lobby.

| Step | Purpose | Required | Skippable |
|------|---------|----------|-----------|
| 1. Welcome | Wordmark hero + name capture. Sets the brand moment. | Yes | No |
| 2. Tour 1 — Guess the year | Core loop. Slider preview with year 1984 + album placeholder. | No (tour is optional) | Skip button sends to Ready |
| 3. Tour 2 — Double or nothing | Bet mechanic. Shows `12 × 2 = 24` neon-green reward. | No | Skip |
| 4. Tour 3 — Steal an answer | Power-up. Cyan steal button + target picker preview. | No | Skip |
| 5. Tour 4 — Guess the artist | Bonus-round multiple-choice pattern. 2×2 option grid matching in-game UI. | No | Skip (button reads "Let's play →") |
| 6. Ready | Wordmark hero + "You're in, {name}!" + waiting pulse + player count meta-line. | — | — |
| 7. Lobby | Existing polished lobby with ↺ "Replay the tour" entry point. | — | — |

**Tour header (wizard-style progress):** Reuses the `.wiz-progress` pattern from the admin first-run wizard. Four segments, 3px tall, 4px gaps. Completed segments fill with the `--color-accent-primary → --color-accent-secondary` gradient and a pink glow. The current segment renders at 60% inner-fill width. "Step N of 4" label sits above the bar.

**Tour footer (explicit buttons):** Every tour card ends with a ghost `Skip` button (flex: 1) + primary `Next →` button (flex: 2) with the `--glow-primary` treatment. The final card's Next reads "Let's play →" to signal transition out of the tour. Tap-to-continue is still supported on the card body, but the explicit buttons are the primary affordance.

**Content — locked copy (≤8 words per caption):**

| Card | Title | Caption | Hint |
|------|-------|---------|------|
| 1 | Guess the year | Closer = more points | — |
| 2 | Double or nothing | Bet you're close. Win double. | — |
| 3 | Steal an answer | Copy another player. Once per game. | Use it when you have no idea. |
| 4 | Guess the artist | Some rounds reward the artist too. | +5 bonus points. |

**Auto-advance:** 4 seconds per card unless the user taps or swipes first. Respects `prefers-reduced-motion: reduce` → advances instantly on tap only.

**Resume / skip behavior:**

- Returning players (name in localStorage) skip the tour by default — straight to Ready.
- First-time players always see the tour. Card-level Skip button advances to next; "Skip tour" in the step-count row (top-right of every card) sends to Ready.
- Skip from any card = READY state immediately. No confirmation, no intermediate LEARNING state. Trust the user's choice.
- Lobby's ↺ "Replay the tour" link re-enters the 4 cards as a read-only view (no Skip pressure, Next still advances).

**Host visibility gate — protocol:**

Players gain a server-side `onboarded: bool` flag that flips true when they exit the tour (Skip all, Next through final card, or already-stored localStorage skip). Until it flips, the host sees them as LEARNING.

Player state machine: `JOINING → LEARNING → READY → PLAYING`. Skip from any tour card collapses `LEARNING → READY` immediately.

**Host UI rules:**

- Player count badge shows total (e.g. "👥 4") but the Players section summary reads "3 ready · 1 learning".
- LEARNING players render as `.player-chip.pending` — dashed border, dim text, cyan "TOUR" badge (static, no pulse).
- Amber warning banner above the Start button: "⚠️ N player still learning the rules" (uses `--color-warning-alt` on `rgba(255,102,0,0.06)` background).
- Start button stays clickable. On click while any player is LEARNING, show a confirm modal: "1 player is still learning the rules. Start anyway?" → Yes / Wait. Host can override; the friction prevents accidental starts.

**Player UI rules:**

- Players always see themselves as ready in their own lobby view. No self-TOUR badge.
- Other players on tour are **invisible** in the player lobby. Peer pressure lives on the host, not on other players. Don't shame the slow friend.

**Visual language:**

- Full-screen takeover per screen. Tour replaces the lobby fully (no modal overlay).
- Background: `--color-bg-primary` (#0a0a12) + dual-radial glow (pink top, cyan bottom-right).
- Hero titles: Outfit 900 at 44px (tour cards), 80-88px (wordmark moments).
- Year number on Tour 1: 68px Outfit 900 in `--color-accent-secondary` with `0 0 24px rgba(0,245,255,0.6)` text-shadow — smaller than the in-game 56px `--font-size-year` token because the preview is demonstrative, not the hero moment.
- The success-neon color (`#39ff14`) appears **only** on the Tour 2 final score "24" — this is the "win" reveal moment tokenized. Nowhere else in onboarding.
- Artist options grid on Tour 4 uses the exact in-game `.artist-options-grid` component (2×2, min-height 48px, 2px border, is-winner state with `--color-success` + `--glow-primary`).

**Animation spec:**

- Welcome → Tour 1: fade + slight lift, 300ms (`--transition-normal`). Name-input cyan glow intensifies on focus.
- Tour card transitions: horizontal swipe, 250ms ease-out.
- Progress segment fill: gradient fills from 0 → 60% on enter, then to 100% on exit (300ms total).
- Ready screen entry: wordmark fades up 500ms, waiting pulse starts at +200ms. No confetti — saved for game end.
- Host visibility transition: when a LEARNING player completes the tour, their chip fades from dashed to solid over 400ms; the "ready count" section summary pulses with `--glow-success` once (single flash, not infinite).
- All motion gated behind `prefers-reduced-motion: reduce`.

**Anti-patterns for this flow:**

- Never gate the tour behind a modal. It replaces the lobby full-screen.
- Never show the tour to a returning player (localStorage name check).
- Never add a 5th card. Movie-challenge, intro-round, reactions, superlatives — all handled by in-game splashes + badges at the moment they matter. Four is the ceiling.
- Never hard-disable the host Start button. Warn + confirm; don't paternalize.
- Never expose the TOUR badge to other players. Host-only metadata.
- Never use the success-neon color outside the Tour 2 score reveal. That green is rare and earned.

### First-run wizard — new-user onboarding

**Status:** Pattern documented, not yet implemented. Storyboard at `~/.gstack/projects/mholzi-beatify/designs/design-system-20260417/wizard-flow.html`.

**When to use:** Admin screen first-load for a user who has never configured Beatify. The goal is to turn "I just installed an unknown HACS integration" into "I know what this is and my first game is minutes away."

**Structure:** 3 required steps + 1 optional "level up" step + celebratory completion.

| Step | Required | Purpose |
|------|----------|---------|
| 1. Speakers | Yes | Pick one or more media players. Test-play button per row. |
| 2. Music service | Yes | Pick provider (chip grid), run OAuth (3-step indicator card). |
| 3. Playlist | Yes | Pick from 4 curated bundled packs. Fallback: import from URL. |
| 4. Level up | No | Toggles for Party Lights, Voice/TTS, Game Tuning, HA Entities — each gated on HA capability detection. |
| Done | — | Wordmark hero + live spectator-preview box + "Start first game" CTA. |

**Trigger logic:** Show the wizard when ALL of the following are true on admin load:

- No `media_player` configured
- No credentials saved for any music service
- `beatify_wizard_dismissed` flag absent from localStorage

Any one false → load regular admin instead.

**Resume:** If some required steps are done but not all, open the wizard at the first incomplete step. All 3 required done → skip wizard; show regular admin with an optional "Finish level-up" banner.

**Skip:** "Skip setup" in top-right on Steps 1–3. Skipping writes `beatify_wizard_dismissed = true` and loads regular admin with a persistent "Finish setup" pill in the header. Pill disappears once all 3 required steps complete. Clicking the pill reopens the wizard at the first incomplete step.

**Capability-gated toggles (Step 4):**

- **Party lights** — requires any `light.*` entity in HA
- **Voice announcements** — requires a registered `tts.*` service
- **Game tuning** — always shown (defaults always work)
- **HA entity shortcuts** — always shown, badged "Power-user"

Unavailable capabilities render disabled with ≤45% opacity and an explanation ("No lights found in HA").

**Visual language:**

- Full-screen takeover, dark stage + dual-radial glow background (pink top, cyan bottom-right)
- Progress bar: 3 equal segments, filled with the primary→secondary gradient, current segment has a 60% inner fill
- Hero wordmark uses `--wordmark-hero` text-shadow treatment
- Primary CTA is glow-primary pink; Ghost buttons for Back/Skip
- Completion screen animates: wordmark fades up (600ms), "READY TO PLAY" badge in (300ms), demo preview scales 0.8→1.0 (500ms), CTA glow pulses every 2s until click
- Always respects `prefers-reduced-motion` — collapses to single fade

**Anti-patterns for this flow:**

- Never gate the wizard behind a modal — it replaces the admin page, full-screen
- Never show the wizard to a returning user who has any config (use resume or skip)
- Never make Step 4 feel required; the copy must read as a genuine bonus

## Anti-patterns (never ship)

- Purple/violet gradients as default accent (our purple is reserved for analytics + steal power-up)
- Generic 3-column feature grids with icons in colored circles
- Centered everything with uniform spacing
- Uniform bubbly border-radius on all elements (use the scale — different radii mean different things)
- Gradient buttons as the primary CTA pattern (solid neon is louder and on-brand)
- Decorative background blobs
- "Built for [X]" / "Designed for [Y]" marketing copy patterns
- Overused fonts as primary in NEW contexts (Poppins, Montserrat, Roboto). Outfit + Inter is the locked choice.

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-17 | Initial DESIGN.md created documenting the existing system (styles.css → prose) | Design-consultation pass. Existing neon/cyberpunk direction + oversized game-moment type scale + gradient wordmark were locked in as Beatify's intentional choices, not accidents. No visual changes shipped. |
| 2026-04-17 | Added first-run wizard pattern (see `## Patterns`). Chosen over "polish pass" and "live demo hero" variants. | Admin first-impression review. New users land on a bare-bones admin with emoji icons and collapsed sections — no guidance. Full-screen onboarding with 3 required steps + optional level-up maximizes the chance that a fresh install becomes a played game. Storyboard + trigger spec saved at `~/.gstack/projects/mholzi-beatify/designs/design-system-20260417/wizard-flow.html`. Implementation pending. |
| 2026-04-19 | Added player-onboarding-v2 pattern (see `## Patterns / Player onboarding — post-QR education`). Chosen over lobby-with-expanded-education and "no tour" variants. | Current lobby collapses "How to Play" behind an accordion that most players never open. Game has non-obvious mechanics (bet, steal, artist bonus) that surprise players mid-game and feel unfair on first encounter. 4-card tour (year + bet + steal + artist) reuses the admin wizard's `.wiz-progress` header pattern for visual consistency. Host visibility gate introduces a new player state (`LEARNING`) that changes only the host's lobby view — other players never see TOUR badges. Host Start button stays clickable with a confirm modal, never hard-disabled. Storyboard + protocol spec saved at `~/.gstack/projects/mholzi-beatify/designs/player-onboarding-20260418/preview.html`. Implementation pending. |
