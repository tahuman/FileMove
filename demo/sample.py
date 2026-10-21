# -*- coding: utf-8 -*-
"""
CLI と GUI のデモで共通に使うサンプル。

「ダウンロードにたまったファイルを、デスクトップへ移して整理する」場面のファイルを、
作業フォルダ（work）の中に Windows のホームフォルダに見立てて作る。

    work/Users/user/Downloads   ->  表示上は C:\\Users\\user\\Downloads
    work/D                      ->  表示上は D:

画面やログには表示上のパスを出し、実際の作業フォルダの場所（ユーザー名など）は見せない。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

DAY = 86400
HOME_SHOWN, D_SHOWN = "C:\\Users\\user", "D:"

# (ホームからのパス, 内容, 何日前に更新されたか)。ふだん使う拡張子だけにする
SAMPLE = [
    ("Downloads/見積書_A社.pdf",    "見積書 A社\n" * 300,   3),
    ("Downloads/請求書_10月.pdf",   "請求書 10月\n" * 200,  7),
    ("Downloads/見積書_2025.pdf",   "見積書 2025\n" * 300, 200),
    ("Downloads/売上_2026.xlsx",    "売上\n" * 800,         2),
    ("Downloads/議事録.docx",       "議事録\n" * 400,       5),
    ("Downloads/メモ.txt",          "買い物リスト\n",        1),
    ("Downloads/IMG_0001.jpg",      "JPEG 0001" * 3000,    10),
    ("Downloads/IMG_0001 (1).jpg",  "JPEG 0001" * 3000,    10),   # 同じ写真を 2 回ダウンロードした
    ("Downloads/IMG_0002.jpg",      "JPEG 0002" * 3500,    10),
    ("Pictures/旅行/海_01.jpg",     "JPEG 海01" * 5000,    60),
    ("Pictures/旅行/海_02.jpg",     "JPEG 海02" * 5000,    60),
    ("Pictures/旅行/山_01.jpg",     "JPEG 山01" * 4000,    60),
]
EMPTY_DIRS = ["Desktop"]


class Sample:
    """作業フォルダ work の中のサンプルと、表示上のパスとの変換。"""

    def __init__(self, work: Path):
        self.work = Path(work).resolve()
        self.home = self.work / "Users" / "user"
        self.d_drive = self.work / "D"

    def build(self, extra: list | None = None) -> None:
        """作業フォルダを作り直して、サンプルを置く。extra は SAMPLE と同じ形の追加分。"""
        if self.work.exists():
            shutil.rmtree(self.work)
        self.d_drive.mkdir(parents=True)
        for d in EMPTY_DIRS:
            (self.home / d).mkdir(parents=True, exist_ok=True)
        now = time.time()
        for rel, body, days in SAMPLE + (extra or []):
            p = self.home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            t = now - days * DAY
            os.utime(p, (t, t))

    def real(self, shown: str) -> Path:
        """表示上のパス（C:\\Users\\user\\… / D:\\… / ホームからの相対）を、実際のパスにする。"""
        if shown.startswith(HOME_SHOWN):
            base, rest = self.home, shown[len(HOME_SHOWN):]
        elif shown.startswith(D_SHOWN):
            base, rest = self.d_drive, shown[len(D_SHOWN):]
        else:
            base, rest = self.home, shown
        return base.joinpath(*[p for p in rest.replace("/", "\\").split("\\") if p])

    def shown(self, text: str) -> str:
        """文字列に含まれる実際のパスを、表示上のパスに置き換える。"""
        return text.replace(str(self.d_drive), D_SHOWN).replace(str(self.home), HOME_SHOWN)
