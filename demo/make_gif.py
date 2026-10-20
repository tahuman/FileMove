#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo.py の各ステップを、ターミナル風のアニメーション GIF にする。

    python -m pip install -r requirements-dev.txt   # Pillow が必要
    python demo/make_gif.py              # 全ステップ -> docs/images/demo_*.gif
    python demo/make_gif.py 1 8          # 指定したステップだけ

demo.py をステップごとに --only で実行し、その出力を描画する。
コマンド行（"> python …"）は 1 文字ずつ打ち込むように、それ以外は 1 行ずつ表示する。
作業フォルダは一時ディレクトリを使い、docs/images/ 以外には何も書き込まない。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "docs" / "images"

# 日本語用と英数字用のフォント（それぞれ見つかった最初のもの）。
# 日本語フォントだけだと "~" が上線のように見えるので、英数字は別のフォントで描く
JP_FONTS = [
    "C:/Windows/Fonts/BIZ-UDGothicR.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
]
ASCII_FONTS = [
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]

COLS, ROWS = 96, 34            # 画面の桁数・行数（半角換算）
FONT_SIZE, CELL_W, LINE_H = 16, 9, 22   # CELL_W は半角 1 文字の幅（全角は 2 マス）
PAD, BAR_H = 16, 28

BG, BAR = (30, 30, 36), (52, 52, 60)
COLORS = {
    "text": (220, 220, 220),
    "title": (255, 214, 102),   # ■ ステップ名
    "cmd": (126, 231, 135),     # > python …
    "error": (255, 123, 114),   # 失敗・エラー
    "warn": (255, 170, 90),     # 警告・削除
    "tree": (121, 192, 255),    # フォルダ表示
    "dim": (140, 140, 150),     # 終了コード・補足
}

TYPE_CHARS = 4      # コマンド行を 1 フレームで打ち込む文字数
TYPE_MS, LINE_MS = 35, 70
PAUSE_MS, HOLD_MS = 500, 3500


@dataclass
class Line:
    text: str
    color: str


def width(text: str) -> int:
    """半角を 1、全角（罫線などの曖昧幅も含む）を 2 とした表示幅。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in text)


def wrap(text: str, cols: int = COLS) -> list[str]:
    """表示幅で折り返す。"""
    lines, cur, w = [], "", 0
    for c in text:
        cw = width(c)
        if w + cw > cols:
            lines.append(cur)
            cur, w = "    ", 4   # 折り返した行は字下げする
        cur += c
        w += cw
    lines.append(cur)
    return lines


def classify(text: str) -> str:
    s = text.strip()
    if s.startswith("■"):
        return "title"
    if s.startswith("> python"):
        return "cmd"
    if text.startswith("    "):   # コマンドの出力（ステップの説明文は色分けしない）
        if "失敗" in s and not s.startswith("完了") or "見つかりません" in s or "エラー" in s:
            return "error"
        if "同じ名前になる" in s or "削除" in s or s.startswith("DRY-RUN"):
            return "warn"
    if s.startswith(("📁", "├─", "└─", "│")) or s.endswith("/") or "（まだありません）" in s:
        return "tree"
    if s.startswith("（終了コード") or s.startswith("※"):
        return "dim"
    return "text"


def parse(output: str) -> list[Line]:
    lines: list[Line] = []
    for raw in output.splitlines():
        if not raw.strip() and lines and not lines[-1].text.strip():
            continue   # 連続する空行は 1 行にまとめる
        text = raw.replace("📁 ", "")   # 絵文字はフォントに無いので省く
        lines += [Line(t, classify(raw)) for t in wrap(text)]
    while lines and not lines[-1].text.strip():
        lines.pop()
    return lines


@dataclass
class Fonts:
    jp: ImageFont.FreeTypeFont
    ascii: ImageFont.FreeTypeFont

    def draw(self, d: ImageDraw.ImageDraw, x: int, y: int, text: str, fill) -> None:
        """1 文字ずつマス目に合わせて描く（フォントが混ざっても桁がずれない）。"""
        for c in text:
            if not c.isspace():
                d.text((x, y), c, font=self.ascii if ord(c) < 128 else self.jp, fill=fill)
            x += width(c) * CELL_W


def load_fonts(jp: str | None = None) -> Fonts:
    def first(paths):
        return next((ImageFont.truetype(p, FONT_SIZE) for p in paths if p and Path(p).exists()), None)
    jp_font = first([jp] if jp else JP_FONTS)
    if jp_font is None:
        raise SystemExit("日本語のフォントが見つかりません。--font で .ttf/.ttc を指定してください")
    return Fonts(jp_font, first(ASCII_FONTS) or jp_font)


def frame(shown: list[Line], fonts: Fonts, title: str) -> Image.Image:
    """表示中の行（最後の ROWS 行）を描いた 1 フレーム。"""
    w = PAD * 2 + COLS * CELL_W
    h = BAR_H + PAD * 2 + ROWS * LINE_H
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, BAR_H), fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        x = 14 + i * 20
        d.ellipse((x, 9, x + 11, 20), fill=c)
    fonts.draw(d, (w - width(title) * CELL_W) // 2, 5, title, COLORS["dim"])
    for i, line in enumerate(shown[-ROWS:]):
        fonts.draw(d, PAD, BAR_H + PAD + i * LINE_H, line.text, COLORS[line.color])
    return img


def render(lines: list[Line], out: Path, fonts: Fonts, title: str = "FileMove") -> int:
    """行の並びをアニメーション GIF にして保存し、フレーム数を返す。"""
    frames: list[Image.Image] = []
    durations: list[int] = []
    shown: list[Line] = []

    def add(ms: int) -> None:
        frames.append(frame(shown, fonts, title))
        durations.append(ms)

    for n, line in enumerate(lines):
        if line.color == "cmd":
            # 折り返した 2 行目以降には ">" が無いので、行全体を打ち込む
            prompt, sep, cmd = line.text.partition(">")
            prompt, cmd = (prompt + sep, cmd) if sep else ("", line.text)
            shown.append(Line(prompt, "cmd"))
            for i in range(0, len(cmd), TYPE_CHARS):
                shown[-1] = Line(prompt + cmd[:i + TYPE_CHARS], "cmd")
                add(TYPE_MS)
            if n + 1 == len(lines) or lines[n + 1].color != "cmd":
                durations[-1] = PAUSE_MS   # Enter を押す前の間
        else:
            shown.append(line)
            if line.text.strip():
                add(LINE_MS)
    if frames:
        durations[-1] += HOLD_MS   # 最後の画面で止めて見せる（同じ絵のフレームは足さない）
    else:
        add(HOLD_MS)

    # 全フレームを同じパレットにすると、フレーム間の差分だけが保存されて小さくなる
    palette = frames[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=1)
    return len(frames)


def run_step(index: int, work: Path) -> str:
    """demo.py の 1 ステップを実行して、その出力を返す。"""
    p = subprocess.run([sys.executable, str(HERE / "demo.py"), "--only", str(index), "--work", str(work)],
                       capture_output=True, text=True, encoding="utf-8", check=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return p.stdout


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(HERE))
    import demo  # noqa: E402  ステップ名と GIF のファイル名を取る

    ap = argparse.ArgumentParser(description="デモの各ステップを GIF にする")
    ap.add_argument("steps", nargs="*", type=int, help="ステップ番号（省略時は全部）")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="出力先フォルダ")
    ap.add_argument("--font", help="日本語に使うフォント（.ttf / .ttc）")
    args = ap.parse_args(argv)

    fonts = load_fonts(args.font)
    wanted = args.steps or range(len(demo.STEPS))
    with tempfile.TemporaryDirectory() as tmp:
        for i in wanted:
            title, _, _, gif = demo.STEPS[i]
            out = args.out / f"demo_{gif}.gif"
            n = render(parse(run_step(i, Path(tmp) / "work")), out, fonts, f"FileMove デモ {title.split()[0]}")
            print(f"{out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}"
                  f"  {n} フレーム / {out.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
