"""Tests of dictionary-backed adjacent-word placement."""
import unittest
from krydsord.models import Entry, Puzzle
from krydsord.generator import place_word, place_word_with_dictionary


def e(word):
    return Entry.create(word, f"Forklaring til {word}")


class AdjacentWordTests(unittest.TestCase):
    def setUp(self):
        puzzle = place_word(Puzzle(17, 17), e("AUTHENTICATION"), 0, 0, "across")
        self.puzzle = place_word(puzzle, e("AUTHORIZATION"), 0, 0, "down")

    def test_screenshot_example(self):
        dictionary = {"UD": e("UD")}
        result = place_word_with_dictionary(self.puzzle, e("UD"), 0, 1, "down", dictionary.get)
        self.assertEqual(len(result.placements), 4)
        self.assertEqual([(p.entry.answer, p.direction) for p in result.placements[-2:]],
                         [("UD", "down"), ("UD", "across")])
        result.validate()
        self.assertEqual(Puzzle.from_json(result.to_json()).grid(), result.grid())

    def test_missing_clue_rejects_without_mutation(self):
        with self.assertRaisesRegex(ValueError, "mangler en ordforklaring"):
            place_word_with_dictionary(self.puzzle, e("UD"), 0, 1, "down", {}.get)
        self.assertEqual(len(self.puzzle.placements), 2)

    def test_strict_mode_still_rejects(self):
        with self.assertRaisesRegex(ValueError, "berører"):
            place_word(self.puzzle, e("UD"), 0, 1, "down")

    def test_conflicting_letter_rejects(self):
        with self.assertRaisesRegex(ValueError, "passer ikke"):
            place_word_with_dictionary(self.puzzle, e("AD"), 0, 1, "down", {}.get)


if __name__ == '__main__':
    unittest.main()