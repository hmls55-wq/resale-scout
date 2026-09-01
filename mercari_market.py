import json
import re
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

INPUT = Path("resell_candidates.json")
OUTPUT = Path("mercari_market.json")
MAX_CHECKS = 15
MIN_PRICE = 300
MAX_PRICE = 2_000_000


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def normalize(s):
    s = unescape(s or "")
    return re.sub(r"\s+", " ", s).strip()


def money_values(text):
    values = []
    for m in re.finditer(r"(?:¥|￥)\s*([0-9,]+)|([0-9]{1,3}(?:,[0-9]{3})+)円|(?:^|\s)([0-9]{3,7})円", text):
        raw = next((x for x in m.groups() if x), None)
        if raw:
            try:
                v = int(raw.replace(",", ""))
                if MIN_PRICE <= v <= MAX_PRICE:
                    values.append(v)
            except ValueError:
                pass
    return values


def tokens(s):
    s = normalize(s).lower()
    # Keep Japanese runs and alphanumeric model/brand tokens.
    out = re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}", s)
    stop = {"中古", "美品", "送料無料", "即購入", "匿名配送", "送料込み", "ジャンク", "セット", "商品"}
    return {x for x in out if x not in stop}


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_anchor = False
        self.anchor_href = ""
        self.anchor_text = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            if "/item/" in href:
                self.in_anchor = True
                self.anchor_href = href
                self.anchor_text = []

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.in_anchor:
            title = normalize(" ".join(self.anchor_text))
            if title:
                self.items.append((self.anchor_href, title))
            self.in_anchor = False
            self.anchor_href = ""
            self.anchor_text = []

    def handle_data(self, data):
        if self.in_anchor:
            self.anchor_text.append(data)


def parse_results(html):
    parser = ResultParser()
    parser.feed(html)
    # The same item can appear more than once in markup.
    seen = set()
    out = []
    for href, title in parser.items:
        key = href.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append({"url": "https://jp.mercari.com" + href if href.startswith("/") else href, "title": title})
    return out


def extract_price_from_anchor_context(html, href):
    pos = html.find(href)
    if pos < 0:
        return None
    block = normalize(re.sub(r"<[^>]+>", " ", html[max(0, pos - 300):pos + 1800]))
    vals = money_values(block)
    return vals[0] if vals else None


def market_lookup(query):
    # Mercari supports a sold/trading status filter. This is the market-price signal we want,
    # rather than treating currently listed prices as sold prices.
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({
        "keyword": query,
        "status": "sold_out|trading",
    })
    try:
        html = fetch(url)
    except Exception as exc:
        return {"query": query, "url": url, "error": repr(exc), "count": 0, "prices": []}

    rows = parse_results(html)
    priced = []
    for row in rows[:40]:
        price = extract_price_from_anchor_context(html, row["url"].replace("https://jp.mercari.com", ""))
        if price is not None:
            row["price"] = price
            priced.append(row)
        if len(priced) >= 20:
            break

    prices = [x["price"] for x in priced]
    if not prices:
        return {"query": query, "url": url, "count": 0, "prices": [], "items": []}

    prices_sorted = sorted(prices)
    median = int(statistics.median(prices_sorted))
    trimmed = prices_sorted[1:-1] if len(prices_sorted) >= 5 else prices_sorted
    robust = int(statistics.median(trimmed))
    return {
        "query": query,
        "url": url,
        "count": len(prices),
        "prices": prices_sorted,
        "median": median,
        "robust_median": robust,
        "low": min(prices),
        "high": max(prices),
        "items": priced[:10],
    }


def score_similarity(source_title, candidate_title):
    a = tokens(source_title)
    b = tokens(candidate_title)
    if not a or not b:
        return 0
    overlap = len(a & b) / max(1, len(a))
    # Exact/near model names are much stronger than generic shared words.
    model_hits = sum(1 for x in a & b if re.search(r"[a-z0-9]", x))
    return min(100, int(overlap * 75 + min(model_hits, 5) * 5))


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    checked = []
    for item in candidates[:MAX_CHECKS]:
        title = item.get("title", "").strip()
        if not title:
            continue
        # Prefer a brand plus title; otherwise use the title itself.
        brands = item.get("brands") or []
        brand = brands[0].get("name", "") if brands else ""
        query = " ".join(x for x in [brand, title] if x)
        result = market_lookup(query)
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

    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checked": checked,
        "note": "売り切れ/取引中の検索結果を使った市場確認。画像一致ではなく、まずタイトル・ブランド等のテキスト一致度を算出。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
