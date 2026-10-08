
import json
import os
import re
import html
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

FEEDS_FILE = Path("feeds.json")
NEWS_FILE = Path("news.json")
SEEN_FILE = Path("seen.json")

MAX_HEADLINES = 30
MAX_DISCORD_POSTS = 5

HEADERS = {
    "User-Agent": "GreenRoomNews/1.0 (RSS reader)"
}


def download(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def find_text(element, names):
    for name in names:
        child = element.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def parse_feed(data, source):
    root = ET.fromstring(data)
    articles = []

    # RSS 2.0
    items = root.findall(".//item")

    # Atom feeds
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//a:entry", ns)

    for item in items:
        title = find_text(
            item,
            ["title", "{http://www.w3.org/2005/Atom}title"]
        )

        link = find_text(item, ["link"])

        if not link:
            atom_link = item.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = atom_link.get("href", "")

        published = find_text(
            item,
            [
                "pubDate",
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated"
            ]
        )

        if title and link:
            articles.append({
                "title": clean(title),
                "url": link,
                "source": source,
                "published": published
            })

    return articles


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def post_to_discord(article, webhook):
    payload = {
        "username": "Green Room News",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": article["title"][:256],
            "url": article["url"],
            "description": f"Latest gaming news from {article['source']}",
            "color": 3066930
        }]
    }

    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "GreenRoomNews/1.0"
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status


def main():
    config = load_json(FEEDS_FILE, {"feeds": []})
    articles = []

    for feed in config["feeds"]:
        try:
            data = download(feed["url"])
            found = parse_feed(data, feed["name"])
            articles.extend(found)
            print(f"{feed['name']}: {len(found)} articles")
        except Exception as error:
            print(f"Error reading {feed['name']}: {error}")

    # Remove duplicate URLs while preserving feed order.
    unique = {}
    for article in articles:
        unique.setdefault(article["url"], article)

    articles = list(unique.values())

    # Keep the latest headlines for the OBS ticker.
    save_json(NEWS_FILE, {
        "updated": datetime.now(timezone.utc).isoformat(),
        "articles": articles[:MAX_HEADLINES]
    })

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    previous = load_json(SEEN_FILE, {"urls": []})
    seen = set(previous.get("urls", []))

    # First run: establish a baseline without flooding Discord.
    if not SEEN_FILE.exists():
        save_json(SEEN_FILE, {
            "urls": [a["url"] for a in articles][-1000:]
        })
        print("First run: initialized article history.")
        return

    new_articles = [
        article for article in articles
        if article["url"] not in seen
    ]

    if webhook:
        for article in new_articles[:MAX_DISCORD_POSTS]:
            try:
                post_to_discord(article, webhook)
                seen.add(article["url"])
                time.sleep(1)
            except Exception as error:
                print(f"Discord posting failed: {error}")
    else:
        print("No Discord webhook configured.")

    save_json(SEEN_FILE, {
        "urls": list(seen.union(
            a["url"] for a in articles
            if a["url"] in seen
        ))[-1000:]
    })

    print(f"Collected {len(articles)} articles.")
    print(f"New articles found: {len(new_articles)}")


if __name__ == "__main__":
    main()

