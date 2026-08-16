"""The second network seam in this package.

Added 2026-08-11. `dota2.com` is JavaScript-rendered and returns an empty body
to every non-browser fetch -- the reason `config/ti2026_rules.yaml` may never
carry an `official` provenance tag. The Steam News API serves the same
announcement text as plain JSON, so Valve's published wording became
retrievable without a browser.

Like `opendota`, the transport is injectable and the whole test suite runs
offline. Nothing here is called by a release run: the producer that uses it
writes a pinned snapshot under `data/raw/`, and release runs read pinned bytes.
"""

import json
import time
import urllib.parse
from collections.abc import Callable

STEAM_NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
DOTA_2_APP_ID = 570

__all__ = [
    "DOTA_2_APP_ID",
    "STEAM_NEWS_URL",
    "SteamNewsError",
    "announcement_by_gid",
    "steam_news_query",
]


class SteamNewsError(RuntimeError):
    """Steam News request failed, or returned a payload this module cannot read."""


def steam_news_query(
    transport: Callable[[str], bytes],
    app_id: int = DOTA_2_APP_ID,
    count: int = 100,
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Return the raw `newsitems` list, newest first.

    `maxlength=0` asks for untruncated bodies -- the default truncates
    `contents`, which would silently produce a capture missing the sentences
    the format facts live in.
    """
    query = urllib.parse.urlencode(
        {
            "appid": app_id,
            "count": count,
            "maxlength": 0,
            "feeds": "steam_community_announcements",
        }
    )
    url = f"{STEAM_NEWS_URL}?{query}"
    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            payload = json.loads(transport(url))
        except Exception as exc:  # noqa: BLE001 -- network boundary: retry transport failures
            last = exc
            if attempt < max_retries - 1:
                sleep(2.0**attempt)
            continue
        # A 200 carrying a payload without `appnews.newsitems` is not an empty
        # feed, it is a shape this module cannot read. Returning [] would look
        # like "Valve has published nothing" and silently drop every fact.
        try:
            return payload["appnews"]["newsitems"]
        except (KeyError, TypeError) as exc:
            raise SteamNewsError(f"unreadable Steam News payload: {exc}") from exc
    raise SteamNewsError(f"Steam News request failed after {max_retries} attempts: {last}")


def announcement_by_gid(newsitems: list[dict], gid: str) -> dict:
    """Select exactly one announcement by `gid`.

    Selecting by title or by position would bind a capture to a moving target:
    the feed reorders as Valve posts, and titles repeat across years. `gid` is
    the only stable identifier Steam exposes for a post.
    """
    matches = [item for item in newsitems if item.get("gid") == gid]
    if not matches:
        raise SteamNewsError(f"no announcement with gid {gid!r} in {len(newsitems)} items")
    if len(matches) > 1:
        raise SteamNewsError(f"{len(matches)} announcements share gid {gid!r}")
    return matches[0]
