"""Tkinter desktop UI. Tk widgets and SQLite are only touched on the UI thread."""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import logging
from pathlib import Path
import queue
import sqlite3
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .database import Database
from .generator import Board, generate, place_word, place_word_with_dictionary
from .models import Entry, Placement, Puzzle, clean_text

ALL_CATEGORIES = "Alle kategorier"
DIRECTION_LABELS = {"Vandret": "across", "Lodret": "down"}


def action(function):
    """Report expected user/input/file errors without crashing the event loop."""
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except (ValueError, OSError, sqlite3.Error, tk.TclError, UnicodeError) as exc:
            messagebox.showerror("Handlingen kunne ikke gennemføres", str(exc), parent=self)
            return False
    return wrapped


class EntryDialog(simpledialog.Dialog):
    def __init__(self, parent, title: str, entry: Entry | None = None, new_clue: bool = False):
        self.entry, self.new_clue = entry, new_clue
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        self.word = tk.StringVar(value=self.entry.answer if self.entry else "")
        self.category = tk.StringVar(value=self.entry.category if self.entry else "")
        ttk.Label(master, text="Svarord (A-Z og Æ, Ø, Å):").grid(row=0, column=0, sticky="w", pady=5)
        field = ttk.Entry(master, textvariable=self.word, width=48)
        field.grid(row=1, column=0, sticky="ew")
        ttk.Label(master, text="Ordforklaring:").grid(row=2, column=0, sticky="w", pady=(12, 5))
        self.clue = tk.Text(master, height=5, width=56, wrap="word", font=("Segoe UI", 10))
        self.clue.grid(row=3, column=0, sticky="ew")
        if self.entry and not self.new_clue:
            self.clue.insert("1.0", self.entry.clue)
        ttk.Label(master, text="Kategori (valgfri):").grid(row=4, column=0, sticky="w", pady=(12, 5))
        ttk.Entry(master, textvariable=self.category).grid(row=5, column=0, sticky="ew")
        ttk.Label(master, text="Mellemrum, bindestreger og apostroffer fjernes fra svarordet.",
                  style="Muted.TLabel").grid(row=6, column=0, sticky="w", pady=10)
        return self.clue if self.new_clue else field

    def validate(self):
        try:
            self.result = Entry.create(self.word.get(), self.clue.get("1.0", "end"), self.category.get())
            return True
        except ValueError as exc:
            messagebox.showerror("Kontrollér indtastningen", str(exc), parent=self)
            return False


class ExportDialog(simpledialog.Dialog):
    def body(self, master):
        self.mode = tk.StringVar(value="puzzle")
        ttk.Label(master, text="Hvad skal PDF-filen indeholde?", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=8)
        for text, value in (("Opgave uden svar", "puzzle"),
                            ("Opgave og facit på separate sider", "both"),
                            ("Kun facit", "solution")):
            ttk.Radiobutton(master, text=text, value=value, variable=self.mode).pack(anchor="w", pady=6)
        ttk.Label(master, text="Ved 'Opgave uden svar' gemmes svarene ikke i PDF-filen.",
                  style="Muted.TLabel").pack(anchor="w", pady=10)

    def apply(self):
        self.result = self.mode.get()


class Application(tk.Tk):
    def __init__(self, database: Database):
        super().__init__()
        self.db = database
        self.puzzle = Puzzle()
        self.puzzle_id: int | None = None
        self.dirty = False
        self.loading = False
        self.busy = False
        self.pending_entry: Entry | None = None
        self.highlight_index: int | None = None
        self.dictionary_rows: dict[str, Entry] = {}
        self.messages: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.disabled_states = []
        self.geometry("1340x860")
        self.minsize(1100, 760)
        self.title(f"Kryds & Tværs Generator {__version__}")
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._styles()
        self._variables()
        self._menus()
        self._layout()
        self.refresh_dictionary()
        self.refresh_saved()
        self._display_puzzle()
        self.after(80, self._poll_worker)
        self.bind("<Control-s>", lambda event: self.save_current())
        self.bind("<Control-n>", lambda event: self.new_puzzle())
        self.bind("<Control-o>", lambda event: self.open_json())
        self.bind("<Control-p>", lambda event: self.export_pdf())

    def _styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.configure(background="#F3F5F7")
        style.configure(".", font=("Segoe UI", 10), background="#F3F5F7", foreground="#213442")
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background="#176D78", foreground="white", padding=(12, 7))
        style.map("Accent.TButton", background=[("active", "#0E5862"), ("disabled", "#B0BFC4")])
        style.configure("TNotebook.Tab", padding=(20, 8))
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=29)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=7)
        style.map("Treeview", background=[("selected", "#D5E9EC")], foreground=[("selected", "#13313B")])
        style.configure("Muted.TLabel", foreground="#586D7C")
        style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TLabelframe", padding=10)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

    def _variables(self):
        self.title_var = tk.StringVar(value=self.puzzle.title)
        self.note_var = tk.StringVar()
        self.rows_var = tk.StringVar(value="17")
        self.cols_var = tk.StringVar(value="17")
        self.target_var = tk.StringVar(value="20")
        self.attempts_var = tk.StringVar(value="100")
        self.seconds_var = tk.StringVar(value="8")
        self.seed_var = tk.StringVar()
        self.generation_category = tk.StringVar(value=ALL_CATEGORIES)
        self.selected_only = tk.BooleanVar(value=False)
        self.show_answers = tk.BooleanVar(value=True)
        self.cell_mode = tk.StringVar(value="Vælg position")
        self.status_var = tk.StringVar(value="Klar. Ordbogen gemmes automatisk; gem krydsordet med Ctrl+S.")
        self.stats_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.pattern_var = tk.StringVar()
        self.filter_category = tk.StringVar(value=ALL_CATEGORIES)
        self.dict_count_var = tk.StringVar()
        self.manual_row = tk.StringVar(value="9")
        self.manual_col = tk.StringVar(value="9")
        self.manual_direction = tk.StringVar(value="Vandret")
        self.allow_adjacent_var = tk.BooleanVar(value=False)
        self.selected_word_var = tk.StringVar(value="Intet ord valgt")
        self.selected_clue_var = tk.StringVar(value="Vælg en ordforklaring fra orddatabasen.")
        for var in (self.title_var, self.note_var):
            var.trace_add("write", lambda *args: self._mark_dirty())
        for var in (self.manual_row, self.manual_col, self.manual_direction):
            var.trace_add("write", lambda *args: self.draw_grid() if hasattr(self, "canvas") else None)

    def _menus(self):
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        for label, command in (("Nyt tomt krydsord    Ctrl+N", self.new_puzzle),
                                ("Gem krydsord    Ctrl+S", self.save_current),
                                ("Gem som ny kopi", lambda: self.save_current(copy=True)),
                                ("Åbn krydsordsfil (JSON)    Ctrl+O", self.open_json),
                                ("Eksportér krydsordsfil (JSON)", self.export_json),
                                ("Eksportér PDF    Ctrl+P", self.export_pdf)):
            file_menu.add_command(label=label, command=command)
        file_menu.add_separator()
        file_menu.add_command(label="Afslut", command=self.close_app)
        menu.add_cascade(label="Filer", menu=file_menu)
        db_menu = tk.Menu(menu, tearoff=False)
        db_menu.add_command(label="Importér ordforklaringer fra CSV", command=self.import_csv)
        db_menu.add_command(label="Eksportér hele orddatabasen til CSV", command=self.export_csv)
        db_menu.add_command(label="Tag sikkerhedskopi af databasen", command=self.backup_database)
        menu.add_cascade(label="Database", menu=db_menu)
        menu.add_command(label="Hjælp / Om", command=self.about)
        self.config(menu=menu)

    def _layout(self):
        banner = tk.Frame(self, background="#203744", padx=22, pady=12)
        banner.pack(fill="x")
        tk.Label(banner, text="Kryds & Tværs", font=("Segoe UI", 24, "bold"),
                 background="#203744", foreground="white").pack(side="left")
        ttk.Button(banner, text="Om", command=self.about).pack(side="right", padx=(14, 0))
        tk.Label(banner, text="ORDBOG  /  KONSTRUKTION  /  PDF", font=("Segoe UI", 10),
                 background="#203744", foreground="#C7DADD").pack(side="right")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=15, pady=(12, 6))
        self.editor_tab, self.dictionary_tab, self.saved_tab = [ttk.Frame(self.tabs, padding=12) for _ in range(3)]
        self.tabs.add(self.editor_tab, text="Krydsord")
        self.tabs.add(self.dictionary_tab, text="Orddatabase")
        self.tabs.add(self.saved_tab, text="Gemte krydsord")
        self._editor()
        self._dictionary()
        self._saved()
        footer = ttk.Frame(self, padding=(18, 6, 18, 10))
        footer.pack(side="bottom", fill="x", before=self.tabs)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", wraplength=1250).pack(anchor="w")

    @staticmethod
    def _spin(parent, variable, minimum, maximum, width=5):
        return ttk.Spinbox(parent, textvariable=variable, from_=minimum, to=maximum, width=width)

    def _editor(self):
        meta = ttk.Frame(self.editor_tab)
        meta.pack(fill="x", pady=(0, 10))
        ttk.Label(meta, text="Titel").pack(side="left")
        ttk.Entry(meta, textvariable=self.title_var, width=32).pack(side="left", padx=(8, 20), fill="x", expand=True)
        ttk.Label(meta, text="Beskrivelse").pack(side="left")
        ttk.Entry(meta, textvariable=self.note_var, width=44).pack(side="left", padx=(8, 0), fill="x", expand=True)
        settings = ttk.Frame(self.editor_tab)
        settings.pack(fill="x", pady=(0, 8))
        for label, var, minimum, maximum, width in (
                ("Rækker", self.rows_var, 5, 35, 4), ("Kolonner", self.cols_var, 5, 35, 4),
                ("Ønskede ord", self.target_var, 2, 120, 4),
                ("Søgeforsøg", self.attempts_var, 1, 2000, 5),
                ("Maks. sek.", self.seconds_var, 1, 60, 4)):
            ttk.Label(settings, text=label).pack(side="left", padx=(0, 5))
            self._spin(settings, var, minimum, maximum, width).pack(side="left", padx=(0, 13))
        ttk.Label(settings, text="Seed").pack(side="left", padx=(0, 5))
        ttk.Entry(settings, textvariable=self.seed_var, width=11).pack(side="left")
        self.generate_button = ttk.Button(settings, text="Generér forslag", style="Accent.TButton", command=self.start_generation)
        self.generate_button.pack(side="right")
        filters = ttk.Frame(self.editor_tab)
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="Ordgrundlag").pack(side="left", padx=(0, 8))
        self.generation_combo = ttk.Combobox(filters, textvariable=self.generation_category,
                                             state="readonly", width=21)
        self.generation_combo.pack(side="left", padx=(0, 12))
        ttk.Checkbutton(filters, text="Kun markerede forklaringer i orddatabasen", variable=self.selected_only).pack(side="left")
        self.cancel_button = ttk.Button(filters, text="Stop søgning", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="right", padx=(8, 0))
        ttk.Button(filters, text="Nyt tomt gitter", command=self.new_puzzle).pack(side="right")
        self.progress_bar = ttk.Progressbar(self.editor_tab, maximum=100)
        self.progress_bar.pack(fill="x", pady=(0, 9))
        split = ttk.Panedwindow(self.editor_tab, orient="horizontal")
        split.pack(fill="both", expand=True)
        left = ttk.Frame(split)
        right = ttk.Frame(split, padding=(14, 0, 0, 0))
        split.add(left, weight=3)
        split.add(right, weight=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.after(150, lambda: split.sashpos(0, max(500, self.winfo_width() * 53 // 100)))
        preview_tools = ttk.Frame(left)
        preview_tools.pack(fill="x", pady=(0, 8))
        ttk.Label(preview_tools, text="Gitter", style="Heading.TLabel").pack(side="left")
        ttk.Label(preview_tools, text="Klik-funktion:").pack(side="left", padx=(14, 4))
        ttk.Combobox(preview_tools, textvariable=self.cell_mode, state="readonly", width=19,
                     values=("Vælg position", "Skillefelt til/fra", "Kodebogstav til/fra")).pack(side="left")
        ttk.Button(preview_tools, text="Ryd kodeord", command=self.clear_codeword).pack(side="left", padx=5)
        ttk.Checkbutton(preview_tools, text="Vis svar i gitteret", variable=self.show_answers,
                        command=self.draw_grid).pack(side="right")
        board = ttk.Frame(left)
        board.pack(fill="both", expand=True)
        board.rowconfigure(0, weight=1)
        board.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(board, background="white", highlightthickness=1, highlightbackground="#CDD5DB")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        xs, ys = ttk.Scrollbar(board, orient="horizontal", command=self.canvas.xview), ttk.Scrollbar(board, command=self.canvas.yview)
        xs.grid(row=1, column=0, sticky="ew")
        ys.grid(row=0, column=1, sticky="ns")
        self.canvas.config(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.canvas.bind("<Configure>", lambda event: self.draw_grid())
        self.canvas.bind("<Button-1>", self.grid_click)
        ttk.Label(left, textvariable=self.stats_var, style="Muted.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(left, text="Klik på et felt for at vælge startposition. Størrelsen øverst gælder et nyt gitter.",
                  style="Muted.TLabel", wraplength=650).pack(anchor="w")
        ttk.Label(right, text="Ord i krydsordet", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        frame = ttk.Frame(right)
        frame.grid(row=1, column=0, sticky="nsew")
        self.placed_tree = ttk.Treeview(frame, columns=("number", "direction", "word", "clue"), show="headings", height=7,
                                        selectmode="browse")
        for col, label, width in (("number", "Nr.", 36), ("direction", "Retning", 68),
                                   ("word", "Svar", 94), ("clue", "Ordforklaring", 235)):
            self.placed_tree.heading(col, text=label)
            self.placed_tree.column(col, width=width, minwidth=30, stretch=(col == "clue"))
        scroll = ttk.Scrollbar(frame, command=self.placed_tree.yview)
        self.placed_tree.configure(yscrollcommand=scroll.set)
        self.placed_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.placed_tree.bind("<<TreeviewSelect>>", self.placed_selected)
        self.placed_tree.bind("<Double-1>", lambda event: self.edit_puzzle_clue())
        edit_tools = ttk.Frame(right)
        edit_tools.grid(row=2, column=0, sticky="ew", pady=6)
        ttk.Button(edit_tools, text="Ret forklaring", command=self.edit_puzzle_clue).pack(side="left", padx=(0, 7))
        ttk.Button(edit_tools, text="Fjern ord", command=self.remove_word).pack(side="left")
        manual = ttk.LabelFrame(right, text="Indsæt ord manuelt")
        manual.grid(row=3, column=0, sticky="ew", pady=7)
        choice = ttk.Frame(manual)
        choice.pack(fill="x")
        ttk.Label(choice, textvariable=self.selected_word_var, style="Heading.TLabel").pack(side="left")
        ttk.Button(choice, text="Vælg fra ordbog", command=lambda: self.tabs.select(self.dictionary_tab)).pack(side="right")
        ttk.Label(manual, textvariable=self.selected_clue_var, wraplength=410,
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 7))
        position = ttk.Frame(manual)
        position.pack(fill="x", pady=3)
        for label, variable in (("Række", self.manual_row), ("Kolonne", self.manual_col)):
            ttk.Label(position, text=label).pack(side="left", padx=(0, 5))
            self._spin(position, variable, 1, 35, 4).pack(side="left", padx=(0, 10))
        ttk.Combobox(position, textvariable=self.manual_direction, values=list(DIRECTION_LABELS),
                     state="readonly", width=9).pack(side="left")
        ttk.Checkbutton(manual, text="Tillad naboord fra orddatabasen",
                        variable=self.allow_adjacent_var).pack(anchor="w", pady=(5, 0))
        actions = ttk.Frame(manual)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Foreslå placering", command=self.suggest_position).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Indsæt ord", command=self.insert_word, style="Accent.TButton").pack(side="left")
        save = ttk.Frame(right)
        save.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        ttk.Button(save, text="Gem", command=self.save_current).pack(side="left", padx=(0, 6))
        ttk.Button(save, text="Gem kopi", command=lambda: self.save_current(copy=True)).pack(side="left", padx=(0, 6))
        ttk.Button(save, text="Eksportér PDF", style="Accent.TButton", command=self.export_pdf).pack(side="right")

    def _dictionary(self):
        ttk.Label(self.dictionary_tab, text="Ord og ordforklaringer", style="Heading.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Label(self.dictionary_tab, text="Et ord kan have flere forklaringer. Markér flere rækker med Ctrl eller Shift.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        filters = ttk.Frame(self.dictionary_tab)
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="Søg").pack(side="left", padx=(0, 6))
        search = ttk.Entry(filters, textvariable=self.search_var, width=25)
        search.pack(side="left", padx=(0, 12))
        search.bind("<Return>", lambda event: self.refresh_dictionary())
        ttk.Label(filters, text="Mønster, fx ?A?").pack(side="left", padx=(0, 6))
        pattern = ttk.Entry(filters, textvariable=self.pattern_var, width=14)
        pattern.pack(side="left", padx=(0, 12))
        pattern.bind("<Return>", lambda event: self.refresh_dictionary())
        self.category_combo = ttk.Combobox(filters, textvariable=self.filter_category, state="readonly", width=20)
        self.category_combo.pack(side="left", padx=(0, 12))
        self.category_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_dictionary())
        ttk.Button(filters, text="Søg", command=self.refresh_dictionary).pack(side="left", padx=(0, 6))
        ttk.Button(filters, text="Nulstil", command=self.reset_search).pack(side="left")
        frame = ttk.Frame(self.dictionary_tab)
        frame.pack(fill="both", expand=True)
        self.dictionary_tree = ttk.Treeview(frame, columns=("word", "clue", "category", "length"),
                                            show="headings", selectmode="extended")
        for col, label, width in (("word", "Svarord", 170), ("clue", "Ordforklaring", 660),
                                   ("category", "Kategori", 145), ("length", "Bogstaver", 80)):
            self.dictionary_tree.heading(col, text=label)
            self.dictionary_tree.column(col, width=width, stretch=col == "clue", minwidth=70)
        scroll = ttk.Scrollbar(frame, command=self.dictionary_tree.yview)
        self.dictionary_tree.configure(yscrollcommand=scroll.set)
        self.dictionary_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.dictionary_tree.bind("<Double-1>", lambda event: self.edit_entry())
        tools = ttk.Frame(self.dictionary_tab)
        tools.pack(fill="x", pady=12)
        for label, command in (("Tilføj ord", self.add_entry), ("Ny forklaring til ord", self.add_clue),
                                ("Redigér", self.edit_entry), ("Slet", self.delete_entries)):
            ttk.Button(tools, text=label, command=command).pack(side="left", padx=(0, 7))
        ttk.Button(tools, text="Brug i krydsord", command=self.use_entry, style="Accent.TButton").pack(side="right")
        extra = ttk.Frame(self.dictionary_tab)
        extra.pack(fill="x")
        ttk.Label(extra, textvariable=self.dict_count_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(extra, text="Eksportér CSV", command=self.export_csv).pack(side="right", padx=(7, 0))
        ttk.Button(extra, text="Importér CSV", command=self.import_csv).pack(side="right")

    def _saved(self):
        ttk.Label(self.saved_tab, text="Gemte krydsord", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(self.saved_tab, text="Gemte krydsord beholder deres egne svar og forklaringer, også når orddatabasen ændres.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        frame = ttk.Frame(self.saved_tab)
        frame.pack(fill="both", expand=True)
        self.saved_tree = ttk.Treeview(frame, columns=("title", "updated"), show="headings", selectmode="browse")
        self.saved_tree.heading("title", text="Titel")
        self.saved_tree.heading("updated", text="Senest gemt (UTC)")
        self.saved_tree.column("title", width=700)
        self.saved_tree.column("updated", width=220, stretch=False)
        scroll = ttk.Scrollbar(frame, command=self.saved_tree.yview)
        self.saved_tree.configure(yscrollcommand=scroll.set)
        self.saved_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.saved_tree.bind("<Double-1>", lambda event: self.load_saved())
        tools = ttk.Frame(self.saved_tab)
        tools.pack(fill="x", pady=12)
        ttk.Button(tools, text="Åbn krydsord", style="Accent.TButton", command=self.load_saved).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Slet krydsord", command=self.delete_saved).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Opdatér liste", command=self.refresh_saved).pack(side="left")
        ttk.Button(tools, text="Sikkerhedskopi af database", command=self.backup_database).pack(side="right")

    def _mark_dirty(self):
        if not self.loading:
            self.dirty = True
            self.title(f"Kryds & Tværs Generator {__version__} *")

    def _ensure_idle(self):
        if self.busy:
            raise ValueError("Stop søgningen, før du ændrer eller gemmer krydsordet.")

    def _sync_metadata(self):
        self.puzzle.title = clean_text(self.title_var.get(), "Titlen", 120)
        self.puzzle.note = clean_text(self.note_var.get(), "Beskrivelsen", 500, required=False)

    def _confirm_replace(self) -> bool:
        if not self.dirty:
            return True
        choice = messagebox.askyesnocancel("Ikke-gemte ændringer", "Vil du gemme ændringerne i det aktuelle krydsord først?", parent=self)
        if choice is None:
            return False
        return bool(self.save_current()) if choice else True

    def _set_puzzle(self, puzzle: Puzzle, puzzle_id: int | None = None, dirty: bool = False):
        self.loading = True
        self.puzzle, self.puzzle_id = puzzle, puzzle_id
        self.title_var.set(puzzle.title)
        self.note_var.set(puzzle.note)
        self.rows_var.set(str(puzzle.rows))
        self.cols_var.set(str(puzzle.cols))
        self.pending_entry = None
        self.highlight_index = None
        self.cell_mode.set("Vælg position")
        self.selected_word_var.set("Intet ord valgt")
        self.selected_clue_var.set("Vælg en ordforklaring fra orddatabasen.")
        self.loading = False
        self.dirty = dirty
        self.title(f"Kryds & Tværs Generator {__version__}" + (" *" if dirty else ""))
        self._display_puzzle()
        self.tabs.select(self.editor_tab)

    def _display_puzzle(self):
        self.puzzle.renumber()
        self.placed_tree.delete(*self.placed_tree.get_children())
        for i, p in sorted(enumerate(self.puzzle.placements), key=lambda pair: (pair[1].number, pair[1].direction)):
            direction = "Vandret" if p.direction == "across" else "Lodret"
            self.placed_tree.insert("", "end", iid=str(i), values=(p.number, direction, p.entry.answer, p.entry.clue))
        board = Board(self.puzzle)
        self.stats_var.set(f"{len(self.puzzle.placements)} ord · {board.quality()[1]} krydsninger · "
                           f"{self.puzzle.rows} × {self.puzzle.cols} felter · "
                           f"{len(self.puzzle.blocked)} skillefelter · "
                           f"kodeord: {len(self.puzzle.secret_cells)} bogstaver")
        self.draw_grid()

    def draw_grid(self):
        if not hasattr(self, "canvas"):
            return
        canvas, puzzle = self.canvas, self.puzzle
        canvas.delete("all")
        cell = max(17, min(36, (canvas.winfo_width() - 50) / puzzle.cols,
                             (canvas.winfo_height() - 50) / puzzle.rows))
        self.cell_size, self.grid_offset = cell, 29
        width, height = puzzle.cols * cell + 48, puzzle.rows * cell + 48
        canvas.configure(scrollregion=(0, 0, width, height))
        grid = puzzle.grid()
        starts = {(p.row, p.col): p.number for p in puzzle.placements}
        highlighted = set()
        if self.highlight_index is not None and 0 <= self.highlight_index < len(puzzle.placements):
            highlighted = {(r, c) for r, c, _ in puzzle.placements[self.highlight_index].cells()}
        for r in range(puzzle.rows):
            canvas.create_text(15, 29 + (r + 0.5) * cell, text=str(r + 1), fill="#71808A", font=("Segoe UI", -10))
        for c in range(puzzle.cols):
            canvas.create_text(29 + (c + 0.5) * cell, 15, text=str(c + 1), fill="#71808A", font=("Segoe UI", -10))
        for r in range(puzzle.rows):
            for c in range(puzzle.cols):
                x, y = 29 + c * cell, 29 + r * cell
                fill = ("#ADB7C0" if (r, c) in puzzle.blocked else
                        "#FFF0B8" if (r, c) in puzzle.secret_cells else
                        "#D9EDF0" if (r, c) in highlighted else
                        "white" if grid[r][c] else "#E6EBEF")
                canvas.create_rectangle(x, y, x + cell, y + cell, fill=fill, outline="#AAB8C1", width=0.7)
                if (r, c) in puzzle.secret_cells:
                    number = puzzle.secret_cells.index((r, c)) + 1
                    canvas.create_rectangle(x + 1, y + 1, x + cell - 1, y + cell - 1,
                                            outline="#C78116", width=2)
                    canvas.create_text(x + cell - 2, y + cell - 2, text=str(number), anchor="se",
                                       font=("Segoe UI", -max(7, int(cell * .25)), "bold"), fill="#A76200")
                if (r, c) in starts:
                    canvas.create_text(x + 2, y + 1, text=str(starts[r, c]), anchor="nw",
                                       font=("Segoe UI", -max(7, int(cell * 0.27))), fill="#2E424D")
                if grid[r][c] and self.show_answers.get():
                    canvas.create_text(x + cell / 2, y + cell * 0.61, text=grid[r][c],
                                       font=("Segoe UI", -int(cell * 0.53), "bold"), fill="#233744")
        try:
            row, col = int(self.manual_row.get()) - 1, int(self.manual_col.get()) - 1
            if self.pending_entry:
                direction = DIRECTION_LABELS[self.manual_direction.get()]
                if self.allow_adjacent_var.get():
                    try:
                        place_word_with_dictionary(puzzle, self.pending_entry, row, col,
                                                   direction, self._dictionary_lookup())
                        valid = True
                    except ValueError:
                        valid = False
                else:
                    valid, _, _ = Board(puzzle).check(self.pending_entry, row, col, direction)
                color = "#167C66" if valid else "#BD4A4A"
                for r, c, letter in Placement(self.pending_entry, row, col, direction).cells():
                    if 0 <= r < puzzle.rows and 0 <= c < puzzle.cols:
                        x, y = 29 + c * cell, 29 + r * cell
                        canvas.create_rectangle(x + 1, y + 1, x + cell - 1, y + cell - 1, outline=color, width=2)
                        if not grid[r][c] and self.show_answers.get():
                            canvas.create_text(x + cell / 2, y + cell * 0.61, text=letter,
                                               font=("Segoe UI", -int(cell * 0.51)), fill=color)
            elif 0 <= row < puzzle.rows and 0 <= col < puzzle.cols:
                x, y = 29 + col * cell, 29 + row * cell
                canvas.create_rectangle(x + 1, y + 1, x + cell - 1, y + cell - 1, outline="#176D78", width=2)
        except (ValueError, KeyError, tk.TclError):
            pass

    def grid_click(self, event):
        if self.busy:
            return
        row = int((self.canvas.canvasy(event.y) - self.grid_offset) // self.cell_size)
        col = int((self.canvas.canvasx(event.x) - self.grid_offset) // self.cell_size)
        if 0 <= row < self.puzzle.rows and 0 <= col < self.puzzle.cols:
            if self.cell_mode.get() != "Vælg position":
                if self.busy:
                    self.status_var.set("Vent til genereringen er afsluttet.")
                    return
                pos = (row, col)
                if self.cell_mode.get() == "Skillefelt til/fra":
                    if pos in self.puzzle.blocked:
                        self.puzzle.blocked.remove(pos)
                    elif self.puzzle.grid()[row][col]:
                        self.status_var.set("Skillefelter kan kun sættes på tomme felter.")
                        return
                    else:
                        self.puzzle.blocked.append(pos)
                else:
                    if pos in self.puzzle.secret_cells:
                        self.puzzle.secret_cells.remove(pos)
                    elif not self.puzzle.grid()[row][col]:
                        self.status_var.set("Vælg et bogstavfelt til kodeordet.")
                        return
                    else:
                        self.puzzle.secret_cells.append(pos)
                self._mark_dirty()
                self._display_puzzle()
                self.status_var.set("Kodeord: " + self.puzzle.codeword() if self.puzzle.secret_cells else "Felt opdateret.")
                return
            self.manual_row.set(str(row + 1))
            self.manual_col.set(str(col + 1))

    @action
    def clear_codeword(self):
        self._ensure_idle()
        self.puzzle.secret_cells.clear()
        self._mark_dirty()
        self._display_puzzle()
        self.status_var.set("Kodeordet er ryddet.")

    def placed_selected(self, event=None):
        selection = self.placed_tree.selection()
        self.highlight_index = int(selection[0]) if selection else None
        self.draw_grid()

    @action
    def new_puzzle(self):
        self._ensure_idle()
        rows, cols = int(self.rows_var.get()), int(self.cols_var.get())
        title = clean_text(self.title_var.get(), "Titlen", 120)
        new = Puzzle(rows, cols, title, note=self.note_var.get())
        new.validate()
        if self._confirm_replace():
            self._set_puzzle(new, dirty=True)
            self.status_var.set("Tomt gitter oprettet. Vælg et ord i orddatabasen eller generér et forslag.")

    def _set_busy(self, busy: bool):
        self.busy = busy
        if busy:
            def visit(widget):
                for child in widget.winfo_children():
                    if child is self.cancel_button:
                        continue
                    if isinstance(child, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Spinbox, ttk.Checkbutton)):
                        self.disabled_states.append((child, child.state()))
                        child.state(["disabled"])
                    visit(child)
            visit(self.editor_tab)
            self.cancel_button.state(["!disabled"])
        else:
            for widget, original in self.disabled_states:
                widget.state(["!disabled", "!readonly"])
                widget.state(original)
            self.disabled_states.clear()
            self.cancel_button.state(["disabled"])

    @action
    def start_generation(self):
        self._ensure_idle()
        rows, cols = int(self.rows_var.get()), int(self.cols_var.get())
        title = clean_text(self.title_var.get(), "Titlen", 120)
        note = clean_text(self.note_var.get(), "Beskrivelsen", 500, required=False)
        Puzzle(rows, cols, title).validate()
        target, attempts = int(self.target_var.get()), int(self.attempts_var.get())
        seconds = float(self.seconds_var.get().replace(",", "."))
        seed = int(self.seed_var.get()) if self.seed_var.get().strip() else None
        if not 1 <= seconds <= 60:
            raise ValueError("Maksimal søgetid skal være mellem 1 og 60 sekunder.")
        category = self.generation_category.get()
        category = "" if category == ALL_CATEGORIES else category
        if self.selected_only.get():
            entries = [self.dictionary_rows[i] for i in self.dictionary_tree.selection()]
            entries = [entry for entry in entries if not category or entry.category == category]
        else:
            entries = self.db.entries(category=category)
        if len({entry.answer for entry in entries if len(entry.answer) <= max(rows, cols)}) < 2:
            raise ValueError("Vælg mindst to forskellige ord, som passer til gitterets størrelse og kategori.")
        if not 2 <= target <= 120 or not 1 <= attempts <= 2000:
            raise ValueError("Vælg 2-120 ord og 1-2000 søgeforsøg.")
        if not self._confirm_replace():
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.progress_bar.configure(value=0)
        self.status_var.set("Søger efter en sammenhængende placering af ordene ...")

        def worker():
            try:
                result = generate(entries, rows, cols, target, attempts, seed, seconds, title,
                                  self.cancel_event,
                                  lambda n, total, count: self.messages.put(("progress", n, total, count)))
                result.puzzle.note = note
                self.messages.put(("done", result))
            except Exception as exc:
                logging.exception("Generation failed")
                self.messages.put(("error", str(exc)))
        threading.Thread(target=worker, name="CrosswordGenerator", daemon=True).start()

    def _poll_worker(self):
        try:
            while True:
                message = self.messages.get_nowait()
                if message[0] == "progress":
                    _, count, total, words = message
                    self.progress_bar.configure(value=count / total * 100)
                    self.status_var.set(f"Søgeforsøg {count}/{total} · Bedste forslag: {words} ord")
                elif message[0] == "error":
                    self._set_busy(False)
                    messagebox.showerror("Generering mislykkedes", message[1], parent=self)
                elif message[0] == "done":
                    self._set_busy(False)
                    result = message[1]
                    count = len(result.puzzle.placements)
                    if count < 2:
                        self.status_var.set("Der blev ikke fundet et krydsord med mindst to krydsende ord.")
                        messagebox.showinfo("Ingen brugbar placering", "Prøv andre ord, flere søgeforsøg eller et større gitter. Det tidligere krydsord er bevaret.", parent=self)
                        continue
                    self._set_puzzle(result.puzzle, dirty=True)
                    self.status_var.set(f"Indsat {count} af ønskede {result.requested} ord fra {result.available} mulige. "
                                        f"{result.attempts} søgeforsøg · Seed: {result.puzzle.seed}" +
                                        (" · Søgningen blev stoppet." if result.cancelled else ""))
                    if count < result.requested or result.too_long:
                        details = (f"Der blev indsat {count} af ønskede {result.requested} ord.\n\n"
                                   "Algoritmen er en heuristik og kan ikke garantere, at alle ord passer. "
                                   "Prøv større gitter, flere søgeforsøg eller et andet ordgrundlag.")
                        if self.selected_only.get() and result.unplaced:
                            details += "\n\nIkke anvendte ord: " + ", ".join(result.unplaced[:100])
                        if result.too_long:
                            details += "\n\nFor lange til gitteret: " + ", ".join(result.too_long[:100])
                        messagebox.showinfo("Genereringsresultat", details, parent=self)
        except queue.Empty:
            pass
        self.after(80, self._poll_worker)

    @action
    def refresh_dictionary(self):
        category = self.filter_category.get()
        category = "" if category == ALL_CATEGORIES else category
        entries = self.db.entries(self.search_var.get(), category, self.pattern_var.get())
        self.dictionary_tree.delete(*self.dictionary_tree.get_children())
        self.dictionary_rows = {str(e.id): e for e in entries}
        for entry in entries:
            self.dictionary_tree.insert("", "end", iid=str(entry.id),
                                        values=(entry.answer, entry.clue, entry.category, len(entry.answer)))
        categories = [ALL_CATEGORIES] + self.db.categories()
        self.category_combo.configure(values=categories)
        self.generation_combo.configure(values=categories)
        for variable in (self.filter_category, self.generation_category):
            if variable.get() not in categories:
                variable.set(ALL_CATEGORIES)
        words, clues = self.db.counts()
        self.dict_count_var.set(f"{words} forskellige ord · {clues} ordforklaringer i alt · {len(entries)} viste rækker")

    def reset_search(self):
        self.search_var.set("")
        self.pattern_var.set("")
        self.filter_category.set(ALL_CATEGORIES)
        self.refresh_dictionary()

    def _one_entry(self) -> Entry:
        selected = self.dictionary_tree.selection()
        if len(selected) != 1:
            raise ValueError("Markér præcis én ordforklaring i orddatabasen.")
        return self.dictionary_rows[selected[0]]

    @action
    def add_entry(self):
        dialog = EntryDialog(self, "Tilføj ord og ordforklaring")
        if dialog.result:
            entry = dialog.result
            self.db.add_entry(entry.answer, entry.clue, entry.category)
            self.refresh_dictionary()
            self.status_var.set(f"{entry.answer}: Ordforklaringen er gemt i databasen.")

    @action
    def add_clue(self):
        current = self._one_entry()
        dialog = EntryDialog(self, "Ny forklaring til " + current.answer, current, new_clue=True)
        if dialog.result:
            entry = dialog.result
            self.db.add_entry(entry.answer, entry.clue, entry.category)
            self.refresh_dictionary()
            self.status_var.set(f"En ny forklaring til {entry.answer} er gemt.")

    @action
    def edit_entry(self):
        current = self._one_entry()
        dialog = EntryDialog(self, "Redigér ordforklaring", current)
        if dialog.result:
            entry = dialog.result
            self.db.update_entry(current.id, entry.answer, entry.clue, entry.category)
            self.refresh_dictionary()
            self.status_var.set("Orddatabasen er opdateret. Allerede oprettede krydsord er ikke ændret.")

    @action
    def delete_entries(self):
        selected = self.dictionary_tree.selection()
        if not selected:
            raise ValueError("Markér de ordforklaringer, du vil slette.")
        if messagebox.askyesno("Slet ordforklaringer", f"Slet {len(selected)} markerede ordforklaringer?\n\nGemte krydsord ændres ikke.", parent=self):
            for entry_id in selected:
                self.db.delete_entry(int(entry_id))
            self.refresh_dictionary()
            self.status_var.set("De markerede ordforklaringer er slettet.")

    @action
    def use_entry(self):
        self._ensure_idle()
        self.pending_entry = self._one_entry()
        self.highlight_index = None
        self.selected_word_var.set(self.pending_entry.answer[:21] + ("..." if len(self.pending_entry.answer) > 21 else ""))
        self.selected_clue_var.set(self.pending_entry.clue[:150] + ("..." if len(self.pending_entry.clue) > 150 else ""))
        self.tabs.select(self.editor_tab)
        self.status_var.set("Klik på et startfelt, vælg retning og indsæt ordet. Grøn ramme betyder gyldig placering.")
        self.draw_grid()

    def _dictionary_lookup(self):
        """An exact-word lookup; prefer the first available clue per answer."""
        known = {}
        for candidate in self.db.entries():
            known.setdefault(candidate.answer, candidate)
        return known.get

    @action
    def suggest_position(self):
        self._ensure_idle()
        if self.pending_entry is None:
            raise ValueError("Vælg først et ord med 'Brug i krydsord' i orddatabasen.")
        board = Board(self.puzzle)
        positions = board.candidates(self.pending_entry)
        if self.allow_adjacent_var.get():
            # Candidate enumeration for dense mode must include positions where
            # contact creates dictionary-backed words, not just strict crossings.
            lookup = self._dictionary_lookup()
            positions = []
            for direction, (dr, dc) in DIRECTIONS.items():
                for r in range(self.puzzle.rows - dr * (len(self.pending_entry.answer) - 1)):
                    for c in range(self.puzzle.cols - dc * (len(self.pending_entry.answer) - 1)):
                        try:
                            updated = place_word_with_dictionary(self.puzzle, self.pending_entry,
                                                                 r, c, direction, lookup)
                        except ValueError:
                            continue
                        positions.append((r, c, direction, len(updated.placements) - len(self.puzzle.placements)))
        if not positions:
            raise ValueError("Ingen gyldig placering fundet for dette ord i det nuværende gitter.")
        positions.sort(key=lambda p: (-p[3], p[0], p[1], p[2]))
        current = (self.manual_row.get(), self.manual_col.get(), self.manual_direction.get())
        display = [(str(r + 1), str(c + 1), "Vandret" if d == "across" else "Lodret") for r, c, d, _ in positions]
        index = (display.index(current) + 1) % len(display) if current in display else 0
        row, col, direction = display[index]
        self.manual_row.set(row)
        self.manual_col.set(col)
        self.manual_direction.set(direction)
        self.status_var.set(f"Placering {index + 1} af {len(display)}. Klik igen for næste forslag, eller vælg 'Indsæt ord'.")

    @action
    def insert_word(self):
        self._ensure_idle()
        if self.pending_entry is None:
            raise ValueError("Vælg først et ord i orddatabasen.")
        self._sync_metadata()
        row, col = int(self.manual_row.get()) - 1, int(self.manual_col.get()) - 1
        direction = DIRECTION_LABELS[self.manual_direction.get()]
        if self.allow_adjacent_var.get():
            self.puzzle = place_word_with_dictionary(
                self.puzzle, self.pending_entry, row, col, direction, self._dictionary_lookup())
        else:
            self.puzzle = place_word(self.puzzle, self.pending_entry, row, col, direction)
        self.status_var.set(f"{self.pending_entry.answer} er indsat i krydsordet.")
        self.pending_entry = None
        self.selected_word_var.set("Intet ord valgt")
        self.selected_clue_var.set("Vælg det næste ord fra orddatabasen.")
        self.highlight_index = None
        self._mark_dirty()
        self._display_puzzle()

    def _placed_index(self) -> int:
        selected = self.placed_tree.selection()
        if not selected:
            raise ValueError("Markér et ord i listen 'Ord i krydsordet'.")
        return int(selected[0])

    @action
    def remove_word(self):
        self._ensure_idle()
        index = self._placed_index()
        # Refuse to split the crossword into disconnected components.
        updated = self.puzzle.without(index)
        word = self.puzzle.placements[index].entry.answer
        self.puzzle = updated
        self.highlight_index = None
        self._mark_dirty()
        self._display_puzzle()
        self.status_var.set(f"{word} er fjernet fra krydsordet, men findes stadig i orddatabasen.")

    @action
    def edit_puzzle_clue(self):
        self._ensure_idle()
        index = self._placed_index()
        placement = self.puzzle.placements[index]
        text = simpledialog.askstring("Ret forklaring i dette krydsord",
                                      f"{placement.entry.answer}\nKun dette krydsord ændres; orddatabasen ændres ikke.",
                                      initialvalue=placement.entry.clue, parent=self)
        if text is not None:
            text = clean_text(text, "Ordforklaringen", 500)
            self.puzzle.placements[index] = replace(placement, entry=replace(placement.entry, clue=text))
            self._mark_dirty()
            self._display_puzzle()
            self.status_var.set("Ordforklaringen er ændret i dette krydsord. Gem for at beholde ændringen.")

    @action
    def save_current(self, copy: bool = False):
        self._ensure_idle()
        self._sync_metadata()
        self.puzzle_id = self.db.save_puzzle(self.puzzle, None if copy else self.puzzle_id)
        self.dirty = False
        self.title(f"Kryds & Tværs Generator {__version__}")
        self.refresh_saved()
        self.status_var.set(f"Krydsordet '{self.puzzle.title}' er gemt" + (" som en ny kopi." if copy else "."))
        return True

    @action
    def refresh_saved(self):
        self.saved_tree.delete(*self.saved_tree.get_children())
        for record in self.db.list_puzzles():
            stamp = record["updated_at"].replace("T", " ").replace("Z", "")
            self.saved_tree.insert("", "end", iid=str(record["id"]), values=(record["title"], stamp))

    @action
    def load_saved(self):
        self._ensure_idle()
        selected = self.saved_tree.selection()
        if not selected:
            raise ValueError("Vælg et gemt krydsord.")
        puzzle_id = int(selected[0])
        puzzle = self.db.load_puzzle(puzzle_id)
        if self._confirm_replace():
            self._set_puzzle(puzzle, puzzle_id)
            self.status_var.set(f"'{puzzle.title}' er åbnet." + (f" Oprindeligt seed: {puzzle.seed}." if puzzle.seed is not None else ""))

    @action
    def delete_saved(self):
        self._ensure_idle()
        selected = self.saved_tree.selection()
        if not selected:
            raise ValueError("Vælg et gemt krydsord.")
        puzzle_id = int(selected[0])
        if messagebox.askyesno("Slet gemt krydsord", "Slet det valgte krydsord fra databasen?", parent=self):
            self.db.delete_puzzle(puzzle_id)
            if puzzle_id == self.puzzle_id:
                self.puzzle_id = None
                self._mark_dirty()
            self.refresh_saved()

    @action
    def export_pdf(self):
        self._ensure_idle()
        self._sync_metadata()
        if not self.puzzle.placements:
            raise ValueError("Krydsordet er tomt. Indsæt eller generér ord først.")
        choice = ExportDialog(self, "Eksportér som PDF")
        if not choice.result:
            return
        filename = "krydsord_facit.pdf" if choice.result == "solution" else "krydsord.pdf"
        path = filedialog.asksaveasfilename(parent=self, title="Gem PDF", defaultextension=".pdf",
                                           initialfile=filename, filetypes=[("PDF-dokument", "*.pdf")])
        if path:
            from .pdf_export import export_pdf
            export_pdf(self.puzzle, path, include_solution=choice.result == "both",
                       solution_only=choice.result == "solution")
            self.status_var.set(f"PDF gemt: {path}")
            messagebox.showinfo("PDF eksporteret", f"PDF-filen er gemt:\n{path}", parent=self)

    @action
    def export_json(self):
        self._ensure_idle()
        self._sync_metadata()
        path = filedialog.asksaveasfilename(parent=self, title="Gem redigerbar krydsordsfil",
                                           initialfile="mit_krydsord.krydsord.json", defaultextension=".json",
                                           filetypes=[("Krydsordsfil", "*.json")])
        if path:
            payload = self.puzzle.to_json()
            Path(path).write_text(payload, encoding="utf-8")
            self.status_var.set(f"Redigerbar krydsordsfil gemt: {path}. Den indeholder også svarene.")

    @action
    def open_json(self):
        self._ensure_idle()
        path = filedialog.askopenfilename(parent=self, title="Åbn krydsordsfil", filetypes=[("Krydsordsfil", "*.json")])
        if not path:
            return
        if Path(path).stat().st_size > 2_000_000:
            raise ValueError("Krydsordsfilen må højst være 2 MB.")
        puzzle = Puzzle.from_json(Path(path).read_text(encoding="utf-8-sig"))
        if self._confirm_replace():
            self._set_puzzle(puzzle, dirty=True)
            self.status_var.set("Krydsordsfilen er åbnet. Vælg Gem for at tilføje den til databasen.")

    @action
    def import_csv(self):
        path = filedialog.askopenfilename(parent=self, title="Importér ordforklaringer",
                                          filetypes=[("CSV-fil", "*.csv"), ("Alle filer", "*")])
        if path:
            added, skipped = self.db.import_csv(path)
            self.refresh_dictionary()
            messagebox.showinfo("Import færdig", f"{added} nye forklaringer indlæst.\n{skipped} eksisterende forklaringer sprunget over.", parent=self)

    @action
    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self, title="Eksportér orddatabase", initialfile="orddatabase.csv",
                                           defaultextension=".csv", filetypes=[("CSV-fil", "*.csv")])
        if path:
            self.db.export_csv(path)
            self.status_var.set(f"Alle ord og forklaringer eksporteret: {path}")

    @action
    def backup_database(self):
        path = filedialog.asksaveasfilename(parent=self, title="Gem sikkerhedskopi",
                                           initialfile="krydsord_backup.sqlite3", defaultextension=".sqlite3",
                                           filetypes=[("SQLite-database", "*.sqlite3")])
        if path:
            self.db.backup(path)
            self.status_var.set(f"Backup gemt: {path}")
            messagebox.showinfo("Sikkerhedskopi oprettet", "Orddatabasen og alle gemte krydsord er kopieret.\nIkke-gemte ændringer er ikke med i sikkerhedskopien.", parent=self)

    def about(self):
        """Show usage instructions, version, copyright and GitHub project link."""
        repo_url = "https://github.com/ibhelmer/krydsord"
        dialog = tk.Toplevel(self)
        dialog.title(f"Om Kryds & Tværs Generator – {__version__}")
        dialog.geometry("800x700")
        dialog.minsize(630, 450)
        dialog.transient(self)

        heading = ttk.Frame(dialog, padding=(20, 15))
        heading.pack(fill="x")
        ttk.Label(heading, text="Kryds & Tværs Generator", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(heading, text=f"Version {__version__}  ·  Oktober 2026  ·  © 2026 Ib Helmer Nielsen",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 0))

        body = ttk.Frame(dialog, padding=(20, 0, 20, 0))
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical")
        content = tk.Text(body, wrap="word", font=("Segoe UI", 10), padx=13, pady=13,
                          background="white", relief="flat", yscrollcommand=scroll.set)
        scroll.configure(command=content.yview)
        scroll.pack(side="right", fill="y")
        content.pack(side="left", fill="both", expand=True)
        description = (
            "SÅDAN VIRKER PROGRAMMET\n"
            "Programmet opbygger nummererede krydsord med vandrette og lodrette "
            "ordforklaringer og eksporterer opgave og facit til PDF.\n\n"
            "1. ORDDATABASE\n"
            "Tilføj, redigér eller slet svarord og korte ordforklaringer under fanen "
            "Orddatabase. Et ord kan have flere forklaringer. Søg på kategori, "
            "fritekst eller mønster (fx ?A?). Importér og eksportér CSV med "
            "kolonnerne word;clue;category. Æ, Ø og Å understøttes.\n\n"
            "2. GENERÉR KRYDSORD\n"
            "Under Krydsord vælger du gitterstørrelse, målantallet af ord og "
            "eventuelt kategori eller markerede ordforklaringer. Tryk på "
            "Generér forslag. Generatoren søger efter kombinationer af ord, "
            "der krydser hinanden. Den kan ikke garantere, at alle ord placeres.\n\n"
            "3. REDIGÉR GITTERET\n"
            "Vælg et ord fra orddatabasen, startfelt og retning for manuel "
            "placering. Brug Foreslå placering til at finde gyldige felter. "
            "Du kan fjerne ord og rette deres forklaringer.\n\n"
            "4. SKILLEFELTER\n"
            "Vælg 'Skillefelt til/fra' i Klik-funktion-menuen og klik på et tomt "
            "felt for at indsætte eller fjerne et gråt skillefelt. Et skillefelt "
            "kan ikke dække en eksisterende bogstavplacering.\n\n"
            "5. HEMMELIGT KODEORD\n"
            "Vælg 'Kodebogstav til/fra', og klik på bogstaverne i den rækkefølge, "
            "som danner kodeordet. Numrene i de gule felter viser rækkefølgen. "
            "'Ryd kodeord' nulstiller markeringerne. Opgaven viser tomme "
            "kodeordsfelter; løsningen står i facit.\n\n"
            "6. GEM OG EKSPORTÉR\n"
            "Orddatabasen gemmes automatisk. Krydsord gemmes særskilt med "
            "Gem (Ctrl+S) og kan åbnes under Gemte krydsord. Eksportér PDF "
            "som opgave, opgave med facit eller kun facit. JSON kan også "
            "eksporteres og importeres.\n\n"
            "TEKNIK OG BEGRÆNSNINGER\n"
            "Python, Tkinter, SQLite og ReportLab. Generatoren bruger en "
            "randomiseret multi-start greedy-heuristik. Krydsordet er af den "
            "nummererede type med forklaringer uden for gitteret, ikke et "
            "skandinavisk pilekrydsord.\n\n"
            "COPYRIGHT\n"
            "© 2026 Ib Helmer Nielsen. Se repositoryets LICENSE og NOTICE "
            "for licens- og ophavsretsoplysninger.\n\n"
            f"DATABASE PÅ DENNE COMPUTER\n{self.db.path}\n"
        )
        content.insert("1.0", description)
        content.configure(state="disabled")
        footer = ttk.Frame(dialog, padding=(20, 12))
        footer.pack(fill="x")
        link = tk.Label(footer, text=repo_url, fg="#126C85", cursor="hand2",
                        font=("Segoe UI", 10, "underline"))
        link.pack(side="left")
        link.bind("<Button-1>", lambda _event: webbrowser.open(repo_url))
        ttk.Button(footer, text="Åbn GitHub", command=lambda: webbrowser.open(repo_url)).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Luk", command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_set()

    @action
    def close_app(self):
        if self.busy:
            if not messagebox.askyesno("Afslut programmet", "Stop søgningen og afslut?", parent=self):
                return
            self.cancel_event.set()
            self.after(100, self._close_when_idle)
            return
        if not self._confirm_replace():
            return
        self.db.close()
        self.destroy()

    def _close_when_idle(self):
        if self.busy:
            self.after(100, self._close_when_idle)
        else:
            self.close_app()

    def report_callback_exception(self, exc_type, value, traceback):
        logging.error("Unexpected UI error", exc_info=(exc_type, value, traceback))
        messagebox.showerror("Uventet fejl", f"Der opstod en uventet fejl:\n{value}\n\nDetaljer er skrevet i programmets logfil.", parent=self)