import json

import pytest

from ti26.cli_fetch_steam_news import main, render_capture
from ti26.data.steam_news import (
    STEAM_NEWS_URL,
    SteamNewsError,
    announcement_by_gid,
    steam_news_query,
)

ITEM = {
    "gid": "1840944183772671",
    "title": "The International: Streams, Secret Shop, and More",
    "date": 1786494519,
    "contents": "Sixteen teams have earned the right to compete.",
}


def fake_transport(payload, calls=None):
    def transport(url):
        if calls is not None:
            calls.append(url)
        return json.dumps(payload).encode()

    return transport


def feed(*items):
    return {"appnews": {"appid": 570, "newsitems": list(items)}}


def test_query_returns_newsitems_and_asks_for_untruncated_bodies():
    """Kills replacing `maxlength=0` with any truncating value.

    The default Steam News length cuts `contents` off, which would pin a
    capture missing the sentences the format facts live in -- and the capture
    would still look structurally valid.
    """
    calls = []
    items = steam_news_query(fake_transport(feed(ITEM), calls))
    assert items == [ITEM]
    assert calls[0].startswith(STEAM_NEWS_URL)
    assert "maxlength=0" in calls[0]
    assert "feeds=steam_community_announcements" in calls[0]


def test_query_retries_then_succeeds():
    """Kills removing the retry loop, or breaking out of it on first failure."""
    attempts = []

    def transport(url):
        attempts.append(url)
        if len(attempts) < 3:
            raise OSError("connection reset")
        return json.dumps(feed(ITEM)).encode()

    items = steam_news_query(transport, sleep=lambda _: None)
    assert items == [ITEM]
    assert len(attempts) == 3


def test_query_raises_after_exhausting_retries():
    """Kills returning `[]` instead of raising when the transport never succeeds.

    An empty list here would read as "Valve has published nothing" and silently
    produce a capture with no facts in it.
    """

    def transport(url):
        raise OSError("connection reset")

    with pytest.raises(SteamNewsError, match="failed after 3 attempts"):
        steam_news_query(transport, sleep=lambda _: None)


def test_query_rejects_a_payload_without_newsitems():
    """Kills softening the lookup to `payload.get("appnews", {}).get("newsitems", [])`.

    A 200 carrying an unreadable shape is not an empty feed. Defaulting to []
    turns a broken contract into a silently factless capture.
    """
    with pytest.raises(SteamNewsError, match="unreadable"):
        steam_news_query(fake_transport({"appnews": {"appid": 570}}))


def test_announcement_selected_by_gid_not_by_position():
    """Kills selecting `newsitems[0]`, or matching on title instead of gid.

    The feed reorders every time Valve posts, so position is a moving target
    and a re-run would pin a different announcement under the same name.
    """
    other = dict(ITEM, gid="999", title="Gameplay Patch 7.41e and Summer Scrub")
    assert announcement_by_gid([other, ITEM], ITEM["gid"]) == ITEM


def test_announcement_absent_gid_raises():
    """Kills returning None when no item matches, which would pin `null`."""
    with pytest.raises(SteamNewsError, match="no announcement with gid"):
        announcement_by_gid([ITEM], "nope")


def test_announcement_duplicate_gid_raises():
    """Kills returning `matches[0]` when a gid is ambiguous.

    Picking the first would make which announcement got pinned depend on feed
    order, silently, for a capture that is supposed to be content-addressed.
    """
    with pytest.raises(SteamNewsError, match="2 announcements share gid"):
        announcement_by_gid([ITEM, dict(ITEM)], ITEM["gid"])


def test_capture_bytes_do_not_depend_on_key_order():
    """Kills dropping `sort_keys=True` from the pinned rendering.

    Without it, an unchanged announcement can serialize to different bytes and
    a digest mismatch would mean "dict order changed" rather than "Valve edited
    the post" -- which is the only thing the mismatch is allowed to mean.
    """
    reordered = dict(reversed(list(ITEM.items())))
    assert list(reordered) != list(ITEM)
    assert render_capture(reordered) == render_capture(ITEM)


def test_cli_pins_the_announcement(tmp_path, monkeypatch, capsys):
    """Kills writing the whole feed, or a truncated body, instead of one item."""
    monkeypatch.setattr(
        "ti26.cli_fetch_steam_news.steam_news_query",
        lambda *a, **k: [dict(ITEM, gid="999"), ITEM],
    )
    out = tmp_path / "steam-news"
    assert main(["--gid", ITEM["gid"], "--out", str(out)]) == 0
    pinned = json.loads((out / f"{ITEM['gid']}.json").read_text())
    assert pinned == ITEM
    assert ITEM["title"] in capsys.readouterr().out


def test_cli_refuses_to_overwrite_a_diverged_capture(tmp_path, monkeypatch, capsys):
    """Kills writing unconditionally over an existing pinned capture.

    Overwriting destroys the record of what the source said when the owner
    attested it, which is the whole point of pinning the bytes.
    """
    monkeypatch.setattr(
        "ti26.cli_fetch_steam_news.steam_news_query", lambda *a, **k: [ITEM]
    )
    out = tmp_path / "steam-news"
    out.mkdir()
    (out / f"{ITEM['gid']}.json").write_bytes(render_capture(dict(ITEM, contents="edited")))

    assert main(["--gid", ITEM["gid"], "--out", str(out)]) == 1
    assert "CHANGED" in capsys.readouterr().out
    assert json.loads((out / f"{ITEM['gid']}.json").read_text())["contents"] == "edited"


def test_cli_is_idempotent_on_identical_bytes(tmp_path, monkeypatch, capsys):
    """Kills reporting a re-fetch of unchanged content as a divergence."""
    monkeypatch.setattr(
        "ti26.cli_fetch_steam_news.steam_news_query", lambda *a, **k: [ITEM]
    )
    out = tmp_path / "steam-news"
    assert main(["--gid", ITEM["gid"], "--out", str(out)]) == 0
    assert main(["--gid", ITEM["gid"], "--out", str(out)]) == 0
    assert "unchanged" in capsys.readouterr().out
