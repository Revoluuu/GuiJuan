from __future__ import annotations

import tkinter as tk
import sys
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List

from .arxiv_api import enrich_from_arxiv
from .crossref import CrossrefClient, enrich_from_crossref
from .csv_review import export_review_csv, load_review_csv
from .duplicates import find_duplicates
from .metadata import PaperMetadata, extract_paper_metadata, metadata_status
from .naming import RenamePreview, build_rename_previews
from .operations import apply_renames, undo_last
from .scanner import scan_pdf_files
from .bibtex import export_bibtex


COLORS = {
    "page": "#d9b77d",
    "sidebar": "#f1e4cd",
    "main": "#f8f3e9",
    "surface": "#fffdf8",
    "ink": "#3f2d1d",
    "muted": "#756859",
    "brand": "#2f7567",
    "brand_hover": "#245d52",
    "brown": "#7a4b24",
    "line": "#dfd1bc",
    "ready": "#d9efe1",
    "review": "#ffe5a8",
    "failed": "#f7c7bd",
}

TYPE_LABELS = {"paper": "论文", "appendix": "附录", "book": "书籍", "other": "其他"}


class GuiJuanApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("归卷 GuiJuan - 论文 PDF 整理器")
        self.geometry("1280x720")
        self.minsize(1050, 620)
        self.configure(background=COLORS["page"])
        self.folder = tk.StringVar()
        self.email = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.online = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="准备就绪。选择论文文件夹后开始扫描。")
        self.total_text = tk.StringVar(value="0 个文件")
        self.ready_text = tk.StringVar(value="0 个可保存")
        self.review_text = tk.StringVar(value="0 个需检查")
        self.attention_text = tk.StringVar(value="0 个建议检查")
        self.blocked_text = tk.StringVar(value="0 个必须修改")
        self.items: List[PaperMetadata] = []
        self.previews: List[RenamePreview] = []
        self._configure_style()
        self._load_brand_assets()
        self._build()

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
        self._sidebar_button(sidebar, "03   保存名称", self.apply_names)
        tk.Label(sidebar, text="工具", background=COLORS["sidebar"], foreground=COLORS["muted"], anchor="w", font=("Microsoft YaHei UI", 8, "bold")).pack(fill="x", padx=20, pady=(16, 6))
        self._sidebar_button(sidebar, "导出校对 CSV", self.export_csv)
        self._sidebar_button(sidebar, "导出 BibTeX", self.export_bib)
        self._sidebar_button(sidebar, "检查重复论文", self.show_duplicates)
        self._sidebar_button(sidebar, "Crossref 设置", self.configure_crossref)
        if self.side_image:
            tk.Label(sidebar, image=self.side_image, background=COLORS["sidebar"], bd=0).pack(side="bottom", fill="x")

        main = tk.Frame(shell, background=COLORS["main"], bd=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(3, weight=1)
        main.grid_columnconfigure(0, weight=1)

        banner = tk.Canvas(main, height=108, background=COLORS["page"], highlightthickness=0)
        banner.grid(row=0, column=0, sticky="ew")
        if self.banner_image:
            banner.create_image(0, 0, image=self.banner_image, anchor="nw")
        banner.create_text(24, 34, text="论文整理", anchor="w", fill=COLORS["ink"], font=("Microsoft YaHei UI", 18, "bold"))
        banner.create_text(24, 67, text="选择文件夹，检查识别结果，再安全保存名称。", anchor="w", fill="#69533d", font=("Microsoft YaHei UI", 9))

        folder_card = ttk.Frame(main, style="Card.TFrame", padding=14)
        folder_card.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 8))
        ttk.Label(folder_card, text="选择论文文件夹", style="Step.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.folder_entry = ttk.Entry(folder_card, textvariable=self.folder, font=("Microsoft YaHei UI", 10))
        self.folder_entry.grid(row=1, column=0, sticky="ew", ipady=5)
        ttk.Button(folder_card, text="浏览文件夹", style="Secondary.TButton", command=self.choose_folder).grid(row=1, column=1, padx=(10, 0))
        ttk.Button(folder_card, text="开始扫描", style="Primary.TButton", command=self.scan).grid(row=1, column=2, padx=(10, 0))
        options = tk.Frame(folder_card, background=COLORS["surface"])
        options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._classic_checkbutton(options, "包含子文件夹", self.recursive).pack(side="left")
        self._classic_checkbutton(options, "Crossref 在线校验（仅发送 DOI）", self.online).pack(side="left", padx=(16, 0))
        folder_card.columnconfigure(0, weight=1)

        review_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        review_card.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        ttk.Label(review_card, text="论文文件", style="Step.TLabel").pack(side="left")
        metrics = ttk.Frame(review_card, style="Card.TFrame")
        metrics.pack(side="left", padx=(24, 0))
        ttk.Label(metrics, textvariable=self.total_text, style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, text="  ·  ", style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, textvariable=self.ready_text, style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, text="  ·  ", style="Metric.TLabel").pack(side="left")
        ttk.Label(metrics, textvariable=self.review_text, style="Metric.TLabel").pack(side="left")
        self.more_button = ttk.Button(review_card, text="更多功能  ▾", style="Quiet.TButton", command=self.show_more_menu)
        self.more_button.pack(side="right")
        self.edit_button = ttk.Button(review_card, text="编辑选中项", style="Secondary.TButton", command=self.edit_selected, state="disabled")
        self.edit_button.pack(side="right", padx=(0, 8))

        columns = ("file", "type", "title", "year", "suggested", "status")
        table_frame = ttk.Frame(main, style="Card.TFrame", padding=2)
        table_frame.grid(row=3, column=0, sticky="nsew", padx=12)
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
        widths = (145, 50, 190, 48, 230, 82)
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
        action_card.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 6))
        ttk.Label(action_card, text="确认后保存", style="Step.TLabel").pack(side="left")
        ttk.Label(action_card, text="改名前请检查黄色和红色项目", style="Metric.TLabel").pack(side="left", padx=(18, 0))
        self.save_button = ttk.Button(action_card, text="保存全部名称", style="Primary.TButton", command=self.apply_names, state="disabled")
        self.save_button.pack(side="right")
        ttk.Button(action_card, text="撤销上次改名", style="Quiet.TButton", command=self.undo).pack(side="right", padx=(0, 8))

        ttk.Label(main, textvariable=self.status, style="Status.TLabel", anchor="w").grid(row=5, column=0, sticky="ew")

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
        tk.Label(right, text="隐私：PDF 内容在本地处理；在线校验仅发送 DOI。", background=COLORS["sidebar"], foreground=COLORS["muted"], justify="left", wraplength=185, font=("Microsoft YaHei UI", 8)).pack(side="bottom", fill="x")

    @staticmethod
    def _classic_checkbutton(parent, text: str, variable: tk.BooleanVar):
        return tk.Checkbutton(
            parent, text=text, variable=variable, onvalue=True, offvalue=False,
            background=COLORS["surface"], activebackground=COLORS["surface"],
            foreground=COLORS["muted"], selectcolor="#ffffff",
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
        )

    @staticmethod
    def _sidebar_button(parent, text: str, command, selected: bool = False) -> None:
        background = "#e4d2b5" if selected else COLORS["sidebar"]
        button = tk.Button(
            parent, text=text, command=command, anchor="w", relief="flat", bd=0,
            padx=20, pady=8, background=background, activebackground="#e4d2b5",
            foreground=COLORS["brown"] if selected else COLORS["ink"],
            font=("Microsoft YaHei UI", 9, "bold" if selected else "normal"),
        )
        button.pack(fill="x", padx=10, pady=1)

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
            preview.status == "preview" and item.status != "complete" and item.source != "gui-review"
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
        self.edit_button.configure(state="normal" if self.table.selection() else "disabled")
        can_save = any(preview.status == "preview" for preview in self.previews)
        self.save_button.configure(state="normal" if can_save else "disabled")

    def show_more_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="导出校对 CSV", command=self.export_csv)
        menu.add_command(label="载入校对 CSV", command=self.load_csv)
        menu.add_command(label="导出 BibTeX", command=self.export_bib)
        menu.add_command(label="检查重复论文", command=self.show_duplicates)
        menu.add_separator()
        menu.add_command(label="Crossref 访问设置…", command=self.configure_crossref)
        try:
            menu.tk_popup(
                self.more_button.winfo_rootx(),
                self.more_button.winfo_rooty() + self.more_button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def configure_crossref(self) -> None:
        value = simpledialog.askstring(
            "Crossref 访问设置",
            "联系邮箱（可留空）\n仅随 DOI 查询发送，用于 Crossref 请求标识；不是登录账号。",
            initialvalue=self.email.get(), parent=self,
        )
        if value is not None:
            self.email.set(value.strip())
            self.status.set("Crossref 联系邮箱已更新。" if value.strip() else "Crossref 将使用匿名公共访问。")

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择论文文件夹")
        if selected:
            self.folder.set(selected)

    def _selected_root(self) -> Path:
        root = Path(self.folder.get().strip())
        if not root.is_dir():
            raise ValueError("请先选择有效的论文文件夹。")
        return root

    def _populate(self) -> None:
        self.table.delete(*self.table.get_children())
        ready_count = 0
        attention_count = 0
        blocked_count = 0
        for index, (item, preview) in enumerate(zip(self.items, self.previews)):
            blocked = preview.status != "preview"
            reviewed = item.source == "gui-review" and not blocked
            uncertain = item.status != "complete" and not reviewed and not blocked
            if blocked:
                display_status, tags = "× 必须修改", ("failed",)
                blocked_count += 1
            elif uncertain:
                display_status, tags = "! 建议检查", ("review",)
                attention_count += 1
            elif reviewed:
                display_status, tags = "✓ 已确认", ("reviewed",)
                ready_count += 1
            else:
                display_status, tags = "✓ 可保存", ("ready",)
                ready_count += 1
            status_key = tags[0]
            self.table.insert("", "end", iid=str(index), tags=tags, image=self.status_images[status_key], values=(
                item.path.name, TYPE_LABELS.get(item.document_type, item.document_type),
                item.title, item.year, preview.suggested_name, display_status,
            ))
        self.total_text.set(f"{len(self.items)} 个文件")
        self.ready_text.set(f"{ready_count} 个可保存")
        self.attention_text.set(f"{attention_count} 个")
        self.blocked_text.set(f"{blocked_count} 个")
        review_count = attention_count + blocked_count
        self.review_text.set(f"{review_count} 个需检查")
        if self.items:
            self.empty_state.place_forget()
        else:
            self.empty_state.place(relx=0.5, rely=0.48, anchor="center")
        self._update_action_state()
        self._update_summary_panel()
        self.status.set(
            f"扫描完成：{ready_count} 个可直接保存，{review_count} 个建议检查。"
            if self.items else "没有找到 PDF 文件。"
        )

    def scan(self) -> None:
        try:
            self.status.set("正在读取论文，请稍候……")
            self.update_idletasks()
            root = self._selected_root()
            files = scan_pdf_files(root, recursive=self.recursive.get())
            items = [extract_paper_metadata(file.path) for file in files]
            if self.online.get():
                client = CrossrefClient(self.email.get())
                items = [enrich_from_crossref(item, client) for item in items]
                items = [enrich_from_arxiv(item) if not item.doi else item for item in items]
            self.items = items
            self.previews = build_rename_previews(items)
            self._populate()
        except Exception as error:
            messagebox.showerror("扫描失败", str(error))

    def export_csv(self) -> None:
        if not self.items:
            messagebox.showinfo("尚无结果", "请先扫描论文。")
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
                self.items = load_review_csv(source, self._selected_root())
                self.previews = build_rename_previews(self.items)
                self._populate()
                self.status.set("已载入人工校对结果，可以预览并执行改名。")
            except Exception as error:
                messagebox.showerror("载入失败", str(error))

    def export_bib(self) -> None:
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
        ttk.Label(frame, text="修改后只会更新当前预览，点击“保存全部名称”后才会真正重命名。", style="Metric.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        type_label = tk.StringVar(value=TYPE_LABELS.get(item.document_type, "其他"))
        values = {
            "title": tk.StringVar(value=item.title),
            "authors": tk.StringVar(value=item.authors),
            "year": tk.StringVar(value=item.year),
            "doi": tk.StringVar(value=item.doi),
            "suggested_name": tk.StringVar(value=preview.suggested_name),
        }
        labels = (
            ("文档类型", "document_type"), ("标题", "title"),
            ("作者", "authors"), ("年份", "year"), ("DOI", "doi"),
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
            doi = values["doi"].get().strip()
            status, note = metadata_status(
                title, authors, year, doi,
                require_doi=document_type == "paper", document_type=document_type,
            )
            self.items[index] = replace(
                item, document_type=document_type, title=title, authors=authors,
                year=year, doi=doi, status=status, note=note,
                source="gui-review", suggested_name=values["suggested_name"].get().strip(),
            )
            self.previews = build_rename_previews(self.items)
            self._populate()
            dialog.destroy()
            self.status.set("人工修改已保存到预览；确认无误后可保存全部名称。")

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.grid(row=len(labels) + 2, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", style="Quiet.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存修改", style="Primary.TButton", command=save).pack(side="left")

    def show_duplicates(self) -> None:
        groups = find_duplicates(self.items)
        if not groups:
            messagebox.showinfo("重复检查", "没有发现疑似重复论文。")
            return
        lines = [f"{group.reason}:\n" + "\n".join(str(path.name) for path in group.files) for group in groups]
        messagebox.showwarning("发现疑似重复论文", "\n\n".join(lines))

    def apply_names(self) -> None:
        if not self.previews:
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
            self.scan()
        except Exception as error:
            messagebox.showerror("改名失败", str(error))

    def undo(self) -> None:
        if not messagebox.askyesno("确认撤销", "恢复上一次批量改名吗？"):
            return
        try:
            result = undo_last(self._selected_root())
            messagebox.showinfo("撤销完成", f"已恢复 {result.changed} 个文件。")
            self.scan()
        except Exception as error:
            messagebox.showerror("撤销失败", str(error))


def main() -> None:
    GuiJuanApp().mainloop()


if __name__ == "__main__":
    main()
