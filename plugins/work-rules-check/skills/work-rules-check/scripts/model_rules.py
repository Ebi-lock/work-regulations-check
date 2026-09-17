#!/usr/bin/env python3
"""厚生労働省「モデル就業規則」から規程例と解説を引く。

修正案を書くときは、自分で条文を考えるより、モデル就業規則の規程例に合わせるほうが
労基署とのやり取りで説明しやすく、文言の正確さも担保できる。

    python3 model_rules.py --toc                  # 目次（どんな条があるか）
    python3 model_rules.py --grep 年次有給休暇     # 該当する規程例
    python3 model_rules.py --article 23           # 条番号で引く
    python3 model_rules.py --grep 懲戒 --explain  # 規程例＋厚労省の解説
    python3 model_rules.py --version-info         # 版とダウンロード元

初回はダウンロードに少し時間がかかる。以降はキャッシュを使う。
--refresh で取り直す（改訂を確認したいとき）。

注意: モデル就業規則はあくまで一例であり、これに合わせること自体が義務ではない。
事業場の実情に合わない部分は、根拠法令を満たす範囲で調整すること。
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.request

# 厚生労働省「モデル就業規則について」
#   https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/model/index.html
# 版が変わると URL の数字も変わる。取得に失敗したら上のページで最新の docx を確認すること。
INDEX_URL = ("https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/"
             "roudoukijun/zigyonushi/model/index.html")
DOCX_URL = "https://www.mhlw.go.jp/content/001620506.docx"
VERSION = "令和7年12月版"

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "mhlw-model-rules")
DOCX = os.path.join(CACHE, "model.docx")
TXT = os.path.join(CACHE, "model.txt")

ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


DOCX_IN_PAGE = re.compile(r'href="(/content/\d+\.docx)"', re.I)
VERSION_IN_PAGE = re.compile(r'(令和\s*[0-9０-９一二三四五六七八九十]+\s*年\s*'
                             r'[0-9０-９一二三四五六七八九十]+\s*月版)')


def discover():
    """掲載ページから最新版の docx URL と版名を拾う。

    版が変わると URL の数字も変わるため、URL を固定で持つと改訂のたびに壊れる。
    ページから拾い、拾えなければ既知の URL にフォールバックする。"""
    try:
        req = urllib.request.Request(INDEX_URL,
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return DOCX_URL, VERSION, False

    m = DOCX_IN_PAGE.search(html)
    if not m:
        return DOCX_URL, VERSION, False
    url = "https://www.mhlw.go.jp" + m.group(1)
    v = VERSION_IN_PAGE.search(html)
    return url, (v.group(1).replace(" ", "") if v else VERSION), True


def ensure(refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    if refresh or not os.path.exists(TXT):
        if refresh or not os.path.exists(DOCX):
            url, ver, live = discover()
            note = "" if live else "（掲載ページを読めなかったため既知のURLを使用）"
            sys.stderr.write(f"モデル就業規則（{ver}）を取得しています…{note}\n")
            if live and url != DOCX_URL:
                sys.stderr.write(
                    f"[情報] スクリプトが想定する版（{VERSION}）と異なる版が"
                    f"掲載されています: {ver}\n"
                    f"        新しい版を取得します。条番号が変わっている可能性が"
                    f"あるため、--toc で確認してください。\n")
            try:
                urllib.request.urlretrieve(url, DOCX)
            except Exception as e:
                sys.exit(f"ダウンロードに失敗しました: {e}\n"
                         f"厚労省のページで最新の docx の URL を確認してください:\n{INDEX_URL}")
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(here, "extract_text.py"),
                            DOCX, "-o", TXT], capture_output=True)
        if r.returncode != 0:
            sys.exit(r.stderr.decode("utf-8", "replace"))
    with open(TXT, encoding="utf-8") as f:
        return f.read().split("\n")


# 規程例は表のセルで、必ず「（条見出し）」から始まる。
# 条番号は Word の自動採番で入っている箇所があり、テキストに現れないことがあるので、
# 見出しを手がかりにして拾い、番号は取れたときだけ使う。
CAPTION_RE = re.compile(r'^（([^（）。、]{1,30})）')
NUM_RE = re.compile(r'第\s*([０-９0-9]+)\s*条')


TOC_RE = re.compile(r'^第\s*([０-９0-9]+)\s*条\s*（([^（）]{1,30})）\s*$')


def toc_numbers(lines):
    """冒頭の目次から「条見出し → 条番号」を作る。

    規程例の本文側は Word の自動採番で番号が取れない条があるため、
    目次から番号を補う。"""
    m = {}
    for ln in lines:
        t = TOC_RE.match(ln.strip())
        if t:
            m.setdefault(t.group(2).strip(), int(t.group(1).translate(ZEN)))
    return m


def sections(lines):
    """規程例のセル（表の行）と、その直後の解説をまとめて返す。"""
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith('|'):
            continue
        cell = ln.strip('| ').strip()
        m = CAPTION_RE.match(cell)
        if not m:
            continue
        head = cell[m.end():m.end() + 40]
        nm = NUM_RE.search(head)
        # 解説は次の表セルが始まるまで
        body = []
        for nxt in lines[i + 1:]:
            if nxt.startswith('|'):
                break
            body.append(nxt)
        out.append({
            'caption': m.group(1).strip(),
            'num': int(nm.group(1).translate(ZEN)) if nm else None,
            'from_toc': False,
            'cell': ln,
            'explain': '\n'.join(body).strip(),
        })
    return out


def unwrap(cell):
    """1行に潰れた規程例のセルを、項ごとに改行して読めるようにする。"""
    s = cell.strip('| ').strip()
    s = re.sub(r'\s{2,}', ' ', s)
    # 「 ２　」「 ３　」のような項番号の前で改行する
    s = re.sub(r'\s(?=[２-９]０?　|[１-９][０-９]　)', '\n', s)
    # 号（①②… / 一、二…）の前でも改行
    s = re.sub(r'\s(?=[①-⑳])', '\n', s)
    return s.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--toc', action='store_true', help='規程例の目次')
    ap.add_argument('--grep', help='条見出し・本文に含まれる語で探す')
    ap.add_argument('--article', type=int, help='モデル就業規則の条番号で引く')
    ap.add_argument('--explain', action='store_true', help='厚労省の解説も表示する')
    ap.add_argument('--version-info', action='store_true')
    ap.add_argument('--refresh', action='store_true', help='取り直す')
    a = ap.parse_args()

    if a.version_info:
        url, ver, live = discover()
        print(f"厚生労働省「モデル就業規則」{ver}"
              f"{'' if live else '（掲載ページを読めず、既知の情報）'}")
        print(f"  docx: {url}")
        print(f"  掲載ページ: {INDEX_URL}")
        if live and ver != VERSION:
            print(f"  ※ スクリプトが想定する版は {VERSION} です。"
                  f"掲載版が新しいため、--refresh で取り直してください。")
        print(f"  キャッシュ: {TXT if os.path.exists(TXT) else '（未取得）'}")
        print("\n版が古い可能性があるときは --refresh、"
              "それでも変わらなければ掲載ページで新しい版の URL を確認すること。")
        return

    lines = ensure(a.refresh)
    secs = sections(lines)
    toc = toc_numbers(lines)
    for sec in secs:
        if sec['num'] is None and sec['caption'] in toc:
            sec['num'] = toc[sec['caption']]
            sec['from_toc'] = True

    if a.toc or not (a.grep or a.article):
        print(f"厚生労働省「モデル就業規則」{VERSION} 規程例（{len(secs)} 条）\n")
        for s in secs:
            n = f"第{s['num']}条" if s['num'] else "（番号不明）"
            print(f"  {n:<10} {s['caption']}")
        print("\n--grep <語> または --article <番号> で本文を表示します。")
        print("※ 同じ条番号が複数あるのは、変形労働時間制など制度ごとの"
              "規程例が並んでいるため。")
        print("※ Word の自動採番で振られている条は番号が取れないことがある。"
              "その場合は --grep で見出しから引くこと。")
        return

    if a.article:
        hits = [s for s in secs if s['num'] == a.article]
        if not hits:
            print(f"第{a.article}条は番号として拾えませんでした"
                  "（Word の自動採番の可能性）。--toc か --grep で探してください。\n")
    else:
        hits = [s for s in secs
                if a.grep in s['caption'] or a.grep in s['cell']]

    if not hits:
        print(f"該当する規程例がありませんでした。--toc で目次を確認してください。")
        return

    print(f"出典: 厚生労働省「モデル就業規則」{VERSION}\n")
    for s in hits:
        print("=" * 60)
        n = f"第{s['num']}条" if s['num'] else ""
        print(f"{n}（{s['caption']}）")
        print("=" * 60)
        print(unwrap(s['cell']))
        if a.explain and s['explain']:
            print("\n--- 厚労省の解説 ---")
            print(s['explain'])
        print()


if __name__ == '__main__':
    main()
