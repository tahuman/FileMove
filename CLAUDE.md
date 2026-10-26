# FileMove

ディレクトリ構成を保ったままファイルをコピー／移動するソフト。コマンドで使う CLI（`migrate_files.py`）と、画面で使う GUI（`gui/`）がある。

## 構成

| 場所 | 中身 |
|---|---|
| `migrate_files.py` | 処理の本体（`run_migration()` など）と CLI |
| `gui/` | GUI（tkinter）。`runner.py` が入力の確認と別スレッドでの実行、`app.py` が画面 |
| `test_migrate_files.py` / `test_gui.py` | 本体と CLI のテスト / GUI のテスト |
| `testdata/` | CLI のシナリオ（`SCENARIOS.md` と `run_scenarios.py`） |
| `demo/` | デモ。`sample.py` が共通のサンプル、`cli/` が CLI、`gui/` が GUI |
| `docs/cli/` / `docs/gui/` | CLI / GUI のマニュアル |
| `docs/images/cli/` / `docs/images/gui/` | CLI / GUI のデモの GIF |
| `requirements.txt` / `requirements-dev.txt` | GUI の追加ライブラリ（無くても動く） / テスト・デモ用 |
| `.claude/skills/gui-check/` | GUI の画面を撮って見た目を確かめる手順（skill） |

## 実装とテストは必ずセットで行う

- 機能の追加・変更・バグ修正をしたら、同じ作業の中でテストも追加・更新する。実装だけ・テストだけで終わらせない
- 本体と CLI の単体テストは `test_migrate_files.py`、GUI のテストは `test_gui.py` に書き、それぞれ冒頭の「テスト網羅」に項目（ID と一文の説明）を足す
- CLI から見た振る舞いが変わる場合は、`testdata/SCENARIOS.md` の表と `testdata/run_scenarios.py` の `SCENARIOS` も揃えて更新する
- 作業の最後に `python -m pytest` を実行し、全件成功を確認してから報告する。失敗が残る場合はその出力を添えて報告する

## テストの実行

```
python -m pip install -r requirements-dev.txt
python -m pytest                    # 全件（本体・CLI・GUI・シナリオ、40 秒ほど）
python -m pytest -m "not scenario"  # シナリオ以外
python -m pytest test_gui.py        # GUI だけ
```

## テストの書き方

- ファイル操作は `tmp_path` の中で行い、リポジトリを汚さない
- 失敗・中断は本物の障害を起こさず、差し替えで再現する（`transfer_file` の `copy_fn`、`run_migration` の `should_cancel` / `progress`、`monkeypatch`）
- 時刻に依存する処理は `now` を渡して固定する
- GUI のテストはウィンドウを隠して（`withdraw()`）動かし、画面を開けない環境では skip する。確認の画面などは `App` の引数（`confirm` など）で差し替える

## CLI と GUI を分ける

- 処理の本体は `migrate_files.py`。GUI は本体の関数（`run_migration()`、`check_paths()`、`make_filter()` など）を呼ぶだけにする
- GUI に処理を書かない。新しい機能はまず本体に足し、CLI と GUI の両方から使えるようにする。CLI の `main()` にしか無い処理を GUI で使いたくなったら、本体の関数に切り出す
- GUI は今のところ Windows 向け。Windows 専用の機能（レジストリ、Windows だけのライブラリ）は使わず、後から Mac・Linux に広げられるようにしておく
- GUI の追加ライブラリ（`requirements.txt` の sv-ttk・tkinterdnd2）は、入っていなくても動くようにする（見た目が古くなる・ドラッグ＆ドロップが使えないだけ）
- GUI はシンプルに保つ。上から「① 移すもの → ② 移す先 → ③ 移動かコピーか → 実行」の順で、細かい設定は「詳細設定」に畳む。結果は見出しと 1 ファイルずつの一覧で、終わったか・何が残ったかがひと目で分かるようにする。結果の言葉は `gui/runner.py`（画面に依存しない）に書く

## デモ

- CLI の振る舞いを変えたら `demo/cli/demo.py` のパターンを更新し、`python demo/cli/make_gif.py` で GIF（`docs/images/cli/`）を作り直す
- GUI の画面や振る舞いを変えたら、skill `gui-check`（`.claude/skills/gui-check/SKILL.md`）で画面を撮って見た目を確かめる。`demo/gui/demo_gui.py` のパターンを更新し、`python demo/gui/demo_gui.py` で GIF（`docs/images/gui/`）を作り直す（録画中は画面にウィンドウが出る）
- デモのサンプル（ダウンロード → デスクトップの整理）は `demo/sample.py` で共通にする。表示上のパスは `C:\Users\user\…` にし、実際の作業フォルダの場所は見せない
- README には主要な使い方だけ、各 MANUAL の「シナリオで見る使い方」には全パターンを載せる

## その他

- `plan.md` は今後の機能・課題の一覧。終わったものは「完了」の表に移す。デモのように更新し続けるものは「継続」に置き、完了には移さない
- `fix.md` は見つけた不具合・指摘の一覧。直したら `plan.md` の「修正（完了）」に移す
