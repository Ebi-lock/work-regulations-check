#!/usr/bin/env python3
"""就業規則を作るための聞き取りを、順を追って進める。

質問の順序・分岐・進捗を機械側で持つ。モデルの記憶だけに任せると、
順序が飛ぶ、聞いたつもりで聞いていない、制度が無いのに細目を聞く、が起きる。

    python3 intake.py --start /tmp/hearing.json      # 開始
    python3 intake.py --next                          # 次に聞く質問（既定5問）
    python3 intake.py --answer base.company="株式会社テスト" base.industry="小売"
    python3 intake.py --answer worktime.flex=保留      # 決まらないものは保留
    python3 intake.py --status                        # 進捗
    python3 intake.py --summary                       # 聞き取り結果をMarkdownで
    python3 intake.py --pending                       # 保留・未回答の一覧

回答ファイルのパスは --file で指定するか、環境変数 INTAKE_FILE で渡す。
--start で作ったパスは同ファイル内に記録されるので、以降は省略できる。
"""
import argparse
import json
import os
import sys

# 質問バンクは work-regulations-check 側の references に1つだけ置く。
# 作成スキル（work-regulations-draft）からは scripts がシンボリックリンクなので、
# realpath で実体の位置に解決してから参照する。2箇所に置くと片方だけ直る事故になる。
HERE = os.path.dirname(os.path.realpath(__file__))
BANK = os.path.join(HERE, "..", "references", "questions.json")
STATE_POINTER = os.path.join(os.path.expanduser("~"), ".cache", "work-rules-intake")

HOLD = "保留"


def load_bank():
    with open(BANK, encoding="utf-8") as f:
        return json.load(f)


def state_path(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("INTAKE_FILE"):
        return os.environ["INTAKE_FILE"]
    if os.path.exists(STATE_POINTER):
        with open(STATE_POINTER, encoding="utf-8") as f:
            p = f.read().strip()
        if p and os.path.exists(p):
            return p
    sys.exit("回答ファイルがありません。--start <パス> で開始してください。")


def load_state(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(path, st):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def visible(q, answers):
    """depends_on が満たされていれば聞く。制度が無いなら細目は聞かない。"""
    dep = q.get("depends_on")
    if not dep:
        return True
    for key, want in dep.items():
        got = answers.get(key)
        if got is None or got == HOLD:
            return False
        if isinstance(want, list):
            if got not in want:
                return False
        elif str(got) != str(want):
            return False
    return True


def all_questions(bank):
    for sec in bank["sections"]:
        for q in sec["questions"]:
            yield sec, q


def next_batch(bank, answers, size):
    out = []
    for sec, q in all_questions(bank):
        qid = f"{sec['id']}.{q['id']}"
        if qid in answers:
            continue
        if not visible(q, answers):
            continue
        out.append((sec, q, qid))
        if len(out) >= size:
            break
    return out


def progress(bank, answers):
    asked = answered = held = 0
    for sec, q in all_questions(bank):
        qid = f"{sec['id']}.{q['id']}"
        if not visible(q, answers) and qid not in answers:
            continue
        asked += 1
        if qid in answers:
            if answers[qid] == HOLD:
                held += 1
            else:
                answered += 1
    return answered, held, asked


def cmd_next(bank, st, size):
    batch = next_batch(bank, st["answers"], size)
    if not batch:
        a, h, t = progress(bank, st["answers"])
        print("聞き取りは完了です。")
        if h:
            print(f"保留が {h} 件あります。--pending で確認してください。")
        print("--summary で結果を出力できます。")
        return

    sec = batch[0][0]
    a, h, t = progress(bank, st["answers"])
    print(f"■ {sec['title']}　（{a + h}/{t} 問 回答済み）")
    if sec.get("note"):
        print(f"  {sec['note']}")
    print()

    for _, q, qid in batch:
        print(f"[{qid}] {q['text']}")
        if q.get("why"):
            print(f"    なぜ: {q['why']}")
        if q.get("options"):
            for o in q["options"]:
                mark = " ←モデル就業規則の例" if o == q.get("default") else ""
                print(f"    - {o}{mark}")
        elif q.get("default"):
            print(f"    既定値の例: {q['default']}")
        if q.get("caution"):
            print(f"    注意: {q['caution']}")
        print()

    print("回答の記録:")
    print("  python3 intake.py --answer " +
          " ".join(f'{qid}="…"' for _, _, qid in batch))
    print(f"  決まらないものは {HOLD} と記録すること（推測で埋めない）")


def cmd_answer(bank, st, path, pairs):
    index = {f"{s['id']}.{q['id']}": (s, q) for s, q in all_questions(bank)}
    ok, bad = [], []
    for pair in pairs:
        if "=" not in pair:
            bad.append(f"{pair}（= がない）")
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k not in index:
            bad.append(f"{k}（そのIDの質問はない）")
            continue
        st["answers"][k] = v
        ok.append(f"{k} = {v}")
    save_state(path, st)
    for x in ok:
        print("記録:", x)
    for x in bad:
        print("無視:", x, file=sys.stderr)
    a, h, t = progress(bank, st["answers"])
    print(f"\n進捗: {a + h}/{t}（うち保留 {h}）")
    if next_batch(bank, st["answers"], 1):
        print("次の質問は --next で表示します。")
    else:
        print("聞き取り完了。--summary で出力できます。")


def cmd_status(bank, st):
    a, h, t = progress(bank, st["answers"])
    print(f"進捗: {a + h}/{t} 問（回答 {a} / 保留 {h} / 未回答 {t - a - h}）\n")
    for sec in bank["sections"]:
        done = tot = 0
        for q in sec["questions"]:
            qid = f"{sec['id']}.{q['id']}"
            if not visible(q, st["answers"]) and qid not in st["answers"]:
                continue
            tot += 1
            if qid in st["answers"]:
                done += 1
        if tot:
            bar = "█" * int(10 * done / tot) + "░" * (10 - int(10 * done / tot))
            print(f"  {bar} {done:>2}/{tot:<2} {sec['title']}")


def cmd_pending(bank, st):
    held, unans = [], []
    for sec, q in all_questions(bank):
        qid = f"{sec['id']}.{q['id']}"
        if st["answers"].get(qid) == HOLD:
            held.append((sec, q, qid))
        elif qid not in st["answers"] and visible(q, st["answers"]):
            unans.append((sec, q, qid))

    print(f"■ 保留（決める必要がある項目）: {len(held)} 件")
    for sec, q, qid in held:
        print(f"  [{qid}] {q['text']}")
        if q.get("affects"):
            print(f"      影響する条: {q['affects']}")
    if not held:
        print("  なし")

    print(f"\n■ 未回答: {len(unans)} 件")
    for sec, q, qid in unans[:20]:
        print(f"  [{qid}] {q['text']}")
    if len(unans) > 20:
        print(f"  … 他 {len(unans) - 20} 件")
    if not unans:
        print("  なし")


def cmd_summary(bank, st):
    print("# 聞き取り結果\n")
    for sec in bank["sections"]:
        rows = []
        for q in sec["questions"]:
            qid = f"{sec['id']}.{q['id']}"
            if qid in st["answers"]:
                rows.append((q["text"], st["answers"][qid], q.get("affects", "")))
        if not rows:
            continue
        print(f"## {sec['title']}\n")
        print("| 項目 | 回答 | 影響する条 |")
        print("|---|---|---|")
        for t, v, a in rows:
            mark = f"**{v}**" if v == HOLD else v
            print(f"| {t} | {mark} | {a} |")
        print()

    held = [(f"{s['id']}.{q['id']}", q) for s, q in all_questions(bank)
            if st["answers"].get(f"{s['id']}.{q['id']}") == HOLD]
    if held:
        print("## 決める必要がある項目\n")
        print("| 項目 | 影響する条 |")
        print("|---|---|")
        for qid, q in held:
            print(f"| {q['text']} | {q.get('affects', '')} |")
        print()
        print("これらは推測で埋めていない。決まってから条文に反映すること。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", metavar="PATH", help="聞き取りを開始する")
    ap.add_argument("--file", help="回答ファイルのパス")
    ap.add_argument("--next", action="store_true", help="次に聞く質問")
    ap.add_argument("--size", type=int, default=5, help="1回に出す質問数（既定5）")
    ap.add_argument("--answer", nargs="+", metavar="ID=値", help="回答を記録")
    ap.add_argument("--status", action="store_true", help="進捗")
    ap.add_argument("--pending", action="store_true", help="保留・未回答")
    ap.add_argument("--summary", action="store_true", help="結果をMarkdownで")
    a = ap.parse_args()

    bank = load_bank()

    if a.start:
        path = os.path.abspath(a.start)
        if os.path.exists(path):
            st = load_state(path)
            print(f"既存の回答ファイルを使います: {path}")
        else:
            st = {"answers": {}}
            save_state(path, st)
            print(f"聞き取りを開始します: {path}")
        os.makedirs(os.path.dirname(STATE_POINTER), exist_ok=True)
        with open(STATE_POINTER, "w", encoding="utf-8") as f:
            f.write(path)
        a2, h, t = progress(bank, st["answers"])
        print(f"全 {t} 問（制度の有無で増減します）\n")
        cmd_next(bank, st, a.size)
        return

    path = state_path(a.file)
    st = load_state(path)

    if a.answer:
        cmd_answer(bank, st, path, a.answer)
    elif a.status:
        cmd_status(bank, st)
    elif a.pending:
        cmd_pending(bank, st)
    elif a.summary:
        cmd_summary(bank, st)
    else:
        cmd_next(bank, st, a.size)


if __name__ == "__main__":
    main()
