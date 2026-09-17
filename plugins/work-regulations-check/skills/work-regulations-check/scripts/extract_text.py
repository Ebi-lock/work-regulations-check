#!/usr/bin/env python3
"""就業規則ファイルからテキストを抽出する。

使い方:
    python3 extract_text.py <path> [-o out.txt]

対応: .docx / .doc / .rtf / .odt / .txt / .md / .pdf
PDF は pypdf 等が入っていれば使い、無ければ Read ツールで読むよう案内して終了する
(終了コード 2)。表の中に賃金テーブルや休暇日数が入っていることが多いので、
docx では表も本文と同じ流れに書き出す。
"""
import argparse
import os
import re
import subprocess
import sys
from collections import Counter


def from_docx(path):
    try:
        import docx
    except ImportError:
        sys.exit("python-docx が見つかりません: pip3 install python-docx")

    d = docx.Document(path)
    out = []

    # 本文: 段落と表を出現順に並べる (document.element.body を辿る)
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            t = Paragraph(child, d).text.strip()
            if t:
                out.append(t)
        elif tag == 'tbl':
            tbl = Table(child, d)
            out.append('')
            for row in tbl.rows:
                cells = [c.text.strip().replace('\n', ' ') for c in row.cells]
                # 完全な重複セル (結合セル) を畳む
                dedup = [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]
                out.append('| ' + ' | '.join(dedup) + ' |')
            out.append('')

    # Word の自動採番で振られた条番号は paragraph.text に現れない。
    # 条番号が落ちたまま点検すると「条番号が無い」と誤って指摘するので警告する。
    numbered = sum(1 for p in d.paragraphs
                   if p._p.pPr is not None and p._p.pPr.numPr is not None)
    if numbered:
        sys.stderr.write(
            f"[警告] Word の自動採番が使われた段落が {numbered} 件あります。"
            "条番号や項番号がテキストに出ていない可能性があります。\n"
            "        条番号の点検は原本か PDF 版で確認してください。\n")

    # ヘッダー・フッター (改定日や版数が入っていることがある)
    hf = []
    for sec in d.sections:
        for part in (sec.header, sec.footer):
            for p in part.paragraphs:
                t = p.text.strip()
                if t and t not in hf:
                    hf.append(t)
    if hf:
        out.append('')
        out.append('--- ヘッダー/フッター ---')
        out.extend(hf)

    return '\n'.join(out)


def from_textutil(path):
    if sys.platform != 'darwin':
        sys.exit(f"{os.path.splitext(path)[1]} の変換には macOS の textutil が必要です。"
                 "docx か txt に変換してから渡してください。")
    r = subprocess.run(['textutil', '-convert', 'txt', '-stdout', path],
                       capture_output=True)
    if r.returncode != 0:
        sys.exit(f"textutil に失敗しました: {r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode('utf-8', 'replace')


def from_pdf(path):
    for mod, fn in (
        ('pypdf', lambda m: '\n'.join(p.extract_text() or '' for p in m.PdfReader(path).pages)),
        ('PyPDF2', lambda m: '\n'.join(p.extract_text() or '' for p in m.PdfReader(path).pages)),
        ('pdfplumber', lambda m: '\n'.join(
            (pg.extract_text() or '') for pg in m.open(path).pages)),
        ('fitz', lambda m: '\n'.join(pg.get_text() for pg in m.open(path))),
    ):
        try:
            m = __import__(mod)
        except ImportError:
            continue
        text = fn(m)
        if text.strip():
            return text
        sys.stderr.write(
            f"[警告] {mod} でテキストを取得できませんでした。"
            "スキャン画像のPDFの可能性があります。\n")
        break

    sys.stderr.write(
        "PDF からテキストを抽出できるライブラリがありません。\n"
        "次のどちらかで進めてください。\n"
        "  1) Read ツールで PDF を直接読む (pages 引数で 20 ページずつ、全ページ通しで)\n"
        "  2) pip3 install pypdf を実行してから再試行する\n")
    sys.exit(2)


PAGENO_RE = re.compile(r'^[\s　]*(?:[-–—]?\s*)?[0-9０-９]{1,3}(?:\s*[/／]\s*[0-9０-９]{1,3})?'
                       r'(?:\s*[-–—])?[\s　]*$')


def strip_running_heads(lines):
    """PDF のページヘッダー・フッターを落とす。

    条文と紛れないよう、(1) 3回以上繰り返される短い行、(2) ページ番号だけの行、
    に限って削除する。条番号を含む行は本文の可能性があるので必ず残す。
    """
    # ページ番号だけが違うフッター (「... ©2025 3」) も同じものとして数えるため、
    # 末尾の数字を落とした形でも照合する。
    def key(s):
        return re.sub(r'[\s　]*[0-9０-９]{1,3}[\s　]*$', '', s).strip()

    body = [ln.strip() for ln in lines if ln.strip()]
    counts = Counter(body)
    counts_k = Counter(key(s) for s in body)
    repeated = {s for s in set(body)
                if len(s) <= 60 and '条' not in s
                and (counts[s] >= 3 or (key(s) and counts_k[key(s)] >= 3))}

    out, dropped = [], 0
    for ln in lines:
        s = ln.strip()
        if s and (s in repeated or PAGENO_RE.match(s)):
            dropped += 1
            continue
        out.append(ln)
    if dropped:
        sys.stderr.write(f"[情報] ページヘッダー/フッターとみられる {dropped} 行を除去しました\n")

    # 連続する空行を1行にまとめる
    squeezed = []
    for ln in out:
        if not ln.strip() and squeezed and not squeezed[-1].strip():
            continue
        squeezed.append(ln)
    return squeezed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('-o', '--out', help='出力先。省略時は標準出力')
    a = ap.parse_args()

    if not os.path.exists(a.path):
        sys.exit(f"ファイルが見つかりません: {a.path}")

    ext = os.path.splitext(a.path)[1].lower()
    if ext == '.docx':
        text = from_docx(a.path)
    elif ext in ('.doc', '.rtf', '.rtfd', '.odt', '.html', '.htm'):
        text = from_textutil(a.path)
    elif ext == '.pdf':
        text = from_pdf(a.path)
    elif ext in ('.txt', '.md', ''):
        with open(a.path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    else:
        sys.exit(f"未対応の形式です: {ext}")

    # 全角スペースだけの行など、条文の区切りを壊さない範囲で整える
    lines = [ln.rstrip() for ln in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    if ext == '.pdf':
        lines = strip_running_heads(lines)
    text = '\n'.join(lines)

    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
        chars = len(text)
        sys.stderr.write(f"抽出しました: {a.out} ({chars:,} 文字 / {len(lines):,} 行)\n")
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
