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
            if a and a in text and entry.get("name") not in seen:
                hits.append({
                    "name": entry.get("name", alias),
                    "matched": alias,
                    "priority": entry.get("priority", "監視"),
                })
                seen.add(entry.get("name"))
                break
    return hits


def load_state():
    data = load_json(STATE_PATH, {})
    return set(data.get("seen_urls", []))


def save_state(seen):
    urls = list(seen)[-5000:]
    STATE_PATH.write_text(
        json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "seen_urls": urls}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def discord_notify(items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook or not items:
        if not webhook:
            print("DISCORD_WEBHOOK_URL is not configured; notification skipped.")
        return False

    ok = True
    for item in items[:MAX_NEW_ITEMS]:
        hits = ", ".join(h["name"] for h in item.get("watch_hits", [])[:4]) or "通信テスト"
        priority = "🔥" if any(h.get("priority") == "最優先" for h in item.get("watch_hits", [])) else "🟡"
        image = (item.get("image_urls") or [None])[0]
        embed = {
            "title": f"{priority} {item.get('title', 'ジモティー商品')[:240]}",
            "url": item.get("url"),
            "description": f"監視一致：{hits}\n価格：{item.get('price', 0):,}円\n\nResell Scout 通知経路テスト",
            "footer": {"text": "Resell Scout"},
        }
        if image:
            embed["image"] = {"url": image}
        payload = json.dumps({"content": "🚨 ジモティー通知テスト", "embeds": [embed]}, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ResellScout/1.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status not in (200, 204):
                    ok = False
                    print("Discord notification failed:", r.status)
        except Exception as e:
            ok = False
            print("Discord notification error:", repr(e))
    return ok


def main():
    entries = load_watchlist()
    seen = load_state()
    force_current = os.environ.get("FORCE_CURRENT_MATCHES", "").strip().lower() == "true"
    all_items = []
    for url in scout.SEARCH_URLS:
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
        if url in seen and not force_current:
            continue
        hits = match_watchlist(item, entries)
        if hits:
            item["watch_hits"] = hits
            matches.append(item)

    # In the one-time commit-triggered test, always send the first live listing
    # so Discord delivery can be verified independently of watchlist matching.
    if force_current and not matches and unique:
        first_item = next(iter(unique.values()))
        first_item["watch_hits"] = [{"name": "通信テスト", "matched": "強制テスト", "priority": "監視"}]
        matches = [first_item]
        print("No watchlist match; using first live listing for Discord delivery test.")

    seen.update(unique.keys())
    save_state(seen)

    matches.sort(key=lambda x: (0 if any(h.get("priority") == "最優先" for h in x.get("watch_hits", [])) else 1, x.get("price", 0)))
    Path("new_matches.json").write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(matches),
        "matches": matches[:MAX_NEW_ITEMS],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "CURRENT-TEST" if force_current else "NEW-ONLY"
    print(f"Mode: {mode}")
    print(f"Observed: {len(unique)} / Watched matches: {len(matches)}")
    for item in matches[:MAX_NEW_ITEMS]:
        print(f"MATCH: {item['title']} / {item['price']:,}円 / {item['url']}")

    discord_notify(matches)


if __name__ == "__main__":
    main()
