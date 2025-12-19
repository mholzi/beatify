---
stepsCompleted: [1, 2, 3, 4]
status: complete
completedAt: '2025-12-18'
inputDocuments:
  - '_bmad-output/prd.md'
  - '_bmad-output/architecture.md'
epicCount: 7
storyCount: 38
frCoverage: 59
---

# Beatify - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Beatify, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

**Installation & Setup (FR1-FR6)**
- FR1: Admin can install Beatify via HACS
- FR2: Admin can add Beatify integration via HA Settings → Integrations
- FR3: System can display available HA media players for selection
- FR4: System can display available HA media players for selection
- FR5: System can detect and list available playlist JSON files
- FR6: Admin can access standalone admin web page without authentication

**Game Configuration (FR7-FR11)**
- FR7: Admin can select one or more playlist files for a game session
- FR8: Admin can select which HA media player to use for audio output
- FR9: Admin can start a new game (creating lobby and QR code)
- FR10: Admin can view QR code page in print-friendly format
- FR11: System can generate QR code containing player join URL

**Player Onboarding (FR12-FR16)**
- FR12: Player can scan QR code to open player web page
- FR13: Player can enter a display name to join the game
- FR14: System can reject duplicate player names with helpful message
- FR15: Player can view QR code on their screen to invite others
- FR16: Late-joining player can enter mid-game directly into current round

**Lobby Management (FR17-FR21)**
- FR17: Player can view list of all players in lobby
- FR18: Player can see which player is the admin (badge indicator)
- FR19: Admin can see real-time lobby updates as players join
- FR20: Admin can click "Participate" to join as player with admin privileges
- FR21: Admin can start gameplay when ready (from player view with admin controls)

**Gameplay — Core Loop (FR22-FR31)**
- FR22: System can play song audio through selected HA media player
- FR23: Player can view album cover during round
- FR24: Player can view countdown timer during round
- FR25: Player can select a year guess using year selector
- FR26: Player can submit their guess before timer expires
- FR27: Player can see confirmation when their guess is submitted
- FR28: Player can see which other players have submitted (scrolling row)
- FR29: System can auto-advance to reveal when timer expires
- FR30: Player can view reveal showing correct year and song info
- FR31: Player can view their personal result for the round

**Gameplay — Scoring (FR32-FR38)**
- FR32: System can calculate accuracy score (exact=10, ±3yrs=5, ±5yrs=1, else=0)
- FR33: System can apply speed bonus multiplier (1.5x for 0-10s, 1.2x for 10-20s, 1.0x for 20-30s)
- FR34: System can track player streaks (consecutive scoring rounds)
- FR35: System can award streak bonuses (+20 at 3, +50 at 5, +100 at 10)
- FR36: Player can choose to bet (double-or-nothing) during countdown
- FR37: System can apply bet multiplier to round score
- FR38: System can award 0 points when player doesn't submit before timer

**Leaderboard (FR39-FR42)**
- FR39: Player can view live leaderboard with all player scores
- FR40: System can update leaderboard in real-time after each round
- FR41: Player can view final leaderboard when game ends
- FR42: Player can see streak status indicators on leaderboard

**Admin Controls During Gameplay (FR43-FR48)**
- FR43: Admin can stop current song early
- FR44: Admin can advance to next round
- FR45: Admin can adjust volume up/down (controlling HA media player)
- FR46: Admin can end game (triggering final leaderboard)
- FR47: Admin controls are visible only to admin-flagged player
- FR48: Admin controls are accessible from player screen (no device switching)

**Session Management (FR49-FR53)**
- FR49: System can pause game when admin disconnects
- FR50: Player can see "Waiting for admin..." when game is paused
- FR51: Admin can rejoin active game via admin page
- FR52: Admin can reclaim admin status by rejoining with same name
- FR53: System can perform full reset when game ends (all players disconnected)

**Error Handling (FR54-FR59)**
- FR54: System can display error when no playlists found (with how-to link)
- FR55: System can display error when no playlists found (with how-to link)
- FR56: System can display error when media player unavailable
- FR57: Player can see error when not on correct network (with WiFi hint)
- FR58: System can auto-reconnect player on connection drop
- FR59: System can recover player state on reconnection (rejoin current round)

### NonFunctional Requirements

**Performance**
- NFR1: Page load time < 2 seconds
- NFR2: WebSocket latency < 200ms
- NFR3: Year selector responsiveness 60fps
- NFR4: Lobby update delay < 500ms
- NFR5: Leaderboard update < 1 second

**Scalability**
- NFR6: Maximum concurrent players: 20 per game session
- NFR7: Maximum active games: 1 per HA instance

**Reliability**
- NFR8: Game completion rate: 99%
- NFR9: Reconnection success rate: 95%
- NFR10: Graceful degradation required (errors pause game, not crash)

**Integration**
- NFR11: Minimum HA version: 2025.11
- NFR12: Installation via HACS
- NFR13: At least one media_player entity required
- NFR14: Support any HA media_player entity

**Security (Intentionally Minimal)**
- NFR15: No authentication (frictionless access is design principle)
- NFR16: No user accounts
- NFR17: Local network only, no encryption needed

**Accessibility**
- NFR18: Touch targets minimum 44x44px
- NFR19: Sufficient color contrast for readability
- NFR20: No audio-only feedback (visual confirmation for all actions)

### Additional Requirements

**From Architecture Document:**

- **Starter Template:** Use `integration_blueprint` (ludeeus/integration_blueprint) as project foundation — clone and rename to beatify
- **Python Runtime:** Python 3.11+ required (HA dependency)
- **WebSocket Implementation:** Custom aiohttp WebSocket server at `/beatify/ws` (no HA auth, frictionless access)
- **State Machine Pattern:** Explicit phases: LOBBY → PLAYING → REVEAL → END with PAUSED state for admin disconnect
- **Playlist Data Format:** JSON with fields: `year` (integer), `uri` (string), `fun_fact` (string)
- **Playlist Storage Path:** `{HA_CONFIG}/beatify/playlists/*.json` (user-editable location)
- **Player Session Management:** Name-based identity with 60-second reconnection grace period
- **Timer Synchronization:** Hybrid approach — server sends `round_end_timestamp`, client calculates countdown locally
- **URL Structure:** All endpoints under `/beatify/*` namespace (admin, play, ws, static)
- **Album Art Fallback:** Use generic placeholder image (`www/img/no-artwork.svg`) when MA returns no artwork
- **Test Fixtures:** GameState accepts `time_fn` for testability; mock fixtures for HA and MA services

**Implementation Patterns (Architecture-Mandated):**

- Python: PEP 8 strict (snake_case functions, PascalCase classes)
- JavaScript: JS standard (camelCase functions, PascalCase classes)
- WebSocket messages: snake_case field names
- CSS classes: kebab-case with `is-` prefix for states
- Logging: HA native `_LOGGER = logging.getLogger(__name__)`
- Error codes: UPPER_SNAKE_CASE (NAME_TAKEN, GAME_NOT_STARTED, etc.)

### FR Coverage Map

| FR | Epic | Description |
|----|------|-------------|
| FR1 | Epic 1 | HACS installation |
| FR2 | Epic 1 | HA integration setup |
| FR3 | Epic 1 | Media player detection |
| FR4 | Epic 1 | Media player display |
| FR5 | Epic 1 | Playlist detection |
| FR6 | Epic 1 | Admin page access |
| FR54 | Epic 1 | MA not configured error |
| FR7 | Epic 2 | Select playlists |
| FR8 | Epic 2 | Select media player |
| FR9 | Epic 2 | Start game / create lobby |
| FR10 | Epic 2 | Print-friendly QR page |
| FR11 | Epic 2 | Generate QR code |
| FR55 | Epic 2 | No playlists error |
| FR56 | Epic 2 | Media player unavailable error |
| FR12 | Epic 3 | Scan QR to open page |
| FR13 | Epic 3 | Enter name to join |
| FR14 | Epic 3 | Duplicate name rejection |
| FR15 | Epic 3 | QR on player screen |
| FR16 | Epic 3 | Late-join mid-game |
| FR17 | Epic 3 | View lobby player list |
| FR18 | Epic 3 | See admin badge |
| FR19 | Epic 3 | Real-time lobby updates |
| FR20 | Epic 3 | Admin "Participate" button |
| FR21 | Epic 3 | Admin start game button |
| FR22 | Epic 4 | Play audio through HA media player |
| FR23 | Epic 4 | View album cover |
| FR24 | Epic 4 | View countdown timer |
| FR25 | Epic 4 | Year selector |
| FR26 | Epic 4 | Submit guess |
| FR27 | Epic 4 | Submit confirmation |
| FR28 | Epic 4 | "Who submitted" row |
| FR29 | Epic 4 | Auto-advance on timer |
| FR30 | Epic 4 | Reveal with year + song info |
| FR31 | Epic 4 | Personal round result |
| FR32 | Epic 4 | Accuracy scoring |
| FR33 | Epic 5 | Speed bonus multiplier |
| FR34 | Epic 5 | Streak tracking |
| FR35 | Epic 5 | Streak bonuses |
| FR36 | Epic 5 | Betting option |
| FR37 | Epic 5 | Bet multiplier |
| FR38 | Epic 5 | No submission = 0 points |
| FR39 | Epic 5 | Live leaderboard |
| FR40 | Epic 5 | Real-time leaderboard updates |
| FR41 | Epic 5 | Final leaderboard |
| FR42 | Epic 5 | Streak indicators |
| FR43 | Epic 6 | Stop song early |
| FR44 | Epic 6 | Advance to next round |
| FR45 | Epic 6 | Volume control |
| FR46 | Epic 6 | End game |
| FR47 | Epic 6 | Admin controls visible only to admin |
| FR48 | Epic 6 | Controls accessible from player screen |
| FR49 | Epic 7 | Pause on admin disconnect |
| FR50 | Epic 7 | "Waiting for admin" message |
| FR51 | Epic 7 | Admin rejoin via admin page |
| FR52 | Epic 7 | Reclaim admin status |
| FR53 | Epic 7 | Full reset on game end |
| FR57 | Epic 7 | Wrong network error |
| FR58 | Epic 7 | Auto-reconnect |
| FR59 | Epic 7 | State recovery on reconnect |

## Epic List

### Epic 1: Project Foundation & HA Integration

**Goal:** HA enthusiasts can install Beatify via HACS, configure it through the HA integrations UI, and verify all dependencies (media players, playlists) are detected and ready—with clear error messages if no media players are available.

**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR54

**Starter Template:** This epic uses `integration_blueprint` (ludeeus/integration_blueprint) as the project foundation.

---

### Epic 2: Game Session Creation

**Goal:** Host can set up a new game session by selecting playlists and a media player, generating a QR code that can be printed or displayed for guests to scan—with clear errors if playlists are missing or media player is unavailable.

**FRs covered:** FR7, FR8, FR9, FR10, FR11, FR55, FR56

---

### Epic 3: Player Onboarding & Lobby

**Goal:** Guests can scan the QR code, enter their name, join the lobby, and see who else is waiting. Admin can participate as a player while retaining controls. The lobby fills up with real-time updates and shows admin badge.

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21

---

### Epic 4: Core Gameplay Loop

**Goal:** Players experience the full game round: song plays through home speakers, everyone sees the album cover and timer, guesses a year, sees who submitted, then the reveal shows the correct answer, song info, and their personal score.

**FRs covered:** FR22, FR23, FR24, FR25, FR26, FR27, FR28, FR29, FR30, FR31, FR32

**Note:** Includes basic accuracy scoring (FR32) to deliver complete round feedback.

---

### Epic 5: Advanced Scoring & Leaderboard

**Goal:** The game becomes fully competitive with speed bonuses, streak tracking, betting mechanics, and a live leaderboard that updates after each round and shows final standings with streak indicators.

**FRs covered:** FR33, FR34, FR35, FR36, FR37, FR38, FR39, FR40, FR41, FR42

---

### Epic 6: Host Game Control

**Goal:** Host can control game flow during play—stop a song early, skip to next round, adjust volume, or end the game—all from their player screen while playing alongside guests.

**FRs covered:** FR43, FR44, FR45, FR46, FR47, FR48

---

### Epic 7: Resilience & Recovery

**Goal:** The system handles problems gracefully—auto-reconnection for dropped connections, game pause when admin disconnects with "Waiting for admin" message, state recovery so nobody loses their place, and clear network error messages.

**FRs covered:** FR49, FR50, FR51, FR52, FR53, FR57, FR58, FR59

---

### Epic Summary

| Epic | Title | FR Count | User Value |
|------|-------|----------|------------|
| 1 | Project Foundation & HA Integration | 7 | Install, verify, MA error handling |
| 2 | Game Session Creation | 7 | Configure game, config error handling |
| 3 | Player Onboarding & Lobby | 10 | Join & see players |
| 4 | Core Gameplay Loop | 11 | Play rounds with score feedback |
| 5 | Advanced Scoring & Leaderboard | 10 | Gamification & competition |
| 6 | Host Game Control | 6 | Control during play |
| 7 | Resilience & Recovery | 8 | Handle disconnects & recovery |

**Total: 7 epics, 59 FRs**

---

## Epic 1: Project Foundation & HA Integration

**Goal:** HA enthusiasts can install Beatify via HACS, configure it through the HA integrations UI, and verify all dependencies (media players, playlists) are detected and ready—with clear error messages if no media players are available.

**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR54

**Starter Template:** This epic uses `integration_blueprint` (ludeeus/integration_blueprint) as the project foundation.

---

### Story 1.1: Initialize Project from Starter Template

As a **developer**,
I want **Beatify initialized from integration_blueprint with proper naming and structure**,
So that **I have a working HA integration scaffold to build upon**.

**Acceptance Criteria:**

**Given** the integration_blueprint repository is available
**When** the project is initialized
**Then** a `custom_components/beatify/` directory exists with:
- `__init__.py` with basic async_setup_entry
- `manifest.json` with domain "beatify" and version "0.0.1"
- `const.py` with DOMAIN = "beatify"
- `config_flow.py` skeleton for UI setup
**And** the project passes `ruff` linting
**And** the project can be loaded by Home Assistant (no errors in logs)

---

### Story 1.2: HACS Installation & Integration Setup

As a **Home Assistant admin**,
I want **to install Beatify via HACS and add it through Settings → Integrations**,
So that **Beatify is properly registered in my Home Assistant instance**.

**Acceptance Criteria:**

**Given** Beatify is available in HACS
**When** admin installs via HACS and restarts Home Assistant
**Then** Beatify appears in the HACS integration list as installed
**And** no errors appear in Home Assistant logs

**Given** Beatify is installed via HACS
**When** admin navigates to Settings → Devices & Services → Add Integration → searches "Beatify"
**Then** Beatify appears in the integration list
**And** admin can initiate the setup flow

**Given** admin initiates Beatify setup
**When** the config flow completes successfully
**Then** Beatify integration appears in the integrations dashboard
**And** `hacs.json` contains valid metadata (name, documentation URL, domains)

---

### Story 1.3: Media Player Validation

As a **Home Assistant admin**,
I want **Beatify to validate that media players are available**,
So that **I know the system can play audio for the game**.

**Acceptance Criteria:**

**Given** at least one `media_player` entity exists in HA
**When** Beatify config flow runs
**Then** media players are detected as available
**And** setup proceeds to the next step

**Given** no `media_player` entities exist in HA
**When** Beatify config flow runs
**Then** a warning message displays: "No media players found. Beatify requires at least one media player."
**And** setup can proceed but warns that playback won't work without media players

**Given** media players are detected
**When** Beatify lists available players
**Then** all `media_player` entities are shown with their friendly names

---

### Story 1.4: Media Player & Playlist Discovery

As a **Home Assistant admin**,
I want **to see available media players and playlists during setup**,
So that **I can verify my system is ready to run Beatify games**.

**Acceptance Criteria:**

**Given** Beatify config flow is running
**When** Beatify scans for media players
**Then** all HA `media_player` entities are listed with friendly names (FR4)
**And** at least one media player must be available to proceed

**Given** Beatify scans for playlists
**When** the playlist directory `{HA_CONFIG}/beatify/playlists/` exists
**Then** all `.json` files in that directory are listed as available playlists (FR5)

**Given** the playlist directory does not exist
**When** Beatify scans for playlists
**Then** the directory is created automatically
**And** a message indicates "No playlists found yet" (not an error at setup time)

**Given** playlist JSON files exist
**When** Beatify validates them
**Then** each file is checked for required fields: `name`, `songs[]` with `year`, `uri`
**And** invalid playlists are flagged with specific error messages

---

### Story 1.5: Admin Page Access

As a **Home Assistant admin**,
I want **to access a standalone admin web page without authentication**,
So that **I can manage Beatify games from any device on my network**.

**Acceptance Criteria:**

**Given** Beatify integration is configured
**When** admin navigates to `http://<ha-ip>:8123/beatify/admin`
**Then** the admin page loads without requiring HA login (FR6)
**And** the page is mobile-responsive

**Given** admin page loads
**When** the page initializes
**Then** it displays:
- Detected media players from Story 1.4
- Detected playlists from Story 1.4
**And** if no playlists are found, shows helpful message with how-to link (FR54)

**Given** admin accesses the page from a mobile device
**When** the page renders
**Then** all elements are touch-friendly (44x44px minimum targets)
**And** layout adapts to mobile viewport

---

## Epic 2: Game Session Creation

**Goal:** Host can set up a new game session by selecting playlists and a media player, generating a QR code that can be printed or displayed for guests to scan—with clear errors if playlists are missing or media player is unavailable.

**FRs covered:** FR7, FR8, FR9, FR10, FR11, FR55, FR56

---

### Story 2.1: Select Playlists for Game

As a **host**,
I want **to select one or more playlist files for my game session**,
So that **I can customize the music selection for my party**.

**Acceptance Criteria:**

**Given** admin page is loaded with available playlists
**When** host views the playlist selection area
**Then** all valid playlists from `{HA_CONFIG}/beatify/playlists/` are displayed with:
- Playlist name
- Song count
- Checkbox for selection (FR7)

**Given** no playlists exist in the playlist directory
**When** admin page loads
**Then** an error displays: "No playlists found. Add playlist JSON files to [folder path]."
**And** a link to "How to create playlists" documentation is provided (FR55)

**Given** host selects multiple playlists
**When** playlists are selected
**Then** total song count across all selected playlists is displayed
**And** songs will be shuffled across all selected playlists during gameplay

**Given** host attempts to start game with no playlists selected
**When** start game is clicked
**Then** validation prevents start with message "Select at least one playlist"

---

### Story 2.2: Select Media Player

As a **host**,
I want **to select which HA media player to use for audio output**,
So that **the music plays through my preferred speakers**.

**Acceptance Criteria:**

**Given** admin page is loaded with available media players
**When** host views the media player selection area
**Then** all HA `media_player` entities are displayed as selectable options (FR8)
**And** each shows friendly name and current state (playing/idle/off)

**Given** no media players are available in HA
**When** admin page loads
**Then** an error displays: "No media players found. Configure a media player in Home Assistant."
**And** troubleshooting guidance is provided (FR56)

**Given** selected media player becomes unavailable (e.g., powered off)
**When** host attempts to start game
**Then** error displays: "Selected media player is unavailable. Please select another or check the device."
**And** media player list refreshes automatically (FR56)

**Given** host selects a media player
**When** selection is made
**Then** selection is visually confirmed
**And** the player is stored for the game session

---

### Story 2.3: Start Game & Create Lobby

As a **host**,
I want **to start a new game which creates a lobby for players to join**,
So that **I can begin gathering players for the party**.

**Acceptance Criteria:**

**Given** host has selected at least one playlist and a media player
**When** host clicks "Start Game"
**Then** a new game session is created with state LOBBY (FR9)
**And** WebSocket server begins accepting connections at `/beatify/ws`
**And** the admin page transitions to show the lobby view

**Given** game session is created
**When** lobby is active
**Then** a unique game ID is generated
**And** the join URL is constructed: `http://<ha-ip>:8123/beatify/play?game=<id>`

**Given** a game is already in progress
**When** admin page loads
**Then** admin sees option to "Rejoin existing game" or "End current game"
**And** cannot start a new game until current one ends

---

### Story 2.4: QR Code Generation & Display

As a **host**,
I want **to display and print a QR code that guests can scan to join**,
So that **joining the game is frictionless for my guests**.

**Acceptance Criteria:**

**Given** game lobby is created
**When** lobby view displays
**Then** a QR code is generated containing the player join URL (FR11)
**And** the QR code is large enough to scan from across a room

**Given** QR code is displayed
**When** host clicks "Print QR Code" or opens print dialog
**Then** a print-friendly page renders with:
- Large QR code centered
- Join URL displayed as text below
- "Scan to Play Beatify!" instruction
- Minimal styling for clean printing (FR10)

**Given** host views QR code on mobile device
**When** page renders
**Then** QR code scales appropriately for the viewport
**And** remains scannable

**Given** game session ends
**When** QR code is scanned
**Then** player sees message "This game has ended" rather than error

---

## Epic 3: Player Onboarding & Lobby

**Goal:** Guests can scan the QR code, enter their name, join the lobby, and see who else is waiting. Admin can participate as a player while retaining controls. The lobby fills up with real-time updates and shows admin badge.

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21

---

### Story 3.1: Player Page & QR Scan Entry

As a **party guest**,
I want **to scan a QR code and immediately see the game page**,
So that **I can join without downloading an app or creating an account**.

**Acceptance Criteria:**

**Given** guest scans the QR code with their phone camera
**When** the link opens in their browser
**Then** the player page loads at `/beatify/play?game=<id>` (FR12)
**And** page loads in under 2 seconds (NFR1)
**And** no login or authentication is required

**Given** player page loads
**When** game lobby is active
**Then** player sees the name entry screen
**And** the page is mobile-optimized with large touch targets

**Given** player page loads
**When** game ID in URL is invalid or expired
**Then** player sees friendly error: "Game not found. Ask the host for a new QR code."

---

### Story 3.2: Name Entry & Join

As a **party guest**,
I want **to enter my name and join the game**,
So that **other players can see who I am**.

**Acceptance Criteria:**

**Given** player is on the name entry screen
**When** player enters a display name and taps "Join"
**Then** WebSocket connection is established
**And** player joins the game session (FR13)
**And** player transitions to the lobby view

**Given** player enters a name that's already taken
**When** player taps "Join"
**Then** error displays: "Name taken, choose another" (FR14)
**And** player can enter a different name
**And** the name field retains focus for quick retry

**Given** player enters an empty name or only whitespace
**When** player taps "Join"
**Then** validation prevents join with message "Please enter a name"

**Given** player enters a very long name (>20 characters)
**When** player taps "Join"
**Then** name is truncated to 20 characters
**Or** validation prompts for shorter name

---

### Story 3.3: Lobby View & Player List

As a **player in the lobby**,
I want **to see all other players waiting and know who the admin is**,
So that **I know the game is filling up and who's in charge**.

**Acceptance Criteria:**

**Given** player has joined the lobby
**When** lobby view displays
**Then** a list of all players in the lobby is shown (FR17)
**And** each player's name is displayed
**And** the list updates in real-time as players join/leave (FR19)

**Given** admin has joined as a player
**When** lobby displays player list
**Then** admin's name shows a visible badge/indicator (e.g., "👑" or "(Host)") (FR18)
**And** the badge is clearly distinguishable

**Given** new player joins the lobby
**When** their WebSocket connection is established
**Then** all existing players see the new name appear within 500ms (NFR4)
**And** a subtle animation or highlight draws attention to the new joiner

**Given** player disconnects from lobby
**When** WebSocket connection closes
**Then** player is removed from the list after brief grace period (5 seconds)
**And** other players see the list update

---

### Story 3.4: Player-to-Player QR Sharing

As a **player who has joined**,
I want **to show the QR code on my screen to invite friends**,
So that **joining can spread virally without needing the wall poster**.

**Acceptance Criteria:**

**Given** player is in the lobby
**When** lobby view displays
**Then** a QR code is visible on the player's screen (FR15)
**And** QR code is labeled "Invite friends" or similar
**And** QR code contains the same join URL

**Given** another guest scans the QR from a player's phone
**When** they open the link
**Then** they reach the same name entry screen
**And** can join the same game

**Given** player is on a small phone screen
**When** QR code displays
**Then** QR code is sized appropriately (not too small to scan)
**And** can be tapped to enlarge if needed

---

### Story 3.5: Admin Participation

As a **host**,
I want **to join the game as a player while keeping admin controls**,
So that **I can play along with my guests**.

**Acceptance Criteria:**

**Given** host is on the admin page with active lobby
**When** host clicks "Participate"
**Then** host is prompted to enter their display name (FR20)
**And** host joins the lobby as a player
**And** host's view transitions to player view with admin controls visible

**Given** host has joined as participant
**When** host views the lobby
**Then** host sees the same player list as other players
**And** host's name shows admin badge (FR18)
**And** host has a "Start Game" button that others don't see (FR21)

**Given** host is the only player in lobby
**When** host clicks "Start Game"
**Then** game can still start (single-player testing mode)

**Given** multiple players are in lobby
**When** host clicks "Start Game"
**Then** game transitions from LOBBY to PLAYING state
**And** all connected players receive the state change via WebSocket

---

### Story 3.6: Late Join Support

As a **guest arriving late to the party**,
I want **to join a game that's already in progress**,
So that **I don't have to wait for the next game**.

**Acceptance Criteria:**

**Given** game is in PLAYING state (not LOBBY)
**When** late joiner scans QR and enters name
**Then** player joins directly into the current round (FR16)
**And** player skips the lobby entirely
**And** player sees the current game state (album cover, timer, etc.)

**Given** late joiner joins during PLAYING phase
**When** they land in the game
**Then** they can submit a guess for the current round if time remains
**And** they appear on the leaderboard with 0 points initially

**Given** late joiner joins during REVEAL phase
**When** they land in the game
**Then** they see the current reveal
**And** they're ready for the next round

**Given** game is in END state
**When** someone scans the QR
**Then** they see "This game has ended" message
**And** cannot join

---

## Epic 4: Core Gameplay Loop

**Goal:** Players experience the full game round: song plays through home speakers, everyone sees the album cover and timer, guesses a year, sees who submitted, then the reveal shows the correct answer, song info, and their personal score.

**FRs covered:** FR22, FR23, FR24, FR25, FR26, FR27, FR28, FR29, FR30, FR31, FR32

**Note:** Includes basic accuracy scoring (FR32) to deliver complete round feedback.

---

### Story 4.1: Song Playback via Media Player

**Complexity Note:** Medium effort - includes played-song tracking logic and direct HA media player control.

As a **player**,
I want **to hear the song playing through the home speakers**,
So that **everyone in the room experiences the same audio together**.

**Acceptance Criteria:**

**Given** game transitions to PLAYING state for a new round
**When** round starts
**Then** the selected song plays through the configured HA media player (FR22)
**And** playback begins within 1 second of round start

**Given** song is playing
**When** media player receives the play command
**Then** `media_player.play_media` service is called with:
- `entity_id`: selected media player
- `media_content_id`: song URI from playlist
- `media_content_type`: "music"
**And** volume is set to the configured level

**Given** a song has been played in the current game session
**When** the system selects the next song
**Then** that song is marked as "played" and excluded from future selection
**And** songs are selected randomly from the unplayed pool

**Given** all songs in selected playlists have been played
**When** the system tries to select the next song
**Then** admin is notified "All songs played - game will end after this reveal"
**And** game transitions to END after final reveal

**Given** admin starts a new game (from setup screen)
**When** new game session is created
**Then** all "played" markers are reset
**And** full playlist is available again

**Given** song URI is invalid or unavailable
**When** playback is attempted
**Then** system marks song as played and skips to next song in playlist
**And** logs warning for host review

**Given** media player becomes unavailable mid-game
**When** playback fails
**Then** game pauses with message "Media player unavailable"
**And** game can resume when media player is restored

---

### Story 4.2: Round Display (Album Cover & Timer)

As a **player**,
I want **to see the album cover and a countdown timer**,
So that **I have visual context and know how much time I have to guess**.

**Acceptance Criteria:**

**Given** round starts
**When** player view updates
**Then** album cover image is displayed prominently (FR23)
**And** image is fetched from media_player entity's `entity_picture` attribute
**And** if no artwork available, placeholder image (`no-artwork.svg`) is shown

**Given** round starts
**When** player view updates
**Then** countdown timer displays starting from 30 seconds (FR24)
**And** timer counts down in real-time
**And** timer is large and clearly visible

**Given** timer is running
**When** time reaches 10 seconds
**Then** timer changes color (e.g., orange) to indicate urgency

**Given** timer is running
**When** time reaches 5 seconds
**Then** timer changes color again (e.g., red) for final warning

**Given** server sends `round_end_timestamp`
**When** client calculates remaining time
**Then** countdown is synchronized across all clients within 200ms (NFR2)

---

### Story 4.3: Year Selector & Guess Submission

As a **player**,
I want **to select a year and submit my guess**,
So that **I can compete by guessing when the song was released**.

**Acceptance Criteria:**

**Given** player is viewing the round screen
**When** player interacts with year selector
**Then** a smooth, draggable slider or picker allows year selection (FR25)
**And** year range spans reasonable bounds (e.g., 1950-2025)
**And** selector responds at 60fps (NFR3)

**Given** player has selected a year
**When** player taps "Submit" button
**Then** guess is sent to server via WebSocket (FR26)
**And** submission timestamp is recorded for speed bonus calculation

**Given** player submits their guess
**When** server acknowledges
**Then** player sees visual confirmation (checkmark, "Submitted!") (FR27)
**And** submit button becomes disabled
**And** player cannot change their guess

**Given** player has not submitted
**When** they try to submit after timer expires
**Then** submission is rejected by server
**And** player sees "Time's up!" message

---

### Story 4.4: Submission Tracking Display

As a **player**,
I want **to see who else has submitted their guess**,
So that **I feel the social pressure and excitement of the game**.

**Acceptance Criteria:**

**Given** round is in progress
**When** any player submits their guess
**Then** all players see an updated "submitted" indicator (FR28)
**And** update appears within 500ms

**Given** submissions are being tracked
**When** player view displays
**Then** a scrolling row or list shows which players have submitted
**And** submitted players are visually distinct (e.g., checkmark, grayed out)

**Given** all players have submitted
**When** the last submission is received
**Then** round can optionally auto-advance to reveal (admin preference)
**Or** timer continues until expiry

**Given** player views submission row
**When** many players are in game (>10)
**Then** row scrolls horizontally or shows count ("15/18 submitted")

---

### Story 4.5: Timer Expiry & Auto-Advance

As a **player**,
I want **the round to automatically advance when time runs out**,
So that **the game keeps moving even if someone forgets to submit**.

**Acceptance Criteria:**

**Given** countdown timer reaches zero
**When** timer expires
**Then** game state transitions from PLAYING to REVEAL (FR29)
**And** all clients receive the state change
**And** no more submissions are accepted

**Given** some players have not submitted when timer expires
**When** round transitions to reveal
**Then** non-submitters receive 0 points for the round
**And** their status shows "No guess"

**Given** timer expires
**When** server triggers reveal
**Then** transition happens within 500ms of timer end
**And** all clients see reveal simultaneously

---

### Story 4.6: Reveal & Scoring

As a **player**,
I want **to see the correct answer, song info, and my score**,
So that **I get the satisfying payoff of finding out how I did**.

**Acceptance Criteria:**

**Given** round transitions to REVEAL
**When** reveal displays
**Then** correct year is shown prominently (FR30)
**And** song title and artist are displayed
**And** fun_fact from playlist is shown (if available)

**Given** player submitted a guess
**When** reveal displays
**Then** player sees their personal result (FR31):
- Their guessed year
- The correct year
- How many years off they were
- Points earned this round

**Given** player's guess is evaluated
**When** score is calculated (FR32)
**Then** accuracy scoring applies:
- Exact match: 10 points
- Within ±3 years: 5 points
- Within ±5 years: 1 point
- More than 5 years off: 0 points

**Given** player did not submit
**When** reveal displays
**Then** player sees "No guess - 0 points"

**Given** reveal phase completes
**When** admin triggers next round (or auto-advance)
**Then** game returns to PLAYING state with next song

---

## Epic 5: Advanced Scoring & Leaderboard

**Goal:** The game becomes fully competitive with speed bonuses, streak tracking, betting mechanics, and a live leaderboard that updates after each round and shows final standings with streak indicators.

**FRs covered:** FR33, FR34, FR35, FR36, FR37, FR38, FR39, FR40, FR41, FR42

---

### Story 5.1: Speed Bonus Multiplier

As a **player**,
I want **to earn bonus points for submitting quickly**,
So that **fast recognition of songs is rewarded**.

**Acceptance Criteria:**

**Given** player submits a guess
**When** submission timestamp is evaluated
**Then** speed bonus multiplier is applied (FR33):
- 0-10 seconds: 1.5x multiplier
- 10-20 seconds: 1.2x multiplier
- 20-30 seconds: 1.0x (no bonus)

**Given** player earns accuracy points
**When** speed bonus is calculated
**Then** final round score = accuracy_points × speed_multiplier
**And** score is rounded to nearest integer

**Given** player submits at exactly 10.0 seconds
**When** multiplier is determined
**Then** the higher multiplier (1.5x) is applied (inclusive boundary)

**Given** reveal displays
**When** player views their result
**Then** speed bonus is shown (e.g., "5 pts × 1.5x = 8 pts")

---

### Story 5.2: Streak Tracking & Bonuses

As a **player**,
I want **to earn bonus points for consecutive scoring rounds**,
So that **consistent performance is rewarded**.

**Acceptance Criteria:**

**Given** player scores points in a round (>0)
**When** round completes
**Then** player's streak counter increments (FR34)

**Given** player scores 0 points in a round
**When** round completes
**Then** player's streak counter resets to 0

**Given** player reaches streak milestone
**When** streak bonus is evaluated (FR35)
**Then** bonus points are awarded:
- 3 consecutive scoring rounds: +20 bonus
- 5 consecutive scoring rounds: +50 bonus
- 10 consecutive scoring rounds: +100 bonus

**Given** player earns a streak bonus
**When** reveal displays
**Then** streak bonus is shown separately (e.g., "🔥 3-streak bonus: +20!")

**Given** player maintains streak across rounds
**When** leaderboard displays
**Then** current streak is visible (e.g., "🔥3" indicator)

---

### Story 5.3: Betting Mechanic

As a **player**,
I want **to bet double-or-nothing on my guess**,
So that **I can take risks for bigger rewards**.

**Acceptance Criteria:**

**Given** round is in progress (PLAYING phase)
**When** player views the game screen
**Then** a "Bet" toggle or button is visible (FR36)
**And** betting can be activated before submitting

**Given** player activates bet
**When** they submit their guess
**Then** bet flag is sent with submission

**Given** player bet and scored points
**When** score is calculated (FR37)
**Then** points are doubled (after speed bonus)
**And** reveal shows "🎲 Bet paid off! Double points!"

**Given** player bet but scored 0 points
**When** score is calculated
**Then** no additional penalty (0 × 2 = 0)
**And** reveal shows "🎲 Bet lost - no points"

**Given** player activates bet
**When** bet is confirmed
**Then** visual indicator shows bet is active
**And** player can deactivate before submitting

---

### Story 5.4: No Submission Penalty

As a **game system**,
I want **to award 0 points when players don't submit**,
So that **there's incentive to participate in every round**.

**Acceptance Criteria:**

**Given** timer expires
**When** player has not submitted a guess
**Then** player receives 0 points for the round (FR38)
**And** streak is broken (reset to 0)

**Given** player did not submit
**When** reveal displays
**Then** player sees "No guess submitted - 0 points"
**And** streak indicator shows broken streak if applicable

**Given** player had an active bet but didn't submit
**When** round completes
**Then** bet is forfeited (no effect, just 0 points)

---

### Story 5.5: Live Leaderboard

As a **player**,
I want **to see a live leaderboard with everyone's scores**,
So that **I know my standing throughout the game**.

**Acceptance Criteria:**

**Given** game is in progress
**When** player views game screen
**Then** leaderboard is visible showing all players (FR39)
**And** players are ranked by total score (highest first)

**Given** round completes (after reveal)
**When** scores are calculated
**Then** leaderboard updates in real-time (FR40)
**And** update occurs within 1 second (NFR5)

**Given** leaderboard displays
**When** player views rankings
**Then** each entry shows:
- Rank position
- Player name
- Total score
- Current streak indicator (FR42)

**Given** player's rank changes
**When** leaderboard updates
**Then** movement is visually indicated (up/down arrow or animation)

**Given** many players in game (>10)
**When** leaderboard displays
**Then** list is scrollable
**And** current player's position is highlighted/visible

---

### Story 5.6: Final Leaderboard

As a **player**,
I want **to see the final standings when the game ends**,
So that **there's a celebratory conclusion to the competition**.

**Acceptance Criteria:**

**Given** game transitions to END state
**When** final leaderboard displays
**Then** all players see the complete final standings (FR41)
**And** leaderboard remains visible until dismissed

**Given** final leaderboard displays
**When** player views results
**Then** top 3 players are highlighted (podium style)
**And** each player sees their final rank and total score

**Given** final leaderboard displays
**When** player views their own entry
**Then** their entry is visually highlighted
**And** shows their final stats (score, best streak, etc.)

**Given** game has ended
**When** final leaderboard is shown
**Then** admin sees option to "Start New Game"
**And** players see "Thanks for playing!" message

---

## Epic 6: Host Game Control

**Goal:** Host can control game flow during play—stop a song early, skip to next round, adjust volume, or end the game—all from their player screen while playing alongside guests.

**FRs covered:** FR43, FR44, FR45, FR46, FR47, FR48

---

### Story 6.1: Admin Control Bar UI

As a **host playing the game**,
I want **to see admin controls on my player screen**,
So that **I can manage the game without switching devices**.

**Acceptance Criteria:**

**Given** host has joined as participant (via "Participate" button)
**When** host views player screen during gameplay
**Then** an admin control bar is visible at bottom of screen (FR48)
**And** control bar contains: Stop Song, Next Round, Volume, End Game buttons

**Given** regular player views their screen
**When** game is in progress
**Then** no admin controls are visible (FR47)
**And** only the admin-flagged player sees controls

**Given** host views admin control bar
**When** controls are displayed
**Then** buttons are touch-friendly (44x44px minimum)
**And** controls don't obstruct gameplay elements (year selector, timer)

**Given** game is in different phases
**When** controls are displayed
**Then** contextually irrelevant controls are disabled (e.g., "Stop Song" disabled during REVEAL)

---

### Story 6.2: Stop Song Control

As a **host**,
I want **to stop the current song early**,
So that **I can cut off songs that are dragging or that everyone already knows**.

**Acceptance Criteria:**

**Given** round is in PLAYING phase with song playing
**When** host taps "Stop Song"
**Then** audio playback stops immediately (FR43)
**And** `media_player.media_stop` service is called

**Given** host stops song
**When** playback ends
**Then** timer continues counting down
**And** players can still submit guesses
**And** visual indicator shows "Song stopped"

**Given** round is in REVEAL or LOBBY phase
**When** host views controls
**Then** "Stop Song" button is disabled/hidden

---

### Story 6.3: Next Round Control

As a **host**,
I want **to advance to the next round**,
So that **I can keep the game moving when energy is high**.

**Acceptance Criteria:**

**Given** round is in REVEAL phase
**When** host taps "Next Round"
**Then** game transitions to PLAYING with next song (FR44)
**And** all players receive state update

**Given** round is in PLAYING phase
**When** host taps "Next Round"
**Then** current round ends immediately (skips to reveal briefly, then next song)
**Or** confirmation prompt asks "Skip this round?"

**Given** no more songs are available
**When** host taps "Next Round"
**Then** message displays "No more songs - ending game"
**And** game transitions to END state

**Given** host rapidly taps "Next Round"
**When** multiple taps detected
**Then** action is debounced (only one transition per 2 seconds)

---

### Story 6.4: Volume Control

As a **host**,
I want **to adjust the speaker volume during the game**,
So that **I can respond to room conditions without leaving the game**.

**Acceptance Criteria:**

**Given** game is active
**When** host taps "Volume Up" or "Volume Down"
**Then** HA media player volume adjusts immediately (FR45)
**And** `media_player.volume_set` service is called

**Given** volume is adjusted
**When** change is applied
**Then** volume changes in increments (e.g., 10% per tap)
**And** current volume level is briefly displayed

**Given** volume is at maximum (100%)
**When** host taps "Volume Up"
**Then** no change occurs
**And** visual feedback indicates max reached

**Given** volume is at minimum (0%)
**When** host taps "Volume Down"
**Then** no change occurs
**And** visual feedback indicates min reached

**Given** host adjusts volume
**When** command is sent
**Then** adjustment happens within 500ms
**And** other players are not notified (volume is room-level, not per-player)

---

### Story 6.5: End Game Control

As a **host**,
I want **to end the game and show final results**,
So that **I can conclude the game when the party is winding down**.

**Acceptance Criteria:**

**Given** game is in progress (any phase)
**When** host taps "End Game"
**Then** confirmation prompt appears: "End game and show final results?"

**Given** host confirms end game
**When** confirmation is accepted
**Then** game transitions to END state (FR46)
**And** final leaderboard displays for all players
**And** audio playback stops if currently playing

**Given** host cancels end game
**When** confirmation is dismissed
**Then** game continues in current state
**And** no state change occurs

**Given** game ends
**When** END state is reached
**Then** admin control bar is hidden
**And** admin sees "Start New Game" option on final screen

---

### Story 6.6: Start New Game Reset

As a **host**,
I want **to start a completely new game after one ends**,
So that **I can run multiple games at a party with fresh state**.

**Acceptance Criteria:**

**Given** game is in END state (final leaderboard showing)
**When** admin taps "Start New Game"
**Then** full game reset is performed:
- All player sessions are terminated
- All player scores are cleared
- All played song markers are reset
- WebSocket connections are closed
- Game state returns to pre-lobby (setup screen)

**Given** players are viewing final leaderboard
**When** admin initiates new game
**Then** all players see "Game ended - Thanks for playing!"
**And** players must re-scan QR and re-enter name to join new game

**Given** admin returns to setup screen
**When** setup screen displays
**Then** previously selected playlists and media player are remembered (convenience)
**And** admin can modify selections or start immediately

**Given** new game is started
**When** admin clicks "Start Game" on setup
**Then** fresh lobby is created with new game ID
**And** new QR code is generated
**And** played song pool is full (all songs available)

**Given** admin wants to change playlists between games
**When** on setup screen after reset
**Then** admin can select different playlists
**And** new game uses only newly selected playlists

---

## Epic 7: Resilience & Recovery

**Goal:** The system handles problems gracefully—auto-reconnection for dropped connections, game pause when admin disconnects with "Waiting for admin" message, state recovery so nobody loses their place, and clear network error messages.

**FRs covered:** FR49, FR50, FR51, FR52, FR53, FR57, FR58, FR59

---

### Story 7.1: Admin Disconnect & Game Pause

**Implementation Note:** Pay careful attention to race conditions during PAUSED state transitions. Ensure state machine handles concurrent events (e.g., timer expiry during disconnect detection, admin reconnect during pause transition).

As a **player**,
I want **the game to pause when the host disconnects**,
So that **the game doesn't continue without someone in control**.

**Acceptance Criteria:**

**Given** game is in progress (LOBBY, PLAYING, or REVEAL)
**When** admin's WebSocket connection closes unexpectedly
**Then** game transitions to PAUSED state (FR49)
**And** timer stops counting down if in PLAYING phase
**And** audio playback stops

**Given** game is paused due to admin disconnect
**When** players view their screens
**Then** all players see "Waiting for admin..." message (FR50)
**And** game UI is dimmed or shows overlay
**And** players cannot submit guesses while paused

**Given** admin closes browser or loses connection
**When** disconnect is detected
**Then** system waits 5 seconds before pausing (grace period for brief drops)
**And** if reconnection happens within grace period, no pause occurs

**Given** game is paused
**When** pause duration exceeds 5 minutes
**Then** optional: game auto-ends with current standings preserved

---

### Story 7.2: Admin Reconnection

As a **host who got disconnected**,
I want **to rejoin and resume control of the game**,
So that **the party can continue without starting over**.

**Acceptance Criteria:**

**Given** game is paused due to admin disconnect
**When** admin navigates to admin page (`/beatify/admin`)
**Then** admin page shows "Active game paused - Rejoin?" option (FR51)
**And** displays current game state (round number, player count)

**Given** admin clicks "Rejoin"
**When** rejoin flow starts
**Then** admin is prompted to enter their name
**And** must enter the same name they used before

**Given** admin enters their original name
**When** name matches the disconnected admin
**Then** admin reclaims admin status (FR52)
**And** admin rejoins as player with admin controls
**And** game transitions from PAUSED back to previous state

**Given** admin enters a different name
**When** name doesn't match
**Then** error displays: "Enter your original name to reclaim admin"
**And** admin can retry

**Given** admin successfully rejoins
**When** game resumes
**Then** all players see "Admin reconnected - Game resuming!"
**And** timer resumes if in PLAYING phase
**And** audio restarts if song was playing

---

### Story 7.3: Player Auto-Reconnect

As a **player who lost connection**,
I want **to automatically reconnect and resume playing**,
So that **I don't lose my score or miss rounds**.

**Acceptance Criteria:**

**Given** player's WebSocket connection drops
**When** connection is lost
**Then** client automatically attempts reconnection (FR58)
**And** reconnection attempts occur every 2 seconds
**And** player sees "Reconnecting..." indicator

**Given** player reconnects within 60 seconds
**When** connection is restored
**Then** player's session is recovered (FR59)
**And** player's score and streak are preserved
**And** player rejoins current game state (LOBBY/PLAYING/REVEAL)

**Given** player reconnects during PLAYING phase
**When** session is restored
**Then** player sees current round state
**And** can submit guess if timer hasn't expired
**And** if they already submitted, sees "Already submitted" state

**Given** player reconnects after 60 seconds
**When** grace period has expired
**Then** player's session has ended
**And** player must re-enter name to rejoin as new player
**And** previous score is lost

**Given** player is reconnecting
**When** reconnection fails repeatedly (5 attempts)
**Then** player sees "Connection lost. Check your WiFi and refresh."

---

### Story 7.4: Network Error Messages

As a **player on the wrong network**,
I want **to see a clear error message about the connection issue**,
So that **I know how to fix the problem**.

**Acceptance Criteria:**

**Given** player attempts to load player page
**When** device cannot reach the Beatify server
**Then** player sees error: "Can't reach Beatify. Make sure you're on the home WiFi." (FR57)
**And** error includes the expected network name if detectable

**Given** player is on cellular data
**When** they scan the QR code
**Then** page may fail to load or show network error
**And** error message suggests switching to WiFi

**Given** WebSocket connection fails to establish
**When** player tries to join
**Then** error displays: "Connection failed. Check your WiFi connection."
**And** retry button is available

**Given** player sees network error
**When** they switch to correct WiFi
**Then** refreshing the page should work
**And** no stale error state persists

---

### Story 7.5: Game End Full Reset

As a **game system**,
I want **to perform a complete reset when a game ends**,
So that **no stale data affects the next game**.

**Acceptance Criteria:**

**Given** game transitions to END state
**When** end state is reached (via admin "End Game" or natural conclusion)
**Then** system prepares for full reset (FR53)

**Given** admin initiates new game (covered in Epic 6.6)
**When** reset is triggered
**Then** all WebSocket connections are closed gracefully
**And** all player sessions are terminated
**And** all players are disconnected with "Game ended" message

**Given** full reset occurs
**When** game state is cleared
**Then** player list is emptied
**And** all scores are cleared
**And** played song markers are reset
**And** round counter resets to 0
**And** game phase returns to initial state

**Given** reset is complete
**When** admin returns to setup screen
**Then** system is ready for fresh game configuration
**And** no data from previous game persists in game state
