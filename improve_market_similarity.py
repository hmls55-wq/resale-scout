import json
import re
from pathlib import Path

PATH = Path('mercari_market.json')
STOP = {'中古','美品','新品','未使用','送料無料','即購入','匿名配送','送料込み','ジャンク','セット','商品','格安','専用','ホワイト','白','ブラウン','茶','ブラック','黒','木製'}
SYNONYMS = [
    {'白色','ホワイト','白'}, {'黒色','ブラック','黒'}, {'茶色','ブラウン','茶'},
    {'キャスター付','キャスター付き'}, {'収納棚','ラック','収納ラック'},
    {'食器棚','キッチン収納'}, {'チェスト','収納チェスト'}, {'敷布団','マットレス'},
]
CATEGORY_TERMS = ['食器棚','キッチンワゴン','ワゴン','テレビ台','本棚','チェスト','ダイニングチェア','ソファ','ベッド','マットレス','敷布団','タンス','キャビネット','サイドボード','ラック','収納ケース','デスク','テーブル']

def norm(s):
    return re.sub(r'[\s　・/_,.()（）\[\]【】「」]+', '', str(s or '').lower())

def tokens(s):
    s = norm(s)
    out = set(re.findall(r'[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}', s))
    for i in range(len(s)-1):
        x = s[i:i+2]
        if re.fullmatch(r'[ぁ-んァ-ヶ一-龥々ー]{2}', x): out.add(x)
    return {x for x in out if x not in STOP}

def score(source, candidate):
    a, b = norm(source), norm(candidate)
    if not a or not b: return 0
    score = 0
    for term in CATEGORY_TERMS:
        t = norm(term)
        if t in a and t in b: score += 22
    for group in SYNONYMS:
        if any(norm(x) in a for x in group) and any(norm(x) in b for x in group): score += 8
    shared = tokens(source) & tokens(candidate)
    score += min(30, len(shared) * 5)
    grams_a = {a[i:i+2] for i in range(len(a)-1) if re.fullmatch(r'[ぁ-んァ-ヶ一-龥々ー]{2}', a[i:i+2])}
    grams_b = {b[i:i+2] for i in range(len(b)-1) if re.fullmatch(r'[ぁ-んァ-ヶ一-龥々ー]{2}', b[i:i+2])}
    if grams_a: score += min(20, int(20 * len(grams_a & grams_b) / len(grams_a)))
    return min(100, score)

def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    changed = 0
    for row in data.get('checked', []):
        source = row.get('source_title') or row.get('query') or ''
        best, best_title = 0, ''
        for item in row.get('items', []):
            s = score(source, item.get('title', ''))
            if s > best: best, best_title = s, item.get('title', '')
        old = int(row.get('best_similarity') or 0)
        if best != old:
            row['best_similarity_before'] = old
            row['best_similarity'] = best
            row['best_similarity_title'] = best_title
            changed += 1
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'improved market similarity rows: {changed}')
    for row in data.get('checked', []): print(row.get('source_title'), '=>', row.get('best_similarity'), row.get('best_similarity_title', ''))

if __name__ == '__main__': main()
