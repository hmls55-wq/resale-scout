import json
from pathlib import Path

INPUT = Path("profit_candidates.json")
OUTPUT_JSON = Path("opportunity_candidates.json")
OUTPUT_MD = Path("opportunity_report.md")


def clamp(value, low=0, high=100):
    return max(low, min(high, int(value)))


def score_row(row):
    profit = row.get("estimated_profit")
    count = int(row.get("sold_count_checked") or 0)
    similarity = int(row.get("similarity") or 0)
    sale = int(row.get("sale_price_estimate") or 0)
    low = int(row.get("sale_price_low") or 0)
    high = int(row.get("sale_price_high") or 0)

    if profit is None or sale <= 0:
        return 0, "D", "利益または送料を確定できない"

    profit_score = clamp((profit / 15000) * 40)
    count_score = clamp((count / 20) * 20)
    match_score = clamp((similarity / 60) * 25)

    stability_score = 0
    if low > 0 and high >= low:
        ratio = high / low if low else 99
        if ratio <= 1.5:
            stability_score = 15
        elif ratio <= 2.0:
            stability_score = 10
        elif ratio <= 3.0:
            stability_score = 5

    total = clamp(profit_score + count_score + match_score + stability_score)

    if profit >= 10000 and similarity >= 25 and count >= 10:
        grade = "A"
        reason = "利益・売り切れ件数・商品一致度が良好"
    elif profit >= 5000 and count >= 5 and similarity >= 15:
        grade = "B"
        reason = "利益は十分。相場または一致度を要確認"
    elif profit >= 2000:
        grade = "C"
        reason = "利益はあるが、売れ行き・一致度・送料の確認が必要"
    else:
        grade = "D"
        reason = "利益が小さく仕入れ優先度が低い"

    return total, grade, reason


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    ranked = []

    for row in rows:
        score, grade, reason = score_row(row)
        item = dict(row)
        item["opportunity_score"] = score
        item["grade"] = grade
        item["decision_reason"] = reason

        sale = int(item.get("sale_price_estimate") or 0)
        shipping = item.get("shipping")
        if sale and shipping is not None:
            item["buy_price_ceiling_5000_profit"] = max(0, int(sale * 0.90 - shipping - 5000))
        else:
            item["buy_price_ceiling_5000_profit"] = None
        ranked.append(item)

    ranked.sort(key=lambda x: (x["opportunity_score"], x.get("rank_profit") or -10**9), reverse=True)
    OUTPUT_JSON.write_text(json.dumps({"rows": ranked}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Resell Scout 仕入れ優先ランキング",
        "",
        "※スコアは利益、メルカリ売り切れ件数、商品一致度、売却価格のばらつきから算出。売れ行きの実測率ではありません。",
        "",
        "|順位|判定|スコア|商品|仕入れ|売却相場|想定利益|売切確認|一致度|5,000円利益の仕入れ上限|",
        "|---:|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranked, 1):
        sale = f"{r['sale_price_estimate']:,}円" if r.get('sale_price_estimate') else '—'
        profit = f"{r['estimated_profit']:,}円" if r.get('estimated_profit') is not None else '—'
        ceiling = f"{r['buy_price_ceiling_5000_profit']:,}円" if r.get('buy_price_ceiling_5000_profit') is not None else '—'
        lines.append(
            f"|{i}|{r['grade']}|{r['opportunity_score']}|{r['title'][:35]}|"
            f"{r['purchase_price']:,}円|{sale}|{profit}|{r.get('sold_count_checked', 0)}件|"
            f"{r.get('similarity', 0)}|{ceiling}|"
        )

    lines += ["", "## 判定", "", "- A: 最優先で現物確認", "- B: 有力な仕入れ候補", "- C: 利益はあるが要確認", "- D: 原則スルー"]
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("opportunity rows:", len(ranked))
    for r in ranked[:10]:
        print(r["grade"], r["opportunity_score"], r["title"], "profit=", r.get("estimated_profit"))


if __name__ == "__main__":
    main()
