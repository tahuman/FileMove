#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileMove の GUI のデモ。CLI のデモと同じ「ダウンロード → デスクトップの整理」の場面で、
画面を自動で操作して、パターン（G1〜G6）ごとにアニメーション GIF にする。

    python demo/gui/demo_gui.py            # 全パターンを録画 -> docs/images/gui/demo_g*.gif
    python demo/gui/demo_gui.py 2 4        # 指定したパターンだけ（G2 と G4）
    python demo/gui/demo_gui.py --show 2   # 録画せず、画面で動きだけ見る
    python demo/gui/demo_gui.py --snap OUT 2   # 待たずに動かし、変わった画面を OUT に PNG で保存（見た目の確認用）

録画中は画面に FileMove のウィンドウが開き、ほかのウィンドウより手前に出る（画面を撮影するため）。
ファイル選択の画面やドラッグ＆ドロップは自動で操作できないので、ボタンや一覧を指したうえで、
選んだ結果を直接入れている。表示上のパスは C:\\Users\\user\\… / D:\\…（demo/sample.py）。
Windows 用（画面の撮影に Pillow の ImageGrab を使う）。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))          # migrate_files と gui
sys.path.insert(0, str(HERE.parent))   # demo/sample.py

import migrate_files as mf  # noqa: E402
from gui.app import App, apply_theme, make_root  # noqa: E402
from sample import D_SHOWN, HOME_SHOWN, Sample  # noqa: E402

OUT_DIR = ROOT / "docs" / "images" / "gui"
FRAME_MS = 100          # 録画の間隔
FRAME_PX = 6            # 画像のまわりの黒い枠の太さ
SLOW_PER_FILE = 0.15    # 進捗が見えるよう、1 ファイルごとに待つ秒数（デモのときだけ）

PATTERNS: list = []


def pattern(title: str, gif: str, extra: list | None = None):
    """GUI デモの 1 パターン。title は「何をしたいか」の 1 行。"""
    def deco(fn):
        PATTERNS.append((title, fn, gif, extra or []))
        return fn
    return deco


# ---------------------------------------------------------------- 録画

@dataclass
class Recorder:
    """ウィンドウを撮影して、タイトルバーと説明の帯を付けたフレームをためる。"""
    root: tk.Tk
    title: str
    enabled: bool = True      # 撮影する
    realtime: bool = True     # 人が見る速さで待つ（テストでは待たない）
    caption: str = ""
    pointer: tk.Widget | None = None
    frames: list = field(default_factory=list)
    durations: list = field(default_factory=list)

    def shot(self, ms: int = FRAME_MS) -> None:
        self.root.update()
        if not self.enabled:
            return
        from PIL import ImageGrab
        r = self.root
        x, y, w, h = r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()
        img = compose(ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True),
                      self.title, self.caption, self._pointer_at())
        if self.frames and img.tobytes() == self.frames[-1].tobytes():
            self.durations[-1] += ms   # 変化が無ければ前のフレームを延ばす
        else:
            self.frames.append(img)
            self.durations.append(ms)

    def _pointer_at(self) -> tuple[int, int] | None:
        w = self.pointer
        if w is None:
            return None
        return (w.winfo_rootx() - self.root.winfo_rootx() + w.winfo_width() // 2,
                w.winfo_rooty() - self.root.winfo_rooty() + w.winfo_height() // 2)

    def wait(self, ms: int) -> None:
        """ms のあいだ画面を動かしながら撮る（realtime でなければ待たずに 1 回だけ撮る）。"""
        if not self.realtime:
            self.shot()
            time.sleep(0.005)
            return
        end = time.time() + ms / 1000
        while time.time() < end:
            t = time.time()
            self.shot()
            time.sleep(max(0.0, FRAME_MS / 1000 - (time.time() - t)))

    def save_png(self, out_dir: Path, prefix: str) -> int:
        """撮った画面を 1 枚ずつ PNG で保存する（--snap）。"""
        out_dir.mkdir(parents=True, exist_ok=True)
        for n, img in enumerate(self.frames, 1):
            img.save(out_dir / f"{prefix}_{n:02}.png")
        return len(self.frames)

    def save(self, out: Path) -> int:
        from PIL import Image
        out.parent.mkdir(parents=True, exist_ok=True)
        palette = self.frames[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in self.frames]
        self.durations[-1] += 3000   # 最後の画面で止めて見せる
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=self.durations,
                       loop=0, optimize=True, disposal=1)
        return len(frames)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for p in (["C:/Windows/Fonts/YuGothB.ttc"] if bold else []) + ["C:/Windows/Fonts/YuGothM.ttc",
                                                                 "C:/Windows/Fonts/meiryo.ttc"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def compose(window, title: str, caption: str, pointer: tuple[int, int] | None):
    """撮影した画面に、Windows 11 風のタイトルバーと、下に説明の帯を付け、まわりを黒い枠で囲む。

    画面が白っぽく、README などの白い背景と境目が分からないので、枠（FRAME_PX）で区切る。
    """
    from PIL import Image, ImageDraw, ImageOps
    bar_h, cap_h = 34, 64
    w, h = window.size
    img = Image.new("RGB", (w, bar_h + h + cap_h), (250, 250, 250))
    img.paste(window, (0, bar_h))
    d = ImageDraw.Draw(img)

    # タイトルバー（左にアプリ名、右に 最小化・最大化・閉じる）
    d.text((14, bar_h // 2), "FileMove", font=_font(15), fill=(30, 30, 30), anchor="lm")
    fg, cy, x = (60, 60, 60), bar_h // 2, w - 128
    d.line((x, cy, x + 10, cy), fill=fg)
    x += 46
    d.rectangle((x, cy - 5, x + 10, cy + 5), outline=fg)
    x += 46
    d.line((x, cy - 5, x + 10, cy + 5), fill=fg)
    d.line((x, cy + 5, x + 10, cy - 5), fill=fg)

    # マウスの矢印
    if pointer:
        px, py = pointer[0], pointer[1] + bar_h
        arrow = [(px, py), (px, py + 22), (px + 6, py + 17), (px + 10, py + 26),
                 (px + 14, py + 24), (px + 10, py + 15), (px + 17, py + 15)]
        d.polygon(arrow, fill=(255, 255, 255), outline=(0, 0, 0))

    # 説明の帯（1 行目: 何をしたいか、2 行目: 今していること）
    top = bar_h + h
    d.rectangle((0, top, w, top + cap_h), fill=(32, 32, 32))
    d.text((16, top + 18), title, font=_font(17, bold=True), fill=(97, 214, 214), anchor="lm")
    d.text((16, top + 45), caption, font=_font(15), fill=(235, 235, 235), anchor="lm")
    return ImageOps.expand(img, border=FRAME_PX, fill=(0, 0, 0))


# ---------------------------------------------------------------- 操作

class Driver:
    """App を人が操作しているように動かす。"""

    def __init__(self, app: App, rec: Recorder, sample: Sample):
        self.app, self.rec, self.sample = app, rec, sample

    def say(self, text: str, ms: int = 900) -> None:
        self.rec.caption = text
        self.rec.pointer = None
        self.rec.wait(ms)

    def point(self, widget: tk.Widget, text: str, ms: int = 700) -> None:
        self.rec.caption = text
        self.rec.pointer = widget
        self.rec.wait(ms)

    def click(self, widget: tk.Widget, text: str, action: Callable[[], None]) -> None:
        self.point(widget, text)
        action()
        self.rec.wait(500)

    def add_source(self, shown: str, drag: bool = False) -> None:
        real = self.sample.real(shown)
        if drag:
            self.click(self.app.src_list, f"エクスプローラーから {shown} を ① 対象フォルダにドラッグ＆ドロップ",
                       lambda: self.app.drop_sources("{" + str(real) + "}"))
        else:
            self.click(self.app.add_folder_btn, f"「フォルダを追加…」で ① 対象フォルダに {shown} を選ぶ",
                       lambda: self.app.add_source(real))

    def set_dest(self, shown: str) -> None:
        self.click(self.app.dest_btn, f"「参照…」で ② 保存先フォルダに {shown} を選ぶ",
                   lambda: self.app.set_dest(self.sample.real(shown)))

    def type_into(self, entry: tk.Widget, var: tk.StringVar, text: str, caption: str) -> None:
        self.point(entry, caption, ms=400)
        var.set("")
        for i in range(1, len(text) + 1):
            var.set(text[:i])
            self.rec.wait(70)
        self.rec.wait(400)

    def choose_move(self) -> None:
        self.click(self.app.move_radio, "③ は「移動」のまま（元のファイルは消える）", lambda: self.app.move_var.set(True))

    def choose_copy(self) -> None:
        self.click(self.app.copy_radio, "③ で「コピー」を選ぶ（元のファイルも残す）", lambda: self.app.move_var.set(False))

    def preview(self, note: str = "一覧で、どのファイルがどこへ行くかを確かめる（まだ何も変えていない）") -> None:
        self.click(self.app.preview_btn, "「確認」を押す", lambda: self.app.start(dry_run=True))
        self._wait_job("確認中…")
        self.say(note, 1800)

    def execute(self) -> None:
        self.click(self.app.run_btn, "「実行」を押す" + ("（確認の画面で「はい」）" if self.app.move_var.get() else ""),
                   lambda: self.app.start(dry_run=False))
        self._wait_job("実行中…（太い進捗バーが進む）")

    def run(self) -> None:
        """確認 → 実行（実行は確認の後でないと押せない）。"""
        self.preview()
        self.execute()

    def _wait_job(self, caption: str) -> None:
        self.rec.caption = caption
        self.rec.pointer = None
        while self.app.job and (self.app.job.running or not self.app.job.events.empty()):
            self.rec.wait(FRAME_MS)
        self.rec.wait(300)


# ---------------------------------------------------------------- パターン

@pattern("G1 何が起きるか、先に確認したい", gif="g01_dry-run")
def g1(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Downloads")
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\整理")
    d.point(d.app.run_btn, "「確認」を押すまで、「実行」は押せない", 1200)
    d.preview("一覧に、どのファイルがどこへ行くかが出る。まだ何も変えていない")
    d.point(d.app.run_btn, "内容を確かめたら「実行」を押せるようになる", 1800)


@pattern("G2 ダウンロードのファイルを、デスクトップへ移したい", gif="g02_move")
def g2(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Downloads", drag=True)
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\整理")
    d.choose_move()
    d.run()
    d.say("完了。一覧とログは閉じて保存した。(1) 付きの重複も消えている", 2500)
    d.point(d.app.report_btn, "「結果を開く」で、保存した結果の一覧（Excel で開ける）を見られる", 1500)


@pattern("G3 書類と写真を、別々のフォルダに振り分けたい", gif="g03_sort")
def g3(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Downloads")
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\書類")
    d.type_into(d.app.exts_entry, d.app.exts_var, "pdf,docx,xlsx,txt", "④ の種類（拡張子）に書類の拡張子を入れる")
    d.run()
    d.add_source(f"{HOME_SHOWN}\\Downloads")
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\写真")
    d.type_into(d.app.exts_entry, d.app.exts_var, "jpg", "種類（拡張子）を jpg に変える")
    d.run()
    d.say("書類は Desktop\\書類、写真は Desktop\\写真 に分かれた", 2500)


@pattern("G4 2 回ダウンロードした (1) 付きのファイルを消したい", gif="g04_dedupe")
def g4(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Downloads")
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\写真")
    d.type_into(d.app.exts_entry, d.app.exts_var, "jpg", "④ の種類（拡張子）に jpg を入れる")
    d.point(d.app.dedupe_check, "「(1) 付きの重複ファイルを削除する」は最初からオン", 1200)
    d.preview("一覧に「→ 重複を削除します」が出る")
    d.execute()
    d.say("IMG_0001 (1).jpg は IMG_0001.jpg と中身が同じなので消えた", 2500)


@pattern("G5 保存先に同じ名前のファイルがある", gif="g05_same-name",
         extra=[("Desktop/整理/メモ.txt", "前に書いたメモ\n", 30)])
def g5(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Downloads")
    d.set_dest(f"{HOME_SHOWN}\\Desktop\\整理")
    d.choose_copy()
    d.type_into(d.app.exts_entry, d.app.exts_var, "txt", "種類に txt を入れる（デスクトップにも別の メモ.txt がある）")
    d.run()
    d.say("「同名ファイルの処理」は既定で「連番を付けて保存」。メモ_1.txt として両方残る", 2500)


@pattern("G6 C ドライブが一杯なので、写真を D ドライブへ移したい", gif="g06_drive")
def g6(d: Driver) -> None:
    d.add_source(f"{HOME_SHOWN}\\Pictures\\旅行")
    d.set_dest(f"{D_SHOWN}\\写真\\旅行")
    d.choose_move()
    d.run()
    d.say("ドライブをまたいでも、同じ操作で移せる（USB メモリや外付け HDD も同じ）", 2500)


# ---------------------------------------------------------------- 本体

def _dpi_aware() -> None:
    """画面の拡大率に関係なく、撮影の座標とウィンドウの座標をそろえる（Windows）。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def play(index: int, work: Path, *, record: bool, out_dir: Path = OUT_DIR, slow: bool = True,
         hidden: bool = False, snap: Path | None = None) -> Path | None:
    """index 番目（1 から）のパターンを実行する。record なら GIF を保存してそのパスを返す。
    slow は進捗が見えるよう転送をゆっくりにする。hidden はウィンドウを出さない（テスト用）。
    snap を渡すと、待たずに動かして、変わった画面をそのフォルダに PNG で保存する。"""
    title, fn, gif, extra = PATTERNS[index - 1]
    sample = Sample(work)
    sample.build(extra)

    real_transfer = mf.transfer_file
    if slow:
        def transfer(*a, **kw):
            time.sleep(SLOW_PER_FILE)
            return real_transfer(*a, **kw)
        mf.transfer_file = transfer

    root = make_root()
    if hidden:
        root.withdraw()
    try:
        apply_theme(root)
        app = App(root, ledger_path=sample.work / "ledger.jsonl", report_dir=sample.work / "履歴",
                  display=sample.shown,
                  parse=lambda s: str(sample.real(s)) if s.startswith((HOME_SHOWN, D_SHOWN)) else s,
                  confirm=lambda *a: True, opener=lambda p: None)
        root.geometry("860x940+40+20")
        if record or snap:
            root.attributes("-topmost", True)   # 撮影するので手前に出す
        rec = Recorder(root, title, enabled=record or snap is not None, realtime=not (hidden or snap))
        driver = Driver(app, rec, sample)
        driver.say("ダウンロード → デスクトップの整理（FileMove の画面）", 800)
        fn(driver)
        if snap:
            n = rec.save_png(snap, f"g{index}")
            print(f"{snap / f'g{index}_*.png'}  {n} 枚")
            return None
        if record:
            out = out_dir / f"demo_{gif}.gif"
            n = rec.save(out)
            print(f"{out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}  {n} フレーム / "
                  f"{out.stat().st_size // 1024}KB")
            return out
        return None
    finally:
        mf.transfer_file = real_transfer
        root.destroy()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FileMove の GUI のデモ（録画して GIF にする）")
    ap.add_argument("patterns", nargs="*", type=int, help=f"パターンの番号 1〜{len(PATTERNS)}（省略時は全部）")
    ap.add_argument("--show", action="store_true", help="録画せず、画面で動きだけ見る")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="GIF の出力先フォルダ")
    ap.add_argument("--snap", type=Path, metavar="DIR", help="GIF を作らず、変わった画面を DIR に PNG で保存する")
    args = ap.parse_args(argv)
    if any(not 1 <= i <= len(PATTERNS) for i in args.patterns):
        ap.error(f"パターンの番号は 1〜{len(PATTERNS)} で指定してください")

    _dpi_aware()
    with tempfile.TemporaryDirectory() as tmp:
        for i in args.patterns or range(1, len(PATTERNS) + 1):
            play(i, Path(tmp) / "work", record=not (args.show or args.snap), out_dir=args.out,
                 slow=not args.snap, snap=args.snap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
