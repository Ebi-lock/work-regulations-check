#!/usr/bin/env python3
"""厚生労働省の「国会提出法案」から、労働関係の改正情報を拾う。

法改正チェックの起点。e-Gov は「いま条文がどうなっているか」は分かるが、
「何が、なぜ、いつから変わるのか」は分からない。そこは厚労省の概要資料が要る。

    python3 mhlw_bills.py --sessions           # どの国会回次が載っているか
    python3 mhlw_bills.py --session 217        # その回次の労働関係法案と資料URL
    python3 mhlw_bills.py --session 217 --all  # 労働関係以外も含めて全部
    python3 mhlw_bills.py --summary 217        # 労働関係法案の「概要」PDFを読む
    python3 mhlw_bills.py --recent 3           # 直近3回次をまとめて

「概要」PDF には改正のポイントと**施行期日**が書かれている。
ここで施行期日の考え方（公布から○年以内で政令で定める日、など）を押さえてから、
e-Gov で実際の条文と施行日を確認する。
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.request

BASE = "https://www.mhlw.go.jp"
INDEX = f"{BASE}/topics/bukyoku/soumu/houritu/index.html"
SESSION = BASE + "/stf/topics/bukyoku/soumu/houritu/{}.html"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "mhlw-bills")

# 就業規則に影響しうる法案を拾うための語。広めに取って、外れは目で捨てる。
LABOR_KW = ["労働", "雇用", "賃金", "育児", "介護休業", "女性活躍", "高年齢者",
            "職業安定", "安全衛生", "最低賃金", "パートタイム", "有期雇用",
            "ハラスメント", "働き方"]


def fetch(url, binary=False):
    os.makedirs(CACHE, exist_ok=True)
    name = re.sub(r'[^A-Za-z0-9_.-]', '_', url)[-150:]
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read()
        except Exception as e:
            sys.exit(f"取得に失敗しました: {url}\n{e}")
        with open(path, "wb") as f:
            f.write(data)
    if binary:
        return path
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace")


def list_sessions():
    html = fetch(INDEX)
    nums = sorted({int(m) for m in re.findall(r'houritu/(\d+)\.html', html)},
                  reverse=True)
    return nums


H2 = re.compile(r'<h2[^>]*class="m-hdgLv2__hdg"[^>]*>(.*?)</h2>', re.S)
LINK = re.compile(r'<a[^>]*href="(/content/\d+\.pdf)"[^>]*>(.*?)</a>', re.S)


def strip_tags(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&')
    return re.sub(r'\s+', ' ', s).strip()


def parse_session(n):
    """回次ページから [{title, docs:[(label,url)]}] を返す。"""
    avail = list_sessions()
    if n not in avail:
        near = [x for x in avail if x <= n][:3] or avail[:3]
        sys.exit(f"第{n}回国会のページは掲載されていません。\n"
                 f"掲載があるのは: {'、'.join(f'第{x}回' for x in avail[:12])}\n"
                 f"近いものだと第{near[0]}回です。--sessions で一覧を確認してください。")
    html = fetch(SESSION.format(n))
    parts = H2.split(html)
    bills = []
    # parts = [先頭, 見出し1, 本文1, 見出し2, 本文2, ...]
    for i in range(1, len(parts) - 1, 2):
        title = strip_tags(parts[i])
        body = parts[i + 1]
        docs = [(strip_tags(lb), BASE + href) for href, lb in LINK.findall(body)]
        if title:
            bills.append({"title": title, "docs": docs})
    return bills


def is_labor(title):
    return any(k in title for k in LABOR_KW)


def show_session(n, show_all=False):
    bills = parse_session(n)
    if not bills:
        print(f"第{n}回国会: 法案が見つかりませんでした（ページ構成が変わった可能性）")
        return []
    picked = [b for b in bills if show_all or is_labor(b["title"])]
    print(f"■ 第{n}回国会  提出法案 {len(bills)} 件"
          f"（うち労働関係 {sum(1 for b in bills if is_labor(b['title']))} 件）")
    print(f"  {SESSION.format(n)}\n")
    if not picked:
        print("  労働関係の法案はありません。--all で全件表示。\n")
    for b in picked:
        print(f"  ● {b['title']}")
        for label, url in b["docs"]:
            print(f"      {label:<24} {url}")
        print()
    return picked


def summary_of(bill):
    """法案の「概要」PDF を落としてテキスト化する。"""
    for label, url in bill["docs"]:
        if label.startswith("概要"):
            pdf = fetch(url, binary=True)
            here = os.path.dirname(os.path.abspath(__file__))
            r = subprocess.run(
                [sys.executable, os.path.join(here, "extract_text.py"), pdf],
                capture_output=True)
            if r.returncode != 0:
                return f"（概要PDFのテキスト化に失敗: {url}）"
            return r.stdout.decode("utf-8", "replace").strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", action="store_true", help="掲載されている国会回次")
    ap.add_argument("--session", type=int, help="この回次の法案を表示")
    ap.add_argument("--recent", type=int, metavar="N", help="直近N回次をまとめて")
    ap.add_argument("--summary", type=int, metavar="回次",
                    help="その回次の労働関係法案の概要PDFを読む")
    ap.add_argument("--all", action="store_true", help="労働関係以外も表示")
    a = ap.parse_args()

    if a.sessions:
        ns = list_sessions()
        print("掲載されている国会回次（新しい順）:")
        print("  " + "、".join(f"第{n}回" for n in ns[:20]))
        print(f"\n  例: python3 mhlw_bills.py --session {ns[0]}")
        return

    if a.summary:
        bills = [b for b in parse_session(a.summary) if is_labor(b["title"])]
        if not bills:
            print(f"第{a.summary}回国会に労働関係の法案はありません。")
            return
        for b in bills:
            print("=" * 70)
            print(b["title"])
            print("=" * 70)
            s = summary_of(b)
            print(s if s else "（概要PDFが見つかりません。上のURL一覧を参照）")
            print()
        return

    if a.recent:
        for n in list_sessions()[:a.recent]:
            show_session(n, a.all)
        return

    if a.session:
        show_session(a.session, a.all)
        return

    # 既定: 直近2回次
    for n in list_sessions()[:2]:
        show_session(n, a.all)
    print("施行期日と改正のポイントは --summary <回次> で概要PDFを読むこと。")


if __name__ == "__main__":
    main()
