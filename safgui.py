"""MX Simulator SAF Tool - a small Tkinter GUI for .saf archives.

Open an archive to look inside and extract files, or pack a folder into a new
.saf.  Requires nothing but the Python standard library.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import safcore

APP_TITLE = "MX Simulator SAF Tool"
APP_SUBTITLE = "Open, extract and build .saf archives"

BG = "#15171c"
PANEL = "#1b1e25"
CARD = "#232833"
CARD_HOVER = "#2c323f"
FG = "#e7eaf1"
MUTED = "#8a93a6"
ACCENT = "#3d8bfd"
ACCENT_HOVER = "#5b9dff"
DANGER = "#e0606b"
SELECT = "#2c4a76"

TYPE_COLORS = {
    ".png": "#7fb2ff",
    ".jm": "#6ed3a0",
    ".shp": "#e7b168",
    ".sec": "#c79bf0",
}


def _base_font(size: int = 10, weight: str = "normal") -> tuple[str, int, str]:
    family = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
    return (family, size, weight)


class App(tk.Tk):
    def __init__(self, initial_saf: str | None = None) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1020x680")
        self.minsize(780, 520)
        self.configure(bg=BG)

        # ---- extract state ----
        self.archive: safcore.SafArchive | None = None
        self.visible_entries: list[safcore.SafEntry] = []
        self.dest_var = tk.StringVar()
        self.overwrite_var = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()
        self.extract_info_var = tk.StringVar(value="No archive open")
        self.extract_status_var = tk.StringVar(value="Open a .saf file to begin.")
        self.extract_progress_var = tk.DoubleVar(value=0.0)

        # ---- create state ----
        self.source_folder: str | None = None
        self.create_items: list[tuple[str, str]] = []
        self.create_excluded: set[str] = set()
        self.root_name_var = tk.StringVar()
        self.wrap_root_var = tk.BooleanVar(value=True)
        self.output_var = tk.StringVar()
        self.create_info_var = tk.StringVar(value="No folder selected")
        self.create_status_var = tk.StringVar(value="Pick a folder to pack.")
        self.create_progress_var = tk.DoubleVar(value=0.0)

        # ---- worker state ----
        self.queue: queue.Queue | None = None
        self.cancel_event: threading.Event | None = None
        self.worker_kind: str | None = None

        self._apply_theme()
        self._build_ui()
        self.bind("<Control-a>", lambda _event: self._select_all_entries())
        self.bind("<Control-o>", lambda _event: self.open_dialog())

        if initial_saf:
            self.load_archive(initial_saf)

    # ------------------------------------------------------------------
    # theme / layout
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=_base_font())
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", font=_base_font(17, "bold"))
        style.configure(
            "TButton",
            background=CARD,
            foreground=FG,
            borderwidth=0,
            focuscolor=BG,
            padding=(13, 7),
        )
        style.map(
            "TButton",
            background=[("active", CARD_HOVER), ("disabled", PANEL)],
            foreground=[("disabled", "#4b5262")],
        )
        style.configure(
            "Accent.TButton", background=ACCENT, foreground="#ffffff"
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", "#243040")],
            foreground=[("disabled", "#5c6a80")],
        )
        style.configure(
            "TEntry",
            fieldbackground=CARD,
            foreground=FG,
            insertcolor=FG,
            bordercolor=CARD,
            lightcolor=CARD,
            darkcolor=CARD,
            borderwidth=0,
            padding=7,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure(
            "TCheckbutton", background=BG, foreground=FG, focuscolor=BG
        )
        style.map(
            "TCheckbutton",
            background=[("active", BG)],
            indicatorcolor=[("selected", ACCENT), ("!selected", CARD)],
            foreground=[("disabled", "#4b5262")],
        )
        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=FG,
            borderwidth=0,
            rowheight=25,
        )
        style.map(
            "Treeview",
            background=[("selected", SELECT)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Treeview.Heading",
            background=BG,
            foreground=MUTED,
            relief="flat",
            padding=(8, 7),
            font=_base_font(9, "bold"),
        )
        style.map("Treeview.Heading", background=[("active", CARD)])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=BG,
            foreground=MUTED,
            padding=(20, 9),
            borderwidth=0,
            font=_base_font(10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", FG)],
        )
        style.configure(
            "TProgressbar",
            background=ACCENT,
            troughcolor=PANEL,
            borderwidth=0,
            thickness=6,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=CARD,
            troughcolor=PANEL,
            arrowcolor=MUTED,
            borderwidth=0,
        )
        style.map("Vertical.TScrollbar", background=[("active", CARD_HOVER)])

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 16, 18, 4))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=APP_SUBTITLE, style="Muted.TLabel").pack(anchor="w")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(8, 16))

        self.extract_tab = ttk.Frame(self.notebook, padding=16)
        self.create_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.extract_tab, text="Extract")
        self.notebook.add(self.create_tab, text="Create")

        self._build_extract_tab()
        self._build_create_tab()

    def _build_extract_tab(self) -> None:
        tab = self.extract_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew")
        self.open_button = ttk.Button(
            top, text="Open .saf\u2026", style="Accent.TButton", command=self.open_dialog
        )
        self.open_button.pack(side="left")
        self.archive_label = ttk.Label(top, text="No archive open", style="Muted.TLabel")
        self.archive_label.pack(side="left", padx=12)
        ttk.Label(top, textvariable=self.extract_info_var, style="Muted.TLabel").pack(
            side="right"
        )

        search = ttk.Frame(tab)
        search.grid(row=1, column=0, sticky="ew", pady=(14, 8))
        search.columnconfigure(0, weight=1)
        self.filter_entry = ttk.Entry(search, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky="ew")
        self.filter_entry.insert(0, "")
        self.filter_var.trace_add("write", lambda *_: self._refresh_entry_list())
        ttk.Label(search, text="Filter", style="Muted.TLabel").grid(
            row=0, column=1, padx=(10, 0)
        )

        columns = ("name", "size", "type")
        tree_wrap = ttk.Frame(tab, style="Card.TFrame")
        tree_wrap.grid(row=2, column=0, sticky="nsew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_wrap, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("name", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("type", text="Type")
        self.tree.column("name", width=560, anchor="w", stretch=True)
        self.tree.column("size", width=110, anchor="e", stretch=False)
        self.tree.column("type", width=100, anchor="w", stretch=False)
        for ext, color in TYPE_COLORS.items():
            self.tree.tag_configure(ext.replace(".", "ext_"), foreground=color)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        tab.rowconfigure(2, weight=1)

        bottom = ttk.Frame(tab)
        bottom.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        bottom.columnconfigure(1, weight=1)

        ttk.Label(bottom, text="Extract to", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.dest_entry = ttk.Entry(bottom, textvariable=self.dest_var)
        self.dest_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.browse_dest_button = ttk.Button(
            bottom, text="Browse\u2026", command=self._choose_dest
        )
        self.browse_dest_button.grid(row=0, column=2)

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.extract_all_button = ttk.Button(
            actions, text="Extract all", style="Accent.TButton", command=self.extract_all
        )
        self.extract_all_button.pack(side="left")
        self.extract_sel_button = ttk.Button(
            actions, text="Extract selected", command=self.extract_selected
        )
        self.extract_sel_button.pack(side="left", padx=8)
        self.select_all_button = ttk.Button(
            actions, text="Select all", command=self._select_all_entries
        )
        self.select_all_button.pack(side="left")
        self.extract_cancel_button = ttk.Button(
            actions, text="Cancel", command=self._request_cancel
        )
        ttk.Checkbutton(
            actions, text="Overwrite existing files", variable=self.overwrite_var
        ).pack(side="right")

        status = ttk.Frame(tab)
        status.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        status.columnconfigure(0, weight=1)
        ttk.Progressbar(
            status, variable=self.extract_progress_var, maximum=100.0
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(status, textvariable=self.extract_status_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )

    def _build_create_tab(self) -> None:
        tab = self.create_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(4, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew")
        self.folder_button = ttk.Button(
            top, text="Choose folder\u2026", style="Accent.TButton", command=self.choose_folder
        )
        self.folder_button.pack(side="left")
        self.folder_label = ttk.Label(top, text="No folder selected", style="Muted.TLabel")
        self.folder_label.pack(side="left", padx=12)
        ttk.Label(top, textvariable=self.create_info_var, style="Muted.TLabel").pack(
            side="right"
        )

        options = ttk.Frame(tab)
        options.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Root name", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.root_entry = ttk.Entry(options, textvariable=self.root_name_var)
        self.root_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.root_entry.bind("<Return>", lambda _event: self._reload_create_list())
        self.root_entry.bind("<FocusOut>", lambda _event: self._reload_create_list())
        self.wrap_check = ttk.Checkbutton(
            options,
            text="Store files inside the root folder",
            variable=self.wrap_root_var,
            command=self._reload_create_list,
        )
        self.wrap_check.grid(row=0, column=2, sticky="e")
        ttk.Label(
            options,
            text="Files inside the game archive always use forward slashes, e.g. "
            "mytrack/models/post.jm",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        file_wrap = ttk.Frame(tab, style="Card.TFrame")
        file_wrap.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        file_wrap.columnconfigure(0, weight=1)
        file_wrap.rowconfigure(0, weight=1)
        self.create_tree = ttk.Treeview(
            file_wrap, columns=("name", "size"), show="headings", selectmode="extended"
        )
        self.create_tree.heading("name", text="File (inside archive)")
        self.create_tree.heading("size", text="Size")
        self.create_tree.column("name", width=680, anchor="w", stretch=True)
        self.create_tree.column("size", width=110, anchor="e", stretch=False)
        for ext, color in TYPE_COLORS.items():
            self.create_tree.tag_configure(ext.replace(".", "ext_"), foreground=color)
        self.create_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(file_wrap, orient="vertical", command=self.create_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.create_tree.configure(yscrollcommand=scroll.set)
        tab.rowconfigure(2, weight=1)

        list_actions = ttk.Frame(tab)
        list_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.exclude_button = ttk.Button(
            list_actions, text="Exclude selected", command=self.exclude_selected
        )
        self.exclude_button.pack(side="left")
        self.refresh_button = ttk.Button(
            list_actions, text="Refresh", command=self._reload_create_list
        )
        self.refresh_button.pack(side="left", padx=8)

        output = ttk.Frame(tab)
        output.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="Save as", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.output_entry = ttk.Entry(output, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.output_button = ttk.Button(
            output, text="Browse\u2026", command=self._choose_output
        )
        self.output_button.grid(row=0, column=2)

        build_actions = ttk.Frame(tab)
        build_actions.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.build_button = ttk.Button(
            build_actions, text="Build .saf", style="Accent.TButton", command=self.build_saf
        )
        self.build_button.pack(side="left")
        self.build_cancel_button = ttk.Button(
            build_actions, text="Cancel", command=self._request_cancel
        )

        status = ttk.Frame(tab)
        status.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        status.columnconfigure(0, weight=1)
        ttk.Progressbar(
            status, variable=self.create_progress_var, maximum=100.0
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(status, textvariable=self.create_status_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )

    # ------------------------------------------------------------------
    # extract tab behaviour
    # ------------------------------------------------------------------
    def open_dialog(self) -> None:
        if self._busy():
            return
        initial = os.path.dirname(self.archive.path) if self.archive else os.getcwd()
        path = filedialog.askopenfilename(
            parent=self,
            title="Open .saf archive",
            initialdir=initial,
            filetypes=[("MX Simulator archive", "*.saf"), ("All files", "*.*")],
        )
        if path:
            self.load_archive(path)

    def load_archive(self, path: str) -> None:
        try:
            archive = safcore.read(path)
        except (safcore.SafError, OSError) as exc:
            messagebox.showerror(APP_TITLE, "Could not open %s\n\n%s" % (os.path.basename(path), exc))
            return

        self.archive = archive
        self.archive_label.configure(text=os.path.basename(archive.path))
        self.title("%s \u2014 %s" % (os.path.basename(archive.path), APP_TITLE))
        self.extract_info_var.set(
            "%d files \u00b7 %s \u00b7 header %s"
            % (
                len(archive.entries),
                safcore.human_size(archive.total_size),
                safcore.human_size(archive.header_size),
            )
        )
        self.filter_var.set("")
        self.dest_var.set(
            os.path.join(os.path.dirname(archive.path), archive.stem)
        )
        self.extract_progress_var.set(0.0)
        self._refresh_entry_list()
        if archive.warnings:
            self.extract_status_var.set(archive.warnings[0])
        else:
            self.extract_status_var.set("Ready to extract.")

    def _refresh_entry_list(self) -> None:
        needle = self.filter_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.visible_entries = []
        if self.archive is not None:
            for entry in self.archive.entries:
                if needle and needle not in entry.name.lower():
                    continue
                self.visible_entries.append(entry)
                self.tree.insert(
                    "",
                    "end",
                    iid=str(len(self.visible_entries) - 1),
                    values=(
                        entry.name,
                        safcore.human_size(entry.size),
                        entry.extension.lstrip(".").upper() or "\u2014",
                    ),
                    tags=(entry.extension.replace(".", "ext_"),),
                )
        if self.archive is None:
            self.extract_info_var.set("No archive open")
        else:
            shown = len(self.visible_entries)
            total = len(self.archive.entries)
            self.extract_info_var.set(
                "%d files \u00b7 %s%s"
                % (
                    total,
                    safcore.human_size(self.archive.total_size),
                    "" if shown == total else " \u00b7 %d shown" % shown,
                )
            )

    def _select_all_entries(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def _choose_dest(self) -> None:
        initial = self.dest_var.get() or os.getcwd()
        path = filedialog.askdirectory(parent=self, title="Extract to folder", initialdir=initial)
        if path:
            self.dest_var.set(path)

    def extract_all(self) -> None:
        self._extract(self.archive.entries if self.archive else None)

    def extract_selected(self) -> None:
        if self.archive is None:
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Select one or more files first.")
            return
        entries = [self.visible_entries[int(iid)] for iid in selection]
        self._extract(entries)

    def _extract(self, entries) -> None:
        if self._busy():
            return
        if self.archive is None or not entries:
            return
        dest = self.dest_var.get().strip()
        if not dest:
            self._choose_dest()
            dest = self.dest_var.get().strip()
            if not dest:
                return
        archive = self.archive
        overwrite = self.overwrite_var.get()
        self.extract_progress_var.set(0.0)
        self.extract_status_var.set("Starting\u2026")
        self._set_busy(True, "extract")

        def work(reporter, cancel):
            return safcore.extract(
                archive,
                dest,
                entries=entries,
                overwrite=overwrite,
                progress=reporter,
                cancel=cancel,
            )

        self._run(work, "extract")

    def _extract_finished(self, result: safcore.ExtractResult) -> None:
        self._set_busy(False, "extract")
        if result.cancelled:
            self.extract_status_var.set(
                "Cancelled. Extracted %d files to %s" % (result.written, result.dest)
            )
            return
        self.extract_progress_var.set(100.0)
        message = "Extracted %d files to %s" % (result.written, result.dest)
        if result.skipped:
            message += " (%d skipped)" % result.skipped
        if result.errors:
            message += " (%d errors)" % len(result.errors)
        self.extract_status_var.set(message)
        if result.errors:
            details = "\n".join("%s: %s" % item for item in result.errors[:15])
            if len(result.errors) > 15:
                details += "\n\u2026"
            messagebox.showwarning(APP_TITLE, "%s\n\n%s" % (message, details))

    # ------------------------------------------------------------------
    # create tab behaviour
    # ------------------------------------------------------------------
    def choose_folder(self) -> None:
        if self._busy():
            return
        path = filedialog.askdirectory(
            parent=self, title="Folder to pack", initialdir=self.source_folder or os.getcwd()
        )
        if not path:
            return
        self.source_folder = os.path.abspath(path)
        name = os.path.basename(self.source_folder.rstrip("\\/"))
        self.root_name_var.set(name)
        self.wrap_root_var.set(True)
        self.create_excluded.clear()
        if not self.output_var.get().strip():
            self.output_var.set(
                os.path.join(os.path.dirname(self.source_folder), name + ".saf")
            )
        self.folder_label.configure(text=name)
        self._reload_create_list()

    def _reload_create_list(self) -> None:
        if self._busy() or not self.source_folder:
            return
        root = self.root_name_var.get().strip() if self.wrap_root_var.get() else ""
        try:
            root = safcore.clean_archive_name(root) if root else ""
        except safcore.SafError as exc:
            self.create_status_var.set("Root name: %s" % exc)
            return
        try:
            items = safcore.collect_files(self.source_folder, root)
        except safcore.SafError as exc:
            self.create_status_var.set(str(exc))
            return

        self.create_items = [
            (arcname, path)
            for arcname, path in items
            if path not in self.create_excluded
        ]
        self.create_tree.delete(*self.create_tree.get_children())
        total = 0
        for arcname, path in self.create_items:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            total += size
            extension = os.path.splitext(arcname)[1].lower()
            self.create_tree.insert(
                "",
                "end",
                iid=path,
                values=(arcname, safcore.human_size(size)),
                tags=(extension.replace(".", "ext_"),),
            )
        self.create_info_var.set(
            "%d files \u00b7 %s" % (len(self.create_items), safcore.human_size(total))
        )
        excluded = len(self.create_excluded)
        self.create_status_var.set(
            "Add files to the list, then build."
            if not excluded
            else "%d file(s) excluded." % excluded
        )

    def exclude_selected(self) -> None:
        if self._busy():
            return
        selection = self.create_tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Select files in the list to exclude.")
            return
        for path in selection:
            self.create_excluded.add(path)
        self._reload_create_list()

    def _choose_output(self) -> None:
        initial = self.output_var.get().strip() or os.getcwd()
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save .saf as",
            initialdir=os.path.dirname(initial) or os.getcwd(),
            initialfile=os.path.basename(initial) or "new.saf",
            defaultextension=".saf",
            filetypes=[("MX Simulator archive", "*.saf")],
        )
        if path:
            self.output_var.set(path)

    def build_saf(self) -> None:
        if self._busy():
            return
        if not self.create_items:
            messagebox.showinfo(APP_TITLE, "Choose a folder with files to pack first.")
            return
        output = self.output_var.get().strip()
        if not output:
            self._choose_output()
            output = self.output_var.get().strip()
            if not output:
                return
        if not output.lower().endswith(".saf"):
            output += ".saf"
            self.output_var.set(output)
        if os.path.exists(output):
            if not messagebox.askyesno(APP_TITLE, "Replace the existing file?\n\n%s" % output):
                return

        items = list(self.create_items)
        self.create_progress_var.set(0.0)
        self.create_status_var.set("Starting\u2026")
        self._set_busy(True, "build")

        def work(reporter, cancel):
            return safcore.build(output, items, progress=reporter, cancel=cancel)

        self._run(work, "build")

    def _build_finished(self, result: safcore.BuildResult) -> None:
        self._set_busy(False, "build")
        if result.cancelled:
            self.create_status_var.set("Cancelled. No archive was written.")
            return
        self.create_progress_var.set(100.0)
        size = os.path.getsize(result.path) if os.path.exists(result.path) else 0
        message = "Built %s \u00b7 %d files \u00b7 %s" % (
            os.path.basename(result.path),
            result.count,
            safcore.human_size(size),
        )
        self.create_status_var.set(message)
        messagebox.showinfo(APP_TITLE, message)

    # ------------------------------------------------------------------
    # worker plumbing
    # ------------------------------------------------------------------
    def _busy(self) -> bool:
        if self.worker_kind is not None:
            messagebox.showinfo(APP_TITLE, "Please wait for the current task to finish.")
            return True
        return False

    def _set_busy(self, busy: bool, kind: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        for widget in (
            self.open_button,
            self.extract_all_button,
            self.extract_sel_button,
            self.select_all_button,
            self.folder_button,
            self.build_button,
            self.exclude_button,
            self.refresh_button,
            self.browse_dest_button,
            self.output_button,
        ):
            widget.configure(state=state)
        for button in (self.extract_cancel_button, self.build_cancel_button):
            button.pack_forget()
        if busy:
            manager = (
                self.extract_all_button
                if kind == "extract"
                else self.build_button
            )
            target = (
                self.extract_cancel_button if kind == "extract" else self.build_cancel_button
            )
            target.pack(side="left", padx=8, after=manager)
        self.worker_kind = kind if busy else None

    def _request_cancel(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
            if self.worker_kind == "extract":
                self.extract_status_var.set("Cancelling\u2026")
            else:
                self.create_status_var.set("Cancelling\u2026")

    def _run(self, work, kind: str) -> None:
        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        worker_queue = self.queue
        worker_cancel = self.cancel_event

        def reporter(done: int, total: int, name: str) -> None:
            worker_queue.put(("progress", done, total, name))

        def runner() -> None:
            try:
                result = work(reporter, worker_cancel.is_set)
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI
                worker_queue.put(("error", exc))
            else:
                worker_queue.put(("done", result))

        threading.Thread(target=runner, daemon=True).start()
        self.after(80, lambda: self._poll(kind))

    def _poll(self, kind: str) -> None:
        assert self.queue is not None
        finished = False
        try:
            while True:
                message = self.queue.get_nowait()
                if message[0] == "progress":
                    _, done, total, name = message
                    percent = (done / total * 100.0) if total else 0.0
                    if kind == "extract":
                        self.extract_progress_var.set(percent)
                        if name:
                            self.extract_status_var.set(
                                "%s \u2014 %s of %s"
                                % (name, safcore.human_size(done), safcore.human_size(total))
                            )
                    else:
                        self.create_progress_var.set(percent)
                        if name:
                            self.create_status_var.set(
                                "%s \u2014 %s of %s"
                                % (name, safcore.human_size(done), safcore.human_size(total))
                            )
                elif message[0] == "done":
                    finished = True
                    result = message[1]
                    if kind == "extract":
                        self._extract_finished(result)
                    else:
                        self._build_finished(result)
                elif message[0] == "error":
                    finished = True
                    self._set_busy(False, kind)
                    error = message[1]
                    if kind == "extract":
                        self.extract_status_var.set("Failed: %s" % error)
                    else:
                        self.create_status_var.set("Failed: %s" % error)
                    messagebox.showerror(APP_TITLE, str(error))
        except queue.Empty:
            pass
        if not finished:
            self.after(80, lambda: self._poll(kind))


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    initial = None
    for argument in argv:
        if argument.lower().endswith(".saf") and os.path.isfile(argument):
            initial = argument
            break
    app = App(initial_saf=initial)
    app.mainloop()


if __name__ == "__main__":
    main()
