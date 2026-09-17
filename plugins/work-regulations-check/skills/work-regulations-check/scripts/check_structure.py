#!/usr/bin/env python3
"""就業規則テキストの形式面を機械的に点検し、条文の地図を出力する。

使い方:
    python3 check_structure.py <text-file> [--json]

機械判定できるものだけを扱う:
  - 章・条の一覧 (この規程に何が書かれているかの地図)
  - 条番号の飛び / 重複 / 逆順
  - 内部参照 (第○条・第○章) の参照先が存在しないもの
  - 別規程・別表への参照 (添付されていなければ確認対象)
  - 用語のゆれ

内容面の妥当性はここでは判定しない。SKILL.md の references/ を読んで人間の目で見ること。
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict

KANJI = {'〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
         '六': 6, '七': 7, '八': 8, '九': 9}
UNITS = {'十': 10, '百': 100, '千': 1000}
NUM_CHARS = '0-9０-９〇零一二三四五六七八九十百千'


def kanji_to_int(s):
    """「三十二」「百二十」「32」「３２」→ int。解釈できなければ None。"""
    s = s.strip()
    z = s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    if z.isdigit():
        return int(z)

    total, cur = 0, 0
    for ch in s:
        if ch in KANJI:
            cur = KANJI[ch]
        elif ch in UNITS:
            u = UNITS[ch]
            total += (cur if cur else 1) * u
            cur = 0
        else:
            return None
    return total + cur


def fmt(n, branch):
    return f"第{n}条" + (f"の{branch}" if branch else "")


# 「第三十二条の二（服務）」「第 32 条の2」などを拾う
ART_RE = re.compile(
    r'第\s*([' + NUM_CHARS + r']+)\s*条(?:\s*の\s*([' + NUM_CHARS + r']+))?')
CHAP_RE = re.compile(
    r'第\s*([' + NUM_CHARS + r']+)\s*(章|編|節)\s*(.{0,30})')


HEADING_ONLY_RE = re.compile(r'^[（(]\s*(.{1,30}?)\s*[)）]$')


def parse(text):
    lines = text.split('\n')
    articles, chapters, refs = [], [], []

    # 「（目的）」を前の行に置き、次の行を「第1条 本規則は…」で始める書式が多い。
    # 条文の本文を見出しとして拾ってしまわないよう、直前の括弧書きを見出し候補にする。
    pending_heading = None

    for i, ln in enumerate(lines, 1):
        stripped = ln.strip()

        hm = HEADING_ONLY_RE.match(stripped)
        if hm:
            pending_heading = hm.group(1)
            continue

        m = CHAP_RE.match(stripped)
        if m:
            n = kanji_to_int(m.group(1))
            if n is not None:
                chapters.append({'num': n, 'kind': m.group(2),
                                 'title': m.group(3).strip(' 　()（）'), 'line': i})
                pending_heading = None
                continue

        for m in ART_RE.finditer(ln):
            n = kanji_to_int(m.group(1))
            b = kanji_to_int(m.group(2)) if m.group(2) else None
            if n is None:
                continue
            # 行頭にあれば条文の見出し、本文中にあれば参照とみなす
            head = ln[:m.start()].strip(' 　\t')
            if head == '':
                rest = ln[m.end():].strip(' 　\t')
                inline = HEADING_ONLY_RE.match(rest)
                if inline:                      # 第1条（目的） 本文…
                    title = inline.group(1)
                elif pending_heading:           # （目的）\n第1条 本文…
                    title = pending_heading
                else:
                    title = rest.strip('（）()')[:40]
                articles.append({'num': n, 'branch': b, 'title': title[:40], 'line': i})
                pending_heading = None
            else:
                refs.append({'num': n, 'branch': b, 'line': i,
                             'context': stripped[:80]})

    return articles, chapters, refs


def check_sequence(articles):
    """条番号の飛び・重複・逆順を検出する。"""
    issues = []
    seen = Counter((a['num'], a['branch']) for a in articles)
    for key, c in seen.items():
        if c > 1:
            issues.append({'type': '重複', 'article': fmt(*key),
                           'detail': f'{c} 箇所に同じ条番号がある'})

    mains = [a for a in articles if a['branch'] is None]
    prev = None
    for a in mains:
        if prev is None:
            if a['num'] != 1:
                issues.append({'type': '開始', 'article': fmt(a['num'], None),
                               'detail': f'第1条ではなく第{a["num"]}条から始まっている'})
        elif a['num'] == prev:
            pass  # 重複は上で報告済み
        elif a['num'] < prev:
            issues.append({'type': '逆順', 'article': fmt(a['num'], None),
                           'detail': f'第{prev}条のあとに第{a["num"]}条が出てくる'
                                     '（附則や別規程の混在かもしれない）',
                           'line': a['line']})
        elif a['num'] > prev + 1:
            missing = list(range(prev + 1, a['num']))
            if len(missing) > 30:
                # 「第19２０条」のような全半角混在の誤記や、抽出時のノイズで
                # 桁が増えているケース。欠番を数百件並べても読めないので別扱いにする。
                issues.append({'type': '異常', 'article': f'第{a["num"]}条',
                               'detail': f'第{prev}条の直後に第{a["num"]}条が現れる。'
                                         '条番号の誤記（全角と半角の混在など）か、'
                                         'テキスト抽出のノイズの可能性が高い。原文を確認すること',
                               'line': a['line']})
                prev = a['num']
                continue
            label = '・'.join(f'第{m}条' for m in missing[:8])
            if len(missing) > 8:
                label += f' ほか{len(missing) - 8}件'
            issues.append({'type': '欠番', 'article': label,
                           'detail': f'第{prev}条の次が第{a["num"]}条になっている',
                           'line': a['line']})
        prev = max(prev or 0, a['num'])
    return issues


def check_refs(articles, chapters, refs, text):
    exist = {(a['num'], a['branch']) for a in articles}
    exist_main = {a['num'] for a in articles}
    dangling = []
    for r in refs:
        key = (r['num'], r['branch'])
        if key in exist:
            continue
        # 「第5条の2」が無くても「第5条」があるなら枝番の書き分けの問題として扱う
        if r['branch'] is not None and r['num'] in exist_main:
            dangling.append({**r, 'note': f'第{r["num"]}条はあるが枝番が見つからない'})
        elif r['branch'] is None and r['num'] not in exist_main:
            dangling.append({**r, 'note': '参照先の条が見つからない'})
    return dangling


# 別規程の名前はほぼ漢字・カタカナ・英数字でできている。ひらがなを外すことで
# 「〜については別に定めるパートタイマー就業規則」のように前の文をのみ込むのを防ぐ。
EXTERNAL_RE = re.compile(
    r'([一-龥ァ-ヴA-Za-z0-9０-９・ー]{2,20}?'
    r'(?:規程|規則|細則|要領|協定|マニュアル|ガイドライン|別表|様式))')

# 自分自身を指す言い方。これを別規程として数えると毎回ノイズになる。
SELF_REF = {'就業規則', '本規則', '本規程', 'この規則', 'この規程',
            '当規則', '当規程', '同規則', '同規程'}


def find_external(text, self_titles):
    hits = defaultdict(int)
    for m in EXTERNAL_RE.finditer(text):
        name = m.group(1).strip('・ー')
        if name in SELF_REF or name in self_titles or len(name) < 3:
            continue
        hits[name] += 1
    return sorted(hits.items(), key=lambda kv: -kv[1])


TERM_GROUPS = [
    ('従業員の呼び方', ['従業員', '社員', '労働者', '職員']),
    ('会社の呼び方', ['会社', '当社', '当法人', '本会社']),
    ('賃金の呼び方', ['賃金', '給与', '給料', '報酬']),
    ('年休の呼び方', ['年次有給休暇', '有給休暇', '年休', '年次休暇']),
    ('規程/規則', ['就業規則', '本規則', '本規程', 'この規則', 'この規程']),
    ('懲戒の呼び方', ['懲戒', '制裁']),
]


def check_terms(text):
    out = []
    for label, terms in TERM_GROUPS:
        counts = {}
        for t in terms:
            # 長い語の中に短い語が含まれるので、長い順に潰しながら数える
            counts[t] = text.count(t)
        # 「年次有給休暇」に含まれる「有給休暇」を差し引く
        for a in terms:
            for b in terms:
                if a != b and b in a and counts.get(a):
                    counts[b] = max(0, counts[b] - counts[a])
        used = {t: c for t, c in counts.items() if c > 0}
        if len(used) > 1:
            out.append({'label': label, 'counts': used})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    with open(a.path, encoding='utf-8', errors='replace') as f:
        text = f.read()

    articles, chapters, refs = parse(text)
    seq = check_sequence(articles)
    dangling = check_refs(articles, chapters, refs, text)
    self_titles = {c['title'] for c in chapters} | {a['title'] for a in articles}
    external = find_external(text, self_titles)
    terms = check_terms(text)

    result = {
        'articles': len(articles), 'chapters': len(chapters),
        'sequence_issues': seq, 'dangling_refs': dangling,
        'external_refs': external, 'term_variants': terms,
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    w = sys.stdout.write
    w(f"■ 構成: {len(chapters)} 章 / {len(articles)} 条\n\n")

    if chapters:
        w("【章立て】\n")
        for c in chapters:
            w(f"  第{c['num']}{c['kind']} {c['title']}  (行 {c['line']})\n")
        w("\n")

    w("【条文一覧】\n")
    for x in articles:
        w(f"  {fmt(x['num'], x['branch']):<10} {x['title']}\n")
    w("\n")

    w(f"【条番号の不整合】 {len(seq)} 件\n")
    for s in seq:
        line = f" (行 {s['line']})" if 'line' in s else ''
        w(f"  [{s['type']}] {s['article']}: {s['detail']}{line}\n")
    if not seq:
        w("  なし\n")
    w("\n")

    w(f"【参照先が見つからない内部参照】 {len(dangling)} 件\n")
    for d in dangling:
        w(f"  行 {d['line']}: {fmt(d['num'], d['branch'])} — {d['note']}\n")
        w(f"      > {d['context']}\n")
    if not dangling:
        w("  なし\n")
    w("\n")

    w(f"【本文から参照されている別規程・別表】 {len(external)} 件\n")
    w("  ※ 手元に無いものは、内容を確認できない旨をレポートに書くこと\n")
    for name, c in external:
        w(f"  {name} ({c} 箇所)\n")
    if not external:
        w("  なし\n")
    w("\n")

    w(f"【用語のゆれ】 {len(terms)} 件\n")
    w("  ※ 章や対象者を分けて意図的に使い分けている場合は問題ない。本文で確認すること\n")
    for t in terms:
        inner = '、'.join(f"{k} {v}回" for k, v in
                          sorted(t['counts'].items(), key=lambda kv: -kv[1]))
        w(f"  {t['label']}: {inner}\n")
    if not terms:
        w("  なし\n")


if __name__ == '__main__':
    main()
