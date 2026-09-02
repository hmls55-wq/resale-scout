import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import scout

WATCHLIST_PATH = Path("watchlist.json")
STATE_PATH = Path("watch_state.json")
MAX_NEW_ITEMS = 20
WEEK_PAGES = 7


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def load_watchlist():
    data = load_json(WATCHLIST_PATH, {})
    entries = data.get("brands", []) + [
        {"name": x, "aliases": [x], "priority": "キーワード"}
        for x in data.get("extra_terms", [])
    ]
    return entries


def match_watchlist(item, entries):
    text = norm(" ".join([item.get("title", ""), item.get("text", "")]))
    hits = []
    seen = set()
    for entry in entries:
        for alias in entry.get("aliases", []):
            a = norm(alias)
            name = entry.get("name", alias)
            if a and a in text and name not in seen:
                hits.append({"name": name, "matched": alias, "priority": entry.get("priority", "監視")})
                seen.add(name)
                break
    return hits


def load_state():
    data = load_json(STATE_PATH, {})
    return set(data.get("seen_urls", []))


def save_state(seen):
    urls = list(seen)[-5000:]
    STATE_PATH.write_text(json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "seen_urls": urls}, ensure_ascii=False, indent=2), encoding="utf-8")


def discord_notify(items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not configured; notification skipped.")
        return False
    if not items:
        print("Discord: no matching items; notification skipped.")
        return True

    print(f"Discord: sending {min(len(items), MAX_NEW_ITEMS)} notification(s)...")
    ok = True
    for item in items[:MAX_NEW_ITEMS]:
        hits = ", ".join(h["name"] for h in item.get("watch_hits", [])[:4]) or "監視一致"
        priority = "🔥" if any(h.get("priority") == "最優先" for h in item.get("watch_hits", [])) else "🟡"
        image = (item.get("image_urls") or [None])[0]
        embed = {
            "title": f"{priority} {item.get('title', 'ジモティー商品')[:240]}",
            "url": item.get("url"),
            "description": f"監視一致：{hits}\n価格：{item.get('price', 0):,}円\n\n直近1週間スキャン",
            "footer": {"text": "Resell Scout"},
        }
        if image:
            embed["image"] = {"url": image}
        payload = json.dumps({"content": "🚨 ジモティー仕入れ候補", "embeds": [embed]}, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(
                webhook,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "ResellScout/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", errors="replace")
                print(f"Discord: HTTP {r.status} for {item.get('title', 'item')}")
                if r.status not in (200, 204):
                    ok = False
                    print("Discord notification failed:", r.status, body[:300])
        except Exception as e:
            ok = False
            print("Discord notification error:", repr(e))
    return ok


def main():
    entries = load_watchlist()
    seen = load_state()
    week_scan = os.environ.get("WEEK_SCAN", "true").strip().lower() == "true"
    all_items = []

    # Jimoty's category pages are paginated. Scan several pages so the manual
    # review covers a broad recent inventory rather than only the first page.
    for base_url in scout.SEARCH_URLS:
        for page in range(1, WEEK_PAGES + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            print("Fetching:", url)
            try:
                html = scout.fetch(url)
                all_items.extend(scout.extract_items(html))
            except Exception as e:
                print("Fetch failed:", repr(e))

    unique = {}
    for item in all_items:
        unique[item["url"]] = item

    matches = []
    for url, item in unique.items():
        if not week_scan and url in seen:
            continue
        hits = match_watchlist(item, entries)
        if hits:
            item["watch_hits"] = hits
            matches.append(item)

    if not week_scan:
        seen.update(unique.keys())
        save_state(seen)

    matches.sort(key=lambda x: (0 if any(h.get("priority") == "最優先" for h in x.get("watch_hits", [])) else 1, x.get("price", 0)))
    Path("new_matches.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "mode": "WEEK-SCAN" if week_scan else "NEW-ONLY", "count": len(matches), "matches": matches[:MAX_NEW_ITEMS]}, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "WEEK-SCAN" if week_scan else "NEW-ONLY"
    print(f"Mode: {mode}")
    print(f"Observed: {len(unique)} / Watched matches: {len(matches)}")
    for item in matches[:MAX_NEW_ITEMS]:
        print(f"MATCH: {item['title']} / {item['price']:,}円 / {item['url']}")

    if not discord_notify(matches):
        raise RuntimeError("Discord notification failed")


if __name__ == "__main__":
    main()
