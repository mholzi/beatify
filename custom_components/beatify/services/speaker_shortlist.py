"""The short speaker list in the wizard's Step 1 (#3537).

A Home Assistant with Music Assistant usually shows the same physical speaker
two or three times: once from Music Assistant and once more from each native
integration that found it (Sonos, Cast, ...). #1627 already drops a native twin
that shares its ``unique_id`` with the Music Assistant player, but most
integrations use their own ids, so the duplicates stayed in the list.

This module is pure (no Home Assistant import) so the rules are unit-tested on
plain dicts:

* :func:`find_duplicates` marks a non-Music-Assistant player as a duplicate of
  a Music Assistant player for the same physical speaker. The signal is the
  device registry (both entities on the same device, which happens when Music
  Assistant shares the speaker's MAC with the native integration) or the same
  area plus the same name once integration words are removed. Anything weaker
  is not a duplicate: when in doubt both stay on the list.
  #3580: Music Assistant itself can list one device several times (a Cast
  player, a second protocol, a "dashboard:chromecast" player, ...), each with
  its own device and unique_id. Two Music Assistant players whose names reduce
  to the same words and whose areas do not conflict are one speaker: all but
  one are marked as duplicates of it.
* :func:`apply_shortlist` decides which speakers the wizard shows on its own.
  Duplicates are left off; the admin's own choice (stored server-side) wins
  over that; the speaker that is selected or was used last is always shown.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

MA_PLATFORM = "music_assistant"

#: Words that name the integration or the kind of device rather than the room.
#: "Living Room Sonos" and "Living Room (MA)" are both "living room".
_NOISE_WORDS = frozenset(
    {
        "ma",
        "music",
        "assistant",
        "sonos",
        "cast",
        "chromecast",
        "google",
        "airplay",
        "dlna",
        "upnp",
        "speaker",
        "speakers",
        "player",
        "media",
        "mediaplayer",
    }
)

#: Upper bound for one override list: far above any real house, low enough
#: that a bad request cannot grow the stored file without limit.
MAX_OVERRIDE_ENTRIES = 500
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def name_key(name: Any) -> str:
    """Reduce a friendly name to the words that name the speaker.

    Lower case, accents dropped, punctuation and integration words removed,
    bare numbers removed ("Kitchen 2" is HA's suffix for a second entity of
    the same name). Returns ``""`` when nothing is left, which never matches.
    """
    if not isinstance(name, str):
        return ""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    words = [
        w
        for w in re.split(r"[^a-z0-9]+", folded)
        if w and w not in _NOISE_WORDS and not w.isdigit()
    ]
    return " ".join(words)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _is_speaker(player: Mapping[str, Any]) -> bool:
    """Real speakers only: the TV screen / this phone targets are never hidden."""
    return not player.get("browser_target")


def _unavailable(player: Mapping[str, Any]) -> bool:
    return player.get("state") == "unavailable"


def _same_speaker(
    native: Mapping[str, Any],
    ma: Mapping[str, Any],
    meta: Mapping[str, Mapping[str, Any]],
) -> bool:
    n_meta = meta.get(native["entity_id"], {})
    m_meta = meta.get(ma["entity_id"], {})
    n_device = _str_or_none(n_meta.get("device_id"))
    if n_device and n_device == _str_or_none(m_meta.get("device_id")):
        return True
    n_area = _str_or_none(n_meta.get("area_id"))
    if not n_area or n_area != _str_or_none(m_meta.get("area_id")):
        return False
    key = name_key(native.get("friendly_name"))
    return bool(key) and key == name_key(ma.get("friendly_name"))


def _ma_twin_pairs(
    ma_players: list[Mapping[str, Any]],
    meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """#3580: map each extra Music Assistant player to the one that stays.

    Two Music Assistant players are the same speaker when their names reduce
    to the same words and their areas do not conflict (equal, or at least one
    side has no area). Different areas, or different words, keep both. Of a
    group the available player wins, then the plainest name (no "+" or other
    marks), then the lowest entity_id, so the choice is stable.
    """

    def _area(p: Mapping[str, Any]) -> str | None:
        return _str_or_none(meta.get(p["entity_id"], {}).get("area_id"))

    def _rank(p: Mapping[str, Any]) -> tuple[bool, int, str]:
        name = str(p.get("friendly_name") or "")
        marks = sum(1 for ch in name if not (ch.isalnum() or ch.isspace()))
        return (_unavailable(p), marks, p["entity_id"])

    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for p in ma_players:
        key = name_key(p.get("friendly_name"))
        if key:
            by_name.setdefault(key, []).append(p)
    twins: dict[str, str] = {}
    for group in by_name.values():
        remaining = sorted(group, key=_rank)
        while remaining:
            keeper = remaining.pop(0)
            keeper_area = _area(keeper)
            rest = []
            for other in remaining:
                other_area = _area(other)
                if keeper_area and other_area and keeper_area != other_area:
                    rest.append(other)
                elif _unavailable(other) or not _unavailable(keeper):
                    twins[other["entity_id"]] = keeper["entity_id"]
                else:
                    rest.append(other)
            remaining = rest
    return twins


def find_duplicates(
    players: Iterable[Mapping[str, Any]],
    meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Map each duplicate speaker's entity_id to the Music Assistant player
    for the same physical speaker.

    ``meta`` holds ``{"device_id": ..., "area_id": ...}`` per entity_id, the
    area already resolved from the device when the entity has none.

    Conservative on purpose:

    * a non-Music-Assistant player can only be a duplicate of a Music
      Assistant player that is in the list; a Music Assistant player only of
      another one with the same name (#3580);
    * a player that is available is never hidden behind one that is not, so
      the only working entry for a speaker always stays on the short list.
    """
    speakers = [p for p in players if _is_speaker(p) and p.get("entity_id")]
    ma_players = [p for p in speakers if p.get("platform") == MA_PLATFORM]
    if not ma_players:
        return {}
    ma_twins = _ma_twin_pairs(ma_players, meta)
    duplicates: dict[str, str] = dict(ma_twins)
    for native in speakers:
        if native.get("platform") == MA_PLATFORM:
            continue
        matches = [m for m in ma_players if _same_speaker(native, m, meta)]
        if not _unavailable(native):
            matches = [m for m in matches if not _unavailable(m)]
        if matches:
            first = matches[0]["entity_id"]
            duplicates[native["entity_id"]] = ma_twins.get(first, first)
    return duplicates


def sanitize_overrides(raw: Any) -> dict[str, list[str]]:
    """Normalise a stored or posted ``{"shown": [...], "hidden": [...]}``.

    Keeps well-formed entity ids only, drops repeats, caps each list. An id
    named in both lists counts as hidden.
    """

    def _ids(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if (
                isinstance(item, str)
                and len(item) <= 255
                and _ENTITY_ID.match(item)
                and item not in out
            ):
                out.append(item)
            if len(out) >= MAX_OVERRIDE_ENTRIES:
                break
        return out

    if not isinstance(raw, Mapping):
        return {"shown": [], "hidden": []}
    hidden = _ids(raw.get("hidden"))
    shown = [e for e in _ids(raw.get("shown")) if e not in hidden]
    return {"shown": shown, "hidden": hidden}


def apply_shortlist(
    players: Iterable[Mapping[str, Any]],
    duplicates: Mapping[str, str],
    overrides: Any,
    pinned: Iterable[str | None] = (),
) -> list[dict[str, Any]]:
    """Return copies of ``players`` with the shortlist fields added.

    Each real speaker gets:

    * ``duplicate_of`` — the Music Assistant entity it duplicates, or ``None``;
    * ``visibility_override`` — ``"shown"``, ``"hidden"`` or ``None`` (the
      admin's own choice from the manage view);
    * ``shortlisted`` — whether Step 1 shows it without expanding the list.

    The admin's choice beats the automatic rule. A pinned speaker (selected
    or last used) is shortlisted whatever the rules say, so the current pick
    never disappears into the collapsed part. The browser targets pass
    through unchanged.
    """
    clean = sanitize_overrides(overrides)
    shown = set(clean["shown"])
    hidden = set(clean["hidden"])
    pinned_ids = {p for p in pinned if isinstance(p, str) and p}
    out: list[dict[str, Any]] = []
    for player in players:
        item = dict(player)
        if _is_speaker(item):
            entity_id = item.get("entity_id")
            dup_of = duplicates.get(entity_id) if entity_id else None
            if entity_id in hidden:
                override: str | None = "hidden"
            elif entity_id in shown:
                override = "shown"
            else:
                override = None
            if override is not None:
                listed = override == "shown"
            else:
                listed = dup_of is None
            item["duplicate_of"] = dup_of
            item["visibility_override"] = override
            item["shortlisted"] = listed or entity_id in pinned_ids
        out.append(item)
    return out
