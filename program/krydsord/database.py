"""SQLite storage. All variable SQL values use bound parameters.

A word can have multiple clues. Saved puzzles contain immutable snapshots of
answers and clues, so future dictionary changes cannot silently alter puzzles.
Use this repository on its creating thread; the generator receives plain data.
"""
from __future__ import annotations

import csv
from pathlib import Path
import sqlite3

from .models import ALPHABET, Entry, Puzzle, clean_text


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("CASEFOLD", 1, lambda s: (s or "").casefold(),
                                        deterministic=True)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.connection.close()
            raise ValueError("Databasen kommer fra en nyere programversion.")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY,
                answer TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS clues (
                id INTEGER PRIMARY KEY,
                word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                UNIQUE(word_id, text)
            );
            CREATE INDEX IF NOT EXISTS idx_clues_word ON clues(word_id);
            CREATE INDEX IF NOT EXISTS idx_clues_category ON clues(category);
            CREATE TABLE IF NOT EXISTS puzzles (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            PRAGMA user_version = 1;
        """)

    def close(self) -> None:
        self.connection.close()

    def _word_id(self, answer: str) -> int:
        self.connection.execute("INSERT OR IGNORE INTO words(answer) VALUES (?)", (answer,))
        return self.connection.execute("SELECT id FROM words WHERE answer=?", (answer,)).fetchone()[0]

    def add_entry(self, answer: str, clue: str, category: str = "") -> int:
        entry = Entry.create(answer, clue, category)
        try:
            with self.connection:
                word_id = self._word_id(entry.answer)
                cur = self.connection.execute(
                    "INSERT INTO clues(word_id,text,category) VALUES(?,?,?)",
                    (word_id, entry.clue, entry.category))
                return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("Denne ordforklaring findes allerede til ordet.") from exc

    def update_entry(self, entry_id: int, answer: str, clue: str, category: str = "") -> None:
        entry = Entry.create(answer, clue, category)
        try:
            with self.connection:
                word_id = self._word_id(entry.answer)
                cur = self.connection.execute(
                    "UPDATE clues SET word_id=?,text=?,category=? WHERE id=?",
                    (word_id, entry.clue, entry.category, entry_id))
                if cur.rowcount != 1:
                    raise ValueError("Ordforklaringen findes ikke længere.")
                self.connection.execute("DELETE FROM words WHERE NOT EXISTS "
                                        "(SELECT 1 FROM clues WHERE clues.word_id=words.id)")
        except sqlite3.IntegrityError as exc:
            raise ValueError("Denne ordforklaring findes allerede til ordet.") from exc

    def delete_entry(self, entry_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM clues WHERE id=?", (entry_id,))
            self.connection.execute("DELETE FROM words WHERE NOT EXISTS "
                                    "(SELECT 1 FROM clues WHERE clues.word_id=words.id)")

    def entries(self, search: str = "", category: str = "", pattern: str = "") -> list[Entry]:
        sql = ("SELECT c.id, w.id AS word_id, w.answer, c.text AS clue, c.category "
               "FROM clues c JOIN words w ON w.id=c.word_id WHERE 1=1")
        params: list[str] = []
        if search.strip():
            # instr gives literal, Unicode case-insensitive substring search:
            # '%' and '_' are not silently interpreted as SQL wildcards.
            sql += " AND (instr(CASEFOLD(w.answer),?)>0 OR instr(CASEFOLD(c.text),?)>0)"
            params.extend([search.strip().casefold()] * 2)
        if category:
            sql += " AND c.category=?"
            params.append(category)
        if pattern.strip():
            pattern = "".join(pattern.upper().split()).replace(".", "?").replace("_", "?")
            if len(pattern) > 35 or not set(pattern) <= (ALPHABET | {"?"}):
                raise ValueError("Et mønster må kun indeholde bogstaver og ? for ukendte felter.")
            sql += " AND w.answer GLOB ?"
            params.append(pattern)
        sql += " ORDER BY w.answer, c.text, c.id"
        return [Entry(**dict(row)) for row in self.connection.execute(sql, params)]

    def categories(self) -> list[str]:
        return [r[0] for r in self.connection.execute(
            "SELECT DISTINCT category FROM clues WHERE category<>'' ORDER BY CASEFOLD(category)")]

    def counts(self) -> tuple[int, int]:
        return (self.connection.execute("SELECT COUNT(*) FROM words").fetchone()[0],
                self.connection.execute("SELECT COUNT(*) FROM clues").fetchone()[0])

    def import_csv(self, path: str | Path) -> tuple[int, int]:
        """Validate the entire CSV before changing anything; import atomically."""
        path = Path(path)
        if path.stat().st_size > 10_000_000:
            raise ValueError("CSV-filen må højst være 10 MB.")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            except csv.Error:
                # Header-based fallback for short, otherwise well-formed files.
                class Fallback(csv.excel):
                    delimiter = ";" if ";" in sample.partition("\n")[0] else ","
                dialect = Fallback
            reader = csv.DictReader(handle, dialect=dialect)
            aliases = {"ord": "word", "ordforklaring": "clue", "kategori": "category"}
            reader.fieldnames = [aliases.get(h.strip().lower(), h.strip().lower())
                                 for h in (reader.fieldnames or [])]
            if not {"word", "clue"} <= set(reader.fieldnames):
                raise ValueError("CSV skal have kolonnerne word,clue,category (eller ord,ordforklaring,kategori).")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("CSV har gentagne kolonnenavne.")
            incoming = []
            for row in reader:
                if None in row:
                    raise ValueError(f"CSV-linje {reader.line_num}: for mange kolonner.")
                try:
                    incoming.append(Entry.create(row.get("word"), row.get("clue"), row.get("category") or ""))
                except ValueError as exc:
                    raise ValueError(f"CSV-linje {reader.line_num}: {exc}") from exc
        inserted = skipped = 0
        with self.connection:
            for entry in incoming:
                word_id = self._word_id(entry.answer)
                cur = self.connection.execute(
                    "INSERT OR IGNORE INTO clues(word_id,text,category) VALUES(?,?,?)",
                    (word_id, entry.clue, entry.category))
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
        return inserted, skipped

    def export_csv(self, path: str | Path) -> None:
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["word", "clue", "category"])
            for entry in self.entries():
                writer.writerow([entry.answer, entry.clue, entry.category])

    def seed_once(self, path: str | Path) -> None:
        if not self.connection.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            # A user-supplied populated database is not mixed with demo entries.
            if self.counts() == (0, 0):
                self.import_csv(path)
            with self.connection:
                self.connection.execute("INSERT INTO settings(key,value) VALUES('seeded','1')")

    def save_puzzle(self, puzzle: Puzzle, puzzle_id: int | None = None) -> int:
        payload = puzzle.to_json()
        title = clean_text(puzzle.title, "Titlen", 120)
        with self.connection:
            if puzzle_id is None:
                return self.connection.execute(
                    "INSERT INTO puzzles(title,data_json) VALUES(?,?)", (title, payload)).lastrowid
            cur = self.connection.execute(
                "UPDATE puzzles SET title=?,data_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (title, payload, puzzle_id))
            if cur.rowcount != 1:
                raise ValueError("Krydsordet findes ikke længere. Gem som en ny kopi.")
            return puzzle_id

    def list_puzzles(self) -> list[dict]:
        return [dict(r) for r in self.connection.execute(
            "SELECT id,title,created_at,updated_at FROM puzzles ORDER BY updated_at DESC,id DESC")]

    def load_puzzle(self, puzzle_id: int) -> Puzzle:
        row = self.connection.execute("SELECT data_json FROM puzzles WHERE id=?", (puzzle_id,)).fetchone()
        if row is None:
            raise ValueError("Krydsordet findes ikke.")
        return Puzzle.from_json(row[0])

    def delete_puzzle(self, puzzle_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM puzzles WHERE id=?", (puzzle_id,))

    def backup(self, path: str | Path) -> None:
        path = Path(path).expanduser().resolve()
        if path == self.path:
            raise ValueError("Backup må ikke overskrive den aktive database.")
        destination = sqlite3.connect(path)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()