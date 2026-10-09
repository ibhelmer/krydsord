"""Regression tests for divider cells and secret-word extraction."""
import unittest
from krydsord.models import Entry, Placement, Puzzle
from krydsord.generator import Board


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = Puzzle(9, 9, "Kodeord", placements=[
            Placement(Entry.create("KAT", "Husdyr"), 4, 3, "across")],
            blocked=[(0, 0)], secret_cells=[(4, 3), (4, 4), (4, 5)])

    def test_roundtrip(self):
        restored = Puzzle.from_json(self.puzzle.to_json())
        self.assertEqual(restored.codeword(), "KAT")
        self.assertEqual(restored.blocked, [(0, 0)])
        self.assertEqual(restored.secret_cells, self.puzzle.secret_cells)

    def test_blocking_letter_rejected(self):
        self.puzzle.blocked.append((4, 3))
        with self.assertRaises(ValueError):
            self.puzzle.validate()

    def test_empty_secret_rejected(self):
        self.puzzle.secret_cells.append((1, 1))
        with self.assertRaises(ValueError):
            self.puzzle.validate()

    def test_blocked_word_placement(self):
        self.puzzle.blocked = [(4, 4)]
        self.puzzle.secret_cells = []
        b = Board(Puzzle(9, 9, "Test", blocked=self.puzzle.blocked))
        valid, _, _ = b.check(Entry.create("KAT", "Husdyr"), 4, 3, "across")
        self.assertFalse(valid)

    def test_delete_word_removes_code_cells(self):
        empty = self.puzzle.without(0)
        self.assertEqual(empty.secret_cells, [])
        self.assertEqual(empty.blocked, [(0, 0)])


if __name__ == "__main__":
    unittest.main()