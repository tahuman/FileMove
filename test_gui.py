# -*- coding: utf-8 -*-
"""
GUI（gui/）のテスト（pytest）

実行:
    python -m pytest test_gui.py

画面を開くテスト（W）は、ウィンドウを隠したまま tkinter を動かす。画面の無い環境では skip する。

テスト網羅:
  入力の確認（gui/runner.py の build_options）
    - [U1] 正しい入力を run_migration() の引数にする（拡張子・期間・移動・同名時・重複削除）
    - [U2] 移行元なし・移行元が無い・移行先なし・移行先がファイル・移行元と同じ・期間の書式違いは、
           画面に出す文言の ValueError（CLI のオプション名ではなく画面の項目名で出す）
  実行（gui/runner.py の MigrationJob）
    - [U3] 別スレッドで実行し、ログ・進捗（scanned から順に）・結果がキューに届く。台帳は指定した場所に作られる
    - [U4] 中止すると、今のファイルの後で止まり、結果に cancelled が立つ
    - [U5] ドライランは何も書き込まず、台帳も作らない。summary() にドライランの案内が入る
  画面（gui/app.py）
    - [W1] 移行元を追加（同じものは 1 回だけ）・外す、移行先を入れて実行すると、移動・重複削除まで終わり、
           進捗バーと件数・結果の文言が更新される
    - [W2] 入力に問題があると実行せずに文言を出す。移動は確認で「いいえ」なら実行しない
    - [W3] 表示用のパス変換（display / parse）が、一覧・移行先・ログに効く
  GUI のデモ（demo/gui/demo_gui.py）
    - [W4] 全パターン（G1〜G6）を録画せずに動かし、それぞれ期待どおりのファイルの状態になる
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import migrate_files as mf
from gui.runner import Form, MigrationJob, build_options, summary


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
    form = Form(sources=[downloads], dest=str(tmp_path / "Desktop"), move=True, on_exists="rename",
                exts="pdf, jpg", since="30d", dedupe=True)

    opts = build_options(form)

    assert opts["src"] == [downloads]
    assert opts["dst"] == tmp_path / "Desktop"
    assert (opts["move"], opts["on_exists"], opts["dedupe"], opts["verify"]) == (True, "rename", True, True)
    assert opts["filt"].exts == {"pdf", "jpg"}
    assert opts["filt"].since is not None


@pytest.mark.parametrize("change, message", [
    (dict(sources=[]), "移行元を追加してください"),
    (dict(sources=["missing"]), "移行元が見つかりません"),
    (dict(dest="  "), "移行先のフォルダを選んでください"),
    (dict(dest="file"), "移行先がディレクトリではありません"),
    (dict(dest="same"), "移行元と移行先が同じです"),
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
    root.destroy()


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


def test_W1_app_move_with_dedupe(tk_root, downloads, tmp_path):
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: True)
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
    assert app.status_var.get().startswith("完了しました: 成功 4") and "重複を削除 1" in app.status_var.get()
    assert app.run_btn.instate(["!disabled"]) and app.cancel_btn.instate(["disabled"])


def test_W2_app_input_errors_and_confirm(tk_root, downloads, tmp_path):
    asked = []
    app = _make_app(tk_root, tmp_path, confirm=lambda *a: asked.append(a) or False)

    app.start(dry_run=True)
    assert app.status_var.get() == "⚠ 移行元を追加してください"
    assert app.job is None

    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    app.move_var.set(True)
    app.start(dry_run=False)                          # 確認で「いいえ」
    assert len(asked) == 1 and app.job is None
    assert len(list(downloads.iterdir())) == 4

    app.start(dry_run=True)                           # ドライランは確認しない
    _pump(app)
    assert len(asked) == 1
    assert "確認しました（ドライラン）" in app.status_var.get()
    assert not (tmp_path / "Desktop").exists()


def test_W3_app_display_paths(tk_root, downloads, tmp_path):
    real = str(tmp_path)
    app = _make_app(tk_root, tmp_path,
                    display=lambda s: s.replace(real, "C:\\Users\\user"),
                    parse=lambda s: s.replace("C:\\Users\\user", real))

    app.add_source(downloads)
    app.set_dest(tmp_path / "Desktop")
    assert app.src_list.get(0) == "C:\\Users\\user\\Downloads\\"
    assert app.dest_var.get() == "C:\\Users\\user\\Desktop"

    app.start(dry_run=False)
    _pump(app)
    log = app.log_text.get("1.0", "end")
    assert real not in log and "C:\\Users\\user\\Desktop" in log
    assert (tmp_path / "Desktop" / "見積書.pdf").exists()


# ================================================================ GUI のデモ

def _names(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


DEMO_EXPECTED = {   # パターン -> (確かめるフォルダ（ホームから / D:）, そこにあるべきファイル)
    1: [("Desktop/整理", [])],                                     # ドライランなので何も書き込まない
    2: [("Desktop/整理", ["IMG_0001 (1).jpg", "IMG_0001.jpg", "IMG_0002.jpg", "メモ.txt", "売上_2026.xlsx",
                          "見積書_2025.pdf", "見積書_A社.pdf", "請求書_10月.pdf", "議事録.docx"]),
        ("Downloads", [])],
    3: [("Desktop/書類", ["メモ.txt", "売上_2026.xlsx", "見積書_2025.pdf", "見積書_A社.pdf",
                          "請求書_10月.pdf", "議事録.docx"]),
        ("Desktop/写真", ["IMG_0001 (1).jpg", "IMG_0001.jpg", "IMG_0002.jpg"])],
    4: [("Desktop/写真", ["IMG_0001.jpg", "IMG_0002.jpg"])],
    5: [("Desktop/整理", ["メモ.txt", "メモ_1.txt"])],
    6: [("D:/写真/旅行", ["山_01.jpg", "海_01.jpg", "海_02.jpg"]), ("Pictures/旅行", [])],
}


def test_W4_gui_demo_patterns(tk_root, tmp_path):
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
