---
stepsCompleted: [1, 2, 3, 4, 6, 7, 8, 9, 10, 11]
lastStep: 11
status: complete
inputDocuments:
  - '_bmad-output/analysis/brainstorming-session-2025-12-16.md'
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 1
  projectDocs: 0
workflowType: 'prd'
lastStep: 0
project_name: 'Beatify'
user_name: 'Markusholzhaeuser'
date: '2025-12-17'
---

# Product Requirements Document - Beatify

**Author:** Markusholzhaeuser
**Date:** 2025-12-17

## Executive Summary

Beatify is a Home Assistant HACS integration that transforms any HA-equipped home into a crowd-scale music year-guessing game venue.

**For hosts:** Install once via HACS, control everything through your existing Home Assistant setup—game flow, playlists, audio through your connected speakers.

**For guests:** Scan a QR code, type your name, play. No app download. No account creation. No Home Assistant required. Just a browser.

### The Problem

Picture this: 30 people at a party, someone suggests a music game. With existing solutions like Hitster, the next 10 minutes is chaos—"download this app," "create an account," "what's the code again?" Half the group loses interest before the first song plays.

Beatify eliminates that friction entirely. QR code on the TV, 30 seconds later, everyone's in.

**Specific problems solved:**
1. **Player limits** — Hitster caps at 10; Beatify scales from 2 to 200+
2. **Access friction** — Hitster requires app + account; Beatify needs only a browser
3. **Audio fragmentation** — Hitster plays on individual phones; Beatify uses your home audio system

### What Makes This Special

The irreducible core is the game loop: join → song plays → guess year → reveal → leaderboard. This must work flawlessly before any enhancement matters.

Frictionless access is a **design principle**, not a shortcut:
- No accounts means no passwords, no data storage, no GDPR concerns
- No app means no version mismatches, no store approvals, no platform lock-in
- Browser-only means it works on any device guests already have in their pocket

The gamification layers (speed bonuses, streaks, betting, awards) amplify engagement but are secondary to the core promise: **anyone can play in seconds**.

## Project Classification

| Dimension | Value |
|-----------|-------|
| **Technical Type** | web_app (browser-based player UI) + HA integration backend |
| **Domain** | general (entertainment/party game) |
| **Complexity** | Low |
| **Project Context** | Greenfield |

## Success Criteria

### User Success

| Metric | Target |
|--------|--------|
| Minimum players per game | 5+ participants |
| Join friction | Fast enough that no one abandons the process |
| Engagement | Players stay for multiple rounds (time spent) |
| Word of mouth | At least one guest asks how to get Beatify for their own setup |

The host success moment: guests are playing within seconds of scanning, energy stays high throughout, and someone asks "what IS this?" afterward.

### Business Success

| Metric | Target |
|--------|--------|
| HACS downloads | 100 downloads = success |
| Community presence | Mentions on HA forums, Reddit r/homeassistant |
| Recognition | Known as a quality HA party game integration |

This is a side project with reach—not a startup, but something the HA community recognizes and adopts.

### Technical Success

| Metric | Target |
|--------|--------|
| HA compatibility | Works on current HA versions without breaking |
| Documentation | Clear enough for self-service installation |
| Error handling | Fails gracefully (bad playlist, Music Assistant offline, etc.) |
| Reliability | Stable enough that strangers can depend on it |

### Measurable Outcomes

- **Launch:** Publicly available on HACS with documentation
- **Traction:** 100 downloads within first year
- **Quality bar:** Zero "it crashed my HA" issues reported

## Product Scope

### MVP - Minimum Viable Product

The MVP is a complete, polished party game—not a skeleton:

**Core Experience:**
- Game loop: join → song plays → guess year → reveal → leaderboard
- QR code join flow (scan → name → play)
- Admin controls: start game, stop song, next round, volume

**Scoring System (full implementation):**
- Accuracy scoring: exact (10pts), ±3 years (5pts), ±5 years (1pt)
- Speed bonuses: 1.5x (0-10s), 1.2x (10-20s), 1.0x (20-30s)
- Streak bonuses: 3 in a row (+20), 5 (+50), 10 (+100)
- Betting: double-or-nothing option during countdown

**Technical Foundation:**
- HACS integration
- Music Assistant for playlist/playback
- HA media player output
- Local web server for player interface

### Growth Features (Post-MVP)

- Dramatic reveal sequence ("It's from the 80s... It's 1985!")
- End-game podium (🥇🥈🥉) with rank movement animation
- Awards showcase: Longest Streak, Fastest Guesser, Biggest Risk Taker, Most Exact Hits
- Spectator mode

### Excluded (Not This Product)

These features are out of scope permanently, not deferred:

- Team mode
- Smart home integration (lights/sounds reacting to game)
- Tournament/multi-game mode
- User accounts/history

## User Journeys

### Journey 1: Marcus — First-Time Installer

Marcus is a Home Assistant enthusiast who's always looking for ways to make his smart home the center of social gatherings. He sees Beatify mentioned on Reddit's r/homeassistant and thinks "this would be perfect for New Year's Eve."

He finds Beatify in HACS, installs it, and adds the integration via Settings → Integrations. He already has Music Assistant running his Spotify playlists, so the integration detects it automatically. He creates a test playlist JSON with 10 songs—just artist, year, and Spotify URI for each track.

He opens the Beatify admin page—just a local URL, no login needed. From there, he selects his test playlist, picks his living room speaker, and hits "Start Game." The QR code appears. He prints the page and sticks it on the fridge for the party. He scans the QR with his phone, enters "Test Player," and the lobby shows him waiting. He starts the game from the admin page, a song plays through his living room speakers, and he guesses the year. It works. He's ready for the party.

### Journey 2: Sarah — Host Running a Game

Sarah has hosted three Beatify nights already. Tonight's her birthday party—25 people expected.

An hour before guests arrive, she opens the Beatify admin page on her iPhone. She selects three playlist JSONs (80s hits, 90s pop, 2000s bangers), picks her living room Sonos, and hits "Start Game"—this creates the lobby and generates the QR code. She prints the QR page and sticks it on the living room wall.

Guests start arriving. Some scan the wall QR, others get shown it by friends who are already in—the QR is right there on every player's screen. Within 10 minutes, 18 people are in the lobby.

Sarah clicks "Participate" on her phone. She enters her name and transitions to the player view—but with an "admin" badge visible to everyone and admin controls on her screen. She can see the lobby filling up, same as other players, but she has the "Start Game" button they don't.

When everyone's ready, she taps "Start Game." The first song blasts through the living room speakers. She guesses along with everyone else, but her screen also shows admin controls (stop song, next round, volume, end game).

After 15 rounds, she hits "End Game." Everyone sees the final leaderboard. Her cousin Erik won. The party continues.

### Journey 3: Tom — Player Joining

Tom arrives at Sarah's birthday party. He doesn't know what Beatify is, doesn't have Home Assistant, and doesn't care about smart home stuff. He just wants a drink and good conversation.

Someone points at the QR code on the wall. "Scan that, it's a music game." Tom pulls out his Android phone, opens the camera, scans. A webpage loads instantly—no app store, no download, no account creation. Just a text field: "Enter your name."

He types "Tom" and taps Join. He's in the lobby. He sees 15 other names already waiting, including "Sarah (Admin)" with a badge. The QR code is right there on his screen too—he shows it to his girlfriend who just walked in.

Sarah starts the game. Tom's screen shows an album cover and a countdown timer. He has no idea what song this is, but he can hear it playing through the living room speakers. He drags the year slider to 1987 and taps Submit. He sees a checkmark and "Waiting for others..."—a scrolling row shows who else has submitted.

The reveal: 1984 — "Wake Me Up Before You Go-Go" by Wham! Tom was 3 years off—he gets 5 points. The leaderboard updates. He's in 8th place. He's hooked.

15 rounds later, he's in 4th. He lost to Sarah's cousin Erik but beat his girlfriend. He asks Sarah, "What IS this? Can I get it for my place?"

### Journey 4: Lisa — Late Joiner

Lisa arrives 30 minutes late to Sarah's party. The game is already on round 8. She can hear music playing and see people staring at their phones, laughing.

Her friend Tom waves her over. "Scan this!" He shows her his phone screen—there's a QR code right there with an "Invite friends" label. Lisa scans it with her iPhone. A webpage loads. Name field. She types "Lisa" and taps Join.

She lands directly in the game—not the lobby, because the game is already running. The current round is in progress: she sees an album cover, a countdown timer with 12 seconds left. She quickly drags to 1995 and submits.

She got it wrong—it was 2001. Zero points. But she's on the leaderboard now, in last place. She doesn't care. By round 15, she's climbed to 11th. She saw the final reveal and the podium, same as everyone else.

She never felt "late." She just jumped in.

### Journey 5: Sarah — Admin During Gameplay

The game is running. Sarah is on round 6, playing alongside 18 other players on her iPhone.

Her screen looks almost like everyone else's: album cover, countdown timer, year selector. But at the bottom, she has an admin control bar that others don't see: **Stop Song** | **Next Round** | **Volume +/-** | **End Game**.

A song starts. It's a deep cut from 1978 that nobody recognizes. The countdown hits 15 seconds and people are still guessing wildly. Sarah makes her own guess (1982—close enough for 5 points), then watches the "submitted" row fill up. When only 2 people haven't submitted, she decides to let the timer run out rather than force it.

Timer hits zero. The reveal plays. People groan—it was a one-hit wonder. Sarah taps **Next Round** to keep the energy moving.

Round 9. A song starts but the speakers are too quiet—someone turned the volume down earlier for a conversation. Sarah taps **Volume +** twice without leaving the game screen. The room hears the adjustment immediately.

Round 12. An obscure track nobody knows. The energy is dying. Sarah taps **Stop Song** halfway through the countdown to cut it short, then immediately hits **Next Round**. Momentum restored.

Round 15. Sarah decides that's enough. She taps **End Game**. The final leaderboard appears on everyone's screen. Her admin bar disappears—she's just a player now, viewing results with everyone else.

### Journey 6: Marcus — When Things Go Wrong

Marcus is setting up Beatify for the first time, but his setup isn't perfect.

He installs the HACS integration and opens the admin page. Instead of playlist options, he sees: "Music Assistant not found. Beatify requires Music Assistant to play songs. [Setup Guide]" He clicks the link, realizes he never installed Music Assistant, and fixes it. He reloads—now the admin page shows his media players.

He selects his living room speaker and hits "Start Game." Error: "No playlists found. Add playlist JSON files to [folder path]. [How to create playlists]" He checks the docs, creates a quick 5-song test playlist, drops it in the folder. Refresh—now he sees his playlist.

Later, at the party. Tom's girlfriend tries to scan the QR but she's still on cellular, not the home WiFi. Her browser spins, then shows: "Can't reach Beatify. Make sure you're on the home WiFi." She switches networks, scans again, and she's in.

Mid-game, Sarah's phone dies. The game pauses—everyone's screen shows "Waiting for admin..." Sarah grabs a charger, opens the admin page on her phone, sees the active game, hits "Rejoin," enters her name "Sarah," and she's back with admin controls. The game resumes.

Round 10. Everyone's arguing about the song and forgets to submit. Timer hits zero. The reveal plays automatically—it was 1992. Nobody gets points. The game continues to round 11.

### Journey Requirements Summary

| Capability | Revealed By |
|------------|-------------|
| HACS installation + HA integration setup | Marcus (Installer) |
| Music Assistant auto-detection | Marcus (Installer) |
| Playlist JSON format + documentation | Marcus (Installer) |
| Standalone admin web page (no auth, mobile-first) | Marcus, Sarah |
| Admin page state detection (no game → setup, active game → Rejoin) | Marcus (Error Recovery) |
| Media player selection | Sarah (Host) |
| QR code page (print-friendly) | Marcus, Sarah |
| Admin flow: playlists → media player → Start Game → Participate | Sarah (Host) |
| Admin badge visible in lobby/game | Sarah, Tom |
| Admin controls in player view | Sarah (Admin During Gameplay) |
| Controls: Stop Song, Next Round, Volume, End Game | Sarah (Admin During Gameplay) |
| QR code on player screen with "Invite friends" label | Tom, Lisa |
| Name-only join (no account) | Tom (Player) |
| Lobby view with player list | Tom (Player) |
| Game screen: album cover, timer, year selector | Tom (Player) |
| Submit confirmation + "who's submitted" row | Tom (Player) |
| Reveal: year + song info (MVP) | Tom (Player) |
| Leaderboard updates | Tom, Lisa |
| Late join support (mid-game entry) | Lisa (Late Joiner) |
| Late joiners skip lobby, land in current round | Lisa (Late Joiner) |
| Real-time volume control via HA | Sarah (Admin During Gameplay) |
| Error states with helpful messages + links | Marcus (Error Recovery) |
| Admin reconnect via admin page | Marcus (Error Recovery) |
| Game pause when admin disconnects | Marcus (Error Recovery) |

### Edge Case Handling

| Scenario | Behavior |
|----------|----------|
| Music Assistant not configured | Admin page shows error + setup guide link |
| No playlists found | Admin page shows error + how-to link |
| Media player unavailable | Admin page shows error + troubleshooting hint |
| Player on wrong network | Player page shows "Can't reach Beatify" + WiFi hint |
| Duplicate name attempted | Block save, prompt "Name taken, choose another" |
| Admin disconnects mid-game | Game pauses, all players see "Waiting for admin..." |
| Admin reconnects | Admin page → Rejoin → same name → regains controls |
| Timer expires, no submissions | Auto-reveal, 0 points for all, game continues |
| End Game pressed | Full reset—all players disconnected, admin returns to setup, new game requires fresh joins |

## Innovation & Novel Patterns

### Detected Innovation: Smart Home as Entertainment Platform

Beatify represents a category-defining experiment: **the first party game built as a Home Assistant integration.**

While HA has thousands of integrations for automation, monitoring, and control, Beatify pioneers using the smart home as a **social entertainment platform**. This isn't just "a game that happens to run on HA"—it's a proof of concept that HA's device ecosystem (media players, displays, speakers) can power interactive group experiences.

### Why Home Assistant?

The innovation isn't the game mechanics (year-guessing games exist). The innovation is the delivery platform:

- **Device integration:** Centralized audio through existing HA media players—no Bluetooth pairing, no "everyone download the app," no fighting over who controls the speaker
- **Zero infrastructure:** Hosts already have HA running. Beatify adds entertainment without adding hardware
- **Ecosystem leverage:** HACS distribution means instant access to HA's engaged, technical user base

### Category Potential

If Beatify succeeds, it may validate "HA as entertainment platform" as a category:
- Trivia nights with HA-controlled buzzers
- Karaoke with scoring and queue management
- Party games that integrate lights and audio

This is speculative—Beatify's success (or failure) will provide data.

### Validation Approach

The innovation hypothesis is validated if:
- **Adoption:** 100+ HACS downloads (proves demand exists)
- **Community response:** Mentions on r/homeassistant, HA forums (proves resonance)
- **Follow-on interest:** Questions like "can you add X game mode?" or "I want to build something similar"

### Risk Mitigation

If "HA as entertainment platform" doesn't resonate:
- Beatify still works as a personal project (original goal)
- The game mechanics are sound regardless of platform
- No sunk cost in proprietary infrastructure—it's just a HACS integration

## Web Application Specific Requirements

### Project-Type Overview

Beatify is a **Multi-Page Application (MPA)** serving two distinct web interfaces:
- **Admin page:** Game setup, configuration, and rejoin functionality
- **Player page:** Lobby, game screen, and results

Both interfaces are mobile-first, served locally from the Home Assistant integration, with no external hosting or CDN requirements.

### Browser Support Matrix

| Browser | Support Level | Notes |
|---------|---------------|-------|
| Chrome (Android) | Full | Primary target for players |
| Safari (iOS) | Full | Primary target for players |
| Firefox (Mobile) | Full | Secondary support |
| Edge (Mobile) | Full | Secondary support |
| Desktop browsers | Functional | Admin may use desktop, players unlikely |

**No legacy browser support required.** Modern browsers only (ES6+, CSS Grid, WebSocket API).

### Responsive Design

| Breakpoint | Target |
|------------|--------|
| Mobile (320-480px) | Primary—all player interactions |
| Tablet (481-768px) | Supported—larger touch targets |
| Desktop (769px+) | Functional—admin convenience only |

**Design approach:** Mobile-first. All critical interactions (year selector, submit, leaderboard) must be thumb-friendly on a phone screen held in one hand.

### Real-Time Architecture

**Technology:** WebSockets

**Real-time requirements:**
| Feature | Direction | Latency Target |
|---------|-----------|----------------|
| Lobby updates (player joins) | Server → All clients | < 500ms |
| Game state sync (round start, timer) | Server → All clients | < 200ms |
| Submit confirmation | Client → Server | Immediate |
| "Who's submitted" updates | Server → All clients | < 500ms |
| Leaderboard updates | Server → All clients | < 1s |
| Admin controls (stop, next, volume) | Client → Server → HA | < 500ms |

**Connection handling:**
- Auto-reconnect on connection drop
- Game state recovery on reconnect (player rejoins current round)
- Admin reconnect via admin page flow

### Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Initial page load | < 2s | Don't lose players waiting |
| Time to interactive | < 3s | QR scan → playing should be fast |
| WebSocket latency | < 200ms | Game feel responsive |
| Year selector responsiveness | 60fps | Smooth drag interaction |

**No offline support required.** Game requires active network connection to HA.

### SEO Strategy

**Not applicable.** Beatify is a local network application:
- Not indexed by search engines
- No public URLs
- No meta tags or structured data needed

### Accessibility Level

**No formal WCAG compliance required.**

Basic usability considerations:
- Touch targets minimum 44x44px
- Sufficient color contrast for readability
- Year selector usable with simple tap/drag
- No reliance on audio-only feedback (visual confirmation on submit)

### Implementation Considerations

**Local network constraints:**
- All traffic stays on LAN (no internet required during gameplay)
- URL must be accessible from any device on home WiFi
- QR code contains local IP/hostname—may change if HA restarts

**HA integration constraints:**
- Web server runs within HA Python environment
- WebSocket server must coexist with HA's own WebSocket
- Media player control via HA service calls

## Scoping Validation & Risk Analysis

### MVP Strategy Confirmation

**MVP Philosophy:** Experience MVP — Deliver the complete party game experience with full scoring system. Not a skeleton, but not overbuilt.

**Scope Assessment:** Simple MVP
- Solo developer
- Lean feature set with clear boundaries
- Well-defined "done" criteria (core loop + full scoring)

**MVP Validation Criteria:**
The MVP is complete when all 6 user journeys work as documented:
1. First-time installer can set up and test
2. Host can run a full game on one device
3. Player can join and play via QR
4. Late joiner can enter mid-game
5. Admin controls work during gameplay
6. Error states show helpful messages

### Risk Analysis

**Technical Risks:**

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| WebSocket complexity in HA environment | Medium | High | Start with WebSocket prototype early; fallback to polling if needed |
| Music Assistant integration issues | Low | High | Test MA integration first; document minimum MA version |
| Mobile browser inconsistencies | Medium | Medium | Test on iOS Safari + Android Chrome early; keep UI simple |

**Market Risks:**

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| HA users don't want party games | Medium | High | Validate with r/homeassistant post before heavy development |
| Playlist JSON format too complex | Medium | Medium | Provide sample playlists; clear documentation |
| Competition from similar tools | Low | Low | First-mover in HA space; niche is small |

**Resource Risks:**

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Solo dev burnout | Medium | High | Keep MVP lean; celebrate milestones |
| Scope creep | Medium | Medium | Excluded list is permanent; resist feature requests until post-MVP |
| Time availability | High | Medium | No deadline pressure; ship when ready |

### Contingency: Minimum Viable Minimum

If resources are even more constrained than expected, the absolute minimum shippable product is:

- Core game loop only (no speed bonus, no streaks, no betting)
- Basic scoring (accuracy only: 10/5/1)
- Single playlist support
- No late-join support

This "MVP of the MVP" proves the concept but loses the gamification that makes it fun. Only use as last resort.

## Functional Requirements

### Installation & Setup

- FR1: Admin can install Beatify via HACS
- FR2: Admin can add Beatify integration via HA Settings → Integrations
- FR3: System can detect Music Assistant installation status
- FR4: System can display available HA media players for selection
- FR5: System can detect and list available playlist JSON files
- FR6: Admin can access standalone admin web page without authentication

### Game Configuration

- FR7: Admin can select one or more playlist files for a game session
- FR8: Admin can select which HA media player to use for audio output
- FR9: Admin can start a new game (creating lobby and QR code)
- FR10: Admin can view QR code page in print-friendly format
- FR11: System can generate QR code containing player join URL

### Player Onboarding

- FR12: Player can scan QR code to open player web page
- FR13: Player can enter a display name to join the game
- FR14: System can reject duplicate player names with helpful message
- FR15: Player can view QR code on their screen to invite others
- FR16: Late-joining player can enter mid-game directly into current round

### Lobby Management

- FR17: Player can view list of all players in lobby
- FR18: Player can see which player is the admin (badge indicator)
- FR19: Admin can see real-time lobby updates as players join
- FR20: Admin can click "Participate" to join as player with admin privileges
- FR21: Admin can start gameplay when ready (from player view with admin controls)

### Gameplay — Core Loop

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

### Gameplay — Scoring

- FR32: System can calculate accuracy score (exact=10, ±3yrs=5, ±5yrs=1, else=0)
- FR33: System can apply speed bonus multiplier (1.5x for 0-10s, 1.2x for 10-20s, 1.0x for 20-30s)
- FR34: System can track player streaks (consecutive scoring rounds)
- FR35: System can award streak bonuses (+20 at 3, +50 at 5, +100 at 10)
- FR36: Player can choose to bet (double-or-nothing) during countdown
- FR37: System can apply bet multiplier to round score
- FR38: System can award 0 points when player doesn't submit before timer

### Leaderboard

- FR39: Player can view live leaderboard with all player scores
- FR40: System can update leaderboard in real-time after each round
- FR41: Player can view final leaderboard when game ends
- FR42: Player can see streak status indicators on leaderboard

### Admin Controls (During Gameplay)

- FR43: Admin can stop current song early
- FR44: Admin can advance to next round
- FR45: Admin can adjust volume up/down (controlling HA media player)
- FR46: Admin can end game (triggering final leaderboard)
- FR47: Admin controls are visible only to admin-flagged player
- FR48: Admin controls are accessible from player screen (no device switching)

### Session Management

- FR49: System can pause game when admin disconnects
- FR50: Player can see "Waiting for admin..." when game is paused
- FR51: Admin can rejoin active game via admin page
- FR52: Admin can reclaim admin status by rejoining with same name
- FR53: System can perform full reset when game ends (all players disconnected)

### Error Handling

- FR54: System can display error when Music Assistant not configured (with setup guide link)
- FR55: System can display error when no playlists found (with how-to link)
- FR56: System can display error when media player unavailable
- FR57: Player can see error when not on correct network (with WiFi hint)
- FR58: System can auto-reconnect player on connection drop
- FR59: System can recover player state on reconnection (rejoin current round)

## Non-Functional Requirements

### Performance

| Metric | Target | Rationale |
|--------|--------|-----------|
| Page load time | < 2 seconds | Players shouldn't wait after QR scan |
| WebSocket latency | < 200ms | Game state updates feel instant |
| Year selector responsiveness | 60fps | Smooth drag interaction |
| Lobby update delay | < 500ms | New players appear quickly |
| Leaderboard update | < 1 second | Results feel real-time |

**Degradation behavior:** If network is slow, game should remain playable with delayed updates rather than freezing or crashing.

### Scalability

| Metric | Target |
|--------|--------|
| Maximum concurrent players | 20 per game session |
| Maximum active games | 1 (single game per HA instance) |

**Design constraint:** This is a party game for a single household. Enterprise-scale multi-tenancy is explicitly out of scope.

### Reliability

| Metric | Target | Rationale |
|--------|--------|-----------|
| Game completion rate | 99% | Once started, games should finish without crashes |
| Reconnection success | 95% | Players/admin should be able to rejoin after disconnects |
| Graceful degradation | Required | Errors should pause game, not crash it |

**Critical reliability scenarios:**
- Admin disconnect → Game pauses (not crashes)
- Player disconnect → Player can rejoin (state preserved)
- Music Assistant unavailable mid-game → Clear error, game paused
- HA restart mid-game → Game state lost (acceptable, document this limitation)

### Integration

**Home Assistant:**
| Requirement | Specification |
|-------------|---------------|
| Minimum HA version | 2025.11 |
| Installation method | HACS |
| Configuration | Via HA Settings → Integrations |

**Music Assistant:**
| Requirement | Specification |
|-------------|---------------|
| Dependency | Required (not optional) |
| Detection | Auto-detect on admin page load |
| Error handling | Clear message + setup guide if not found |

**Media Player:**
| Requirement | Specification |
|-------------|---------------|
| Supported types | Any HA media_player entity |
| Volume control | Via HA service calls |
| Playback control | Play, stop via HA service calls |

### Security

**Intentional non-requirements:**

Beatify deliberately has NO security features:
- No authentication (frictionless access is a design principle)
- No user accounts (no data to protect)
- No encryption (local network only, no sensitive data)
- No authorization (anyone on local network can join)

**This is by design, not a gap.** Security theater would add friction without protecting anything valuable.

**Network assumption:** Beatify assumes the home network is trusted. If untrusted users have network access, that's a network security issue, not a Beatify issue.

### Accessibility

**No formal WCAG compliance required.**

Basic usability only:
- Touch targets: 44x44px minimum
- Color contrast: Readable in typical indoor lighting
- No audio-only feedback: Visual confirmation for all actions

