#!/usr/bin/env python3
"""e-Gov 法令API (https://laws.e-gov.go.jp/) から条文を取得する。

レポートに条文番号を書くとき、記憶に頼ると番号や数値を間違える。
このスクリプトで原文を引き、施行日とあわせて引用すること。

    python3 fetch_law.py 労基法 89 91 37        # 条文を取得
    python3 fetch_law.py --list                  # 使える法令名の一覧
    python3 fetch_law.py 労基法 --status         # 現在の施行日と最終改正だけ
    python3 fetch_law.py 労施法 33 --asof 2026-10-01   # 未施行の改正後の条文
    python3 fetch_law.py 労基法 --grep 就業規則  # 条文本文を検索して該当条を出す

--asof は未施行の改正を先読みするのに使う。就業規則は改定してから施行日を迎えるため、
「まだ施行されていないが、もう改定に織り込むべきもの」を拾うのに要る。
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://laws.e-gov.go.jp/api/2"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "egov-laws")

# 就業規則の点検で使う法令。law_id は e-Gov の法令ID。
LAWS = {
    "労基法":      ("322AC0000000049", "労働基準法"),
    "労基則":      ("322M40000100023", "労働基準法施行規則"),
    "労契法":      ("419AC0000000128", "労働契約法"),
    "育介法":      ("403AC0000000076", "育児休業、介護休業等育児又は家族介護を行う労働者の福祉に関する法律"),
    "高年法":      ("346AC0000000068", "高年齢者等の雇用の安定等に関する法律"),
    "労施法":      ("341AC0000000132", "労働施策の総合的な推進並びに労働者の雇用の安定及び職業生活の充実等に関する法律"),
    "パート有期法": ("405AC0000000076", "短時間労働者及び有期雇用労働者の雇用管理の改善等に関する法律"),
    "均等法":      ("347AC0000000113", "雇用の分野における男女の均等な機会及び待遇の確保等に関する法律"),
    "安衛法":      ("347AC0000000057", "労働安全衛生法"),
    "最賃法":      ("334AC0000000137", "最低賃金法"),
}
ALIASES = {
    "労働基準法": "労基法", "労働基準法施行規則": "労基則", "労働契約法": "労契法",
    "育児介護休業法": "育介法", "育児・介護休業法": "育介法",
    "高年齢者雇用安定法": "高年法", "高齢法": "高年法",
    "労働施策総合推進法": "労施法", "パワハラ防止法": "労施法",
    "パート法": "パート有期法", "短時間有期法": "パート有期法",
    "男女雇用機会均等法": "均等法", "労働安全衛生法": "安衛法", "最低賃金法": "最賃法",
}


def resolve(name):
    key = ALIASES.get(name, name)
    if key not in LAWS:
        sys.exit(f"未登録の法令です: {name}\n--list で一覧を確認するか、"
                 f"e-Gov の法令IDを直接 --law-id で指定してください。")
    return LAWS[key]


def get(path, params, use_cache=True):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    os.makedirs(CACHE, exist_ok=True)
    cf = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9_.-]', '_', url)[-180:] + ".json")
    if use_cache and os.path.exists(cf):
        with open(cf, encoding="utf-8") as f:
            return json.load(f)
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"e-Gov への接続に失敗しました: {e}\nURL: {url}")
    if isinstance(data, dict) and data.get("code"):
        sys.exit(f"e-Gov がエラーを返しました: {data.get('message')} (code {data['code']})")
    with open(cf, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


# --- JSON ツリー → 読める条文テキスト -------------------------------------

BLOCK_BEFORE = {"Article", "Paragraph", "Item", "Subitem1", "Subitem2",
                "ArticleCaption", "Chapter", "Section"}


def render(node, out):
    if isinstance(node, str):
        out.append(node)
        return
    if isinstance(node, list):
        for c in node:
            render(c, out)
        return
    tag = node.get("tag", "")
    kids = node.get("children", [])

    if tag == "ArticleCaption":
        out.append("\n")
        render(kids, out)
        out.append("\n")
        return
    if tag == "ArticleTitle":
        render(kids, out)
        out.append("　")
        return
    if tag in ("ParagraphNum", "ItemTitle", "Subitem1Title", "Subitem2Title"):
        buf = []
        render(kids, buf)
        t = "".join(buf).strip()
        if t:
            out.append("\n" + t + "　")
        return
    if tag == "Paragraph":
        # 項番号は ParagraphNum 子要素にあることも、attr にしかないこともある。
        # 両方書くと「2　２　…」と重複するので、子要素が空のときだけ attr を使う。
        has_num = any(
            isinstance(c, dict) and c.get("tag") == "ParagraphNum"
            and "".join(x for x in c.get("children", []) if isinstance(x, str)).strip()
            for c in kids)
        num = node.get("attr", {}).get("Num")
        if not has_num and num and num != "1":
            out.append(f"\n{num}　")
        render(kids, out)
        return
    if tag in ("Item", "Subitem1", "Subitem2"):
        render(kids, out)
        return
    if tag == "Sentence":
        render(kids, out)
        return
    if tag == "Column":
        render(kids, out)
        out.append("　")
        return
    if tag in ("TableStruct", "Table", "Fig", "AppdxTable"):
        out.append("〔表・図は省略。e-Gov で確認すること〕")
        return
    render(kids, out)


def to_text(node):
    out = []
    render(node, out)
    s = "".join(out)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def iter_articles(node):
    if isinstance(node, dict):
        if node.get("tag") == "Article":
            yield node
            return
        for c in node.get("children", []):
            yield from iter_articles(c)
    elif isinstance(node, list):
        for c in node:
            yield from iter_articles(c)


def article_label(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleTitle":
            return to_text(c).strip("　")
    return "第?条"


# --- 出力 -----------------------------------------------------------------

def probe_future(law_id, current_id, no_cache=False):
    """未施行の改正があるか、先の日付で引いて確かめる。

    API の amendment_scheduled_enforcement_date は埋まっていないことがあるため、
    実際に先の版を取りに行って版IDが変わるかで判定する。"""
    import datetime
    today = datetime.date.today()
    found = []
    for months in (3, 6, 12, 24, 36):
        d = (today + datetime.timedelta(days=int(months * 30.44))).isoformat()
        try:
            r = get(f"law_data/{law_id}",
                    {"response_format": "json", "asof": d, "elm": "Article_1"},
                    not no_cache)
        except SystemExit:
            continue
        rid = r.get("revision_info", {}).get("law_revision_id")
        eff = r.get("revision_info", {}).get("amendment_enforcement_date")
        if rid and rid != current_id and eff not in [f[0] for f in found]:
            found.append((eff, r["revision_info"].get("amendment_law_num")))
    return found


def print_header(short, full, rev, asof):
    sys.stdout.write(f"■ {full}（{short}）\n")
    sys.stdout.write(f"  現在の版: {rev.get('amendment_enforcement_date')} 施行"
                     f" / 最終改正 {rev.get('amendment_law_num')}\n")
    if rev.get("amendment_law_title"):
        sys.stdout.write(f"  改正法: {rev['amendment_law_title']}\n")
    sched = rev.get("amendment_scheduled_enforcement_date")
    if sched:
        sys.stdout.write(f"  ★ 未施行の改正あり（施行予定 {sched}）。"
                         f"--asof {sched} で改正後の条文を確認すること\n")
    if asof:
        sys.stdout.write(f"  ※ {asof} 時点の版を取得しています\n")
    sys.stdout.write("\n")


def norm_article(s):
    """「30の2」「30-2」「第30条の2」→ 「30_2」"""
    s = s.replace("第", "").replace("条", "")
    s = s.replace("の", "_").replace("-", "_").replace("ノ", "_")
    return s.strip("_ 　")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("law", nargs="?", help="法令の略称（--list で一覧）")
    ap.add_argument("articles", nargs="*", help="条番号。例: 89 91 30の2")
    ap.add_argument("--law-id", help="e-Gov の法令IDを直接指定する")
    ap.add_argument("--asof", help="YYYY-MM-DD 時点の版を取得する（未施行の先読みに使う）")
    ap.add_argument("--status", action="store_true", help="施行日と最終改正だけ表示")
    ap.add_argument("--grep", help="条文本文を検索し、該当する条を表示する")
    ap.add_argument("--list", action="store_true", help="登録済みの法令一覧")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    if a.list:
        print("登録済みの法令（左の略称で指定できる）:\n")
        for k, (lid, full) in LAWS.items():
            al = [x for x, y in ALIASES.items() if y == k]
            print(f"  {k:<12} {full}")
            if al:
                print(f"  {'':<12} 別名: {'、'.join(al)}")
        print("\n一覧にない法令は --law-id で e-Gov の法令IDを直接指定してください。")
        return

    if not a.law and not a.law_id:
        ap.error("法令を指定してください（--list で一覧）")

    articles = list(a.articles)
    if a.law_id:
        # --law-id を使うと法令名のスロットが空くので、最初の位置引数は条番号になる。
        # ここで拾わないと、指定した条が黙って落ちる。
        if a.law:
            articles.insert(0, a.law)
        law_id, short, full = a.law_id, a.law_id, a.law_id
    else:
        law_id, full = resolve(a.law)
        short = ALIASES.get(a.law, a.law)
    a.articles = articles

    params = {"response_format": "json"}
    if a.asof:
        params["asof"] = a.asof

    # --status と --grep は全文が要る。条指定があるときは該当条だけ取る。
    if a.articles and not a.grep and not a.status:
        shown = 0
        for art in a.articles:
            p = dict(params, elm=f"Article_{norm_article(art)}")
            d = get(f"law_data/{law_id}", p, not a.no_cache)
            if shown == 0:
                print_header(short, full, d["revision_info"], a.asof)
                shown = 1
            print(to_text(d["law_full_text"]))
            print("\n" + "─" * 60)
        print(f"\n出典: e-Gov法令検索 https://laws.e-gov.go.jp/law/{law_id}")
        return

    d = get(f"law_data/{law_id}", params, not a.no_cache)
    print_header(short, full, d["revision_info"], a.asof)

    if a.status:
        if not a.asof:
            future = probe_future(law_id, d["revision_info"].get("law_revision_id"),
                                  a.no_cache)
            if future:
                print("  ★ 未施行の改正があります:")
                for eff, num in future:
                    when = f"{eff} 施行" if eff else "施行日不明（e-Gov に日付なし）"
                    print(f"      {when} / {num}")
                print("    条番号が繰り下がることがあるため、未施行の条を現行版で引くと"
                      "別の条文が返ります。")
                dated = [f for f in future if f[0]]
                if dated:
                    print("    必ず --asof を付けて取り直すこと:")
                    print(f"      python3 fetch_law.py {short} <条番号> "
                          f"--asof {dated[0][0]}")
            else:
                print("  未施行の改正は見つかりませんでした。")
            print()
        print(f"出典: https://laws.e-gov.go.jp/law/{law_id}")
        return

    if a.grep:
        hits = 0
        for art in iter_articles(d["law_full_text"]):
            t = to_text(art)
            if a.grep in t:
                hits += 1
                print(t)
                print("\n" + "─" * 60)
        print(f"\n「{a.grep}」を含む条: {hits} 件")
        print(f"出典: e-Gov法令検索 https://laws.e-gov.go.jp/law/{law_id}")
        return

    # 条の指定も検索もない場合は目次だけ出す
    arts = list(iter_articles(d["law_full_text"]))
    print(f"全 {len(arts)} 条。条番号を指定して本文を取得してください。\n")
    for art in arts:
        cap = ""
        for c in art.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
                cap = to_text(c)
        print(f"  {article_label(art):<12} {cap}")


if __name__ == "__main__":
    main()
