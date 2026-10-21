#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileMove の CLI のデモ。「ダウンロードにたまったファイルを、デスクトップへ移して整理する」という
場面で、使い方のパターン（P1〜P12）を順番に実行して見せる。

    python demo/cli/demo.py            # 1 パターンごとに Enter で進む
    python demo/cli/demo.py --auto     # 止まらずに最後まで流す
    python demo/cli/demo.py --only 3   # P3 だけ表示する

パターンごとにサンプル（demo/sample.py）を作り直すので、どれも単独で実行できる。
demo/work/cli/（--work で変更可）以外には何も書き込まない。
表示上のパスは Windows の形（C:\\Users\\user\\Downloads、D:\\写真）にしているが、
実際には作業フォルダの中で実行している。GIF にするには demo/cli/make_gif.py を使う。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent.parent / "migrate_files.py"
sys.path.insert(0, str(HERE.parent))   # demo/sample.py を読む

from sample import D_SHOWN, HOME_SHOWN, Sample  # noqa: E402

WORK = HERE.parent / "work" / "cli"
PROMPT = f"PS {HOME_SHOWN}>"
ENV = Sample(WORK)

STEPS = []
QUIET = False  # True の間は何も表示しない（準備のコマンドを黙って実行するため）


def step(title: str, note: str, gif: str, extra: list | None = None):
    """デモの 1 パターン。title は「何をしたいか」の 1 行、gif は make_gif.py が出力するファイル名、
    extra はこのパターンだけ追加で置くサンプル（demo/sample.py の SAMPLE と同じ形）。"""
    def deco(fn):
        STEPS.append((title, note, fn, gif, extra or []))
        return fn
    return deco


# ---------------------------------------------------------------- パスの表示

def home() -> Path:
    return ENV.home


def real(shown: str) -> Path:
    """表示上のパス（C:\\Users\\user\\… / D:\\… / ホームからの相対）を、作業フォルダ内の実際のパスにする。"""
    return ENV.real(shown)


def to_shown(text: str) -> str:
    """出力に含まれる実際のパスを、表示上のパスに戻す。"""
    return ENV.shown(text)


# ---------------------------------------------------------------- 表示まわり

def say(text: str = "") -> None:
    if not QUIET:
        print(text, flush=True)


def label(text: str) -> None:
    say(f"\n  【{text}】")


def tree(shown: str) -> None:
    """フォルダの中身をツリー表示する。"""
    root = real(shown)
    say(f"  📁 {shown}\\")
    if not root.exists():
        say("     （まだありません）")
        return
    if not any(root.iterdir()):
        say("     （空）")
        return

    def walk(d: Path, prefix: str) -> None:
        items = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, p in enumerate(items):
            last = i == len(items) - 1
            branch = "└─ " if last else "├─ "
            mark = "\\" if p.is_dir() else ""
            say(f"  {prefix}{branch}{p.name}{mark}")
            if p.is_dir():
                walk(p, prefix + ("   " if last else "│  "))
    walk(root, "   ")


def run(*args: str) -> None:
    """コマンドを表示してから実行し、出力を見やすく整えて表示する。

    パスは表示上の形（Downloads\\… や D:\\…）で渡す。
    """
    shown = " ".join(f'"{a}"' if " " in a or "*" in a else a for a in args)
    say(f"\n  {PROMPT} python migrate_files.py {shown}\n")
    # ドライブ付きのパスは作業フォルダ内の実際のパスに、それ以外はホームからの相対パスのまま渡す
    actual = [str(real(a)) if a.startswith((HOME_SHOWN, D_SHOWN)) else a.replace("\\", os.sep)
              for a in args]
    p = subprocess.run([sys.executable, str(SCRIPT), *actual,
                        "--log", str(ENV.work / "migration.log"), "--ledger", str(ENV.work / "ledger.jsonl")],
                       cwd=home(), capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in (p.stdout + p.stderr).splitlines():
        msg = line.split("] ", 1)[-1]  # 日時とレベルを省く
        if set(msg) <= {"=", "-"}:
            continue
        say(f"    {to_shown(msg)}")
    say(f"    （終了コード {p.returncode}）")


def quietly(*args: str) -> None:
    """準備のためにコマンドを実行する（表示しない）。"""
    global QUIET
    was, QUIET = QUIET, True
    try:
        run(*args)
    finally:
        QUIET = was


# ---------------------------------------------------------------- パターン

@step("P1 何が起きるか、先に確認したい",
      "--dry-run を付けると、どのファイルがどこへ行くかを表示するだけで、何も書き込みません。",
      gif="p01_dry-run")
def p1():
    run("Downloads", "Desktop\\整理", "--dry-run")
    label("実行後（何も変わっていない）")
    tree(f"{HOME_SHOWN}\\Desktop")


@step("P2 ダウンロードのファイルを、デスクトップへコピーしたい",
      "コピー後に中身が同じか（SHA-256）を確かめます。ダウンロードのファイルはそのまま残ります。",
      gif="p02_copy")
def p2():
    run("Downloads", "Desktop\\整理")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop\\整理")


@step("P3 ダウンロードのファイルを、デスクトップへ移したい",
      "--move を付けると移動になります。移行先で中身が同じと確かめてから、元のファイルを消します。",
      gif="p03_move")
def p3():
    label("実行前")
    tree(f"{HOME_SHOWN}\\Downloads")
    run("Downloads", "Desktop\\整理", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Downloads")
    tree(f"{HOME_SHOWN}\\Desktop\\整理")


@step("P4 書類と写真を、別々のフォルダに振り分けたい",
      "--ext で拡張子を指定すると、その種類だけを移せます。",
      gif="p04_sort")
def p4():
    run("Downloads", "Desktop\\書類", "--ext", "pdf,docx,xlsx,txt", "--move")
    run("Downloads", "Desktop\\写真", "--ext", "jpg", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop")


@step("P5 最近ダウンロードしたものだけ移したい",
      "--since 30d で、30 日以内に更新されたものだけが対象になります（200 日前の見積書_2025.pdf は残る）。",
      gif="p05_since")
def p5():
    run("Downloads", "Desktop\\最近", "--since", "30d", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Downloads")


@step("P6 移行先に同じ名前のファイルがある",
      "既定では上書きせずに飛ばします。--on-exists rename なら番号を付けて両方残します。",
      gif="p06_same-name",
      extra=[("Desktop/整理/メモ.txt", "前に書いたメモ\n", 30)])
def p6():
    run("Downloads", "Desktop\\整理", "--ext", "txt")
    run("Downloads", "Desktop\\整理", "--ext", "txt", "--on-exists", "rename")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop\\整理")


@step("P7 途中で止まった・もう一度実行してしまった",
      "済んだものは台帳に記録されているので飛ばします。止まったときも、同じコマンドで続きから再開できます。",
      gif="p07_resume")
def p7():
    quietly("Downloads", "Desktop\\整理")
    run("Downloads", "Desktop\\整理")


@step("P8 選んだファイルだけ移したい",
      "ファイルの指定とワイルドカード（\" で囲む）を混ぜて、いくつでも並べられます。最後が移行先です。",
      gif="p08_select")
def p8():
    run("Downloads\\見積書_A社.pdf", "Downloads\\*.xlsx", "Desktop\\整理", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop\\整理")


@step("P9 コピーしておいたダウンロードを、後から片付けたい",
      "前にコピーしたときと同じコマンドに --move を付けると、移行先に同じ中身があるものは元だけ消します。",
      gif="p09_cleanup")
def p9():
    quietly("Downloads", "Desktop\\整理")
    run("Downloads", "Desktop\\整理", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Downloads")


@step("P10 2 回ダウンロードした (1) 付きのファイルを消したい",
      "--dedupe で、IMG_0001 (1).jpg のように番号が付いていて中身も同じものを消します。中身が違うものは消しません。",
      gif="p10_dedupe")
def p10():
    run("Downloads", "Desktop\\写真", "--ext", "jpg", "--move", "--dedupe")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop\\写真")


@step("P11 パスを打ち間違えた",
      "存在しないファイルが 1 つでもあると、何もせずに止まり、どれが無いかを表示します。",
      gif="p11_missing")
def p11():
    run("Downloads\\見積書_C社.pdf", "Desktop\\整理")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Desktop")


@step("P12 C ドライブが一杯なので、写真を D ドライブへ移したい",
      "ドライブをまたいでも、同じ使い方で移せます。USB メモリや外付け HDD も同じです。",
      gif="p12_drive")
def p12():
    run(f"{HOME_SHOWN}\\Pictures\\旅行", "D:\\写真\\旅行", "--move")
    label("実行後")
    tree(f"{HOME_SHOWN}\\Pictures\\旅行")
    tree("D:\\写真\\旅行")


# ---------------------------------------------------------------- 本体

def main(argv: list[str] | None = None) -> int:
    global ENV
    ap = argparse.ArgumentParser(description="FileMove の CLI のデモ")
    ap.add_argument("--auto", action="store_true", help="Enter を待たずに最後まで流す")
    ap.add_argument("--only", type=int, metavar="N", help=f"P{{N}} だけ表示する（1〜{len(STEPS)}）")
    ap.add_argument("--work", type=Path, default=WORK, help="作業フォルダ（毎回作り直す）")
    args = ap.parse_args(argv)
    if args.only is not None and not 1 <= args.only <= len(STEPS):
        ap.error(f"--only は 1〜{len(STEPS)} で指定してください")
    ENV = Sample(args.work)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # 出力をファイルに書き出しても止まらない

    if args.only is None:
        say("=" * 64)
        say("  FileMove CLI デモ（ダウンロード → デスクトップの整理）")
        say(f"  作業フォルダ: {ENV.work}")
        say("=" * 64)

    chosen = [STEPS[args.only - 1]] if args.only else STEPS
    for i, (title, note, fn, _, extra) in enumerate(chosen):
        ENV.build(extra)
        say(f"\n■ {title}")
        say(f"  {note}")
        fn()
        if not args.auto and args.only is None and i < len(chosen) - 1:
            try:
                input("\n  -- Enter で次へ（Ctrl+C で終了） --")
            except (KeyboardInterrupt, EOFError):
                say("\n終了しました。")
                return 0

    if args.only is None:
        say("\nデモは以上です。作業フォルダの中身は自由に触って確かめてください。")
        say("使い方の詳細は docs/cli/MANUAL.md を参照してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
