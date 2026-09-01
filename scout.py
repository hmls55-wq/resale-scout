import json
import re
import time
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

MAX_DISTANCE_KM = 25
MIN_PROFIT = 5_000
HIGH_PROFIT = 15_000
MARKET_CHECK_MAX_PRICE = 5_000

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
        "フィリップ・スタルク", "philippe starck",
    ],
    "照明": [
        "le klint", "leklint", "フランク・ロイド・ライト", "frank lloyd wright",
        "ヤコブソンランプ", "jakobsson lamp", "foscarini", "フォスカリーニ",
        "nemo", "luceplan", "インゴ・マウラー", "ingo maurer", "tom dixon",
        "verpan", "vibia", "marset", "&tradition", "muuto",
    ],
    "高優先": [
        "マルニ", "maruni", "天童木工", "tendo", "無印良品", "muji",
        "cassina", "カッシーナ", "vitra", "ヴィトラ", "string", "ストリング",
        "magis", "マジス",
    ],
}

# 一般家具も候補に入れ、安い仕入れはメルカリ相場確認へ回す
MARKET_KEYWORDS = [
    "椅子", "イス", "チェア", "スツール", "ベンチ", "ソファ", "テーブル", "机", "デスク",
    "ダイニング", "食器棚", "キャビネット", "サイドボード", "チェスト", "タンス", "箪笥",
    "本棚", "書棚", "ラック", "シェルフ", "テレビ台", "収納家具", "収納", "ドレッサー",
    "鏡", "ミラー", "照明", "ライト", "ランプ", "ペンダント", "フロアライト",
    "木製", "無垢材", "無垢", "北欧", "ヴィンテージ", "ビンテージ", "アンティーク",
    "昭和レトロ", "レトロ", "デザイナーズ", "家具",
]

KEYWORDS = [
    *MARKET_KEYWORDS,
    "アーコール", "ercol", "ルイスポールセン", "louis poulsen", "イームズ", "eames",
    "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet", "kartell",
    "flos", "artemide", "artek", "アルテック", "ジープラン", "g-plan", "nathan", "ネイサン",
    "ヤマギワ", "ウェグナー", "wegner", "モーエンセン", "クリスチャンセン", "スタルク",
    "le klint", "foscarini", "nemo", "luceplan", "tom dixon", "verpan", "vibia", "marset",
    "muuto",
]


def fetch(url):
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.6 Safari/605.1.15",
    ]
    last_error = None
    for attempt, ua in enumerate(user_agents, 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Referer": "https://jmty.jp/",
            })
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


def strip_tags(text):
    return normalize(re.sub(r"<[^>]+>", " ", text))


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
    market_keywords = [k for k in keywords if k in MARKET_KEYWORDS]
    size = extract_size(text)
    size_result = size_ok(size)

    if size_result is False:
        return None
    if not brands and not keywords:
        return None

    # ブランド品は従来の利益推定で厳選
    if brands:
        estimated_sale = estimate_sale_price(title, price, brands)
        net_sale = int(estimated_sale * 0.90)
        profit = net_sale - price
        if profit < MIN_PROFIT:
            # 低価格ブランド品は相場確認候補として残す
            if price > MARKET_CHECK_MAX_PRICE:
                return None
            estimated_sale = None
            net_sale = None
            profit = None
            reason = "ブランド品・低仕入れ／メルカリ相場確認"
        else:
            reason = "簡易相場推定で利益基準クリア"
    else:
        # 一般家具は安いものを相場確認へ回す。ここでは利益を断定しない。
        if not market_keywords or price > MARKET_CHECK_MAX_PRICE:
            return None
        estimated_sale = None
        net_sale = None
        profit = None
        reason = "低価格家具／メルカリ相場確認"

    score = 0
    if brands:
        score += 60 if brands[0]["priority"] == "最優先" else 40 if brands[0]["priority"] == "照明" else 30
    score += min(len(keywords) * 5, 25)
    if price == 0:
        score += 20
    elif price <= 1_000:
        score += 15
    elif price <= MARKET_CHECK_MAX_PRICE:
        score += 10
    if profit is not None:
        score += 30 if profit >= HIGH_PROFIT else 15
    if size_result is None:
        score -= 5

    urgency = "🔥 緊急" if profit is not None and profit >= HIGH_PROFIT else "🔎 相場確認"
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
        "urgency": urgency,
        "reason": reason,
        "url": url,
    }


def extract_items(html):
    """商品リンク単位で次の商品リンクまでを1ブロックとして解析する。"""
    html = unescape(html)
    items, seen = [], set()
    href_pattern = re.compile(r'''href=["']([^"']*article-[a-z0-9]+)["']''', re.I)
    matches = list(href_pattern.finditer(html))
    print("  商品リンク候補:", len(matches))

    for index, match in enumerate(matches):
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

        # 同じ商品カード内だけを見る。次の商品リンクを境界にする。
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(html), match.end() + 3000)
        block = html[match.start():end]
        text = strip_tags(block)
        price = extract_price(text)
        if price is None:
            continue

        # アンカー文字列を商品タイトルとして取得
        title = ""
        anchor = re.search(r'''<a[^>]+href=["']''' + re.escape(href) + r'''["'][^>]*>(.*?)</a>''', block, re.I | re.S)
        if anchor:
            title = strip_tags(anchor.group(1))
        if not title:
            title = url.rsplit("/", 1)[-1]

        items.append({"title": title, "price": price, "url": url, "text": text})
        if len(items) >= 300:
            break

    return items


def sort_key(item):
    profit = item.get("estimated_profit")
    return (-item.get("score", 0), -(profit if isinstance(profit, int) else -1), item.get("price", 0))


def write_reports(candidates, total_items):
    candidates = sorted(candidates, key=sort_key)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "max_distance_km": MAX_DISTANCE_KM,
            "min_profit": MIN_PROFIT,
            "high_profit": HIGH_PROFIT,
            "market_check_max_price": MARKET_CHECK_MAX_PRICE,
        },
        "source_items": total_items,
        "candidates": candidates,
    }
    Path("resell_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Resell Scout 候補レポート", "",
        f"実行時刻: {payload['generated_at']}",
        f"一覧から取得: {total_items}",
        f"候補数: {len(candidates)}", "",
        "> 🔎 相場確認候補は利益を断定していません。メルカリ検索で相場を確認する前提です。", "",
    ]
    for i, item in enumerate(candidates[:30], 1):
        brands = ", ".join(x["name"] for x in item["brands"]) or "-"
        profit = item.get("estimated_profit")
        sale = item.get("estimated_sale_price")
        profit_text = f"{profit:,}円" if isinstance(profit, int) else "要メルカリ相場確認"
        sale_text = f"{sale:,}円" if isinstance(sale, int) else "要メルカリ相場確認"
        lines += [
            f"## {i}. {item['urgency']} {item['title']}",
            f"- 仕入れ: {item['price']:,}円",
            f"- 売価推定: {sale_text}",
            f"- 利益推定: {profit_text}",
            f"- 判定理由: {item['reason']}",
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
    print("相場確認対象の仕入れ上限:", f"{MARKET_CHECK_MAX_PRICE:,}円")

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
    print("利益/相場確認候補:", len(candidates))
    for item in sorted(candidates, key=sort_key)[:10]:
        profit = item.get("estimated_profit")
        profit_text = f"{profit:,}円" if isinstance(profit, int) else "要相場確認"
        print(item["urgency"], item["title"], f"仕入れ={item['price']:,}円", f"利益={profit_text}", f"score={item['score']}")


if __name__ == "__main__":
    main()
