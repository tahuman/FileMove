#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_files.py の動作確認用テストデータを生成する。

更新日時(mtime)は git では保持されないため、データはコミットせず毎回このスクリプトで作る。
何度実行しても同じ内容になる（mtime は実行時刻からの相対値）。

使用例:
    python testdata/make_testdata.py            # testdata/work/ に生成（既存は作り直し）
    python testdata/make_testdata.py --out D:/tmp/fm

生成物:
    work/src/           移行元
    work/dst/           移行先（衝突確認用のファイルを事前に配置済み）
    work/ledger_partial.jsonl   再開確認用の台帳（壊れた行を含む）

シナリオと期待結果は testdata/SCENARIOS.md を参照。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

DAY = 86400

# (相対パス, サイズ or 内容, 何日前に更新されたか)
#   サイズ(int) の場合は決まったパターンのバイト列で埋める
SRC_FILES: list[tuple[str, int | str, float]] = [
    # --- 拡張子フィルタ（大文字小文字の混在）
    ("docs/report_2025.pdf",               10 * 1024,   400),
    ("docs/report_2026.PDF",               20 * 1024,     5),
    ("docs/meeting notes.txt",             "スペースを含むファイル名\n", 10),
    ("docs/議事録_2026年10月.docx",          5 * 1024,      2),
    ("data/sales.xlsx",                    50 * 1024,    40),
    ("data/sales.csv",                     "id,amount\n1,100\n2,200\n", 40),
    ("images/photo1.jpg",                  200 * 1024,   90),
    ("images/photo2.JPG",                  300 * 1024,    1),
    # --- サイズフィルタ／分割ハッシュ（CHUNK_SIZE=1MB を跨ぐ）
    ("data/big/large_3MB.bin",             3 * 1024 * 1024, 1),
    ("data/big/exact_1MB.bin",             1024 * 1024,  1),
    ("empty_file.txt",                     0,            3),
    # --- 深い階層・特殊な名前
    ("data/nested/a/b/c/deep.txt",         "深い階層\n", 20),
    ("no_extension",                       "拡張子なし\n", 15),
    (".hidden_config",                     "key=value\n", 15),
    ("日本語フォルダ/サブ フォルダ/メモ.txt",   "日本語パス\n", 7),
    ("archive.tar.gz",                     8 * 1024,     60),
    # --- 除外パターン確認用
    ("cache/build.tmp",                    1024,          1),
    ("data/~$sales.xlsx",                  165,           1),   # Office のロックファイル
    ("images/Thumbs.db",                   4 * 1024,     30),
    ("node_modules/pkg/index.js",          "module.exports = 1;\n", 100),
    (".git/HEAD",                          "ref: refs/heads/main\n", 100),
    # --- 移行先との衝突確認用（dst 側にも同名あり）
    ("conflict/same.txt",                  "NEW (src)\n", 1),
    ("conflict/renamed.txt",               "NEW (src)\n", 1),
    ("conflict/only_in_src.txt",           "src only\n", 1),
]

# 移行先に事前に置いておくファイル
DST_FILES: list[tuple[str, str]] = [
    ("conflict/same.txt",      "OLD (dst)\n"),
    ("conflict/renamed.txt",   "OLD (dst)\n"),
    ("conflict/renamed_1.txt", "OLD (dst) _1\n"),  # rename 時は _2 が付くはず
]

# 空ディレクトリ（ファイル単位の移行なので移行先には作られない想定）
EMPTY_DIRS = ["empty_dir", "data/nested/empty_child"]


def pattern_bytes(rel: str, size: int) -> bytes:
    """パスごとに異なる、再現可能なバイト列を作る。"""
    seed = rel.encode("utf-8") + b"|"
    block = (seed * (4096 // len(seed) + 1))[:4096]
    return (block * (size // len(block) + 1))[:size]


def write_file(base: Path, rel: str, body: int | str, days_ago: float | None, now: float) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, int):
        path.write_bytes(pattern_bytes(rel, body))
    else:
        path.write_bytes(body.encode("utf-8"))
    if days_ago is not None:
        t = now - days_ago * DAY
        os.utime(path, (t, t))


def root_id(path: Path) -> str:
    """migrate_files._root_id と同じ規則で移行元／移行先を表す。"""
    return os.path.normcase(str(path.resolve()))


def write_ledger(path: Path, src: Path, dst: Path) -> None:
    """一部処理済み＋失敗＋壊れた行、および別の移行・旧形式の記録を含む台帳。"""
    scope = {"src_root": root_id(src), "dst_root": root_id(dst)}

    def rec(**kw) -> str:
        return json.dumps(kw, ensure_ascii=False)

    lines = [
        # この src→dst の記録
        rec(path="docs/report_2025.pdf", status="done", ts="2026-10-01T10:00:00", **scope),
        rec(path="data/sales.csv", status="done", ts="2026-10-01T10:00:01", **scope),
        rec(path="data/sales.xlsx", status="failed", error="テスト用の失敗記録",
            ts="2026-10-01T10:00:02", **scope),
        rec(path="images/photo1.jpg", status="skipped", reason="exists",
            ts="2026-10-01T10:00:03", **scope),
        # 別の移行の記録（同じ相対パスでも処理済み扱いにならないこと）
        rec(path="empty_file.txt", status="done", ts="2026-09-01T09:00:00",
            src_root=root_id(path.parent / "other_src"), dst_root=scope["dst_root"]),
        rec(path="no_extension", status="done", ts="2026-09-01T09:00:01",
            src_root=scope["src_root"], dst_root=root_id(path.parent / "other_dst")),
        # 旧形式（ルートなし）の記録も参照されないこと
        rec(path="archive.tar.gz", status="done", ts="2026-08-01T08:00:00"),
        "",                                     # 空行
        "{this is not json",                    # JSON として壊れている
        json.dumps({"status": "done"}),         # path キーなし
        json.dumps(["path", "done"]),           # dict ではない
        '{"path": "docs/meeting notes.txt", "status": "do',  # 書き込み途中で落ちた行
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="migrate_files.py 用テストデータ生成")
    ap.add_argument("--out", type=Path, default=here / "work", help="出力先（既定: testdata/work）")
    args = ap.parse_args()

    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)
    src, dst = out / "src", out / "dst"
    now = time.time()

    for rel, body, days in SRC_FILES:
        write_file(src, rel, body, days, now)
    for d in EMPTY_DIRS:
        (src / d).mkdir(parents=True, exist_ok=True)
    for rel, body in DST_FILES:
        write_file(dst, rel, body, None, now)
    write_ledger(out / "ledger_partial.jsonl", src, dst)

    total = sum((src / r).stat().st_size for r, _, _ in SRC_FILES)
    print(f"生成しました: {out}")
    print(f"  src: {len(SRC_FILES)} ファイル / {total:,} bytes / 空ディレクトリ {len(EMPTY_DIRS)}")
    print(f"  dst: {len(DST_FILES)} ファイル（衝突確認用）")
    print(f"  ledger_partial.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
