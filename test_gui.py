# -*- coding: utf-8 -*-
"""
GUI（gui/）のテスト（pytest）

実行:
    python -m pytest test_gui.py

画面を開くテスト（W）は、ウィンドウを隠したまま tkinter を動かす。画面の無い環境では skip する。

テスト網羅:
  入力の確認（gui/runner.py の build_options）
    - [U1] 正しい入力を run_migration() の引数にする（拡張子・期間・移動・同名時・重複削除）。
           移す先の前後の空白と "（エクスプローラーの「パスのコピー」）は取る
    - [U2] 移すものなし・移すものが無い・移す先なし・移す先がファイル・移すものと同じ・相対パス・
           期間の書式違いは、画面に出す文言の ValueError（CLI の言葉ではなく画面の項目名で出す）
  実行（gui/runner.py の MigrationJob）
    - [U3] 別スレッドで実行し、ログ・進捗（scanned から順に）・結果がキューに届く。台帳は指定した場所に作られる
    - [U4] 中止すると、今のファイルの後で止まり、結果に cancelled が立つ
    - [U5] ドライランは何も書き込まず、台帳も作らない。summary() にドライランの案内が入る
  結果の見せ方（gui/runner.py の describe / dedupe_rows / outcome）
    - [U6] 進捗の通知を一覧の行（状態・行き先・理由・色）にする。移動／コピー、ドライラン、
           済み・同名で残した・失敗・重複の削除をそれぞれ区別する
    - [U7] 結果の見出し: 完了・確認だけ・残したものあり・失敗あり・中止・対象なしを、色（level）と文言で分ける
  画面（gui/app.py）
    - [W1] 移すものを追加（同じものは 1 回だけ）・外す、移す先を入れて移動すると、重複削除まで終わり、
           進捗バー・件数・結果の見出し・一覧が更新される。空になった移すものは一覧から外れ、
           「移す先を開く」で移す先が開く
    - [W2] 入力に問題があると実行せずに見出しで知らせる。移動は確認で「いいえ」なら実行しない。
           「先に確認する」は確認を出さず、何も書き込まない
    - [W3] 表示用のパス変換（display / parse）が、一覧・移す先・結果の一覧・ログに効く
    - [W4] 同じ名前の別のファイルがあって残したものは、黄色の行と「残しています」の見出しで分かる（移動でも元は消さない）
    - [W5] ドラッグ＆ドロップされたもの（"{空白 入り} 普通" の形）を移すもの・移す先に入れる。
           移す先には、ファイルが落とされたらそのフォルダを入れる
    - [W6] 実行中にウィンドウを閉じようとすると確かめ、「はい」なら中止して終わってから閉じる。「いいえ」なら続ける
    - [W7] 方法を切り替えると実行ボタンの文言（移動する／コピーする）が変わり、詳細設定は開いたときだけ出る
  GUI のデモ（demo/gui/demo_gui.py）
    - [W8] 全パターン（G1〜G6）を録画せずに動かし、それぞれ期待どおりのファイルの状態になる
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import migrate_files as mf
from gui.runner import Form, MigrationJob, build_options, dedupe_rows, describe, outcome, summary


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
                exts="pdf, jpg", since="30d", dedupe=True)

    opts = build_options(form)

    assert opts["src"] == [downloads]
    assert opts["dst"] == tmp_path / "Desktop"
    assert (opts["move"], opts["on_exists"], opts["dedupe"], opts["verify"]) == (True, "rename", True, True)
    assert opts["filt"].exts == {"pdf", "jpg"}
    assert opts["filt"].since is not None


@pytest.mark.parametrize("change, message", [
    (dict(sources=[]), "移すものを追加してください"),
    (dict(sources=["missing"]), "移すものが見つかりません"),
    (dict(dest="  "), "移す先のフォルダを選んでください"),
    (dict(dest='""'), "移す先のフォルダを選んでください"),
    (dict(dest="file"), "移す先がディレクトリではありません"),
    (dict(dest="same"), "移すものと移す先が同じです"),
    (dict(dest="整理"), "移す先は、ドライブからの場所で入れてください"),
    (dict(since="あした"), "^期間の書式が不正です"),
])
def test_U2_build_options_errors(downloads, tmp_path, change, message):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    values = {"sources": [downloads], "dest": str(tmp_path / "Desktop"), **change}
    values["sources"] = [tmp_path / "nope" if s == "missing" else s for s in values["sources"]]
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


# ================================================================ 結果の見せ方

def _ev(status, reason="", error=""):
    return mf.ProgressEvent(status, 1, 1, "a.txt", dest="D:\\out\\a.txt", reason=reason, error=error)


@pytest.mark.parametrize("ev, move, dry_run, state, tag, note", [
    (_ev("done"), True, False, "✔ 移動しました", "ok", "D:\\out\\a.txt"),
    (_ev("done"), False, False, "✔ コピーしました", "ok", "D:\\out\\a.txt"),
    (_ev("dryrun"), True, True, "→ 移動します", "plan", "D:\\out\\a.txt"),
    (_ev("removed", "same"), True, False, "✔ 移動しました", "ok", "同じものが既にあるので、元だけ削除"),
    (_ev("removed", "same"), True, True, "→ 元を削除します", "plan", "元だけ削除"),
    (_ev("skipped", "exists"), True, False, "⚠ 残しました", "warn", "同じ名前の別のファイル"),
    (_ev("skipped", "exists"), True, True, "⚠ 残します", "warn", "同じ名前の別のファイル"),
    (_ev("skipped", "done"), False, False, "✔ 済み", "muted", "前回までに済んでいます"),
    (_ev("skipped", "same"), False, False, "✔ 済み", "muted", "同じものが移す先に既にあります"),
    (_ev("failed", error="使用中です"), True, False, "✗ できませんでした", "error", "使用中です"),
])
def test_U6_describe_rows(ev, move, dry_run, state, tag, note):
    row = describe(ev, move=move, dry_run=dry_run, display=lambda s: s)

    assert (row.state, row.name, row.tag) == (state, "a.txt", tag)
    assert note in row.note
    assert describe(mf.ProgressEvent("scanned", 0, 3), move=True, dry_run=False) is None


def test_U6_dedupe_rows(tmp_path):
    result = mf.MigrationResult(dedupe=mf.DedupeResult(removed=1, paths=[tmp_path / "写真" / "a (1).jpg"],
                                                       failures=[("写真/b (1).jpg", "使用中です")]))

    rows = dedupe_rows(result, dry_run=False, root=tmp_path)

    assert [(r.state, r.name, r.tag) for r in rows] == [("✔ 重複を削除しました", "写真/a (1).jpg", "ok"),
                                                        ("✗ できませんでした", "写真/b (1).jpg", "error")]
    assert dedupe_rows(mf.MigrationResult(), dry_run=False, root=tmp_path) == []


@pytest.mark.parametrize("fields, kw, level, title, detail", [
    (dict(copied=8, sources_removed=1, dirs_removed=[Path("x")]), dict(move=True), "ok",
     "完了しました: 9 件を移動しました", "空になったフォルダを削除 1 件"),
    (dict(copied=3), dict(move=False, dry_run=True), "info",
     "確認だけしました（まだ何も変えていません）", "3 件をコピーします。よければ「コピーする」を押してください"),
    (dict(copied=2, skipped=1), dict(move=True, kept=1), "warn",
     "2 件を移動しました。1 件は残しています", "同じ名前の別のファイル"),
    (dict(copied=2, failed=1), dict(move=True), "error", "1 件ができませんでした", "赤い行"),
    (dict(copied=1, cancelled=True), dict(move=True), "warn", "中止しました", "続きから"),
    (dict(), dict(move=True), "info", "移動するファイルがありませんでした", "種類・期間"),
    (dict(skipped=3, already_done=3), dict(move=False), "ok", "完了しました: 0 件をコピーしました", "前回までに済み 3 件"),
])
def test_U7_outcome(fields, kw, level, title, detail):
    o = outcome(mf.MigrationResult(**fields), **{"dry_run": False, **kw})

    assert (o.level, o.title) == (level, title)
    assert detail in o.detail


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


def _rows(app) -> list[tuple[str, str]]:
    return [(r.state, r.name) for r in app.rows]


def test_W1_app_move_with_dedupe(tk_root, downloads, tmp_path):
    opened = []
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True, opener=opened.append)
    app.add_source(downloads)
    app.add_source(downloads)                       # 同じものは 1 回だけ
    app.add_source(tmp_path / "Downloads" / "見積書.pdf")
    app.src_list.selection_set(1)
    app._remove_selected()
    assert app.sources == [downloads] and app.src_list.size() == 1

    app.set_dest(tmp_path / "Desktop")
    app.move_var.set(True)
    app.dedupe_var.set(True)
    app.start(dry_run=False)
    _pump(app)

    assert app.last_result.ok
    assert sorted(p.name for p in (tmp_path / "Desktop").iterdir()) == ["IMG_0001.jpg", "売上.xlsx", "見積書.pdf"]
    assert app.count_var.get() == "4 / 4 件"
    assert app.progress["value"] == 4
    o = app.last_outcome
    assert (o.level, o.title) == ("ok", "完了しました: 4 件を移動しました")
    assert "重複を削除 1 件" in o.detail and "「Downloads」 は空になったので ① から外しました" in o.detail
    assert app.title_var.get() == o.title
    assert _rows(app)[-1] == ("✔ 重複を削除しました", "IMG_0001 (1).jpg")
    assert len(app.tree.get_children()) == 5
    assert app.sources == [] and app.src_list.size() == 0       # 空になったので一覧から外れる
    assert app.run_btn.instate(["!disabled"]) and app.cancel_btn.instate(["disabled"])

    assert app.open_btn.winfo_manager() == "grid"
    app.open_btn.invoke()
    assert opened == [tmp_path / "Desktop"]


def test_W2_app_input_errors_and_confirm(tk_root, downloads, tmp_path):
    asked = []
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: asked.append(a) or False)

    app.start(dry_run=True)
    assert (app.last_outcome.level, app.last_outcome.detail) == ("warn", "移すものを追加してください")
    assert app.job is None

    app.add_source(downloads)
    app.dest_var.set("整理")                         # 相対パス
    app.start(dry_run=True)
    assert "ドライブからの場所" in app.last_outcome.detail and app.job is None

    app.set_dest(tmp_path / "Desktop")
    app.move_var.set(True)
    app.start(dry_run=False)                          # 確認で「いいえ」
    assert len(asked) == 1 and app.job is None
    assert len(list(downloads.iterdir())) == 4

    app.start(dry_run=True)                           # 「先に確認する」は確認しない
    _pump(app)
    assert len(asked) == 1
    assert app.last_outcome.title == "確認だけしました（まだ何も変えていません）"
    assert _rows(app)[0] == ("→ 移動します", "IMG_0001 (1).jpg")
    assert not (tmp_path / "Desktop").exists()
    assert app.sources == [downloads]                 # 確認だけなら一覧はそのまま
    assert app.open_btn.winfo_manager() == ""         # まだ無い移す先は開けない


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
    app.start(dry_run=False)
    _pump(app)
    log = app.log_text.get("1.0", "end")
    assert real not in log and "C:\\Users\\user\\Desktop" in log
    notes = [app.tree.item(i, "values")[2] for i in app.tree.get_children()]
    assert notes and all(n.startswith("C:\\Users\\user\\Desktop\\") for n in notes)
    assert (tmp_path / "Desktop" / "見積書.pdf").exists()


def test_W4_app_kept_files_are_visible(tk_root, downloads, tmp_path):
    from gui.runner import ON_EXISTS
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "見積書.pdf").write_text("前からある別の見積書", encoding="utf-8")
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
    app.add_source(downloads)
    app.set_dest(desktop)
    app.on_exists_var.set(next(k for k, v in ON_EXISTS.items() if v == "skip"))

    app.start(dry_run=False)
    _pump(app)

    assert (downloads / "見積書.pdf").exists()                    # 移動でも、残したものは消さない
    assert ("⚠ 残しました", "見積書.pdf") in _rows(app)
    item = next(i for i in app.tree.get_children() if app.tree.item(i, "values")[1] == "見積書.pdf")
    assert app.tree.item(item, "tags") == ("warn",)
    assert (app.last_outcome.level, app.last_outcome.title) == ("warn", "3 件を移動しました。1 件は残しています")
    assert app.sources == [downloads]                              # まだ残っているので一覧から外さない


def test_W5_app_drop(tk_root, downloads, tmp_path):
    app = _make_app(tk_root, tmp_path)
    spaced = tmp_path / "新しい フォルダ"
    spaced.mkdir()

    app.drop_sources(f"{{{spaced}}} {downloads.as_posix()}")
    assert app.sources == [spaced, Path(downloads.as_posix())]

    app.drop_dest(f"{{{downloads / '見積書.pdf'}}}")              # ファイルならそのフォルダ
    assert app.dest_var.get() == str(downloads)
    app.drop_dest(f"{{{spaced}}}")
    assert app.dest_var.get() == str(spaced)


def test_W6_app_close_while_running(tk_root, downloads, tmp_path, monkeypatch):
    answers = []
    app = _make_app(tk_root, tmp_path, confirm=lambda title, *a: answers.pop(0) if title == "閉じる確認" else True)
    real = mf.transfer_file
    started = []

    def slow(*a, **kw):
        started.append(1)
        time.sleep(0.2)
        return real(*a, **kw)
    monkeypatch.setattr(mf, "transfer_file", slow)
    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
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


def test_W7_app_mode_and_more(tk_root, tmp_path):
    app = _make_app(tk_root, tmp_path)
    tk_root.update()
    assert app.move_var.get() is True and app.run_btn.cget("text") == "移動する"
    app.copy_radio.invoke()
    assert app.move_var.get() is False and app.run_btn.cget("text") == "コピーする"

    assert app.more.winfo_manager() == ""
    app.more_check.invoke()
    assert app.more.winfo_manager() == "grid"
    app.more_check.invoke()
    assert app.more.winfo_manager() == ""


# ================================================================ GUI のデモ

def _names(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


DEMO_EXPECTED = {   # パターン -> (確かめるフォルダ（ホームから / D:）, そこにあるべきファイル)
    1: [("Desktop/整理", [])],                                     # 確認だけなので何も書き込まない
    2: [("Desktop/整理", ["IMG_0001 (1).jpg", "IMG_0001.jpg", "IMG_0002.jpg", "メモ.txt", "売上_2026.xlsx",
                          "見積書_2025.pdf", "見積書_A社.pdf", "請求書_10月.pdf", "議事録.docx"]),
        ("Downloads", [])],
    3: [("Desktop/書類", ["メモ.txt", "売上_2026.xlsx", "見積書_2025.pdf", "見積書_A社.pdf",
                          "請求書_10月.pdf", "議事録.docx"]),
        ("Desktop/写真", ["IMG_0001 (1).jpg", "IMG_0001.jpg", "IMG_0002.jpg"])],
    4: [("Desktop/写真", ["IMG_0001.jpg", "IMG_0002.jpg"])],
    5: [("Desktop/整理", ["メモ.txt", "メモ_1.txt"]), ("Downloads", ["IMG_0001 (1).jpg", "IMG_0001.jpg",
        "IMG_0002.jpg", "メモ.txt", "売上_2026.xlsx", "見積書_2025.pdf", "見積書_A社.pdf", "請求書_10月.pdf",
        "議事録.docx"])],                                          # コピーなので元も残る
    6: [("D:/写真/旅行", ["山_01.jpg", "海_01.jpg", "海_02.jpg"]), ("Pictures/旅行", [])],
}


def test_W8_gui_demo_patterns(tk_root, tmp_path):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("demo_gui", Path(__file__).parent / "demo/gui/demo_gui.py")
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
