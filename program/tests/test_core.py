"""Run with: python -m unittest discover -s tests -v"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest

from krydsord.database import Database
from krydsord.generator import Board, generate, place_word
from krydsord.models import Entry, Placement, Puzzle, normalize_answer
from krydsord.pdf_export import export_pdf

ROOT = Path(__file__).resolve().parents[1]


def entry(word, clue="Testforklaring"):
    return Entry.create(word, clue)


def small_puzzle():
    puzzle = Puzzle(9, 9)
    puzzle = place_word(puzzle, entry("KAT"), 3, 2, "across")
    return place_word(puzzle, entry("TASKE"), 2, 3, "down")


class NormalizationTests(unittest.TestCase):
    def test_danish_letters(self):
        self.assertEqual(normalize_answer(" æble ø å "), "ÆBLEØÅ")
        self.assertEqual(normalize_answer("a\u030a" * 2), "ÅÅ")

    def test_spaces_hyphens_apostrophes(self):
        self.assertEqual(normalize_answer("it-sikkerhed"), "ITSIKKERHED")
        self.assertEqual(normalize_answer("a'b"), "AB")

    def test_reject_bad_words(self):
        for word in ("", "A", "ESP32", "abc!", "a" * 36, "😀", None):
            with self.subTest(word=word), self.assertRaises(ValueError):
                normalize_answer(word)

    def test_clue_limits(self):
        for clue in ("", " ", "a" * 501, None, "abc\x00def"):
            with self.subTest(clue=clue), self.assertRaises(ValueError):
                Entry.create("KAT", clue)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "words.sqlite3")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_multiple_clues_one_word(self):
        self.db.add_entry("MUS", "Lille gnaver", "Dyr")
        self.db.add_entry("mus", "Pegeenhed", "IT")
        self.assertEqual(self.db.counts(), (1, 2))
        self.assertEqual(len(self.db.entries(category="IT")), 1)

    def test_duplicate_is_rejected(self):
        self.db.add_entry("KAT", "Miaver")
        with self.assertRaises(ValueError):
            self.db.add_entry("kat", "Miaver")
        self.assertEqual(self.db.counts(), (1, 1))

    def test_unicode_search_and_pattern(self):
        self.db.add_entry("VÆG", "Flade i et rum")
        self.db.add_entry("KAT", "Miaver")
        self.assertEqual(self.db.entries(search="væg")[0].answer, "VÆG")
        self.assertEqual(self.db.entries(pattern="?Æ?")[0].answer, "VÆG")
        self.assertEqual(self.db.entries(pattern=".a_")[0].answer, "KAT")
        self.assertEqual(self.db.entries(search="%"), [])
        with self.assertRaises(ValueError):
            self.db.entries(pattern="[A-Z]*")

    def test_move_clue_to_other_word(self):
        a = self.db.add_entry("MUS", "Pegeenhed", "IT")
        self.db.add_entry("MUS", "Gnaver", "Dyr")
        self.db.update_entry(a, "TASTATUR", "Har taster", "IT")
        self.assertEqual(self.db.counts(), (2, 2))
        self.db.delete_entry(a)
        self.assertEqual(self.db.counts(), (1, 1))

    def test_duplicate_update_rolls_back(self):
        self.db.add_entry("KAT", "Miaver")
        second = self.db.add_entry("MUS", "Gnaver")
        with self.assertRaises(ValueError):
            self.db.update_entry(second, "KAT", "Miaver")
        self.assertEqual(self.db.counts(), (2, 2))
        self.assertEqual(self.db.entries(search="MUS")[0].clue, "Gnaver")

    def test_missing_update_rolls_back_new_word(self):
        with self.assertRaises(ValueError):
            self.db.update_entry(999, "KAT", "Miaver")
        self.assertEqual(self.db.counts(), (0, 0))

    def test_csv_roundtrip_and_deduplication(self):
        self.db.add_entry("ÆBLE", "Rød frugt; på et træ", "Mad")
        self.db.add_entry("MUS", "Pegeenhed", "IT")
        path = self.root / "words.csv"
        self.db.export_csv(path)
        self.assertEqual(self.db.import_csv(path), (0, 2))
        other = Database(self.root / "copy.sqlite3")
        try:
            self.assertEqual(other.import_csv(path), (2, 0))
            self.assertEqual([(e.answer, e.clue, e.category) for e in other.entries()],
                             [(e.answer, e.clue, e.category) for e in self.db.entries()])
        finally:
            other.close()

    def test_csv_comma_and_danish_headers(self):
        path = self.root / "words.csv"
        path.write_text('ord,ordforklaring,kategori\nKAT,"Et dyr, der miaver",Dyr\n', encoding="utf-8")
        self.assertEqual(self.db.import_csv(path), (1, 0))

    def test_csv_atomic_validation(self):
        path = self.root / "bad.csv"
        path.write_text("word;clue;category\nKAT;Miaver;Dyr\n123;Fejl;Test\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.db.import_csv(path)
        self.assertEqual(self.db.counts(), (0, 0))

    def test_puzzle_snapshot_survives_dictionary_edits(self):
        clue_id = self.db.add_entry("KAT", "Oprindelig forklaring")
        e = self.db.entries()[0]
        puzzle = place_word(Puzzle(9, 9), e, 4, 3, "across")
        puzzle_id = self.db.save_puzzle(puzzle)
        self.db.update_entry(clue_id, "KAT", "Ny forklaring")
        self.db.delete_entry(clue_id)
        self.assertEqual(self.db.load_puzzle(puzzle_id).placements[0].entry.clue, "Oprindelig forklaring")

    def test_save_update_copy_delete(self):
        puzzle = small_puzzle()
        a = self.db.save_puzzle(puzzle)
        puzzle.title = "Ny titel"
        self.assertEqual(self.db.save_puzzle(puzzle, a), a)
        self.assertEqual(self.db.load_puzzle(a).title, "Ny titel")
        b = self.db.save_puzzle(puzzle)
        self.assertNotEqual(a, b)
        self.db.delete_puzzle(a)
        self.assertEqual(len(self.db.list_puzzles()), 1)
        with self.assertRaises(ValueError):
            self.db.load_puzzle(a)

    def test_seed_once_does_not_restore_deleted_words(self):
        self.db.seed_once(ROOT / "krydsord/sample_words.csv")
        self.assertEqual(self.db.counts(), (142, 144))
        for e in self.db.entries():
            self.db.delete_entry(e.id)
        self.db.seed_once(ROOT / "krydsord/sample_words.csv")
        self.assertEqual(self.db.counts(), (0, 0))

    def test_backup(self):
        self.db.add_entry("KAT", "Miaver")
        self.db.save_puzzle(small_puzzle())
        path = self.root / "backup.sqlite3"
        self.db.backup(path)
        backup = Database(path)
        try:
            self.assertEqual(backup.counts(), (1, 1))
            self.assertEqual(len(backup.list_puzzles()), 1)
        finally:
            backup.close()
        with self.assertRaises(ValueError):
            self.db.backup(self.db.path)


class PlacementTests(unittest.TestCase):
    def test_valid_crossing(self):
        puzzle = small_puzzle()
        puzzle.validate()
        self.assertEqual(puzzle.grid()[3][3], "A")
        self.assertEqual(Board(puzzle).quality()[1], 1)

    def test_ends_and_sides_cannot_touch(self):
        puzzle = place_word(Puzzle(9, 9), entry("KAT"), 3, 2, "across")
        for word, row, col, direction in (("HUS", 3, 5, "across"),
                                          ("AB", 4, 3, "across"),
                                          ("TASKE", 1, 2, "down")):
            with self.subTest(word=word, row=row), self.assertRaises(ValueError):
                place_word(puzzle, entry(word), row, col, direction)

    def test_conflict_overlap_duplicate_disconnected(self):
        puzzle = small_puzzle()
        cases = (("BB", 2, 2, "down"), ("AT", 3, 3, "across"),
                 ("KAT", 0, 0, "across"), ("HUS", 7, 6, "across"))
        for word, row, col, direction in cases:
            with self.subTest(word=word), self.assertRaises(ValueError):
                place_word(puzzle, entry(word), row, col, direction)

    def test_grid_bounds(self):
        for row, col in ((-1, 0), (0, -1), (9, 0), (0, 8)):
            with self.subTest(row=row, col=col), self.assertRaises(ValueError):
                place_word(Puzzle(9, 9), entry("KAT"), row, col, "across")

    def test_two_words_can_share_start_number(self):
        puzzle = place_word(Puzzle(9, 9), entry("KAT"), 3, 3, "across")
        puzzle = place_word(puzzle, entry("KO"), 3, 3, "down")
        self.assertEqual([p.number for p in puzzle.placements], [1, 1])

    def test_independent_validation_rejects_unclued_runs(self):
        puzzle = Puzzle(9, 9, placements=[Placement(entry("KAT"), 3, 2, "across"),
                                         Placement(entry("AB"), 4, 3, "across")])
        with self.assertRaises(ValueError):
            puzzle.validate()

    def test_independent_validation_rejects_disconnected(self):
        puzzle = Puzzle(9, 9, placements=[Placement(entry("KAT"), 1, 1, "across"),
                                         Placement(entry("HUS"), 5, 5, "across")])
        with self.assertRaises(ValueError):
            puzzle.validate()
        puzzle.validate(require_connected=False)

    def test_removal_keeps_validity_and_rejects_bridge_removal(self):
        puzzle = small_puzzle()
        self.assertEqual(len(puzzle.without(0).placements), 1)
        puzzle = place_word(puzzle, entry("KO"), 5, 3, "across")
        with self.assertRaises(ValueError):
            puzzle.without(1)
        self.assertEqual(len(puzzle.without(2).placements), 2)

    def test_json_roundtrip(self):
        puzzle = small_puzzle()
        puzzle.note = "Prøv med æ, ø og å."
        puzzle.seed = 42
        self.assertEqual(Puzzle.from_json(puzzle.to_json()), puzzle)

    def test_json_rejects_invalid_input(self):
        for content in ("{}", "not json", "[]", '"text"', "a" * 2_000_001):
            with self.subTest(content=content[:30]), self.assertRaises(ValueError):
                Puzzle.from_json(content)
        data = json.loads(small_puzzle().to_json())
        data["placements"][0]["row"] = True
        with self.assertRaises(ValueError):
            Puzzle.from_json(json.dumps(data))

    def test_json_placement_order_does_not_matter(self):
        puzzle = small_puzzle()
        data = json.loads(puzzle.to_json())
        data["placements"].reverse()
        restored = Puzzle.from_json(json.dumps(data))
        self.assertEqual(restored.grid(), puzzle.grid())


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        db = Database(Path(cls.temp.name) / "words.sqlite3")
        db.seed_once(ROOT / "krydsord/sample_words.csv")
        cls.entries = db.entries()
        db.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_many_seeds_and_sizes(self):
        for seed in range(15):
            for rows, cols, target in ((9, 9, 12), (13, 19, 20), (17, 17, 24), (25, 25, 45), (35, 35, 80)):
                with self.subTest(seed=seed, rows=rows, cols=cols):
                    result = generate(self.entries, rows, cols, target, attempts=5, seed=seed, max_seconds=None)
                    result.puzzle.validate()
                    self.assertGreaterEqual(len(result.puzzle.placements), 2)
                    self.assertLessEqual(len(result.puzzle.placements), target)
                    self.assertEqual(len({p.entry.answer for p in result.puzzle.placements}), len(result.puzzle.placements))

    def test_reproducible_with_same_seed_without_deadline(self):
        args = dict(attempts=20, seed=47, max_seconds=None)
        a = generate(self.entries, **args)
        b = generate(self.entries, **args)
        self.assertEqual(a.puzzle.to_json(), b.puzzle.to_json())

    def test_multiple_clues_never_duplicate_answer(self):
        result = generate([entry("KAT", "Forklaring A"), entry("KAT", "Forklaring B"), entry("TASKE")],
                          target=3, seed=1, attempts=5, max_seconds=None)
        self.assertEqual(len(result.puzzle.placements), 2)
        self.assertEqual(result.available, 2)

    def test_impossible_words_are_reported(self):
        result = generate([entry("AAAA"), entry("BBBB")], target=2, attempts=5, seed=2, max_seconds=None)
        self.assertEqual(len(result.puzzle.placements), 1)
        self.assertEqual(len(result.unplaced), 1)

    def test_long_words_excluded(self):
        result = generate([entry("KAT"), entry("TASKE"), entry("ABCDEFGHIJK")],
                          rows=5, cols=5, target=2, attempts=3, seed=1, max_seconds=None)
        self.assertEqual(result.too_long, ["ABCDEFGHIJK"])

    def test_cancel_before_start(self):
        event = threading.Event()
        event.set()
        result = generate(self.entries, cancel=event)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.attempts, 0)
        self.assertFalse(result.puzzle.placements)

    def test_parameter_validation(self):
        for kwargs in ({"rows": 4}, {"cols": 36}, {"target": 1}, {"attempts": 0},
                       {"max_seconds": 0}, {"seed": "x"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate(self.entries, **kwargs)


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_export_modes(self):
        puzzle = small_puzzle()
        puzzle.title = "Æble, Øresund og Århus"
        for name, kwargs in (("puzzle", {}), ("solution", {"solution_only": True}),
                              ("both", {"include_solution": True})):
            path = self.root / (name + ".pdf")
            export_pdf(puzzle, path, **kwargs)
            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            self.assertGreater(path.stat().st_size, 2000)

    def test_long_clues_and_xml_special_characters(self):
        puzzle = small_puzzle()
        puzzle.title = "Ord <og> tegn & danske bogstaver"
        puzzle.placements = [replace(p, entry=replace(p.entry, clue=("Æble <ø> & å " * 38).strip()))
                             for p in puzzle.placements]
        export_pdf(puzzle, self.root / "long.pdf", include_solution=True)

    def test_no_font_files_needed_for_danish(self):
        from unittest.mock import patch
        with patch("krydsord.pdf_export._fonts", return_value=("Helvetica", "Helvetica-Bold")):
            puzzle = place_word(Puzzle(9, 9, "Æ, Ø og Å"), entry("BLÅBÆR", "Små bær"), 3, 1, "across")
            export_pdf(puzzle, self.root / "fallback.pdf", include_solution=True)

    def test_blank_puzzle_cannot_be_exported(self):
        with self.assertRaises(ValueError):
            export_pdf(Puzzle(), self.root / "empty.pdf")


if __name__ == "__main__":
    unittest.main()