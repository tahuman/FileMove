# -*- coding: utf-8 -*-
"""
GUI と本体（migrate_files）のつなぎ。画面（tkinter）には依存しないので、単体でテストできる。

    form = Form(sources=[...], dest="D:/写真", move=True)
    job = MigrationJob(form, dry_run=False)
    job.start()
    for kind, payload in job.drain():   # 画面側は after() で定期的に呼ぶ
        ...

処理そのものは migrate_files.run_migration() に任せ、ここでは入力の確認と、
別スレッドで動かして結果をキューで画面に渡すこと、結果を画面の言葉にすること、
結果を保存することだけを行う。
"""

from __future__ import annotations

import csv
import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import migrate_files as mf

# 画面の選択肢 -> --on-exists の値（先頭が画面の既定。中身が同じものは両方残さずスキップする）
ON_EXISTS = {
    "連番を付けて保存": "rename",
    "スキップ": "skip",
    "上書き": "overwrite",
}


def app_dir() -> Path:
    """GUI のデータ（台帳・結果の履歴）の置き場所。実行した場所に作ると散らばるので、ユーザーごとにまとめる。"""
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / "FileMove"


def default_ledger_path() -> Path:
    return app_dir() / "migration_ledger.jsonl"


def default_report_dir() -> Path:
    return app_dir() / "履歴"


@dataclass
class Form:
    """画面で入力された内容。"""
    sources: list[Path] = field(default_factory=list)
    dest: str = ""
    move: bool = False
    on_exists: str = "skip"
    exts: str = ""       # "pdf,jpg"（空ならすべて）
    since: str = ""      # "30d" など（空なら絞らない）
    dedupe: bool = False
    verify: bool = True
    only: frozenset[str] | None = None   # 確認した一覧のファイルだけを対象にする（実行のとき）


def _screen_words(text: str) -> str:
    """本体の文言（CLI の言葉）を画面の項目名に直す。"""
    for cli, screen in (("--since ", "期間"), ("移行元", "対象フォルダ"), ("移行先", "保存先フォルダ")):
        text = text.replace(cli, screen)
    return text


def clean_path(text: str) -> str:
    """貼り付けたパスの前後の空白と "（エクスプローラーの「パスのコピー」で付く）を取る。"""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def build_options(form: Form) -> dict:
    """入力を確かめて run_migration() に渡す引数にする。問題があれば ValueError（画面にそのまま出す文言）。"""
    if not form.sources:
        raise ValueError("対象フォルダを追加してください")
    missing = [str(p) for p in form.sources if not p.exists()]
    if missing:
        raise ValueError("対象フォルダが見つかりません: " + ", ".join(missing))
    files = [str(p) for p in form.sources if not p.is_dir()]
    if files:
        raise ValueError("対象にできるのはフォルダだけです: " + ", ".join(files))
    dest = clean_path(form.dest)
    if not dest:
        raise ValueError("保存先フォルダを選んでください")
    dst = Path(dest)
    if not dst.is_absolute():   # 相対パスだと、GUI を起動したフォルダの中に作られてしまう
        raise ValueError("保存先フォルダは、ドライブからの場所で入れてください（例: C:\\Users\\…\\Desktop）。"
                         "「参照…」で選ぶと確実です")
    try:
        mf.check_paths(form.sources, dst)
        # desktop.ini・Office の一時ファイル・ダウンロード途中のファイルは移さない
        filt = mf.make_filter(ext=form.exts, excludes=mf.SYSTEM_EXCLUDES, since=form.since, only=form.only)
    except ValueError as e:
        raise ValueError(_screen_words(str(e))) from None
    return dict(src=list(form.sources), dst=dst, filt=filt, move=form.move,
                on_exists=form.on_exists, dedupe=form.dedupe, verify=form.verify)


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__(logging.INFO)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", record.getMessage()))


class MigrationJob:
    """run_migration() を別スレッドで動かし、ログ・進捗・結果をキューに積む。

    キューに積むもの: ("log", 文字列) / ("progress", ProgressEvent) /
    ("finished", MigrationResult) / ("error", 例外の文言)
    """

    def __init__(self, form: Form, *, dry_run: bool, ledger_path: Path | None = None):
        self.options = build_options(form)   # 開始前に入力を確かめる（ValueError）
        self.dry_run = dry_run
        self.ledger_path = ledger_path or default_ledger_path()
        self.events: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        """今のファイルが終わったところで止める（途中のファイルは .part を残さず片付く）。"""
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def drain(self) -> list[tuple[str, object]]:
        """これまでに積まれたものを取り出す（画面のスレッドから呼ぶ）。"""
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def _run(self) -> None:
        log = mf.LOGGER
        handler = _QueueHandler(self.events)
        log.addHandler(handler)
        if log.level == logging.NOTSET or log.level > logging.INFO:
            log.setLevel(logging.INFO)
        try:
            ledger = mf.Ledger(None if self.dry_run else self.ledger_path)
        except OSError as e:   # 台帳を開けない（別の FileMove が使っている、権限が無いなど）
            self.events.put(("error", f"記録ファイル（台帳）を開けません: {e}"))
            log.removeHandler(handler)
            return
        log.info("%s", mf.start_message(self.options["src"], self.options["dst"],
                                        move=self.options["move"], dry_run=self.dry_run))
        try:
            result = mf.run_migration(**self.options, dry_run=self.dry_run, ledger=ledger, log=log,
                                      progress=lambda ev: self.events.put(("progress", ev)),
                                      should_cancel=self._cancel.is_set)
            log.info("%s", summary(result, self.dry_run))
            self.events.put(("finished", result))
        except Exception as e:  # 想定外のエラーも画面に出して、ボタンを戻せるようにする
            self.events.put(("error", str(e)))
        finally:
            ledger.close()
            log.removeHandler(handler)


# ---------------------------------------------------------------- 結果の見せ方（画面に依存しない）

@dataclass
class Row:
    """結果の一覧の 1 行。tag は色分け（ok / plan / muted / warn / error）。"""
    state: str
    name: str
    note: str
    tag: str


def describe(ev: mf.ProgressEvent, *, move: bool, dry_run: bool,
             display: Callable[[str], str] = lambda s: s) -> Row | None:
    """進捗の通知を、結果の一覧の 1 行にする（scanned は行にしない）。"""
    verb = "移動" if move else "コピー"
    dest = display(ev.dest)
    if ev.status == "done":
        return Row(f"✔ {verb}しました", ev.rel, dest, "ok")
    if ev.status == "dryrun":
        return Row(f"→ {verb}します", ev.rel, dest, "plan")
    if ev.status == "removed":
        return Row("→ 元を削除します" if dry_run else "✔ 移動しました", ev.rel,
                   f"{dest}（同じファイルが既にあるため、元だけ削除）", "plan" if dry_run else "ok")
    if ev.status == "skipped" and ev.reason == "exists":
        return Row("⚠ スキップします" if dry_run else "⚠ スキップしました", ev.rel,
                   "保存先に同名の別ファイルがあります（元のファイルはそのまま）", "warn")
    if ev.status == "skipped":
        why = "前回までに処理済み" if ev.reason == "done" else "同じファイルが保存先に既にあります"
        return Row("✔ 処理済み", ev.rel, f"{dest}（{why}）", "muted")
    if ev.status == "failed":
        return Row("✗ エラー", ev.rel, ev.error, "error")
    return None


def dedupe_rows(result: mf.MigrationResult, *, dry_run: bool, root: Path,
                display: Callable[[str], str] = lambda s: s) -> list[Row]:
    """重複の削除の結果を、一覧の行にする。"""
    if not result.dedupe:
        return []
    rows = [Row("→ 重複を削除します" if dry_run else "✔ 重複を削除しました", _rel(p, root),
                display(str(p)), "plan" if dry_run else "ok") for p in result.dedupe.paths]
    rows += [Row("✗ エラー", name, err, "error") for name, err in result.dedupe.failures]
    return rows


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


@dataclass
class Outcome:
    """終わったときに結果の欄に大きく出す内容。level は ok / info / warn / error。"""
    level: str
    title: str
    detail: str


def outcome(result: mf.MigrationResult, *, dry_run: bool, move: bool, kept: int = 0) -> Outcome:
    """結果を、ひと目で分かる見出しと説明にする。kept は同名の別ファイルがあるためスキップした数。"""
    verb = "移動" if move else "コピー"
    done = result.copied + result.sources_removed
    extra = []
    if result.dedupe and result.dedupe.removed:
        extra.append(f"重複を{'削除予定' if dry_run else '削除'} {result.dedupe.removed} 件")
    if result.dirs_removed:
        extra.append(f"空になったフォルダを削除 {len(result.dirs_removed)} 件")
    if result.already_done:
        extra.append(f"前回までに処理済み {result.already_done} 件")
    tail = "（" + "、".join(extra) + "）" if extra else ""

    if result.cancelled:
        return Outcome("warn", "中止しました",
                       f"{done} 件を{verb}したところで止めました。もう一度「確認」から行うと、続きから処理します。")
    if dry_run:
        if not done and not (result.dedupe and result.dedupe.removed):
            if kept:   # 全部が同名のためスキップになる
                return Outcome("warn", f"{kept} 件は保存先に同名の別ファイルがあるためスキップします",
                               f"{verb}するファイルはありません。両方残すには「同名ファイルの処理」を"
                               "「連番を付けて保存」に、保存先のものを置き換えるには「上書き」にして、"
                               "もう一度「確認」を押してください。")
            return Outcome("info", f"{verb}するファイルはありません",
                           "対象フォルダが空か、種類・期間の条件に合うファイルがないか、すべて処理済みです。")
        kept_note = f"{kept} 件は保存先に同名の別ファイルがあるためスキップします。" if kept else ""
        return Outcome("info", f"確認: {done} 件を{verb}します（まだ何も変えていません）",
                       f"一覧で内容を確かめてから「実行」を押してください{tail}。{kept_note}")
    failed = result.failed + (len(result.dedupe.failures) if result.dedupe else 0)
    if failed:
        return Outcome("error", f"{failed} 件でエラーが起きました",
                       f"{done} 件は{verb}しました{tail}。赤い行に原因が出ています。"
                       "原因を取り除いてから、もう一度「確認」から行ってください。")
    if kept:
        return Outcome("warn", f"{done} 件を{verb}しました。{kept} 件はスキップしました",
                       f"保存先に同名の別ファイルがあるためです{tail}。両方残すには、"
                       "「同名ファイルの処理」を「連番を付けて保存」にしてください。")
    return Outcome("ok", f"完了: {done} 件を{verb}しました", "、".join(extra))


def summary(result: mf.MigrationResult, dry_run: bool) -> str:
    """件数の 1 行（ログの最後に出す）。"""
    head = "中止しました" if result.cancelled else "確認しました（ドライラン）" if dry_run else "完了しました"
    text = f"{head}: 成功 {result.copied} / スキップ {result.skipped} / 失敗 {result.failed}"
    extra = []
    if result.sources_removed:
        extra.append(f"元だけ削除 {result.sources_removed}")
    if result.dedupe and result.dedupe.removed:
        extra.append(f"重複を削除 {result.dedupe.removed}")
    if result.dirs_removed:
        extra.append(f"空のフォルダを削除 {len(result.dirs_removed)}")
    if extra:
        text += "（" + "、".join(extra) + "）"
    if dry_run:
        text += "\n※ ドライランのため、まだ何も書き込んでいません。"
    return text


def save_report(rows: Iterable[Row], log_text: str, directory: Path, *, move: bool,
                now: datetime | None = None) -> tuple[Path, Path]:
    """結果の一覧（CSV。Excel で開ける）とログ（テキスト）を保存し、そのパスを返す。

    名前は「20261026_221500_移動_結果.csv」「…_ログ.txt」。同じ秒に保存したら _2, _3 … を付ける。
    """
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}_{'移動' if move else 'コピー'}"
    stem, i = base, 1
    while (directory / f"{stem}_結果.csv").exists() or (directory / f"{stem}_ログ.txt").exists():
        i += 1
        stem = f"{base}_{i}"
    csv_path, log_path = directory / f"{stem}_結果.csv", directory / f"{stem}_ログ.txt"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:   # BOM 付きなら Excel で文字化けしない
        w = csv.writer(f)
        w.writerow(["状態", "ファイル", "保存先・理由"])
        w.writerows([r.state, r.name, r.note] for r in rows)
    log_path.write_text(log_text, encoding="utf-8")
    return csv_path, log_path
