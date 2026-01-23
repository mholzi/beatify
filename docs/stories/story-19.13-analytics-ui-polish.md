# Story 19.13: Analytics UI/UX Polish

## Epic 19: Admin Dashboard Analytics

## User Story

**As a** game administrator,
**I want** a cleaner, more polished analytics interface,
**So that** the dashboard is visually consistent and free of broken elements.

---

## Overview

This story cleans up the Analytics Dashboard UI by removing deprecated elements, fixing styling issues, and improving visual consistency. It removes the Error Rate stat card (deprecated per Story 19.6), the System Health section, and the refresh/last-updated footer. It also fixes the playlist name display to show clean names instead of file paths.

---

## Acceptance Criteria

### AC1: Remove Analytics Subtitle from Header
- [ ] **Given** the analytics page header
- [ ] **When** the page loads
- [ ] **Then** the "Analytics" subtitle text below the logo is removed
- [ ] **And** the header shows only the Beatify wordmark with back link

**Implementation:**
- Remove the `<span class="analytics-subtitle">` element from `analytics.html`
- Remove `.analytics-subtitle` styles from `analytics.css`

### AC2: Remove Error Rate Stat Card
- [ ] **Given** the stat cards section
- [ ] **When** the page loads
- [ ] **Then** the "Error Rate" stat card is removed from the grid
- [ ] **And** only 3 stat cards remain: Total Games, Avg Players, Avg Score

**Implementation:**
- Remove `#stat-error-rate` div from `analytics.html` (lines 67-72)
- Remove error rate rendering logic from `analytics.js` (lines 67-70)
- Update grid CSS in `analytics.css` (lines 88-107) to handle 3 cards:
  - Change desktop breakpoint from `repeat(4, 1fr)` to `repeat(3, 1fr)` for balanced layout
  - Or keep current grid and accept one empty cell on desktop

### AC3: Strip File Path from Playlist Names
- [ ] **Given** the playlist detail cards (Top Playlists section)
- [ ] **When** displaying playlist names
- [ ] **Then** only the clean playlist name is shown (e.g., "80s Hits")
- [ ] **And** the full file path is stripped (not "/config/playlists/80s-hits.json")
- [ ] **And** the .json extension is removed if present

**Implementation:**
- Update `renderPlaylists()` in `analytics.js` (lines 88-113) to extract just the filename
- Use same path-stripping logic already in `openPlaylistModal()` (lines 474-478)
- Strip the `.json` extension using `.replace(/\.json$/i, '')`

### AC4: Verify Playlist Modal Dark Theme
- [ ] **Given** the playlist detail modal popup
- [ ] **When** opened
- [ ] **Then** there is no white background (uses dark theme consistently)
- [ ] **And** content stretches to 100% width of the container
- [ ] **And** table backgrounds are transparent (no white cells)

**Implementation:**
- Verify `.playlist-modal` background is `var(--bg-color, #0a0a0f)` - Already set in CSS line 768
- Verify all table elements have `background: transparent` - Already set in CSS lines 859, 865, 877, 922
- Verify `::backdrop` styling for dark overlay - Already set in CSS lines 773-774
- **Note**: This AC is verification only; no code changes required if dark theme is working correctly

### AC5: Remove Refresh Section
- [ ] **Given** the bottom of the analytics page
- [ ] **When** the page loads
- [ ] **Then** the refresh button is removed
- [ ] **And** the "last updated" timestamp is removed

**Implementation:**
- Remove `.refresh-section` div from `analytics.html`
- Remove `#refresh-btn` and `#last-updated` elements
- Remove `handleRefreshClick()` and `updateLastUpdated()` functions from `analytics.js`
- Remove `.refresh-section`, `.last-updated` styles from `analytics.css`

### AC6: Remove System Health / Error Monitoring Section
- [ ] **Given** the analytics page
- [ ] **When** the page loads
- [ ] **Then** the entire System Health / Error Monitoring section is removed
- [ ] **And** no error panel or health badge is visible

**Implementation:**
- Remove `.error-analytics` section from `analytics.html`
- Remove `renderErrorStats()` function from `analytics.js`
- Remove all error panel related styles from `analytics.css` (lines 376-531)
- Remove `getErrorTypeIcon()` function from `analytics.js`

---

## Technical Implementation Details

### Files to Modify

#### 1. `custom_components/beatify/www/analytics.html`

**Remove:**
```html
<!-- Line 23: Analytics subtitle -->
<span class="analytics-subtitle" data-i18n="analyticsDashboard.subtitle">Analytics</span>

<!-- Lines 67-72: Error Rate stat card -->
<div class="stat-card" id="stat-error-rate">
    <div class="stat-icon" aria-hidden="true">⚡</div>
    <div class="stat-value">--</div>
    <div class="stat-label" data-i18n="analyticsDashboard.errorRate">Error Rate</div>
    <div class="stat-trend"></div>
</div>

<!-- Lines 216-245: System Health section -->
<section class="error-analytics">
    ...entire section...
</section>

<!-- Lines 247-254: Refresh section -->
<div class="refresh-section">
    ...entire section...
</div>
```

#### 2. `custom_components/beatify/www/js/analytics.js`

**Remove:**
- Lines 67-70: Error rate rendering in `renderStats()` (the `updateStatCard('stat-error-rate', ...)` call)
- Lines 79-81: `renderErrorStats()` call in `renderStats()`
- Lines 218-273: `renderErrorStats()` function
- Lines 275-286: `getErrorTypeIcon()` function
- Lines 798-814: `updateLastUpdated()` function
- Lines 841-844: `handleRefreshClick()` function
- Lines 866-869: Refresh button event listener in `init()`
- Lines 877-888: Error expand button event listener in `init()`

**Note:** After removing these functions, also remove the `updateLastUpdated(data.generated_at)` call on line 40 in `loadAnalytics()`.

**Modify:**
- `renderPlaylists()` function to strip file paths from playlist names:

```javascript
function renderPlaylists(playlists) {
    // ... existing code ...
    listEl.innerHTML = playlists.map(function(p) {
        // Strip file path to get clean playlist name
        var displayName = p.name;
        if (displayName && displayName.includes('/')) {
            displayName = displayName.split('/').pop();
        }
        // Remove .json extension if present
        displayName = displayName.replace(/\.json$/i, '');

        var barWidth = (p.play_count / maxCount * 100).toFixed(1);
        return '<div class="playlist-row">' +
            '<div class="playlist-info">' +
                '<span class="playlist-name">' + escapeHtml(displayName) + '</span>' +
                // ... rest unchanged
```

#### 3. `custom_components/beatify/www/css/analytics.css`

**Remove:**
```css
/* Lines 39-45: Analytics subtitle styles */
.analytics-subtitle { ... }

/* Lines 203-219: Refresh section styles */
.refresh-section { ... }
.refresh-icon { ... }
.last-updated { ... }

/* Lines 376-531: Error analytics styles */
.error-analytics { ... }
.error-panel { ... }
/* ... all error panel related styles ... */
```

**Modify (optional for balanced layout):**
```css
/* Line 105: Change 4 columns to 3 columns for stat cards */
/* From: grid-template-columns: repeat(4, 1fr); */
/* To:   grid-template-columns: repeat(3, 1fr); */
```

---

## UI Before/After

### Before (Current State)
```
┌─────────────────────────────────────────────────┐
│  ← Back to Admin                                │
│                                                 │
│  Beatify                                        │
│  Analytics  ← REMOVE THIS                       │
├─────────────────────────────────────────────────┤
│  [7 Days] [30 Days] [90 Days] [All Time]        │
├─────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│ │🎮       │ │👥       │ │🏆       │ │⚡       │ │
│ │ 42      │ │ 4.2     │ │ 156     │ │ 0.5%    │ │
│ │Total    │ │Avg      │ │Avg      │ │Error    │ │ ← REMOVE
│ │Games    │ │Players  │ │Score    │ │Rate     │ │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
├─────────────────────────────────────────────────┤
│  🎵 Top Playlists                               │
│  /config/beatify/playlists/80s-hits.json  ← FIX │
├─────────────────────────────────────────────────┤
│  🔧 System Health                               │ ← REMOVE
│  [Error panel...]                               │
├─────────────────────────────────────────────────┤
│  [🔄 Refresh]  Updated: 14:32                   │ ← REMOVE
└─────────────────────────────────────────────────┘
```

### After (Target State)
```
┌─────────────────────────────────────────────────┐
│  ← Back to Admin                                │
│                                                 │
│  Beatify                                        │
├─────────────────────────────────────────────────┤
│  [7 Days] [30 Days] [90 Days] [All Time]        │
├─────────────────────────────────────────────────┤
│ ┌───────────────┐ ┌───────────────┐ ┌───────────┐
│ │🎮             │ │👥             │ │🏆         │
│ │ 42            │ │ 4.2           │ │ 156       │
│ │Total Games    │ │Avg Players    │ │Avg Score  │
│ └───────────────┘ └───────────────┘ └───────────┘
├─────────────────────────────────────────────────┤
│  🎵 Top Playlists                               │
│  80s Hits                                   ← ✓ │
├─────────────────────────────────────────────────┤
│  🎵 Song Statistics                             │
│  [Song cards and playlist grid...]              │
├─────────────────────────────────────────────────┤
│  📈 Games Over Time                             │
│  [Chart...]                                     │
└─────────────────────────────────────────────────┘
```

---

## Definition of Done

- [ ] Analytics subtitle removed from header
- [ ] Error Rate stat card removed
- [ ] Stat cards grid updated to 3 columns on desktop (optional but recommended)
- [ ] System Health / Error Monitoring section removed
- [ ] Refresh button and last updated timestamp removed
- [ ] `updateLastUpdated()` call removed from `loadAnalytics()`
- [ ] Playlist names display clean names (not file paths, no .json extension)
- [ ] Modal uses dark theme consistently (no white backgrounds) - verify only
- [ ] All removed CSS classes cleaned up (.analytics-subtitle, .refresh-section, .error-analytics, etc.)
- [ ] All removed JS functions cleaned up (renderErrorStats, getErrorTypeIcon, updateLastUpdated, handleRefreshClick)
- [ ] All removed event listeners cleaned up (refresh button, error expand button)
- [ ] No console errors on page load
- [ ] Page renders correctly on mobile and desktop
- [ ] All existing functionality still works (period filtering, song stats, chart)

---

## Story Points: 3

## Priority: High (Removes broken/deprecated UI elements)

## Dependencies
- Story 19.7 (Song Statistics) - Already complete
- Story 19.6 (Error Monitoring) - Deprecated, being removed

---

## Testing Checklist

1. [ ] Load analytics page - verify no subtitle shown
2. [ ] Verify only 3 stat cards displayed (no Error Rate)
3. [ ] Verify Top Playlists shows clean names (not paths)
4. [ ] Open playlist modal - verify dark theme throughout
5. [ ] Verify no refresh button or last updated text
6. [ ] Verify no System Health section
7. [ ] Test period filter buttons still work
8. [ ] Test song statistics cards still work
9. [ ] Test playlist modal search and sorting
10. [ ] Test on mobile viewport
11. [ ] Check browser console for errors
