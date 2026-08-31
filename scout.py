import re
import math
import urllib.request
from html import unescape
from datetime import datetime

# ============================================================
# Resell Scout
# ジモティー公開ページから仕入れ候補を探すMVP
# ============================================================

# ------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------

MAX_DISTANCE_KM = 25

# プロボックス積載を想定した簡易上限
MAX_LENGTH_CM = 180
MAX_WIDTH_CM = 100
MAX_HEIGHT_CM = 100

MIN_PROFIT = 5000
HIGH_PROFIT = 15000

# 自宅位置
# ※ここは後で自宅付近の緯度・経度を設定する
# 現在は名古屋市中村区付近を仮設定
HOME_LAT = 35.168
HOME_LON = 136.873

# ------------------------------------------------------------
# 優先ブランド
# ------------------------------------------------------------

PRIORITY_BRANDS = {

    "最優先": [
        "アーコール",
        "ercol",
        "ルイスポールセン",
        "louis poulsen",
        "イームズ",
        "eames",
        "artek",
        "アルテック",
        "g-plan",
        "ジープラン",
        "カリモク",
        "karimoku",
        "飛騨産業",
        "hida sangyo",
        "ton",
        "thonet",
        "kartell",
        "flos",
        "artemide",
        "nathan",
        "ネイサン",
        "ヤマギワ",
        "yamag iwa",
        "yamagawa",
        "yamag iwa",
        "macintosh",
        "マッキントッシュ",
        "ウェグナー",
        "wegner",
        "ボーエ・モーエンセン",
        "ボーエモーエンセン",
        "børge mogensen",
        "kai kristiansen",
        "カイ・クリスチャンセン",
        "フィリップ・スタルク",
        "philippe starck",
        "フロス",
        "アルテミデ",
    ],

    "照明": [
        "le klint",
        "leklint",
        "フランク・ロイド・ライト",
        "frank lloyd wright",
        "jakobsson lamp",
        "ヤコブソンランプ",
        "foscarini",
        "フォスカリーニ",
        "nemo",
        "luceplan",
        "インゴ・マウラー",
        "ingo maurer",
        "dcw éditions",
        "dcw editions",
        "davide groppi",
        "tom dixon",
        "verpan",
        "vibia",
        "marset",
        "and tradition",
        "&tradition",
        "astep",
        "lzf",
        "estiluz",
        "northern",
        "muuto",
        "nordic modern",
    ],

    "高優先": [
        "マルニ",
        "maruni",
        "天童木工",
        "tendo",
        "無印良品",
        "muji",
        "cassina",
        "カッシーナ",
        "vitra",
        "ヴィトラ",
        "string",
        "ストリング",
        "magis",
        "マジス",
    ]
}

# ------------------------------------------------------------
# 検索キーワード
# ------------------------------------------------------------

KEYWORDS = [
    "アーコール",
    "ercol",
    "ルイスポールセン",
    "louis poulsen",
    "イームズ",
    "eames",
    "カリモク",
    "karimoku",
    "飛騨産業",
    "hida sangyo",
    "ton",
    "thonet",
    "kartell",
    "flos",
    "artemide",
    "artek",
    "アルテック",
    "ジープラン",
    "g-plan",
    "nathan",
    "ネイサン",
    "ヤマギワ",
    "yamag iwa",
    "ウェグナー",
    "wegner",
    "モーエンセン",
    "クリスチャンセン",
    "スタルク",
    "le klint",
    "foscarini",
    "nemo",
    "luceplan",
    "tom dixon",
    "verpan",
    "vibia",
    "marset",
    "muuto",
    "デザイナーズ",
    "デザイナーズ家具",
    "ヴィンテージ家具",
    "ヴィンテージチェア",
    "北欧家具",
    "北欧ヴィンテージ",
    "デザインチェア",
    "デザイン照明",
    "ペンダントライト",
    "テーブルランプ",
    "フロアライト",
]

# ------------------------------------------------------------
# ジモティー検索ページ
# ------------------------------------------------------------

SEARCH_URLS = [
    "https://jmty.jp/aichi/sale-fur",
    "https://jmty.jp/aichi/sale-fur/g-all/a-459-nagoya",
]

# ------------------------------------------------------------
# HTTP取得
# ------------------------------------------------------------

def fetch(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        )
    }

    request = urllib.request.Request(
        url,
        headers=headers
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="ignore"
        )


# ------------------------------------------------------------
# ブランド判定
# ------------------------------------------------------------

def find_brands(text):

    text_lower = text.lower()

    found = []

    for priority, brands in PRIORITY_BRANDS.items():

        for brand in brands:

            if brand.lower() in text_lower:

                found.append({
                    "name": brand,
                    "priority": priority
                })

    return found


# ------------------------------------------------------------
# キーワード判定
# ------------------------------------------------------------

def keyword_match(text):

    text_lower = text.lower()

    found = []

    for keyword in KEYWORDS:

        if keyword.lower() in text_lower:

            found.append(keyword)

    return found


# ------------------------------------------------------------
# 価格取得
# ------------------------------------------------------------

def extract_price(text):

    matches = re.findall(
        r'([0-9０-９]{1,3}(?:[,，][0-9０-９]{3})*|[0-9０-９]+)\s*円',
        text
    )

    if not matches:
        return None

    value = matches[0]

    value = value.replace(",", "")
    value = value.replace("，", "")

    # 全角数字
    table = str.maketrans(
        "０１２３４５６７８９",
        "0123456789"
    )

    value = value.translate(table)

    try:
        return int(value)
    except:
        return None


# ------------------------------------------------------------
# 商品サイズ取得
# ------------------------------------------------------------

def extract_size(text):

    patterns = [
        r'(\d{2,3})\s*[×xX]\s*(\d{2,3})\s*[×xX]\s*(\d{2,3})',
        r'幅\s*(\d{2,3}).{0,10}高さ\s*(\d{2,3})',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            values = [
                int(x)
                for x in match.groups()
            ]

            if len(values) == 3:

                return {
                    "length": values[0],
                    "width": values[1],
                    "height": values[2]
                }

    return None


# ------------------------------------------------------------
# サイズ判定
# ------------------------------------------------------------

def size_ok(size):

    if not size:
        # サイズ記載なしは
        # 自動除外せず「要確認」
        return None

    values = [
        size["length"],
        size["width"],
        size["height"]
    ]

    values.sort(reverse=True)

    return (
        values[0] <= MAX_LENGTH_CM
        and
        values[1] <= MAX_WIDTH_CM
        and
        values[2] <= MAX_HEIGHT_CM
    )


# ------------------------------------------------------------
# 距離計算
# ------------------------------------------------------------

def distance_km(lat1, lon1, lat2, lon2):

    radius = 6371

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        +
        math.cos(p1)
        *
        math.cos(p2)
        *
        math.sin(dl / 2) ** 2
    )

    return (
        2
        *
        radius
        *
        math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )


# ------------------------------------------------------------
# 利益推定
# ------------------------------------------------------------

def estimate_sale_price(title, price, brands):

    text = title.lower()

    # ブランド別の簡易推定
    # 後で実際のメルカリ販売実績に置き換える

    if any(
        x in text
        for x in [
            "アーコール",
            "ercol"
        ]
    ):
        return max(price * 5, 20000)

    if any(
        x in text
        for x in [
            "flos",
            "artemide",
            "ルイスポールセン",
            "louis poulsen"
        ]
    ):
        return max(price * 4, 25000)

    if any(
        x in text
        for x in [
            "カリモク",
            "karimoku"
        ]
    ):
        return max(price * 3, 12000)

    if any(
        x in text
        for x in [
            "kartell",
            "artek",
            "イームズ",
            "eames"
        ]
    ):
        return max(price * 4, 15000)

    if brands:

        if brands[0]["priority"] == "最優先":
            return max(price * 3, 10000)

        if brands[0]["priority"] == "照明":
            return max(price * 3, 10000)

    return price * 2


# ------------------------------------------------------------
# 商品評価
# ------------------------------------------------------------

def evaluate_item(title, price, text):

    brands = find_brands(text)

    keywords = keyword_match(text)

    size = extract_size(text)

    size_result = size_ok(size)

    estimated_sale = estimate_sale_price(
        title,
        price,
        brands
    )

    profit = estimated_sale - price

    # 明らかに大型なら除外
    if size_result is False:

        return None

    # ブランドもキーワードも無ければ除外
    if not brands and not keywords:

        return None

    # 最低利益未満
    if profit < MIN_PROFIT:

        return None

    if profit >= HIGH_PROFIT:

        urgency = "🔥 緊急"

    else:

        urgency = "⚡ 有力"

    return {
        "title": title,
        "price": price,
        "estimated_sale": estimated_sale,
        "profit": profit,
        "brands": brands,
        "keywords": keywords,
        "size": size,
        "size_ok": size_result,
        "urgency": urgency,
    }


# ------------------------------------------------------------
# ジモティー商品抽出
# ------------------------------------------------------------

def extract_items(html):

    html = unescape(html)

    items = []

    # ジモティーの商品ページURL
    urls = re.findall(
        r'href=["\'](\/aichi\/sale-[^"\']+)["\']',
        html
    )

    # 重複除去
    unique_urls = []

    for url in urls:

        if url not in unique_urls:

            unique_urls.append(url)

    # ページ内テキストから候補を作る
    for url in unique_urls[:100]:

        full_url = "https://jmty.jp" + url

        # URLから簡易タイトルを推定
        slug = url.split("/")[-1]

        slug = slug.replace("-", " ")

        title = slug[:100]

        # URL自体にもブランド名が含まれる場合がある
        text = title

        price = extract_price(text)

        # URLだけでは価格が取れない場合
        # ページ全体からの詳細取得は次段階で実装
        if price is None:

            continue

        items.append({
            "title": title,
            "price": price,
            "url": full_url,
            "text": text
        })

    return items


# ------------------------------------------------------------
# メイン
# ------------------------------------------------------------

def main():

    print()
    print("========================================")
    print("        Resell Scout")
    print("========================================")

    print(
        "実行時刻:",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print()
    print("設定")
    print("----------------------------------------")
    print(
        "引き取り範囲:",
        MAX_DISTANCE_KM,
        "km"
    )
    print(
        "最低利益:",
        f"{MIN_PROFIT:,}円"
    )
    print(
        "高利益:",
        f"{HIGH_PROFIT:,}円"
    )
    print()

    candidates = []

    for url in SEARCH_URLS:

        print("チェック:", url)

        try:

            html = fetch(url)

            items = extract_items(html)

            print(
                "取得候補:",
                len(items)
            )

            for item in items:

                result = evaluate_item(
                    item["title"],
                    item["price"],
                    item["text"]
                )

                if result:

                    result["url"] = item["url"]

                    candidates.append(result)

        except Exception as e:

            print(
                "取得エラー:",
                str(e)
            )

    # 重複除去
    unique = {}

    for item in candidates:

        unique[item["url"]] = item

    candidates = list(unique.values())

    print()
    print("========================================")
    print("候補結果")
    print("========================================")

    if not candidates:

        print()
        print("新しい有力候補なし")
        print("通知対象なし")

    else:

        # 利益順
        candidates.sort(
            key=lambda x: x["profit"],
            reverse=True
        )

        for item in candidates[:20]:

            print()
            print(item["urgency"])
            print(
                "商品:",
                item["title"]
            )

            print(
                "仕入れ価格:",
                f'{item["price"]:,}円'
            )

            print(
                "想定販売価格:",
                f'{item["estimated_sale"]:,}円'
            )

            print(
                "想定利益:",
                f'{item["profit"]:,}円'
            )

            if item["brands"]:

                print(
                    "ブランド:",
                    ", ".join(
                        x["name"]
                        for x in item["brands"]
                    )
                )

            if item["keywords"]:

                print(
                    "キーワード:",
                    ", ".join(
                        item["keywords"][:10]
                    )
                )

            if item["size"]:

                print(
                    "サイズ:",
                    item["size"]
                )

                print(
                    "プロボックス:",
                    "積載可能"
                    if item["size_ok"]
                    else "積載困難"
                )

            else:

                print(
                    "サイズ:",
                    "記載なし・要確認"
                )

            print(
                "URL:",
                item["url"]
            )

            print("----------------------------------------")

    print()
    print("========================================")
    print("Resell Scout 終了")
    print("========================================")


if __name__ == "__main__":
    main()
