#!/usr/bin/env python3
"""Generate a comprehensive Markdown stats report for the Beatify project.

Maintains a JSON history file for daily comparisons. When run repeatedly,
shows deltas vs. the previous snapshot and only surfaces new/updated posts.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


GITHUB_REPO = "mholzi/beatify"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
HACS_API = "https://analytics.home-assistant.io/custom_integrations.json"
REDDIT_SUBREDDITS = ["homeassistant", "homeautomation"]
YOUTUBE_SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
HA_COMMUNITY = "https://community.home-assistant.io"
SIMON42_COMMUNITY = "https://community.simon42.com"

USER_AGENT = "Beatify-Stats-Generator/1.0"


# ── History ──────────────────────────────────────────────────────────────────

def load_history(history_path):
    """Load history JSON. Returns dict with 'snapshots' list."""
    if os.path.exists(history_path):
        with open(history_path) as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history_path, history):
    """Save history JSON."""
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


def get_previous_snapshot(history):
    """Get the most recent snapshot, or None."""
    if history["snapshots"]:
        return history["snapshots"][-1]
    return None


def build_snapshot(github, hacs, reddit, youtube, ha_forum, simon42_forum):
    """Build a snapshot dict with key metrics and post fingerprints."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snapshot = {"date": today, "metrics": {}, "posts": {}}

    # Key metrics for delta comparison
    if github:
        snapshot["metrics"]["github_stars"] = github.get("stars", 0)
        snapshot["metrics"]["github_forks"] = github.get("forks", 0)
        snapshot["metrics"]["github_watchers"] = github.get("watchers", 0)
        snapshot["metrics"]["github_open_issues"] = github.get("open_issues", 0)
        snapshot["metrics"]["github_open_prs"] = github.get("open_prs", 0)
        snapshot["metrics"]["github_contributors"] = github.get("contributors", 0)
        if "traffic_views" in github:
            snapshot["metrics"]["github_views_total"] = github["traffic_views"]["total"]
            snapshot["metrics"]["github_views_unique"] = github["traffic_views"]["unique"]
        if "traffic_clones" in github:
            snapshot["metrics"]["github_clones_total"] = github["traffic_clones"]["total"]
            snapshot["metrics"]["github_clones_unique"] = github["traffic_clones"]["unique"]

    if hacs and hacs.get("found"):
        snapshot["metrics"]["hacs_installs"] = hacs["total_installs"]
        snapshot["metrics"]["hacs_rank"] = hacs["rank"]

    # Post fingerprints: url -> comment count (for detecting new comments)
    # Reddit
    reddit_posts = {}
    for post in (reddit or []):
        reddit_posts[post["url"]] = {
            "title": post["title"],
            "num_comments": post["num_comments"],
            "score": post["score"],
        }
    snapshot["posts"]["reddit"] = reddit_posts

    # YouTube
    yt_posts = {}
    for video in (youtube or []):
        yt_posts[video["url"]] = {
            "title": video["title"],
            "comments": video["comments"],
            "views": video["views"],
        }
    snapshot["posts"]["youtube"] = yt_posts

    # HA Forum
    ha_topics_map = {}
    for topic in (ha_forum or {}).get("topics", []):
        ha_topics_map[topic["url"]] = {
            "title": topic["title"],
            "posts_count": topic["posts_count"],
            "reply_count": topic["reply_count"],
            "views": topic["views"],
        }
    snapshot["posts"]["ha_forum"] = ha_topics_map

    # simon42 Forum
    s42_topics_map = {}
    for topic in (simon42_forum or {}).get("topics", []):
        s42_topics_map[topic["url"]] = {
            "title": topic["title"],
            "posts_count": topic["posts_count"],
            "reply_count": topic["reply_count"],
            "views": topic["views"],
        }
    snapshot["posts"]["simon42_forum"] = s42_topics_map

    return snapshot


# ── Delta helpers ────────────────────────────────────────────────────────────

def delta_str(current, previous, key):
    """Return a delta string like ' (+3)' or ' (-1)' or ''."""
    if previous is None:
        return ""
    prev_val = previous.get("metrics", {}).get(key)
    if prev_val is None:
        return ""
    diff = current - prev_val
    if diff > 0:
        return f" (+{diff})"
    elif diff < 0:
        return f" ({diff})"
    return ""


def is_new_or_updated_post(url, current_data, prev_posts):
    """Check if a post is new or has new comments vs previous snapshot."""
    if url not in prev_posts:
        return "new"
    prev = prev_posts[url]
    # Check comment count changes
    comment_key = "num_comments" if "num_comments" in current_data else "comments" if "comments" in current_data else "posts_count"
    prev_comment_key = "num_comments" if "num_comments" in prev else "comments" if "comments" in prev else "posts_count"
    curr_comments = current_data.get(comment_key, 0)
    prev_comments = prev.get(prev_comment_key, 0)
    if curr_comments > prev_comments:
        return f"+{curr_comments - prev_comments} comments"
    return None


# ── Fetch functions ──────────────────────────────────────────────────────────

def fetch_json(url, headers=None, timeout=15):
    """Fetch JSON from a URL with error handling."""
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  Warning: Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def fetch_json_curl(url, timeout=15):
    """Fetch JSON using curl (more reliable for Reddit)."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", str(timeout), "-H", "User-Agent: Beatify-Stats/1.0", url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        print(f"  Warning: curl failed for {url}: {e}", file=sys.stderr)
    return None


def fetch_github_stats(token=None):
    """Fetch GitHub repository statistics."""
    print("Fetching GitHub stats...")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    stats = {}

    data = fetch_json(GITHUB_API, headers)
    if data:
        stats["stars"] = data.get("stargazers_count", 0)
        stats["forks"] = data.get("forks_count", 0)
        stats["watchers"] = data.get("subscribers_count", 0)
        stats["open_issues"] = data.get("open_issues_count", 0)
        stats["description"] = data.get("description", "")
        stats["created_at"] = data.get("created_at", "")
        stats["updated_at"] = data.get("pushed_at", "")
        stats["language"] = data.get("language", "")
        stats["license"] = (data.get("license") or {}).get("spdx_id", "N/A")

    all_prs = fetch_json(f"{GITHUB_API}/pulls?state=open&per_page=100", headers)
    if all_prs is not None:
        stats["open_prs"] = len(all_prs)
        stats["open_issues"] = stats.get("open_issues", 0) - stats["open_prs"]

    contributors = fetch_json(f"{GITHUB_API}/contributors?per_page=100", headers)
    if contributors:
        stats["contributors"] = len(contributors)
        stats["top_contributors"] = [
            {"login": c["login"], "contributions": c["contributions"]}
            for c in contributors[:5]
        ]

    releases = fetch_json(f"{GITHUB_API}/releases?per_page=1", headers)
    if releases and len(releases) > 0:
        r = releases[0]
        stats["latest_release"] = {
            "tag": r.get("tag_name", ""),
            "name": r.get("name", ""),
            "date": r.get("published_at", ""),
            "prerelease": r.get("prerelease", False),
        }

    if token:
        views = fetch_json(f"{GITHUB_API}/traffic/views", headers)
        if views:
            stats["traffic_views"] = {
                "total": views.get("count", 0),
                "unique": views.get("uniques", 0),
            }

        clones = fetch_json(f"{GITHUB_API}/traffic/clones", headers)
        if clones:
            stats["traffic_clones"] = {
                "total": clones.get("count", 0),
                "unique": clones.get("uniques", 0),
            }

        referrers = fetch_json(f"{GITHUB_API}/traffic/popular/referrers", headers)
        if referrers:
            stats["referrers"] = [
                {"source": r["referrer"], "count": r["count"], "unique": r["uniques"]}
                for r in referrers[:10]
            ]

        paths = fetch_json(f"{GITHUB_API}/traffic/popular/paths", headers)
        if paths:
            stats["popular_paths"] = [
                {"path": p["path"], "count": p["count"], "unique": p["uniques"]}
                for p in paths[:10]
            ]

    return stats


def fetch_hacs_stats():
    """Fetch HACS install count and ranking."""
    print("Fetching HACS stats...")
    data = fetch_json(HACS_API, timeout=30)
    if not data:
        return None

    beatify = data.get("beatify")
    if not beatify:
        return {"found": False}

    ranked = sorted(data.items(), key=lambda x: x[1].get("total", 0), reverse=True)
    rank = next((i + 1 for i, (name, _) in enumerate(ranked) if name == "beatify"), None)

    return {
        "found": True,
        "total_installs": beatify.get("total", 0),
        "versions": beatify.get("versions", {}),
        "rank": rank,
        "total_integrations": len(data),
    }


def fetch_reddit_posts():
    """Fetch Reddit posts mentioning Beatify."""
    print("Fetching Reddit posts...")
    all_posts = []

    for subreddit in REDDIT_SUBREDDITS:
        url = f"https://www.reddit.com/r/{subreddit}/search.json?q=Beatify&restrict_sr=on&sort=new&limit=25"
        data = fetch_json_curl(url)
        time.sleep(2)

        if data and "data" in data:
            for child in data["data"].get("children", []):
                post = child.get("data", {})
                all_posts.append({
                    "subreddit": post.get("subreddit", subreddit),
                    "title": post.get("title", ""),
                    "url": f"https://reddit.com{post.get('permalink', '')}",
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "created": datetime.fromtimestamp(
                        post.get("created_utc", 0), tz=timezone.utc
                    ).strftime("%Y-%m-%d"),
                    "author": post.get("author", ""),
                })

    return all_posts


def fetch_youtube_videos(api_key):
    """Fetch YouTube videos mentioning Beatify."""
    print("Fetching YouTube videos...")
    if not api_key:
        return None

    search_url = (
        f"{YOUTUBE_SEARCH_API}?part=snippet&q=%22Beatify%22+home+assistant"
        f"&type=video&maxResults=25&order=date&key={api_key}"
    )
    search_data = fetch_json(search_url)
    if not search_data or "items" not in search_data:
        return []

    video_ids = [item["id"]["videoId"] for item in search_data["items"] if "videoId" in item.get("id", {})]
    if not video_ids:
        return []

    ids_str = ",".join(video_ids)
    stats_url = f"{YOUTUBE_VIDEOS_API}?part=snippet,statistics&id={ids_str}&key={api_key}"
    stats_data = fetch_json(stats_url)
    if not stats_data or "items" not in stats_data:
        return []

    videos = []
    for item in stats_data["items"]:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        videos.append({
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published": snippet.get("publishedAt", "")[:10],
            "url": f"https://youtube.com/watch?v={item['id']}",
            "views": int(statistics.get("viewCount", 0)),
            "likes": int(statistics.get("likeCount", 0)),
            "comments": int(statistics.get("commentCount", 0)),
        })

    return videos


def fetch_discourse_posts(base_url, forum_name):
    """Fetch posts from a Discourse forum."""
    print(f"Fetching {forum_name} posts...")
    url = f"{base_url}/search.json?q=%22Beatify%22"
    data = fetch_json(url)

    if not data:
        return {"topics": [], "posts": []}

    topics = []
    for topic in data.get("topics", []):
        topics.append({
            "title": topic.get("title", ""),
            "url": f"{base_url}/t/{topic.get('slug', '')}/{topic.get('id', '')}",
            "posts_count": topic.get("posts_count", 0),
            "reply_count": topic.get("reply_count", 0),
            "views": topic.get("views", 0),
            "created_at": (topic.get("created_at") or "")[:10],
            "last_posted_at": (topic.get("last_posted_at") or "")[:10],
        })

    posts = []
    for post in data.get("posts", []):
        posts.append({
            "topic_id": post.get("topic_id"),
            "username": post.get("username", ""),
            "created_at": (post.get("created_at") or "")[:10],
            "blurb": post.get("blurb", ""),
        })

    return {"topics": topics, "posts": posts}


# ── Report generation ────────────────────────────────────────────────────────

def format_date(iso_str):
    """Format an ISO date string to a readable format."""
    if not iso_str:
        return "N/A"
    try:
        return iso_str[:10]
    except (IndexError, TypeError):
        return "N/A"


def _format_view_deltas(topics, prev_topics):
    """Format view count changes for forum topics. Returns string or None."""
    parts = []
    for topic in topics:
        prev = prev_topics.get(topic["url"], {})
        prev_views = prev.get("views", 0)
        curr_views = topic.get("views", 0)
        if curr_views > prev_views:
            title_short = topic["title"][:30] + ("..." if len(topic["title"]) > 30 else "")
            parts.append(f"{title_short} ({prev_views}→{curr_views}, +{curr_views - prev_views})")
    return ", ".join(parts) if parts else None


def generate_report(github, hacs, reddit, youtube, ha_forum, simon42_forum, prev_snapshot):
    """Generate the Markdown report with deltas vs previous snapshot."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prev_date = prev_snapshot["date"] if prev_snapshot else None
    lines = []

    lines.append("# Beatify Stats Report")
    lines.append(f"> Generated: {now}")
    if prev_date:
        lines.append(f"> Compared to: {prev_date}")
    lines.append("")

    # ── GitHub ──
    lines.append("---")
    lines.append("## GitHub")
    lines.append("")
    if github:
        lines.append(f"**Repository**: [mholzi/beatify](https://github.com/{GITHUB_REPO})")
        lines.append("")
        lines.append("| Metric | Value | Change |")
        lines.append("|---|---|---|")

        metrics = [
            ("Stars", github.get("stars", 0), "github_stars"),
            ("Forks", github.get("forks", 0), "github_forks"),
            ("Watchers", github.get("watchers", 0), "github_watchers"),
            ("Open Issues", github.get("open_issues", 0), "github_open_issues"),
            ("Open PRs", github.get("open_prs", 0), "github_open_prs"),
            ("Contributors", github.get("contributors", 0), "github_contributors"),
        ]
        for label, value, key in metrics:
            d = delta_str(value, prev_snapshot, key)
            lines.append(f"| {label} | {value} | {d} |")

        lines.append(f"| License | {github.get('license', 'N/A')} | |")
        lines.append(f"| Last Push | {format_date(github.get('updated_at'))} | |")
        lines.append("")

        if "latest_release" in github:
            r = github["latest_release"]
            pre = " (pre-release)" if r.get("prerelease") else ""
            lines.append(f"**Latest Release**: {r['tag']}{pre} ({format_date(r['date'])})")
            lines.append("")

        if "traffic_views" in github:
            lines.append("### Traffic (last 14 days)")
            lines.append("")
            lines.append("| Metric | Total | Unique | Change (Total) | Change (Unique) |")
            lines.append("|---|---|---|---|---|")
            tv = github["traffic_views"]
            tc = github.get("traffic_clones", {})
            lines.append(
                f"| Views | {tv['total']} | {tv['unique']} "
                f"| {delta_str(tv['total'], prev_snapshot, 'github_views_total')} "
                f"| {delta_str(tv['unique'], prev_snapshot, 'github_views_unique')} |"
            )
            lines.append(
                f"| Clones | {tc.get('total', 'N/A')} | {tc.get('unique', 'N/A')} "
                f"| {delta_str(tc.get('total', 0), prev_snapshot, 'github_clones_total')} "
                f"| {delta_str(tc.get('unique', 0), prev_snapshot, 'github_clones_unique')} |"
            )
            lines.append("")

        if "referrers" in github and github["referrers"]:
            lines.append("### Top Referrers")
            lines.append("")
            lines.append("| Source | Views | Unique |")
            lines.append("|---|---|---|")
            for ref in github["referrers"]:
                lines.append(f"| {ref['source']} | {ref['count']} | {ref['unique']} |")
            lines.append("")

        if "popular_paths" in github and github["popular_paths"]:
            lines.append("### Popular Pages")
            lines.append("")
            lines.append("| Path | Views | Unique |")
            lines.append("|---|---|---|")
            for p in github["popular_paths"]:
                lines.append(f"| `{p['path']}` | {p['count']} | {p['unique']} |")
            lines.append("")
    else:
        lines.append("*Failed to fetch GitHub data.*")
        lines.append("")

    # ── HACS ──
    lines.append("---")
    lines.append("## HACS")
    lines.append("")
    if hacs and hacs.get("found"):
        lines.append("| Metric | Value | Change |")
        lines.append("|---|---|---|")
        d_installs = delta_str(hacs["total_installs"], prev_snapshot, "hacs_installs")
        d_rank = ""
        if prev_snapshot:
            prev_rank = prev_snapshot.get("metrics", {}).get("hacs_rank")
            if prev_rank is not None:
                rank_diff = prev_rank - hacs["rank"]  # positive = improved
                if rank_diff > 0:
                    d_rank = f" (+{rank_diff} places)"
                elif rank_diff < 0:
                    d_rank = f" ({rank_diff} places)"
        lines.append(f"| Active Installs | **{hacs['total_installs']}** | {d_installs} |")
        lines.append(f"| Rank | #{hacs['rank']} of {hacs['total_integrations']} | {d_rank} |")
        pct = round(hacs["rank"] / hacs["total_integrations"] * 100, 1)
        lines.append(f"| Percentile | Top {pct}% | |")
        lines.append("")

        if hacs.get("versions"):
            lines.append("### Version Distribution")
            lines.append("")
            lines.append("| Version | Installs |")
            lines.append("|---|---|")
            sorted_versions = sorted(hacs["versions"].items(), key=lambda x: x[1], reverse=True)
            for version, count in sorted_versions:
                lines.append(f"| {version} | {count} |")
            lines.append("")
    elif hacs and not hacs.get("found"):
        lines.append("*Beatify not found in HACS analytics.*")
        lines.append("")
    else:
        lines.append("*Failed to fetch HACS data.*")
        lines.append("")

    # ── Posts sections (only new/updated) ──
    prev_posts = prev_snapshot.get("posts", {}) if prev_snapshot else {}

    # ── Reddit ──
    lines.append("---")
    lines.append("## Reddit")
    lines.append("")
    if reddit:
        prev_reddit = prev_posts.get("reddit", {})
        updated_posts = []
        for post in reddit:
            status = is_new_or_updated_post(
                post["url"],
                {"num_comments": post["num_comments"]},
                prev_reddit,
            )
            if status or not prev_snapshot:
                updated_posts.append((post, status))

        lines.append(f"**Total posts**: {len(reddit)}")
        if prev_snapshot:
            new_count = sum(1 for _, s in updated_posts if s == "new")
            comment_count = sum(1 for _, s in updated_posts if s and s != "new")
            if new_count or comment_count:
                parts = []
                if new_count:
                    parts.append(f"{new_count} new")
                if comment_count:
                    parts.append(f"{comment_count} with new comments")
                lines.append(f"**Updates**: {', '.join(parts)}")
        lines.append("")

        if updated_posts:
            lines.append("| Status | Date | Subreddit | Title | Score | Comments |")
            lines.append("|---|---|---|---|---|---|")
            for post, status in updated_posts:
                badge = "NEW" if status == "new" else status if status else ""
                title = post["title"][:55] + ("..." if len(post["title"]) > 55 else "")
                lines.append(
                    f"| {badge} | {post['created']} | r/{post['subreddit']} | "
                    f"[{title}]({post['url']}) | {post['score']} | {post['num_comments']} |"
                )
            lines.append("")
        elif prev_snapshot:
            lines.append("*No new posts or comments since last report.*")
            lines.append("")
    else:
        lines.append("*No Reddit posts found mentioning Beatify.*")
        lines.append("")

    # ── YouTube ──
    lines.append("---")
    lines.append("## YouTube")
    lines.append("")
    if youtube is None:
        lines.append("*YouTube data unavailable. Set `YOUTUBE_API_KEY` environment variable to enable.*")
        lines.append("")
    elif youtube:
        prev_yt = prev_posts.get("youtube", {})
        updated_videos = []
        for video in youtube:
            status = is_new_or_updated_post(
                video["url"],
                {"comments": video["comments"]},
                prev_yt,
            )
            if status or not prev_snapshot:
                updated_videos.append((video, status))

        lines.append(f"**Total videos**: {len(youtube)}")
        lines.append("")

        if updated_videos:
            lines.append("| Status | Date | Channel | Title | Views | Likes | Comments |")
            lines.append("|---|---|---|---|---|---|---|")
            for video, status in updated_videos:
                badge = "NEW" if status == "new" else status if status else ""
                title = video["title"][:45] + ("..." if len(video["title"]) > 45 else "")
                lines.append(
                    f"| {badge} | {video['published']} | {video['channel']} | "
                    f"[{title}]({video['url']}) | {video['views']:,} | "
                    f"{video['likes']:,} | {video['comments']:,} |"
                )
            lines.append("")
        elif prev_snapshot:
            # Show view deltas for existing videos
            yt_view_parts = []
            for video in youtube:
                prev = prev_yt.get(video["url"], {})
                prev_views = prev.get("views", 0)
                curr_views = video.get("views", 0)
                if curr_views > prev_views:
                    yt_view_parts.append(f"{video['channel']} ({prev_views}→{curr_views}, +{curr_views - prev_views})")
            if yt_view_parts:
                lines.append(f"*No new comments.* View changes: {', '.join(yt_view_parts)}")
            else:
                lines.append("*No new videos or comments since last report.*")
            lines.append("")
    else:
        lines.append("*No YouTube videos found mentioning Beatify.*")
        lines.append("")

    # ── HA Community Forum ──
    lines.append("---")
    lines.append("## Home Assistant Community Forum")
    lines.append("")
    ha_topics = ha_forum.get("topics", []) if ha_forum else []
    if ha_topics:
        prev_ha = prev_posts.get("ha_forum", {})
        updated_topics = []
        for topic in ha_topics:
            status = is_new_or_updated_post(
                topic["url"],
                {"posts_count": topic["posts_count"]},
                prev_ha,
            )
            if status or not prev_snapshot:
                updated_topics.append((topic, status))

        lines.append(f"**Total topics**: {len(ha_topics)}")
        lines.append("")

        if updated_topics:
            lines.append("| Status | Topic | Views | Replies | Last Activity |")
            lines.append("|---|---|---|---|---|")
            for topic, status in updated_topics:
                badge = "NEW" if status == "new" else status if status else ""
                title = topic["title"][:55] + ("..." if len(topic["title"]) > 55 else "")
                lines.append(
                    f"| {badge} | [{title}]({topic['url']}) | {topic['views']} | "
                    f"{topic['reply_count']} | {topic['last_posted_at']} |"
                )
            lines.append("")
        elif prev_snapshot:
            # Show view deltas even when no new comments
            view_changes = _format_view_deltas(ha_topics, prev_ha)
            if view_changes:
                lines.append(f"*No new comments.* View changes: {view_changes}")
            else:
                lines.append("*No new topics or comments since last report.*")
            lines.append("")
    else:
        lines.append("*No mentions of Beatify found on the Home Assistant Community forum.*")
        lines.append("")

    # ── simon42 German Forum ──
    lines.append("---")
    lines.append("## German Home Assistant Forum (simon42 Community)")
    lines.append("")
    s42_topics = simon42_forum.get("topics", []) if simon42_forum else []
    if s42_topics:
        prev_s42 = prev_posts.get("simon42_forum", {})
        updated_topics = []
        for topic in s42_topics:
            status = is_new_or_updated_post(
                topic["url"],
                {"posts_count": topic["posts_count"]},
                prev_s42,
            )
            if status or not prev_snapshot:
                updated_topics.append((topic, status))

        lines.append(f"**Total topics**: {len(s42_topics)}")
        lines.append("")

        if updated_topics:
            lines.append("| Status | Topic | Views | Replies | Last Activity |")
            lines.append("|---|---|---|---|---|")
            for topic, status in updated_topics:
                badge = "NEW" if status == "new" else status if status else ""
                title = topic["title"][:55] + ("..." if len(topic["title"]) > 55 else "")
                lines.append(
                    f"| {badge} | [{title}]({topic['url']}) | {topic['views']} | "
                    f"{topic['reply_count']} | {topic['last_posted_at']} |"
                )
            lines.append("")
        elif prev_snapshot:
            # Show view deltas even when no new comments
            view_changes = _format_view_deltas(s42_topics, prev_s42)
            if view_changes:
                lines.append(f"*No new comments.* View changes: {view_changes}")
            else:
                lines.append("*No new topics or comments since last report.*")
            lines.append("")
    else:
        lines.append("*No mentions of Beatify found on the simon42 Community forum.*")
        lines.append("")

    # ── Summary ──
    lines.append("---")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Platform | Key Metric | Change |")
    lines.append("|---|---|---|")
    if github:
        d = delta_str(github.get("stars", 0), prev_snapshot, "github_stars")
        lines.append(f"| GitHub | {github.get('stars', 0)} stars, {github.get('forks', 0)} forks | {d} |")
    if hacs and hacs.get("found"):
        d = delta_str(hacs["total_installs"], prev_snapshot, "hacs_installs")
        lines.append(f"| HACS | {hacs['total_installs']} active installs (#{hacs['rank']}) | {d} |")
    lines.append(f"| Reddit | {len(reddit) if reddit else 0} posts | |")
    if youtube is not None:
        lines.append(f"| YouTube | {len(youtube) if youtube else 0} videos | |")
    lines.append(f"| HA Forum | {len(ha_topics)} topics | |")
    lines.append(f"| simon42 Forum | {len(s42_topics)} topics | |")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Beatify stats report")
    parser.add_argument("--output", "-o", default="./docs/beatify-stats.md", help="Output file path")
    parser.add_argument("--history", default=None, help="Path to history JSON file (default: same dir as output)")
    args = parser.parse_args()

    # History file lives next to the output by default
    if args.history:
        history_path = args.history
    else:
        history_path = str(Path(args.output).parent / "beatify-stats-history.json")

    github_token = os.environ.get("GITHUB_TOKEN")
    youtube_key = os.environ.get("YOUTUBE_API_KEY")

    if not github_token:
        print("Note: GITHUB_TOKEN not set - traffic/referral data will be skipped.")
    if not youtube_key:
        print("Note: YOUTUBE_API_KEY not set - YouTube data will be skipped.")
    print()

    # Load previous data
    history = load_history(history_path)
    prev_snapshot = get_previous_snapshot(history)
    if prev_snapshot:
        print(f"Previous snapshot: {prev_snapshot['date']}")
    else:
        print("No previous snapshot found — first run.")
    print()

    # Fetch current data
    github = fetch_github_stats(github_token)
    hacs = fetch_hacs_stats()
    reddit = fetch_reddit_posts()
    youtube = fetch_youtube_videos(youtube_key)
    ha_forum = fetch_discourse_posts(HA_COMMUNITY, "Home Assistant Community")
    time.sleep(1)
    simon42_forum = fetch_discourse_posts(SIMON42_COMMUNITY, "simon42 Community")

    # Build and save snapshot
    snapshot = build_snapshot(github, hacs, reddit, youtube, ha_forum, simon42_forum)

    # Replace today's snapshot if already exists, otherwise append
    if history["snapshots"] and history["snapshots"][-1]["date"] == snapshot["date"]:
        history["snapshots"][-1] = snapshot
    else:
        history["snapshots"].append(snapshot)

    # Keep last 90 days
    if len(history["snapshots"]) > 90:
        history["snapshots"] = history["snapshots"][-90:]

    save_history(history_path, history)
    print(f"\nSnapshot saved to: {history_path}")

    # Generate report
    print("Generating report...")
    report = generate_report(github, hacs, reddit, youtube, ha_forum, simon42_forum, prev_snapshot)

    with open(args.output, "w") as f:
        f.write(report)

    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
