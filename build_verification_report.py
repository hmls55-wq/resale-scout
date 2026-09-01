import json
from pathlib import Path
from urllib.parse import quote

INPUT = Path("resell_candidates.json")
OUTPUT = Path("verification_report.md")

# 2026-09時点のメルカリ便の主な送料目安。
# 大型家具はサイズ・重量・梱包状態で変わるため、保守的にたのメル便の検索導線を残す。
TAKYUBIN = {60: 750, 80: 850, 100: 1050, 120: 1200, 140: 1450, 160: 1700, 180: 2100, 200: 2500}
TANOMERU = {80: 1700, 120: 2400, 160: 3400, 200: 5000, 250: 8600, 300: 12000, 350: 18500, 400: 25400, 450: 33000}


def mercari_search_url(query: str) -> str:
    return "https://jp.mercari.com/search?keyword=" + quote(query)


def google_images_url(query: str) -> str:
    return "https://www.google.com/search?tbm=isch&q=" + quote(query)


def money(value):
    return f"{value:,}円" if isinstance(value, int) else "要メルカリ相場確認"


def shipping_estimate(item):
    size = item.get("size") or {}
    vals = [size.get("length"), size.get("width"), size.get("height")]
    if not all(isinstance(v, (int, float)) for v in vals):
        return None, "サイズ不明"
    total = int(sum(vals))
    if total <= 200:
        # 通常の宅急便で送れる可能性があるサイズ。重量は不明なので保守的に1,700円を仮置き。
        for s in sorted(TAKYUBIN):
            if total <= s:
                return TAKYUBIN[s], f"らくらくメルカリ便 {s}サイズ目安"
    for s in sorted(TANOMERU):
        if total <= s:
            return TANOMERU[s], f"梱包・発送たのメル便 {s}サイズ目安"
    return None, "450サイズ超・個別確認"


def main():
    if not INPUT.exists():
        raise SystemExit("resell_candidates.json がありません")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])

    lines = [
        "# Resell Scout 仕入れ判定用レポート",
        "",
        f"実行時刻: {data.get('generated_at', '-')}",
        f"候補数: {len(candidates)}",
        "",
        "> 🔎 相場確認候補は、メルカリの検索結果と実物画像を確認してから仕入れ判断します。",
        "> メルカリ販売手数料は販売価格の10%。送料込みの場合は送料も販売利益から差し引きます。",
        "> 売却済み履歴を自動取得できない候補は、利益を断定せず「要確認」と表示します。",
        "",
    ]

    for i, item in enumerate(candidates[:30], 1):
        title = item.get("title", "-")
        brands = ", ".join(x.get("name", "") for x in item.get("brands", []))
        keywords = item.get("keywords", [])
        query_parts = []
        if brands:
            query_parts.append(brands.split(",")[0])
        query_parts.append(title)
        if keywords and len(query_parts) < 2:
            query_parts.append(keywords[0])
        query = " ".join(dict.fromkeys(x for x in query_parts if x))

        ship, ship_note = shipping_estimate(item)
        price = item.get("price", 0)
        est_sale = item.get("estimated_sale_price")
        if isinstance(est_sale, int) and isinstance(ship, int):
            est_profit_after_cost = int(est_sale * 0.90) - ship - price
        else:
            est_profit_after_cost = None

        image_urls = item.get("image_urls") or []
        lens = item.get("google_lens_url")
        lines += [
            f"## {i}. {item.get('urgency', '')} {title}",
            f"- 仕入れ価格: {price:,}円",
            f"- 簡易売価推定: {money(est_sale)}",
            f"- 送料目安: {money(ship)}（{ship_note}）",
            f"- 手数料: 売価の10%",
            f"- コスト控除後の簡易利益: {money(est_profit_after_cost)}",
            f"- 判定理由: {item.get('reason', '-')}",
            f"- スコア: {item.get('score', 0)}",
            f"- 検索キーワード: `{query}`",
            f"- [メルカリで検索]({mercari_search_url(query)})",
            f"- [Google画像検索]({google_images_url(query)})",
            f"- [ジモティー商品]({item.get('url', '#')})",
        ]
        if lens:
            lines.append(f"- [Google Lens（商品画像）]({lens})")
        if image_urls:
            lines.append(f"- ジモティー画像: {image_urls[0]}")
        lines += [
            "- 最終判定: **同一商品・売却済み相場・送料・状態を確認してから仕入れ**",
            "",
        ]

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
