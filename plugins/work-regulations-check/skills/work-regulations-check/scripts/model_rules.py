#!/usr/bin/env python3
"""厚生労働省が公開している規程例から、条文案と解説を引く。

修正案を自分の言葉で起案するより、厚労省の規程例に合わせるほうがよい。
文言が厚労省のものであれば労基署への説明が通りやすく、人事担当者が社内で
承認を取るときにも使いやすい。

引ける規程例は2つある。

  model  モデル就業規則 …… 就業規則の本体
  ikuji  育児・介護休業等に関する規則の規定例 …… 育介法まわり
         （産後パパ育休・子の看護等休暇・柔軟な働き方の措置などは
           モデル就業規則には入っていないので、こちらを使う）

    python3 model_rules.py --toc                    # 両方の目次
    python3 model_rules.py --grep 年次有給休暇       # 両方から検索
    python3 model_rules.py --grep 出生時育児休業     # 育介側が当たる
    python3 model_rules.py --article 23 --source model
    python3 model_rules.py --grep 懲戒 --explain     # 規程例＋厚労省の解説
    python3 model_rules.py --version-info           # 版と出典URL
    python3 model_rules.py --refresh --toc          # 取り直す

注意: 規程例はあくまで一例であり、これに合わせること自体は義務ではない。
「規程例と違う」だけを理由に指摘してはいけない。指摘するのは、法令に反しているか、
法令が求める記載が無い場合に限る。
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.request

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "mhlw-model-rules")

SOURCES = {
    "model": {
        "label": "モデル就業規則",
        "version": "令和7年12月版",
        "index": ("https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/"
                  "roudoukijun/zigyonushi/model/index.html"),
        "doc": "https://www.mhlw.go.jp/content/001620506.docx",
        "ext": ".docx",
        "pattern": r'href="(/content/\d+\.docx)"',
    },
    "ikuji": {
        "label": "育児・介護休業等に関する規則の規定例",
        "version": "令和7年4月1日・10月1日施行対応版",
        "index": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/000103533.html",
        # 規定例本体（詳細版）の Word。社内様式例・労使協定例は別ファイル。
        "doc": "https://www.mhlw.go.jp/content/11909000/001672014.doc",
        "ext": ".doc",
        "pattern": r'href="(/content/11909000/\d+\.doc)"',
    },
}

ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


# --- 取得 -----------------------------------------------------------------

def discover(key):
    """掲載ページから最新の Word の URL を拾う。

    版が変わると URL の数字も変わるため、URL を固定で持つと改訂のたびに壊れる。
    拾えなければ既知の URL にフォールバックする。"""
    src = SOURCES[key]
    try:
        req = urllib.request.Request(src["index"],
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return src["doc"], False

    m = re.search(src["pattern"], html, re.I)
    if not m:
        return src["doc"], False
    return "https://www.mhlw.go.jp" + m.group(1), True


def ensure(key, refresh=False):
    src = SOURCES[key]
    os.makedirs(CACHE, exist_ok=True)
    doc = os.path.join(CACHE, key + src["ext"])
    txt = os.path.join(CACHE, key + ".txt")

    if refresh or not os.path.exists(txt):
        if refresh or not os.path.exists(doc):
            url, live = discover(key)
            note = "" if live else "（掲載ページを読めず既知のURLを使用）"
            sys.stderr.write(f"{src['label']}（{src['version']}）を取得しています…{note}\n")
            if live and url != src["doc"]:
                sys.stderr.write(
                    f"[情報] スクリプトが想定するファイルと異なるものが掲載されています。\n"
                    f"        新しい版の可能性があります。--toc で条の構成を確認してください。\n")
            try:
                urllib.request.urlretrieve(url, doc)
            except Exception as e:
                sys.exit(f"ダウンロードに失敗しました: {e}\n"
                         f"掲載ページで最新のURLを確認してください:\n{src['index']}")
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(here, "extract_text.py"),
                            doc, "-o", txt], capture_output=True)
        if r.returncode != 0:
            sys.exit(r.stderr.decode("utf-8", "replace"))

    with open(txt, encoding="utf-8") as f:
        return f.read().split("\n")


# --- モデル就業規則の解析（規程例が表のセルに入っている） -------------------

CAPTION_RE = re.compile(r'^（([^（）。、]{1,30})）')
NUM_RE = re.compile(r'第\s*([０-９0-9]+)\s*条')
TOC_RE = re.compile(r'^第\s*([０-９0-9]+)\s*条\s*（([^（）]{1,30})）\s*$')


def toc_numbers(lines):
    """冒頭の目次から「条見出し → 条番号」を作る。

    規程例の本文側は Word の自動採番で番号が取れない条があるため、目次から補う。"""
    m = {}
    for ln in lines:
        t = TOC_RE.match(ln.strip())
        if t:
            m.setdefault(t.group(2).strip(), int(t.group(1).translate(ZEN)))
    return m


def parse_model(lines):
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith('|'):
            continue
        cell = ln.strip('| ').strip()
        m = CAPTION_RE.match(cell)
        if not m:
            continue
        nm = NUM_RE.search(cell[m.end():m.end() + 40])
        body = []
        for nxt in lines[i + 1:]:
            if nxt.startswith('|'):
                break
            body.append(nxt)
        out.append({
            'source': 'model',
            'caption': m.group(1).strip(),
            'num': int(nm.group(1).translate(ZEN)) if nm else None,
            'variant': None,
            'text': cell,
            'explain': '\n'.join(body).strip(),
        })

    toc = toc_numbers(lines)
    for s in out:
        if s['num'] is None and s['caption'] in toc:
            s['num'] = toc[s['caption']]
    return out


# --- 育介の規定例の解析（見出し行・条番号行・本文の3段） --------------------

CAPTION_ONLY_RE = re.compile(r'^（([^（）]{1,40})）\s*$')
ART_LINE_RE = re.compile(r'^第\s*([０-９0-9]+)\s*条(?:\s*（続き）)?\s*$')
CHAPTER_RE = re.compile(r'^第[０-９0-9一二三四五六七八九十]+章')
VARIANT_RE = re.compile(r'^(ケース[①-⑳]|【[^】]{1,40}】|◇[^\n]{1,40})\s*《?([^》]*)》?')


def parse_ikuji(lines):
    """（見出し）／第N条／本文 の3段構成を拾う。

    同じ条に「ケース①〜③」のような選択肢が並ぶのがこの規定例の特徴で、
    事業場の事情に応じてどれかを選ぶ前提になっている。variant として残す。"""
    out = []
    pending_caption = None
    pending_variant = None
    i = 0
    while i < len(lines):
        ln = lines[i].strip()

        v = VARIANT_RE.match(ln)
        if v:
            pending_variant = ln[:60]
            i += 1
            continue

        if CHAPTER_RE.match(ln):
            pending_variant = None
            i += 1
            continue

        c = CAPTION_ONLY_RE.match(ln)
        if c:
            pending_caption = c.group(1).strip()
            i += 1
            continue

        am = ART_LINE_RE.match(ln)
        if am and pending_caption:
            num = int(am.group(1).translate(ZEN))
            body = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if (CAPTION_ONLY_RE.match(nxt) or ART_LINE_RE.match(nxt)
                        or CHAPTER_RE.match(nxt) or VARIANT_RE.match(nxt)):
                    break
                body.append(lines[j])
                j += 1
            out.append({
                'source': 'ikuji',
                'caption': pending_caption,
                'num': num,
                'variant': pending_variant,
                'text': '\n'.join(x for x in body if x.strip()).strip(),
                'explain': '',
            })
            pending_caption = None
            pending_variant = None
            i = j
            continue
        i += 1
    return out


PARSERS = {'model': parse_model, 'ikuji': parse_ikuji}


def load(key, refresh=False):
    return PARSERS[key](ensure(key, refresh))


def unwrap(s):
    """1行に潰れた規程例を、項ごとに改行して読めるようにする。"""
    s = s.strip('| ').strip()
    s = re.sub(r'[ \t]{2,}', ' ', s)
    s = re.sub(r'(?<=[。）\s])(?=[２-９]０?　)', '\n', s)
    s = re.sub(r'\s(?=[①-⑳])', '\n', s)
    return s.strip()


# --- CLI ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--toc', action='store_true', help='規程例の目次')
    ap.add_argument('--grep', help='条見出し・本文に含まれる語で探す')
    ap.add_argument('--article', type=int, help='条番号で引く（--source の指定が要る）')
    ap.add_argument('--source', choices=['model', 'ikuji', 'both'], default='both',
                    help='どの規程例を見るか（既定: both）')
    ap.add_argument('--explain', action='store_true',
                    help='厚労省の解説も表示する（モデル就業規則のみ）')
    ap.add_argument('--version-info', action='store_true')
    ap.add_argument('--refresh', action='store_true', help='取り直す')
    a = ap.parse_args()

    if a.version_info:
        for k, src in SOURCES.items():
            url, live = discover(k)
            txt = os.path.join(CACHE, k + ".txt")
            print(f"[{k}] 厚生労働省「{src['label']}」{src['version']}"
                  f"{'' if live else '（掲載ページを読めず、既知の情報）'}")
            print(f"     doc: {url}")
            print(f"     掲載ページ: {src['index']}")
            print(f"     キャッシュ: {txt if os.path.exists(txt) else '（未取得）'}")
        print("\n版が古い可能性があるときは --refresh。"
              "それでも変わらなければ掲載ページで新しいURLを確認すること。")
        return

    keys = list(SOURCES) if a.source == 'both' else [a.source]
    if a.article and a.source == 'both':
        sys.exit("--article は条番号が規程例ごとに別なので、--source model か "
                 "--source ikuji を付けてください。")

    secs = []
    for k in keys:
        secs += load(k, a.refresh)

    if a.toc or not (a.grep or a.article):
        for k in keys:
            ss = [s for s in secs if s['source'] == k]
            print(f"\n■ 厚生労働省「{SOURCES[k]['label']}」{SOURCES[k]['version']}"
                  f"  規程例 {len(ss)} 件\n")
            for s in ss:
                n = f"第{s['num']}条" if s['num'] else "（番号不明）"
                v = f"  〔{s['variant']}〕" if s['variant'] else ""
                print(f"  {n:<10} {s['caption']}{v}")
        print("\n--grep <語> または --article <番号> --source <名> で本文を表示します。")
        print("※ 同じ条番号が複数あるのは、制度ごと・ケースごとの選択肢が並んでいるため。")
        return

    if a.article:
        hits = [s for s in secs if s['num'] == a.article]
        if not hits:
            print(f"第{a.article}条は見つかりませんでした"
                  "（Word の自動採番で番号が取れないことがあります）。"
                  "--toc か --grep で探してください。")
            return
    else:
        hits = [s for s in secs
                if a.grep in s['caption'] or a.grep in s['text']]

    if not hits:
        print("該当する規程例がありませんでした。--toc で目次を確認してください。")
        print("育介法まわりが見つからない場合は --source ikuji を試してください。")
        return

    shown = set()
    for s in hits:
        src = SOURCES[s['source']]
        if s['source'] not in shown:
            print(f"\n出典: 厚生労働省「{src['label']}」{src['version']}")
            shown.add(s['source'])
        print("=" * 64)
        n = f"第{s['num']}条" if s['num'] else ""
        v = f"  〔{s['variant']}〕" if s['variant'] else ""
        print(f"{n}（{s['caption']}）{v}")
        print("=" * 64)
        print(unwrap(s['text']))
        if a.explain and s['explain']:
            print("\n--- 厚労省の解説 ---")
            print(s['explain'])
        print()


if __name__ == '__main__':
    main()
