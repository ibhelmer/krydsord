"""Exercise desktop workflows using a temporary database and mocked file dialogs.

Run from the project root: python -m tests.smoke_gui
A graphical display is required. No normal user database is opened or modified.
"""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from krydsord.database import Database
from krydsord.gui import Application
from krydsord.models import Entry, Puzzle

ROOT = Path(__file__).resolve().parents[1]


def require_idle(app: Application, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while app.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.015)
    assert not app.busy, "The generation worker did not complete."
    app.update()


def main() -> None:
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        db = Database(root / "test.sqlite3")
        db.seed_once(ROOT / "krydsord/sample_words.csv")
        errors = []
        stack.enter_context(patch("krydsord.gui.messagebox.showerror", side_effect=lambda *args, **kw: errors.append(args)))
        stack.enter_context(patch("krydsord.gui.messagebox.showinfo", return_value=None))
        stack.enter_context(patch("krydsord.gui.messagebox.askyesno", return_value=True))
        stack.enter_context(patch("krydsord.gui.messagebox.askyesnocancel", return_value=False))
        app = Application(db)
        try:
            for _ in range(5):
                app.update()
                time.sleep(0.05)
            assert len(app.dictionary_tree.get_children()) == 144
            assert app.placed_tree.winfo_height() > 70
            print("PASS: Desktop initialization and visible editor controls")

            new = Entry.create("TEKST", "En række skrevne tegn", "Sprog")
            with patch("krydsord.gui.EntryDialog", return_value=SimpleNamespace(result=new)):
                app.add_entry()
            added = next(e for e in db.entries() if e.answer == "TEKST")
            app.dictionary_tree.selection_set(str(added.id))
            second = Entry.create("TEKST", "Det skrevne indhold i en bog", "Sprog")
            with patch("krydsord.gui.EntryDialog", return_value=SimpleNamespace(result=second)):
                app.add_clue()
            assert db.counts() == (143, 146)
            app.pattern_var.set("?A?")
            app.refresh_dictionary()
            assert all(len(e.answer) == 3 and e.answer[1] == "A" for e in app.dictionary_rows.values())
            app.reset_search()
            print("PASS: Dictionary creation, multiple clues and pattern search")

            app._set_puzzle(Puzzle(9, 9), dirty=False)
            for word, row, col, direction in (("KAT", "4", "3", "Vandret"),
                                               ("TASKE", "3", "4", "Lodret")):
                item = next(e for e in app.dictionary_rows.values() if e.answer == word)
                app.dictionary_tree.selection_set(str(item.id))
                app.use_entry()
                app.manual_row.set(row)
                app.manual_col.set(col)
                app.manual_direction.set(direction)
                app.insert_word()
            app.puzzle.validate()
            assert len(app.puzzle.placements) == 2
            app.save_current()
            original_id = app.puzzle_id
            app.save_current(copy=True)
            assert original_id != app.puzzle_id
            app.placed_tree.selection_set("0")
            with patch("krydsord.gui.simpledialog.askstring", return_value="Ny lokal forklaring"):
                app.edit_puzzle_clue()
            app.save_current()
            assert db.load_puzzle(original_id).placements[0].entry.clue != "Ny lokal forklaring"
            print("PASS: Manual placement, validation, save, copy and clue snapshots")

            pdf = root / "test.pdf"
            with patch("krydsord.gui.ExportDialog", return_value=SimpleNamespace(result="puzzle")), \
                    patch("krydsord.gui.filedialog.asksaveasfilename", return_value=str(pdf)):
                app.export_pdf()
            assert pdf.read_bytes().startswith(b"%PDF-")
            json_path = root / "puzzle.json"
            with patch("krydsord.gui.filedialog.asksaveasfilename", return_value=str(json_path)):
                app.export_json()
            app._set_puzzle(Puzzle(), dirty=False)
            with patch("krydsord.gui.filedialog.askopenfilename", return_value=str(json_path)):
                app.open_json()
            assert len(app.puzzle.placements) == 2
            backup = root / "backup.sqlite3"
            with patch("krydsord.gui.filedialog.asksaveasfilename", return_value=str(backup)):
                app.backup_database()
            assert backup.is_file()
            print("PASS: PDF export, editable JSON roundtrip and database backup")

            app.dirty = False
            app.rows_var.set("17")
            app.cols_var.set("17")
            app.seed_var.set("42")
            app.attempts_var.set("25")
            app.start_generation()
            require_idle(app)
            assert len(app.puzzle.placements) == 20
            assert "disabled" not in app.generate_button.state()
            app.save_current()
            print("PASS: Background generation, event queue, control restoration and saving")

            for word in ("AAAA", "BBBB"):
                db.add_entry(word, "Test af afbrydelse")
            app.refresh_dictionary()
            selected = [str(e.id) for e in db.entries() if e.answer in {"AAAA", "BBBB"}]
            app.dictionary_tree.selection_set(selected)
            app.selected_only.set(True)
            before = app.puzzle.to_json()
            app.start_generation()
            app.cancel_event.set()
            require_idle(app)
            assert app.puzzle.to_json() == before
            assert not errors, errors
            print("PASS: Stop search, preserve prior puzzle when no usable result exists")
        finally:
            app.cancel_event.set()
            app.dirty = False
            if app.busy:
                require_idle(app)
            app.close_app()
        assert not errors, errors
    print("GUI smoke test passed.")


if __name__ == "__main__":
    main()