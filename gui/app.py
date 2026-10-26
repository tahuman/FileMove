# -*- coding: utf-8 -*-
"""
FileMove の画面（tkinter）。

    python -m gui        # リポジトリのフォルダで実行する（Windows ならダブルクリックで gui/FileMove.pyw でも可）

上から「① 移すもの → ② 移す先 → ③ 移動かコピーか → 実行」の順に並べ、細かい設定は「詳細設定」に畳む。
結果は、ひと目で分かる見出しと、1 ファイルずつの一覧（ログは別のタブ）で見せる。

入力の確認・実行・結果の言葉は gui/runner.py（その先は migrate_files.run_migration()）に任せ、
ここでは画面の部品と、ボタン・進捗の表示だけを扱う。
見た目（Windows 11 風の sv-ttk）とドラッグ＆ドロップ（tkinterdnd2）は、入っていれば使う。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import migrate_files as mf
from gui.runner import ON_EXISTS, Form, MigrationJob, Outcome, clean_path, dedupe_rows, describe, outcome

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


def open_folder(path: Path) -> None:
    """フォルダをエクスプローラー（Mac は Finder など）で開く。"""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class App:
    """FileMove のメイン画面。

    display / parse は表示上のパスと実際のパスの変換（デモで C:\\Users\\user のように見せるため）。
    confirm は「移動してよいか」などの確認、opener は「移す先を開く」（テストやデモでは差し替える）。
    """

    def __init__(self, root: tk.Tk, *, ledger_path: Path | None = None,
                 display: Callable[[str], str] = lambda s: s,
                 parse: Callable[[str], str] = lambda s: s,
                 confirm: Callable[[str, str], bool] = messagebox.askyesno,
                 opener: Callable[[Path], None] = open_folder):
        self.root = root
        self.ledger_path = ledger_path
        self.display, self.parse, self.confirm, self.opener = display, parse, confirm, opener
        self.sources: list[Path] = []
        self.job: MigrationJob | None = None
        self.last_result: mf.MigrationResult | None = None
        self.last_outcome: Outcome | None = None
        self.rows: list = []          # 結果の一覧の行（runner.Row）
        self._dest_dir: Path | None = None
        self._closing = False

        root.title("FileMove")
        root.minsize(760, 720)
        setup_fonts(root)
        self._build()
        self.can_drop = self._setup_drop()
        self._update_hint()
        self._show(Outcome("info", "はじめに", "① 移すもの と ② 移す先 を選び、③ で移動かコピーかを選んでください。"
                                              "「先に確認する」で、何がどこへ行くかを先に見られます。"))
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------ 画面の組み立て

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=(20, 14, 20, 16))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="FileMove", font="FileMoveTitle").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="フォルダの構成を保ったまま、ファイルを移動・コピーします",
                  foreground="#5f5f5f").grid(row=1, column=0, sticky="w", pady=(0, 6))

        # ① 移すもの
        self._step(main, 2, "① 移すもの")
        src = ttk.Frame(main)
        src.grid(row=3, column=0, sticky="ew")
        src.columnconfigure(0, weight=1)
        box = ttk.Frame(src, style="Card.TFrame", padding=6)
        box.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.src_list = tk.Listbox(box, height=4, activestyle="none", selectmode="extended", relief="flat",
                                   borderwidth=0, highlightthickness=0, background="#ffffff",
                                   foreground="#1c1c1c", selectbackground="#cce4f7", selectforeground="#1c1c1c")
        self.src_list.pack(fill="both", expand=True)
        self.src_list.bind("<Delete>", lambda e: self._remove_selected())
        self.src_hint = ttk.Label(box, foreground="#8a8a8a", background="#ffffff", anchor="center")
        self.add_folder_btn = ttk.Button(src, text="フォルダを追加…", command=self._ask_folder)
        self.add_folder_btn.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.add_files_btn = ttk.Button(src, text="ファイルを追加…", command=self._ask_files)
        self.add_files_btn.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=4)
        self.remove_btn = ttk.Button(src, text="選んだものを外す", command=self._remove_selected)
        self.remove_btn.grid(row=2, column=1, sticky="new", padx=(10, 0))

        # ② 移す先
        self._step(main, 4, "② 移す先")
        dst = ttk.Frame(main)
        dst.grid(row=5, column=0, sticky="ew")
        dst.columnconfigure(0, weight=1)
        self.dest_var = tk.StringVar()
        self.dest_entry = ttk.Entry(dst, textvariable=self.dest_var)
        self.dest_entry.grid(row=0, column=0, sticky="ew")
        self.dest_btn = ttk.Button(dst, text="参照…", command=self._ask_dest)
        self.dest_btn.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        dst.columnconfigure(1, minsize=self.add_folder_btn.winfo_reqwidth())

        # ③ 方法
        self._step(main, 6, "③ 移動かコピーか")
        modes = ttk.Frame(main)
        modes.grid(row=7, column=0, sticky="ew")
        self.move_var = tk.BooleanVar(value=True)
        self.move_radio = ttk.Radiobutton(modes, text="移動（元のファイルは消えます）", variable=self.move_var,
                                          value=True, style="Toggle.TButton", width=26)
        self.move_radio.pack(side="left", ipady=4)
        self.copy_radio = ttk.Radiobutton(modes, text="コピー（元のファイルも残します）", variable=self.move_var,
                                          value=False, style="Toggle.TButton", width=26)
        self.copy_radio.pack(side="left", padx=(8, 0), ipady=4)
        self.more_var = tk.BooleanVar(value=False)
        self.more_check = ttk.Checkbutton(modes, text="詳細設定", variable=self.more_var,
                                          style="Switch.TCheckbutton", command=self._toggle_more)
        self.more_check.pack(side="right")

        self.more = ttk.Frame(main, padding=(4, 10, 0, 0))
        self.more.grid(row=8, column=0, sticky="ew")
        self._build_more(self.more)
        self.more.grid_remove()

        # 実行
        bar = ttk.Frame(main)
        bar.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        self.preview_btn = ttk.Button(bar, text="先に確認する", command=lambda: self.start(dry_run=True))
        self.preview_btn.pack(side="left", ipady=3)
        self.run_btn = ttk.Button(bar, style="Accent.TButton", width=14, command=lambda: self.start(dry_run=False))
        self.run_btn.pack(side="left", padx=8, ipady=3)
        self.cancel_btn = ttk.Button(bar, text="中止", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", ipady=3)
        self.count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.count_var, width=12, anchor="e").pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.pack(side="right", fill="x", expand=True, padx=(16, 8))
        self.move_var.trace_add("write", lambda *a: self._update_run_label())
        self._update_run_label()

        # 結果
        card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        card.grid(row=10, column=0, sticky="ew", pady=(14, 0))
        card.columnconfigure(1, weight=1)
        self.icon_label = ttk.Label(card, font="FileMoveIcon", width=2)
        self.icon_label.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 8))
        self.title_var = tk.StringVar()
        self.title_label = ttk.Label(card, textvariable=self.title_var, font="FileMoveHeading")
        self.title_label.grid(row=0, column=1, sticky="w")
        self.detail_var = tk.StringVar()
        self.detail_label = ttk.Label(card, textvariable=self.detail_var, wraplength=540, justify="left")
        self.detail_label.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self.open_btn = ttk.Button(card, text="移す先を開く", command=self.open_dest)
        self.open_btn.grid(row=0, column=2, rowspan=2, sticky="e", padx=(10, 0))
        self.open_btn.grid_remove()

        self.tabs = ttk.Notebook(main)
        self.tabs.grid(row=11, column=0, sticky="nsew", pady=(10, 0))
        main.rowconfigure(11, weight=1)
        listf = ttk.Frame(self.tabs)
        self.tree = ttk.Treeview(listf, columns=("state", "name", "note"), show="headings", height=8)
        for col, text, width, stretch in (("state", "状態", 150, False), ("name", "ファイル", 240, True),
                                          ("note", "行き先・理由", 300, True)):
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
        self.log_text = tk.Text(logf, height=8, wrap="none", state="disabled", relief="flat", borderwidth=0,
                                font="TkDefaultFont", spacing1=1, background="#ffffff", foreground="#1c1c1c")
        lscroll = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lscroll.set)
        lscroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.tabs.add(logf, text="ログ")

    def _build_more(self, f: ttk.Frame) -> None:
        f.columnconfigure(2, weight=1)
        gray = dict(foreground="#6b6b6b")
        ttk.Label(f, text="同じ名前があるとき").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.on_exists_var = tk.StringVar(value=next(iter(ON_EXISTS)))
        self.on_exists_combo = ttk.Combobox(f, textvariable=self.on_exists_var, values=list(ON_EXISTS),
                                            state="readonly", width=22)
        self.on_exists_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="中身が同じなら、両方は残しません", **gray).grid(row=0, column=2, sticky="w", padx=10)

        ttk.Label(f, text="種類（拡張子）").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.exts_var = tk.StringVar()
        self.exts_entry = ttk.Entry(f, textvariable=self.exts_var, width=24)
        self.exts_entry.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="例: pdf,jpg（空ならすべて）", **gray).grid(row=1, column=2, sticky="w", padx=10, pady=(6, 0))

        ttk.Label(f, text="期間").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.since_var = tk.StringVar()
        self.since_entry = ttk.Entry(f, textvariable=self.since_var, width=24)
        self.since_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="例: 30d（30 日以内に更新されたもの）", **gray).grid(row=2, column=2, sticky="w",
                                                                   padx=10, pady=(6, 0))

        self.dedupe_var = tk.BooleanVar(value=False)
        self.dedupe_check = ttk.Checkbutton(f, text="「(1)」付きの重複ファイルを消す（中身が同じものだけ）",
                                            variable=self.dedupe_var)
        self.dedupe_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _step(self, parent: ttk.Frame, row: int, text: str) -> None:
        ttk.Label(parent, text=text, font="FileMoveStep").grid(row=row, column=0, sticky="w", pady=(10, 4))

    def _toggle_more(self) -> None:
        if self.more_var.get():
            self.more.grid()
        else:
            self.more.grid_remove()

    def _update_run_label(self) -> None:
        self.run_btn.configure(text="移動する" if self.move_var.get() else "コピーする")

    def _update_hint(self) -> None:
        """移すものが空のときは、一覧の上に操作の案内を出す。"""
        if self.sources:
            self.src_hint.place_forget()
            return
        self.src_hint.configure(text="ここにフォルダやファイルをドラッグ＆ドロップ" if self.can_drop
                                else "右の「フォルダを追加…」で選んでください")
        self.src_hint.place(relx=0.5, rely=0.5, anchor="center")

    # ------------------------------------------------------------ 入力

    def _setup_drop(self) -> bool:
        """tkinterdnd2 で起動していれば、移すもの・移す先にドラッグ＆ドロップできるようにする。"""
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
        """ドロップされたもの（"{C:/a b} C:/c" の形）を移すものに加える。"""
        for p in self.root.tk.splitlist(data):
            self.add_source(Path(p))

    def drop_dest(self, data: str) -> None:
        paths = [Path(p) for p in self.root.tk.splitlist(data)]
        if paths:
            self.set_dest(paths[0] if paths[0].is_dir() else paths[0].parent)

    def _ask_folder(self) -> None:
        path = filedialog.askdirectory(title="移すフォルダを選ぶ")
        if path:
            self.add_source(Path(path))

    def _ask_files(self) -> None:
        for path in filedialog.askopenfilenames(title="移すファイルを選ぶ"):
            self.add_source(Path(path))

    def _ask_dest(self) -> None:
        path = filedialog.askdirectory(title="移す先のフォルダを選ぶ")
        if path:
            self.set_dest(Path(path))

    def add_source(self, path: Path) -> None:
        if any(mf._root_id(p) == mf._root_id(path) for p in self.sources):
            return   # 同じものは 1 回だけ
        self.sources.append(path)
        self.src_list.insert("end", self.display(str(path)) + ("\\" if path.is_dir() else ""))
        self._update_hint()

    def _remove_selected(self) -> None:
        for i in reversed(self.src_list.curselection()):
            self.src_list.delete(i)
            del self.sources[i]
        self._update_hint()

    def _forget_moved_sources(self) -> list[str]:
        """移動して空になった（無くなった）ものを、移すものの一覧から外し、その名前を返す。"""
        gone = []
        for i in reversed(range(len(self.sources))):
            p = self.sources[i]
            if not p.exists() or (p.is_dir() and not any(f.is_file() for f in p.rglob("*"))):
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

    # ------------------------------------------------------------ 実行

    def start(self, *, dry_run: bool) -> None:
        if self.job and self.job.running:
            return
        form = self.form()
        try:
            job = MigrationJob(form, dry_run=dry_run, ledger_path=self.ledger_path)
        except ValueError as e:
            self._show(Outcome("warn", "入力を確かめてください", str(e)))
            return
        if form.move and not dry_run and not self.confirm(
                "移動の確認", "移動すると、移す先で中身を確かめた後に元のファイルを削除します。\n実行しますか？"):
            return

        self._clear()
        self._dest_dir = job.options["dst"]
        self.progress.configure(value=0, maximum=1)
        self.count_var.set("")
        verb = "移動" if form.move else "コピー"
        self._show(Outcome("info", "確認しています…" if dry_run else f"{verb}しています…",
                           "終わるまでお待ちください。" + ("" if dry_run else "「中止」で途中で止められます。")))
        self.tabs.select(0)
        self._set_running(True)
        self.job = job
        job.start()
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

    def _poll(self) -> None:
        job = self.job
        for kind, payload in job.drain():
            if kind == "log":
                self._append_log(self.display(payload))
            elif kind == "progress":
                self._on_progress(payload)
            elif kind == "finished":
                self._finish(payload)
            elif kind == "error":
                self._show(Outcome("error", "エラーが起きました", str(payload)))
                self._set_running(False)
        if job.running or not job.events.empty():
            self.root.after(POLL_MS, self._poll)
            return
        if self.cancel_btn.instate(["!disabled"]):
            self._set_running(False)
        if self._closing:
            self.root.destroy()

    def _on_progress(self, ev: mf.ProgressEvent) -> None:
        if ev.status == "scanned":
            self.progress.configure(maximum=max(ev.total, 1), value=0)
            self.count_var.set(f"0 / {ev.total} 件")
            return
        self.progress.configure(value=ev.index)
        self.count_var.set(f"{ev.index} / {ev.total} 件")
        row = describe(ev, move=self.job.options["move"], dry_run=self.job.dry_run, display=self.display)
        if row:
            self._add_row(row)

    def _finish(self, result: mf.MigrationResult) -> None:
        job = self.job
        self.last_result = result
        for row in dedupe_rows(result, dry_run=job.dry_run, root=job.options["dst"], display=self.display):
            self._add_row(row)
        kept = sum(1 for r in self.rows if r.tag == "warn")
        o = outcome(result, dry_run=job.dry_run, move=job.options["move"], kept=kept)
        if job.options["move"] and not job.dry_run:
            gone = self._forget_moved_sources()
            if gone:   # 一覧から消えた理由が分かるように書いておく
                note = "、".join(f"「{n}」" for n in gone) + " は空になったので ① から外しました。"
                o = Outcome(o.level, o.title, f"{o.detail}。{note}" if o.detail else note)
        self._show(o)
        if not job.dry_run and self._dest_dir and self._dest_dir.is_dir():
            self.open_btn.grid()
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        for b in (self.preview_btn, self.run_btn):
            b.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    # ------------------------------------------------------------ 結果とログ

    def _show(self, o: Outcome) -> None:
        """結果の欄（見出し・説明）を更新する。"""
        self.last_outcome = o
        icon, color = LEVELS[o.level]
        self.icon_label.configure(text=icon, foreground=color)
        self.title_label.configure(foreground=color)
        self.title_var.set(o.title)
        self.detail_var.set(o.detail)
        if o.level != "ok":
            self.open_btn.grid_remove()

    def _add_row(self, row) -> None:
        self.rows.append(row)
        item = self.tree.insert("", "end", values=(row.state, self.display(row.name), row.note), tags=(row.tag,))
        self.tree.see(item)

    def _clear(self) -> None:
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.open_btn.grid_remove()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


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
    strong = dict(family=family + " Semibold", weight="normal") if family + " Semibold" in families         else dict(family=family, weight="bold")
    for name, size in (("FileMoveTitle", 18), ("FileMoveStep", 11), ("FileMoveHeading", 13), ("FileMoveIcon", 18)):
        if name in font.names(root):
            font.nametofont(name, root).configure(size=size, **strong)
        else:
            font.Font(root, name=name, size=size, **strong)


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


def main() -> None:
    dpi_aware()
    root = make_root()
    apply_theme(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
