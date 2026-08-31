from datetime import datetime

print("========================================")
print("        Resell Scout")
print("========================================")
print("実行時刻:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print()

# ========================================
# 設定
# ========================================

MAX_DISTANCE_KM = 25

# プロボックス積載を想定した簡易サイズ上限
MAX_LENGTH_CM = 180
MAX_WIDTH_CM = 100
MAX_HEIGHT_CM = 100

# 利益判定
MIN_PROFIT = 5000
HIGH_PROFIT = 15000

# ========================================
# ブランド辞書
# ========================================

priority_brands = {

    # ★ 最優先
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
        "nathan",
        "ネイサン",
        "飛騨産業",
        "hida sangyo",
        "ton",
        "thonet",
        "kartell",
        "カリモク",
        "karimoku",
        "flos",
        "artemide"
    ],

    # ★ 高優先
    "高優先": [
        "macintosh",
        "ヤマギワ",
        "yamagiwa",
        "ウェグナー",
        "wegner",
        "ボーエ・モーエンセン",
        "ボーエモーエンセン",
        "børge mogensen",
        "カイ・クリスチャンセン",
        "kai kristiansen",
        "フィリップ・スタルク",
        "philippe starck"
    ]
}


# ========================================
# 商品カテゴリー
# ========================================

categories = {
    "家具": [
        "チェア",
        "椅子",
        "イス",
        "chair",
        "テーブル",
        "table",
        "デスク",
        "desk",
        "ソファ",
        "sofa",
        "キャビネット",
        "cabinet",
        "チェスト",
        "chest",
        "棚",
        "ラック",
        "スツール",
        "stool"
    ],

    "照明": [
        "照明",
        "ライト",
        "ランプ",
        "lamp",
        "light",
        "ペンダント",
        "pendant",
        "フロアライト",
        "テーブルランプ"
    ]
}


# ========================================
# テスト用商品データ
# ※次の段階でジモティーのデータに置き換える
# ========================================

items = [

    {
        "title": "アーコール ヴィンテージチェア",
        "price": 3000,
        "estimated_sale": 25000,
        "distance": 8,
        "length": 85,
        "width": 50,
        "height": 80
    },

    {
        "title": "カリモク ダイニングチェア",
        "price": 2000,
        "estimated_sale": 12000,
        "distance": 15,
        "length": 60,
        "width": 60,
        "height": 90
    },

    {
        "title": "ルイスポールセン ペンダントライト",
        "price": 5000,
        "estimated_sale": 35000,
        "distance": 20,
        "length": 60,
        "width": 60,
        "height": 50
    },

    {
        "title": "大型3人掛けソファ",
        "price": 3000,
        "estimated_sale": 20000,
        "distance": 10,
        "length": 210,
        "width": 90,
        "height": 90
    }
]


# ========================================
# ブランド判定
# ========================================

def find_brands(title):

    title_lower = title.lower()

    found = []
    rank = "対象外"

    for priority, brand_list in priority_brands.items():

        for brand in brand_list:

            if brand.lower() in title_lower:

                found.append(brand)

                if priority == "最優先":
                    rank = "最優先"

                elif rank != "最優先":
                    rank = "高優先"

    return found, rank


# ========================================
# カテゴリー判定
# ========================================

def find_category(title):

    title_lower = title.lower()

    for category, words in categories.items():

        for word in words:

            if word.lower() in title_lower:
                return category

    return "その他"


# ========================================
# サイズ判定
# ========================================

def check_size(item):

    if item["length"] > MAX_LENGTH_CM:
        return False

    if item["width"] > MAX_WIDTH_CM:
        return False

    if item["height"] > MAX_HEIGHT_CM:
        return False

    return True


# ========================================
# 利益計算
# ========================================

def calculate_profit(item):

    purchase = item["price"]
    sale = item["estimated_sale"]

    # メルカリ手数料10%を仮設定
    fee = sale * 0.10

    profit = sale - fee - purchase

    return int(profit)


# ========================================
# 総合判定
# ========================================

def judge(item, rank, profit, size_ok):

    if item["distance"] > MAX_DISTANCE_KM:
        return "スルー"

    if not size_ok:
        return "スルー"

    if rank == "最優先" and profit >= HIGH_PROFIT:
        return "🔥 最優先"

    if rank in ["最優先", "高優先"] and profit >= MIN_PROFIT:
        return "◎ 仕入れ候補"

    if profit >= MIN_PROFIT:
        return "△ 要確認"

    return "スルー"


# ========================================
# 商品チェック
# ========================================

print("商品チェック開始")
print("----------------------------------------")

for item in items:

    title = item["title"]

    brands, rank = find_brands(title)

    category = find_category(title)

    size_ok = check_size(item)

    profit = calculate_profit(item)

    result = judge(
        item,
        rank,
        profit,
        size_ok
    )

    if result != "スルー":

        print()
        print("🔥", result)
        print("商品:", title)
        print("カテゴリー:", category)
        print("仕入れ価格:", f'{item["price"]:,}円')
        print("想定販売価格:", f'{item["estimated_sale"]:,}円')
        print("想定利益:", f'{profit:,}円')
        print("距離:", f'{item["distance"]}km')
        print(
            "サイズ:",
            f'{item["length"]} × '
            f'{item["width"]} × '
            f'{item["height"]}cm'
        )

        if brands:
            print("ブランド:", ", ".join(brands))

        print("判定:", result)
        print("----------------------------------------")

    else:

        print("スルー:", title)


print()
print("========================================")
print("Resell Scout テスト完了")
print("========================================")
