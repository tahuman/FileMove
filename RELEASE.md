# リリースの手順

バージョンを出すまでに行うこと。上から順に行い、終わったらチェックを付ける。
次のバージョンでは、この表を写して使う（済んだバージョンの記録は下の「履歴」に残す）。

ブランチは develop から `release/vX.Y` を切って作業し、main と develop の両方へ戻す。

---

## v1.0.0（作業中・ブランチ `release/v1.0`）

### 1. リリースに入れる修正

- [x] バージョン番号（`migrate_files.__version__`。CLI の `--version`・GUI のタイトル・exe のプロパティ）
- [x] ユースケースのテスト（`test_usecases.py`・`docs/gui/USECASES.md`）
- [x] README・マニュアルの画像に黒い枠、exe の入手先を README に書く
- [x] F30（全部がスキップになるときの確認の見出し）
- [x] コミット（c8c385c まで）

### 2. 自動のテストと exe

- [ ] `python -m pytest` が全件成功する（本体・CLI・GUI・ユースケース・シナリオ）
- [ ] `python tools/build_exe.py` で exe を作り直し、署名と自己診断が通る（`test_gui.py` の X1〜X3 も）

### 3. 人が確かめる

- [ ] `docs/gui/USECASES.md` の「2. 人が確かめること」をすべて行う
- [ ] 見つかった問題は `fix.md` に書き、このリリースで直すかを決める。直したら 2 からやり直す

### 4. マージ

- [ ] `release/v1.0` をコミットして push する
- [ ] main へマージ（merge commit）。main は v0.1 のままなので、次の 4 ファイルがコンフリクトする。**すべて develop（release）側を採る**
  - `README.md`・`migrate_files.py`・`testdata/SCENARIOS.md`・`testdata/run_scenarios.py`（後の 2 つは両方で新規に作ったファイルなので、ファイルごと release 側にする）
  - ローカルで `git checkout main` → `git merge release/v1.0` なら、「入ってくる側（Incoming）」を採る
  - GitHub の PR 画面で解消するなら向きが逆になるので、マーカーのブランチ名を見て release 側を採る
- [ ] main で `python -m pytest` が全件成功する
- [ ] develop へもマージ（merge commit）。release で直したもの（バージョン・ユースケースのテスト・F30 など）を develop に戻す

### 5. タグと配布

- [ ] main に `v1.0.0` のタグを付けて push する（`git tag -a v1.0.0 -m "FileMove 1.0.0"` → `git push origin v1.0.0`）
- [ ] main で `python tools/build_exe.py` を実行して、配る exe を作る（`dist\FileMove.exe`・`dist\FileMove.cer`）
- [ ] GitHub の Release（v1.0.0）を作り、`FileMove.exe` と `FileMove.cer` を添付する
  - 説明に、主な機能と、自己署名のため初回に SmartScreen の警告が出ること（「詳細情報」→「実行」）を書く
  - リポジトリは今は非公開なので、見られるのは自分だけ

### 6. 後片付け

- [ ] `release/v1.0` ブランチを消す（手で行う）
- [ ] `plan.md`・`fix.md` を見直し、このリリースの記録を下の「履歴」に移す

### 後で行う（公開するとき）

- [ ] リポジトリを公開する
- [ ] README に、exe を Releases から入手できることと、SmartScreen の警告のことを書く（入手先の一文は README にある）
- [ ] 正規の証明書が要るかを考える（SignPath Foundation・Certum のオープンソース向け証明書など。`plan.md` の「exe の署名」を参照）

---

## 履歴

| バージョン | 日付 | 内容 |
|---|---|---|
| v0.1 | | 最初の版（CLI のみ）。main に残っている |
