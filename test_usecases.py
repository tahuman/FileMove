#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ユースケースのテスト（システムテスト）。GUI を人と同じ順に操作して、最後の状態まで確かめる。

    python -m pytest test_usecases.py

単体テスト（test_migrate_files.py / test_gui.py）が部品ごとの振る舞いを見るのに対して、こちらは
「ダウンロードを整理する」のような使い方を 1 つずつ通しで行い、次をまとめて確かめる。
  - フォルダの中身（どこに何が残ったか。移したファイルは中身まで元と同じか）
  - 画面（結果の見出し・一覧・対象フォルダの一覧）
  - 保存した結果（CSV・ログ）
ユースケースの一覧と、自動では確かめられない「人が確かめること」は docs/gui/USECASES.md にまとめている。

テスト網羅:
  - [UC1] ダウンロードの整理（既定の設定）: 構成を保って移動し、重複・空のフォルダを消し、システムのファイルは残す
  - [UC2] コピーでバックアップ: 元は変えずに同じ中身を作り、もう一度行っても何も増えない
  - [UC3] 保存先に同じ名前のファイルがある: 連番を付けて保存・スキップ・上書きのそれぞれの結果。
          全部がスキップになるときも、確認でその理由が分かり、言われたとおりに変えれば移せる（UC3b）
  - [UC4] PDF だけを移す（種類で絞る）: ほかのファイルは残り、対象フォルダも一覧に残る
  - [UC5] 最近のファイルだけを移す（期間で絞る）
  - [UC6] 複数のフォルダを 1 か所にまとめる: 同じ名前は両方残る
  - [UC7] 確認の後にファイルが増えた・設定を変えた: 確認したものだけを移す／確認をやり直させる
  - [UC8] 途中で中止して、後で続きを行う: 二重に移さず、最後には全部そろう
  - [UC9] 開いている（使用中の）ファイルがある: そのファイルだけエラーで元に残り、閉じた後に移せる
  - [UC10] 読み取り専用・日本語・空白・絵文字・深い階層のファイルも、そのまま移せる
  - [UC11] 入力の誤り（保存先が対象フォルダと同じ・対象フォルダが消えた）: 何もせずに知らせる。保存先が無ければ作る
  - [UC12] 対象フォルダの中のフォルダに整理する: 移した先をもう一度移さない（何度行っても入れ子にならない）
"""

from __future__ import annotations

import csv
import hashlib
import os
import stat
import sys
import time
from pathlib import Path

import pytest

import migrate_files as mf

DAY = 86400


# ================================================================ 準備

@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("画面を開けない環境")
    root.withdraw()
    yield root
    root.destroy()


def put(base: Path, files: dict[str, str], *, age_days: float = 0) -> dict[str, str]:
    """base の下にファイルを作り、{相対パス: 中身のハッシュ} を返す。"""
    for rel, body in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        if age_days:
            t = time.time() - age_days * DAY
            os.utime(p, (t, t))
    return {rel: hashlib.sha256(body.encode("utf-8")).hexdigest() for rel, body in files.items()}


def tree(base: Path) -> dict[str, str]:
    """base の下のファイルを {相対パス: 中身のハッシュ} にする（無ければ空）。"""
    if not base.exists():
        return {}
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in base.rglob("*") if p.is_file()}


def dirs(base: Path) -> set[str]:
    return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_dir()}


class User:
    """人と同じ順に画面を操作する。"""

    def __init__(self, root, tmp_path: Path):
        from gui.app import App
        self.confirms: list[str] = []
        self.app = App(root, ledger_path=tmp_path / "appdata" / "ledger.jsonl",
                       report_dir=tmp_path / "appdata" / "履歴",
                       confirm=lambda title, msg: self.confirms.append(msg) or True, opener=lambda p: None)

    # ---- ① ～ ④
    def add(self, *folders: Path) -> "User":
        for f in folders:
            assert self.app.add_source(f), f
        return self

    def dest(self, folder: Path) -> "User":
        self.app.set_dest(folder)
        return self

    def copy(self) -> "User":
        self.app.move_var.set(False)
        return self

    def same_name(self, label: str) -> "User":
        self.app.on_exists_var.set(label)
        return self

    def kinds(self, text: str) -> "User":
        self.app.exts_var.set(text)
        return self

    def since(self, text: str) -> "User":
        self.app.since_var.set(text)
        return self

    # ---- 確認 → 実行
    def check(self) -> "User":
        self.app.start(dry_run=True)
        self.wait()
        return self

    def run(self, *, until=None, timeout: float = 30) -> "User":
        self.app.start(dry_run=False)
        self.wait(until=until, timeout=timeout)
        return self

    def wait(self, *, until=None, timeout: float = 30) -> None:
        """実行が終わるまで画面を動かす。until が真になったら、そこで一度返す（中止の操作のため）。"""
        app, end = self.app, time.time() + timeout
        while app.job and (app.job.running or not app.job.events.empty()
                           or app.cancel_btn.instate(["!disabled"])):
            app.root.update()
            if until and until():
                return
            assert time.time() < end, "終わらない"
            time.sleep(0.01)
        app.root.update()

    # ---- 見えているもの
    @property
    def title(self) -> str:
        return self.app.last_outcome.title

    @property
    def level(self) -> str:
        return self.app.last_outcome.level

    def rows(self, state: str | None = None) -> list[str]:
        return sorted(r.name for r in self.app.rows if state is None or r.state == state)

    def can_run(self) -> bool:
        return self.app.run_btn.instate(["!disabled"])

    def list_shown(self) -> bool:
        return self.app.tabs.winfo_manager() == "grid"

    def sources_shown(self) -> list[str]:
        return [p.name for p in self.app.sources]

    def report(self) -> list[list[str]]:
        with open(self.app.last_report[0], encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))[1:]

    def log(self) -> str:
        return self.app.last_report[1].read_text(encoding="utf-8")


@pytest.fixture
def user(tk_root, tmp_path):
    return User(tk_root, tmp_path)


# ================================================================ ユースケース

def test_UC1_tidy_downloads(user, tmp_path):
    downloads, desktop = tmp_path / "Downloads", tmp_path / "Desktop" / "整理"
    moved = put(downloads, {"見積書.pdf": "見積", "請求書_10月.pdf": "請求", "IMG_0001.jpg": "写真1",
                            "資料/議事録.docx": "議事録", "資料/2025/売上.xlsx": "売上"})
    dup = put(downloads, {"IMG_0001 (1).jpg": "写真1"})                     # 同じ写真を 2 回ダウンロード
    kept = put(downloads, {"desktop.ini": "[.ShellClassInfo]", "~$売上.xlsx": "lock", "setup.exe.crdownload": "途中"})

    user.add(downloads).dest(desktop).check()
    assert user.title == "確認: 6 件を移動します（まだ何も変えていません）"
    assert tree(desktop) == {} and tree(downloads) == {**moved, **dup, **kept}   # 確認では何も変えない
    assert user.can_run()

    user.run()
    assert user.level == "ok" and user.title == "完了: 6 件を移動しました"
    assert "重複を削除 1 件" in user.app.last_outcome.detail
    assert tree(desktop) == moved                                                  # 構成も中身もそのまま
    assert tree(downloads) == kept and dirs(downloads) == set()                    # 空のフォルダも消える
    assert user.sources_shown() == [] and not user.list_shown()                    # 一覧は閉じて保存される
    assert len(user.report()) == 7 and "完了しました: 成功 6" in user.log()
    assert user.confirms == ["確認した 6 件を移動します。\n保存先で中身を確かめた後に、元のファイルを削除します。実行しますか？"]
    assert not user.can_run()                                                      # 次はまた確認から


def test_UC2_backup_by_copy(user, tmp_path):
    photos, backup = tmp_path / "写真", tmp_path / "USB" / "写真のバックアップ"
    files = put(photos, {"2025/旅行/001.jpg": "a", "2025/旅行/002.jpg": "b", "2026/家族.png": "c"})

    user.add(photos).dest(backup).copy().check().run()
    assert user.title == "完了: 3 件をコピーしました"
    assert tree(photos) == files and tree(backup) == files
    assert user.sources_shown() == ["写真"]                                        # コピーなので一覧に残る
    assert user.confirms == []                                                     # コピーは消さないので確かめない

    user.check()                                                                   # 同じことをもう一度
    assert user.title == "コピーするファイルはありません"
    assert set(user.rows("✔ 処理済み")) == set(files)
    assert tree(backup) == files


def test_UC3_same_name_in_dest(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    put(dst, {"メモ.txt": "前からあるメモ", "見積書.pdf": "見積"})

    # 連番を付けて保存（既定）: 別の中身は両方残す。同じ中身なら元だけ消す
    put(src, {"メモ.txt": "新しいメモ", "見積書.pdf": "見積"})
    user.add(src).dest(dst).check().run()
    assert user.title == "完了: 2 件を移動しました"
    assert tree(dst) == put(tmp_path / "expect1", {"メモ.txt": "前からあるメモ", "メモ_1.txt": "新しいメモ",
                                                   "見積書.pdf": "見積"})
    assert tree(src) == {}

    # スキップ: 元は残し、黄色の見出しと一覧で知らせる
    put(src, {"メモ.txt": "もっと新しいメモ", "請求書.pdf": "請求"})
    user.add(src).same_name("スキップ").check().run()
    assert user.level == "warn" and user.title == "1 件を移動しました。1 件はスキップしました"
    assert user.rows("⚠ スキップしました") == ["メモ.txt"] and user.list_shown()
    assert tree(src) == put(tmp_path / "expect2", {"メモ.txt": "もっと新しいメモ"})
    assert (dst / "メモ.txt").read_text(encoding="utf-8") == "前からあるメモ"

    # 上書き: 保存先を新しいものにする
    user.same_name("上書き").check().run()
    assert user.title == "完了: 1 件を移動しました"
    assert (dst / "メモ.txt").read_text(encoding="utf-8") == "もっと新しいメモ" and tree(src) == {}


def test_UC3b_all_skipped(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    put(dst, {"メモ.txt": "前からあるメモ"})
    put(src, {"メモ.txt": "新しいメモ"})

    user.add(src).dest(dst).same_name("スキップ").check()
    assert user.rows("⚠ スキップします") == ["メモ.txt"]
    assert user.level == "warn" and user.title == "1 件は保存先に同名の別ファイルがあるためスキップします"
    assert not user.can_run()                                                      # 移すものが無いので実行はできない

    user.same_name("連番を付けて保存").check().run()                               # 言われたとおりに変える
    assert user.title == "完了: 1 件を移動しました"
    assert set(tree(dst)) == {"メモ.txt", "メモ_1.txt"} and tree(src) == {}


def test_UC4_only_pdf(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "書類"
    pdf = put(src, {"見積書.pdf": "1", "請求/10月.PDF": "2"})
    rest = put(src, {"写真.jpg": "3", "請求/メモ.txt": "4"})

    user.add(src).dest(dst).kinds("pdf").check()
    assert user.rows() == sorted(pdf)
    user.run()
    assert user.title == "完了: 2 件を移動しました"
    assert tree(dst) == pdf and tree(src) == rest
    assert user.sources_shown() == ["Downloads"]                                   # まだファイルが残る


def test_UC5_recent_files_only(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    new = put(src, {"今週.pdf": "new"}, age_days=3)
    old = put(src, {"去年.pdf": "old"}, age_days=400)

    user.add(src).dest(dst).since("30d").check().run()
    assert user.title == "完了: 1 件を移動しました"
    assert tree(dst) == new and tree(src) == old


def test_UC6_merge_folders(user, tmp_path):
    a, b, dst = tmp_path / "PC1" / "書類", tmp_path / "PC2" / "書類", tmp_path / "まとめ"
    put(a, {"報告書.docx": "PC1 の報告書", "a.txt": "a"})
    put(b, {"報告書.docx": "PC2 の報告書", "b.txt": "b"})

    user.add(a, b).dest(dst).check().run()
    assert user.title == "完了: 4 件を移動しました"
    assert tree(dst) == put(tmp_path / "expect", {"報告書.docx": "PC1 の報告書", "報告書_1.docx": "PC2 の報告書",
                                                  "a.txt": "a", "b.txt": "b"})
    assert tree(a) == tree(b) == {} and user.sources_shown() == []


def test_UC7_changes_after_check(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    put(src, {"見積書.pdf": "1"})
    user.add(src).dest(dst).check()

    late = put(src, {"後から.pdf": "2"})                                           # 確認の後にダウンロードした
    user.run()
    assert user.title == "完了: 1 件を移動しました"
    assert set(tree(dst)) == {"見積書.pdf"} and tree(src) == late                  # 確認していないものは移さない
    assert user.sources_shown() == ["Downloads"]

    user.check()
    assert user.can_run()
    user.copy()                                                                    # 確認の後に設定を変えた
    assert not user.can_run() and user.title == "設定が変わりました"
    user.run()                                                                     # 押せない状態で実行しようとしても
    assert user.title == "先に「確認」を押してください" and tree(src) == late


def test_UC8_cancel_and_resume(user, tmp_path, monkeypatch):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    files = put(src, {f"file{i:02}.txt": f"中身{i}" for i in range(20)})
    real = mf.transfer_file

    def slow(*a, **kw):                                                            # 1 件ずつ時間がかかる
        time.sleep(0.05)
        return real(*a, **kw)

    monkeypatch.setattr(mf, "transfer_file", slow)
    user.add(src).dest(dst).check()
    user.run(until=lambda: len(user.app.rows) >= 3)
    user.app.cancel()
    user.wait()
    assert user.level == "warn" and user.title == "中止しました"
    done = tree(dst)
    assert 3 <= len(done) < 20
    assert {**done, **tree(src)} == files                                          # 失われたものも二重のものもない

    user.check()                                                                   # 続きから
    assert user.title == f"確認: {20 - len(done)} 件を移動します（まだ何も変えていません）"
    user.run()
    assert user.title == f"完了: {20 - len(done)} 件を移動しました"
    assert tree(dst) == files and tree(src) == {}


@pytest.mark.skipif(sys.platform != "win32", reason="開いているファイルを消せないのは Windows の振る舞い")
def test_UC9_file_in_use(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    files = put(src, {"開いている.xlsx": "表", "閉じている.pdf": "書類"})

    user.add(src).dest(dst).check()
    with open(src / "開いている.xlsx", "rb"):                                      # Excel などで開いたまま
        user.run()
    assert user.level == "error" and user.title == "1 件でエラーが起きました"
    assert user.rows("✗ エラー") == ["開いている.xlsx"] and user.list_shown()
    assert tree(src) == {"開いている.xlsx": files["開いている.xlsx"]}               # 元のまま残る
    assert tree(dst) == {"閉じている.pdf": files["閉じている.pdf"]}                 # 書きかけも残らない

    user.check().run()                                                             # 閉じてからもう一度
    assert user.title == "完了: 1 件を移動しました"
    assert tree(dst) == files and tree(src) == {}


def test_UC10_unusual_files(user, tmp_path):
    src, dst = tmp_path / "Downloads", tmp_path / "Desktop"
    files = put(src, {"読み取り専用.pdf": "ro", "名前 に 空白.txt": "sp", "絵文字🍣.txt": "emoji",
                      "a/b/c/d/e/f/深い階層の長い名前のファイル_" + "あ" * 40 + ".txt": "deep"})
    (src / "読み取り専用.pdf").chmod(stat.S_IREAD)

    user.add(src).dest(dst).check().run()
    assert user.title == "完了: 4 件を移動しました"
    assert tree(dst) == files and tree(src) == {}


def test_UC11_input_mistakes(user, tmp_path):
    src = tmp_path / "Downloads"
    files = put(src, {"見積書.pdf": "1"})

    user.add(src).dest(src).check()                                                # 保存先が対象フォルダと同じ
    assert user.level == "warn" and user.title == "入力を確かめてください"
    assert tree(src) == files

    gone = tmp_path / "消えたフォルダ"
    gone.mkdir()
    user.add(gone)
    gone.rmdir()                                                                   # 追加した後に消された
    user.dest(tmp_path / "まだ無いフォルダ").check()
    assert user.title == "入力を確かめてください" and "消えたフォルダ" in user.app.last_outcome.detail

    user.app.src_list.selection_set(1)
    user.app._remove_selected()
    user.check().run()                                                             # 保存先が無ければ作る
    assert user.title == "完了: 1 件を移動しました"
    assert tree(tmp_path / "まだ無いフォルダ") == files


def test_UC12_sort_into_subfolder(user, tmp_path):
    src = tmp_path / "Downloads"
    files = put(src, {"見積書.pdf": "1", "資料/議事録.docx": "2"})

    user.add(src).dest(src / "整理").check().run()
    assert user.title == "完了: 2 件を移動しました"
    assert tree(src) == {f"整理/{k}": v for k, v in files.items()}
    user.check()                                                                   # もう一度行っても
    assert user.title == "移動するファイルはありません"
    assert tree(src) == {f"整理/{k}": v for k, v in files.items()}               # 整理/整理/… にならない
