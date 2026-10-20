#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileMove のデモ。サンプルのフォルダを作り、主な使い方を順番に実行して見せる。

    python demo/demo.py            # 1 ステップごとに Enter で進む
    python demo/demo.py --auto     # 止まらずに最後まで流す
    python demo/demo.py --only 8   # ⑧ だけ表示する（前のステップは黙って実行する）

demo/work/（--work で変更可）以外には何も書き込まない（毎回作り直す）。
GIF にするには demo/make_gif.py を使う。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "migrate_files.py"
WORK = HERE / "work"
DAY = 86400

# (パス, 内容, 何日前に更新されたか)
SAMPLE = [
    ("旧PC/書類/見積書_A社.pdf",        "見積書 A社\n" * 200,  3),
    ("旧PC/書類/見積書_B社.pdf",        "見積書 B社\n" * 200, 120),
    ("旧PC/書類/議事録 10月.docx",       "議事録\n" * 100,      5),
    ("旧PC/書類/~$議事録 10月.docx",     "lock",                 1),
    ("旧PC/写真/2026/旅行_01.jpg",       "JPEG" * 5000,        40),
    ("旧PC/写真/2026/旅行_01 (1).jpg",   "JPEG" * 5000,        40),   # 同じ写真を 2 回保存した
    ("旧PC/写真/2026/旅行_02.jpg",       "JPEG" * 6000,        40),
    ("旧PC/写真/2026/Thumbs.db",         "thumbs",              40),
    ("旧PC/写真/2025/花見.jpg",          "JPEG" * 4000,       200),
    ("デスクトップ/メモ.txt",            "買い物リスト\n",       1),
    ("デスクトップ/report.xlsx",         "XLSX" * 1000,          2),
    ("ダウンロード/report.xlsx",         "XLSX(別物)" * 1000,   10),
    ("ダウンロード/請求書_10月.pdf",     "請求書\n" * 150,       7),
]

STEPS = []
QUIET = False  # True の間は何も表示しない（--only で前のステップを黙って実行するため）


def step(title: str, note: str, gif: str):
    """デモの 1 ステップ。gif は make_gif.py が出力するファイル名に使う。"""
    def deco(fn):
        STEPS.append((title, note, fn, gif))
        return fn
    return deco


# ---------------------------------------------------------------- 表示まわり

def say(text: str = "") -> None:
    if not QUIET:
        print(text, flush=True)


def tree(root: Path, label: str | None = None) -> None:
    """フォルダの中身をツリー表示する。"""
    say(f"  📁 {label or root.name}/")
    if not root.exists():
        say("     （まだありません）")
        return

    def walk(d: Path, prefix: str) -> None:
        items = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, p in enumerate(items):
            last = i == len(items) - 1
            branch = "└─ " if last else "├─ "
            if p.is_dir():
                say(f"  {prefix}{branch}{p.name}/")
                walk(p, prefix + ("   " if last else "│  "))
            else:
                say(f"  {prefix}{branch}{p.name}")
    walk(root, "   ")


def run(*args: str) -> None:
    """コマンドを表示してから実行し、出力を見やすく整えて表示する。"""
    shown = " ".join(f'"{a}"' if " " in a or "*" in a else a for a in args)
    say(f"\n  > python migrate_files.py {shown}\n")
    p = subprocess.run([sys.executable, str(SCRIPT), *args,
                        "--log", "migration.log"],
                       cwd=WORK, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in (p.stdout + p.stderr).splitlines():
        msg = line.split("] ", 1)[-1]  # 日時とレベルを省く
        if set(msg) <= {"=", "-"}:
            continue
        say(f"    {msg}")
    say(f"    （終了コード {p.returncode}）")


# ---------------------------------------------------------------- ステップ

@step("サンプルの準備",
      "古い PC から新しい PC へデータを移す、という想定のフォルダを用意しました。",
      gif="00_sample")
def s0():
    tree(WORK / "旧PC")
    tree(WORK / "デスクトップ")
    tree(WORK / "ダウンロード")


@step("① まずはドライラン",
      "--dry-run を付けると、何がどこへ行くかを表示するだけで、何も書き込みません。\n"
      "  本番の前に必ずこれで確認します。",
      gif="01_dry-run")
def s1():
    run("旧PC", "新PC", "--dry-run")
    tree(WORK / "新PC")


@step("② フォルダごとコピー（不要なファイルを除外）",
      "Office の一時ファイル（~$…）と Thumbs.db を除外してコピーします。\n"
      "  フォルダの構成はそのまま。コピー後に中身が同じか（SHA-256）を確認しています。",
      gif="02_copy")
def s2():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db")
    tree(WORK / "新PC")


@step("③ 同じコマンドをもう一度",
      "台帳に記録されているので、済んだものは飛ばします。\n"
      "  途中で止まったときも、同じコマンドで続きから再開できます。",
      gif="03_resume")
def s3():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db")


@step("④ 別々のフォルダのファイルをまとめて（同じ名前に注意）",
      "デスクトップとダウンロードの両方に report.xlsx があります。\n"
      "  既定（skip）では後のほうは飛ばされるので、実行前に警告が出ます。まずはドライランで確認。",
      gif="04_same-name")
def s4():
    run("デスクトップ/メモ.txt", "デスクトップ/report.xlsx", "ダウンロード/report.xlsx",
        "新PC/受け取り", "--dry-run")


@step("⑤ rename で両方残して移動",
      "--on-exists rename で番号を付けて両方残し、--move で移動します。\n"
      "  移動は、移行先で中身の一致を確認してから元を消します。",
      gif="05_rename-move")
def s5():
    run("デスクトップ/メモ.txt", "デスクトップ/report.xlsx", "ダウンロード/report.xlsx",
        "新PC/受け取り", "--on-exists", "rename", "--move")
    tree(WORK / "新PC" / "受け取り", "新PC/受け取り")
    tree(WORK / "デスクトップ")
    tree(WORK / "ダウンロード")


@step("⑥ ワイルドカードと絞り込み",
      "旧PC の書類から「最近 30 日以内に更新された PDF」だけを集めます。\n"
      "  ワイルドカードは \" で囲みます（Windows でも使えます）。",
      gif="06_filter")
def s6():
    run("旧PC/書類/*", "ダウンロード/*.pdf", "新PC/最近のPDF", "--ext", "pdf", "--since", "30d")
    tree(WORK / "新PC" / "最近のPDF", "新PC/最近のPDF")


@step("⑦ 指定ミスは実行前に止まる",
      "存在しないファイルが 1 つでも混ざっていると、何もせずに止まります（終了コード 2）。",
      gif="07_missing")
def s7():
    run("旧PC/書類/見積書_A社.pdf", "旧PC/書類/見積書_C社.pdf", "新PC/確認用")
    tree(WORK / "新PC" / "確認用", "新PC/確認用")


@step("⑧ コピー済みのものを --move で片付ける",
      "② でコピーした旧PC を、後から --move で片付けます。移行先に同じ中身があるものは\n"
      "  転送せずに元だけ消します。除外したファイル（~$… と Thumbs.db）は対象外なので残ります。",
      gif="08_move-cleanup")
def s8():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db", "--move")
    tree(WORK / "旧PC")


@step("⑨ (1) 付きの重複ファイルを消す",
      "--dedupe を付けると、転送の後に移行先で「旅行_01 (1).jpg」のような番号付きのファイルが\n"
      "  「旅行_01.jpg」と同じ中身なら消します。中身が違うものは消しません。まずはドライランで確認。",
      gif="09_dedupe")
def s9():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db", "--dedupe", "--dry-run")
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db", "--dedupe")
    tree(WORK / "新PC" / "写真" / "2026", "新PC/写真/2026")


# ---------------------------------------------------------------- 本体

def build_sample() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    now = time.time()
    for rel, body, days in SAMPLE:
        p = WORK / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        t = now - days * DAY
        os.utime(p, (t, t))


def main(argv: list[str] | None = None) -> int:
    global QUIET, WORK
    ap = argparse.ArgumentParser(description="FileMove のデモ")
    ap.add_argument("--auto", action="store_true", help="Enter を待たずに最後まで流す")
    ap.add_argument("--only", type=int, metavar="N",
                    help=f"N 番目のステップだけ表示する（0〜{len(STEPS) - 1}。前のステップは黙って実行）")
    ap.add_argument("--work", type=Path, default=WORK, help="作業フォルダ（毎回作り直す）")
    args = ap.parse_args(argv)
    if args.only is not None and not 0 <= args.only < len(STEPS):
        ap.error(f"--only は 0〜{len(STEPS) - 1} で指定してください")
    WORK = args.work.resolve()

    build_sample()
    if args.only is None:
        say("=" * 64)
        say("  FileMove デモ")
        say(f"  作業フォルダ: {WORK}")
        say("=" * 64)

    for i, (title, note, fn, _) in enumerate(STEPS):
        if args.only is not None and i > args.only:
            break
        QUIET = args.only is not None and i < args.only
        say(f"\n■ {title}")
        say(f"  {note}\n")
        fn()
        if not args.auto and args.only is None and i < len(STEPS) - 1:
            try:
                input("\n  -- Enter で次へ（Ctrl+C で終了） --")
            except (KeyboardInterrupt, EOFError):
                say("\n終了しました。")
                return 0
    QUIET = False

    if args.only is None:
        say("\nデモは以上です。作業フォルダの中身は自由に触って確かめてください。")
        say("使い方の詳細は docs/MANUAL.md を参照してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
