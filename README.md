# FileMove
ファイルを移す際に複数ファイルを一度に移動させるソフトウェア


## 使い方

```
python migrate_files.py 移行元 [移行元 ...] 移行先 --dry-run   # まず確認
python migrate_files.py 移行元 [移行元 ...] 移行先             # 実行（--move で移動）
```

移行元にはフォルダ・ファイル・ワイルドカードを混ぜて複数指定できます。

## デモ

**① まずドライランで確認**（何も書き込まずに、何がどこへ行くかだけを表示）

![ドライラン](docs/images/demo_01_dry-run.gif)

**② フォルダごとコピー**（不要なファイルを除外。コピー後に中身を SHA-256 で照合）

![コピー](docs/images/demo_02_copy.gif)

**③ 移動**（`--move`。移行先で中身の一致を確認してから元を消す）

![移動](docs/images/demo_05_rename-move.gif)

ほかの使い方（再開・絞り込み・コピー済みの片付け・重複の削除など）は [docs/MANUAL.md](docs/MANUAL.md#13-シナリオで見る使い方) にまとめています。

- 詳しい使い方: [docs/MANUAL.md](docs/MANUAL.md)
- デモ: `python demo/demo.py`（サンプルを作って主な使い方を順に実行します。`--auto` で止まらずに流す）
- デモの GIF を作り直す: `python demo/make_gif.py`（`docs/images/` に出力。Pillow が必要）
- 動作確認: `python -m pytest`（単体テストと全シナリオ。シナリオだけなら `python testdata/run_scenarios.py`）
