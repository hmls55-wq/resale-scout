import json
from pathlib import Path
from urllib.parse import quote

INPUT = Path("resell_candidates.json")
MARKET = Path("mercari_market.json")
OUTPUT = Path("verification_report.md")

TAKYUBIN = {60: 750, 80: 850, 100: 1050, 120: 1200, 140: 1450, 160: 1700, 180: 2100, 200: 2500}
TANOMERU = {80: 1700, 120: 2400, 160: 3400, 200: 5000, 250: 8600, 300: 12000, 350: 18500, 400: 25400, 450: 33000}


def mercari_search_url(query: str) -> str:
    return "https://jp.mercari.com/search?keyword=" + quote(query)


def money(value):
    return f"{value:,}円" if isinstance(value, int) else "要確認"


def shipping_estimate(item):
    size = item.get("size") or {}
    vals = [size.get("length"), size.get("width"), size.get("height")]
    if not all(isinstance(v, (int, float)) for v in vals):
        return None, "サイズ不明"
    total = int(sum(vals))
    if total <= 200:
        for s in sorted(TAKYUBIN):
            if total <= s:
                return TAKYUBIN[s], f"らくらくメルカリ便 {s}サイズ目安"
    for s in sorted(TANOMERU):
        if total <= s:
            return TANOMERU[s], f"たのメル便 {s}サイズ目安"
    return None, "450サイズ超・個別確認"


def main():
    if not INPUT.exists():
        raise SystemExit("resell_candidates.json がありません")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    market = {}
    if MARKET.exists():
        market_data = json.loads(MARKET.read_text(encoding="utf-8"))
        for row in market_data.get("checked", []):
            market[row.get("source_url")] = row

    scored = []
    for item in candidates[:30]:
        ship, ship_note = shipping_estimate(item)
        purchase = item.get("price", 0)
        m = market.get(item.get("url"), {})
        sale = m.get("robust_median") or m.get("median")
        similarity = m.get("best_similarity", 0)
        profit = None
        if isinstance(sale, int) and isinstance(ship, int) and similarity >= 35:
            profit = int(sale * 0.90) - ship - purchase
        row = dict(item)
        row.update({"market_sale": sale, "shipping": ship, "profit": profit, "similarity": similarity, "ship_note": ship_note})
        scored.append(row)

    ranked = sorted(scored, key=lambda x: x.get("profit") if isinstance(x.get("profit"), int) else -10**18, reverse=True)
    lines = ["# Resell Scout 仕入れ判定レポート", "", f"候補数: {len(candidates)}", "", "## 🔥 利益ランキング", ""]
    for i, item in enumerate(ranked[:10], 1):
        sale = item.get("market_sale")
        profit = item.get("profit")
        lines += [
            f"### {i}. {item.get('title', '-')}",
            f"- 仕入れ: {money(item.get('price'))}",
            f"- メルカリ相場（中央値）: {money(sale)}",
            f"- 送料: {money(item.get('shipping'))}（{item.get('ship_note')}）",
            "- 手数料: 売価の10%",
            f"- 想定利益: **{money(profit)}**",
            f"- タイトル一致度: {item.get('similarity', 0)} / 100",
            f"- [メルカリ検索]({mercari_search_url(item.get('title', ''))})",
            f"- [ジモティー商品]({item.get('url', '#')})",
            "- ⚠️ 画像・状態・売却履歴を最終確認してから仕入れ",
            "",
        ]

    lines += ["## 全候補", ""]
    for item in ranked:
        lines.append(f"- {item.get('title','-')} / 仕入れ {money(item.get('price'))} / 相場 {money(item.get('market_sale'))} / 利益 {money(item.get('profit'))} / 一致度 {item.get('similarity',0)}")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
