# Beatify Playlist Enrichment Runbook

Complete guide for extracting Spotify playlists and enriching them with metadata and cross-platform streaming URIs.

## Overview

This runbook documents the process of adding a new playlist to Beatify, from extracting songs from a Spotify playlist to creating a fully enriched JSON file with metadata and cross-platform URIs.

**Time estimate:** 2-3 hours for a 100-track playlist
**Success rate:** 80-95% automatic enrichment

## Prerequisites

### Required Tools
- Python 3.8+
- `requests` library for API calls
- Access to the internet (for Odesli API)

### Required Scripts
All scripts are located in the `scripts/` directory:
- `enrich_playlists.py` - Adds Apple Music and YouTube Music URIs
- `add_metadata.py` - Template for metadata enrichment
- `complete_all_metadata.py` - Bulk metadata enrichment

### API Limitations
- **Spotify API:** Currently unavailable for new app registrations (as of 2026)
- **Odesli API:** 6-second rate limit between requests (free tier)
- **WebFetch:** No authentication, works with public Spotify embed players

## Process Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Extract Songs from Spotify Playlist                      │
│    ├─ Find playlist embed URL                               │
│    └─ Extract all track data                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Create Initial JSON Structure                            │
│    ├─ Format track data                                     │
│    └─ Save to playlists directory                           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Enrich with Metadata                                     │
│    ├─ Add chart positions                                   │
│    ├─ Add certifications                                    │
│    ├─ Add alternative artists                               │
│    └─ Add fun facts (EN/DE/ES)                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Add Streaming URIs                                       │
│    ├─ Apple Music URIs via Odesli                           │
│    └─ YouTube Music URIs via Odesli                         │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Commit and Close Issue                                   │
└─────────────────────────────────────────────────────────────┘
```

## Step 1: Extract Songs from Spotify Playlist

### Option A: Using WebFetch (Recommended)

Since Spotify API is unavailable for new apps, use WebFetch to extract from the embed player.

1. **Get the Spotify playlist URL:**
   ```
   Example: https://open.spotify.com/playlist/37i9dQZF1DX9UIxCLpCN0g
   ```

2. **Use WebFetch to extract all tracks:**

   The Spotify embed player exposes all track data in a single request. Use the Claude Code WebFetch tool with this prompt:

   ```
   Extract all tracks from this Spotify playlist. For each track, provide:
   - Track name
   - Artist name(s)
   - Spotify URI
   - Year (if available)

   Format as a structured list.
   ```

3. **Expected output:**
   ```
   1. La Bouche - Be My Lover (1995)
      spotify:track:3vSn1frPgFcRXrjWOfhMLl

   2. Real McCoy - Another Night (1994)
      spotify:track:3DL3P7ZMOu5gApQwaUtseF
   ...
   ```

### Option B: Using Playwright (If Available)

If you have Playwright configured:

```bash
# Navigate to the playlist
playwright navigate https://open.spotify.com/playlist/[PLAYLIST_ID]

# Scroll to load all tracks
playwright evaluate "window.scrollTo(0, document.body.scrollHeight)"

# Extract track data
playwright get_visible_text
```

**Note:** Spotify uses virtualization, so you may need multiple scroll sessions.

### Option C: Manual CSV Export

If automation fails, manually copy tracks from Spotify and use the batch import script.

## Step 2: Create Initial JSON Structure

### 2.1 Create the JSON File

Create a new file in `custom_components/beatify/playlists/[playlist-name].json`:

```json
{
  "name": "Playlist Name 🎵",
  "version": "1.0",
  "songs": []
}
```

### 2.2 Convert Extracted Tracks to JSON Format

For each track from Step 1, create a song object:

```json
{
  "year": 1995,
  "uri": "spotify:track:3vSn1frPgFcRXrjWOfhMLl",
  "artist": "La Bouche",
  "alt_artists": [],
  "title": "Be My Lover",
  "chart_info": {
    "billboard_peak": null,
    "uk_peak": null,
    "weeks_on_chart": null
  },
  "certifications": [],
  "awards": [],
  "fun_fact": "",
  "fun_fact_de": "",
  "fun_fact_es": ""
}
```

### 2.3 Quick Python Script to Generate Initial JSON

```python
#!/usr/bin/env python3
import json

# Paste your extracted tracks here
tracks = [
    ("La Bouche", "Be My Lover", "spotify:track:3vSn1frPgFcRXrjWOfhMLl", 1995),
    # ... more tracks
]

songs = []
for artist, title, uri, year in tracks:
    songs.append({
        "year": year,
        "uri": uri,
        "artist": artist,
        "alt_artists": [],
        "title": title,
        "chart_info": {
            "billboard_peak": None,
            "uk_peak": None,
            "weeks_on_chart": None
        },
        "certifications": [],
        "awards": [],
        "fun_fact": "",
        "fun_fact_de": "",
        "fun_fact_es": ""
    })

playlist = {
    "name": "Your Playlist Name 🎵",
    "version": "1.0",
    "songs": songs
}

with open("custom_components/beatify/playlists/your-playlist.json", "w") as f:
    json.dump(playlist, f, indent=2, ensure_ascii=False)

print(f"Created playlist with {len(songs)} tracks")
```

## Step 3: Enrich with Metadata

This is the most time-consuming step. You'll need to research each track's history.

### 3.1 Create a Metadata Script

Use `scripts/add_metadata.py` as a template:

```python
#!/usr/bin/env python3
import json
from pathlib import Path

PLAYLISTS_DIR = Path(__file__).parent.parent / "custom_components" / "beatify" / "playlists"

# Define metadata for each track
METADATA = {
    "Be My Lover": {
        "alt_artists": ["Real McCoy", "Culture Beat", "Corona"],
        "chart_info": {
            "billboard_peak": 6,
            "uk_peak": 27,
            "weeks_on_chart": 20
        },
        "certifications": ["Platinum (US)", "Gold (UK)"],
        "fun_fact": "La Bouche's biggest hit spent 6 months on the Billboard Hot 100.",
        "fun_fact_de": "La Bouches größter Hit verbrachte 6 Monate in den Billboard Hot 100.",
        "fun_fact_es": "El mayor éxito de La Bouche pasó 6 meses en el Billboard Hot 100."
    },
    # Add more tracks...
}

def enrich_metadata(playlist_file):
    with open(playlist_file, 'r', encoding='utf-8') as f:
        playlist = json.load(f)

    enriched_count = 0
    for song in playlist['songs']:
        if song['title'] in METADATA:
            metadata = METADATA[song['title']]
            song['alt_artists'] = metadata.get('alt_artists', [])
            song['chart_info'] = metadata.get('chart_info', song['chart_info'])
            song['certifications'] = metadata.get('certifications', [])
            song['fun_fact'] = metadata.get('fun_fact', '')
            song['fun_fact_de'] = metadata.get('fun_fact_de', '')
            song['fun_fact_es'] = metadata.get('fun_fact_es', '')
            enriched_count += 1

    # Save backup
    backup_path = playlist_file.with_suffix('.json.bak')
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(playlist, f, indent=2, ensure_ascii=False)

    # Save updated file
    with open(playlist_file, 'w', encoding='utf-8') as f:
        json.dump(playlist, f, indent=2, ensure_ascii=False)

    print(f"Enriched {enriched_count}/{len(playlist['songs'])} tracks")

if __name__ == "__main__":
    enrich_metadata(PLAYLISTS_DIR / "your-playlist.json")
```

### 3.2 Research Sources for Metadata

**Chart Positions:**
- Billboard: https://www.billboard.com/charts/
- UK Charts: https://www.officialcharts.com/
- Wikipedia often has detailed chart histories

**Certifications:**
- RIAA (US): https://www.riaa.com/gold-platinum/
- BPI (UK): https://www.bpi.co.uk/
- Usually found on Wikipedia pages

**Alternative Artists:**
- Look for artists in the same genre/era
- Artists commonly confused with this one
- Artists from the same record label or producer

**Fun Facts:**
- Wikipedia articles
- Music history websites
- Billboard/Rolling Stone articles
- Producer/songwriter credits

### 3.3 Batch Processing Tips

For large playlists (50+ tracks):

1. **Group by popularity:** Start with the most well-known tracks
2. **Research in batches:** Do 10-20 tracks at a time
3. **Use templates:** Copy structure from similar tracks
4. **Translate efficiently:** Use a translation service for German/Spanish

Example workflow:
```
Day 1: Research top 25 most popular tracks (2-3 hours)
Day 2: Research next 25 tracks (2-3 hours)
Day 3: Research remaining tracks + translations (2-3 hours)
Day 4: Add streaming URIs (automated, 10-15 minutes)
```

## Step 4: Add Streaming URIs

### 4.1 Using the Enrichment Script

The `enrich_playlists.py` script automatically adds Apple Music and YouTube Music URIs:

```bash
cd scripts
python3 enrich_playlists.py
```

**Interactive prompts:**
```
Playlists directory: /path/to/beatify/custom_components/beatify/playlists
Provider(s) (apple, youtube, all): all
Playlist file (or 'all'): your-playlist.json
Region code (US, UK, DE, etc.): US
```

### 4.2 How It Works

The script uses the Odesli API (https://odesli.co/) to convert Spotify URIs to other platforms:

```python
# For each track:
# 1. Send Spotify URI to Odesli API
response = requests.get(
    "https://api.song.link/v1-alpha.1/links",
    params={"url": spotify_uri, "userCountry": region}
)

# 2. Extract platform URIs from response
apple_music_uri = response['linksByPlatform']['appleMusic']['url']
youtube_music_uri = response['linksByPlatform']['youtubeMusic']['url']

# 3. Wait 6 seconds (rate limit)
time.sleep(6)
```

### 4.3 Expected Results

**Success rates:**
- Apple Music: 75-90% (some tracks not available in all regions)
- YouTube Music: 90-98% (better coverage)

**Time required:**
- 100 tracks × 6 seconds = 10 minutes minimum
- Real time: ~12-15 minutes (includes API overhead)

### 4.4 Handling Failed Lookups

The script creates `scripts/unmatched_songs.log` for failed lookups:

```
APPLE_MUSIC failures:
  - Artist Name - Song Title (spotify:track:xxxxx)

YOUTUBE_MUSIC failures:
  - Artist Name - Song Title (spotify:track:xxxxx)
```

**Manual research for failed tracks:**
1. Search Apple Music/YouTube Music directly
2. Copy the URI from the share menu
3. Add manually to JSON file

## Step 5: Validation and Quality Checks

### 5.1 Validate JSON Structure

```bash
# Check JSON syntax
python3 -m json.tool custom_components/beatify/playlists/your-playlist.json > /dev/null
echo "✓ JSON is valid"
```

### 5.2 Check Completeness

Run this Python check:

```python
import json

with open("custom_components/beatify/playlists/your-playlist.json") as f:
    playlist = json.load(f)

total = len(playlist['songs'])
with_metadata = sum(1 for s in playlist['songs'] if s['fun_fact'])
with_apple = sum(1 for s in playlist['songs'] if s.get('uri_apple_music'))
with_youtube = sum(1 for s in playlist['songs'] if s.get('uri_youtube_music'))

print(f"Total tracks: {total}")
print(f"With metadata: {with_metadata}/{total} ({100*with_metadata/total:.1f}%)")
print(f"With Apple Music: {with_apple}/{total} ({100*with_apple/total:.1f}%)")
print(f"With YouTube Music: {with_youtube}/{total} ({100*with_youtube/total:.1f}%)")
```

### 5.3 Quality Checklist

- [ ] All tracks have Spotify URI
- [ ] All tracks have year
- [ ] 90%+ tracks have metadata (chart_info, certifications)
- [ ] 90%+ tracks have fun facts in English
- [ ] 80%+ tracks have German/Spanish translations
- [ ] 75%+ tracks have Apple Music URI
- [ ] 90%+ tracks have YouTube Music URI
- [ ] Alternative artists selected for variety
- [ ] JSON file is properly formatted
- [ ] Backup file created (.bak)

## Step 6: Commit and Deploy

### 6.1 Git Workflow

```bash
# Stage the playlist file
git add custom_components/beatify/playlists/your-playlist.json

# Check what will be committed
git status
git diff --staged

# Create commit
git commit -m "feat(playlists): Add [Playlist Name] with [N] tracks

Closes #[ISSUE_NUMBER]

Complete playlist featuring [N] tracks from [genre/era]:
- All tracks include comprehensive metadata
- Alternative artists added for gameplay variety
- Fun facts in 3 languages (EN, DE, ES)
- [X]% coverage for Apple Music URIs
- [Y]% coverage for YouTube Music URIs

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

# Push to main
git push origin main
```

### 6.2 Close GitHub Issue

```bash
gh issue close [ISSUE_NUMBER] --comment "✅ [Playlist Name] has been added with [N] fully enriched tracks!

**Features:**
- [N] tracks from [genre/era]
- Complete metadata (chart positions, certifications, awards)
- Alternative artists for gameplay variety
- Fun facts in English, German, and Spanish
- Cross-platform URIs: [X]% Apple Music, [Y]% YouTube Music

The playlist is now ready for use in Beatify. 🎉"
```

## Troubleshooting

### Problem: Spotify API credentials not available

**Solution:** Use WebFetch to extract from embed player (see Step 1, Option A)

### Problem: WebFetch only returns partial data

**Solution:** Spotify embed player should expose all tracks. If not:
1. Try increasing scroll depth
2. Check if playlist is too large (>300 tracks)
3. Fall back to manual CSV export

### Problem: Odesli API rate limiting

**Solution:** The script enforces 6-second delays. If you still get rate limited:
1. Wait 1 hour
2. Resume enrichment (script skips existing URIs)

### Problem: Low Apple Music match rate (<60%)

**Causes:**
- Regional availability (try different region code)
- Track naming mismatches
- Tracks not available on Apple Music

**Solution:**
1. Re-run with different region (UK, DE, etc.)
2. Manually search Apple Music for failed tracks
3. Some tracks genuinely unavailable

### Problem: Metadata research taking too long

**Solution:**
1. Start with top 25-50 tracks only
2. Leave less popular tracks with minimal metadata
3. Focus on fun facts - most engaging for users
4. Use Wikipedia as primary source
5. Consider releasing v1.0 with partial metadata

### Problem: Translation quality concerns

**Solution:**
1. Use DeepL or Google Translate for initial pass
2. Have native speaker review if possible
3. Keep translations short and simple
4. Focus on key facts, not flowery language

## Best Practices

### Efficiency
- **Automate where possible:** Use scripts for repetitive tasks
- **Batch operations:** Research/translate multiple tracks together
- **Parallel work:** Research metadata while streaming URIs process
- **Incremental commits:** Commit after each major milestone

### Quality
- **Verify chart positions:** Cross-reference multiple sources
- **Interesting fun facts:** Focus on surprising/entertaining details
- **Alternative artists matter:** Choose artists that fit gameplay (not too obscure)
- **Consistent formatting:** Follow existing playlist patterns

### Collaboration
- **Document blockers:** Log failed tracks for community help
- **Version control:** Create backups before bulk operations
- **Clear commit messages:** Explain what was enriched
- **Issue updates:** Keep GitHub issue updated with progress

## Scripts Reference

### enrich_playlists.py
**Purpose:** Add Apple Music and YouTube Music URIs
**Usage:** `python3 scripts/enrich_playlists.py`
**Time:** ~10-15 minutes per 100 tracks
**Success rate:** 75-95%

### add_metadata.py (template)
**Purpose:** Add metadata for well-known tracks
**Usage:** Create custom version, run `python3 scripts/add_metadata.py`
**Time:** Manual research required
**Coverage:** Target top 20-30 tracks

### complete_all_metadata.py (template)
**Purpose:** Bulk metadata enrichment
**Usage:** Create with all track metadata, run once
**Time:** Research: hours, Execution: seconds
**Coverage:** All remaining tracks

## Example: Eurodance 90s Playlist

See the successful implementation in commit `0f63b18`:

**Stats:**
- 100 tracks extracted via WebFetch
- 100/100 tracks with full metadata
- 84/100 (84%) with Apple Music URIs
- 97/100 (97%) with YouTube Music URIs
- Total time: ~6 hours (2h extraction/setup, 3h metadata, 1h enrichment)

**Key learnings:**
1. WebFetch is reliable for public playlists
2. Research top 50 tracks first for maximum impact
3. Odesli API very reliable for YouTube Music
4. Apple Music coverage depends heavily on region
5. Fun facts in native language first, then translate

## Support

If you encounter issues:
1. Check existing GitHub issues
2. Review `scripts/unmatched_songs.log` for failed enrichments
3. Consult existing playlist files as examples
4. Ask in GitHub discussions

## File Locations

```
beatify/
├── custom_components/beatify/playlists/
│   ├── eurodance-90s.json              # Example complete playlist
│   └── [your-playlist].json            # Your new playlist
│
├── scripts/
│   ├── enrich_playlists.py             # Streaming URI enrichment
│   ├── add_metadata.py                 # Metadata template
│   ├── complete_all_metadata.py        # Bulk metadata template
│   ├── unmatched_songs.log             # Failed enrichments
│   └── PLAYLIST_ENRICHMENT_RUNBOOK.md  # This file
│
└── .github/
    └── issues/                          # Playlist requests
```

---

**Last updated:** 2026-01-27
**Maintainer:** Beatify Contributors
**Version:** 1.0
