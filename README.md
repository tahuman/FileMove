# FileMove
ファイルを移す際に複数ファイルを一度に移動させるソフトウェア

- フォルダの構成を保ったまま、たくさんのファイルを一度にコピー・移動できます
- コピー後に中身が同じか（SHA-256）を確かめてから完了とします。移動のときも、確かめるまで元のファイルは消しません
- 途中で止まっても、もう一度実行すれば続きから再開します
- 実行する前に「何がどこへ行くか」だけを確認できます（ドライラン）

画面で操作する **GUI** と、コマンドで使う **CLI** があります。できることは同じです。

| | GUI（画面） | CLI（コマンド） |
|---|---|---|
| 向いている人 | ふだんの整理に。ボタンで操作したい | 決まった作業をくり返したい・バッチで自動化したい |
| 起動 | `FileMove.exe` をダブルクリック（Python 不要。exe はリポジトリには入っていないので、[Releases](../../releases) から入手するか、`python tools/build_exe.py` で作る）。または `gui\FileMove.pyw`・`python -m gui` | `python migrate_files.py 移行元 移行先` |
| 対応 OS | Windows（Mac・Linux は今後対応予定） | Windows・Mac・Linux |
| マニュアル | [docs/gui/MANUAL.md](docs/gui/MANUAL.md) | [docs/cli/MANUAL.md](docs/cli/MANUAL.md) |

## GUI（画面で使う）

ダウンロードにたまったファイルを、デスクトップへ移して整理する例です。

**① 確認する**（対象フォルダと保存先フォルダを選んで「確認」。何も変えずに、どのファイルがどこへ行くかを一覧に表示。確認するまで「実行」は押せない）

![GUI 確認](docs/images/gui/demo_g01_dry-run.gif)

**② 実行する**（確認した一覧のファイルだけを移す。保存先で中身の一致を確かめてから元を消し、終わると結果が大きく出て、結果の一覧とログを保存する）

![GUI 移動](docs/images/gui/demo_g02_move.gif)

ほかの使い方（種類ごとの振り分け・重複の削除・ドライブ間の移動など）は [docs/gui/MANUAL.md](docs/gui/MANUAL.md#8-シナリオで見る使い方) にまとめています。

## CLI（コマンドで使う）

```
python migrate_files.py 移行元 [移行元 ...] 移行先 --dry-run   # まず確認
python migrate_files.py 移行元 [移行元 ...] 移行先             # 実行（--move で移動）
```

移行元にはフォルダ・ファイル・ワイルドカードを混ぜて複数指定できます。

**① 何が起きるか、先に確認する**（`--dry-run`）

![CLI ドライラン](docs/images/cli/demo_p01_dry-run.gif)

**② 移動する**（`--move`。C ドライブ → D ドライブのようなドライブ間でも同じ）

![CLI 移動](docs/images/cli/demo_p03_move.gif)

ほかの使い方（コピー・振り分け・再開・コピー済みの片付け・重複の削除など）は [docs/cli/MANUAL.md](docs/cli/MANUAL.md#13-シナリオで見る使い方) にまとめています。

## 開発者向け

| やりたいこと | コマンド |
|---|---|
| GUI を Python から使う | `python -m pip install -r requirements.txt`（見た目の sv-ttk・ドラッグ＆ドロップの tkinterdnd2。無くても動く） |
| exe を作る | `python tools/build_exe.py`（`dist\FileMove.exe`。`dist/` は git に入れない。自己署名の証明書で署名し、作った後に自己診断も行う。PyInstaller が必要） |
| テスト（本体・CLI・GUI・ユースケース・シナリオ） | `python -m pip install -r requirements-dev.txt` の後に `python -m pytest` |
| リリースの手順 | [RELEASE.md](RELEASE.md)（テスト・人の確認・マージ・タグ・配布の順。人の確認は [docs/gui/USECASES.md](docs/gui/USECASES.md)） |
| CLI のデモを動かす | `python demo/cli/demo.py`（`--auto` で止まらずに流す、`--only 3` で P3 だけ） |
| CLI のデモの GIF を作り直す | `python demo/cli/make_gif.py`（`docs/images/cli/` に出力。Pillow が必要） |
| GUI のデモを見る | `python demo/gui/demo_gui.py --show 2`（G2 を画面で再生） |
| GUI のデモの GIF を作り直す | `python demo/gui/demo_gui.py`（`docs/images/gui/` に出力。Windows・Pillow が必要。録画中は画面にウィンドウが出る） |
| GUI の画面を撮って確かめる | `python demo/gui/demo_gui.py --snap 出力先 2`（変わった画面を PNG で保存） |

構成: 本体と CLI は `migrate_files.py`、GUI は `gui/`（本体の `run_migration()` を呼ぶだけ）、exe 化は `tools/build_exe.py`。今後の予定は [plan.md](plan.md)。
