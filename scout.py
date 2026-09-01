import json
import math
import re
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

# 自宅付近（距離フィルタを実装するための基準点）
HOME_LAT = 35.168
HOME_LON = 136.873

SEARCH_URLS = [
    "https://jmty.jp/aichi/sale-fur",
    "https://jmty.jp/aichi/sale-fur/g-all/a-459-nagoya",
]

# プロボックス積載を想定した簡易上限
MAX_LENGTH_CM = 180
MAX_WIDTH_CM = 100
MAX_HEIGHT_CM = 100

PRIORITY_BRANDS = {
    "最優先": [
        "アーコール", "ercol", "ルイスポールセン", "louis poulsen",
        "イームズ", "eames", "artek", "アルテック", "g-plan", "ジープラン",
        "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet",
        "kartell", "flos", "artemide", "nathan", "ネイサン", "ヤマギワ",
        "yamag iwa", "マッキントッシュ", "ウェグナー", "wegner",
        "ボーエ・モーエンセン", "ボーエモーエンセン", "kai kristiansen",
        "カイ・クリスチャンセン", "フィリップ・スタルク", "philippe starck",
        "フロス", "アルテミデ",
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
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8", errors="ignore")


def normalize(text):
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_brands(text):
    low = text.lower()
    found = []
    seen = set()
    for priority, brands in PRIORITY_BRANDS.items():
        for brand in brands:
            if brand.lower() in low and brand.lower() not in seen:
                found.append({"name": brand, "priority": priority})
                seen.add(brand.lower())
    return found


def keyword_match(text):
    low = text.lower()
    return [k for k in KEYWORDS if k.lower() in low]


def extract_price(text):
    text = normalize(text)
    patterns = [
        r"(?:¥|￥)\s*([0-9０-９][0-9０-９,，]*)",
        r"([0-9０-９][0-9０-９,，]*)\s*円",
        r"([0-9０-９]{1,3}(?:[,，][0-9０-９]{3})+)\s*",
    ]
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).translate(table).replace(",", "").replace("，", "")
            try:
                price = int(value)
                if 100 <= price <= 2_000_000:
                    return price
            except ValueError:
                pass
    return None


def extract_size(text):
    patterns = [
        r"(\d{2,3})\s*[×xX]\s*(\d{2,3})\s*[×xX]\s*(\d{2,3})",
        r"幅\s*(\d{2,3}).{0,15}?奥行(?:き)?\s*(\d{2,3}).{0,15}?高さ\s*(\d{2,3})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            a, b, c = map(int, m.groups())
            return {"length": a, "width": b, "height": c}
    return None


def size_ok(size):
    if not size:
        return None
    values = sorted([size["length"], size["width"], size["height"]], reverse=True)
    return values[0] <= MAX_LENGTH_CM and values[1] <= MAX_WIDTH_CM and values[2] <= MAX_HEIGHT_CM


def distance_km(lat1, lon1, lat2, lon2):
    radius = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_sale_price(title, price, brands):
    """現段階は相場推定。実売履歴APIではないので「推定」と明記する。"""
    text = title.lower()
    if any(x in text for x in ["アーコール", "ercol"]):
        return max(price * 5, 20_000)
    if any(x in text for x in ["flos", "artemide", "ルイスポールセン", "louis poulsen"]):
        return max(price * 4, 25_000)
    if any(x in text for x in ["カリモク", "karimoku"]):
        return max(price * 3, 12_000)
    if any(x in text for x in ["kartell", "artek", "イームズ", "eames"]):
        return max(price * 4, 15_000)
    if brands:
        if brands[0]["priority"] in ["最優先", "照明"]:
            return max(price * 3, 10_000)
    return price * 2


def evaluate_item(title, price, text, url):
    brands = find_brands(text)
    keywords = keyword_match(text)
    size = extract_size(text)
    size_result = size_ok(size)

    if size_result is False:
        return None
    if not brands and not keywords:
        return None

    estimated_sale = estimate_sale_price(title, price, brands)
    # メルカリ手数料10%＋送料等を見込んだ保守的な概算
    net_sale = int(estimated_sale * 0.90)
    profit = net_sale - price
    if profit < MIN_PROFIT:
        return None

    score = 0
    if brands:
        score += 50 if brands[0]["priority"] == "最優先" else 30 if brands[0]["priority"] == "照明" else 20
    score += min(len(keywords) * 5, 20)
    if profit >= HIGH_PROFIT:
        score += 30
    elif profit >= MIN_PROFIT:
        score += 15
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
    """一覧ページからリンク周辺のテキストを使って商品候補を作る。
    DOM依存を減らし、価格がURL slugにない商品も拾えるようにする。
    """
    html = unescape(html)
    items = []
    seen = set()

    anchor_pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']*?/aichi/sale-[^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in anchor_pattern.finditer(html):
        href = match.group(1)
        anchor_html = match.group(2)
        url = "https://jmty.jp" + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)

        anchor_text = normalize(re.sub(r"<[^>]+>", " ", anchor_html))
        start = max(0, match.start() - 700)
        end = min(len(html), match.end() + 1200)
        context = normalize(re.sub(r"<[^>]+>", " ", html[start:end]))
        text = normalize(anchor_text + " " + context)

        price = extract_price(text)
        if price is None:
            continue

        title = anchor_text
        if not title or len(title) < 2:
            slug = href.rstrip("/").split("/")[-1]
            title = normalize(slug.replace("-", " "))

        items.append({"title": title, "price": price, "url": url, "text": text})
        if len(items) >= 150:
            break

    return items


def write_reports(candidates):
    candidates = sorted(candidates, key=lambda x: (-x["score"], -x["estimated_profit"]))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "max_distance_km": MAX_DISTANCE_KM,
            "min_profit": MIN_PROFIT,
            "high_profit": HIGH_PROFIT,
        },
        "candidates": candidates,
    }
    Path("resell_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Resell Scout 候補レポート",
        "",
        f"実行時刻: {payload['generated_at']}",
        f"候補数: {len(candidates)}",
        "",
        "> 利益は現段階では実売履歴ではなく、簡易相場推定です。",
        "",
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
            f"- URL: {item['url']}",
            "",
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

    unique = {}
    for item in candidates:
        unique[item["url"]] = item
    candidates = list(unique.values())

    write_reports(candidates)

    print("一覧から取得:", total_items)
    print("利益候補:", len(candidates))
    for item in sorted(candidates, key=lambda x: (-x["score"], -x["estimated_profit"]))[:10]:
        print(
            item["urgency"],
            item["title"],
            f"仕入れ={item['price']:,}円",
            f"利益推定={item['estimated_profit']:,}円",
            f"score={item['score']}",
        )


if __name__ == "__main__":
    main()
