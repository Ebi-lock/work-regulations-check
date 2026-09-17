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
    if not branch:
        return f"第{n}条"
    if isinstance(branch, int):
        branch = (branch,)
    return f"第{n}条" + "".join(f"の{b}" for b in branch)


PARA_RE = re.compile(r'^\s*第\s*([' + NUM_CHARS + r']+)\s*項')


def para_of(line, pos):
    """「第67条第3項」の項番号を拾う。無ければ None。"""
    m = PARA_RE.match(line[pos:pos + 10])
    return kanji_to_int(m.group(1)) if m else None


NUMBERED_PARA_RE = re.compile(r'^\s*([０-９0-9]{1,2}|[一-九十]{1,3})[　 ]')


def count_paragraphs(lines, articles):
    """各条が何項まであるかを数える。

    項番号は本文側に「2　」「３　」の形で振られる。第1項は番号が無いのが通例なので、
    見つかった最大の番号か、無ければ1を返す。行頭の箇条書き番号と紛れうるため、
    あくまで目安として扱い、超過している参照だけを報告する。"""
    spans = []
    for idx, a in enumerate(articles):
        end = articles[idx + 1]['line'] - 1 if idx + 1 < len(articles) else len(lines)
        spans.append((a, a['line'], end))

    out = {}
    for a, start, end in spans:
        mx = 1
        for ln in lines[start:end]:
            m = NUMBERED_PARA_RE.match(ln)
            if m:
                v = kanji_to_int(m.group(1))
                if v and 1 < v <= 30:
                    mx = max(mx, v)
        out[(a['num'], a['branch'])] = mx
    return out


# 「第三十二条の二（服務）」「第 32 条の2」「第66条の8の2」などを拾う。
# 枝番は多段になることがあるので繰り返しで受ける。1段しか見ないと
# 「第66条の8の2」が「第66条の8」に化けて、別の条を指しているように見える。
ART_RE = re.compile(
    r'第\s*([' + NUM_CHARS + r']+)\s*条((?:\s*の\s*[' + NUM_CHARS + r']+)*)')
BRANCH_RE = re.compile(r'の\s*([' + NUM_CHARS + r']+)')

# 「労働安全衛生法第66条の8」のように、直前に法令名が来る参照は外部法令。
# 規程内部の条番号と混ぜると、実在しない参照切れを大量に報告することになる。
EXT_LAW_RE = re.compile(
    r'(?:[一-龥ァ-ヴA-Za-z0-9・ー]{2,30}?(?:法|令|規則|条例|協定|指針)'
    r'(?:施行(?:令|規則))?)\s*$')

# 条見出しは「（休職）第9条 …」のように括弧書きが同じ行の前に来ることがある。
# 行頭からこれだけなら、条文の定義行とみなす。
CAPTION_PREFIX_RE = re.compile(r'^[（(][^（）()。]{1,40}[)）]\s*$')

# 行頭にあっても定義とは限らない。「第67条第3項から第5項までの規定を準用する」は
# 準用の参照であって、第67条をそこで定義しているわけではない。
# 条番号の直後がこれらで続くなら参照として扱う。
REF_FOLLOW_RE = re.compile(
    r'^\s*(?:第\s*[' + NUM_CHARS + r']+\s*[項号]|から|まで|及び|並びに|又は|若しくは|'
    r'の規定|に規定|に定め|による|により|に基づ|の定め|乃至|・|、|～|〜)')
CHAP_RE = re.compile(
    r'第\s*([' + NUM_CHARS + r']+)\s*(章|編|節)\s*(.{0,30})')


HEADING_ONLY_RE = re.compile(r'^[（(]\s*(.{1,30}?)\s*[)）]$')


def parse(text):
    lines = text.split('\n')
    articles, chapters, refs, external_refs = [], [], [], []

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

        first_on_line = True
        for m in ART_RE.finditer(ln):
            n = kanji_to_int(m.group(1))
            branches = tuple(x for x in
                             (kanji_to_int(g) for g in BRANCH_RE.findall(m.group(2)))
                             if x is not None)
            b = branches if branches else None
            if n is None:
                continue

            head = ln[:m.start()].strip(' 　\t')

            # 直前が法令名なら、この規程の条ではなく外部法令の引用
            if EXT_LAW_RE.search(head):
                external_refs.append({'num': n, 'branch': b, 'line': i,
                                      'law': EXT_LAW_RE.search(head).group(0).strip(),
                                      'context': stripped[:100]})
                first_on_line = False
                continue

            # 行頭、または行頭が条見出しの括弧書きだけなら、条文の定義行。
            # ただし直後が項番号や「から」なら参照なので除く。
            follows_as_ref = bool(REF_FOLLOW_RE.match(ln[m.end():]))
            is_def = (first_on_line
                      and (head == '' or CAPTION_PREFIX_RE.match(head))
                      and not follows_as_ref)
            if is_def:
                rest = ln[m.end():].strip(' 　\t')
                inline = HEADING_ONLY_RE.match(rest)
                if head and CAPTION_PREFIX_RE.match(head):   # （休職）第9条 本文…
                    title = head.strip('（）() 　')
                elif inline:                                  # 第1条（目的） 本文…
                    title = inline.group(1)
                elif pending_heading:                         # （目的）\n第1条 本文…
                    title = pending_heading
                else:
                    body = rest.strip('（）()')
                    title = f"（見出しなし）{body[:28]}" if body else "（見出しなし）"
                articles.append({'num': n, 'branch': b, 'title': title[:40], 'line': i})
                pending_heading = None
            else:
                # 「第7条から第9条まで」の範囲参照を拾うため、後続の語も見る
                tail = ln[m.end():m.end() + 12]
                refs.append({'num': n, 'branch': b, 'line': i,
                             'range_to': bool(re.match(r'\s*(から|〜|～)', tail)),
                             'para': para_of(ln, m.end()),
                             'context': stripped[:100]})
            first_on_line = False

    return articles, chapters, refs, external_refs


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


def check_refs(articles, chapters, refs, paras):
    """内部参照を解決する。

    「参照先が無い」だけでなく、**参照先が何の条か**を返すのが要点。
    条番号は合っているが中身が違う参照（「第51条に基づき割増賃金」だが
    第51条は手当の条、など）は、存在チェックでは絶対に見つからない。
    見出しを並べて人が見比べられるようにする。"""
    index = {(a['num'], a['branch']): a for a in articles}
    main_index = {a['num']: a for a in articles if not a['branch']}

    dangling, resolved, bad_para = [], [], []
    for r in refs:
        key = (r['num'], r['branch'])
        target = index.get(key)
        if target is None and r['branch'] and r['num'] in main_index:
            dangling.append({**r, 'note': f'第{r["num"]}条はあるが枝番が見つからない'})
            continue
        if target is None and not r['branch']:
            target = main_index.get(r['num'])
        if target is None:
            dangling.append({**r, 'note': '参照先の条が見つからない'})
            continue

        resolved.append({**r, 'title': target['title'], 'target_line': target['line']})

        p = r.get('para')
        if p:
            mx = paras.get((target['num'], target['branch']), 1)
            if p > mx:
                bad_para.append({**r, 'title': target['title'],
                                 'max': mx, 'want': p})
    return dangling, resolved, bad_para


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
    ap.add_argument('--refs', action='store_true',
                    help='内部参照の解決先を全件表示する（中身違いの参照を目視で探すため）')
    a = ap.parse_args()

    with open(a.path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    lines = text.split('\n')

    articles, chapters, refs, external = parse(text)
    paras = count_paragraphs(lines, articles)
    seq = check_sequence(articles)
    dangling, resolved, bad_para = check_refs(articles, chapters, refs, paras)
    self_titles = {c['title'] for c in chapters} | {x['title'] for x in articles}
    ext_docs = find_external(text, self_titles)
    terms = check_terms(text)

    if a.json:
        print(json.dumps({
            'articles': len(articles), 'chapters': len(chapters),
            'sequence_issues': seq, 'dangling_refs': dangling,
            'paragraph_issues': bad_para, 'resolved_refs': resolved,
            'external_law_refs': external, 'external_docs': ext_docs,
            'term_variants': terms,
        }, ensure_ascii=False, indent=2))
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
        p = paras.get((x['num'], x['branch']), 1)
        w(f"  {fmt(x['num'], x['branch']):<12} {x['title']}"
          f"{f'  [{p}項]' if p > 1 else ''}\n")
    w("\n")

    w(f"【条番号の不整合】 {len(seq)} 件\n")
    for x in seq:
        line = f" (行 {x['line']})" if 'line' in x else ''
        w(f"  [{x['type']}] {x['article']}: {x['detail']}{line}\n")
    if not seq:
        w("  なし\n")
    w("\n")

    w(f"【参照先が見つからない内部参照】 {len(dangling)} 件\n")
    seen = set()
    for d in dangling:
        k = (d['line'], d['num'], d['branch'])
        if k in seen:
            continue
        seen.add(k)
        w(f"  行 {d['line']}: {fmt(d['num'], d['branch'])} — {d['note']}\n")
        w(f"      > {d['context']}\n")
    if not dangling:
        w("  なし\n")
    w("\n")

    w(f"【存在しない項への参照】 {len(bad_para)} 件\n")
    for b in bad_para:
        w(f"  行 {b['line']}: {fmt(b['num'], b['branch'])}第{b['want']}項"
          f" — {b['title']} は第{b['max']}項までしかない\n")
        w(f"      > {b['context']}\n")
    if not bad_para:
        w("  なし\n")
    w("  ※ 項数は本文の項番号から数えた目安。箇条書きと紛れることがあるので原文で確認すること\n\n")

    w(f"【内部参照の解決先】 {len(resolved)} 件\n")
    w("  ※ **条番号は合っているが中身が違う参照**は、ここを読まないと見つからない。\n")
    w("     参照元の文意と、参照先の見出しが噛み合っているか必ず目で確かめること。\n")
    show = resolved if a.refs else resolved[:25]
    for r in show:
        para = f"第{r['para']}項" if r.get('para') else ""
        w(f"  行 {r['line']}: {fmt(r['num'], r['branch'])}{para}"
          f" → 「{r['title']}」\n")
        w(f"      > {r['context']}\n")
    if not a.refs and len(resolved) > 25:
        w(f"  … 他 {len(resolved) - 25} 件。全件見るには --refs\n")
    if not resolved:
        w("  なし\n")
    w("\n")

    if external:
        w(f"【外部法令への参照】 {len(external)} 件（内部参照とは区別済み）\n")
        agg = {}
        for e in external:
            agg.setdefault((e['law'], e['num'], e['branch']), []).append(e['line'])
        for (law, n, b), ls in sorted(agg.items()):
            w(f"  {law}{fmt(n, b)}  (行 {', '.join(str(x) for x in sorted(set(ls))[:5])})\n")
        w("  ※ 引用している法令の条番号が改正でずれていないか、fetch_law.py で確認すること\n\n")

    w(f"【本文から参照されている別規程・別表】 {len(ext_docs)} 件\n")
    w("  ※ 手元に無いものは、内容を確認できない旨をレポートに書くこと\n")
    for name, c in ext_docs:
        w(f"  {name} ({c} 箇所)\n")
    if not ext_docs:
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
