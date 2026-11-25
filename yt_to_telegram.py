#!/usr/bin/env python3
"""
YouTube -> Telegram auto-poster.

Watches YouTube channel RSS feeds and sends a Telegram message
whenever a new video appears.

Setup:
    pip install requests
    export TELEGRAM_BOT_TOKEN="123456:ABC..."
    export TELEGRAM_CHAT_ID="@yourchannel"   # or numeric ID like -1001234567890
    python yt_to_telegram.py

Edit CHANNELS below (channel IDs start with "UC").
"""

import html
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "@your_channel_or_chat_id")

# Display name -> YouTube channel ID (loaded from channels.json if it exists)
CHANNELS = {
    "Example Channel 1": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "Example Channel 2": "UCyyyyyyyyyyyyyyyyyyyyyy",
}
if Path("channels.json").exists():
    CHANNELS = json.loads(Path("channels.json").read_text(encoding="utf-8"))

CHECK_INTERVAL = 600          # seconds between checks (10 min)
STATE_FILE = Path("seen_videos.json")
SEND_THUMBNAIL = True         # True = send the video thumbnail with the post
SKIP_SHORTS = False           # True = ignore videos whose link contains /shorts/
MESSAGE_TEMPLATE = "🎬 <b>{channel}</b>\n{title}\n\n{link}"
# -----------------------------

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_videos(channel_id: str) -> list[dict]:
    r = requests.get(FEED_URL.format(channel_id), timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    videos = []
    for entry in root.findall("atom:entry", NS):
        vid = entry.find("yt:videoId", NS).text
        title = entry.find("atom:title", NS).text or ""
        link = entry.find("atom:link", NS).attrib.get("href", f"https://www.youtube.com/watch?v={vid}")
        thumb = entry.find("media:group/media:thumbnail", NS)
        thumb_url = thumb.attrib.get("url") if thumb is not None else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        videos.append({"id": vid, "title": title, "link": link, "thumb": thumb_url})
    return videos  # newest first


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    r.raise_for_status()


def send_photo(photo_url: str, caption: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    r = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "photo": photo_url,
            "caption": caption[:1024],
            "parse_mode": "HTML",
        },
        timeout=20,
    )
    r.raise_for_status()


def check_once(state: dict) -> None:
    for name, cid in CHANNELS.items():
        try:
            videos = fetch_videos(cid)
        except Exception as e:
            print(f"[{name}] fetch error: {e}")
            continue

        seen = set(state.get(cid, []))
        first_run = cid not in state

        # First run: just remember existing videos, don't spam the chat
        if first_run:
            state[cid] = [v["id"] for v in videos]
            print(f"[{name}] initialized with {len(videos)} existing videos")
            continue

        new = [v for v in videos if v["id"] not in seen]
        for v in reversed(new):  # oldest new first
            if SKIP_SHORTS and "/shorts/" in v["link"]:
                seen.add(v["id"])
                continue
            msg = MESSAGE_TEMPLATE.format(
                channel=html.escape(name),
                title=html.escape(v["title"]),
                link=v["link"],
            )
            try:
                if SEND_THUMBNAIL:
                    try:
                        send_photo(v["thumb"], msg)
                    except Exception:
                        send_telegram(msg)  # fall back to text if photo fails
                else:
                    send_telegram(msg)
                print(f"[{name}] posted: {v['title']}")
                seen.add(v["id"])
                time.sleep(1)  # avoid Telegram rate limits
            except Exception as e:
                print(f"[{name}] telegram error: {e}")

        # keep the most recent IDs only
        current = [v["id"] for v in videos]
        older = [i for i in state.get(cid, []) if i not in current]
        state[cid] = (current + older + [i for i in seen if i not in current and i not in older])[:200]


def main() -> None:
    import sys
    state = load_state()
    if "--once" in sys.argv:  # for GitHub Actions / cron
        check_once(state)
        save_state(state)
        return
    print(f"Watching {len(CHANNELS)} channel(s). Interval: {CHECK_INTERVAL}s")
    while True:
        check_once(state)
        save_state(state)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
