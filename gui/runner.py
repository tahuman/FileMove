# -*- coding: utf-8 -*-
"""
GUI と本体（migrate_files）のつなぎ。画面（tkinter）には依存しないので、単体でテストできる。

    form = Form(sources=[...], dest="D:/写真", move=True)
    job = MigrationJob(form, dry_run=False)
    job.start()
    for kind, payload in job.drain():   # 画面側は after() で定期的に呼ぶ
        ...

処理そのものは migrate_files.run_migration() に任せ、ここでは入力の確認と、
別スレッドで動かして結果をキューで画面に渡すことだけを行う。
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

import migrate_files as mf

# 画面の選択肢 -> --on-exists の値
ON_EXISTS = {
    "スキップする（上書きしない）": "skip",
    "番号を付けて両方残す": "rename",
    "上書きする": "overwrite",
}


def default_ledger_path() -> Path:
    """GUI の台帳の置き場所。実行した場所に作ると散らばるので、ユーザーごとのフォルダにまとめる。"""
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / "FileMove" / "migration_ledger.jsonl"


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


def build_options(form: Form) -> dict:
    """入力を確かめて run_migration() に渡す引数にする。問題があれば ValueError（画面にそのまま出す文言）。"""
    if not form.sources:
        raise ValueError("移行元を追加してください")
    missing = [str(p) for p in form.sources if not p.exists()]
    if missing:
        raise ValueError("移行元が見つかりません: " + ", ".join(missing))
    if not form.dest.strip():
        raise ValueError("移行先のフォルダを選んでください")
    dst = Path(form.dest.strip())
    mf.check_paths(form.sources, dst)
    try:
        filt = mf.make_filter(ext=form.exts, since=form.since)
    except ValueError as e:   # 本体の文言は CLI のオプション名なので、画面の項目名に直す
        raise ValueError(str(e).replace("--since ", "期間")) from None
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
        ledger = mf.Ledger(None if self.dry_run else self.ledger_path)
        log.info("%s", mf.start_message(self.options["src"], self.options["dst"],
                                        move=self.options["move"], dry_run=self.dry_run))
        try:
            result = mf.run_migration(**self.options, dry_run=self.dry_run, ledger=ledger, log=log,
                                      progress=lambda ev: self.events.put(("progress", ev)),
                                      should_cancel=self._cancel.is_set)
            self.events.put(("finished", result))
        except Exception as e:  # 想定外のエラーも画面に出して、ボタンを戻せるようにする
            self.events.put(("error", str(e)))
        finally:
            ledger.close()
            log.removeHandler(handler)


def summary(result: mf.MigrationResult, dry_run: bool) -> str:
    """完了したときに画面に出す 1〜2 行。"""
    head = "中止しました" if result.cancelled else "確認しました（ドライラン）" if dry_run else "完了しました"
    text = f"{head}: 成功 {result.copied} / スキップ {result.skipped} / 失敗 {result.failed}"
    extra = []
    if result.sources_removed:
        extra.append(f"元だけ削除 {result.sources_removed}")
    if result.dedupe and result.dedupe.removed:
        extra.append(f"重複を削除 {result.dedupe.removed}")
    if extra:
        text += "（" + "、".join(extra) + "）"
    if dry_run:
        text += "\n※ ドライランのため、まだ何も書き込んでいません。よければ「実行」を押してください。"
    return text
