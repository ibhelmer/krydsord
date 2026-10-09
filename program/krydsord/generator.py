"""Randomized multi-start greedy crossword construction.

This is a heuristic, not an exhaustive/backtracking solver. Each attempt starts
with a different ordering and anchor word. A letter index proposes crossings;
strict checks reject collisions, parallel overlaps and unintended adjacent words.
Layouts are compared by word count, crossing count, then compactness. There is
no guarantee that every requested word can fit or that a global optimum is found.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import random
import secrets
import threading
import time
from typing import Callable, Iterable

from .models import DIRECTIONS, Entry, Placement, Puzzle

BITS = {"across": 1, "down": 2}


class Board:
    def __init__(self, puzzle: Puzzle):
        self.rows, self.cols = puzzle.rows, puzzle.cols
        self.blocked = set(map(tuple, puzzle.blocked))
        self.cells: dict[tuple[int, int], str] = {}
        self.masks: dict[tuple[int, int], int] = {}
        self.letters: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.placements: list[Placement] = []
        self.answers: set[str] = set()
        for p in puzzle.placements:
            self.add(p)

    def check(self, entry: Entry, row: int, col: int, direction: str) -> tuple[bool, str, int]:
        if direction not in DIRECTIONS:
            return False, "Vælg vandret eller lodret.", 0
        if entry.answer in self.answers:
            return False, "Ordet er allerede med i krydsordet.", 0
        dr, dc = DIRECTIONS[direction]
        length = len(entry.answer)
        end_r, end_c = row + dr * (length - 1), col + dc * (length - 1)
        if not (0 <= row <= end_r < self.rows and 0 <= col <= end_c < self.cols):
            return False, "Ordet ligger uden for gitteret.", 0
        if (row - dr, col - dc) in self.cells or (end_r + dr, end_c + dc) in self.cells:
            return False, "Der skal være et tomt felt før og efter ordet.", 0
        crosses = 0
        for index, letter in enumerate(entry.answer):
            r, c = row + dr * index, col + dc * index
            if (r, c) in self.blocked:
                return False, "Et skillefelt spærrer placeringen.", 0
            existing = self.cells.get((r, c))
            if existing:
                if existing != letter:
                    return False, "Bogstaverne passer ikke i en krydsning.", 0
                if self.masks[r, c] & BITS[direction]:
                    return False, "Ord må ikke overlappe i samme retning.", 0
                crosses += 1
            elif (r + dc, c + dr) in self.cells or (r - dc, c - dr) in self.cells:
                return False, "Ordet berører et andet ord uden en rigtig krydsning.", 0
        if self.cells and not crosses:
            return False, "Ordet skal krydse mindst ét eksisterende ord.", 0
        return True, "Placeringen er gyldig.", crosses

    def add(self, placement: Placement) -> None:
        """Internal fast path: callers must first check or validate the placement."""
        for row, col, letter in placement.cells():
            if (row, col) not in self.cells:
                self.letters[letter].append((row, col))
            self.cells[row, col] = letter
            self.masks[row, col] = self.masks.get((row, col), 0) | BITS[placement.direction]
        self.placements.append(placement)
        self.answers.add(placement.entry.answer)

    def candidates(self, entry: Entry) -> list[tuple[int, int, str, int]]:
        if not self.cells:
            candidates = []
            for direction in DIRECTIONS:
                row = self.rows // 2 if direction == "across" else (self.rows - len(entry.answer)) // 2
                col = (self.cols - len(entry.answer)) // 2 if direction == "across" else self.cols // 2
                valid, _, crosses = self.check(entry, row, col, direction)
                if valid:
                    candidates.append((row, col, direction, crosses))
            return candidates
        seen = set()
        result = []
        for index, letter in enumerate(entry.answer):
            for r, c in self.letters.get(letter, []):
                for direction, (dr, dc) in DIRECTIONS.items():
                    if self.masks[r, c] & BITS[direction]:
                        continue
                    row, col = r - dr * index, c - dc * index
                    candidate = (row, col, direction)
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    valid, _, crosses = self.check(entry, row, col, direction)
                    if valid:
                        result.append((row, col, direction, crosses))
        return result

    def area(self) -> int:
        if not self.cells:
            return 0
        rs, cs = zip(*self.cells)
        return (max(rs) - min(rs) + 1) * (max(cs) - min(cs) + 1)

    def quality(self) -> tuple[int, int, int]:
        return len(self.placements), sum(mask == 3 for mask in self.masks.values()), -self.area()


def place_word(puzzle: Puzzle, entry: Entry, row: int, col: int, direction: str) -> Puzzle:
    puzzle.validate()
    board = Board(puzzle)
    valid, reason, _ = board.check(entry, row, col, direction)
    if not valid:
        raise ValueError(reason)
    result = replace(puzzle, placements=puzzle.placements + [Placement(entry, row, col, direction)])
    result.validate()
    result.renumber()
    return result


@dataclass
class GenerationResult:
    puzzle: Puzzle
    requested: int
    available: int
    unplaced: list[str]
    too_long: list[str]
    attempts: int
    cancelled: bool
    elapsed: float


def generate(entries: Iterable[Entry], rows: int = 17, cols: int = 17,
             target: int = 20, attempts: int = 100, seed: int | None = None,
             max_seconds: float | None = 8.0, title: str = "Mit krydsord",
             cancel: threading.Event | None = None,
             progress: Callable[[int, int, int], None] | None = None) -> GenerationResult:
    template = Puzzle(rows, cols, title)
    template.validate()
    if type(target) is not int or not 2 <= target <= 120:
        raise ValueError("Det ønskede antal ord skal være mellem 2 og 120.")
    if type(attempts) is not int or not 1 <= attempts <= 2000:
        raise ValueError("Antal søgeforsøg skal være mellem 1 og 2000.")
    if max_seconds is not None and max_seconds <= 0:
        raise ValueError("Tidsgrænsen skal være positiv.")
    if seed is not None and type(seed) is not int:
        raise ValueError("Seed skal være et heltal.")
    seed = seed if seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    groups: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        # Public API also validates entries constructed directly by callers.
        checked = Entry.create(entry.answer, entry.clue, entry.category, entry.id, entry.word_id)
        groups[checked.answer].append(checked)
    too_long = sorted(answer for answer in groups if len(answer) > max(rows, cols))
    groups = {answer: values for answer, values in groups.items() if len(answer) <= max(rows, cols)}
    if len(groups) < 2:
        raise ValueError("Der skal være mindst to forskellige ord, som kan være i gitteret.")
    pool = [rng.choice(groups[answer]) for answer in sorted(groups)]
    best = Board(template)
    start = time.monotonic()
    completed = 0

    def stopped() -> bool:
        return bool(cancel and cancel.is_set()) or (max_seconds is not None and time.monotonic() - start >= max_seconds)

    for attempt in range(attempts):
        if stopped():
            break
        board = Board(template)
        # Bound the per-attempt work for large dictionaries; later restarts
        # sample different subsets. The whole pool remains eligible overall.
        active = rng.sample(pool, min(len(pool), 250))
        ranked = sorted(active, key=lambda e: len(e.answer) + rng.uniform(0, 12), reverse=True)
        anchor = ranked.pop(0)
        anchor_candidates = board.candidates(anchor)
        row, col, direction, _ = rng.choice(anchor_candidates)
        board.add(Placement(anchor, row, col, direction))
        pending = ranked
        while pending and len(board.placements) < target and not stopped():
            next_pending = []
            inserted = 0
            for entry in pending:
                if len(board.placements) >= target or stopped():
                    break
                candidates = board.candidates(entry)
                if not candidates:
                    next_pending.append(entry)
                    continue
                rs, cs = zip(*board.cells)
                min_r, max_r, min_c, max_c = min(rs), max(rs), min(cs), max(cs)
                old_area = (max_r - min_r + 1) * (max_c - min_c + 1)
                scored = []
                for r, c, direction, crossings in candidates:
                    dr, dc = DIRECTIONS[direction]
                    end_r, end_c = r + dr * (len(entry.answer) - 1), c + dc * (len(entry.answer) - 1)
                    area = (max(max_r, end_r) - min(min_r, r) + 1) * (max(max_c, end_c) - min(min_c, c) + 1)
                    score = crossings * 20 - (area - old_area) * 0.16 + rng.uniform(0, 5)
                    scored.append((score, r, c, direction))
                _, r, c, direction = max(scored)
                board.add(Placement(entry, r, c, direction))
                inserted += 1
            if not inserted:
                break
            pending = next_pending
        completed += 1
        if board.quality() > best.quality():
            best = board
        if progress:
            progress(attempt + 1, attempts, len(best.placements))
    if not best.placements:
        # Allows cancellation before the first attempt without inventing a result.
        puzzle = replace(template, seed=seed)
    else:
        puzzle = replace(template, placements=best.placements, seed=seed)
    puzzle.validate()
    puzzle.renumber()
    return GenerationResult(puzzle, target, len(pool),
                            sorted(answer for answer in groups if answer not in best.answers),
                            too_long, completed, bool(cancel and cancel.is_set()),
                            time.monotonic() - start)