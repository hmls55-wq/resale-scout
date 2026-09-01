import json
import math
import re
import time
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

# ============================================================
# Resell Scout
# ジモティー新着から「仕入れ候補」を抽出するMVP
# ============================================================

MAX_DISTANCE_KM = 25
MIN_PROFIT = 5_000
HIGH_PROFIT = 15_000

SEARCH_URLS = [
    "https://jmty.jp/aichi/sale-fur",
    "https://jmty.jp/aichi/sale-fur/g-all/a-459-nagoya",
]

MAX_LENGTH_CM = 180
MAX_WIDTH_CM = 100
MAX_HEIGHT_CM = 100

PRIORITY_BRANDS = {
    "最優先": [
        "アーコール", "ercol", "ルイスポールセン", "louis poulsen",
        "イームズ", "eames", "artek", "アルテック", "g-plan", "ジープラン",
        "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet",
        "kartell", "flos", "artemide", "nathan", "ネイサン", "ヤマギワ",
        "マッキントッシュ", "ウェグナー", "wegner", "ボーエ・モーエンセン",
        "ボーエモーエンセン", "kai kristiansen", "カイ・クリスチャンセン",
        "フィリップ・スタルク", "philippe starck", "フロス", "アルテミデ",
    ],
    "照明": [
        "le klint", "leklint", "フランク・ロイド・ライト", "frank lloyd wright",
        "jakobsson lamp", "ヤコブソンランプ", "foscarini", "フォスカリーニ",
        "nemo", "luceplan", "インゴ・マウラー", "ingo maurer", "dcw editions",
        "davide groppi", "tom dixon", "verpan", "vibia", "marset", "and tradition",
        "&tradition", "astep", "lzf", "estiluz", "northern", "muuto",
    ],
    "高優先": [
        "マルニ", "maruni", "天童木工", "tendo", "無印良品", "muji",
        "cassina", "カッシーナ", "vitra", "ヴィトラ", "string", "ストリング",
        "magis", "マジス",
    ],
}

KEYWORDS = [
    "アーコール", "ercol", "ルイスポールセン", "louis poulsen", "イームズ", "eames",
    "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet", "kartell",
    "flos", "artemide", "artek", "アルテック", "ジープラン", "g-plan", "nathan", "ネイサン",
    "ヤマギワ", "ウェグナー", "wegner", "モーエンセン", "クリスチャンセン", "スタルク",
    "le klint", "foscarini", "nemo", "luceplan", "tom dixon", "verpan", "vibia", "marset",
    "muuto", "デザイナーズ", "デザイナーズ家具", "ヴィンテージ家具", "ヴィンテージチェア",
    "北欧家具", "北欧ヴィンテージ", "デザインチェア", "デザイン照明", "ペンダントライト",
    "テーブルランプ", "フロアライト",
]


def fetch(url):
    """ジモティーのHTMLを取得。GitHub Actions向けにUA/Acceptを強化して再試行する。"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    ]
    last_error = None
    for attempt, ua in enumerate(user_agents, 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Cache-Control": "no-cache",
                    "Referer": "https://jmty.jp/",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode("utf-8", errors="ignore")
                print(f"  HTTP {response.status}, HTML {len(html):,} bytes")
                if len(html) < 5_000:
                    raise RuntimeError(f"HTMLが短すぎます ({len(html)} bytes)")
                return html
        except Exception as exc:
            last_error = exc
            print(f"  取得リトライ {attempt}: {exc!r}")
            time.sleep(2)
    raise RuntimeError(f"ジモティー取得失敗: {last_error!r}")


def normalize(text):
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_brands(text):
    low = text.lower()
    found, seen = [], set()
    for priority, brands in PRIORITY_BRANDS.items():
        for brand in brands:
            key = brand.lower()
            if key in low and key not in seen:
                found.append({"name": brand, "priority": priority})
                seen.add(key)
    return found


def keyword_match(text):
    low = text.lower()
    return [k for k in KEYWORDS if k.lower() in low]


def extract_price(text):
    text = normalize(text)
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    patterns = [
        r"(?:¥|￥)\s*([0-9０-９][0-9０-９,，]*)",
        r"([0-9０-９][0-9０-９,，]*)\s*円",
        r"([0-9０-９]{1,3}(?:[,，][0-9０-９]{3})+)\s*円?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).translate(table).replace(",", "").replace("，", "")
            try:
                price = int(value)
                if 0 <= price <= 2_000_000:
                    return price
            except ValueError:
                pass
    if re.search(r"(?:^|\s)(?:無料|0円)(?:\s|$)", text):
        return 0
    return None


def extract_size(text):
    patterns = [
        r"(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)",
        r"幅\s*(\d{2,4}).{0,20}?奥行(?:き)?\s*(\d{2,4}).{0,20}?高さ\s*(\d{2,4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            a, b, c = map(float, m.groups())
            return {"length": a, "width": b, "height": c}
    return None


def size_ok(size):
    if not size:
        return None
    values = sorted([size["length"], size["width"], size["height"]], reverse=True)
    return values[0] <= MAX_LENGTH_CM and values[1] <= MAX_WIDTH_CM and values[2] <= MAX_HEIGHT_CM


def estimate_sale_price(title, price, brands):
    text = title.lower()
    if any(x in text for x in ["アーコール", "ercol"]):
        return max(price * 5, 20_000)
    if any(x in text for x in ["flos", "artemide", "ルイスポールセン", "louis poulsen"]):
        return max(price * 4, 25_000)
    if any(x in text for x in ["カリモク", "karimoku"]):
        return max(price * 3, 12_000)
    if any(x in text for x in ["kartell", "artek", "イームズ", "eames"]):
        return max(price * 4, 15_000)
    if brands and brands[0]["priority"] in ["最優先", "照明"]:
        return max(price * 3, 10_000)
    return price * 2


def evaluate_item(title, price, text, url):
    brands = find_brands(text)
    keywords = keyword_match(text)
    size = extract_size(text)
    size_result = size_ok(size)
    if size_result is False or (not brands and not keywords):
        return None

    estimated_sale = estimate_sale_price(title, price, brands)
    net_sale = int(estimated_sale * 0.90)
    profit = net_sale - price
    if profit < MIN_PROFIT:
        return None

    score = 0
    if brands:
        score += 50 if brands[0]["priority"] == "最優先" else 30 if brands[0]["priority"] == "照明" else 20
    score += min(len(keywords) * 5, 20)
    score += 30 if profit >= HIGH_PROFIT else 15
    if size_result is None:
        score -= 5

    return {
        "title": title[:120],
        "price": price,
        "estimated_sale_price": estimated_sale,
        "estimated_net_sale": net_sale,
        "estimated_profit": profit,
        "brands": brands,
        "keywords": keywords,
        "size": size,
        "size_ok": size_result,
        "score": score,
        "urgency": "🔥 緊急" if profit >= HIGH_PROFIT else "⚡ 有力",
        "url": url,
    }


def extract_items(html):
    """記事リンクを広く拾う。ジモティー側のHTML変更で0件になりにくい実装。"""
    html = unescape(html)
    items, seen = [], set()

    # 旧構造/新構造の両方に対応。/article-xxxxx が商品ページ。
    href_pattern = re.compile(r'''href=["']([^"']*/(?:aichi/)?sale-[^"']*article-[^"']+)["']''', re.I)
    matches = list(href_pattern.finditer(html))
    if not matches:
        # hrefの途中に /s/ 等が入るケースも拾う
        href_pattern = re.compile(r'''href=["']([^"']*article-[a-z0-9]+)["']''', re.I)
        matches = list(href_pattern.finditer(html))

    print("  商品リンク候補:", len(matches))

    for match in matches:
        href = match.group(1)
        if href.startswith("/"):
            url = "https://jmty.jp" + href
        elif href.startswith("http"):
            url = href
        else:
            continue
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)

        # アンカー周辺から商品名・価格・説明をまとめて取得
        start = max(0, match.start() - 600)
        end = min(len(html), match.end() + 1800)
        block = html[start:end]
        clean = normalize(re.sub(r"<[^>]+>", " ", block))
        price = extract_price(clean)
        if price is None:
            continue

        # リンクタグ自身の文字列を優先してタイトル化
        title = ""
        a_match = re.search(r'''<a[^>]+href=["']''' + re.escape(href) + r'''["'][^>]*>(.*?)</a>''', html, re.I | re.S)
        if a_match:
            title = normalize(re.sub(r"<[^>]+>", " ", a_match.group(1)))
        if not title:
            # 商品リンクの直後/直前にあるテキストから短い候補を作る
            candidates = [x.strip() for x in re.split(r"\s{2,}", clean) if 2 <= len(x.strip()) <= 120]
            title = candidates[0] if candidates else url.rsplit("/", 1)[-1]

        items.append({"title": title, "price": price, "url": url, "text": clean})
        if len(items) >= 300:
            break

    return items


def write_reports(candidates, total_items):
    candidates = sorted(candidates, key=lambda x: (-x["score"], -x["estimated_profit"]))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {"max_distance_km": MAX_DISTANCE_KM, "min_profit": MIN_PROFIT, "high_profit": HIGH_PROFIT},
        "source_items": total_items,
        "candidates": candidates,
    }
    Path("resell_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Resell Scout 候補レポート", "",
        f"実行時刻: {payload['generated_at']}",
        f"一覧から取得: {total_items}",
        f"候補数: {len(candidates)}", "",
        "> 利益は現段階では実売履歴ではなく、簡易相場推定です。", "",
    ]
    for i, item in enumerate(candidates[:30], 1):
        brands = ", ".join(x["name"] for x in item["brands"]) or "-"
        lines += [
            f"## {i}. {item['urgency']} {item['title']}",
            f"- 仕入れ: {item['price']:,}円",
            f"- 売価推定: {item['estimated_sale_price']:,}円",
            f"- 手数料考慮後利益推定: {item['estimated_profit']:,}円",
            f"- スコア: {item['score']}",
            f"- ブランド: {brands}",
            f"- URL: {item['url']}", "",
        ]
    Path("resell_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    print("========================================")
    print("           Resell Scout")
    print("========================================")
    print("引き取り範囲:", MAX_DISTANCE_KM, "km")
    print("最低利益:", f"{MIN_PROFIT:,}円")

    candidates = []
    total_items = 0
    for search_url in SEARCH_URLS:
        print("チェック:", search_url)
        try:
            html = fetch(search_url)
            items = extract_items(html)
            total_items += len(items)
            print("取得候補:", len(items))
            for item in items:
                result = evaluate_item(item["title"], item["price"], item["text"], item["url"])
                if result:
                    candidates.append(result)
        except Exception as exc:
            print("取得失敗:", repr(exc))

    unique = {item["url"]: item for item in candidates}
    candidates = list(unique.values())
    write_reports(candidates, total_items)

    print("一覧から取得:", total_items)
    print("利益候補:", len(candidates))
    for item in sorted(candidates, key=lambda x: (-x["score"], -x["estimated_profit"]))[:10]:
        print(item["urgency"], item["title"], f"仕入れ={item['price']:,}円", f"利益推定={item['estimated_profit']:,}円", f"score={item['score']}")


if __name__ == "__main__":
    main()
