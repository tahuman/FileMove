#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ファイル移行バッチ

ディレクトリ構成を保ったままファイルをコピー／移動する。
振る舞いの一覧は testdata/SCENARIOS.md（自動実行は testdata/run_scenarios.py）、
単体テストは test_migrate_files.py を参照。

設計上の方針（テストしやすさのため）:
  - 副作用のある処理は差し替え可能にする（copy_fn, now, log, ledger を注入できる）
  - 中核の run_migration() は結果オブジェクトを返すだけで、表示や終了コードは CLI 側の責務
  - 例外は握り潰さず、1 件の失敗が全体を止めないよう呼び出し側でまとめる

使用例:
    python migrate_files.py /data/old /data/new --dry-run
    python migrate_files.py /data/old /data/new --ext pdf,xlsx --since 30d
    python migrate_files.py /data/old /data/new --move
    python migrate_files.py /data/old /data/new --dedupe        # 移行先の "name (1).ext" の重複を削除
    python migrate_files.py /data/old/report.pdf /data/new   # 単一ファイル -> /data/new/report.pdf
    python migrate_files.py a/x.pdf b/y.xlsx "c/*.txt" /data/new  # 複数指定（最後が移行先）
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

CHUNK_SIZE = 1024 * 1024  # 1MB
LOGGER = logging.getLogger("migrate")


# ================================================================ 値のパース

def parse_since(value: str | None, now: float | None = None) -> float | None:
    """'30d' / '12h' / '2025-04-01' を epoch 秒に変換する。

    now を渡せるようにしてあるのは、時刻に依存するテストを安定させるため。
    """
    if not value:
        return None
    now = time.time() if now is None else now
    v = value.strip().lower()
    if v.endswith("d") and v[:-1].isdigit():
        return now - int(v[:-1]) * 86400
    if v.endswith("h") and v[:-1].isdigit():
        return now - int(v[:-1]) * 3600
    try:
        return datetime.strptime(v, "%Y-%m-%d").timestamp()
    except ValueError:
        raise ValueError(f"--since の書式が不正です: {value} (例: 30d, 12h, 2025-04-01)")


def parse_size(value: str | None) -> int | None:
    """'10MB' / '500K' / '1.5GB' / '1234' をバイト数に変換する。"""
    if not value:
        return None
    v = value.strip().upper().replace("B", "")
    units = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    if v and v[-1] in units:
        return int(float(v[:-1]) * units[v[-1]])
    return int(v)


def human(n: float) -> str:
    """バイト数を読みやすい単位にする（ログ表示用）。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ================================================================ ハッシュ

def sha256_of(path: Path) -> str:
    """ファイル全体の SHA-256。大きいファイルでもメモリを食わないよう分割読み。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def same_content(a: Path, b: Path) -> bool:
    """2 つのファイルの中身が同じか。どちらかが無い・サイズが違うならハッシュは計算しない。"""
    try:
        if not (a.is_file() and b.is_file()) or a.stat().st_size != b.stat().st_size:
            return False
        return sha256_of(a) == sha256_of(b)
    except OSError:
        return False


# ================================================================ 移行先の決定

def resolve_destination(dest: Path, policy: str,
                        exists: Callable[[Path], bool] = Path.exists) -> Path | None:
    """同名ファイルがある場合の移行先を決める。None なら転送しない。

    exists を差し替えると、ドライランで「この実行で先に置かれる予定のファイル」も
    既存として扱える。
    """
    if not exists(dest):
        return dest
    if policy == "skip":
        return None
    if policy == "overwrite":
        return dest
    # rename: foo.txt -> foo_1.txt -> foo_2.txt ...
    stem, suffix, i = dest.stem, dest.suffix, 1
    while True:
        cand = dest.with_name(f"{stem}_{i}{suffix}")
        if not exists(cand):
            return cand
        i += 1


# ================================================================ 1ファイルの転送

def transfer_file(src_file: Path, dest: Path, *,
                  move: bool = False,
                  verify: bool = True,
                  copy_fn: Callable[[Path, Path], object] = shutil.copy2) -> str:
    """1 ファイルを転送する。検証済みの SHA-256（verify=False なら空文字）を返す。

    一時ファイル(.part)に書いてから rename するので、途中で落ちても
    中途半端なファイルが移行先に残らない。移行元の削除は検証が通った後だけ。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")

    try:
        copy_fn(src_file, tmp)  # copy2 は更新日時などのメタデータも引き継ぐ

        digest = ""
        if verify:
            digest = sha256_of(src_file)
            if sha256_of(tmp) != digest:
                raise IOError("転送後のハッシュが一致しません"
                              "（転送先の破損、またはコピー中に移行元が更新された）")

        os.replace(tmp, dest)  # 同一ディレクトリ内なのでほぼアトミック
    except BaseException:
        Path(tmp).unlink(missing_ok=True)  # 失敗したら痕跡を残さない
        raise

    if move:
        src_file.unlink()

    return digest


# ================================================================ 台帳（再開用）

def _root_id(path: Path) -> str:
    """台帳で移行元／移行先を識別するための文字列（Windows では大文字小文字を同一視）。"""
    return os.path.normcase(str(Path(path).resolve()))


class Ledger:
    """処理結果を 1 行 1 レコードの JSONL に追記する。再実行時の再開判定に使う。

    path=None なら記録はメモリ上だけ（ドライランや単発実行向け）。

    レコードには移行元・移行先のルート（src_root / dst_root）を記録し、
    bind() で指定した組み合わせのレコードだけを参照する。これにより同じ台帳
    ファイルを別の移行で使い回しても、相対パスが同じだけの別ファイルを
    処理済みと誤判定しない。ルートを持たない旧形式のレコードは参照しない。
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.records: dict[tuple[str, str, str], dict] = {}
        self.scope: tuple[str, str] = ("", "")
        self._fh = None

        if self.path and self.path.exists():
            self._load()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")

    def _load(self) -> None:
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    key = (rec.get("src_root", ""), rec.get("dst_root", ""), rec["path"])
                    self.records[key] = rec
                except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                    continue  # 壊れた行は無視して読み進める

    def bind(self, src: Path, dst: Path) -> None:
        """以降の判定・記録を、この移行元→移行先の組み合わせに限定する。"""
        self.scope = (_root_id(src), _root_id(dst))

    def _key(self, rel: str) -> tuple[str, str, str]:
        return (*self.scope, rel)

    def is_done(self, rel: str) -> bool:
        """成功したものだけ処理済みとみなす。failed は次回に再試行させる。"""
        return self.get(rel).get("status") == "done"

    def get(self, rel: str) -> dict:
        """記録を返す。無ければ空の dict。"""
        return self.records.get(self._key(rel), {})

    def record(self, rel: str, status: str, **extra) -> None:
        rec = {"path": rel, "status": status,
               "ts": datetime.now().isoformat(timespec="seconds"), **extra}
        if any(self.scope):
            rec["src_root"], rec["dst_root"] = self.scope
        self.records[self._key(rel)] = rec
        if self._fh:
            self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._fh.flush()  # 強制終了されても直前までの結果は残る

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# ================================================================ 対象の列挙

@dataclass
class FileFilter:
    """転送対象を絞り込む条件。"""
    exts: Iterable[str] | None = None        # 拡張子（大文字小文字は無視）
    excludes: Sequence[str] = ()             # 除外する glob
    since: float | None = None               # この epoch 秒以降に更新されたもの
    min_size: int | None = None
    max_size: int | None = None

    def __post_init__(self):
        if self.exts is not None:
            self.exts = frozenset(e.lower().lstrip(".") for e in self.exts)
        self.excludes = tuple(self.excludes)

    def excluded(self, name: str, rel: str) -> bool:
        return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p)
                   for p in self.excludes)

    def accepts(self, path: Path, st: os.stat_result) -> bool:
        if self.exts is not None and path.suffix.lower().lstrip(".") not in self.exts:
            return False
        if self.since is not None and st.st_mtime < self.since:
            return False
        if self.min_size is not None and st.st_size < self.min_size:
            return False
        if self.max_size is not None and st.st_size > self.max_size:
            return False
        return True


def collect_files(src: Path, dst: Path, filt: FileFilter,
                  log: logging.Logger | None = None) -> list[Path]:
    """条件に合うファイルを集めて、安定した順序で返す。

    src がファイルの場合は、そのファイル 1 件だけを同じ条件で判定する。
    """
    log = log or LOGGER
    src, dst = Path(src), Path(dst)
    if src.is_file():
        if filt.excluded(src.name, src.name):
            return []
        try:
            st = src.stat()
        except OSError as e:
            log.warning("情報を取得できないためスキップ: %s (%s)", src.name, e)
            return []
        return [src] if filt.accepts(src, st) else []

    dst_resolved = dst.resolve()

    targets: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(src):
        here = Path(dirpath)

        keep = []
        for d in dirnames:
            child = here / d
            if child.resolve() == dst_resolved:
                continue  # 移行先が移行元の配下にある場合、そこは辿らない
            rel_d = child.relative_to(src).as_posix()
            if filt.excluded(d, rel_d):
                continue
            keep.append(d)
        dirnames[:] = keep

        for name in filenames:
            path = here / name
            rel = path.relative_to(src).as_posix()
            if filt.excluded(name, rel):
                continue
            try:
                st = path.stat()
            except OSError as e:
                log.warning("情報を取得できないためスキップ: %s (%s)", rel, e)
                continue
            if filt.accepts(path, st):
                targets.append(path)

    return sorted(targets)


# ================================================================ 全体の流れ

@dataclass
class ProgressEvent:
    """進捗通知。GUI や別の UI から購読できるよう、表示に必要な情報だけを持つ。

    status は "scanned"（走査完了・総数の通知）/ "done" / "skipped" /
    "failed" / "dryrun" のいずれか。
    """
    status: str
    index: int = 0
    total: int = 0
    rel: str = ""
    size: int = 0
    error: str = ""


@dataclass
class MigrationResult:
    copied: int = 0
    skipped: int = 0
    already_done: int = 0   # skipped のうち、台帳で処理済みだったもの
    sources_removed: int = 0  # skipped のうち、--move で移行先に同じ内容があり移行元だけ消したもの
    failed: int = 0
    bytes_transferred: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    elapsed: float = 0.0
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.failed == 0 and not self.cancelled


@dataclass
class _Target:
    root: Path   # 指定された移行元（ディレクトリまたはファイル）。台帳の識別に使う
    path: Path   # 転送するファイル
    rel: str     # 移行先からの相対パス
    shown: str   # ログ表示用の名前


def collect_targets(sources: Sequence[Path], dst: Path, filt: FileFilter,
                    log: logging.Logger) -> list[_Target]:
    """複数の移行元から転送対象を集める。

    - ディレクトリは中身を構成ごと、ファイルは移行先直下に送る
    - 同じファイルが複数の指定に含まれる場合は最初の 1 回だけ扱う
    - 別の移行元から同じ移行先パスに来るものがあれば警告する（扱いは --on-exists に従う）
    """
    multi = len(sources) > 1
    targets: list[_Target] = []
    seen: set[str] = set()
    for root in sources:
        base = root.parent if root.is_file() else root
        for f in collect_files(root, dst, filt, log=log):
            key = _root_id(f)
            if key in seen:
                continue
            seen.add(key)
            rel = f.relative_to(base).as_posix()
            targets.append(_Target(root, f, rel, str(f) if multi else rel))

    by_rel: dict[str, list[_Target]] = {}
    for t in targets:
        by_rel.setdefault(os.path.normcase(t.rel), []).append(t)
    dups = [ts for ts in by_rel.values() if len(ts) > 1]
    if dups:
        log.warning("移行先で同じ名前になるファイルが %d 組あります"
                    "（--on-exists に従って処理。両方残すには --on-exists rename）", len(dups))
        for ts in dups:
            log.warning("  %s <- %s", ts[0].rel, ", ".join(str(t.path) for t in ts))
    return targets


def run_migration(src, dst, *,
                  filt: FileFilter | None = None,
                  move: bool = False,
                  verify: bool = True,
                  on_exists: str = "skip",
                  dry_run: bool = False,
                  ledger: Ledger | None = None,
                  log: logging.Logger | None = None,
                  progress: Callable[[ProgressEvent], None] | None = None,
                  should_cancel: Callable[[], bool] | None = None) -> MigrationResult:
    """移行を実行して結果を返す。表示や終了コードは呼び出し側に任せる。

    src: 移行元のパス、またはパスのリスト（ディレクトリ・ファイル混在可）
    move: 移行元を削除する。移行先に同じ内容が既にあるもの（台帳で済・既存）は
          転送せずに移行元だけ削除する（以前にコピーしたものを後から片付けられる）
    progress: 1 ファイルごとに ProgressEvent が渡される（GUI の進捗表示用）
    should_cancel: True を返すと、その時点で安全に中断する
    """
    log = log or LOGGER
    filt = filt or FileFilter()
    ledger = ledger if ledger is not None else Ledger(None)
    sources = [Path(src)] if isinstance(src, (str, os.PathLike)) else [Path(s) for s in src]
    dst = Path(dst)
    emit = progress or (lambda ev: None)

    targets = collect_targets(sources, dst, filt, log)
    total = len(targets)
    log.info("対象 %d 件 / %s", total,
             human(sum(t.path.stat().st_size for t in targets if t.path.exists())))
    emit(ProgressEvent("scanned", index=0, total=total))

    result = MigrationResult()
    started = time.time()

    # この実行で置いた（ドライランなら置く予定の）移行先。同名ファイルが複数あるとき、
    # ドライランでも実際の実行と同じ判定になるようにする。
    placed: set[str] = set()
    exists = lambda p: p.exists() or _root_id(p) in placed  # noqa: E731

    def drop_source(i: int, t: _Target) -> bool:
        """移行先に同じ内容がある移行元を削除する。失敗したら failed として扱い False を返す。"""
        if not dry_run:
            try:
                t.path.unlink()
            except OSError as e:
                result.failed += 1
                result.failures.append((t.shown, str(e)))
                log.error("[%d/%d] 移行元を削除できません %s: %s", i, total, t.shown, e)
                emit(ProgressEvent("failed", i, total, t.rel, error=str(e)))
                return False
        result.sources_removed += 1
        log.info("[%d/%d] %s移行先に同じ内容があるため移行元を削除: %s",
                 i, total, "DRY-RUN " if dry_run else "", t.shown)
        return True

    for i, t in enumerate(targets, 1):
        f, rel, shown = t.path, t.rel, t.shown
        ledger.bind(t.root, dst)  # 台帳は「指定された移行元 → 移行先」ごとに区別する

        if should_cancel is not None and should_cancel():
            result.cancelled = True
            log.warning("中止されました（%d/%d 件目で停止）", i, total)
            break

        if ledger.is_done(rel):
            # 以前にコピーしたものを --move で片付ける。rename された場合は台帳の dest を見る
            copied_to = Path(ledger.get(rel).get("dest") or dst / rel)
            if move and same_content(f, copied_to):
                if not drop_source(i, t):
                    continue
            else:
                log.debug("[%d/%d] 済: %s", i, total, shown)
            result.skipped += 1
            result.already_done += 1
            emit(ProgressEvent("skipped", i, total, rel))
            continue

        if move and same_content(f, dst / rel):
            # 移行先に同じ内容が既にある = 移動済みとみなす（同名で残したり _1 を作ったりしない）
            if drop_source(i, t):
                result.skipped += 1
                ledger.record(rel, "done", dest=str(dst / rel), reason="same_content")
                emit(ProgressEvent("skipped", i, total, rel))
            continue

        dest = resolve_destination(dst / rel, on_exists, exists)
        if dest is None:
            result.skipped += 1
            log.info("[%d/%d] 既存のためスキップ: %s", i, total, shown)
            ledger.record(rel, "skipped", reason="exists")
            emit(ProgressEvent("skipped", i, total, rel))
            continue

        placed.add(_root_id(dest))
        if dry_run:
            result.copied += 1
            log.info("[%d/%d] DRY-RUN %s -> %s", i, total, shown, dest)
            emit(ProgressEvent("dryrun", i, total, rel))
            continue

        try:
            size = f.stat().st_size
            digest = transfer_file(f, dest, move=move, verify=verify)
            result.copied += 1
            result.bytes_transferred += size
            ledger.record(rel, "done", dest=str(dest), size=size, sha256=digest)
            log.info("[%d/%d] OK %s (%s)", i, total, shown, human(size))
            emit(ProgressEvent("done", i, total, rel, size=size))
        except Exception as e:  # 1 件の失敗で全体を止めない
            result.failed += 1
            result.failures.append((shown, str(e)))
            ledger.record(rel, "failed", error=str(e))
            log.error("[%d/%d] 失敗 %s: %s", i, total, shown, e)
            emit(ProgressEvent("failed", i, total, rel, error=str(e)))

    result.elapsed = time.time() - started
    return result


# ================================================================ 重複ファイルの削除

# "name (1).ext" / "name(2).tar.gz" / "name（3）.txt"。stem は最短一致にして、
# "a (1) (2).txt" は "a (1).txt" の 2 番目として扱う
_NUMBERED = re.compile(r"^(?P<stem>.+?) ?[(（]\d+[)）](?P<ext>(?:\.[^.]+)*)$")


def find_duplicates(root: Path) -> list[tuple[Path, Path]]:
    """root 配下で、番号付きのファイル（例: `file (1).txt`）のうち、同じフォルダに
    番号なしのファイル（`file.txt`）があって中身も同じものを (重複, 元) の組で返す。

    元のファイルが無い、または中身が違うものは対象にしない。
    """
    pairs: list[tuple[Path, Path]] = []
    for dirpath, _, filenames in os.walk(root):
        here = Path(dirpath)
        for name in sorted(filenames):
            m = _NUMBERED.match(name)
            if not m:
                continue
            dup, original = here / name, here / (m["stem"] + m["ext"])
            if same_content(dup, original):
                pairs.append((dup, original))
    return pairs


@dataclass
class DedupeResult:
    removed: int = 0
    bytes_freed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def remove_duplicates(root, *, dry_run: bool = False,
                      log: logging.Logger | None = None) -> DedupeResult:
    """find_duplicates() で見つかった重複を削除する。dry_run なら表示だけ。

    削除する組はすべて先に決めてから消すので、`a.txt` / `a (1).txt` / `a (1) (1).txt`
    が同じ中身なら `a.txt` だけが残る。
    """
    log = log or LOGGER
    root = Path(root)
    result = DedupeResult()
    for dup, original in find_duplicates(root):
        shown = dup.relative_to(root).as_posix()
        size = dup.stat().st_size
        if not dry_run:
            try:
                dup.unlink()
            except OSError as e:
                result.failures.append((shown, str(e)))
                log.error("重複ファイルを削除できません %s: %s", shown, e)
                continue
        result.removed += 1
        result.bytes_freed += size
        log.info("%s重複を削除: %s（%s と同じ内容）",
                 "DRY-RUN " if dry_run else "", shown, original.name)
    return result


# ================================================================ CLI

def expand_sources(args: Sequence[str]) -> list[Path]:
    """移行元の指定をパスのリストにする。

    Windows のシェルは * や ? を展開しないため、ここで展開する。
    見つからないものが 1 つでもあれば、何も始める前に ValueError にする。
    """
    sources: list[Path] = []
    missing: list[str] = []
    for a in args:
        p = Path(a)
        if p.exists():
            sources.append(p)
        elif any(c in a for c in "*?["):
            hits = sorted(glob.glob(a, recursive=True))
            if hits:
                sources.extend(Path(h) for h in hits)
            else:
                missing.append(f"{a}（一致するものがありません）")
        else:
            missing.append(a)
    if missing:
        raise ValueError("移行元が見つかりません: " + ", ".join(missing))
    return sources


def setup_logging(log_path: Path | None, verbose: bool) -> None:
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    LOGGER.addHandler(console)

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        LOGGER.addHandler(fh)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ファイル移行バッチ（検証・再開・ドライラン対応）",
        usage="%(prog)s [options] SRC [SRC ...] DST")
    p.add_argument("paths", nargs="+", metavar="SRC... DST",
                   help="移行元（ディレクトリ／ファイル／ワイルドカード、複数可）と、最後に移行先ディレクトリ。"
                        "ディレクトリは中身を構成ごと、ファイルは移行先直下に送る")
    p.add_argument("--move", action="store_true",
                   help="検証成功後に移行元を削除する。移行先に同じ内容が既にあるものも移行元を削除する")
    p.add_argument("--dedupe", action="store_true",
                   help="転送後、移行先で `name (1).ext` のような番号付きファイルが"
                        "番号なしのものと同じ内容なら削除する")
    p.add_argument("--dry-run", action="store_true", help="書き込まずに対象だけ表示する")
    p.add_argument("--on-exists", choices=["skip", "overwrite", "rename"], default="skip",
                   help="移行先に同名ファイルがある場合の動作（既定: skip）")
    p.add_argument("--no-verify", action="store_true", help="SHA-256 の照合を省略する")
    p.add_argument("--ext", help="対象拡張子をカンマ区切りで 例: pdf,xlsx")
    p.add_argument("--exclude", action="append", metavar="GLOB", help="除外 glob（複数可）")
    p.add_argument("--since", help="更新日時の下限 例: 30d, 12h, 2025-04-01")
    p.add_argument("--min-size", help="下限サイズ 例: 1KB")
    p.add_argument("--max-size", help="上限サイズ 例: 500MB")
    p.add_argument("--ledger", type=Path, default=Path("migration_ledger.jsonl"),
                   help="処理台帳のパス（再開に使う）")
    p.add_argument("--restart", action="store_true", help="台帳を無視して最初からやり直す")
    p.add_argument("--log", type=Path, default=Path("migration.log"), help="ログファイル")
    p.add_argument("-v", "--verbose", action="store_true", help="1 件ごとの詳細を出す")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """終了コード: 0=全件成功 / 1=失敗あり / 2=引数エラー・中断"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if len(args.paths) < 2:
        parser.error("移行元と移行先の両方を指定してください")
    setup_logging(args.log, args.verbose)

    dst = Path(args.paths[-1])
    try:
        sources = expand_sources(args.paths[:-1])
    except ValueError as e:
        LOGGER.error("%s", e)
        return 2
    if dst.exists() and not dst.is_dir():
        LOGGER.error("移行先がディレクトリではありません: %s", dst)
        return 2
    for src in sources:
        # ファイルの場合は、そのファイルがあるディレクトリを移行先にすると自分自身に転送してしまう
        src_dir = src if src.is_dir() else src.parent
        if src_dir.resolve() == dst.resolve():
            LOGGER.error("移行元と移行先が同じです: %s", src)
            return 2

    try:
        filt = FileFilter(
            exts=args.ext.split(",") if args.ext else None,
            excludes=args.exclude or (),
            since=parse_since(args.since),
            min_size=parse_size(args.min_size),
            max_size=parse_size(args.max_size),
        )
    except ValueError as e:
        LOGGER.error("%s", e)
        return 2

    ledger = Ledger(None if (args.dry_run or args.restart) else args.ledger)

    LOGGER.info("=" * 60)
    shown_src = str(sources[0]) + (f" ほか {len(sources) - 1} 件" if len(sources) > 1 else "")
    LOGGER.info("移行開始: %s -> %s（%s%s）", shown_src, dst,
                "移動" if args.move else "コピー", "／ドライラン" if args.dry_run else "")

    try:
        result = run_migration(
            sources, dst, filt=filt, move=args.move,
            verify=not args.no_verify, on_exists=args.on_exists,
            dry_run=args.dry_run, ledger=ledger, log=LOGGER)
    except KeyboardInterrupt:
        LOGGER.warning("中断されました。同じコマンドを再実行すると続きから再開します。")
        return 2
    finally:
        ledger.close()

    LOGGER.info("-" * 60)
    LOGGER.info("完了: 成功 %d / スキップ %d / 失敗 %d",
                result.copied, result.skipped, result.failed)
    if result.already_done:
        LOGGER.info("  うち台帳で処理済みとしてスキップ %d 件（最初からやり直すには --restart）",
                    result.already_done)
    if result.sources_removed:
        LOGGER.info("  うち移行先に同じ内容があるため移行元を削除 %d 件", result.sources_removed)
    LOGGER.info("転送量 %s / 所要 %.1f秒", human(result.bytes_transferred), result.elapsed)
    for rel, err in result.failures:
        LOGGER.info("  - 失敗: %s: %s", rel, err)

    dedupe = DedupeResult()
    if args.dedupe and not result.cancelled and dst.is_dir():
        dedupe = remove_duplicates(dst, dry_run=args.dry_run, log=LOGGER)
        LOGGER.info("重複ファイルの削除: %d 件 / %s", dedupe.removed, human(dedupe.bytes_freed))
        for rel, err in dedupe.failures:
            LOGGER.info("  - 失敗: %s: %s", rel, err)

    if args.dry_run:
        LOGGER.info("※ ドライランのため何も書き込んでいません。")

    if result.cancelled:
        return 2
    return 0 if result.failed == 0 and not dedupe.failures else 1


if __name__ == "__main__":
    sys.exit(main())
