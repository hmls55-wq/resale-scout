import json
from pathlib import Path
from urllib.parse import quote

INPUT = Path("resell_candidates.json")
OUTPUT = Path("verification_report.md")


def mercari_search_url(query: str) -> str:
    return "https://jp.mercari.com/search?keyword=" + quote(query)


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
        "> メルカリの自動スクレイピングは行わず、公式の検索画面で候補を確認できるリンクを生成します。",
        "> 実売価格・売却済み件数・送料は必ず商品ごとに確認してください。",
        "",
    ]

    for i, item in enumerate(candidates[:30], 1):
        title = item.get("title", "-")
        brands = ", ".join(x.get("name", "") for x in item.get("brands", []))
        keywords = item.get("keywords", [])
        query_parts = []
        if brands:
            query_parts.append(brands.split(",")[0])
        if keywords:
            query_parts.append(keywords[0])
        if not query_parts:
            query_parts.append(title)
        query = " ".join(dict.fromkeys(query_parts))

        lines += [
            f"## {i}. {item.get('urgency', '')} {title}",
            f"- 仕入れ価格: {item.get('price', 0):,}円",
            f"- 現在の利益推定: {item.get('estimated_profit', 0):,}円",
            f"- スコア: {item.get('score', 0)}",
            f"- 検索キーワード: `{query}`",
            f"- [メルカリで検索]({mercari_search_url(query)})",
            f"- [ジモティー商品]({item.get('url', '#')})",
            "- 判定: **メルカリ実売履歴を確認 → 仕入れ判断**",
            "",
        ]

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
