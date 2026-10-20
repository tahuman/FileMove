# FileMove
ファイルを移す際に複数ファイルを一度に移動させるソフトウェア


## 使い方

```
python migrate_files.py 移行元 [移行元 ...] 移行先 --dry-run   # まず確認
python migrate_files.py 移行元 [移行元 ...] 移行先             # 実行（--move で移動）
```

移行元にはフォルダ・ファイル・ワイルドカードを混ぜて複数指定できます。

- 詳しい使い方: [docs/MANUAL.md](docs/MANUAL.md)
- デモ: `python demo/demo.py`（サンプルを作って主な使い方を順に実行します。`--auto` で止まらずに流す）
- 動作確認: `python -m pytest`（単体テストと全シナリオ。シナリオだけなら `python testdata/run_scenarios.py`）
