# テストシナリオ（migrate_files.py）

## 準備

```
python testdata/make_testdata.py
```

`testdata/work/` に `src/`・`dst/`・`ledger_partial.jsonl` が作られる（既存は消して作り直す）。
**書き込みを伴うシナリオは、毎回この生成からやり直すこと**（dst や台帳が前の実行で変わるため）。

以下のコマンドは共通で `W=testdata/work`、ログ・台帳はリポジトリを汚さないよう
`--log $W/m.log --ledger $W/l.jsonl` を付ける前提（表では省略）。

## テストデータの中身

| パス (src/) | サイズ | 更新 | 狙い |
|---|---|---|---|
| docs/report_2025.pdf | 10KB | 400日前 | 古いファイル（--since） |
| docs/report_2026.PDF | 20KB | 5日前 | 拡張子の大文字 |
| docs/meeting notes.txt | 小 | 10日前 | 名前にスペース |
| docs/議事録_2026年10月.docx | 5KB | 2日前 | 日本語ファイル名 |
| data/sales.xlsx / sales.csv | 50KB / 小 | 40日前 | 拡張子フィルタ |
| images/photo1.jpg / photo2.JPG | 200KB / 300KB | 90日前 / 1日前 | 拡張子の大文字小文字 |
| data/big/large_3MB.bin | 3MB | 1日前 | ハッシュの分割読み（1MB 超） |
| data/big/exact_1MB.bin | 1MB ちょうど | 1日前 | --max-size の境界 |
| empty_file.txt | 0B | 3日前 | 空ファイル |
| data/nested/a/b/c/deep.txt | 小 | 20日前 | 深い階層 |
| no_extension / .hidden_config / archive.tar.gz | 小 / 小 / 8KB | 15〜60日前 | 拡張子なし・隠し・二重拡張子 |
| 日本語フォルダ/サブ フォルダ/メモ.txt | 小 | 7日前 | 日本語＋スペースのディレクトリ |
| cache/build.tmp | 1KB ちょうど | 1日前 | 除外 glob / --min-size の境界 |
| data/~$sales.xlsx, images/Thumbs.db | 小 | — | 除外 glob（ゴミファイル） |
| node_modules/…, .git/HEAD | 小 | 100日前 | ディレクトリ単位の除外 |
| conflict/same.txt, conflict/renamed.txt | 小 | 1日前 | dst 側に同名あり（衝突） |
| conflict/only_in_src.txt | 小 | 1日前 | 衝突なし |
| empty_dir/, data/nested/empty_child/ | — | — | 空ディレクトリ（移行されない） |

src は計 **24 ファイル**。dst には `conflict/same.txt`, `conflict/renamed.txt`, `conflict/renamed_1.txt`（中身は `OLD (dst)`）が事前配置。

`ledger_partial.jsonl`: この src→dst の記録として `docs/report_2025.pdf`・`data/sales.csv` が done、
`data/sales.xlsx` が failed、`images/photo1.jpg` が skipped。
別の移行の done 記録（`empty_file.txt`・`no_extension`）と、移行元・移行先を持たない旧形式の done 記録（`archive.tar.gz`）、
さらに空行・壊れた JSON・path キーなし・配列・書きかけの行を含む。

## シナリオと期待結果

（2026-10-13 時点の実装で全件確認済み。18・19 は一時ディレクトリで実施）

| # | コマンド（追加引数） | 期待結果 |
|---|---|---|
| 1 | `--dry-run` | 対象 24 / 成功 22・スキップ 2（conflict の 2 件）/ exit 0。dst は変化なし |
| 2 | `--dry-run --ext pdf,jpg` | 4 件（.PDF / .JPG も含む） |
| 3 | `--dry-run --since 30d` | 16 件（400/90/60/40/100日前のものが除外）、成功 14・スキップ 2 |
| 4 | `--dry-run --min-size 1KB --max-size 1MB` | 10 件。build.tmp(1KB) と exact_1MB.bin は境界値で**含まれる**、3MB・空ファイルは除外 |
| 5 | `--dry-run --exclude "*.tmp" --exclude '~$*' --exclude Thumbs.db --exclude node_modules --exclude .git` | 19 件 |
| 6 | `--dry-run --since 2026-13-01` | 「--since の書式が不正です」/ exit 2 |
| 7 | （オプションなし = skip） | 成功 22・スキップ 2 / exit 0。`dst/conflict/same.txt` は `OLD (dst)` のまま。空ディレクトリは作られない |
| 8 | 7 の直後に同じコマンドを再実行 | 成功 0・スキップ 24、「うち台帳で処理済みとしてスキップ 22 件」と表示 |
| 9 | `--on-exists rename` | 成功 24。`same_1.txt` と `renamed_2.txt`（_1 は既存のため）が `NEW (src)` で作られる |
| 10 | `--on-exists overwrite` | 成功 24。`same.txt` が `NEW (src)` に置き換わる |
| 11 | `--ledger $W/ledger_partial.jsonl` | 成功 20・スキップ 4（done の 2 件＋衝突 2 件）、「うち台帳で処理済み 2 件」。failed/skipped 記録の sales.xlsx・photo1.jpg、別の移行・旧形式の記録しかない empty_file.txt・no_extension・archive.tar.gz はコピーされる。壊れた行でエラーにならない |
| 12 | `--restart --ledger $W/ledger_partial.jsonl` | 台帳を無視して 1 と同じく成功 22・スキップ 2 |
| 13 | `--move` | 成功 22・スキップ 2。src に残るのは conflict/same.txt と conflict/renamed.txt のみ |
| 14 | dst を `$W/src/_migrated` にする（2 回実行、2 回目は別台帳） | 1 回目 成功 24。2 回目も対象 24 件のまま（_migrated 配下を辿らない）でスキップ 24 |
| 15 | 7 の後に src と dst の更新日時を比較 | 一致（copy2 でメタデータ保持） |
| 16 | src と dst に同じパスを指定 | 「移行元と移行先が同じです」/ exit 2 |
| 17 | src に存在しないパスを指定 | 「移行元が見つかりません」/ exit 2 |
| 18 | 既定の台帳のまま `A→outA`、続けて `B→outB`（どちらにも `report.txt`） | 2 回とも成功 1。B のファイルが台帳のせいでスキップされない |
| 19 | 18 の後に `a→OUTA`（大文字小文字だけ違うパス、Windows） | 同じ移行とみなし、台帳で処理済みとしてスキップ 1 |

## 単一ファイル指定

移行元にファイルを指定すると、移行先ディレクトリの直下に同じ名前で送る。絞り込み・衝突時の動作・照合・`--move`・ドライラン・台帳はディレクトリ指定と同じく効く。

| # | コマンド（追加引数は表と同じく省略） | 期待結果 |
|---|---|---|
| S1 | `$W/src/docs/議事録_2026年10月.docx $W/out` | 成功 1。`out/議事録_2026年10月.docx` が内容・更新日時とも一致、移行元は残る |
| S2 | S1 を再実行 | スキップ 1（台帳で処理済み） |
| S3 | S1 の後に同じフォルダの `report_2026.PDF` → `$W/out` | 成功 1（別ファイルなので台帳で混ざらない） |
| S4 | S1 に `--dry-run` | 成功 1 と表示、`out/` は作られない |
| S5〜S7 | `.docx` に `--ext pdf` / `build.tmp` に `--exclude "*.tmp"` / `report_2025.pdf` に `--since 30d` | いずれも対象 0 件、exit 0 |
| S8 | `$W/src/conflict/same.txt $W/dst/conflict` | スキップ 1、`same.txt` は `OLD (dst)` のまま |
| S9 | `$W/src/conflict/renamed.txt $W/dst/conflict --on-exists rename` | `renamed_2.txt` が作られる |
| S10 | `$W/src/conflict/same.txt $W/dst/conflict --on-exists overwrite` | `same.txt` が `NEW (src)` になる |
| S11 | `$W/src/data/big/large_3MB.bin $W/out --move` | 成功 1、移行元は消え、移行先は 3,145,728 bytes |
| S12 | `$W/src/empty_file.txt $W/out` | 成功 1（0 バイトでも可） |
| S13 | `$W/src/no_extension $W/src --move --on-exists overwrite`（ファイルのあるフォルダを移行先に） | 「移行元と移行先が同じです」/ exit 2、ファイルは無事 |
| S14 | 移行先に既存の**ファイル**を指定 | 「移行先がディレクトリではありません」/ exit 2 |
| S15 | 存在しないファイルを指定 | 「移行元が見つかりません」/ exit 2 |
| S16 | `docs/` に移動して相対パス `"meeting notes.txt"` を指定 | 成功 1 |

## このデータでは確認できないもの

- ハッシュ不一致・コピー途中の失敗（`.part` が残らないこと）、Ctrl+C 中断 → `copy_fn` を差し替えるユニットテスト向き
- アクセス権のないファイル（stat 失敗時の警告スキップ）→ OS 依存のため手動で権限を外して確認
