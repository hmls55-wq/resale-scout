import json
import re
import statistics
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

INPUT = Path("resell_candidates.json")
OUTPUT = Path("mercari_market.json")
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


def browser_lookup(page, query):
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({
        "keyword": query,
        "status": "sold_out|trading",
    })
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    # Force a small scroll so lazy-loaded result cards appear.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1500)

    items = page.locator('a[href*="/item/"]').all()
    rows = []
    seen = set()
    for anchor in items[:80]:
        href = anchor.get_attribute("href") or ""
        if not href or href in seen:
            continue
        text = normalize(anchor.inner_text())
        if not text:
            continue
        seen.add(href)
        prices = money_values(text)
        if not prices:
            # Some cards render price in a sibling/descendant not captured by inner_text.
            prices = money_values(anchor.evaluate("el => el.parentElement ? el.parentElement.innerText : el.innerText"))
        if prices:
            rows.append({
                "url": "https://jp.mercari.com" + href if href.startswith("/") else href,
                "title": text[:300],
                "price": prices[0],
            })
        if len(rows) >= 20:
            break

    prices = sorted(x["price"] for x in rows)
    if not prices:
        return {"query": query, "url": url, "count": 0, "prices": [], "items": []}
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
        for item in candidates[:MAX_CHECKS]:
            title = normalize(item.get("title", ""))
            if not title:
                continue
            brands = item.get("brands") or []
            brand = brands[0].get("name", "") if brands else ""
            query = " ".join(x for x in [brand, title] if x)
            try:
                result = browser_lookup(page, query)
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
            print("メルカリ相場", title, "件数=", result.get("count", 0), "中央値=", result.get("robust_median"), "一致度=", best_similarity)
            time.sleep(1)
        browser.close()

    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checked": checked,
        "note": "ブラウザでレンダリングしたメルカリ売り切れ/取引中検索結果を使用。タイトル一致度のみで、画像一致は未実装。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
