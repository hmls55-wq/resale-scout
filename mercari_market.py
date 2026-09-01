import json
import re
import statistics
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

INPUT = Path("resell_candidates.json")
OUTPUT = Path("mercari_market.json")
DEBUG_SCREENSHOT = Path("mercari_debug.png")
DEBUG_TEXT = Path("mercari_debug.txt")
MAX_CHECKS = 15
MIN_PRICE = 300
MAX_PRICE = 2_000_000


def normalize(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def money_values(text):
    values = []
    for raw in re.findall(r"(?:¥|￥)\s*([0-9,]+)|([0-9]{1,3}(?:,[0-9]{3})+)円|(?:^|\s)([0-9]{3,7})円", text):
        value = next((x for x in raw if x), None)
        if value:
            try:
                v = int(value.replace(",", ""))
                if MIN_PRICE <= v <= MAX_PRICE:
                    values.append(v)
            except ValueError:
                pass
    return values


def tokens(s):
    s = normalize(s).lower()
    out = re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}", s)
    stop = {"中古", "美品", "送料無料", "即購入", "匿名配送", "送料込み", "ジャンク", "セット", "商品"}
    return {x for x in out if x not in stop}


def score_similarity(source_title, candidate_title):
    a = tokens(source_title)
    b = tokens(candidate_title)
    if not a or not b:
        return 0
    overlap = len(a & b) / max(1, len(a))
    model_hits = sum(1 for x in a & b if re.search(r"[a-z0-9]", x))
    return min(100, int(overlap * 75 + min(model_hits, 5) * 5))


def collect_dom_items(page):
    # Do not depend on a specific React/Next.js card class. Collect every item link
    # and use its nearest list/container text for price extraction.
    return page.locator('a[href*="/item/"]').evaluate_all(
        """els => els.map(a => ({
            href: a.href,
            text: (a.closest('li') || a.closest('[role="article"]') || a.parentElement || a).innerText || ''
        }))"""
    )


def browser_lookup(page, query, debug=False):
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({
        "keyword": query,
        "status": "sold_out|trading",
    })
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(2500)

    anchor_count = page.locator('a[href*="/item/"]').count()
    if debug:
        body = normalize(page.locator("body").inner_text())
        DEBUG_TEXT.write_text(
            f"URL={page.url}\nTITLE={page.title()}\nITEM_ANCHORS={anchor_count}\nBODY={body[:12000]}",
            encoding="utf-8",
        )
        page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=False)
        print("Mercari debug:", page.url, page.title(), "item anchors=", anchor_count)
        print("Mercari body preview:", body[:1000])

    raw_items = collect_dom_items(page)
    rows = []
    seen = set()
    for raw in raw_items[:120]:
        href = raw.get("href", "")
        if not href or href in seen:
            continue
        text = normalize(raw.get("text", ""))
        if not text:
            continue
        seen.add(href)
        prices = money_values(text)
        if not prices:
            # Fall back to the anchor's own text if the nearest container is unusual.
            try:
                anchor_text = normalize(page.locator(f'a[href="{href}"]').first.inner_text())
                prices = money_values(anchor_text)
            except Exception:
                pass
        if prices:
            rows.append({
                "url": href,
                "title": text[:500],
                "price": prices[0],
            })
        if len(rows) >= 20:
            break

    prices = sorted(x["price"] for x in rows)
    if not prices:
        return {"query": query, "url": url, "count": 0, "prices": [], "items": [], "anchor_count": anchor_count}
    trimmed = prices[1:-1] if len(prices) >= 5 else prices
    return {
        "query": query,
        "url": url,
        "count": len(prices),
        "prices": prices,
        "median": int(statistics.median(prices)),
        "robust_median": int(statistics.median(trimmed)),
        "low": min(prices),
        "high": max(prices),
        "items": rows[:10],
        "anchor_count": anchor_count,
    }


def fallback_sold_keyword_lookup(page, query):
    # If the dedicated sold/trading filter renders no cards, try the public search
    # index with explicit sold-language terms. These are fallback signals only.
    all_rows = []
    for extra in ["売約済み", "sold out"]:
        q = f"{query} {extra}"
        url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({"keyword": q})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            raw_items = collect_dom_items(page)
            for raw in raw_items[:80]:
                text = normalize(raw.get("text", ""))
                if not text:
                    continue
                lowered = text.lower()
                if "売約済み" not in text and "sold out" not in lowered and "soldout" not in lowered:
                    continue
                prices = money_values(text)
                if prices:
                    all_rows.append({"url": raw.get("href", ""), "title": text[:500], "price": prices[0]})
        except Exception:
            continue
    unique = {}
    for row in all_rows:
        unique[row["url"]] = row
    rows = list(unique.values())[:20]
    prices = sorted(x["price"] for x in rows)
    if not prices:
        return {"count": 0, "prices": [], "items": [], "fallback": True}
    trimmed = prices[1:-1] if len(prices) >= 5 else prices
    return {
        "count": len(prices),
        "prices": prices,
        "median": int(statistics.median(prices)),
        "robust_median": int(statistics.median(trimmed)),
        "low": min(prices),
        "high": max(prices),
        "items": rows[:10],
        "fallback": True,
    }


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is required")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    checked = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP", viewport={"width": 1440, "height": 1000})
        for index, item in enumerate(candidates[:MAX_CHECKS]):
            title = normalize(item.get("title", ""))
            if not title:
                continue
            brands = item.get("brands") or []
            brand = brands[0].get("name", "") if brands else ""
            query = " ".join(x for x in [brand, title] if x)
            try:
                result = browser_lookup(page, query, debug=(index == 0))
                if result.get("count", 0) == 0:
                    fallback = fallback_sold_keyword_lookup(page, query)
                    if fallback.get("count", 0) > 0:
                        result.update(fallback)
                        result["fallback_used"] = True
            except Exception as exc:
                result = {"query": query, "url": "", "count": 0, "prices": [], "items": [], "error": repr(exc)}
            best_similarity = 0
            for row in result.get("items", []):
                row["similarity"] = score_similarity(title, row.get("title", ""))
                best_similarity = max(best_similarity, row["similarity"])
            result["best_similarity"] = best_similarity
            result["source_url"] = item.get("url")
            result["source_title"] = title
            result["purchase_price"] = item.get("price", 0)
            checked.append(result)
            print("メルカリ相場", title, "件数=", result.get("count", 0), "中央値=", result.get("robust_median"), "一致度=", best_similarity, "fallback=", result.get("fallback_used", False))
            time.sleep(1)
        browser.close()

    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checked": checked,
        "note": "ブラウザでメルカリの売り切れ/取引中検索を確認し、0件時は売約済み/sold outキーワード検索をフォールバック。画像一致は未実装。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
