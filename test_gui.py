# -*- coding: utf-8 -*-
"""
GUI（gui/）のテスト（pytest）

実行:
    python -m pytest test_gui.py

画面を開くテスト（W）は、ウィンドウを隠したまま tkinter を動かす。画面の無い環境では skip する。
exe のテスト（X）は、dist/FileMove.exe があるときだけ動かす（python tools/build_exe.py で作る）。

テスト網羅:
  入力の確認（gui/runner.py の build_options）
    - [U1] 正しい入力を run_migration() の引数にする（拡張子・期間・移動・同名時・重複削除・確認した一覧）。
           保存先フォルダの前後の空白と "（エクスプローラーの「パスのコピー」）は取る
    - [U2] 対象フォルダなし・見つからない・フォルダでない、保存先フォルダなし・ファイル・対象と同じ・相対パス、
           期間の書式違いは、画面に出す文言の ValueError（CLI の言葉ではなく画面の項目名で出す）
  実行（gui/runner.py の MigrationJob）
    - [U3] 別スレッドで実行し、ログ・進捗（scanned から順に）・結果がキューに届く。台帳は指定した場所に作られる
    - [U4] 中止すると、今のファイルの後で止まり、結果に cancelled が立つ
    - [U5] ドライランは何も書き込まず、台帳も作らない。summary() にドライランの案内が入る
    - [U6] 台帳を開けないとき（別の FileMove が使っているなど）は、落ちずに error を積む
  結果の見せ方と保存（gui/runner.py の describe / dedupe_rows / outcome / save_report）
    - [U7] 進捗の通知を一覧の行（状態・保存先・理由・色）にする。移動／コピー、確認、
           処理済み・同名でスキップ・エラー・重複の削除をそれぞれ区別する
    - [U8] 結果の見出し: 完了・確認・スキップあり・エラーあり・中止・対象なしを、色（level）と文言で分ける
    - [U9] 結果の一覧（BOM 付き CSV。Excel で開ける）とログを日時の名前で保存する。同じ秒なら _2 を付ける
  画面（gui/app.py）
    - [W1] 対象フォルダを追加（同じもの 1 回・ファイルは追加しない）・外す、保存先フォルダを入れて、確認 → 実行で
           移動と重複削除まで終わる。確認の前は「実行」を押せない。終わると見出し・太い進捗バー・件数が更新され、
           一覧とログは閉じて保存される。空になった対象フォルダは一覧から外れ、「保存先を開く」「結果を開く」が使える。
           実行の後は、また確認からになる
    - [W2] 入力に問題があると実行せずに見出しで知らせる。確認の前に実行しようとしても実行しない。
           移動は確認の画面で「いいえ」なら実行しない。「確認」は確認の画面を出さず、何も書き込まない
    - [W3] 表示用のパス変換（display / parse）が、対象フォルダ・保存先フォルダ・結果の一覧・ログに効く
    - [W4] 同名の別ファイルがあってスキップしたものは、黄色の行と「スキップしました」の見出しで分かり、
           一覧は閉じない（移動でも元は消さない）
    - [W5] ドラッグ＆ドロップされたもの（"{空白 入り} 普通" の形）のうち、フォルダだけを対象フォルダに入れる。
           保存先フォルダには、ファイルが落とされたらそのフォルダを入れる
    - [W6] 実行中にウィンドウを閉じようとすると確かめ、「はい」なら中止して終わってから閉じる。「いいえ」なら続ける
    - [W7] 既定は 移動・連番を付けて保存・重複の削除オン で、詳細設定は最初から出ている。確認の後に設定や
           対象フォルダを変えると「実行」は押せなくなり、もう一度確認すると押せる
    - [W8] 実行するのは確認した一覧のファイルだけ。確認の後に増えたファイルは移さない
    - [W9] 結果を保存できなくても、移動の結果はそのまま出し、保存できなかったことを知らせる
    - [W10] 画面の処理で想定外のエラーが起きても落ちず、見出しに出して error.log に記録する
    - [W11] 自己診断（self_test。exe の確認用）が、確認 → 実行まで通って 0 を返す
    - [W13] desktop.ini・Office の一時ファイル・ダウンロード途中のファイルは、一覧にも出さず移さない。
           それだけが残ったフォルダは空とみなして対象フォルダの一覧から外す
    - [W14] 500 件（30 フォルダ）でも、確認 → 実行が固まらずに終わり、一覧・保存した結果も 500 件そろう
  GUI のデモ（demo/gui/demo_gui.py）
    - [W12] 全パターン（G1〜G6）を録画せずに動かし、それぞれ期待どおりのファイルの状態になる
  exe（tools/build_exe.py で作った dist/FileMove.exe）
    - [X1] exe の自己診断（--self-test）が正常に終わる（見た目・ドラッグ＆ドロップのライブラリも入っている）
    - [X2] exe に自己署名の証明書（CN=FileMove (self-signed)）で署名されていて、署名の後に書き換わっていない
"""

from __future__ import annotations

import csv
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

import migrate_files as mf
from gui.runner import (ON_EXISTS, Form, MigrationJob, Row, build_options, dedupe_rows, describe, outcome,
                        save_report, summary)

ROOT = Path(__file__).resolve().parent


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    """ダウンロードに 4 ファイル（うち 1 つは (1) 付きの重複）。"""
    d = tmp_path / "Downloads"
    d.mkdir()
    for name, body in {"見積書.pdf": "pdf", "売上.xlsx": "xlsx", "IMG_0001.jpg": "jpg",
                       "IMG_0001 (1).jpg": "jpg"}.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


def _wait(job: MigrationJob) -> list[tuple[str, object]]:
    job.join(10)
    assert not job.running
    return job.drain()


# ================================================================ 入力の確認

def test_U1_build_options(downloads, tmp_path):
    form = Form(sources=[downloads], dest=f'  "{tmp_path / "Desktop"}" ', move=True, on_exists="rename",
                exts="pdf, jpg", since="30d", dedupe=True, only=frozenset([str(downloads / "見積書.pdf")]))

    opts = build_options(form)

    assert opts["src"] == [downloads]
    assert opts["dst"] == tmp_path / "Desktop"
    assert (opts["move"], opts["on_exists"], opts["dedupe"], opts["verify"]) == (True, "rename", True, True)
    assert opts["filt"].exts == {"pdf", "jpg"}
    assert opts["filt"].since is not None
    assert opts["filt"].only == {mf._path_id(downloads / "見積書.pdf")}
    assert build_options(Form(sources=[downloads], dest=str(tmp_path / "x")))["filt"].only is None


@pytest.mark.parametrize("change, message", [
    (dict(sources=[]), "対象フォルダを追加してください"),
    (dict(sources=["missing"]), "対象フォルダが見つかりません"),
    (dict(sources=["file"]), "対象にできるのはフォルダだけです"),
    (dict(dest="  "), "保存先フォルダを選んでください"),
    (dict(dest='""'), "保存先フォルダを選んでください"),
    (dict(dest="file"), "保存先フォルダがディレクトリではありません"),
    (dict(dest="same"), "対象フォルダと保存先フォルダが同じです"),
    (dict(dest="整理"), "保存先フォルダは、ドライブからの場所で入れてください"),
    (dict(since="あした"), "^期間の書式が不正です"),
])
def test_U2_build_options_errors(downloads, tmp_path, change, message):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    values = {"sources": [downloads], "dest": str(tmp_path / "Desktop"), **change}
    values["sources"] = [{"missing": tmp_path / "nope", "file": tmp_path / "file.txt"}.get(s, s)
                         for s in values["sources"]]
    values["dest"] = {"file": str(tmp_path / "file.txt"), "same": str(downloads)}.get(values["dest"], values["dest"])

    with pytest.raises(ValueError, match=message):
        build_options(Form(**values))


# ================================================================ 実行

def test_U3_job_runs_in_thread(downloads, tmp_path):
    ledger = tmp_path / "data" / "ledger.jsonl"
    job = MigrationJob(Form(sources=[downloads], dest=str(tmp_path / "Desktop"), move=True, dedupe=True),
                       dry_run=False, ledger_path=ledger)

    job.start()
    items = _wait(job)

    kinds = [k for k, _ in items]
    assert kinds[-1] == "finished" and "log" in kinds
    progress = [p.status for k, p in items if k == "progress"]
    assert progress == ["scanned", "done", "done", "done", "done"]
    result = items[-1][1]
    assert (result.copied, result.dedupe.removed, result.ok) == (4, 1, True)
    assert sorted(p.name for p in (tmp_path / "Desktop").iterdir()) == ["IMG_0001.jpg", "売上.xlsx", "見積書.pdf"]
    assert not any(downloads.iterdir())
    assert ledger.exists()


def test_U4_job_cancel(downloads, tmp_path, monkeypatch):
    job = MigrationJob(Form(sources=[downloads], dest=str(tmp_path / "Desktop")), dry_run=False,
                       ledger_path=tmp_path / "ledger.jsonl")
    real = mf.transfer_file

    def slow_then_cancel(*a, **kw):
        job.cancel()             # 1 件目の途中で中止ボタンが押された
        return real(*a, **kw)
    monkeypatch.setattr(mf, "transfer_file", slow_then_cancel)

    job.start()
    result = _wait(job)[-1][1]

    assert result.cancelled and result.copied == 1
    assert "中止しました" in summary(result, dry_run=False)


def test_U5_job_dry_run(downloads, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    job = MigrationJob(Form(sources=[downloads], dest=str(tmp_path / "Desktop"), dedupe=True),
                       dry_run=True, ledger_path=ledger)

    job.start()
    result = _wait(job)[-1][1]

    assert (result.copied, result.dedupe.removed) == (4, 1)
    assert not (tmp_path / "Desktop").exists()
    assert not ledger.exists()
    text = summary(result, dry_run=True)
    assert "確認しました（ドライラン）: 成功 4" in text and "重複を削除 1" in text and "まだ何も書き込んでいません" in text


def test_U6_job_ledger_unavailable(downloads, tmp_path):
    ledger = tmp_path / "ledger_is_a_folder"
    ledger.mkdir()                                     # 開けない台帳
    job = MigrationJob(Form(sources=[downloads], dest=str(tmp_path / "Desktop")), dry_run=False,
                       ledger_path=ledger)

    job.start()
    items = _wait(job)

    assert items[-1][0] == "error" and "記録ファイル（台帳）を開けません" in items[-1][1]
    assert len(list(downloads.iterdir())) == 4


# ================================================================ 結果の見せ方と保存

def _ev(status, reason="", error=""):
    return mf.ProgressEvent(status, 1, 1, "a.txt", dest="D:\\out\\a.txt", reason=reason, error=error)


@pytest.mark.parametrize("ev, move, dry_run, state, tag, note", [
    (_ev("done"), True, False, "✔ 移動しました", "ok", "D:\\out\\a.txt"),
    (_ev("done"), False, False, "✔ コピーしました", "ok", "D:\\out\\a.txt"),
    (_ev("dryrun"), True, True, "→ 移動します", "plan", "D:\\out\\a.txt"),
    (_ev("dryrun"), False, True, "→ コピーします", "plan", "D:\\out\\a.txt"),
    (_ev("removed", "same"), True, False, "✔ 移動しました", "ok", "同じファイルが既にあるため、元だけ削除"),
    (_ev("removed", "same"), True, True, "→ 元を削除します", "plan", "元だけ削除"),
    (_ev("skipped", "exists"), True, False, "⚠ スキップしました", "warn", "同名の別ファイル"),
    (_ev("skipped", "exists"), True, True, "⚠ スキップします", "warn", "同名の別ファイル"),
    (_ev("skipped", "done"), False, False, "✔ 処理済み", "muted", "前回までに処理済み"),
    (_ev("skipped", "same"), False, False, "✔ 処理済み", "muted", "同じファイルが保存先に既にあります"),
    (_ev("failed", error="使用中です"), True, False, "✗ エラー", "error", "使用中です"),
])
def test_U7_describe_rows(ev, move, dry_run, state, tag, note):
    row = describe(ev, move=move, dry_run=dry_run, display=lambda s: s)

    assert (row.state, row.name, row.tag) == (state, "a.txt", tag)
    assert note in row.note
    assert describe(mf.ProgressEvent("scanned", 0, 3), move=True, dry_run=False) is None


def test_U7_dedupe_rows(tmp_path):
    result = mf.MigrationResult(dedupe=mf.DedupeResult(removed=1, paths=[tmp_path / "写真" / "a (1).jpg"],
                                                       failures=[("写真/b (1).jpg", "使用中です")]))

    rows = dedupe_rows(result, dry_run=False, root=tmp_path)

    assert [(r.state, r.name, r.tag) for r in rows] == [("✔ 重複を削除しました", "写真/a (1).jpg", "ok"),
                                                        ("✗ エラー", "写真/b (1).jpg", "error")]
    assert dedupe_rows(result, dry_run=True, root=tmp_path)[0].state == "→ 重複を削除します"
    assert dedupe_rows(mf.MigrationResult(), dry_run=False, root=tmp_path) == []


@pytest.mark.parametrize("fields, kw, level, title, detail", [
    (dict(copied=8, sources_removed=1, dirs_removed=[Path("x")]), dict(move=True), "ok",
     "完了: 9 件を移動しました", "空になったフォルダを削除 1 件"),
    (dict(copied=3), dict(move=False, dry_run=True), "info",
     "確認: 3 件をコピーします（まだ何も変えていません）", "一覧で内容を確かめてから「実行」を押してください"),
    (dict(copied=3, skipped=1), dict(move=True, dry_run=True, kept=1), "info",
     "確認: 3 件を移動します（まだ何も変えていません）", "1 件は保存先に同名の別ファイルがあるためスキップします"),
    (dict(), dict(move=True, dry_run=True), "info", "移動するファイルはありません", "すべて処理済み"),
    (dict(copied=2, skipped=1), dict(move=True, kept=1), "warn",
     "2 件を移動しました。1 件はスキップしました", "「連番を付けて保存」"),
    (dict(copied=2, failed=1), dict(move=True), "error", "1 件でエラーが起きました", "赤い行"),
    (dict(copied=1, cancelled=True), dict(move=True), "warn", "中止しました", "続きから"),
    (dict(skipped=3, already_done=3), dict(move=False), "ok", "完了: 0 件をコピーしました", "前回までに処理済み 3 件"),
])
def test_U8_outcome(fields, kw, level, title, detail):
    o = outcome(mf.MigrationResult(**fields), **{"dry_run": False, **kw})

    assert (o.level, o.title) == (level, title)
    assert detail in o.detail


def test_U9_save_report(tmp_path):
    rows = [Row("✔ 移動しました", "見積書.pdf", "C:\\out\\見積書.pdf", "ok"),
            Row("⚠ スキップしました", "メモ, 下書き.txt", "保存先に同名の別ファイルがあります", "warn")]
    now = datetime(2026, 10, 26, 22, 15, 0)

    csv_path, log_path = save_report(rows, "1 行目\n2 行目\n", tmp_path / "履歴", move=True, now=now)
    again, _ = save_report(rows, "", tmp_path / "履歴", move=False, now=now)
    third, _ = save_report(rows, "", tmp_path / "履歴", move=True, now=now)

    assert csv_path.name == "20261026_221500_移動_結果.csv" and log_path.name == "20261026_221500_移動_ログ.txt"
    assert again.name == "20261026_221500_コピー_結果.csv" and third.name == "20261026_221500_移動_2_結果.csv"
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")          # BOM 付き（Excel で文字化けしない）
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        assert list(csv.reader(f)) == [["状態", "ファイル", "保存先・理由"],
                                       ["✔ 移動しました", "見積書.pdf", "C:\\out\\見積書.pdf"],
                                       ["⚠ スキップしました", "メモ, 下書き.txt", "保存先に同名の別ファイルがあります"]]
    assert log_path.read_text(encoding="utf-8") == "1 行目\n2 行目\n"


# ================================================================ 画面

@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("画面を開けない環境")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass   # テストの中で閉じた


def _make_app(root, tmp_path, **kw):
    from gui.app import App
    kw.setdefault("report_dir", tmp_path / "履歴")
    return App(root, ledger_path=tmp_path / "ledger.jsonl", **kw)


def _pump(app, timeout: float = 10) -> None:
    """実行が終わるまで画面のイベントを回す。"""
    end = time.time() + timeout
    while app.job and (app.job.running or not app.job.events.empty()
                       or app.cancel_btn.instate(["!disabled"])):
        app.root.update()
        assert time.time() < end, "終わらない"
        time.sleep(0.01)
    app.root.update()


def _preview_and_run(app) -> None:
    app.start(dry_run=True)
    _pump(app)
    assert app.run_btn.instate(["!disabled"]), app.last_outcome
    app.start(dry_run=False)
    _pump(app)


def _rows(app) -> list[tuple[str, str]]:
    return [(r.state, r.name) for r in app.rows]


def _shown(app) -> bool:
    return app.tabs.winfo_manager() == "grid"


def test_W1_app_preview_then_move(tk_root, downloads, tmp_path):
    opened = []
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True, opener=opened.append)
    assert app.add_source(downloads)
    assert not app.add_source(downloads)                       # 同じものは 1 回だけ
    assert not app.add_source(downloads / "見積書.pdf")        # ファイルは追加しない
    assert app.last_outcome.title == "フォルダだけ追加できます"
    other = tmp_path / "Other"
    other.mkdir()
    app.add_source(other)
    app.src_list.selection_set(1)
    app._remove_selected()
    assert app.sources == [downloads] and app.src_list.size() == 1

    app.set_dest(tmp_path / "Desktop")
    assert app.run_btn.instate(["disabled"])                   # 確認の前は押せない
    app.start(dry_run=True)
    _pump(app)
    assert app.last_outcome.title == "確認: 4 件を移動します（まだ何も変えていません）"
    assert _rows(app)[0] == ("→ 移動します", "IMG_0001 (1).jpg") and _rows(app)[-1][0] == "→ 重複を削除します"
    assert app.run_btn.instate(["!disabled"]) and _shown(app)

    app.start(dry_run=False)
    _pump(app)

    assert app.last_result.ok
    assert sorted(p.name for p in (tmp_path / "Desktop").iterdir()) == ["IMG_0001.jpg", "売上.xlsx", "見積書.pdf"]
    assert app.count_var.get() == "4 / 4 件"
    assert (app.progress.value, app.progress.maximum, app.progress.color) == (4, 4, "#0f7b0f")
    o = app.last_outcome
    assert (o.level, o.title) == ("ok", "完了: 4 件を移動しました")
    assert "重複を削除 1 件" in o.detail and "「Downloads」 は空になったので ① から外しました" in o.detail
    assert "結果の一覧とログを保存しました" in o.detail
    assert app.title_var.get() == o.title.replace(" ", "\u00a0")
    assert _rows(app)[-1] == ("✔ 重複を削除しました", "IMG_0001 (1).jpg")
    assert not _shown(app)                                     # 終わったら一覧とログは閉じる
    assert app.sources == [] and app.src_list.size() == 0      # 空になったので一覧から外れる
    assert app.run_btn.instate(["disabled"])                   # 次はまた確認から

    csv_path, log_path = app.last_report
    assert csv_path.parent == tmp_path / "履歴"
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 1 + 5                # 見出し + 移動 4 + 重複の削除 1
    assert "移行開始" in log_path.read_text(encoding="utf-8")
    app.open_btn.invoke()
    app.report_btn.invoke()
    assert opened == [tmp_path / "Desktop", csv_path]


def test_W2_app_input_errors_and_confirm(tk_root, downloads, tmp_path):
    asked = []
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: asked.append(a) or False)

    app.start(dry_run=True)
    assert (app.last_outcome.level, app.last_outcome.detail) == ("warn", "対象フォルダを追加してください")
    assert app.job is None

    app.add_source(downloads)
    app.dest_var.set("整理")                                    # 相対パス
    app.start(dry_run=True)
    assert "ドライブからの場所" in app.last_outcome.detail and app.job is None

    app.set_dest(tmp_path / "Desktop")
    app.start(dry_run=False)                                     # 確認の前に実行しようとした
    assert app.last_outcome.title == "先に「確認」を押してください" and app.job is None

    app.start(dry_run=True)                                      # 「確認」は確認の画面を出さない
    _pump(app)
    assert asked == [] and not (tmp_path / "Desktop").exists()
    assert app.sources == [downloads]                            # 確認だけなら一覧はそのまま
    assert app.open_btn.winfo_manager() == "" and app.last_report is None

    app.start(dry_run=False)                                     # 確認の画面で「いいえ」
    assert len(asked) == 1 and "4 件を移動します" in asked[0][1]
    assert len(list(downloads.iterdir())) == 4


def test_W3_app_display_paths(tk_root, downloads, tmp_path):
    real = str(tmp_path)
    app = _make_app(tk_root, tmp_path,
                    display=lambda s: s.replace(real, "C:\\Users\\user"),
                    parse=lambda s: s.replace("C:\\Users\\user", real))

    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    assert app.src_list.get(0) == "C:\\Users\\user\\Downloads\\"
    assert app.dest_var.get() == "C:\\Users\\user\\Desktop"

    app.move_var.set(False)
    _preview_and_run(app)
    log = app.log_text.get("1.0", "end")
    assert real not in log and "C:\\Users\\user\\Desktop" in log
    notes = [r.note for r in app.rows]
    assert notes and all(n.startswith("C:\\Users\\user\\Desktop\\") for n in notes)
    assert real not in app.last_report[0].read_text(encoding="utf-8-sig")
    assert (tmp_path / "Desktop" / "見積書.pdf").exists()


def test_W4_app_skipped_files_are_visible(tk_root, downloads, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "見積書.pdf").write_text("前からある別の見積書", encoding="utf-8")
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
    app.add_source(downloads)
    app.set_dest(desktop)
    app.dedupe_var.set(False)
    app.on_exists_var.set(next(k for k, v in ON_EXISTS.items() if v == "skip"))

    _preview_and_run(app)

    assert (downloads / "見積書.pdf").exists()                    # 移動でも、スキップしたものは消さない
    assert ("⚠ スキップしました", "見積書.pdf") in _rows(app)
    item = next(i for i in app.tree.get_children() if app.tree.item(i, "values")[1] == "見積書.pdf")
    assert app.tree.item(item, "tags") == ("warn",)
    assert (app.last_outcome.level, app.last_outcome.title) == ("warn", "3 件を移動しました。1 件はスキップしました")
    assert _shown(app)                                             # 見てほしいので一覧は閉じない
    assert app.sources == [downloads]                              # まだ残っているので一覧から外さない


def test_W5_app_drop(tk_root, downloads, tmp_path):
    app = _make_app(tk_root, tmp_path)
    spaced = tmp_path / "新しい フォルダ"
    spaced.mkdir()

    app.drop_sources(f"{{{spaced}}} {downloads.as_posix()} {{{downloads / '見積書.pdf'}}}")
    assert app.sources == [spaced, Path(downloads.as_posix())]     # ファイルは入れない
    assert app.last_outcome.title == "フォルダだけ追加できます"

    app.drop_dest(f"{{{downloads / '見積書.pdf'}}}")              # ファイルならそのフォルダ
    assert app.dest_var.get() == str(downloads)
    app.drop_dest(f"{{{spaced}}}")
    assert app.dest_var.get() == str(spaced)


def test_W6_app_close_while_running(tk_root, downloads, tmp_path, monkeypatch):
    answers = []
    app = _make_app(tk_root, tmp_path, confirm=lambda title, *a: answers.pop(0) if title == "閉じる確認" else True)
    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    app.start(dry_run=True)
    _pump(app)
    real = mf.transfer_file
    started = []

    def slow(*a, **kw):
        started.append(1)
        time.sleep(0.2)
        return real(*a, **kw)
    monkeypatch.setattr(mf, "transfer_file", slow)
    app.start(dry_run=False)
    while not started:
        tk_root.update()

    answers.append(False)                                          # 「いいえ」なら続ける
    app.close()
    assert app.job.running and not app._closing

    answers.append(True)                                           # 「はい」なら中止して閉じる
    app.close()
    end = time.time() + 10
    while True:
        try:
            tk_root.update()
            tk_root.winfo_exists()
        except Exception:
            break                                                  # 閉じた
        assert time.time() < end, "閉じない"
        time.sleep(0.01)
    assert app.last_result.cancelled and app.last_result.copied < 4
    assert not any(p.name.endswith(".part") for p in (tmp_path / "Desktop").iterdir())


def test_W7_app_defaults_and_preview_invalidation(tk_root, downloads, tmp_path):
    app = _make_app(tk_root, tmp_path)
    tk_root.update()
    assert app.move_var.get() is True and app.dedupe_var.get() is True
    assert ON_EXISTS[app.on_exists_var.get()] == "rename"
    assert app.more.winfo_manager() == "grid"                       # 詳細設定は最初から出ている
    assert not hasattr(app, "add_files_btn")                        # ファイルの追加は無い

    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    changes = [lambda: app.copy_radio.invoke(), lambda: app.exts_var.set("pdf"), lambda: app.since_var.set("30d"),
               lambda: app.dedupe_var.set(False), lambda: app.on_exists_var.set("上書き"),
               lambda: app.set_dest(tmp_path / "Other"), lambda: app.add_source(tmp_path)]
    for change in changes:
        app.start(dry_run=True)
        _pump(app)
        assert app.run_btn.instate(["!disabled"])
        change()
        assert app.run_btn.instate(["disabled"]), change
        assert app.last_outcome.title == "設定が変わりました"
        app.start(dry_run=False)                                     # 押されても実行しない
        assert not (tmp_path / "Desktop").exists() and not (tmp_path / "Other").exists()


def test_W8_app_runs_only_previewed_files(tk_root, downloads, tmp_path):
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    app.dedupe_var.set(False)
    app.start(dry_run=True)
    _pump(app)

    (downloads / "後から来た.pdf").write_text("確認の後に増えた", encoding="utf-8")
    app.start(dry_run=False)
    _pump(app)

    assert sorted(p.name for p in downloads.iterdir()) == ["後から来た.pdf"]
    assert len(list((tmp_path / "Desktop").iterdir())) == 4
    assert app.sources == [downloads]                               # まだファイルがあるので外さない


def test_W9_app_report_save_failure(tk_root, downloads, tmp_path):
    blocker = tmp_path / "履歴は作れない"
    blocker.write_text("ファイル", encoding="utf-8")                 # フォルダを作れない場所
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True, report_dir=blocker / "履歴")
    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")

    _preview_and_run(app)

    assert app.last_outcome.level == "ok" and "結果の保存に失敗しました" in app.last_outcome.detail
    assert app.last_report is None and app.report_btn.winfo_manager() == ""
    assert len(list((tmp_path / "Desktop").iterdir())) == 3


def test_W10_app_unexpected_error(tk_root, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    app = _make_app(tk_root, tmp_path)
    app.preview_btn.configure(command=lambda: 1 / 0)

    app.preview_btn.invoke()                                        # Tk の呼び出しの中で例外
    tk_root.update()
    try:
        raise ZeroDivisionError("division by zero")
    except ZeroDivisionError as e:                                 # invoke() は例外をそのまま返すので、Tk と同じ形で渡す
        tk_root.report_callback_exception(type(e), e, e.__traceback__)

    assert app.last_outcome.title == "想定外のエラーが起きました"
    log = (tmp_path / "appdata" / "FileMove" / "error.log").read_text(encoding="utf-8")
    assert "ZeroDivisionError" in log


def test_W11_self_test(tk_root, tmp_path):
    pytest.importorskip("sv_ttk")
    pytest.importorskip("tkinterdnd2")
    from gui.app import self_test
    out = tmp_path / "self_test.txt"

    assert self_test(out) == 0, out.read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8").endswith("結果: 正常\n")


def test_W13_app_keeps_system_files(tk_root, downloads, tmp_path):
    for name in ("desktop.ini", "~$売上.xlsx", "setup.exe.crdownload"):
        (downloads / name).write_text(name, encoding="utf-8")
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")

    app.start(dry_run=True)
    _pump(app)
    assert not any(r.name in ("desktop.ini", "~$売上.xlsx", "setup.exe.crdownload") for r in app.rows)
    app.start(dry_run=False)
    _pump(app)

    assert sorted(p.name for p in downloads.iterdir()) == ["desktop.ini", "setup.exe.crdownload", "~$売上.xlsx"]
    assert sorted(p.name for p in (tmp_path / "Desktop").iterdir()) == ["IMG_0001.jpg", "売上.xlsx", "見積書.pdf"]
    assert app.sources == [] and "「Downloads」 は空になったので" in app.last_outcome.detail


def test_W14_app_many_files(tk_root, tmp_path):
    src = tmp_path / "Downloads"
    for i in range(500):
        d = src / f"フォルダ{i % 30:02}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"ファイル{i:03}.txt").write_text(f"{i}" * 100, encoding="utf-8")
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
    app.add_source(src)
    app.set_dest(tmp_path / "Desktop")

    start = time.time()
    app.start(dry_run=True)
    _pump(app, timeout=60)
    assert len(app.tree.get_children()) == 500
    app.start(dry_run=False)
    _pump(app, timeout=120)

    assert app.last_outcome.title == "完了: 500 件を移動しました"
    assert sum(1 for p in (tmp_path / "Desktop").rglob("*") if p.is_file()) == 500
    assert not src.exists() or not any(src.iterdir())
    with open(app.last_report[0], encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 501
    assert time.time() - start < 120


# ================================================================ GUI のデモ

def _names(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


DEMO_EXPECTED = {   # パターン -> (確かめるフォルダ（ホームから / D:）, そこにあるべきファイル)
    1: [("Desktop/整理", [])],                                     # 確認だけなので何も書き込まない
    2: [("Desktop/整理", ["IMG_0001.jpg", "IMG_0002.jpg", "メモ.txt", "売上_2026.xlsx",   # (1) 付きは削除
                          "見積書_2025.pdf", "見積書_A社.pdf", "請求書_10月.pdf", "議事録.docx"]),
        ("Downloads", [])],
    3: [("Desktop/書類", ["メモ.txt", "売上_2026.xlsx", "見積書_2025.pdf", "見積書_A社.pdf",
                          "請求書_10月.pdf", "議事録.docx"]),
        ("Desktop/写真", ["IMG_0001.jpg", "IMG_0002.jpg"])],
    4: [("Desktop/写真", ["IMG_0001.jpg", "IMG_0002.jpg"])],
    5: [("Desktop/整理", ["メモ.txt", "メモ_1.txt"]), ("Downloads", ["IMG_0001 (1).jpg", "IMG_0001.jpg",
        "IMG_0002.jpg", "メモ.txt", "売上_2026.xlsx", "見積書_2025.pdf", "見積書_A社.pdf", "請求書_10月.pdf",
        "議事録.docx"])],                                          # コピーなので元も残る
    6: [("D:/写真/旅行", ["山_01.jpg", "海_01.jpg", "海_02.jpg"]), ("Pictures/旅行", [])],
}


def test_W12_gui_demo_patterns(tk_root, tmp_path):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("demo_gui", ROOT / "demo/gui/demo_gui.py")
    demo_gui = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = demo_gui
    spec.loader.exec_module(demo_gui)
    assert len(demo_gui.PATTERNS) == len(DEMO_EXPECTED)

    for i, checks in DEMO_EXPECTED.items():
        work = tmp_path / f"work{i}"
        demo_gui.play(i, work, record=False, slow=False, hidden=True)
        sample = demo_gui.Sample(work)
        for where, expected in checks:
            folder = sample.d_drive / where[3:] if where.startswith("D:/") else sample.home / where
            assert _names(folder) == expected, f"G{i} {where}"


# ================================================================ exe

EXE = ROOT / "dist" / "FileMove.exe"


@pytest.mark.skipif(not EXE.exists(), reason="dist/FileMove.exe が無い（python tools/build_exe.py で作る）")
def test_X1_exe_self_test(tmp_path):
    out = tmp_path / "self_test.txt"

    proc = subprocess.run([str(EXE), "--self-test", str(out)], timeout=300)

    text = out.read_text(encoding="utf-8")
    assert proc.returncode == 0, text
    assert "OK  見た目（sv-ttk）" in text and "OK  ドラッグ＆ドロップ（tkinterdnd2）" in text
    assert text.endswith("結果: 正常\n")


@pytest.mark.skipif(not EXE.exists(), reason="dist/FileMove.exe が無い（python tools/build_exe.py で作る）")
def test_X2_exe_signed():
    script = (f"$s = Get-AuthenticodeSignature -FilePath '{EXE}'; "
              "$s.SignerCertificate.Subject; $s.Status")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60).stdout.split()

    subject, status = " ".join(out[:-1]), out[-1]
    assert subject == "CN=FileMove (self-signed)"
    # 自己署名なので「信頼されていないルート」（UnknownError）か、この PC で信頼していれば Valid。
    # 署名の後に書き換わっていたら HashMismatch、署名が無ければ NotSigned になる
    assert status in ("Valid", "UnknownError"), status
