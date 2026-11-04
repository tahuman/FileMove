# -*- coding: utf-8 -*-
"""
migrate_files.py（本体と CLI）のテスト（pytest）。GUI のテストは test_gui.py

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
    - [P5] make_filter / check_paths / start_message（CLI・GUI 共通）: 入力の文字列から絞り込み条件を作り、
           移行先がファイル・移行元と同じなら ValueError。開始時の 1 行の文言
    - [P6] make_filter(only=...): 渡したファイルだけを対象にし（大文字小文字・相対パスの違いは同じとみなす）、
           後から増えたファイルは扱わない（GUI で「確認した一覧だけを実行する」ため）
    - [P7] SYSTEM_EXCLUDES: desktop.ini・Thumbs.db・Office の一時ファイル・ダウンロード途中のファイルを除外し、
           普通のファイルは除外しない（GUI が常に使う）
  transfer_file（1 ファイルの転送）
    - [T1] 正常にコピーでき、返り値の SHA-256 が移行元と一致し、.part が残らない
    - [T2] verify=False のときはハッシュを計算せず空文字を返す
    - [T3] move=True のときは転送後に移行元が消える
    - [T4] ハッシュ不一致なら IOError。移行先・.part は残らず、move でも移行元は消えない
    - [T5] コピー途中の失敗でも .part が残らず、移行元も消えず、例外はそのまま伝わる
    - [T6] Ctrl+C 相当（KeyboardInterrupt）でも .part が残らない
    - [T7] 失敗しても、移行先にあった既存ファイルは壊さない
    - [T8] 読み取り専用の移行元も移動でき（エクスプローラーと同じ）、読み取り専用の既存ファイルも上書きできる。
           読み取り専用の .part も失敗時に片付く。使用中などで消せないものは失敗のまま
    - [T9] 同じドライブの移動は名前の変更だけで行い、コピーもハッシュの計算もしない（中身・更新日時はそのまま）。
           読み取り専用の移行元・既存ファイルも移せる
    - [T10] 名前の変更で移せない（別のドライブ扱い）ときはコピー → 照合 → 削除に切り替える。別のドライブなら
            最初からコピーで移す。使用中などで名前を変えられないときは、コピーせずに失敗のまま（元は残る）
  run_migration（全体の流れ）
    - [R1] should_cancel が True を返した時点で中断し、cancelled が立ち、残りは転送されない
    - [R2] 最初から中止なら 1 件も転送しない
    - [R3] 1 件の転送失敗で全体は止まらず、failures に記録され、台帳は failed になる
    - [R4] failed は次回の実行で再試行され、done は台帳で処理済みとしてスキップされる
    - [R5] 台帳で done でも、移行先から消えていれば転送し直す（コピー・--move とも）
    - [R6] 台帳の dest は絶対パスで記録し、旧版の相対パスの記録は移行先/相対パスで照合する
    - [C1] 標準出力が cp932（出力をファイルに書き出したとき）でも、絵文字のファイル名でログが壊れない
    - [C2] --version で「FileMove 1.0.0」の形のバージョンを表示して exit 0（移行元・移行先が無くてもよい）
  --move の移行元の片付け
    - [V1] same_content: 中身が同じなら True。中身・サイズが違う、どちらかが無いなら False
    - [V2] 移行先に同じ内容があれば転送せず移行元を削除し、台帳は done。中身が違えば移行元は残る
    - [V3] コピー済み（台帳で done）を後から --move すると移行元が消える。rename 先（台帳の dest）も照合する。
           片付けたものは「台帳で処理済み」には数えない
    - [V4] ドライランでは移行元を消さずに件数だけ数える
    - [V5] 移行元の削除に失敗したら failed になり、残りは続けて処理される
    - [V6] --move で空になった移行元のフォルダを深いほうから消す。指定した移行元そのもの・
           ファイルが残るフォルダ・もともと空のフォルダは残す。ドライランでは消さない
    - [V7] rename でも、移行先に同じ内容があれば _1 を作らずスキップする（reason は same）
  重複ファイルの削除（--dedupe）
    - [D1] find_duplicates: `name (n).ext` で同じフォルダの `name.ext` と同じ内容のものだけを返す
           （中身が違う・元が無い・番号なしのものは対象外。全角括弧・多重拡張子も扱う。
           渡したフォルダだけを見て、サブフォルダはたどらない）
    - [D2] remove_duplicates: 重複だけを消し、ドライランでは消さない。`(1) (1)` の連鎖でも元は残る。
           消した（消す予定の）ものは paths に入る
    - [D3] 削除に失敗したものは failures に入り、残りは続けて処理される
    - [D4] 対象は今回の移行でファイルを置くフォルダだけ。移行先の無関係なフォルダには触らない
    - [D5] ドライランでも、これから置く予定のファイルを含めて判定し、実行したときと結果が一致する
    - [D6] run_migration(dedupe=True) で転送後に重複を削除し、result.dedupe に結果が入る。
           削除に失敗したら result.ok が False になる
  進捗通知（ProgressEvent。GUI の進捗バーが依存する）
    - [E1] 最初に scanned（total 付き）、続いて 1 件ごとに done が index 1..total の順で届く
    - [E2] 既存ファイルのスキップ・台帳での済・失敗・ドライランがそれぞれの status で届き、
           failed には error が入る
    - [E3] 中止したら、それ以降の通知は届かない
    - [E4] --move で移行先に同じ内容があり移行元だけ消したものは removed で届く（ドライランでも）
    - [E5] done / dryrun / skipped / removed には移行先（dest）が入り、skipped / removed には
           理由（reason: done / exists / same）が入る。scanned 以外には移行元（src）が入る
           （GUI の結果の一覧と、確認した一覧だけを実行する仕組みが依存する）
  CLI のデモ（demo/cli/demo.py と、その GIF を作る demo/cli/make_gif.py）
    - [G1] デモの全 12 パターンが指定した作業フォルダで最後まで動き、片付け・重複削除・指定ミス・
           ドライブ間の移動が期待どおりになる。表示には実際の作業フォルダのパスを出さない
    - [G2] --only N は PN だけを表示する（準備のコマンドは表示せずに実行する）
    - [G3] make_gif: 全角を 2 桁として折り返し、コマンド（PS プロンプト）・見出し・出力・
           【実行前／後】・フォルダ表示の種類で色を分ける
    - [G4] make_gif: 行の並びから、複数フレームのループする GIF を作る（フォントが無い環境では skip）
  シナリオ（CLI 経由。testdata/SCENARIOS.md の表を testdata/run_scenarios.py で実行）
    - [S] 全シナリオ。前のシナリオの結果を使うもの（reset=False）は、前提から続けて実行する
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
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


def test_P5_make_filter_and_check_paths(tmp_path):
    filt = mf.make_filter(ext=" PDF, .jpg ,", excludes=["*.tmp"], since="30d", min_size="1KB")
    assert (filt.exts, filt.excludes, filt.min_size) == ({"pdf", "jpg"}, ("*.tmp",), 1024)
    assert filt.since is not None
    assert mf.make_filter(ext="  ").exts is None             # 空ならすべて
    with pytest.raises(ValueError, match="書式が不正"):
        mf.make_filter(since="あした")

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    mf.check_paths([src], tmp_path / "dst")                  # 問題なし
    with pytest.raises(ValueError, match="ディレクトリではありません"):
        mf.check_paths([src], src / "a.txt")
    with pytest.raises(ValueError, match="移行元と移行先が同じです"):
        mf.check_paths([src / "a.txt"], src)

    assert mf.start_message([src], tmp_path, move=True, dry_run=True) == f"移行開始: {src} -> {tmp_path}（移動／ドライラン）"
    assert mf.start_message([src, src], tmp_path, move=False, dry_run=False).endswith("ほか 1 件 -> " + f"{tmp_path}（コピー）")


def test_P6_filter_only(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    for rel in ("a.txt", "b.txt", "sub/c.txt"):
        (src / rel).write_text(rel, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    only = [Path("src") / "a.txt", str(src / "SUB" / "c.txt") if os.name == "nt" else str(src / "sub" / "c.txt")]

    (src / "new.txt").write_text("後から増えた", encoding="utf-8")
    result = mf.run_migration(src, dst, filt=mf.make_filter(only=only))

    assert result.copied == 2
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()) == ["a.txt", "sub/c.txt"]
    assert mf.make_filter().only is None and mf.make_filter(only=[]).only == frozenset()


def test_P7_system_excludes(tmp_path):
    src = tmp_path / "Downloads"
    (src / "資料").mkdir(parents=True)
    names = ["desktop.ini", "Thumbs.db", "~$議事録.docx", "setup.exe.crdownload", "動画.mp4.part",
             "a.partial", "b.download", "資料/desktop.ini", "議事録.docx", "report.pdf", "part.txt", "資料/a.txt"]
    for n in names:
        (src / n).write_text(n, encoding="utf-8")

    found = mf.collect_files(src, tmp_path / "dst", mf.make_filter(excludes=mf.SYSTEM_EXCLUDES))

    assert sorted(f.relative_to(src).as_posix() for f in found) == ["part.txt", "report.pdf", "議事録.docx", "資料/a.txt"]


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
        mf.transfer_file(src_file, dest, move=move, rename=False, copy_fn=_corrupt_copy)

    assert not dest.exists()
    assert not _part(dest).exists()
    assert src_file.read_bytes() == b"hello world"  # move でも移行元は消さない


@pytest.mark.parametrize("exc", [OSError("ディスクがいっぱい"), KeyboardInterrupt()],
                         ids=["T5_oserror", "T6_interrupt"])
def test_T5_T6_failure_mid_copy(src_file, dest, exc):
    with pytest.raises(type(exc)):
        mf.transfer_file(src_file, dest, move=True, rename=False, copy_fn=_failing_copy(exc))

    assert not dest.exists()
    assert not _part(dest).exists()
    assert src_file.exists()


def test_T7_failure_keeps_existing_dest(src_file, dest):
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"existing")

    with pytest.raises(IOError):
        mf.transfer_file(src_file, dest, copy_fn=_corrupt_copy)

    assert dest.read_bytes() == b"existing"


def _no_copy(*a, **kw):
    raise AssertionError("コピー・ハッシュの計算はしないはず")


def test_T9_same_drive_move_by_rename(tmp_path, monkeypatch):
    import stat
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "a.txt").write_text("中身", encoding="utf-8")
    os.utime(src / "a.txt", (1_700_000_000, 1_700_000_000))
    (src / "ro.txt").write_text("読み取り専用", encoding="utf-8")
    os.chmod(src / "ro.txt", stat.S_IREAD)
    (dst / "sub").mkdir(parents=True)
    (dst / "sub" / "ro.txt").write_text("古い", encoding="utf-8")
    os.chmod(dst / "sub" / "ro.txt", stat.S_IREAD)
    monkeypatch.setattr(mf, "sha256_of", _no_copy)

    assert mf.transfer_file(src / "a.txt", dst / "a.txt", move=True, copy_fn=_no_copy) == ""
    mf.transfer_file(src / "ro.txt", dst / "sub" / "ro.txt", move=True, copy_fn=_no_copy)   # 上書き

    assert _names(src) == []
    assert (dst / "a.txt").read_text(encoding="utf-8") == "中身"
    assert (dst / "a.txt").stat().st_mtime == 1_700_000_000
    assert (dst / "sub" / "ro.txt").read_text(encoding="utf-8") == "読み取り専用"


def test_T10_rename_fallback_and_failure(tmp_path, monkeypatch):
    import errno
    src_file = tmp_path / "src" / "a.txt"
    src_file.parent.mkdir()
    src_file.write_bytes(b"hello")
    real_replace = mf.os.replace
    calls = []

    def replace(error):
        def fake(x, y):
            if Path(x) == src_file:      # 移行元からの名前の変更だけ失敗させる（.part からの置き換えは通す）
                calls.append(x)
                raise error
            return real_replace(x, y)
        return fake

    # 名前の変更で移せない（別のドライブ扱い）-> コピー -> 照合 -> 削除
    monkeypatch.setattr(mf.os, "replace", replace(OSError(errno.EXDEV, "別のドライブ")))
    assert mf.transfer_file(src_file, tmp_path / "dst" / "a.txt", move=True) == _sha(b"hello")
    assert len(calls) == 1 and not src_file.exists() and (tmp_path / "dst" / "a.txt").read_bytes() == b"hello"

    # 別のドライブなら最初からコピーで移す
    src_file.write_bytes(b"hello")
    monkeypatch.setattr(mf, "_same_drive", lambda a, b: False)
    assert mf.transfer_file(src_file, tmp_path / "d2" / "a.txt", move=True) == _sha(b"hello")
    assert len(calls) == 1

    # 使用中などで名前を変えられないときは、コピーせずに失敗のまま
    src_file.write_bytes(b"hello")
    monkeypatch.setattr(mf, "_same_drive", lambda a, b: True)
    monkeypatch.setattr(mf.os, "replace", replace(PermissionError(errno.EACCES, "使用中です")))
    with pytest.raises(PermissionError):
        mf.transfer_file(src_file, tmp_path / "d3" / "a.txt", move=True, copy_fn=_no_copy)
    assert src_file.exists() and not (tmp_path / "d3" / "a.txt").exists()


def test_T8_read_only_files(tmp_path, monkeypatch):
    import stat
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "ro.txt").write_text("読み取り専用", encoding="utf-8")
    os.chmod(src / "ro.txt", stat.S_IREAD)
    (src / "new.txt").write_text("新しい", encoding="utf-8")
    (dst / "new.txt").write_text("古い", encoding="utf-8")
    os.chmod(dst / "new.txt", stat.S_IREAD)

    result = mf.run_migration(src, dst, move=True, on_exists="overwrite")

    assert result.ok and result.copied == 2
    assert _names(src) == []
    assert (dst / "ro.txt").read_text(encoding="utf-8") == "読み取り専用"
    assert (dst / "new.txt").read_text(encoding="utf-8") == "新しい"

    # 読み取り専用の .part も、失敗したら片付く
    (src / "ro2.txt").write_text("x", encoding="utf-8")
    os.chmod(src / "ro2.txt", stat.S_IREAD)

    def copy_then_fail(a, b):
        mf.shutil.copy2(a, b)   # 読み取り専用の属性も写る
        raise OSError("ディスクがいっぱいです")
    with pytest.raises(OSError):
        mf.transfer_file(src / "ro2.txt", dst / "ro2.txt", copy_fn=copy_then_fail)
    assert not _part(dst / "ro2.txt").exists()

    # 使用中など（読み取り専用ではない）で消せないものは、失敗のまま
    real = Path.unlink

    def busy(self, *a, **kw):
        if self.name == "busy.txt":
            raise PermissionError("使用中です")
        return real(self, *a, **kw)
    (src / "busy.txt").write_text("b", encoding="utf-8")
    monkeypatch.setattr(Path, "unlink", busy)
    with pytest.raises(PermissionError, match="使用中です"):
        mf.remove_file(src / "busy.txt")


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


@pytest.mark.parametrize("move", [False, True])
def test_R5_retransfer_when_dest_missing(tree, tmp_path, move, caplog):
    src, dst = tree
    ledger_path = tmp_path / "ledger.jsonl"
    first = mf.Ledger(ledger_path)
    mf.run_migration(src, dst, ledger=first)
    first.close()
    (dst / "b.txt").unlink()   # コピーした後に移行先から消えた

    second = mf.Ledger(ledger_path)
    with caplog.at_level("INFO", logger="migrate"):
        result = mf.run_migration(src, dst, move=move, ledger=second)
    second.close()

    assert result.copied == 1
    assert "移行先に見当たらないため転送し直します: b.txt" in caplog.text
    assert (dst / "b.txt").read_text(encoding="utf-8") == "b.txt"
    assert _names(src) == ([] if move else ["a.txt", "b.txt", "c.txt"])


def test_R6_ledger_dest_is_absolute(tree, tmp_path, monkeypatch):
    src, dst = tree
    monkeypatch.chdir(tmp_path)
    ledger_path = tmp_path / "ledger.jsonl"
    first = mf.Ledger(ledger_path)
    mf.run_migration(Path("src"), Path("dst"), ledger=first)   # 相対パスで実行
    first.close()

    second = mf.Ledger(ledger_path)
    second.bind(src, dst)
    assert all(Path(second.get(n)["dest"]).is_absolute() for n in ("a.txt", "b.txt", "c.txt"))

    # 旧版の台帳（dest が相対パス）は、別の場所から実行しても移行先/相対パスで照合する
    second.record("a.txt", "done", dest="dst/a.txt")
    monkeypatch.chdir(src)
    result = mf.run_migration(src, dst, move=True, ledger=second)
    second.close()

    assert result.sources_removed == 3
    assert _names(src) == []


def test_C2_version(capsys):
    with pytest.raises(SystemExit) as e:
        mf.main(["--version"])

    assert e.value.code == 0
    assert capsys.readouterr().out == f"FileMove {mf.__version__}\n"
    assert re.fullmatch(r"\d+\.\d+\.\d+", mf.__version__)


@pytest.mark.scenario
def test_C1_output_to_cp932_file(tmp_path):
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "🍣.txt").write_text("x", encoding="utf-8")

    # 出力をファイルに書き出したときと同じく、標準出力を cp932 にして実行する
    p = subprocess.run([sys.executable, str(ROOT / "migrate_files.py"), "e", "out",
                        "--log", "m.log", "--ledger", "l.jsonl"],
                       cwd=tmp_path, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp932"})
    out = p.stdout.decode("cp932") + p.stderr.decode("cp932", "replace")

    assert p.returncode == 0, out
    assert "Logging error" not in out
    assert "\\U0001f363.txt" in out                                   # 画面には置き換えて出す
    assert "🍣.txt" in (tmp_path / "m.log").read_text(encoding="utf-8")  # ログファイルはそのまま


# ================================================================ --move の移行元の片付け

@pytest.fixture
def unlink_fails_on(monkeypatch):
    """unlink_fails_on("b.txt") で、その名前のファイルだけ削除に失敗させる。"""
    real = Path.unlink

    def install(name: str) -> None:
        def fake(self, *a, **kw):
            if self.name == name:
                raise PermissionError("使用中です")
            return real(self, *a, **kw)
        monkeypatch.setattr(Path, "unlink", fake)
    return install


def test_V1_same_content(tmp_path):
    a, b, c, d = (tmp_path / n for n in ("a", "b", "c", "d"))
    a.write_bytes(b"hello")
    b.write_bytes(b"hello")
    c.write_bytes(b"world")   # 同じサイズで中身が違う
    d.write_bytes(b"hello!")  # サイズが違う

    assert mf.same_content(a, b)
    assert not mf.same_content(a, c)
    assert not mf.same_content(a, d)
    assert not mf.same_content(a, tmp_path / "missing")
    assert not mf.same_content(tmp_path / "missing", a)


def test_V2_move_drops_source_when_dest_has_same_content(tree):
    src, dst = tree
    (dst / "a.txt").write_text("a.txt", encoding="utf-8")   # 同じ内容
    (dst / "b.txt").write_text("違う", encoding="utf-8")    # 中身が違う
    ledger = mf.Ledger(None)

    result = mf.run_migration(src, dst, move=True, ledger=ledger)

    assert (result.copied, result.skipped, result.sources_removed) == (1, 2, 1)
    assert _names(src) == ["b.txt"]                          # 中身が違うものだけ残る
    assert (dst / "b.txt").read_text(encoding="utf-8") == "違う"
    assert _names(dst) == ["a.txt", "b.txt", "c.txt"]        # a_1.txt などは作らない
    ledger.bind(src, dst)
    assert ledger.get("a.txt")["status"] == "done"


def test_V3_move_after_copy_uses_ledger(tree, tmp_path):
    src, dst = tree
    (dst / "a.txt").write_text("既存", encoding="utf-8")
    ledger_path = tmp_path / "ledger.jsonl"

    first = mf.Ledger(ledger_path)
    mf.run_migration(src, dst, on_exists="rename", ledger=first)   # a は a_1.txt に入る
    first.close()
    assert _names(src) == ["a.txt", "b.txt", "c.txt"]

    second = mf.Ledger(ledger_path)
    result = mf.run_migration(src, dst, move=True, ledger=second)
    second.close()

    # 片付けたものは「台帳で処理済みとしてスキップ」には数えない（--restart の案内を出さない）
    assert (result.copied, result.skipped, result.already_done, result.sources_removed) == (0, 3, 0, 3)
    assert _names(src) == []
    assert (dst / "a.txt").read_text(encoding="utf-8") == "既存"


def test_V4_dry_run_keeps_source(tree):
    src, dst = tree
    (dst / "a.txt").write_text("a.txt", encoding="utf-8")

    result = mf.run_migration(src, dst, move=True, dry_run=True)

    assert (result.copied, result.skipped, result.sources_removed) == (2, 1, 1)
    assert _names(src) == ["a.txt", "b.txt", "c.txt"]


def test_V5_drop_source_failure(tree, unlink_fails_on):
    src, dst = tree
    for name in ("a.txt", "b.txt"):
        (dst / name).write_text(name, encoding="utf-8")
    unlink_fails_on("a.txt")
    ledger = mf.Ledger(None)

    result = mf.run_migration(src, dst, move=True, ledger=ledger)

    assert (result.copied, result.skipped, result.failed) == (1, 1, 1)
    assert result.failures == [("a.txt", "使用中です")]
    assert _names(src) == ["a.txt"]
    ledger.bind(src, dst)
    assert ledger.get("a.txt") == {}   # done にしないので次回また片付けを試みる


def test_V6_move_removes_emptied_dirs(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    for rel in ("資料/2025/a.txt", "資料/b.txt", "写真/c.jpg", "残す/d.txt"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(rel, encoding="utf-8")
    (src / "空").mkdir()                                     # もともと空
    filt = mf.make_filter(ext="txt,jpg")
    (src / "残す" / "e.log").write_text("対象外", encoding="utf-8")   # 拡張子で対象外 -> 残る

    preview = mf.run_migration(src, dst, move=True, dry_run=True, filt=filt)
    assert preview.dirs_removed == [] and (src / "資料" / "2025").is_dir()

    result = mf.run_migration(src, dst, move=True, filt=filt)

    assert {p.relative_to(src).as_posix() for p in result.dirs_removed} == {"資料/2025", "資料", "写真"}
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*")) == ["残す", "残す/e.log", "空"]
    assert src.is_dir()                                       # 指定した移行元そのものは残す


def test_V7_rename_skips_same_content(tree):
    src, dst = tree
    (dst / "a.txt").write_text("a.txt", encoding="utf-8")   # 同じ内容
    (dst / "b.txt").write_text("違う", encoding="utf-8")    # 中身が違う

    got, events = _collect(src, dst, on_exists="rename")

    assert [(e.status, e.rel, e.reason) for e in events[1:]] == [
        ("skipped", "a.txt", "same"), ("done", "b.txt", ""), ("done", "c.txt", "")]
    assert _names(dst) == ["a.txt", "b.txt", "b_1.txt", "c.txt"]


# ================================================================ 重複ファイルの削除

@pytest.fixture
def dups(tmp_path: Path) -> Path:
    """重複・重複でないものを混ぜたフォルダ。"""
    root = tmp_path / "dst"
    files = {
        "report.txt": "same",
        "report (1).txt": "same",          # 重複
        "report (2).txt": "different",     # 中身が違う
        "report(3).txt": "same",           # 空白なしも重複
        "memo (1).txt": "orphan",          # 元が無い
        "archive.tar.gz": "gz",
        "archive (1).tar.gz": "gz",        # 多重拡張子
        "sub/写真.jpg": "jpg",
        "sub/写真（1）.jpg": "jpg",          # 全角括弧・サブフォルダ
        "a.txt": "chain",
        "a (1).txt": "chain",
        "a (1) (1).txt": "chain",          # a (1).txt の重複
        "plain.txt": "same",               # 番号なしは対象外
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _rels(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _dirs(root: Path) -> list[Path]:
    return [root, *sorted(p for p in root.rglob("*") if p.is_dir())]


DUPLICATES = {"report (1).txt", "report(3).txt", "archive (1).tar.gz", "sub/写真（1）.jpg",
              "a (1).txt", "a (1) (1).txt"}


def test_D1_find_duplicates(dups):
    pairs = mf.find_duplicates(_dirs(dups))

    got = {d.relative_to(dups).as_posix(): o.name for d, o in pairs}
    assert got == {"report (1).txt": "report.txt", "report(3).txt": "report.txt",
                   "archive (1).tar.gz": "archive.tar.gz", "sub/写真（1）.jpg": "写真.jpg",
                   "a (1).txt": "a.txt", "a (1) (1).txt": "a (1).txt"}
    # 渡したフォルダだけを見る（サブフォルダはたどらない）
    assert {d.name for d, _ in mf.find_duplicates([dups / "sub"])} == {"写真（1）.jpg"}


def test_D2_remove_duplicates(dups):
    before = _rels(dups)

    preview = mf.remove_duplicates(_dirs(dups), root=dups, dry_run=True)
    assert preview.removed == len(DUPLICATES)
    assert _rels(dups) == before

    result = mf.remove_duplicates(_dirs(dups), root=dups)
    assert result.removed == len(DUPLICATES)
    assert result.bytes_freed == sum(len(n) for n in ("same", "same", "gz", "jpg", "chain", "chain"))
    assert _rels(dups) == before - DUPLICATES
    assert {p.relative_to(dups).as_posix() for p in result.paths} == DUPLICATES
    assert (dups / "a.txt").exists()


def test_D3_remove_duplicates_failure(dups, unlink_fails_on):
    unlink_fails_on("report (1).txt")

    result = mf.remove_duplicates(_dirs(dups), root=dups)

    assert result.failures == [("report (1).txt", "使用中です")]
    assert result.removed == len(DUPLICATES) - 1
    assert (dups / "report (1).txt").exists()


def test_D4_dedupe_only_folders_of_this_run(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    for rel, body in {"src/写真/new.jpg": "new", "dst/写真/a.jpg": "a", "dst/写真/a (1).jpg": "a",
                      "dst/私物/b.jpg": "b", "dst/私物/b (1).jpg": "b"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")

    migrated = mf.run_migration(src, dst)
    result = mf.remove_duplicates(migrated.dest_dirs, root=dst)

    assert migrated.dest_dirs == [dst / "写真"]
    assert result.removed == 1
    assert not (dst / "写真/a (1).jpg").exists()
    assert (dst / "私物/b (1).jpg").exists()   # 今回の移行と関係ないフォルダには触らない


def test_D5_dedupe_dry_run_includes_planned_files(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for name in ("a.txt", "a (1).txt"):
        (src / name).write_text("same", encoding="utf-8")

    migrated = mf.run_migration(src, dst, dry_run=True)
    preview = mf.remove_duplicates(migrated.dest_dirs, root=dst, planned=migrated.placed, dry_run=True)

    assert not dst.exists()                    # 何も書き込まない
    assert (preview.removed, preview.bytes_freed) == (1, 4)

    real = mf.run_migration(src, dst)
    assert mf.remove_duplicates(real.dest_dirs, root=dst).removed == preview.removed


def test_D6_run_migration_with_dedupe(tmp_path, unlink_fails_on):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for name in ("a.txt", "a (1).txt", "b.txt", "b (1).txt"):
        (src / name).write_text(name[0], encoding="utf-8")

    preview = mf.run_migration(src, dst, dry_run=True, dedupe=True)
    assert (preview.dedupe.removed, preview.ok) == (2, True)
    assert not dst.exists()
    assert mf.run_migration(src, tmp_path / "plain").dedupe is None   # dedupe なしなら None

    unlink_fails_on("b (1).txt")
    result = mf.run_migration(src, dst, dedupe=True)
    assert result.dedupe.removed == 1
    assert result.dedupe.failures == [("b (1).txt", "使用中です")]
    assert not result.ok           # 重複の削除に失敗したら ok ではない（CLI は exit 1）
    assert _names(dst) == ["a.txt", "b (1).txt", "b.txt"]


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
    (dst / "c.txt").write_text("c.txt", encoding="utf-8")
    ledger = mf.Ledger(tmp_path / "ledger.jsonl")
    ledger.bind(src, dst)
    ledger.record("c.txt", "done")                          # c: 台帳で済（移行先にもある）
    fail_on("b.txt")                                        # b: 失敗

    got, events = _collect(src, dst, ledger=ledger)
    ledger.close()

    assert [g[0] for g in got] == ["scanned", "skipped", "failed", "skipped"]
    assert events[2].error == "読み取りエラー"

    got, _ = _collect(src, dst, dry_run=True, ledger=mf.Ledger(None))
    assert [g[0] for g in got] == ["scanned", "skipped", "dryrun", "skipped"]


def test_E3_no_events_after_cancel(tree):
    src, dst = tree

    got, _ = _collect(src, dst, should_cancel=_cancel_after(1))

    assert got == [("scanned", 0, 3, ""), ("done", 1, 3, "a.txt")]


@pytest.mark.parametrize("dry_run", [False, True])
def test_E4_removed_status(tree, dry_run):
    src, dst = tree
    (dst / "a.txt").write_text("a.txt", encoding="utf-8")   # 同じ内容が移行先にある

    got, _ = _collect(src, dst, move=True, dry_run=dry_run)

    assert [g[0] for g in got] == ["scanned", "removed", *(["dryrun"] * 2 if dry_run else ["done"] * 2)]


def test_E5_progress_dest_and_reason(tree, tmp_path):
    src, dst = tree
    (dst / "a.txt").write_text("既存", encoding="utf-8")   # a: 同名の別のファイル
    (dst / "b.txt").write_text("b.txt", encoding="utf-8")  # b: 同じ内容
    ledger = mf.Ledger(tmp_path / "ledger.jsonl")

    _, events = _collect(src, dst, move=True, ledger=ledger)
    assert events[0].src == "" and [e.src for e in events[1:]] == [str(src / n) for n in ("a.txt", "b.txt", "c.txt")]
    assert [(e.status, e.dest, e.reason) for e in events[1:]] == [
        ("skipped", str(dst / "a.txt"), "exists"),
        ("removed", str(dst / "b.txt"), "same"),
        ("done", str(dst / "c.txt"), "")]

    (src / "c.txt").write_text("c.txt", encoding="utf-8")   # 台帳で済のものをもう一度コピー
    _, events = _collect(src, dst, ledger=ledger)
    ledger.close()
    assert (events[-1].status, events[-1].reason) == ("skipped", "done")
    assert events[-1].dest == os.path.abspath(dst / "c.txt")

    _, events = _collect(src, tmp_path / "new", dry_run=True)
    assert [(e.status, e.dest) for e in events[1:]] == [("dryrun", str(tmp_path / "new" / "a.txt")),
                                                         ("dryrun", str(tmp_path / "new" / "c.txt"))]


# ================================================================ デモ

DEMO = ROOT / "demo" / "cli"


def _run_demo(*args: str) -> str:
    p = subprocess.run([sys.executable, str(DEMO / "demo.py"), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


@pytest.mark.scenario
def test_G1_demo_runs_all_steps(tmp_path):
    work = tmp_path / "work"

    out = _run_demo("--auto", "--work", str(work))

    assert "Traceback" not in out
    assert len([line for line in out.splitlines() if line.startswith("■ P")]) == 12
    assert "うち移行先に同じ内容があるため移行元を削除 9 件" in out   # P9 コピー済みの片付け
    assert "重複を削除: IMG_0001 (1).jpg" in out                      # P10
    assert "移行元が見つかりません: Downloads\\見積書_C社.pdf" in out.replace("/", "\\")  # P11
    body = out.split("作業フォルダ:", 1)[1].split("\n", 1)[1]   # 冒頭の作業フォルダの表示より後
    assert "D:\\写真\\旅行" in body and str(work) not in body       # 実際のパスは見せない
    # 最後の P12 の結果: C の旅行フォルダが D へ移っている
    assert {p.name for p in (work / "D/写真/旅行").iterdir()} == {"海_01.jpg", "海_02.jpg", "山_01.jpg"}
    assert not any((work / "Users/user/Pictures/旅行").iterdir())


@pytest.mark.scenario
def test_G2_demo_only_one_step(tmp_path):
    out = _run_demo("--only", "7", "--work", str(tmp_path / "work"))

    assert [line for line in out.splitlines() if line.startswith("■")] == \
        ["■ P7 途中で止まった・もう一度実行してしまった"]
    assert out.count("PS C:\\Users\\user> python") == 1   # 準備のコピーは表示しない
    assert "台帳で処理済みとしてスキップ 9 件" in out


@pytest.fixture
def make_gif():
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("make_gif", DEMO / "make_gif.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_G3_make_gif_wrap_and_classify(make_gif):
    assert make_gif.width("ab") == 2
    assert make_gif.width("日本") == 4
    assert make_gif.wrap("あ" * 5, cols=4) == ["ああ", "    あ", "    あ", "    あ"]

    lines = make_gif.parse("\n■ P1 見出し\n  警告が出ます（説明文）\n\n\n"
                           "  PS C:\\Users\\user> python migrate_files.py a b\n"
                           "    [1/2] 失敗 x: エラー\n"
                           "    完了: 成功 1 / スキップ 0 / 失敗 1\n"
                           "    重複を削除: a (1).txt\n"
                           "    （終了コード 1）\n"
                           "\n  【実行後】\n"
                           "  📁 C:\\out\\\n     └─ a.txt\n  📁 C:\\empty\\\n     （空）\n\n")
    assert [(l.text.strip(), l.color) for l in lines] == [
        ("", "text"), ("■ P1 見出し", "title"), ("警告が出ます（説明文）", "text"), ("", "text"),
        ("PS C:\\Users\\user> python migrate_files.py a b", "cmd"), ("[1/2] 失敗 x: エラー", "error"),
        ("完了: 成功 1 / スキップ 0 / 失敗 1", "text"), ("重複を削除: a (1).txt", "warn"),
        ("（終了コード 1）", "dim"), ("", "text"), ("【実行後】", "label"),
        ("C:\\out\\", "tree"), ("└─ a.txt", "tree"), ("C:\\empty\\", "tree"), ("（空）", "tree")]


def test_G4_make_gif_render(make_gif, tmp_path):
    try:
        fonts = make_gif.load_fonts()
    except SystemExit:
        pytest.skip("日本語フォントが無い環境")
    lines = make_gif.parse("■ テスト\n  PS C:\\> python migrate_files.py a b\n    完了: 成功 1 / スキップ 0 / 失敗 0\n")
    out = tmp_path / "t.gif"

    n = make_gif.render(lines, out, fonts)

    from PIL import Image
    with Image.open(out) as im:
        assert im.format == "GIF"
        assert im.n_frames == n > 2
        assert im.info.get("loop") == 0


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
