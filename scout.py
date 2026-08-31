from datetime import datetime

print("================================")
print("Resell Scout 起動")
print("================================")

print("実行時刻:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

# テスト用の商品データ
items = [
    {
        "title": "ヴィンテージ アーコール チェア",
        "price": 3000,
        "location": "名古屋市",
        "url": "https://example.com"
    },
    {
        "title": "普通のダイニングチェア",
        "price": 5000,
        "location": "名古屋市",
        "url": "https://example.com"
    }
]

# 監視ブランド
brands = [
    "アーコール",
    "ERCOL",
    "G-PLAN",
    "Nathan",
    "飛騨産業",
    "カリモク",
    "TON",
    "THONET",
    "Kartell",
    "FLOS",
    "Artemide",
    "Louis Poulsen",
    "YAMAGIWA",
    "Eames",
    "Artek",
    "Macintosh",
    "ウェグナー",
    "ボーエ・モーエンセン",
    "カイ・クリスチャンセン",
    "フィリップ・スタルク"
]

print()
print("商品をチェックします")
print("--------------------------------")

for item in items:
    matched = []

    for brand in brands:
        if brand.lower() in item["title"].lower():
            matched.append(brand)

    if matched:
        print("🔥 候補発見")
        print("商品:", item["title"])
        print("価格:", f'{item["price"]:,}円')
        print("場所:", item["location"])
        print("ブランド:", ", ".join(matched))
        print("URL:", item["url"])
        print("--------------------------------")
    else:
        print("スルー:", item["title"])

print()
print("Resell Scout テスト完了")
