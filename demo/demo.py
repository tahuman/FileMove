#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileMove のデモ。サンプルのフォルダを作り、主な使い方を順番に実行して見せる。

    python demo/demo.py          # 1 ステップごとに Enter で進む
    python demo/demo.py --auto   # 止まらずに最後まで流す

demo/work/ 以外には何も書き込まない（毎回作り直す）。
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
    ("旧PC/写真/2026/旅行_02.jpg",       "JPEG" * 6000,        40),
    ("旧PC/写真/2026/Thumbs.db",         "thumbs",              40),
    ("旧PC/写真/2025/花見.jpg",          "JPEG" * 4000,       200),
    ("デスクトップ/メモ.txt",            "買い物リスト\n",       1),
    ("デスクトップ/report.xlsx",         "XLSX" * 1000,          2),
    ("ダウンロード/report.xlsx",         "XLSX(別物)" * 1000,   10),
    ("ダウンロード/請求書_10月.pdf",     "請求書\n" * 150,       7),
]

STEPS = []


def step(title: str, note: str):
    def deco(fn):
        STEPS.append((title, note, fn))
        return fn
    return deco


# ---------------------------------------------------------------- 表示まわり

def say(text: str = "") -> None:
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
      "古い PC から新しい PC へデータを移す、という想定のフォルダを用意しました。")
def s0():
    tree(WORK / "旧PC")
    tree(WORK / "デスクトップ")
    tree(WORK / "ダウンロード")


@step("① まずはドライラン",
      "--dry-run を付けると、何がどこへ行くかを表示するだけで、何も書き込みません。\n"
      "  本番の前に必ずこれで確認します。")
def s1():
    run("旧PC", "新PC", "--dry-run")
    tree(WORK / "新PC")


@step("② フォルダごとコピー（不要なファイルを除外）",
      "Office の一時ファイル（~$…）と Thumbs.db を除外してコピーします。\n"
      "  フォルダの構成はそのまま。コピー後に中身が同じか（SHA-256）を確認しています。")
def s2():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db")
    tree(WORK / "新PC")


@step("③ 同じコマンドをもう一度",
      "台帳に記録されているので、済んだものは飛ばします。\n"
      "  途中で止まったときも、同じコマンドで続きから再開できます。")
def s3():
    run("旧PC", "新PC", "--exclude", "~$*", "--exclude", "Thumbs.db")


@step("④ 別々のフォルダのファイルをまとめて（同じ名前に注意）",
      "デスクトップとダウンロードの両方に report.xlsx があります。\n"
      "  既定（skip）では後のほうは飛ばされるので、実行前に警告が出ます。まずはドライランで確認。")
def s4():
    run("デスクトップ/メモ.txt", "デスクトップ/report.xlsx", "ダウンロード/report.xlsx",
        "新PC/受け取り", "--dry-run")


@step("⑤ rename で両方残して移動",
      "--on-exists rename で番号を付けて両方残し、--move で移動します。\n"
      "  移動は、移行先で中身の一致を確認してから元を消します。")
def s5():
    run("デスクトップ/メモ.txt", "デスクトップ/report.xlsx", "ダウンロード/report.xlsx",
        "新PC/受け取り", "--on-exists", "rename", "--move")
    tree(WORK / "新PC" / "受け取り", "新PC/受け取り")
    tree(WORK / "デスクトップ")
    tree(WORK / "ダウンロード")


@step("⑥ ワイルドカードと絞り込み",
      "旧PC の書類から「最近 30 日以内に更新された PDF」だけを集めます。\n"
      "  ワイルドカードは \" で囲みます（Windows でも使えます）。")
def s6():
    run("旧PC/書類/*", "ダウンロード/*.pdf", "新PC/最近のPDF", "--ext", "pdf", "--since", "30d")
    tree(WORK / "新PC" / "最近のPDF", "新PC/最近のPDF")


@step("⑦ 指定ミスは実行前に止まる",
      "存在しないファイルが 1 つでも混ざっていると、何もせずに止まります（終了コード 2）。")
def s7():
    run("旧PC/書類/見積書_A社.pdf", "旧PC/書類/見積書_C社.pdf", "新PC/確認用")
    tree(WORK / "新PC" / "確認用", "新PC/確認用")


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


def main() -> int:
    ap = argparse.ArgumentParser(description="FileMove のデモ")
    ap.add_argument("--auto", action="store_true", help="Enter を待たずに最後まで流す")
    args = ap.parse_args()

    build_sample()
    say("=" * 64)
    say("  FileMove デモ")
    say(f"  作業フォルダ: {WORK}")
    say("=" * 64)

    for i, (title, note, fn) in enumerate(STEPS):
        say(f"\n■ {title}")
        say(f"  {note}\n")
        fn()
        if not args.auto and i < len(STEPS) - 1:
            try:
                input("\n  -- Enter で次へ（Ctrl+C で終了） --")
            except (KeyboardInterrupt, EOFError):
                say("\n終了しました。")
                return 0

    say("\nデモは以上です。作業フォルダの中身は自由に触って確かめてください。")
    say("使い方の詳細は docs/MANUAL.md を参照してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
