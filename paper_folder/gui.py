from __future__ import annotations

import sys
import tkinter as tk
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional, Union

from . import __version__
from .bibtex import export_bibtex
from .csv_review import export_review_csv, load_review_csv
from .duplicates import find_duplicates
from .metadata import PaperMetadata, metadata_status
from .naming import FIELD_LABELS, RenamePreview, build_rename_previews
from .operations import apply_renames, undo_last
from .scan_work import scan_papers
from .settings import load_settings, save_settings


COLORS = {
    "page": "#d9b77d",
    "sidebar": "#f1e4cd",
    "main": "#f8f3e9",
    "surface": "#fffdf8",
    "ink": "#3f2d1d",
    "muted": "#756859",
    "brand": "#2f7567",
    "brand_hover": "#245d52",
    "guide": "#86501e",
    "guide_fill": "#f8e0b6",
    "brown": "#7a4b24",
    "line": "#dfd1bc",
    "ready": "#d9efe1",
    "review": "#ffe5a8",
    "failed": "#f7c7bd",
}

TYPE_LABELS = {"paper": "论文", "appendix": "附录", "book": "书籍", "other": "其他"}


class GuiJuanApp(tk.Tk):
    def __init__(self, settings_path: Optional[Union[str, Path]] = None) -> None:
        super().__init__()
        self.settings_path = settings_path
        self.app_settings = load_settings(settings_path)
        self.title(f"归卷 GuiJuan v{__version__} - 论文 PDF 整理器")
        self.geometry("1280x720")
        self.minsize(1050, 620)
        self.configure(background=COLORS["page"])
        self.folder = tk.StringVar()
        self.email = tk.StringVar(value=self.app_settings.email)
        self.recursive = tk.BooleanVar(value=self.app_settings.recursive)
        self.online = tk.BooleanVar(value=self.app_settings.online)
        self.status = tk.StringVar(value="准备就绪。选择论文文件夹后开始扫描。")
        self.total_text = tk.StringVar(value="0 个文件")
        self.ready_text = tk.StringVar(value="0 个可保存")
        self.review_text = tk.StringVar(value="0 个需检查")
        self.attention_text = tk.StringVar(value="0 个建议检查")
        self.blocked_text = tk.StringVar(value="0 个必须修改")
        self.items: List[PaperMetadata] = []
        self.previews: List[RenamePreview] = []
        self.results_root: Optional[Path] = None
        self.scan_cancel: Optional[Event] = None
        self.onboarding_step: Optional[int] = None
        self.onboarding_target = None
        self._configure_style()
        self._load_brand_assets()
        self._build()
        self.folder.trace_add("write", self._folder_changed)
        self.protocol("WM_DELETE_WINDOW", self._close)
        if not self.app_settings.onboarding_complete:
            self.after_idle(self.show_onboarding)

    def _save_settings(self) -> None:
        self.app_settings.email = self.email.get().strip()
        self.app_settings.recursive = self.recursive.get()
        self.app_settings.online = self.online.get()
        try:
            save_settings(self.app_settings, self.settings_path)
        except OSError:
            self.status.set("设置暂时无法保存；本次使用不受影响。")

    def _close(self) -> None:
        if self.scan_cancel is not None:
            self.scan_cancel.set()
        self._save_settings()
        self.destroy()

    def _build_previews(self) -> List[RenamePreview]:
        return build_rename_previews(
            self.items,
            fields=self.app_settings.naming_fields,
            conflict_strategy="suffix",
        )

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=COLORS["main"])
        style.configure("TLabel", background=COLORS["main"], foreground=COLORS["ink"], font=("Microsoft YaHei UI", 9))
        style.configure("Card.TFrame", background=COLORS["surface"], relief="flat")
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["ink"], font=("Microsoft YaHei UI", 9))
        style.configure("Step.TLabel", background=COLORS["surface"], foreground=COLORS["brown"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Metric.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", background=COLORS["brand"], foreground="#ffffff", borderwidth=0, padding=(16, 9), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", COLORS["brand_hover"]), ("disabled", "#a9c3bf")])
        style.configure("Secondary.TButton", background="#efe5d6", foreground=COLORS["ink"], borderwidth=0, padding=(13, 8), font=("Microsoft YaHei UI", 9))
        style.map("Secondary.TButton", background=[("active", "#e3d5c1")])
        style.configure("Quiet.TButton", background=COLORS["surface"], foreground=COLORS["muted"], borderwidth=0, padding=(10, 7), font=("Microsoft YaHei UI", 9))
        style.map("Quiet.TButton", background=[("active", "#f1e8db")])
        for button_style in ("Primary.TButton", "Secondary.TButton"):
            guide_style = "Guide." + button_style
            style.configure(
                guide_style, borderwidth=2, bordercolor=COLORS["guide"],
                lightcolor=COLORS["guide"], darkcolor=COLORS["guide"],
                background=COLORS["guide_fill"], foreground=COLORS["ink"],
            )
            style.map(
                guide_style,
                background=[("disabled", "#efe5d6"), ("pressed", "#dfbc85"), ("active", "#f2d29d")],
            )
        style.configure("Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"], foreground=COLORS["ink"], rowheight=34, borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background="#eee4d5", foreground=COLORS["ink"], relief="flat", padding=(8, 8), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview.Heading", background=[("active", "#e2d4c0")])
        style.configure("Status.TLabel", background="#ede1ce", foreground=COLORS["muted"], padding=(12, 6), font=("Microsoft YaHei UI", 9))

    def _load_brand_assets(self) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        icon = base / "assets" / "guijuan-scroll-hd-v3.ico"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.brand_image = self._photo_image(base / "assets" / "guijuan-scroll-sidebar-v3.png")
        if self.brand_image:
            try:
                self.iconphoto(True, self.brand_image)
            except tk.TclError:
                pass
        self.banner_image = self._photo_image(base / "assets" / "parchment-bamboo-banner-v2.png")
        self.side_image = self._photo_image(base / "assets" / "parchment-bamboo-side-v2.png")

    @staticmethod
    def _photo_image(path: Path):
        try:
            return tk.PhotoImage(file=str(path)) if path.exists() else None
        except tk.TclError:
            return None

    def _build(self) -> None:
        shell = tk.Frame(self, background=COLORS["page"], padx=10, pady=10)
        shell.pack(fill="both", expand=True)
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(1, weight=1)

        sidebar = tk.Frame(shell, background=COLORS["sidebar"], width=205, bd=0)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        sidebar.pack_propagate(False)
        if self.brand_image:
            tk.Label(sidebar, image=self.brand_image, background=COLORS["sidebar"], bd=0).pack(pady=(15, 2))
        tk.Label(sidebar, text="归卷  GuiJuan", background=COLORS["sidebar"], foreground=COLORS["ink"], font=("Microsoft YaHei UI", 15, "bold")).pack()
        tk.Label(sidebar, text="让散落的 PDF，一键归卷", background=COLORS["sidebar"], foreground=COLORS["muted"], font=("Microsoft YaHei UI", 8)).pack(pady=(3, 14))
        tk.Frame(sidebar, height=1, background=COLORS["line"]).pack(fill="x", padx=18, pady=(0, 12))
        tk.Label(sidebar, text="工作流程", background=COLORS["sidebar"], foreground=COLORS["muted"], anchor="w", font=("Microsoft YaHei UI", 8, "bold")).pack(fill="x", padx=20, pady=(0, 6))
        self._sidebar_button(sidebar, "01   论文整理", lambda: self.folder_entry.focus_set(), selected=True)
        self._sidebar_button(sidebar, "02   检查结果", self._focus_table)
        self.sidebar_save = self._sidebar_button(sidebar, "03   保存名称", self.apply_names)
        tk.Label(sidebar, text="工具", background=COLORS["sidebar"], foreground=COLORS["muted"], anchor="w", font=("Microsoft YaHei UI", 8, "bold")).pack(fill="x", padx=20, pady=(16, 6))
        self._sidebar_button(sidebar, "导出校对 CSV", self.export_csv)
        self._sidebar_button(sidebar, "导出 BibTeX", self.export_bib)
        self._sidebar_button(sidebar, "检查重复论文", self.show_duplicates)
        self._sidebar_button(sidebar, "Crossref 设置", self.configure_crossref)
        self._sidebar_button(sidebar, "使用帮助", lambda: self.show_onboarding(force=True))
        if self.side_image:
            tk.Label(sidebar, image=self.side_image, background=COLORS["sidebar"], bd=0).pack(side="bottom", fill="x")

        main = tk.Frame(shell, background=COLORS["main"], bd=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(4, weight=1)
        main.grid_columnconfigure(0, weight=1)

        banner = tk.Canvas(main, height=108, background=COLORS["page"], highlightthickness=0)
        banner.grid(row=0, column=0, sticky="ew")
        if self.banner_image:
            banner.create_image(0, 0, image=self.banner_image, anchor="nw")
        banner.create_text(24, 34, text="论文整理", anchor="w", fill=COLORS["ink"], font=("Microsoft YaHei UI", 18, "bold"))
        banner.create_text(24, 67, text="选择文件夹，检查识别结果，再安全保存名称。", anchor="w", fill="#69533d", font=("Microsoft YaHei UI", 9))

        self._build_onboarding_card(main)

        folder_card = ttk.Frame(main, style="Card.TFrame", padding=14)
        folder_card.grid(row=2, column=0, sticky="ew", padx=12, pady=(10, 8))
        ttk.Label(folder_card, text="选择论文文件夹", style="Step.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.folder_entry = ttk.Entry(folder_card, textvariable=self.folder, font=("Microsoft YaHei UI", 10))
        self.folder_entry.grid(row=1, column=0, sticky="ew", ipady=5)
        self.folder_entry.bind("<Return>", lambda _event: self.scan())
        self.browse_button = ttk.Button(folder_card, text="浏览文件夹", style="Secondary.TButton", command=self.choose_folder)
        self.browse_button.grid(row=1, column=1, padx=(10, 0))
        self.scan_button = ttk.Button(folder_card, text="开始扫描", style="Primary.TButton", command=self.scan)
        self.scan_button.grid(row=1, column=2, padx=(10, 0))
        options = tk.Frame(folder_card, background=COLORS["surface"])
        options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.recursive_check = self._classic_checkbutton(options, "包含子文件夹", self.recursive, self._save_settings)
        self.recursive_check.pack(side="left")
        self.online_check = self._classic_checkbutton(options, "在线校验（DOI / arXiv 编号）", self.online, self._save_settings)
        self.online_check.pack(side="left", padx=(16, 0))
        folder_card.columnconfigure(0, weight=1)

        review_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        review_card.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        ttk.Label(review_card, text="论文文件", style="Step.TLabel").pack(side="left")
        self.load_csv_button = ttk.Button(review_card, text="载入校对 CSV", style="Quiet.TButton", command=self.load_csv)
        self.load_csv_button.pack(side="right")
        self.edit_button = ttk.Button(review_card, text="编辑选中项", style="Secondary.TButton", command=self.edit_selected, state="disabled")
        self.edit_button.pack(side="right", padx=(0, 8))
        self.naming_button = ttk.Button(review_card, text="自定义命名", style="Secondary.TButton", command=self.configure_naming)
        self.naming_button.pack(side="right", padx=(0, 8))
        metrics = ttk.Frame(review_card, style="Card.TFrame")
        metrics.pack(side="left", padx=(12, 0))
        ttk.Label(metrics, textvariable=self.total_text, style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, text="  ·  ", style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, textvariable=self.ready_text, style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, text="  ·  ", style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, textvariable=self.review_text, style="Metric.TLabel").pack(side="left")

        columns = ("file", "type", "title", "year", "suggested", "status")
        table_frame = ttk.Frame(main, style="Card.TFrame", padding=2)
        table_frame.grid(row=4, column=0, sticky="nsew", padx=12)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=columns, show="tree headings", height=5)
        self.table.heading("#0", text="")
        self.table.column("#0", width=30, minwidth=30, stretch=False)
        self.status_images = {}
        for name, color in (
            ("ready", "#4e9d78"), ("review", "#dda72e"),
            ("failed", "#c96858"), ("reviewed", "#4f86b5"),
        ):
            image = tk.PhotoImage(width=12, height=12)
            # Draw a compact circle on a transparent canvas. Treeview row
            # background tags are not consistently rendered by Windows themes,
            # so this icon is the reliable status cue.
            for y in range(12):
                for x in range(12):
                    if (x - 5.5) ** 2 + (y - 5.5) ** 2 <= 23:
                        image.put(color, (x, y))
            self.status_images[name] = image
        self.table.tag_configure("failed", background=COLORS["failed"], foreground="#773429")
        self.table.tag_configure("review", background=COLORS["review"], foreground="#6d5011")
        self.table.tag_configure("ready", background=COLORS["ready"], foreground="#285a45")
        self.table.tag_configure("reviewed", background="#dce9f4", foreground="#285985")
        labels = ("原文件名", "类型", "标题", "年份", "建议的新文件名", "状态")
        widths = (145, 50, 190, 48, 230, 128)
        for column, label, width in zip(columns, labels, widths):
            self.table.heading(column, text=label)
            self.table.column(
                column, width=width, minwidth=50,
                stretch=column in {"title", "suggested"},
            )
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.bind("<Double-1>", lambda _event: self.edit_selected())
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_action_state())
        self.empty_state = ttk.Label(
            table_frame,
            text="这里会显示论文识别结果\n\n选择文件夹并点击“开始扫描”",
            background=COLORS["surface"], foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 11), justify="center",
        )
        self.empty_state.place(relx=0.5, rely=0.48, anchor="center")

        action_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        action_card.grid(row=5, column=0, sticky="ew", padx=12, pady=(8, 6))
        ttk.Label(action_card, text="确认后保存", style="Step.TLabel").pack(side="left")
        ttk.Label(action_card, text="改名前请检查黄色和红色项目", style="Metric.TLabel").pack(side="left", padx=(18, 0))
        self.save_button = ttk.Button(action_card, text="保存全部名称", style="Primary.TButton", command=self.apply_names, state="disabled")
        self.save_button.pack(side="right")
        self.undo_button = ttk.Button(action_card, text="撤销上次改名", style="Quiet.TButton", command=self.undo)
        self.undo_button.pack(side="right", padx=(0, 8))

        ttk.Label(main, textvariable=self.status, style="Status.TLabel", anchor="w").grid(row=6, column=0, sticky="ew")

        right = tk.Frame(shell, background=COLORS["sidebar"], width=225, padx=16, pady=18)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.grid_propagate(False)
        tk.Label(right, text="识别概况", background=COLORS["sidebar"], foreground=COLORS["ink"], anchor="w", font=("Microsoft YaHei UI", 12, "bold")).pack(fill="x")
        self.summary_canvas = tk.Canvas(right, width=150, height=150, background=COLORS["sidebar"], highlightthickness=0)
        self.summary_canvas.pack(pady=(8, 4))
        self._update_summary_panel()
        tk.Label(right, textvariable=self.total_text, background=COLORS["sidebar"], foreground=COLORS["ink"], font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(0, 12))
        self._legend_row(right, COLORS["ready"], "可保存", self.ready_text)
        self._legend_row(right, COLORS["review"], "建议检查", self.attention_text)
        self._legend_row(right, COLORS["failed"], "必须修改", self.blocked_text)
        tk.Frame(right, height=1, background=COLORS["line"]).pack(fill="x", pady=16)
        tk.Label(right, text="使用提示", background=COLORS["sidebar"], foreground=COLORS["ink"], anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(fill="x")
        tk.Label(right, text="先处理红色项目，再检查黄色项目。\n双击任意一行可以编辑最终文件名。", background=COLORS["sidebar"], foreground=COLORS["muted"], justify="left", wraplength=185, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(8, 0))
        tk.Label(right, text="PDF 在本地处理。在线校验使用 DOI 或 arXiv 编号。", background=COLORS["sidebar"], foreground=COLORS["muted"], justify="left", wraplength=185, font=("Microsoft YaHei UI", 8)).pack(side="bottom", fill="x")

    def _build_onboarding_card(self, parent) -> None:
        self.onboarding_progress = tk.StringVar()
        self.onboarding_heading = tk.StringVar()
        self.onboarding_description = tk.StringVar()
        self.onboarding_card = tk.Frame(
            parent, background="#f4eadb", padx=14, pady=10,
            highlightthickness=1, highlightbackground="#d8c29e",
        )
        self.onboarding_card.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.onboarding_card.columnconfigure(1, weight=1)

        tk.Label(
            self.onboarding_card, textvariable=self.onboarding_progress,
            background="#f4eadb", foreground=COLORS["brown"],
            font=("Microsoft YaHei UI", 9, "bold"), anchor="w",
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16))
        tk.Label(
            self.onboarding_card, textvariable=self.onboarding_heading,
            background="#f4eadb", foreground=COLORS["ink"],
            font=("Microsoft YaHei UI", 10, "bold"), anchor="w",
        ).grid(row=0, column=1, sticky="ew")
        tk.Label(
            self.onboarding_card, textvariable=self.onboarding_description,
            background="#f4eadb", foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9), anchor="w", justify="left",
        ).grid(row=1, column=1, sticky="ew", pady=(3, 0))

        controls = tk.Frame(self.onboarding_card, background="#f4eadb")
        controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=(14, 0))
        self.onboarding_back_button = ttk.Button(controls, text="上一步", style="Quiet.TButton")
        self.onboarding_back_button.pack(side="left")
        self.onboarding_next_button = ttk.Button(controls, text="下一步", style="Quiet.TButton")
        self.onboarding_next_button.pack(side="left")
        self.onboarding_skip_button = ttk.Button(
            controls, text="跳过", style="Quiet.TButton", command=self._finish_onboarding,
        )
        self.onboarding_skip_button.pack(side="left")
        self.onboarding_card.grid_remove()

    @staticmethod
    def _classic_checkbutton(parent, text: str, variable: tk.BooleanVar, command=None):
        return tk.Checkbutton(
            parent, text=text, variable=variable, onvalue=True, offvalue=False,
            command=command,
            background=COLORS["surface"], activebackground=COLORS["surface"],
            foreground=COLORS["muted"], selectcolor="#ffffff",
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
        )

    @staticmethod
    def _sidebar_button(parent, text: str, command, selected: bool = False) -> tk.Button:
        background = "#e4d2b5" if selected else COLORS["sidebar"]
        button = tk.Button(
            parent, text=text, command=command, anchor="w", relief="flat", bd=0,
            padx=20, pady=8, background=background, activebackground="#e4d2b5",
            foreground=COLORS["brown"] if selected else COLORS["ink"],
            font=("Microsoft YaHei UI", 9, "bold" if selected else "normal"),
        )
        button.pack(fill="x", padx=10, pady=1)
        return button

    @staticmethod
    def _legend_row(parent, color: str, label: str, value: tk.StringVar) -> None:
        row = tk.Frame(parent, background=COLORS["sidebar"])
        row.pack(fill="x", pady=4)
        tk.Label(row, width=2, height=1, background=color, bd=0).pack(side="left")
        tk.Label(row, text=label, background=COLORS["sidebar"], foreground=COLORS["ink"], anchor="w", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(row, textvariable=value, background=COLORS["sidebar"], foreground=COLORS["muted"], anchor="e", font=("Microsoft YaHei UI", 8)).pack(side="right")

    def _focus_table(self) -> None:
        self.table.focus_set()

    def _update_summary_panel(self) -> None:
        if not hasattr(self, "summary_canvas"):
            return
        total = len(self.items)
        blocked = sum(preview.status != "preview" for preview in self.previews)
        attention = sum(
            preview.status == "preview" and (item.status != "complete" or bool(preview.note))
            and item.source != "gui-review"
            for item, preview in zip(self.items, self.previews)
        )
        ready = max(0, total - blocked - attention)
        canvas = self.summary_canvas
        canvas.delete("all")
        canvas.create_oval(18, 18, 132, 132, outline="#dac9ad", width=12)
        if total:
            start = 90
            for count, color in ((ready, "#4e9d78"), (attention, "#dda72e"), (blocked, "#c96858")):
                if count:
                    extent = -360 * count / total
                    canvas.create_arc(18, 18, 132, 132, start=start, extent=extent, style="arc", outline=color, width=12)
                    start += extent
        canvas.create_text(75, 66, text=str(total), fill=COLORS["ink"], font=("Microsoft YaHei UI", 18, "bold"))
        canvas.create_text(75, 91, text="PDF 文件", fill=COLORS["muted"], font=("Microsoft YaHei UI", 8))

    def _update_action_state(self) -> None:
        editable = self.scan_cancel is None and self._results_match_folder()
        self.edit_button.configure(state="normal" if editable and self.table.selection() else "disabled")
        can_save = editable and any(preview.status == "preview" for preview in self.previews)
        self.save_button.configure(state="normal" if can_save else "disabled")

    def _results_match_folder(self) -> bool:
        value = self.folder.get().strip()
        return bool(value and Path(value).absolute() == self.results_root)

    def _folder_changed(self, *_args) -> None:
        self._update_action_state()
        if self.items and not self._results_match_folder():
            self.status.set("目录已更改。重新扫描后即可检查并保存新目录中的文件。")

    def configure_crossref(self) -> None:
        value = simpledialog.askstring(
            "Crossref 访问设置",
            "联系邮箱（可留空）\n仅随 DOI 查询发送，用于 Crossref 请求标识；不是登录账号。",
            initialvalue=self.email.get(), parent=self,
        )
        if value is not None:
            self.email.set(value.strip())
            self._save_settings()
            self.status.set("Crossref 联系邮箱已更新。" if value.strip() else "Crossref 将使用匿名公共访问。")

    def configure_naming(self) -> None:
        existing = getattr(self, "naming_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return

        dialog = tk.Toplevel(self)
        self.naming_dialog = dialog
        dialog.title("自定义命名")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("680x500")
        dialog.minsize(620, 460)
        dialog.configure(background=COLORS["page"])

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=20)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(frame, text="组合文件名字段", style="Step.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text="勾选字段并调整顺序。期刊可从 PDF 或在线校验获取，缺失时可在「编辑选中项」中补填。",
            style="Metric.TLabel",
            wraplength=540,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 16))

        field_order = ("year", "title", "authors", "journal", "doi")
        selected = list(self.app_settings.naming_fields)
        variables = {field: tk.BooleanVar(value=field in selected) for field in field_order}

        choices = ttk.Frame(frame, style="Card.TFrame")
        choices.grid(row=2, column=0, sticky="nsw")
        ttk.Label(choices, text="包含字段", style="Card.TLabel").pack(anchor="w", pady=(0, 6))

        order_frame = ttk.Frame(frame, style="Card.TFrame")
        order_frame.grid(row=2, column=1, sticky="nsew", padx=(26, 12))
        ttk.Label(order_frame, text="文件名顺序", style="Card.TLabel").pack(anchor="w", pady=(0, 6))
        order_list = tk.Listbox(
            order_frame, height=8, exportselection=False, activestyle="none",
            font=("Microsoft YaHei UI", 10), background="#fffaf1",
            foreground=COLORS["ink"], selectbackground="#d8c29e",
            selectforeground=COLORS["ink"], relief="flat", bd=0,
        )
        order_list.pack(fill="both", expand=True)

        def refresh_order(selection: Optional[int] = None) -> None:
            order_list.delete(0, "end")
            for field in selected:
                order_list.insert("end", FIELD_LABELS[field])
            if selected:
                index = min(selection if selection is not None else 0, len(selected) - 1)
                order_list.selection_set(index)
            update_preview()

        def toggle(field: str) -> None:
            if variables[field].get() and field not in selected:
                selected.append(field)
                refresh_order(len(selected) - 1)
            elif not variables[field].get() and field in selected:
                index = selected.index(field)
                selected.remove(field)
                refresh_order(max(0, index - 1))

        for field in field_order:
            self._classic_checkbutton(
                choices, FIELD_LABELS[field], variables[field],
                lambda value=field: toggle(value),
            ).pack(anchor="w", pady=4)

        controls = ttk.Frame(frame, style="Card.TFrame")
        controls.grid(row=2, column=2, sticky="n")

        def move(offset: int) -> None:
            selection = order_list.curselection()
            if not selection:
                return
            index = selection[0]
            target = index + offset
            if target < 0 or target >= len(selected):
                return
            selected[index], selected[target] = selected[target], selected[index]
            refresh_order(target)

        ttk.Button(controls, text="上移", style="Secondary.TButton", command=lambda: move(-1)).pack(fill="x", pady=(24, 6))
        ttk.Button(controls, text="下移", style="Secondary.TButton", command=lambda: move(1)).pack(fill="x")

        preview_value = tk.StringVar()
        preview_box = ttk.Frame(frame, style="Card.TFrame")
        preview_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        ttk.Label(preview_box, text="实时预览", style="Card.TLabel").pack(anchor="w")
        preview_label = tk.Label(
            preview_box, textvariable=preview_value, anchor="w", justify="left",
            background="#f4eadb", foreground=COLORS["ink"], padx=12, pady=10,
            font=("Microsoft YaHei UI", 9), wraplength=590,
        )
        preview_label.pack(fill="x", pady=(6, 0))

        def update_preview() -> None:
            if not selected:
                preview_value.set("请至少选择一个字段")
                return
            sample = PaperMetadata(
                Path("示例论文.pdf"), "A Practical Guide to PDF Organization",
                "Wang; Li", "2025", "10.1234/example", "complete",
                journal="Nature Communications",
            )
            preview = build_rename_previews([sample], fields=selected)[0]
            preview_value.set(preview.suggested_name)

        def reset_defaults() -> None:
            selected[:] = ["year", "title"]
            for field in field_order:
                variables[field].set(field in selected)
            refresh_order()

        def save() -> None:
            if not selected:
                messagebox.showwarning("无法保存", "请至少选择一个命名字段。", parent=dialog)
                return
            self.app_settings.naming_fields = list(selected)
            self._save_settings()
            if self.items:
                self.previews = self._build_previews()
                self._populate()
            self.status.set("命名规则已保存，当前预览已更新。")
            dialog.destroy()
            self._advance_onboarding(2)

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        ttk.Button(buttons, text="恢复默认", style="Quiet.TButton", command=reset_defaults).pack(side="left")
        ttk.Button(buttons, text="取消", style="Quiet.TButton", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="保存规则", style="Primary.TButton", command=save).pack(side="right")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)
        refresh_order()

    def show_onboarding(self, force: bool = False) -> None:
        if self.app_settings.onboarding_complete and not force:
            return
        self.onboarding_card.grid()
        self._render_onboarding_step(1 if self.scan_cancel is not None else 0)

    def _finish_onboarding(self) -> None:
        self.app_settings.onboarding_complete = True
        self._save_settings()
        self.onboarding_step = None
        self._highlight_onboarding(None)
        self.onboarding_card.grid_remove()

    def _highlight_onboarding(self, button) -> None:
        if self.onboarding_target is not None:
            target, style = self.onboarding_target
            target.configure(style=style)
        self.onboarding_target = None
        if button is not None:
            style = button.cget("style")
            self.onboarding_target = (button, style)
            button.configure(style="Guide." + style)

    def _render_onboarding_step(self, index: int) -> None:
        steps = (
            ("选择论文文件夹", "点击描边标出的「浏览文件夹」。", self.browse_button),
            ("扫描论文", "点击描边标出的「开始扫描」。", self.scan_button),
            ("选择文件名字段", "在表格上方点击「自定义命名」。", self.naming_button),
            ("检查预览并保存", "检查表格后，点击下方标出的「保存全部名称」。", self.save_button),
        )
        self.onboarding_step = index
        title, text, target = steps[index]
        if index == 1 and self.scan_cancel is not None:
            text = "扫描中，完成后继续。可在原位置取消。"
        self._highlight_onboarding(target)
        self.onboarding_progress.set(f"入门 {index + 1}/{len(steps)}")
        self.onboarding_heading.set(title)
        self.onboarding_description.set(text)
        self.onboarding_back_button.configure(
            state="normal" if index else "disabled",
            command=lambda: self._render_onboarding_step(index - 1),
        )

        last = index == len(steps) - 1
        self.onboarding_next_button.configure(
            text="完成引导" if last else "下一步",
            command=self._finish_onboarding if last else lambda: self._render_onboarding_step(index + 1),
        )
        if last:
            self.onboarding_skip_button.pack_forget()
        elif not self.onboarding_skip_button.winfo_manager():
            self.onboarding_skip_button.pack(side="left")

    def _advance_onboarding(self, completed_step: int) -> None:
        if self.onboarding_step == completed_step:
            self._render_onboarding_step(completed_step + 1)

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择论文文件夹", parent=self)
        if selected:
            self.folder.set(selected)
            self._advance_onboarding(0)

    def _selected_root(self) -> Path:
        value = self.folder.get().strip()
        root = Path(value)
        if not value or not root.is_dir():
            raise ValueError("请先选择有效的论文文件夹。")
        return root

    def _populate(self, on_complete=None) -> None:
        self.table.delete(*self.table.get_children())
        ready_count = 0
        attention_count = 0
        blocked_count = 0
        total = len(self.items)
        batch_size = 200 if on_complete is not None else total
        if total:
            self.empty_state.place_forget()
        else:
            self.empty_state.place(relx=0.5, rely=0.48, anchor="center")

        def render(start):
            nonlocal ready_count, attention_count, blocked_count
            end = min(start + batch_size, total)
            for index in range(start, end):
                item, preview = self.items[index], self.previews[index]
                blocked = preview.status != "preview"
                reviewed = item.source == "gui-review" and not blocked
                uncertain = (item.status != "complete" or bool(preview.note)) and not reviewed and not blocked
                if blocked:
                    display_status, tag = "× 必须修改", "failed"
                    blocked_count += 1
                elif uncertain:
                    if "期刊" in preview.note:
                        display_status = "! 期刊缺失，已跳过"
                    elif "名称冲突" in preview.note:
                        display_status = "! 已自动避让冲突"
                    else:
                        display_status = "! 建议检查"
                    tag = "review"
                    attention_count += 1
                elif reviewed:
                    display_status, tag = "✓ 已确认", "reviewed"
                    ready_count += 1
                else:
                    display_status, tag = "✓ 可保存", "ready"
                    ready_count += 1
                self.table.insert("", "end", iid=str(index), tags=(tag,), image=self.status_images[tag], values=(
                    item.path.name, TYPE_LABELS.get(item.document_type, item.document_type),
                    item.title, item.year, preview.suggested_name, display_status,
                ))
            if end < total:
                self.status.set(f"正在显示扫描结果 · {end} / {total}")
                self.after(1, render, end)
                return
            self.total_text.set(f"{total} 个文件")
            self.ready_text.set(f"{ready_count} 个可保存")
            self.attention_text.set(f"{attention_count} 个")
            self.blocked_text.set(f"{blocked_count} 个")
            review_count = attention_count + blocked_count
            self.review_text.set(f"{review_count} 个需检查")
            self._update_action_state()
            self._update_summary_panel()
            self.status.set(
                f"扫描完成：{ready_count} 个可直接保存，{review_count} 个建议检查。"
                if total else "没有找到 PDF 文件。"
            )
            if on_complete is not None:
                on_complete()

        render(0)

    def scan(self) -> None:
        if self.scan_cancel is not None:
            return
        naming_dialog = getattr(self, "naming_dialog", None)
        if naming_dialog is not None and naming_dialog.winfo_exists():
            naming_dialog.lift()
            return
        folder = self.folder.get().strip()
        if not folder:
            self.status.set("请先选择论文文件夹。")
            self.folder_entry.focus_set()
            return

        root = Path(folder).absolute()
        recursive, online, email = self.recursive.get(), self.online.get(), self.email.get()
        fields = tuple(self.app_settings.naming_fields)
        events = Queue()
        cancel = Event()
        self.scan_cancel = cancel
        self._set_scan_controls(busy=True)
        self.status.set("正在查找 PDF 文件……")
        if self.onboarding_step in (0, 1):
            self._render_onboarding_step(1)

        last_phase, last_update = "", 0.0

        def report(phase, completed, total):
            nonlocal last_phase, last_update
            now = monotonic()
            if phase != last_phase or completed == total or now - last_update >= 0.08:
                events.put(("progress", (phase, completed, total)))
                last_phase, last_update = phase, now

        def run():
            try:
                items = scan_papers(root, recursive, online, email, report, cancel)
                if cancel.is_set():
                    raise CancelledError()
                events.put(("progress", ("preview", 0, 0)))
                previews = build_rename_previews(items, fields=fields, conflict_strategy="suffix")
                events.put(("done", (items, previews)))
            except CancelledError:
                events.put(("cancelled", None))
            except Exception as error:
                events.put(("error", str(error)))

        Thread(target=run, name="GuiJuan scan", daemon=True).start()
        self.after(60, self._poll_scan, events, root)

    def _set_scan_controls(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (
            self.folder_entry, self.browse_button, self.recursive_check, self.online_check,
            self.naming_button, self.load_csv_button, self.undo_button, self.sidebar_save,
        ):
            widget.configure(state=state)
        self.scan_button.configure(
            state="normal", text="取消扫描" if busy else "开始扫描",
            command=self._cancel_scan if busy else self.scan,
        )
        self._update_action_state()

    def _cancel_scan(self) -> None:
        if self.scan_cancel is not None:
            self.scan_cancel.set()
            self.scan_button.configure(state="disabled")
            self.status.set("正在取消扫描……")

    def _poll_scan(self, events: Queue, root: Path) -> None:
        progress = None
        while True:
            try:
                kind, payload = events.get_nowait()
            except Empty:
                break
            if kind != "progress":
                self._finish_scan(kind, payload, root)
                return
            progress = payload
        if progress is not None and self.scan_cancel is not None and not self.scan_cancel.is_set():
            phase, completed, total = progress
            labels = {
                "discover": "正在查找 PDF 文件……",
                "local": f"正在读取 PDF · {completed} / {total}",
                "online": f"正在在线校验 · {completed} / {total}",
                "preview": "正在生成文件名预览……",
            }
            self.status.set(labels[phase])
        self.after(60, self._poll_scan, events, root)

    def _finish_scan(self, kind, payload, root: Path) -> None:
        cancelled = kind == "cancelled" or self.scan_cancel.is_set()
        if kind == "done" and not cancelled:
            self.items, self.previews = payload
            self.results_root = root
            self.scan_button.configure(state="disabled", text="正在显示结果")

            def finish_rendering():
                self._reset_scan_controls()
                if self.items:
                    self._advance_onboarding(1)

            self._populate(on_complete=finish_rendering)
            return
        self._reset_scan_controls()
        if cancelled:
            self.status.set("扫描已取消。")
        else:
            self.status.set("扫描失败。请检查文件夹路径和访问权限后重试。")
            messagebox.showerror("扫描失败", payload, parent=self)

    def _reset_scan_controls(self) -> None:
        self.scan_cancel = None
        self._set_scan_controls(busy=False)
        if self.onboarding_step == 1:
            self._render_onboarding_step(1)

    def export_csv(self) -> None:
        if self.scan_cancel is not None:
            return
        if not self.items or not self._results_match_folder():
            messagebox.showinfo("尚无当前目录的结果", "请先扫描论文。", parent=self)
            return
        destination = filedialog.asksaveasfilename(
            title="保存校对表", defaultextension=".csv",
            filetypes=(("CSV 文件", "*.csv"),), initialfile="papers-review.csv",
        )
        if destination:
            try:
                export_review_csv(destination, self._selected_root(), self.items, self.previews)
                self.status.set("校对表已导出；请修改后重新载入。")
            except Exception as error:
                messagebox.showerror("导出失败", str(error))

    def load_csv(self) -> None:
        source = filedialog.askopenfilename(title="选择校对 CSV", filetypes=(("CSV 文件", "*.csv"),))
        if source:
            try:
                root = self._selected_root().absolute()
                self.items = load_review_csv(source, root)
                self.previews = self._build_previews()
                self.results_root = root
                self._populate()
                self.status.set("已载入人工校对结果，可以预览并执行改名。")
            except Exception as error:
                messagebox.showerror("载入失败", str(error))

    def export_bib(self) -> None:
        if self.scan_cancel is not None:
            return
        if not self.items:
            messagebox.showinfo("尚无结果", "请先扫描论文。")
            return
        destination = filedialog.asksaveasfilename(
            title="保存 BibTeX", defaultextension=".bib",
            filetypes=(("BibTeX 文件", "*.bib"),), initialfile="papers.bib",
        )
        if destination:
            try:
                export_bibtex(destination, self.items)
                self.status.set("BibTeX 已导出。")
            except Exception as error:
                messagebox.showerror("导出失败", str(error))

    def edit_selected(self) -> None:
        if self.scan_cancel is not None or not self._results_match_folder():
            return
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("请选择文件", "请先在表格中选择一项。")
            return
        index = int(selection[0])
        item = self.items[index]
        preview = self.previews[index]

        dialog = tk.Toplevel(self)
        dialog.title("检查并修改论文信息")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("760x440")
        dialog.minsize(620, 390)
        dialog.configure(background=COLORS["page"])
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=item.path.name, style="Step.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Label(
            frame,
            text="未改动的自动文件名会随信息更新。确认预览后，再点击「保存全部名称」。",
            style="Metric.TLabel", wraplength=550,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        type_label = tk.StringVar(value=TYPE_LABELS.get(item.document_type, "其他"))
        values = {
            "title": tk.StringVar(value=item.title),
            "authors": tk.StringVar(value=item.authors),
            "year": tk.StringVar(value=item.year),
            "journal": tk.StringVar(value=item.journal),
            "doi": tk.StringVar(value=item.doi),
            "suggested_name": tk.StringVar(value=preview.suggested_name),
        }
        labels = (
            ("文档类型", "document_type"), ("标题", "title"),
            ("作者", "authors"), ("年份", "year"), ("期刊", "journal"), ("DOI", "doi"),
            ("最终文件名", "suggested_name"),
        )
        for offset, (label, key) in enumerate(labels):
            row = offset + 2
            ttk.Label(frame, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=6)
            if key == "document_type":
                widget = ttk.Combobox(
                    frame, textvariable=type_label, state="readonly",
                    values=tuple(TYPE_LABELS.values()),
                )
            else:
                widget = ttk.Entry(frame, textvariable=values[key])
            widget.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=6, ipady=3)
        frame.columnconfigure(1, weight=1)

        def save() -> None:
            document_type = next(
                (key for key, label in TYPE_LABELS.items() if label == type_label.get()),
                "other",
            )
            title = values["title"].get().strip()
            authors = values["authors"].get().strip()
            year = values["year"].get().strip()
            journal = values["journal"].get().strip()
            doi = values["doi"].get().strip()
            status, note = metadata_status(
                title, authors, year, doi,
                require_doi=document_type == "paper", document_type=document_type,
            )
            final_name = values["suggested_name"].get().strip()
            if not item.suggested_name and final_name == preview.suggested_name:
                final_name = ""
            self.items[index] = replace(
                item, document_type=document_type, title=title, authors=authors,
                year=year, journal=journal, doi=doi, status=status, note=note,
                source="gui-review", suggested_name=final_name,
            )
            self.previews = self._build_previews()
            self._populate()
            dialog.destroy()
            self.status.set("人工修改已保存到预览；确认无误后可保存全部名称。")

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=len(labels) + 2, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", style="Quiet.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存修改", style="Primary.TButton", command=save).pack(side="left")

    def show_duplicates(self) -> None:
        if self.scan_cancel is not None:
            return
        groups = find_duplicates(self.items)
        if not groups:
            messagebox.showinfo("重复检查", "没有发现疑似重复论文。")
            return
        lines = [f"{group.reason}:\n" + "\n".join(str(path.name) for path in group.files) for group in groups]
        messagebox.showwarning("发现疑似重复论文", "\n\n".join(lines))

    def apply_names(self) -> None:
        if self.scan_cancel is not None:
            return
        if not self.previews or not self._results_match_folder():
            messagebox.showwarning("尚无结果", "请先扫描论文或载入校对 CSV。")
            return
        ready = sum(item.status == "preview" for item in self.previews)
        skipped = len(self.previews) - ready
        if ready == 0:
            messagebox.showwarning("没有可保存名称", "请先修改红色项目的最终文件名。")
            return
        answer = messagebox.askyesno(
            "确认一键保存名称",
            f"将重命名 {ready} 个 PDF，并记录 Undo。\n红色且没有有效名称的 {skipped} 个文件会跳过。\n\n确认继续吗？",
            parent=self,
        )
        if not answer:
            self.status.set("已取消，没有修改任何文件。")
            return
        try:
            result = apply_renames(self.previews, self._selected_root())
            messagebox.showinfo("改名完成", f"已重命名 {result.changed} 个文件。")
            if self.onboarding_step == 3:
                self._finish_onboarding()
            self.items, self.previews = [], []
            self._populate()
            self.scan()
        except Exception as error:
            messagebox.showerror("改名失败", str(error))

    def undo(self) -> None:
        if not messagebox.askyesno("确认撤销", "恢复上一次批量改名吗？"):
            return
        try:
            result = undo_last(self._selected_root())
            messagebox.showinfo("撤销完成", f"已恢复 {result.changed} 个文件。")
            self.items, self.previews = [], []
            self._populate()
            self.scan()
        except Exception as error:
            messagebox.showerror("撤销失败", str(error))


def main() -> None:
    GuiJuanApp().mainloop()


if __name__ == "__main__":
    main()
