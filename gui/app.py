# -*- coding: utf-8 -*-
"""
FileMove の画面（tkinter）。

    python -m gui        # リポジトリのフォルダで実行する（Windows ならダブルクリックで gui/FileMove.pyw でも可）

入力の確認と実行は gui/runner.py（その先は migrate_files.run_migration()）に任せ、
ここでは画面の部品と、ボタン・進捗の表示だけを扱う。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import migrate_files as mf
from gui.runner import ON_EXISTS, Form, MigrationJob, summary

POLL_MS = 50   # 別スレッドの進捗を取りに行く間隔

# 進捗の status -> 画面に出す言葉
STATUS_WORDS = {
    "done": "完了", "dryrun": "確認", "skipped": "スキップ", "removed": "元を削除", "failed": "失敗",
}


class App:
    """FileMove のメイン画面。

    display / parse は表示上のパスと実際のパスの変換（デモで C:\\Users\\user のように見せるため）。
    confirm は「移動してよいか」の確認（テストやデモでは差し替える）。
    """

    def __init__(self, root: tk.Tk, *, ledger_path: Path | None = None,
                 display: Callable[[str], str] = lambda s: s,
                 parse: Callable[[str], str] = lambda s: s,
                 confirm: Callable[[str, str], bool] = messagebox.askyesno):
        self.root = root
        self.ledger_path = ledger_path
        self.display, self.parse, self.confirm = display, parse, confirm
        self.sources: list[Path] = []
        self.job: MigrationJob | None = None
        self.last_result: mf.MigrationResult | None = None

        root.title("FileMove")
        root.minsize(720, 600)
        self._build()

    # ------------------------------------------------------------ 画面の組み立て

    def _build(self) -> None:
        pad = dict(padx=10, pady=(8, 0))
        main = ttk.Frame(self.root, padding=(4, 4, 4, 10))
        main.pack(fill="both", expand=True)

        # 移行元
        src = ttk.LabelFrame(main, text="移行元（移したいフォルダやファイル）", padding=8)
        src.pack(fill="x", **pad)
        self.src_list = tk.Listbox(src, height=5, activestyle="none", selectmode="extended")
        self.src_list.grid(row=0, column=0, rowspan=3, sticky="nsew")
        src.columnconfigure(0, weight=1)
        self.add_folder_btn = ttk.Button(src, text="フォルダを追加…", command=self._ask_folder)
        self.add_folder_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.add_files_btn = ttk.Button(src, text="ファイルを追加…", command=self._ask_files)
        self.add_files_btn.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        self.remove_btn = ttk.Button(src, text="選んだものを外す", command=self._remove_selected)
        self.remove_btn.grid(row=2, column=1, sticky="ew", padx=(8, 0))

        # 移行先
        dst = ttk.LabelFrame(main, text="移行先（入れる先のフォルダ）", padding=8)
        dst.pack(fill="x", **pad)
        self.dest_var = tk.StringVar()
        self.dest_entry = ttk.Entry(dst, textvariable=self.dest_var)
        self.dest_entry.grid(row=0, column=0, sticky="ew")
        dst.columnconfigure(0, weight=1)
        self.dest_btn = ttk.Button(dst, text="参照…", command=self._ask_dest)
        self.dest_btn.grid(row=0, column=1, padx=(8, 0))

        # 設定
        opt = ttk.LabelFrame(main, text="設定", padding=8)
        opt.pack(fill="x", **pad)
        self.move_var = tk.BooleanVar(value=False)
        ttk.Label(opt, text="方法").grid(row=0, column=0, sticky="w", padx=(0, 12))
        modes = ttk.Frame(opt)
        modes.grid(row=0, column=1, columnspan=3, sticky="w")
        self.copy_radio = ttk.Radiobutton(modes, text="コピー（元のファイルは残す）", variable=self.move_var, value=False)
        self.copy_radio.pack(side="left")
        self.move_radio = ttk.Radiobutton(modes, text="移動（元のファイルを消す）", variable=self.move_var, value=True)
        self.move_radio.pack(side="left", padx=(16, 0))

        ttk.Label(opt, text="同じ名前があるとき").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.on_exists_var = tk.StringVar(value=next(iter(ON_EXISTS)))
        self.on_exists_combo = ttk.Combobox(opt, textvariable=self.on_exists_var, values=list(ON_EXISTS),
                                            state="readonly", width=28)
        self.on_exists_combo.grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(opt, text="種類（拡張子）").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.exts_var = tk.StringVar()
        self.exts_entry = ttk.Entry(opt, textvariable=self.exts_var, width=20)
        self.exts_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(opt, text="例: pdf,jpg（空ならすべて）", foreground="gray").grid(row=2, column=2, sticky="w", padx=8, pady=(6, 0))

        ttk.Label(opt, text="期間").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.since_var = tk.StringVar()
        self.since_entry = ttk.Entry(opt, textvariable=self.since_var, width=20)
        self.since_entry.grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(opt, text="例: 30d（30 日以内に更新されたもの）", foreground="gray").grid(row=3, column=2, sticky="w", padx=8, pady=(6, 0))

        self.dedupe_var = tk.BooleanVar(value=False)
        self.dedupe_check = ttk.Checkbutton(opt, text="「(1)」付きの重複ファイルを消す（中身が同じものだけ）",
                                            variable=self.dedupe_var)
        self.dedupe_check.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        opt.columnconfigure(3, weight=1)

        # ボタン
        bar = ttk.Frame(main)
        bar.pack(fill="x", padx=10, pady=(12, 0))
        self.preview_btn = ttk.Button(bar, text="確認（ドライラン）", command=lambda: self.start(dry_run=True))
        self.preview_btn.pack(side="left")
        self.run_btn = ttk.Button(bar, text="実行", command=lambda: self.start(dry_run=False))
        self.run_btn.pack(side="left", padx=8)
        self.cancel_btn = ttk.Button(bar, text="中止", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left")

        # 進捗
        prog = ttk.Frame(main)
        prog.pack(fill="x", padx=10, pady=(10, 0))
        self.progress = ttk.Progressbar(prog, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.count_var = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.count_var, width=14, anchor="e").pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar(value="移行元と移行先を選んで、まず「確認（ドライラン）」を押してください。")
        ttk.Label(main, textvariable=self.status_var, justify="left").pack(fill="x", padx=10, pady=(6, 0))

        # ログ
        logf = ttk.LabelFrame(main, text="ログ", padding=4)
        logf.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(logf, height=10, wrap="none", state="disabled", relief="flat",
                                font="TkDefaultFont", spacing1=1)
        scroll = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 入力

    def _ask_folder(self) -> None:
        path = filedialog.askdirectory(title="移行元のフォルダを選ぶ")
        if path:
            self.add_source(Path(path))

    def _ask_files(self) -> None:
        for path in filedialog.askopenfilenames(title="移行元のファイルを選ぶ"):
            self.add_source(Path(path))

    def _ask_dest(self) -> None:
        path = filedialog.askdirectory(title="移行先のフォルダを選ぶ")
        if path:
            self.set_dest(Path(path))

    def add_source(self, path: Path) -> None:
        if any(mf._root_id(p) == mf._root_id(path) for p in self.sources):
            return   # 同じものは 1 回だけ
        self.sources.append(path)
        self.src_list.insert("end", self.display(str(path)) + ("\\" if path.is_dir() else ""))

    def _remove_selected(self) -> None:
        for i in reversed(self.src_list.curselection()):
            self.src_list.delete(i)
            del self.sources[i]

    def set_dest(self, path: Path) -> None:
        self.dest_var.set(self.display(str(path)))

    def form(self) -> Form:
        return Form(sources=list(self.sources), dest=self.parse(self.dest_var.get()),
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
            self.status_var.set(f"⚠ {e}")
            return
        if form.move and not dry_run and not self.confirm(
                "移動の確認", "移動すると、移行先で中身を確かめた後に元のファイルを削除します。\n実行しますか？"):
            return

        self._clear_log()
        self.progress.configure(value=0, maximum=1)
        self.count_var.set("")
        self.status_var.set("確認しています…" if dry_run else "実行しています…")
        self._set_running(True)
        self.job = job
        job.start()
        self.root.after(POLL_MS, self._poll)

    def cancel(self) -> None:
        if self.job and self.job.running:
            self.job.cancel()
            self.status_var.set("中止しています（今のファイルが終わったら止まります）…")

    def _poll(self) -> None:
        job = self.job
        for kind, payload in job.drain():
            if kind == "log":
                self._append_log(self.display(payload))
            elif kind == "progress":
                self._on_progress(payload)
            elif kind == "finished":
                self.last_result = payload
                self.status_var.set(summary(payload, job.dry_run))
                self._set_running(False)
            elif kind == "error":
                self.status_var.set(f"⚠ エラーが起きました: {payload}")
                self._set_running(False)
        if job.running or not job.events.empty():
            self.root.after(POLL_MS, self._poll)
        elif self.cancel_btn.instate(["!disabled"]):
            self._set_running(False)

    def _on_progress(self, ev: mf.ProgressEvent) -> None:
        if ev.status == "scanned":
            self.progress.configure(maximum=max(ev.total, 1), value=0)
            self.count_var.set(f"0 / {ev.total} 件")
            return
        self.progress.configure(value=ev.index)
        self.count_var.set(f"{ev.index} / {ev.total} 件")
        self.status_var.set(f"{STATUS_WORDS.get(ev.status, ev.status)}: {self.display(ev.rel)}")

    def _set_running(self, running: bool) -> None:
        for b in (self.preview_btn, self.run_btn):
            b.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    # ------------------------------------------------------------ ログ

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def setup_fonts(root: tk.Tk) -> None:
    """Windows では日本語が読みやすい Yu Gothic UI にそろえる（無ければ既定のまま）。"""
    from tkinter import font
    if "Yu Gothic UI" in font.families(root):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name, root).configure(family="Yu Gothic UI", size=10)


def main() -> None:
    root = tk.Tk()
    setup_fonts(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
