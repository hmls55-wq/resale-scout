import json
from pathlib import Path

import scout

INPUT = Path('resell_candidates.json')

SEARCH_URLS = [
    ('家電', 'https://jmty.jp/aichi/sale-ele'),
    ('家電・名古屋', 'https://jmty.jp/aichi/sale-ele/g-all/a-459-nagoya'),
    ('おもちゃ', 'https://jmty.jp/aichi/sale-toy'),
    ('おもちゃ・名古屋', 'https://jmty.jp/aichi/sale-toy/g-all/a-459-nagoya'),
    ('生活雑貨', 'https://jmty.jp/aichi/sale-hom'),
    ('生活雑貨・名古屋', 'https://jmty.jp/aichi/sale-hom/g-all/a-459-nagoya'),
]

EXTRA_KEYWORDS = [
    '工具', '電動工具', 'インパクト', 'インパクトドライバー', 'ドリル', '丸ノコ',
    'グラインダー', 'ジグソー', '切断機', 'コンプレッサー', '溶接機', '測定器',
    'マキタ', 'makita', 'ハイコーキ', 'hikoki', '日立工機', 'ボッシュ', 'bosch',
    'リョービ', 'ryobi', 'ケルヒャー', 'karcher',
    'テレビ', 'レコーダー', '冷蔵庫', '洗濯機', '掃除機', 'ロボット掃除機', '炊飯器',
    '電子レンジ', 'オーブンレンジ', '食洗機', '空気清浄機', '加湿器', '除湿機',
    'エアコン', '扇風機', 'ゲーム機', 'ゲームソフト', 'カメラ', 'レンズ', 'オーディオ',
    'ダイソン', 'dyson', 'パナソニック', 'panasonic', 'ソニー', 'sony', 'シャープ',
    'sharp', '日立', 'hitachi', '東芝', 'toshiba', 'アイリスオーヤマ', '山善',
    'switch', 'ニンテンドー', 'nintendo', 'ps5', 'ps4', 'プレイステーション', 'ゲームボーイ',
    'ポケモン', 'ポケモンカード', 'トレーディングカード', 'トミカ', 'プラレール',
    'フィギュア', 'プラモデル', '模型', 'ミニカー', 'ラジコン', 'lego', 'レゴ',
    'ガンプラ', 'ガンダム', '遊戯王', 'ワンピースカード', 'ドラゴンボールカード',
    'ブランド食器', '食器セット', 'バカラ', 'baccarat', 'ウェッジウッド', 'wedgwood',
    'ロイヤルコペンハーゲン', 'marimekko', 'マリメッコ', 'イッタラ', 'iittala',
    'ル・クルーゼ', 'le creuset', 'ストウブ', 'staub', 'ティファール', 't-fal',
]

EXTRA_BRANDS = {
    '再販強': [
        'マキタ', 'makita', 'ハイコーキ', 'hikoki', 'ボッシュ', 'bosch', 'ダイソン', 'dyson',
        'パナソニック', 'panasonic', 'ソニー', 'sony', 'シャープ', 'sharp', '日立', 'hitachi',
        '東芝', 'toshiba', 'アイリスオーヤマ', 'ニンテンドー', 'nintendo',
        'バカラ', 'baccarat', 'ウェッジウッド', 'wedgwood', 'イッタラ', 'iittala',
        'ル・クルーゼ', 'le creuset', 'ストウブ', 'staub', 'ガンダム', 'ポケモン', 'lego', 'レゴ',
    ]
}


def main():
    data = json.loads(INPUT.read_text(encoding='utf-8'))
    existing = data.get('candidates', [])
    existing_by_url = {x.get('url'): x for x in existing if x.get('url')}

    for word in EXTRA_KEYWORDS:
        if word not in scout.KEYWORDS:
            scout.KEYWORDS.append(word)
        if word not in scout.MARKET_KEYWORDS:
            scout.MARKET_KEYWORDS.append(word)
    scout.PRIORITY_BRANDS.update(EXTRA_BRANDS)

    added = []
    total_extra_items = 0
    for category, url in SEARCH_URLS:
        print('追加カテゴリ:', category, url)
        try:
            html = scout.fetch(url)
            items = scout.extract_items(html)
            total_extra_items += len(items)
            print('  取得候補:', len(items))
            for item in items:
                result = scout.evaluate_item(
                    item['title'], item['price'], item['text'], item['url'], item.get('image_urls')
                )
                if not result or item['url'] in existing_by_url:
                    continue
                result['source_category'] = category
                existing_by_url[item['url']] = result
                added.append(result)
        except Exception as exc:
            print('追加カテゴリ取得失敗:', category, repr(exc))

    merged = list(existing_by_url.values())
    merged.sort(key=scout.sort_key)
    data['candidates'] = merged
    data['source_items'] = int(data.get('source_items', 0)) + total_extra_items
    data['extra_category_items'] = total_extra_items
    data['extra_category_candidates'] = len(added)
    INPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    scout.write_reports(merged, data['source_items'])

    print('追加カテゴリ取得件数:', total_extra_items)
    print('追加候補:', len(added))
    print('候補総数:', len(merged))
    for item in added[:15]:
        print('追加候補', item.get('source_category'), item['title'], f"仕入れ={item['price']:,}円", f"score={item['score']}")


if __name__ == '__main__':
    main()
