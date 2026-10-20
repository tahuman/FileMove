# FileMove

ディレクトリ構成を保ったままファイルをコピー／移動する CLI（`migrate_files.py`）。

## 実装とテストは必ずセットで行う

- 機能の追加・変更・バグ修正をしたら、同じ作業の中でテストも追加・更新する。実装だけ・テストだけで終わらせない
- 単体テストは `test_migrate_files.py` に書き、冒頭の「テスト網羅」に項目（ID と一文の説明）を足す
- CLI から見た振る舞いが変わる場合は、`testdata/SCENARIOS.md` の表と `testdata/run_scenarios.py` の `SCENARIOS` も揃えて更新する
- 作業の最後に `python -m pytest` を実行し、全件成功を確認してから報告する。失敗が残る場合はその出力を添えて報告する

## テストの実行

```
python -m pip install -r requirements-dev.txt
python -m pytest                    # 全件（単体テスト＋シナリオ、20 秒ほど）
python -m pytest -m "not scenario"  # 単体テストだけ
```

## テストの書き方

- ファイル操作は `tmp_path` の中で行い、リポジトリを汚さない
- 失敗・中断は本物の障害を起こさず、差し替えで再現する（`transfer_file` の `copy_fn`、`run_migration` の `should_cancel` / `progress`、`monkeypatch`）
- 時刻に依存する処理は `now` を渡して固定する

## その他

- `plan.md` は今後の機能・課題の一覧。終わったものは「完了」の表に移す
