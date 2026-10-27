# -*- coding: utf-8 -*-
"""
FileMove の画面（tkinter）。

    python -m gui        # リポジトリのフォルダで実行する（Windows ならダブルクリックで gui/FileMove.pyw でも可）
    FileMove.exe         # exe 化したもの（tools/build_exe.py で作る）
    FileMove.exe --self-test   # 画面を出さずに、確認 → 実行まで動くかを確かめる（終了コード 0 なら正常）

上から「① 対象フォルダ → ② 保存先フォルダ → ③ 処理方法 → ④ 詳細設定 → 確認 → 実行」の順に並べる。
「実行」は「確認」で一覧を見てからでないと押せず、実行するのは確認した一覧のファイルだけ
（どのファイルを移すかは、人が一覧を見て決める）。結果は大きな見出しと太い進捗バー、
1 ファイルずつの一覧（ログは別のタブ）で見せ、実行が終わったら一覧とログをファイルに保存する。

入力の確認・実行・結果の言葉・保存は gui/runner.py（その先は migrate_files.run_migration()）に任せ、
ここでは画面の部品と、ボタン・進捗の表示だけを扱う。
見た目（Windows 11 風の sv-ttk）とドラッグ＆ドロップ（tkinterdnd2）は、入っていれば使う。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import migrate_files as mf
from gui.runner import (ON_EXISTS, Form, MigrationJob, Outcome, app_dir, clean_path, dedupe_rows,
                        default_report_dir, describe, outcome, save_report)

POLL_MS = 50   # 別スレッドの進捗を取りに行く間隔

# 結果の見出しの色と印（Windows 11 の色に合わせる）
LEVELS = {
    "ok": ("✔", "#0f7b0f"),
    "info": ("ℹ", "#005fb8"),
    "warn": ("⚠", "#9d5d00"),
    "error": ("✖", "#c42b1c"),
}
# 結果の一覧の行の色（文字, 背景）
ROW_COLORS = {
    "ok": ("#1c1c1c", ""),
    "plan": ("#005fb8", ""),
    "muted": ("#6b6b6b", ""),
    "warn": ("#7a4600", "#fff4ce"),
    "error": ("#a4262c", "#fde7e9"),
}
GRAY = "#6b6b6b"
NBSP = "\u00a0"   # 折り返さない空白
ACCENT = "#005fb8"


def open_path(path: Path) -> None:
    """フォルダやファイルを、エクスプローラー（Mac は Finder など）や関連付けられたアプリで開く。"""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class ThickBar(tk.Canvas):
    """太くて見やすい進捗バー（ttk の進捗バーは細いので描く）。value / maximum で読める。"""

    def __init__(self, master, *, height: int = 14, background: str = "#fafafa"):
        super().__init__(master, height=height, highlightthickness=0, borderwidth=0, background=background)
        self.value, self.maximum, self.color = 0, 1, ACCENT
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, value: int, maximum: int | None = None, color: str | None = None) -> None:
        if maximum is not None:
            self.maximum = max(maximum, 1)
        self.value = min(value, self.maximum)
        self.color = color or self.color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), int(self.cget("height"))
        self.create_rectangle(0, 0, w, h, fill="#e1e1e1", width=0)
        if self.value:
            self.create_rectangle(0, 0, w * self.value / self.maximum, h, fill=self.color, width=0)


class App:
    """FileMove のメイン画面。

    display / parse は表示上のパスと実際のパスの変換（デモで C:\\Users\\user のように見せるため）。
    confirm は「移動してよいか」などの確認、opener は「保存先を開く」「結果を開く」、
    report_dir は結果の一覧とログを保存する場所（テストやデモでは差し替える）。
    """

    def __init__(self, root: tk.Tk, *, ledger_path: Path | None = None, report_dir: Path | None = None,
                 display: Callable[[str], str] = lambda s: s,
                 parse: Callable[[str], str] = lambda s: s,
                 confirm: Callable[[str, str], bool] = messagebox.askyesno,
                 opener: Callable[[Path], None] = open_path):
        self.root = root
        self.ledger_path = ledger_path
        self.report_dir = report_dir or default_report_dir()
        self.display, self.parse, self.confirm, self.opener = display, parse, confirm, opener
        self.sources: list[Path] = []
        self.job: MigrationJob | None = None
        self.last_result: mf.MigrationResult | None = None
        self.last_outcome: Outcome | None = None
        self.last_report: tuple[Path, Path] | None = None
        self.rows: list = []           # 結果の一覧の行（runner.Row）
        self._preview: tuple[Form, frozenset[str]] | None = None   # 確認した入力と、一覧に出たファイル
        self._preview_srcs: set[str] = set()
        self._started_form: Form | None = None
        self._log_lines: list[str] = []
        self._dest_dir: Path | None = None
        self._closing = False

        root.title("FileMove")
        setup_fonts(root)
        self.bg = ttk.Style(root).lookup("TFrame", "background") or "#fafafa"
        self._build()
        self.can_drop = self._setup_drop()
        self._update_hint()
        self._show(Outcome("info", "はじめに",
                           "① 対象フォルダと ② 保存先フォルダを選び、「確認」で移すファイルを一覧で確かめてから、"
                           "「実行」を押してください。"))
        for var in (self.dest_var, self.move_var, self.on_exists_var, self.exts_var, self.since_var,
                    self.dedupe_var):
            var.trace_add("write", lambda *a: self._invalidate())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._on_error
        self._fit_window()

    # ------------------------------------------------------------ 画面の組み立て

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=(20, 12, 20, 14))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        self.main = main

        ttk.Label(main, text="FileMove", font="FileMoveTitle").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="フォルダの構成を保ったまま、ファイルを移動・コピーします",
                  foreground=GRAY).grid(row=1, column=0, sticky="w")

        # ① 対象フォルダ
        self._step(main, 2, "① 対象フォルダ", "移動させたいファイルがある場所")
        src = ttk.Frame(main)
        src.grid(row=3, column=0, sticky="ew")
        src.columnconfigure(0, weight=1)
        box = ttk.Frame(src, style="Card.TFrame", padding=6)
        box.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.src_list = tk.Listbox(box, height=3, activestyle="none", selectmode="extended", relief="flat",
                                   borderwidth=0, highlightthickness=0, background="#ffffff",
                                   foreground="#1c1c1c", selectbackground="#cce4f7", selectforeground="#1c1c1c")
        self.src_list.pack(fill="both", expand=True)
        self.src_list.bind("<Delete>", lambda e: self._remove_selected())
        self.src_hint = ttk.Label(box, foreground="#8a8a8a", background="#ffffff", anchor="center")
        self.add_folder_btn = ttk.Button(src, text="フォルダを追加…", command=self._ask_folder)
        self.add_folder_btn.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.remove_btn = ttk.Button(src, text="選んだフォルダを外す", command=self._remove_selected)
        self.remove_btn.grid(row=1, column=1, sticky="new", padx=(10, 0), pady=(4, 0))

        # ② 保存先フォルダ
        self._step(main, 4, "② 保存先フォルダ", "移動したいファイルの置き場所")
        dst = ttk.Frame(main)
        dst.grid(row=5, column=0, sticky="ew")
        dst.columnconfigure(0, weight=1)
        self.dest_var = tk.StringVar()
        self.dest_entry = ttk.Entry(dst, textvariable=self.dest_var)
        self.dest_entry.grid(row=0, column=0, sticky="ew")
        self.dest_btn = ttk.Button(dst, text="参照…", command=self._ask_dest)
        self.dest_btn.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        dst.columnconfigure(1, minsize=self.remove_btn.winfo_reqwidth())

        # ③ 処理方法
        self._step(main, 6, "③ 処理方法")
        modes = ttk.Frame(main)
        modes.grid(row=7, column=0, sticky="ew")
        self.move_var = tk.BooleanVar(value=True)
        self.move_radio = ttk.Radiobutton(modes, text="移動（元のファイルは消えます）", variable=self.move_var,
                                          value=True, style="Toggle.TButton", width=26)
        self.move_radio.pack(side="left", ipady=3)
        self.copy_radio = ttk.Radiobutton(modes, text="コピー（元のファイルも残します）", variable=self.move_var,
                                          value=False, style="Toggle.TButton", width=26)
        self.copy_radio.pack(side="left", padx=(8, 0), ipady=3)

        # ④ 詳細設定（最初から出しておく）
        self._step(main, 8, "④ 詳細設定")
        self.more = ttk.Frame(main)
        self.more.grid(row=9, column=0, sticky="ew")
        self._build_more(self.more)

        # 確認 → 実行
        bar = ttk.Frame(main)
        bar.grid(row=10, column=0, sticky="ew", pady=(14, 0))
        self.preview_btn = ttk.Button(bar, text="確認", width=10, command=lambda: self.start(dry_run=True))
        self.preview_btn.pack(side="left", ipady=4)
        ttk.Label(bar, text="→", font="FileMoveIcon", foreground=GRAY).pack(side="left", padx=10)
        self.run_btn = ttk.Button(bar, text="実行", style="Accent.TButton", width=10,
                                  command=lambda: self.start(dry_run=False))
        self.run_btn.pack(side="left", ipady=4)
        self.cancel_btn = ttk.Button(bar, text="中止", command=self.cancel)
        self.cancel_btn.pack(side="left", padx=(16, 0), ipady=4)
        self.step_hint = ttk.Label(bar, foreground=GRAY)
        self.step_hint.pack(side="left", padx=(16, 0))

        # 結果（大きな見出し・太い進捗バー）
        res = ttk.Frame(main, padding=(0, 14, 0, 0))
        res.grid(row=11, column=0, sticky="ew")
        res.columnconfigure(1, weight=1)
        self.icon_label = ttk.Label(res, font="FileMoveIcon", width=2)
        self.icon_label.grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        self.title_label = ttk.Label(res, textvariable=self.title_var, font="FileMoveHeading")
        self.title_label.grid(row=0, column=1, sticky="w")
        self.detail_var = tk.StringVar()
        self.detail_label = ttk.Label(res, textvariable=self.detail_var, font="FileMoveBody",
                                      wraplength=760, justify="left")
        res.bind("<Configure>", lambda e: self.detail_label.configure(wraplength=max(e.width - 10, 300)))
        self.detail_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))
        prog = ttk.Frame(res)
        prog.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.progress = ThickBar(prog, background=self.bg)
        self.progress.pack(side="left", fill="x", expand=True)
        self.count_var = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.count_var, font="FileMoveCount", width=10,
                  anchor="e").pack(side="left", padx=(10, 0))
        acts = ttk.Frame(res)
        acts.grid(row=0, column=2, sticky="e")
        self.open_btn = ttk.Button(acts, text="保存先を開く", command=self.open_dest)
        self.open_btn.pack(side="left")
        self.report_btn = ttk.Button(acts, text="結果を開く", command=self.open_report)
        self.report_btn.pack(side="left", padx=(8, 0))
        self.open_btn.pack_forget()
        self.report_btn.pack_forget()

        # 結果の一覧とログ
        self.tabs = ttk.Notebook(main)
        self.tabs.grid(row=12, column=0, sticky="nsew", pady=(10, 0))
        main.rowconfigure(12, weight=1)
        listf = ttk.Frame(self.tabs)
        self.tree = ttk.Treeview(listf, columns=("state", "name", "note"), show="headings", height=6)
        for col, text, width, stretch in (("state", "状態", 150, False), ("name", "ファイル", 240, True),
                                          ("note", "保存先・理由", 320, True)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        for tag, (fg, bg) in ROW_COLORS.items():
            self.tree.tag_configure(tag, foreground=fg, **({"background": bg} if bg else {}))
        scroll = ttk.Scrollbar(listf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tabs.add(listf, text="結果の一覧")

        logf = ttk.Frame(self.tabs)
        self.log_text = tk.Text(logf, height=6, wrap="none", state="disabled", relief="flat", borderwidth=0,
                                font="TkDefaultFont", spacing1=1, background="#ffffff", foreground="#1c1c1c")
        lscroll = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lscroll.set)
        lscroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.tabs.add(logf, text="ログ")
        self._update_buttons()

    def _build_more(self, f: ttk.Frame) -> None:
        f.columnconfigure(2, weight=1)
        gray = dict(foreground=GRAY)
        ttk.Label(f, text="同名ファイルの処理").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.on_exists_var = tk.StringVar(value=next(iter(ON_EXISTS)))
        self.on_exists_combo = ttk.Combobox(f, textvariable=self.on_exists_var, values=list(ON_EXISTS),
                                            state="readonly", width=20)
        self.on_exists_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="保存先に同名の別ファイルがあるとき（中身が同じなら何もしません）", **gray).grid(
            row=0, column=2, sticky="w", padx=10)

        ttk.Label(f, text="種類（拡張子）").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.exts_var = tk.StringVar()
        self.exts_entry = ttk.Entry(f, textvariable=self.exts_var, width=22)
        self.exts_entry.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="例: pdf,jpg（空ならすべて。desktop.ini・ダウンロード途中のファイルなどは移しません）",
                  **gray).grid(row=1, column=2, sticky="w", padx=10, pady=(6, 0))

        ttk.Label(f, text="期間").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.since_var = tk.StringVar()
        self.since_entry = ttk.Entry(f, textvariable=self.since_var, width=22)
        self.since_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="例: 30d（30 日以内に更新されたもの。空なら絞りません）", **gray).grid(
            row=2, column=2, sticky="w", padx=10, pady=(6, 0))

        self.dedupe_var = tk.BooleanVar(value=True)
        self.dedupe_check = ttk.Checkbutton(f, text="「(1)」付きの重複ファイルを削除する（中身が同じものだけ）",
                                            variable=self.dedupe_var)
        self.dedupe_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _step(self, parent: ttk.Frame, row: int, text: str, note: str = "") -> None:
        f = ttk.Frame(parent)
        f.grid(row=row, column=0, sticky="w", pady=(10, 4))
        ttk.Label(f, text=text, font="FileMoveStep").pack(side="left")
        if note:
            ttk.Label(f, text=f"（{note}）", foreground=GRAY).pack(side="left", padx=(6, 0))

    def _fit_window(self) -> None:
        """画面に収まる大きさで開く（拡大率が大きいノート PC でも下が切れないように）。"""
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 820)
        h = min(self.root.winfo_reqheight() + 120, int(self.root.winfo_screenheight() * 0.9))
        self.root.minsize(min(w, 760), min(h, 600))
        self.root.geometry(f"{w}x{h}")

    def _update_hint(self) -> None:
        """対象フォルダが空のときは、一覧の上に操作の案内を出す。"""
        if self.sources:
            self.src_hint.place_forget()
            return
        self.src_hint.configure(text="ここにフォルダをドラッグ＆ドロップ" if self.can_drop
                                else "右の「フォルダを追加…」で選んでください")
        self.src_hint.place(relx=0.5, rely=0.5, anchor="center")

    def _update_buttons(self) -> None:
        running = bool(self.job and self.job.running)
        self.preview_btn.configure(state="disabled" if running else "normal")
        self.run_btn.configure(state="normal" if self._preview and not running else "disabled")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        self.step_hint.configure(text="" if running else
                                 "一覧を確かめたら「実行」を押してください" if self._preview else
                                 "まず「確認」で、移すファイルを一覧で確かめます")

    # ------------------------------------------------------------ 入力

    def _setup_drop(self) -> bool:
        """tkinterdnd2 で起動していれば、対象フォルダ・保存先フォルダにドラッグ＆ドロップできるようにする。"""
        try:
            from tkinterdnd2 import DND_FILES
            self.root.tk.call("package", "present", "tkdnd")
        except Exception:
            return False
        for w in (self.src_list, self.src_hint):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", lambda e: (self.drop_sources(e.data), e.action)[1])
        self.dest_entry.drop_target_register(DND_FILES)
        self.dest_entry.dnd_bind("<<Drop>>", lambda e: (self.drop_dest(e.data), e.action)[1])
        return True

    def drop_sources(self, data: str) -> None:
        """ドロップされたもの（"{C:/a b} C:/c" の形）のうち、フォルダを対象フォルダに加える。"""
        for p in self.root.tk.splitlist(data):
            self.add_source(Path(p))

    def drop_dest(self, data: str) -> None:
        paths = [Path(p) for p in self.root.tk.splitlist(data)]
        if paths:
            self.set_dest(paths[0] if paths[0].is_dir() else paths[0].parent)

    def _ask_folder(self) -> None:
        path = filedialog.askdirectory(title="対象フォルダを選ぶ（移動させたいファイルがある場所）")
        if path:
            self.add_source(Path(path))

    def _ask_dest(self) -> None:
        path = filedialog.askdirectory(title="保存先フォルダを選ぶ（移動したいファイルの置き場所）")
        if path:
            self.set_dest(Path(path))

    def add_source(self, path: Path) -> bool:
        """対象フォルダに加える。フォルダでないもの・同じものは加えない（加えたら True）。"""
        if not path.is_dir():
            self._show(Outcome("warn", "フォルダだけ追加できます",
                               f"「{path.name}」はフォルダではないため追加しませんでした。"
                               "ファイルが入っているフォルダを追加してください。"))
            return False
        if any(mf._root_id(p) == mf._root_id(path) for p in self.sources):
            return False   # 同じものは 1 回だけ
        self.sources.append(path)
        self.src_list.insert("end", self.display(str(path)) + "\\")
        self._update_hint()
        self._invalidate()
        return True

    def _remove_selected(self) -> None:
        for i in reversed(self.src_list.curselection()):
            self.src_list.delete(i)
            del self.sources[i]
        self._update_hint()
        self._invalidate()

    def _forget_moved_sources(self) -> list[str]:
        """移動して空になった（無くなった）フォルダを、対象フォルダの一覧から外し、その名前を返す。
        移さないファイル（desktop.ini など）だけが残っているフォルダも、空とみなす。"""
        system = mf.FileFilter(excludes=mf.SYSTEM_EXCLUDES)
        gone = []
        for i in reversed(range(len(self.sources))):
            p = self.sources[i]
            if not p.exists() or not any(f.is_file() and not system.excluded(f.name, f.name)
                                         for f in p.rglob("*")):
                gone.insert(0, p.name)
                self.src_list.delete(i)
                del self.sources[i]
        self._update_hint()
        return gone

    def set_dest(self, path: Path) -> None:
        self.dest_var.set(self.display(str(path)))

    def form(self) -> Form:
        return Form(sources=list(self.sources), dest=self.parse(clean_path(self.dest_var.get())),
                    move=self.move_var.get(), on_exists=ON_EXISTS[self.on_exists_var.get()],
                    exts=self.exts_var.get(), since=self.since_var.get(), dedupe=self.dedupe_var.get())

    def _invalidate(self) -> None:
        """入力が変わったら、前の確認は使えないので「実行」を押せなくする。"""
        if self.job and self.job.running:
            return
        if self._preview:
            self._preview = None
            self._show(Outcome("info", "設定が変わりました",
                               "もう一度「確認」を押して、移すファイルを一覧で確かめてください。"))
        self._update_buttons()

    # ------------------------------------------------------------ 実行

    def start(self, *, dry_run: bool) -> None:
        if self.job and self.job.running:
            return
        form = self.form()
        if not dry_run:
            if not self._preview or self._preview[0] != form:
                self._show(Outcome("warn", "先に「確認」を押してください",
                                   "移すファイルを一覧で確かめてから実行します。"))
                return
            form.only = self._preview[1]   # 確認した一覧のファイルだけ（後から増えたものは移さない）
        try:
            job = MigrationJob(form, dry_run=dry_run, ledger_path=self.ledger_path)
        except ValueError as e:
            self._show(Outcome("warn", "入力を確かめてください", str(e)))
            return
        verb = "移動" if form.move else "コピー"
        if form.move and not dry_run and not self.confirm(
                "移動の確認", f"確認した {len(form.only)} 件を移動します。\n"
                              "保存先で中身を確かめた後に、元のファイルを削除します。実行しますか？"):
            return

        self._clear()
        self._started_form = self.form()
        self._preview_srcs = set()
        self._dest_dir = job.options["dst"]
        self.progress.set(0, 1, ACCENT)
        self.count_var.set("")
        self._show(Outcome("info", "確認しています…" if dry_run else f"{verb}しています…",
                           "終わるまでお待ちください。" + ("" if dry_run else "「中止」で途中で止められます。")))
        self.tabs.grid()
        self.tabs.select(0)
        self.job = job
        job.start()
        self._update_buttons()
        self.root.after(POLL_MS, self._poll)

    def cancel(self) -> None:
        if self.job and self.job.running:
            self.job.cancel()
            self._show(Outcome("warn", "中止しています…", "今のファイルが終わったら止まります。"))

    def close(self) -> None:
        """ウィンドウを閉じる。処理中なら確かめて、中止してから閉じる。"""
        if self.job and self.job.running:
            if not self.confirm("閉じる確認", "まだ処理中です。中止して閉じますか？\n（今のファイルが終わってから閉じます）"):
                return
            self._closing = True
            self.cancel()
            return
        self.root.destroy()

    def open_dest(self) -> None:
        if self._dest_dir and self._dest_dir.is_dir():
            self.opener(self._dest_dir)

    def open_report(self) -> None:
        if self.last_report and self.last_report[0].exists():
            self.opener(self.last_report[0])

    def _poll(self) -> None:
        job = self.job
        logs, rows_before, finished = [], len(self.rows), False
        for kind, payload in job.drain():
            if kind == "log":
                logs.append(self.display(payload))
            elif kind == "progress":
                self._on_progress(payload)
            elif kind == "finished":
                self._append_log(logs)   # 保存するログに最後の行まで入れてから終える
                logs = []
                self._finish(payload)
                finished = True
            elif kind == "error":
                self._show(Outcome("error", "エラーが起きました", str(payload)))
        # 何千件でも固まらないよう、ログと一覧の表示の更新は取り出した分をまとめて 1 回にする
        self._append_log(logs)
        if len(self.rows) > rows_before and not finished:
            self.tree.see(self.tree.get_children()[-1])
        if job.running or not job.events.empty():
            self.root.after(POLL_MS, self._poll)
            return
        self._update_buttons()
        if self._closing:
            self.root.destroy()

    def _on_progress(self, ev: mf.ProgressEvent) -> None:
        if ev.status == "scanned":
            self.progress.set(0, ev.total)
            self.count_var.set(f"0 / {ev.total} 件")
            return
        if ev.src:
            self._preview_srcs.add(ev.src)
        self.progress.set(ev.index)
        self.count_var.set(f"{ev.index} / {ev.total} 件")
        row = describe(ev, move=self.job.options["move"], dry_run=self.job.dry_run, display=self.display)
        if row:
            self._add_row(row)

    def _finish(self, result: mf.MigrationResult) -> None:
        job = self.job
        move = job.options["move"]
        self.last_result = result
        for row in dedupe_rows(result, dry_run=job.dry_run, root=job.options["dst"], display=self.display):
            self._add_row(row)
        kept = sum(1 for r in self.rows if r.tag == "warn")
        self.tree.yview_moveto(0)   # 一覧は先頭から読めるようにする
        o = outcome(result, dry_run=job.dry_run, move=move, kept=kept)
        notes = [o.detail] if o.detail else []

        if job.dry_run:
            # 移すもの（重複の削除を含む）がある確認だけを、実行に使える確認とする
            has_work = result.copied or result.sources_removed or (result.dedupe and result.dedupe.removed)
            # 確認中に入力が変わっていたら、その確認は使わない
            if not result.cancelled and has_work and self._started_form == self.form():
                self._preview = (self._started_form, frozenset(self._preview_srcs))
        else:
            self._preview = None   # 実行したら、次はまた確認から
            if move:
                gone = self._forget_moved_sources()
                if gone:   # 一覧から消えた理由が分かるように書いておく
                    notes.append("、".join(f"「{n}」" for n in gone) + " は空になったので ① から外しました。")
            try:
                self.last_report = save_report(self.rows, "\n".join(self._log_lines) + "\n", self.report_dir,
                                               move=move)
                notes.append("結果の一覧とログを保存しました（「結果を開く」で見られます）。")
            except OSError as e:
                self.last_report = None
                notes.append(f"結果の保存に失敗しました: {e}")
            if self.last_report:
                self.report_btn.pack(side="left", padx=(8, 0))
            if self._dest_dir and self._dest_dir.is_dir():
                self.open_btn.pack(side="left", before=self.report_btn if self.last_report else None)
            if o.level == "ok":
                self.tabs.grid_remove()   # 終わったら一覧とログは閉じる（保存してある）
        o = Outcome(o.level, o.title, "".join(n if n.endswith("。") else n + "。" for n in notes))
        self._show(o)
        self.progress.set(self.progress.maximum if not result.cancelled else self.progress.value,
                          color=LEVELS[o.level][1])
        self._update_buttons()

    # ------------------------------------------------------------ 結果とログ

    def _show(self, o: Outcome) -> None:
        """結果の欄（見出し・説明）を更新する。"""
        self.last_outcome = o
        icon, color = LEVELS[o.level]
        self.icon_label.configure(text=icon, foreground=color)
        self.title_label.configure(foreground=color)
        # Tk は空白で折り返そうとして「① 対象フォルダと ②」のような所で切るので、空白で切らせない
        self.title_var.set(o.title.replace(" ", NBSP))
        self.detail_var.set(o.detail.replace(" ", NBSP))

    def _add_row(self, row) -> None:
        self.rows.append(row)
        self.tree.insert("", "end", values=(row.state, self.display(row.name), row.note), tags=(row.tag,))

    def _clear(self) -> None:
        self.rows.clear()
        self._log_lines.clear()
        self.tree.delete(*self.tree.get_children())
        self.open_btn.pack_forget()
        self.report_btn.pack_forget()
        self.last_report = None
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, lines: list[str]) -> None:
        if not lines:
            return
        self._log_lines.extend(lines)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "".join(line + "\n" for line in lines))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_error(self, exc, val, tb) -> None:
        """画面の処理で想定外のエラーが起きたら、記録して画面に出す（落とさない）。"""
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            app_dir().mkdir(parents=True, exist_ok=True)
            with open(app_dir() / "error.log", "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}")
        except OSError:
            pass
        self._show(Outcome("error", "想定外のエラーが起きました",
                           f"{val}（詳しくは {app_dir() / 'error.log'}）"))
        self._update_buttons()


# ---------------------------------------------------------------- 起動

def setup_fonts(root: tk.Tk) -> None:
    """日本語が読みやすいフォント（Windows は Yu Gothic UI）にそろえ、見出し用のフォントを作る。"""
    from tkinter import font
    families = set(font.families(root))
    family = next((f for f in ("Yu Gothic UI", "Meiryo UI", "Hiragino Sans", "Noto Sans CJK JP")
                   if f in families), font.nametofont("TkDefaultFont", root).actual("family"))
    names = ["TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"]
    names += [n for n in font.names(root) if n.startswith("SunValley")]   # sv-ttk のフォント
    for name in names:
        f = font.nametofont(name, root)
        f.configure(family=family, **({} if name.startswith("SunValley") else {"size": 10}))
    # 見出しは太字の書体があればそれを使う（太字を合成すると字間が崩れる）
    strong = dict(family=family + " Semibold", weight="normal") if family + " Semibold" in families \
        else dict(family=family, weight="bold")
    specs = {"FileMoveTitle": (18, strong), "FileMoveStep": (11, strong), "FileMoveHeading": (18, strong),
             "FileMoveIcon": (22, strong), "FileMoveCount": (12, strong),
             "FileMoveBody": (11, dict(family=family, weight="normal"))}
    # Font オブジェクトは捨てられると Tk 側のフォントも消える（既定のフォントに戻る）ので、ウィンドウに持たせておく
    keep = root.__dict__.setdefault("_filemove_fonts", {})
    for name, (size, style) in specs.items():
        if name in keep:
            keep[name].configure(size=size, **style)
        else:
            keep[name] = font.Font(root, name=name, size=size, exists=name in font.names(root), **style)


def apply_theme(root: tk.Tk) -> None:
    """Windows 11 風の見た目（sv-ttk があれば）と、フォントをそろえる。"""
    try:
        import sv_ttk
        sv_ttk.set_theme("light", root)
        root.configure(background="#fafafa")
    except ImportError:
        pass
    setup_fonts(root)


def dpi_aware() -> None:
    """画面の拡大率が 100% でなくても文字がぼやけないようにする（Windows。ほかでは何もしない）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def make_root() -> tk.Tk:
    """ドラッグ＆ドロップ（tkinterdnd2）が使えればそのウィンドウを、無ければ普通のウィンドウを作る。"""
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk()
    except Exception:
        return tk.Tk()


def self_test(out: Path | None = None) -> int:
    """画面を隠したまま、一時フォルダで「確認 → 実行（移動）」まで行い、動くかを確かめる（exe の確認用）。

    0 なら正常。結果は out（省略時は %LOCALAPPDATA%\\FileMove\\self_test.txt）に書く。
    """
    import tempfile
    import time
    lines, ok = [], True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        lines.append(f"{'OK ' if cond else 'NG '} {name}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        src, dst = work / "Downloads", work / "Desktop" / "整理"
        (src / "資料").mkdir(parents=True)
        for rel, body in {"見積書.pdf": "pdf", "資料/議事録.docx": "docx", "IMG.jpg": "jpg",
                          "IMG (1).jpg": "jpg"}.items():
            (src / rel).write_text(body, encoding="utf-8")
        root = make_root()
        root.withdraw()
        try:
            apply_theme(root)
            app = App(root, ledger_path=work / "ledger.jsonl", report_dir=work / "履歴",
                      confirm=lambda *a: True, opener=lambda p: None)
            check("見た目（sv-ttk）", ttk.Style(root).theme_use() == "sun-valley-light")
            check("ドラッグ＆ドロップ（tkinterdnd2）", app.can_drop)

            def pump() -> None:
                end = time.time() + 60
                while app.job and (app.job.running or not app.job.events.empty()) and time.time() < end:
                    root.update()
                    time.sleep(0.01)
                root.update()

            app.add_source(src)
            app.set_dest(dst)
            check("確認の前は実行できない", app.run_btn.instate(["disabled"]))
            app.start(dry_run=True)
            pump()
            check("確認で一覧が出る", len(app.rows) == 5 and not dst.exists())
            check("確認の後は実行できる", app.run_btn.instate(["!disabled"]))
            app.start(dry_run=False)
            pump()
            moved = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
            check("移動できる", moved == ["IMG.jpg", "見積書.pdf", "資料/議事録.docx"])
            check("元が空になり、空のフォルダも消える", not any(src.iterdir()))
            check("完了と出る", app.last_outcome.level == "ok")
            check("結果とログを保存する", bool(app.last_report) and all(p.exists() for p in app.last_report))
        except Exception:
            ok = False
            lines.append(traceback.format_exc())
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    out = out or app_dir() / "self_test.txt"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines + ["結果: " + ("正常" if ok else "異常")]) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--self-test"]:
        sys.exit(self_test(Path(argv[1]) if len(argv) > 1 else None))
    dpi_aware()
    root = make_root()
    apply_theme(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
