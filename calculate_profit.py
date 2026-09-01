import json
import re
import statistics
from pathlib import Path

CANDIDATES = Path('resell_candidates.json')
MARKET = Path('mercari_market.json')
OUTPUT = Path('profit_report.md')
JSON_OUTPUT = Path('profit_candidates.json')

TANOMERU = {
    80: 1700, 120: 2400, 160: 3400, 200: 5000,
    250: 8600, 300: 12000, 350: 18500, 400: 25400, 450: 33000,
}
TAKKYU = {
    60: 750, 80: 850, 100: 1050, 120: 1200,
    140: 1450, 160: 1700, 180: 2100,
}


def normalize(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def parse_size(item):
    s = ' '.join([
        str(item.get('jmty_description_excerpt') or ''),
        str(item.get('title') or ''),
    ])
    patterns = [
        r'(?:幅|横幅)\s*[約]?\s*(\d+(?:\.\d+)?)\s*cm?[^\n]{0,80}?(?:奥行(?:き)?|奥行)\s*[約]?\s*(\d+(?:\.\d+)?)\s*cm?[^\n]{0,80}?(?:高さ|縦幅)\s*[約]?\s*(\d+(?:\.\d+)?)',
        r'(?:高さ|縦幅)\s*[約]?\s*(\d+(?:\.\d+)?)\s*cm?[^\n]{0,80}?(?:幅|横幅)\s*[約]?\s*(\d+(?:\.\d+)?)\s*cm?[^\n]{0,80}?(?:奥行(?:き)?|奥行)\s*[約]?\s*(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*cm?',
    ]
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            vals = [float(x) for x in m.groups()]
            return {'length': vals[0], 'width': vals[1], 'height': vals[2]}
    return None


def shipping(size):
    if not size:
        return None, 'unknown'
    total = sum(size.values())
    if total <= 180:
        for limit, fee in TAKKYU.items():
            if total <= limit:
                return fee, f'らくらくメルカリ便 {limit}サイズ'
    if total <= 450:
        for limit, fee in TANOMERU.items():
            if total <= limit:
                return fee, f'たのメル便 {limit}サイズ'
    return None, 'サイズ超過'


def key(s):
    return re.sub(r'[^0-9a-zぁ-んァ-ヶ一-龥々ー]+', '', normalize(s).lower())


def main():
    data = json.loads(CANDIDATES.read_text(encoding='utf-8'))
    market = json.loads(MARKET.read_text(encoding='utf-8'))
    candidates = data.get('candidates', [])
    checked = market.get('checked', [])
    by_title = {key(x.get('source_title')): x for x in checked if x.get('source_title')}

    rows = []
    for item in candidates:
        title = item.get('jmty_detail_title') or item.get('title') or ''
        result = by_title.get(key(title))
        if not result:
            # fallback: exact original title
            result = by_title.get(key(item.get('title')))
        if not result:
            continue

        purchase = int(item.get('price') or 0)
        prices = [int(x) for x in result.get('prices', []) if x]
        sale = int(result.get('robust_median') or result.get('median') or 0)
        size = item.get('size') or parse_size(item)
        fee, shipping_label = shipping(size)
        similarity = int(result.get('best_similarity') or 0)
        count = len(prices)

        # Generic/weak queries are deliberately penalized. A median from one
        # generic result is not treated as a reliable resale estimate.
        confidence = '低'
        if count >= 10 and len(title) >= 6:
            confidence = '中'
        if count >= 15 and len(title) >= 8 and similarity >= 25:
            confidence = '高'

        if sale and fee is not None:
            sale_after_fee = sale - int(sale * 0.10)
            profit = sale_after_fee - fee - purchase
        else:
            sale_after_fee = None
            profit = None

        if profit is not None and confidence == '低':
            profit_for_rank = int(profit * 0.5)
        else:
            profit_for_rank = profit

        rows.append({
            'title': title,
            'purchase_price': purchase,
            'sale_price_estimate': sale or None,
            'sale_price_low': result.get('low'),
            'sale_price_high': result.get('high'),
            'sold_count_checked': count,
            'similarity': similarity,
            'confidence': confidence,
            'size': size,
            'shipping': fee,
            'shipping_label': shipping_label,
            'sale_after_fee': sale_after_fee,
            'estimated_profit': profit,
            'rank_profit': profit_for_rank,
            'source_url': item.get('url'),
            'mercari_url': result.get('url'),
        })

    rows.sort(key=lambda x: (x['rank_profit'] is not None, x['rank_profit'] or -10**9), reverse=True)
    JSON_OUTPUT.write_text(json.dumps({'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        '# Resell Scout 利益ランキング',
        '',
        '※売却価格はメルカリ売り切れ検索の中央値。販売手数料は10%。送料は商品寸法から推定。寸法不明の商品は利益を確定しません。',
        '',
        '|順位|商品|仕入れ|売却相場|送料|想定利益|信頼度|',
        '|---:|---|---:|---:|---:|---:|---|',
    ]
    for i, r in enumerate(rows, 1):
        sale = f"{r['sale_price_estimate']:,}円" if r['sale_price_estimate'] else '—'
        ship = f"{r['shipping']:,}円" if r['shipping'] is not None else '不明'
        profit = f"{r['estimated_profit']:,}円" if r['estimated_profit'] is not None else '算出不可'
        lines.append(f"|{i}|{r['title'][:35]}|{r['purchase_price']:,}円|{sale}|{ship}|{profit}|{r['confidence']}|")

    lines += ['', '## 判定基準', '', '- A: 想定利益10,000円以上', '- B: 想定利益5,000〜9,999円', '- C: 想定利益2,000〜4,999円', '- 見送り: 2,000円未満、または送料・相場の信頼性が不足', '', 'メルカリの販売手数料は販売価格の10%。送料は公式料金表を使用。']
    OUTPUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('profit rows:', len(rows))
    for r in rows[:10]:
        print(r['title'], 'profit=', r['estimated_profit'], 'shipping=', r['shipping'], 'confidence=', r['confidence'])


if __name__ == '__main__':
    main()
