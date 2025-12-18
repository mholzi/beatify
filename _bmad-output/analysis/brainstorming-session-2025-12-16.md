---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Beatify - Home Assistant HACS integration for Hitster-style music game'
session_goals: 'Scale music timeline game for larger crowds, frictionless player access'
selected_approach: 'ai-recommended'
techniques_used: ['Question Storming', 'Cross-Pollination', 'SCAMPER Method']
ideas_generated: [15]
context_file: 'project-context-template.md'
session_status: 'complete'
---

# Brainstorming Session Results

**Facilitator:** Markusholzhaeuser
**Date:** 2025-12-16

## Session Overview

**Topic:** Beatify - A Home Assistant HACS integration that reimagines the Hitster music game for smart home environments

**Goals:**
- Scale the game experience for larger crowds/parties (beyond original 2-10 player limit)
- Enable frictionless player access via local web interface (no login, no HA account)
- Leverage HA media players for centralized audio playback

### Context Guidance

**Project Focus Areas:**
- User Problems: Current Hitster requires app downloads, limited to 10 players
- Technical Approach: HACS integration + local web server for player access
- Architecture: HA owner as admin, players via browser on local network
- Differentiation: Smart home integration, crowd scaling, no-friction access

### Key Concepts

| Beatify Element | Description |
|-----------------|-------------|
| Platform | Home Assistant + HACS ecosystem |
| Admin Role | HA setup owner controls game flow |
| Player Access | Local website, no accounts, no login required |
| Media Integration | HA media players for song playback |
| Core Mechanic | Timeline-based song guessing (Hitster-style) |
| Scale Target | Support for large crowds (party/event scale) |

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** Beatify HA integration with focus on crowd scaling and frictionless access

**Recommended Techniques:**

1. **Question Storming** (deep): Define the right problem space before jumping to solutions - ensure we're asking the right questions about scaling, synchronization, UX, and engagement
2. **Cross-Pollination** (creative): Transfer solutions from other domains - Kahoot, Jackbox, Twitch, Eurovision voting - to gather fresh approaches to crowd-scale party games
3. **SCAMPER Method** (structured): Systematically adapt Hitster mechanics for HA ecosystem using 7 lenses (Substitute, Combine, Adapt, Modify, Put to other uses, Eliminate, Reverse)

**AI Rationale:** This Deep → Creative → Structured flow ensures we first understand the problem space fully, then gather external inspiration, and finally systematically map solutions to HA capabilities

---

## Technique 1: Question Storming Results

### Core Game Design Defined

**Game Identity:** Beatify is NOT a Hitster clone - it's a new crowd-scale music year-guessing game built for Home Assistant.

### Player Flow
```
Scan QR → Enter Name → Lobby (see others) → Game Screen
```

### Admin Flow
```
Launch Game (reset) → Show QR → Start Game → Play as Player + Controls
```

### Round Mechanics
| Element | Design |
|---------|--------|
| Participation | All players simultaneously |
| Time Limit | 30 seconds (configurable) |
| Scoring | Exact=10pts, ±3yrs=5pts, ±5yrs=1pt |
| Betting | Double-or-nothing during countdown |
| No submission | 0 points |

### Player Screen During Round
- Album cover (from media player)
- Countdown timer
- Year selector (hybrid: decade buttons + fine-tune)
- List of submitted players (scrollable row, shows who's betting)

### Reveal Sequence
1. Song info revealed (Year, Title, Artist)
2. Personal result (your guess + points)
3. All player results
4. Updated ranking table

### Admin Powers (While Playing)
- Stop song
- Start next round
- Volume up/down

### Music Architecture
```
JSON Files → Music Assistant → HA Media Player
(ID, URL, Year, Album)
```
- Multiple playlist JSONs (admin selects which to include)
- NOT dependent on direct Spotify integration

### Additional Rules
- Late joiners: Can enter mid-game
- Between rounds: Result screen until admin starts next
- Song fails: Admin skips to next

### Key Questions Identified
- Year selector UX → Hybrid (decade + fine-tune) ✅
- Playlist management → Multi-select JSON files ✅
- Admin role → Player with extra controls ✅

---

## Technique 2: Cross-Pollination Results

### Inspiration Sources
- Kahoot (speed, streaks, podium)
- Jackbox (party game UX)
- Eurovision (dramatic reveals)
- Twitch (predictions/betting)

### Features Added from Cross-Pollination

#### ⚡ Speed Bonus (from Kahoot)
| Submit Within | Multiplier |
|---------------|------------|
| 0-10 seconds | 1.5x |
| 10-20 seconds | 1.2x |
| 20-30 seconds | 1x |

#### 🔥 Streak Bonus (from Kahoot)
| Streak | Bonus Points |
|--------|--------------|
| 3 in a row | +20 pts |
| 5 in a row | +50 pts |
| 10 in a row | +100 pts |

- Streak status visible to all players ("Max is on 🔥5 streak!")

#### 🏆 End-Game Ceremony (from Kahoot/Eurovision)
- Podium with 🥇🥈🥉
- Rank movement animation (show who climbed/dropped)
- Awards showcase:
  - 🔥 Longest Streak
  - ⚡ Fastest Guesser
  - 🎲 Biggest Risk Taker
  - 🎯 Most Exact Hits

#### 🎭 Dramatic Reveal (from Eurovision)
- Range narrowing: "It's from the 80s... It's 1985!"
- Then: Song Title + Artist

### Features Skipped
- ❌ Spectator Mode - not needed
- ❌ Smart Home Integration - not for v1
- ❌ Team Mode - not for v1

---

## Technique 3: SCAMPER Results

| Letter | Question | Decision |
|--------|----------|----------|
| **S** | Substitute | No changes needed |
| **C** | Combine | No changes needed |
| **A** | Adapt | Done via Cross-Pollination |
| **M** | Modify | See configurables below |
| **P** | Put to other uses | Not for v1 |
| **E** | Eliminate | Keep all features |
| **R** | Reverse | No changes |

### Admin-Configurable Settings (from SCAMPER-M)
- ✅ Round timer (default: 30s)
- ✅ Scoring values (default: 10/5/1)
- ✅ Speed bonus multipliers (default: 1.5x/1.2x/1x)
- ✅ Streak bonus thresholds (default: 3→20, 5→50, 10→100)
- ❌ Max players: Unlimited (not configurable)

---

## Final Product Summary: Beatify v1

### What is Beatify?
A Home Assistant HACS integration that brings crowd-scale music year-guessing gameplay to your smart home. Players join via QR code, guess the release year of songs, and compete for points on a live leaderboard.

### Core User Flows

**Admin Flow:**
```
Launch Game → Select Playlists → Show QR Code → Start Game → Play + Control → End Game
```

**Player Flow:**
```
Scan QR → Enter Name → Wait in Lobby → Play Rounds → See Final Results
```

### Round Mechanics

| Phase | What Happens |
|-------|--------------|
| **Song Plays** | Album cover shown, countdown starts |
| **Guessing (30s)** | Players select year, optionally bet |
| **Reveal** | "It's from the 80s... It's 1985!" + Song info |
| **Results** | Personal score → All scores → Updated leaderboard |
| **Next Round** | Admin triggers when ready |

### Scoring System

| Accuracy | Base Points | With Bet (2x) |
|----------|-------------|---------------|
| Exact year | 10 | 20 |
| Within 3 years | 5 | 10 |
| Within 5 years | 1 | 2 |
| More than 5 years | 0 | 0 |

**Speed Bonus (multiplier on base points):**
- 0-10 seconds: 1.5x
- 10-20 seconds: 1.2x
- 20-30 seconds: 1.0x

**Streak Bonus (flat bonus):**
- 3 in a row: +20 pts
- 5 in a row: +50 pts
- 10 in a row: +100 pts

### Technical Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  JSON Files  │ ──→ │  Music Assistant │ ──→ │  HA Media       │
│ (ID,URL,Year,│     │  (HA Integration)│     │  Player         │
│  Album)      │     └──────────────────┘     └─────────────────┘
└──────────────┘
        ↓
┌──────────────────────────────────────────────────────────────┐
│                    BEATIFY HACS INTEGRATION                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │ Admin Panel │    │ Game Engine │    │ Player Web UI   │  │
│  │ (Lovelace)  │    │ (Backend)   │    │ (Local Server)  │  │
│  └─────────────┘    └─────────────┘    └─────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Key Features

**For Players:**
- Zero-friction join (QR → Name → Play)
- Mobile-friendly year selector (decade buttons + fine-tune)
- Live visibility of who's submitted/betting
- Real-time leaderboard with streak indicators
- Personal + global results each round

**For Admin:**
- Player + controller dual role
- Multi-playlist selection
- All game parameters configurable
- Simple controls (stop, next, volume)
- Late-joiner support

**End-Game Experience:**
- Podium (🥇🥈🥉) with rank movement animation
- Awards: Longest Streak, Fastest Guesser, Biggest Risk Taker, Most Exact Hits

### Out of Scope for v1
- ❌ Spectator mode
- ❌ Smart home integration (lights/sounds)
- ❌ Team mode
- ❌ Tournament/multi-game mode
- ❌ User accounts/history

---

## Next Steps

This brainstorming session has produced a comprehensive product vision for Beatify v1.

**Recommended workflow continuation:**

1. **Create Product Brief** → Formalize this vision into a structured brief
2. **Create PRD** → Detail all requirements with acceptance criteria
3. **Create Architecture** → Technical design for HACS integration
4. **Create Epics & Stories** → Break down into implementable work items

**Document saved to:** `_bmad-output/analysis/brainstorming-session-2025-12-16.md`

---

*Session completed: 2025-12-16*
*Techniques used: Question Storming, Cross-Pollination, SCAMPER*
*Session facilitated by: Mary (Business Analyst Agent)*
