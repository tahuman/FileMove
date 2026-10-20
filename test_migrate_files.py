# -*- coding: utf-8 -*-
"""
migrate_files.py のテスト（pytest）

実行:
    python -m pytest                    # 全件（単体テスト＋シナリオ）
    python -m pytest -m "not scenario"  # 単体テストだけ（1 秒かからない）
    python -m pytest -k M1              # 名前で絞り込み

テスト網羅:
  値のパース
    - [P1] parse_size: 単位なし・K/M/G・小数・"B" 付き・大文字小文字・単位前の空白、空なら None
    - [P2] parse_size: 数値でないもの・単位なしの小数・未対応の単位（T）は ValueError（CLI では exit 2）
    - [P3] parse_since: 30d / 12h / 0d は now からの相対、YYYY-MM-DD は日付、空なら None
    - [P4] parse_since: 書式が不正（存在しない日付・単位違い・負数）なら ValueError
  transfer_file（1 ファイルの転送）
    - [T1] 正常にコピーでき、返り値の SHA-256 が移行元と一致し、.part が残らない
    - [T2] verify=False のときはハッシュを計算せず空文字を返す
    - [T3] move=True のときは転送後に移行元が消える
    - [T4] ハッシュ不一致なら IOError。移行先・.part は残らず、move でも移行元は消えない
    - [T5] コピー途中の失敗でも .part が残らず、移行元も消えず、例外はそのまま伝わる
    - [T6] Ctrl+C 相当（KeyboardInterrupt）でも .part が残らない
    - [T7] 失敗しても、移行先にあった既存ファイルは壊さない
  run_migration（全体の流れ）
    - [R1] should_cancel が True を返した時点で中断し、cancelled が立ち、残りは転送されない
    - [R2] 最初から中止なら 1 件も転送しない
    - [R3] 1 件の転送失敗で全体は止まらず、failures に記録され、台帳は failed になる
    - [R4] failed は次回の実行で再試行され、done は台帳で処理済みとしてスキップされる
  進捗通知（ProgressEvent。GUI の進捗バーが依存する）
    - [E1] 最初に scanned（total 付き）、続いて 1 件ごとに done が index 1..total の順で届く
    - [E2] 既存ファイルのスキップ・台帳での済・失敗・ドライランがそれぞれの status で届き、
           failed には error が入る
    - [E3] 中止したら、それ以降の通知は届かない
  シナリオ（CLI 経由。testdata/SCENARIOS.md の表を testdata/run_scenarios.py で実行）
    - [S] 全シナリオ。前のシナリオの結果を使うもの（reset=False）は、前提から続けて実行する
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

import migrate_files as mf

ROOT = Path(__file__).resolve().parent


# ================================================================ 共通

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _part(dest: Path) -> Path:
    return dest.with_name(dest.name + ".part")


def _names(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


@pytest.fixture
def src_file(tmp_path: Path) -> Path:
    p = tmp_path / "src" / "a.txt"
    p.parent.mkdir()
    p.write_bytes(b"hello world")
    return p


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "dst" / "a.txt"


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    """移行元に 3 ファイル（a, b, c）、移行先は空。"""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (src / name).write_text(name, encoding="utf-8")
    return src, dst


@pytest.fixture
def fail_on(monkeypatch):
    """fail_on("b.txt") で、そのファイルだけ転送に失敗させる。"""
    real = mf.transfer_file

    def install(name: str) -> None:
        def fake(src_file, dest, **kw):
            if src_file.name == name:
                raise OSError("読み取りエラー")
            return real(src_file, dest, **kw)
        monkeypatch.setattr(mf, "transfer_file", fake)

    install.undo = monkeypatch.undo
    return install


def _cancel_after(n: int):
    """n 回目の問い合わせから True を返す should_cancel。"""
    calls = 0

    def should_cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > n
    return should_cancel


# ================================================================ 値のパース

@pytest.mark.parametrize("value, expected", [
    (None, None),
    ("", None),
    ("1234", 1234),
    ("0", 0),
    ("500K", 500 * 1024),
    ("1KB", 1024),
    ("1kb", 1024),
    ("10MB", 10 * 1024 ** 2),
    ("1.5GB", int(1.5 * 1024 ** 3)),
    (" 2M ", 2 * 1024 ** 2),
    ("10 MB", 10 * 1024 ** 2),       # 数字と単位の間の空白は許す
])
def test_P1_parse_size(value, expected):
    assert mf.parse_size(value) == expected


@pytest.mark.parametrize("value", ["abc", "1.5", "MB", "1TB"])
def test_P2_parse_size_invalid(value):
    with pytest.raises(ValueError):
        mf.parse_size(value)


NOW = 1_800_000_000.0


@pytest.mark.parametrize("value, expected", [
    (None, None),
    ("", None),
    ("30d", NOW - 30 * 86400),
    ("12h", NOW - 12 * 3600),
    ("0d", NOW),
    (" 7D ", NOW - 7 * 86400),
    ("2025-04-01", datetime(2025, 4, 1).timestamp()),
])
def test_P3_parse_since(value, expected):
    assert mf.parse_since(value, now=NOW) == expected


@pytest.mark.parametrize("value", ["2026-13-01", "2026/04/01", "30m", "-1d", "d", "yesterday"])
def test_P4_parse_since_invalid(value):
    with pytest.raises(ValueError, match="書式が不正"):
        mf.parse_since(value, now=NOW)


# ================================================================ transfer_file

def _corrupt_copy(src: Path, tmp: Path) -> None:
    """中身が化けるコピー（転送先の破損、コピー中の更新を想定）。"""
    tmp.write_bytes(b"corrupted")


def _failing_copy(exc: BaseException):
    """途中まで書いたところで exc を投げるコピー。"""
    def copy(src: Path, tmp: Path) -> None:
        tmp.write_bytes(b"hel")
        raise exc
    return copy


def test_T1_copy_ok(src_file, dest):
    digest = mf.transfer_file(src_file, dest)

    assert dest.read_bytes() == b"hello world"
    assert digest == _sha(b"hello world")
    assert src_file.exists()
    assert not _part(dest).exists()


def test_T2_verify_off_returns_empty(src_file, dest):
    assert mf.transfer_file(src_file, dest, verify=False) == ""
    assert dest.read_bytes() == b"hello world"


def test_T3_move_removes_source(src_file, dest):
    mf.transfer_file(src_file, dest, move=True)

    assert dest.read_bytes() == b"hello world"
    assert not src_file.exists()


@pytest.mark.parametrize("move", [False, True])
def test_T4_hash_mismatch(src_file, dest, move):
    with pytest.raises(IOError, match="ハッシュが一致しません"):
        mf.transfer_file(src_file, dest, move=move, copy_fn=_corrupt_copy)

    assert not dest.exists()
    assert not _part(dest).exists()
    assert src_file.read_bytes() == b"hello world"  # move でも移行元は消さない


@pytest.mark.parametrize("exc", [OSError("ディスクがいっぱい"), KeyboardInterrupt()],
                         ids=["T5_oserror", "T6_interrupt"])
def test_T5_T6_failure_mid_copy(src_file, dest, exc):
    with pytest.raises(type(exc)):
        mf.transfer_file(src_file, dest, move=True, copy_fn=_failing_copy(exc))

    assert not dest.exists()
    assert not _part(dest).exists()
    assert src_file.exists()


def test_T7_failure_keeps_existing_dest(src_file, dest):
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"existing")

    with pytest.raises(IOError):
        mf.transfer_file(src_file, dest, copy_fn=_corrupt_copy)

    assert dest.read_bytes() == b"existing"


# ================================================================ run_migration

def test_R1_cancel_midway(tree):
    src, dst = tree

    result = mf.run_migration(src, dst, should_cancel=_cancel_after(1))

    assert result.cancelled
    assert not result.ok
    assert result.copied == 1
    assert _names(dst) == ["a.txt"]


def test_R2_cancel_before_start(tree):
    src, dst = tree

    result = mf.run_migration(src, dst, should_cancel=lambda: True)

    assert result.cancelled
    assert result.copied == 0
    assert _names(dst) == []


def test_R3_one_failure_does_not_stop(tree, fail_on):
    src, dst = tree
    fail_on("b.txt")
    ledger = mf.Ledger(None)

    result = mf.run_migration(src, dst, ledger=ledger)

    assert (result.copied, result.failed) == (2, 1)
    assert result.failures == [("b.txt", "読み取りエラー")]
    assert _names(dst) == ["a.txt", "c.txt"]
    ledger.bind(src, dst)
    assert ledger.records[ledger._key("b.txt")]["status"] == "failed"


def test_R4_retry_failed_with_ledger(tree, tmp_path, fail_on):
    src, dst = tree
    ledger_path = tmp_path / "ledger.jsonl"

    fail_on("b.txt")
    first = mf.Ledger(ledger_path)
    mf.run_migration(src, dst, ledger=first)
    first.close()
    fail_on.undo()

    second = mf.Ledger(ledger_path)
    result = mf.run_migration(src, dst, ledger=second)
    second.close()

    assert result.copied == 1          # b だけ再試行
    assert result.already_done == 2    # a, c は台帳で済
    assert result.ok
    assert (dst / "b.txt").read_text(encoding="utf-8") == "b.txt"


# ================================================================ 進捗通知

def _collect(src, dst, **kw) -> list[tuple]:
    """run_migration の進捗通知を (status, index, total, rel) の列にする。"""
    events: list[mf.ProgressEvent] = []
    mf.run_migration(src, dst, progress=events.append, **kw)
    return [(e.status, e.index, e.total, e.rel) for e in events], events


def test_E1_progress_order(tree):
    src, dst = tree

    got, events = _collect(src, dst)

    assert got == [("scanned", 0, 3, ""),
                   ("done", 1, 3, "a.txt"),
                   ("done", 2, 3, "b.txt"),
                   ("done", 3, 3, "c.txt")]
    assert all(e.size == 5 for e in events[1:])  # "a.txt" などの中身は 5 バイト


def test_E2_progress_statuses(tree, tmp_path, fail_on):
    src, dst = tree
    (dst / "a.txt").write_text("既存", encoding="utf-8")   # a: 既存のためスキップ
    ledger = mf.Ledger(tmp_path / "ledger.jsonl")
    ledger.bind(src, dst)
    ledger.record("c.txt", "done")                          # c: 台帳で済
    fail_on("b.txt")                                        # b: 失敗

    got, events = _collect(src, dst, ledger=ledger)
    ledger.close()

    assert [g[0] for g in got] == ["scanned", "skipped", "failed", "skipped"]
    assert events[2].error == "読み取りエラー"

    got, _ = _collect(src, dst, dry_run=True, ledger=mf.Ledger(None))
    assert [g[0] for g in got] == ["scanned", "skipped", "dryrun", "dryrun"]


def test_E3_no_events_after_cancel(tree):
    src, dst = tree

    got, _ = _collect(src, dst, should_cancel=_cancel_after(1))

    assert got == [("scanned", 0, 3, ""), ("done", 1, 3, "a.txt")]


# ================================================================ シナリオ（CLI 経由）

def _load_scenarios():
    spec = importlib.util.spec_from_file_location(
        "run_scenarios", ROOT / "testdata" / "run_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass が自分のモジュールを参照するため
    spec.loader.exec_module(module)
    return module


rs = _load_scenarios()


def _chain(i: int) -> list:
    """i 番目のシナリオと、その前提になる直前のシナリオ（reset=False で繋がるもの）。"""
    start = i
    while start > 0 and not rs.SCENARIOS[start].reset:
        start -= 1
    return rs.SCENARIOS[start:i + 1]


@pytest.mark.scenario
@pytest.mark.parametrize("i", range(len(rs.SCENARIOS)),
                         ids=[f"{sc.sid}-{sc.title}" for sc in rs.SCENARIOS])
def test_S_scenario(i):
    sc = rs.SCENARIOS[i]
    if sc.windows_only and os.name != "nt":
        pytest.skip("Windows のみ")

    for step in _chain(i):
        ok, why = rs.run(step)
        assert ok, f"{step.sid} {step.title}: {why}"
