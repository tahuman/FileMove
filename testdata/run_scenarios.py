#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCENARIOS.md のシナリオを CLI 経由で実行し、期待結果と照合する。

    python testdata/run_scenarios.py          # 全件
    python testdata/run_scenarios.py M1 S13   # 指定したものだけ

各シナリオの前に make_testdata.py でデータを作り直す（reset=False のものを除く）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = ROOT / "migrate_files.py"
W = HERE / "work"
SRC, DST, OUT = W / "src", W / "dst", W / "out"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


@dataclass
class Scenario:
    sid: str
    title: str
    args: list
    exit: int = 0
    counts: tuple | None = None          # (成功, スキップ, 失敗)
    check: Callable[[str], object] | None = None   # 出力を受け取り、問題があれば AssertionError
    reset: bool = True
    std_ledger: bool = True              # --log / --ledger を work/ 配下に向ける
    cwd: Path | None = None
    windows_only: bool = False


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def files(base: Path) -> set[str]:
    return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


S = lambda *parts: str(SRC.joinpath(*parts))  # noqa: E731

SCENARIOS: list[Scenario] = [
    # ---------------------------------------------------------------- ディレクトリ指定
    Scenario("1", "ドライラン", [S(), DST, "--dry-run"], counts=(22, 2, 0),
             check=lambda o: expect(len(files(DST)) == 3, "dst が変化した")),
    Scenario("2", "--ext pdf,jpg", [S(), DST, "--dry-run", "--ext", "pdf,jpg"], counts=(4, 0, 0)),
    Scenario("3", "--since 30d", [S(), DST, "--dry-run", "--since", "30d"], counts=(14, 2, 0)),
    Scenario("4", "サイズ境界", [S(), DST, "--dry-run", "--min-size", "1KB", "--max-size", "1MB"],
             counts=(10, 0, 0)),
    Scenario("5", "除外 glob", [S(), DST, "--dry-run", "--exclude", "*.tmp", "--exclude", "~$*",
                               "--exclude", "Thumbs.db", "--exclude", "node_modules",
                               "--exclude", ".git"], counts=(17, 2, 0)),
    Scenario("6", "--since 書式エラー", [S(), DST, "--since", "2026-13-01"], exit=2,
             check=lambda o: expect("書式が不正" in o, "エラー文なし")),
    Scenario("7", "コピー（skip）", [S(), DST], counts=(22, 2, 0),
             check=lambda o: (expect(read(DST / "conflict/same.txt") == "OLD (dst)\n", "上書きされた"),
                              expect(not (DST / "empty_dir").exists(), "空ディレクトリが作られた"))),
    Scenario("8", "再実行で台帳スキップ", [S(), DST], counts=(0, 24, 0), reset=False,
             check=lambda o: expect("台帳で処理済みとしてスキップ 22 件" in o, "台帳スキップ件数の表示なし")),
    Scenario("9", "rename", [S(), DST, "--on-exists", "rename"], counts=(24, 0, 0),
             check=lambda o: (expect(read(DST / "conflict/renamed_2.txt") == "NEW (src)\n", "_2 なし"),
                              expect((DST / "conflict/same_1.txt").exists(), "same_1 なし"))),
    Scenario("10", "overwrite", [S(), DST, "--on-exists", "overwrite"], counts=(24, 0, 0),
             check=lambda o: expect(read(DST / "conflict/same.txt") == "NEW (src)\n", "上書きされない")),
    Scenario("11", "台帳から再開", [S(), DST, "--log", W / "m.log", "--ledger", W / "ledger_partial.jsonl"],
             std_ledger=False, counts=(22, 2, 0),
             check=lambda o: (expect(o.count("移行先に見当たらないため転送し直します") == 2,
                                     "done だが移行先に無いものが転送し直されない"),
                              expect(all((DST / p).exists() for p in
                                         ["docs/report_2025.pdf", "data/sales.csv",
                                          "data/sales.xlsx", "images/photo1.jpg", "empty_file.txt",
                                          "no_extension", "archive.tar.gz"]), "再処理されないものがある"))),
    Scenario("11b", "同じ台帳で再実行", [S(), DST, "--log", W / "m.log", "--ledger", W / "ledger_partial.jsonl"],
             std_ledger=False, reset=False, counts=(0, 24, 0),
             check=lambda o: expect("台帳で処理済みとしてスキップ 22 件" in o, "台帳スキップ件数の表示なし")),
    Scenario("12", "--restart", [S(), DST, "--restart", "--log", W / "m.log",
                                 "--ledger", W / "ledger_partial.jsonl"], std_ledger=False, counts=(22, 2, 0)),
    Scenario("13", "--move", [S(), DST, "--move"], counts=(22, 2, 0),
             check=lambda o: expect(files(SRC) == {"conflict/same.txt", "conflict/renamed.txt"},
                                    f"src の残り: {files(SRC)}")),
    Scenario("14", "移行先が移行元の配下", [S(), S("_migrated")], counts=(24, 0, 0)),
    Scenario("14b", "同（別台帳で再実行）", [S(), S("_migrated"), "--log", W / "m.log",
                                       "--ledger", W / "l2.jsonl"], std_ledger=False, reset=False,
             counts=(0, 24, 0)),
    Scenario("15", "更新日時の保持", [S(), DST], counts=(22, 2, 0),
             check=lambda o: expect(int(os.stat(S("docs/report_2025.pdf")).st_mtime)
                                    == int(os.stat(DST / "docs/report_2025.pdf").st_mtime), "mtime 不一致")),
    Scenario("16", "移行元と移行先が同じ", [S(), S()], exit=2),
    Scenario("17", "存在しない移行元", [S("nope"), DST], exit=2),
    Scenario("18", "既定台帳で別の移行（A→outA）", ["A", "outA"], counts=(1, 0, 0),
             std_ledger=False, cwd=W / "ab"),
    Scenario("18b", "既定台帳で別の移行（B→outB）", ["B", "outB"], counts=(1, 0, 0),
             std_ledger=False, cwd=W / "ab", reset=False,
             check=lambda o: expect(read(W / "ab/outB/report.txt") == "b\n", "B がコピーされない")),
    Scenario("19", "大文字小文字違いは同じ移行", ["a", "OUTA"], counts=(0, 1, 0),
             std_ledger=False, cwd=W / "ab", reset=False, windows_only=True),
    Scenario("20", "コピー（後で --move する前提）", [S(), DST], counts=(22, 2, 0)),
    Scenario("20b", "コピー済みを --move で片付け", [S(), DST, "--move"], counts=(0, 24, 0), reset=False,
             check=lambda o: (expect("移行元を削除 22 件" in o, "削除件数の表示なし"),
                              expect(files(SRC) == {"conflict/same.txt", "conflict/renamed.txt"},
                                     f"src の残り: {files(SRC)}"))),
    Scenario("21", "コピー（台帳なしで --move する前提）", [S(), DST], counts=(22, 2, 0)),
    Scenario("21b", "台帳なしでも同じ内容なら --move で片付け", [S(), DST, "--move", "--restart"],
             counts=(0, 24, 0), reset=False,
             check=lambda o: expect(files(SRC) == {"conflict/same.txt", "conflict/renamed.txt"},
                                    f"src の残り: {files(SRC)}")),

    # ---------------------------------------------------------------- 重複ファイルの削除
    Scenario("D1", "--dedupe", [W / "dup/in", W / "dup/out", "--dedupe"], counts=(1, 0, 0),
             check=lambda o: (expect("重複ファイルの削除: 1 件" in o, "削除件数の表示なし"),
                              expect(files(W / "dup/out") == {"new.txt", "report.txt", "report (2).txt",
                                                              "memo (1).txt", "私物/写真.jpg", "私物/写真 (1).jpg"},
                                     f"out: {files(W / 'dup/out')}"))),
    Scenario("D2", "--dedupe のドライラン", [W / "dup/in", W / "dup/out", "--dedupe", "--dry-run"],
             counts=(1, 0, 0),
             check=lambda o: (expect("DRY-RUN 重複を削除: report (1).txt" in o, "削除予定の表示なし"),
                              expect((W / "dup/out/report (1).txt").exists(), "ドライランで消えた"))),
    Scenario("D3", "これからコピーするものもドライランで判定", [W / "dup/in2", W / "dup/new", "--dedupe", "--dry-run"],
             counts=(2, 0, 0),
             check=lambda o: (expect("DRY-RUN 重複を削除: a (1).txt" in o, "削除予定の表示なし"),
                              expect(not (W / "dup/new").exists(), "ドライランで書き込まれた"))),
    Scenario("D3b", "同（実行）", [W / "dup/in2", W / "dup/new", "--dedupe"], counts=(2, 0, 0), reset=False,
             check=lambda o: expect(files(W / "dup/new") == {"a.txt"}, f"new: {files(W / 'dup/new')}")),

    # ---------------------------------------------------------------- 単一ファイル
    Scenario("S1", "単一ファイルのコピー", [S("docs/議事録_2026年10月.docx"), OUT], counts=(1, 0, 0),
             check=lambda o: (expect(files(OUT) == {"議事録_2026年10月.docx"}, f"out: {files(OUT)}"),
                              expect(Path(S("docs/議事録_2026年10月.docx")).exists(), "移行元が消えた"))),
    Scenario("S2", "単一ファイルの再実行", [S("docs/議事録_2026年10月.docx"), OUT], counts=(0, 1, 0),
             reset=False),
    Scenario("S3", "同じフォルダの別ファイル", [S("docs/report_2026.PDF"), OUT], counts=(1, 0, 0),
             reset=False),
    Scenario("S4", "単一ファイルのドライラン", [S("docs/議事録_2026年10月.docx"), OUT, "--dry-run"],
             counts=(1, 0, 0), check=lambda o: expect(not OUT.exists(), "out が作られた")),
    Scenario("S5", "--ext で除外", [S("docs/議事録_2026年10月.docx"), OUT, "--ext", "pdf"], counts=(0, 0, 0)),
    Scenario("S6", "--exclude で除外", [S("cache/build.tmp"), OUT, "--exclude", "*.tmp"], counts=(0, 0, 0)),
    Scenario("S7", "--since で除外", [S("docs/report_2025.pdf"), OUT, "--since", "30d"], counts=(0, 0, 0)),
    Scenario("S8", "衝突 skip", [S("conflict/same.txt"), DST / "conflict"], counts=(0, 1, 0)),
    Scenario("S9", "衝突 rename", [S("conflict/renamed.txt"), DST / "conflict", "--on-exists", "rename"],
             counts=(1, 0, 0), check=lambda o: expect((DST / "conflict/renamed_2.txt").exists(), "_2 なし")),
    Scenario("S10", "衝突 overwrite", [S("conflict/same.txt"), DST / "conflict", "--on-exists", "overwrite"],
             counts=(1, 0, 0),
             check=lambda o: expect(read(DST / "conflict/same.txt") == "NEW (src)\n", "上書きされない")),
    Scenario("S11", "単一ファイルの --move", [S("data/big/large_3MB.bin"), OUT, "--move"], counts=(1, 0, 0),
             check=lambda o: (expect(not Path(S("data/big/large_3MB.bin")).exists(), "移行元が残った"),
                              expect((OUT / "large_3MB.bin").stat().st_size == 3 * 1024 * 1024, "サイズ不一致"))),
    Scenario("S12", "空ファイル", [S("empty_file.txt"), OUT], counts=(1, 0, 0)),
    Scenario("S13", "同じフォルダへ move+overwrite", [S("no_extension"), S(), "--move", "--on-exists",
                                                    "overwrite"], exit=2,
             check=lambda o: expect(read(Path(S("no_extension"))) == "拡張子なし\n", "ファイルが壊れた")),
    Scenario("S14", "移行先が既存ファイル", [S("no_extension"), S(".hidden_config")], exit=2),
    Scenario("S15", "存在しないファイル", [S("nope.txt"), OUT], exit=2),
    Scenario("S16", "相対パス指定", ["meeting notes.txt", "../../out"], counts=(1, 0, 0), cwd=SRC / "docs",
             check=lambda o: expect((OUT / "meeting notes.txt").exists(), "コピーされない")),

    # ---------------------------------------------------------------- 複数指定
    Scenario("M1", "別フォルダの 2 ファイル", [S("docs/report_2026.PDF"), S("data/sales.csv"), OUT],
             counts=(2, 0, 0), check=lambda o: expect(files(OUT) == {"report_2026.PDF", "sales.csv"},
                                                      f"out: {files(OUT)}")),
    Scenario("M2", "M1 の再実行", [S("docs/report_2026.PDF"), S("data/sales.csv"), OUT],
             counts=(0, 2, 0), reset=False),
    Scenario("M3", "ワイルドカード", [S("docs/report_*"), OUT], counts=(2, 0, 0),
             check=lambda o: expect(files(OUT) == {"report_2025.pdf", "report_2026.PDF"}, f"out: {files(OUT)}")),
    Scenario("M4", "ディレクトリとファイルの混在", [S("docs"), S("data/sales.csv"), OUT], counts=(5, 0, 0),
             check=lambda o: expect("sales.csv" in files(OUT) and "meeting notes.txt" in files(OUT),
                                    f"out: {files(OUT)}")),
    Scenario("M5", "重複指定は 1 回だけ", [S("docs"), S("docs/meeting notes.txt"), S("docs"), OUT],
             counts=(4, 0, 0)),
    Scenario("M6", "同名ファイル（skip）", [S("conflict/same.txt"), str(DST / "conflict/same.txt"), OUT],
             counts=(1, 1, 0),
             check=lambda o: (expect("同じ名前になるファイルが 1 組" in o, "警告なし"),
                              expect(read(OUT / "same.txt") == "NEW (src)\n", "先に指定した方が残らない"))),
    Scenario("M7", "同名ファイル（rename）", [S("conflict/same.txt"), str(DST / "conflict/same.txt"), OUT,
                                         "--on-exists", "rename"], counts=(2, 0, 0),
             check=lambda o: expect(read(OUT / "same_1.txt") == "OLD (dst)\n", "same_1 なし")),
    Scenario("M6d", "同名ファイルのドライランも実行と同じ判定", [S("conflict/same.txt"),
             str(DST / "conflict/same.txt"), OUT, "--dry-run"], counts=(1, 1, 0)),
    Scenario("M7d", "同名ファイル rename のドライラン", [S("conflict/same.txt"), str(DST / "conflict/same.txt"),
             OUT, "--dry-run", "--on-exists", "rename"], counts=(2, 0, 0),
             check=lambda o: expect("same_1.txt" in o, "ドライランで same_1 が表示されない")),
    Scenario("M8","1 つでも存在しなければ何もしない", [S("data/sales.csv"), S("nope.txt"), OUT], exit=2,
             check=lambda o: (expect("nope.txt" in o, "どれが無いか表示されない"),
                              expect(not OUT.exists(), "途中まで実行された"))),
    Scenario("M9", "ワイルドカードが 0 件", [S("docs/*.zzz"), OUT], exit=2,
             check=lambda o: expect("一致するものがありません" in o, "エラー文なし")),
    Scenario("M10", "複数の --move", [S("docs/report_2026.PDF"), S("data/sales.csv"), OUT, "--move"],
             counts=(2, 0, 0),
             check=lambda o: expect(not Path(S("docs/report_2026.PDF")).exists()
                                    and not Path(S("data/sales.csv")).exists(), "移行元が残った")),
    Scenario("M11", "複数のドライラン", [S("docs"), S("data/sales.csv"), OUT, "--dry-run"], counts=(5, 0, 0),
             check=lambda o: expect(not OUT.exists(), "out が作られた")),
    Scenario("M12", "複数 + 絞り込み", [S("docs/report_2026.PDF"), S("data/sales.csv"), OUT, "--ext", "pdf"],
             counts=(1, 0, 0)),
    Scenario("M13", "引数が 1 つだけ", [S()], exit=2),
    Scenario("M14", "複数のうち 1 つが移行先と同じフォルダ", [S("data/sales.csv"), S("docs/report_2026.PDF"),
                                                  S("docs")], exit=2),
]


def reset() -> None:
    subprocess.run([sys.executable, HERE / "make_testdata.py"], check=True, capture_output=True, env=ENV)
    ab = W / "ab"
    for name, body in (("A", "a\n"), ("B", "b\n")):
        (ab / name).mkdir(parents=True, exist_ok=True)
        (ab / name / "report.txt").write_text(body, encoding="utf-8")
    # --dedupe 用: out/ 直下は report (1).txt だけが重複（(2) は中身違い、memo (1) は元が無い）。
    # out/私物/ は今回の移行と関係ないので、重複でも消さない。in2/ は同じ中身の 2 ファイル
    for rel, body in (("in/new.txt", "new\n"), ("out/report.txt", "same\n"),
                      ("out/report (1).txt", "same\n"), ("out/report (2).txt", "different\n"),
                      ("out/memo (1).txt", "orphan\n"), ("out/私物/写真.jpg", "jpg\n"),
                      ("out/私物/写真 (1).jpg", "jpg\n"), ("in2/a.txt", "same\n"), ("in2/a (1).txt", "same\n")):
        (W / "dup" / rel).parent.mkdir(parents=True, exist_ok=True)
        (W / "dup" / rel).write_text(body, encoding="utf-8")


def run(sc: Scenario) -> tuple[bool, str]:
    if sc.reset:
        reset()
    args = [str(a) for a in sc.args]
    if sc.std_ledger:
        args += ["--log", str(W / "m.log"), "--ledger", str(W / "l.jsonl")]
    p = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=sc.cwd or ROOT,
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    out = p.stdout + p.stderr
    try:
        expect(p.returncode == sc.exit, f"exit {p.returncode}（期待 {sc.exit}）")
        if sc.counts is not None:
            m = re.search(r"完了: 成功 (\d+) / スキップ (\d+) / 失敗 (\d+)", out)
            expect(m is not None, "完了行がない")
            got = tuple(int(x) for x in m.groups())
            expect(got == sc.counts, f"成功/スキップ/失敗 = {got}（期待 {sc.counts}）")
        if sc.check:
            sc.check(out)
    except AssertionError as e:
        return False, str(e)
    return True, ""


def main(argv: list[str]) -> int:
    wanted = set(argv)
    failed = 0
    for sc in SCENARIOS:
        if wanted and sc.sid not in wanted:
            continue
        if sc.windows_only and os.name != "nt":
            print(f"SKIP  {sc.sid:>4}  {sc.title}（Windows のみ）")
            continue
        ok, why = run(sc)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {sc.sid:>4}  {sc.title}" + ("" if ok else f"  → {why}"))
    reset()
    print(f"\n{'全件成功' if not failed else f'{failed} 件失敗'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
