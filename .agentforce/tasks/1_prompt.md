# Task #1: UI Review — Beatify Frontend

## Project: Beatify3
- **Path:** /Volumes/extern/Beatify3
- **Git:** https://github.com/mholzi/beatify.git (main)
- **Type:** Home Assistant Custom Component — Multiplayer Music Trivia Quiz

## Priority: HIGH

## Agent: Reviewer (Code Review / Quality)

## Objective
Conduct a comprehensive UI/UX review of the Beatify frontend. The game is played on mobile (guests scan QR code), and there's an admin dashboard for the host.

## Scope
Review all frontend views:
- **player.html** + player.js — Guest game interface (mobile-first)
- **dashboard.html** + dashboard.js + dashboard.css — Host control panel
- **admin.html** + admin.js — Admin settings
- **launcher.html** — Game launcher / QR flow
- **analytics.html** + analytics.js + analytics.css — Game stats

Supporting files:
- **css/styles.css** — Main styles
- **js/i18n.js** — Internationalization
- **js/utils.js** — Shared utilities
- **js/playlist-requests.js** — Playlist handling

## Review Criteria
1. **Visual Consistency** — Design language, spacing, colors, typography
2. **Mobile Responsiveness** — Player is mobile-first; does it work well on various screen sizes?
3. **Accessibility (a11y)** — Semantic HTML, ARIA labels, contrast ratios, keyboard nav
4. **Performance** — Asset sizes, render blocking, unnecessary reflows
5. **Code Quality** — DRY, naming conventions, separation of concerns
6. **UX Flow** — Is the scan→play flow smooth? Any friction points?

## Deliverables
1. Structured findings report (this file, updated with results)
2. List of issues with severity (critical/major/minor/suggestion)
3. If code changes needed → create sub-task for Coder agent

## Workflow
- After completing review → set status to `review`
- If sub-tasks needed (e.g., Coder for fixes) → create them with parent_task_id=1
- Sub-task agents must acknowledge before owner proceeds
- Once all sub-tasks resolved → set status to `pending_feedback` (awaits client approval)

---
## Agent System Instructions

You are the **Reviewer** agent (Code Review).
Working directory: /Volumes/extern/Beatify3

### Task Management
If you need help from another agent (e.g., Coder for fixes, Tester for tests):
- Create a sub-task by writing a JSON file to: /Volumes/extern/Beatify3/.agentforce/tasks/1_subtask_request.json
- Format: {"title": "...", "description": "...", "agent": "Coder|Tester|Reviewer|Docs|DevOps|Researcher|Debugger", "priority": "low|medium|high|critical"}
- The heartbeat will pick it up and create the sub-task.

### Deliverables
1. Write your findings/solution to: /Volumes/extern/Beatify3/.agentforce/tasks/1_solution.md
2. If no sub-tasks needed, the task will move to pending_feedback for client review.

