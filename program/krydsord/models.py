"""Domain objects, normalization and independent crossword validation.

Coordinates are zero-based internally. Answers use A-Z and ÆØÅ; punctuation
between words is removed, while Danish letters each occupy exactly one cell.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import unicodedata

ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZÆØÅ")
DIRECTIONS = {"across": (0, 1), "down": (1, 0)}
MAX_SIZE = 35


def normalize_answer(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Svaret skal være tekst.")
    value = unicodedata.normalize("NFC", value).upper()
    value = "".join(c for c in value if not c.isspace() and c not in "-'’‐‑–")
    if not 2 <= len(value) <= MAX_SIZE:
        raise ValueError(f"Svaret skal indeholde mellem 2 og {MAX_SIZE} bogstaver.")
    if not set(value) <= ALPHABET:
        raise ValueError("Brug kun A-Z og Æ, Ø, Å i svaret. Tal understøttes ikke.")
    return value


def clean_text(value: str, label: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} skal være tekst.")
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if required and not value:
        raise ValueError(f"{label} må ikke være tom.")
    if len(value) > maximum:
        raise ValueError(f"{label} må højst være {maximum} tegn.")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError(f"{label} indeholder et ugyldigt kontroltegn.")
    return value


@dataclass(frozen=True)
class Entry:
    id: int
    word_id: int
    answer: str
    clue: str
    category: str = ""

    @classmethod
    def create(cls, answer: str, clue: str, category: str = "",
               entry_id: int = 0, word_id: int = 0) -> Entry:
        return cls(entry_id, word_id, normalize_answer(answer),
                   clean_text(clue, "Ordforklaringen", 500),
                   clean_text(category, "Kategorien", 80, required=False))


@dataclass(frozen=True)
class Placement:
    entry: Entry
    row: int
    col: int
    direction: str
    number: int = 0

    def cells(self):
        dr, dc = DIRECTIONS[self.direction]
        for i, letter in enumerate(self.entry.answer):
            yield self.row + dr * i, self.col + dc * i, letter


@dataclass
class Puzzle:
    rows: int = 17
    cols: int = 17
    title: str = "Mit krydsord"
    placements: list[Placement] = field(default_factory=list)
    note: str = ""
    seed: int | None = None
    blocked: list[tuple[int, int]] = field(default_factory=list)
    secret_cells: list[tuple[int, int]] = field(default_factory=list)

    def renumber(self) -> None:
        starts = sorted({(p.row, p.col) for p in self.placements})
        numbers = {pos: i + 1 for i, pos in enumerate(starts)}
        self.placements = [replace(p, number=numbers[p.row, p.col])
                           for p in self.placements]

    def grid(self) -> list[list[str]]:
        result = [["" for _ in range(self.cols)] for _ in range(self.rows)]
        for placement in self.placements:
            for row, col, letter in placement.cells():
                result[row][col] = letter
        return result

    def validate(self, require_connected: bool = True) -> None:
        """Validate the final grid independently of the generation algorithm.

        Scanning all maximal letter runs catches accidental two-letter words,
        side contacts and end contacts as well as collisions and disconnected
        components. Placement order is irrelevant.
        """
        if any(type(n) is not int or not 5 <= n <= MAX_SIZE
               for n in (self.rows, self.cols)):
            raise ValueError(f"Gitteret skal være mellem 5 og {MAX_SIZE} felter på hver led.")
        clean_text(self.title, "Titlen", 120)
        clean_text(self.note, "Beskrivelsen", 500, required=False)
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("Seed skal være et heltal.")
        if len(self.placements) > 600:
            raise ValueError("Krydsordet indeholder for mange ord.")
        if len(set(map(tuple, self.blocked))) != len(self.blocked) or len(set(map(tuple, self.secret_cells))) != len(self.secret_cells):
            raise ValueError("Felter kan ikke vælges flere gange.")
        for pos in self.blocked + self.secret_cells:
            if (not isinstance(pos, (list, tuple)) or len(pos) != 2 or
                any(type(n) is not int for n in pos) or
                not (0 <= pos[0] < self.rows and 0 <= pos[1] < self.cols)):
                raise ValueError("Et markeret felt ligger uden for gitteret.")
        occupied: dict[tuple[int, int], str] = {}
        owners: dict[tuple[int, int], list[int]] = {}
        seen_placements: set[tuple[int, int, str, str]] = set()
        expected = set()
        for index, p in enumerate(self.placements):
            if type(p.row) is not int or type(p.col) is not int:
                raise ValueError("Række og kolonne skal være heltal.")
            if p.direction not in DIRECTIONS:
                raise ValueError("Ugyldig retning.")
            if normalize_answer(p.entry.answer) != p.entry.answer:
                raise ValueError("Svaret er ikke normaliseret.")
            clean_text(p.entry.clue, "Ordforklaringen", 500)
            clean_text(p.entry.category, "Kategorien", 80, required=False)
            placement_key = (p.row, p.col, p.direction, p.entry.answer)
            if placement_key in seen_placements:
                raise ValueError("Den samme placering er tilføjet to gange.")
            seen_placements.add(placement_key)
            expected.add((p.row, p.col, p.direction, p.entry.answer))
            for row, col, letter in p.cells():
                if not (0 <= row < self.rows and 0 <= col < self.cols):
                    raise ValueError(f"Ordet {p.entry.answer} ligger uden for gitteret.")
                pos = (row, col)
                if pos in occupied and occupied[pos] != letter:
                    raise ValueError("To ord har forskellige bogstaver i samme felt.")
                for other in owners.get(pos, []):
                    if self.placements[other].direction == p.direction:
                        raise ValueError("To ord må ikke overlappe i samme retning.")
                occupied[pos] = letter
                owners.setdefault(pos, []).append(index)
        if set(map(tuple, self.blocked)) & occupied.keys():
            raise ValueError("Et skillefelt må ikke indeholde et bogstav.")
        if not set(map(tuple, self.secret_cells)) <= occupied.keys():
            raise ValueError("Kodeordets felter skal indeholde bogstaver fra krydsordet.")
        actual = set()
        for (row, col), _ in occupied.items():
            for direction, (dr, dc) in DIRECTIONS.items():
                if (row - dr, col - dc) in occupied:
                    continue
                r, c = row, col
                letters = []
                while (r, c) in occupied:
                    letters.append(occupied[r, c])
                    r, c = r + dr, c + dc
                if len(letters) >= 2:
                    actual.add((row, col, direction, "".join(letters)))
        if actual != expected:
            raise ValueError("Ord rører hinanden og danner et utilsigtet ord. Sørg for luft mellem ordene.")
        if require_connected and self.placements:
            neighbours = {i: set() for i in range(len(self.placements))}
            for indexes in owners.values():
                for index in indexes:
                    neighbours[index].update(j for j in indexes if j != index)
            reached, pending = {0}, [0]
            while pending:
                for other in neighbours[pending.pop()] - reached:
                    reached.add(other)
                    pending.append(other)
            if len(reached) != len(self.placements):
                raise ValueError("Alle ord skal hænge sammen via krydsninger.")

    def codeword(self) -> str:
        grid = self.grid()
        return "".join(grid[r][c] for r, c in self.secret_cells)

    def without(self, index: int) -> Puzzle:
        if not 0 <= index < len(self.placements):
            raise ValueError("Vælg et ord i krydsordet.")
        remaining = [p for i, p in enumerate(self.placements) if i != index]
        used = {(r, c) for p in remaining for r, c, _ in p.cells()}
        result = replace(self, placements=remaining,
                         secret_cells=[pos for pos in self.secret_cells if tuple(pos) in used])
        result.validate()
        result.renumber()
        return result

    def to_json(self) -> str:
        self.validate()
        return json.dumps({
            "format": "krydsord", "version": 1,
            "rows": self.rows, "cols": self.cols, "title": self.title,
            "note": self.note, "seed": self.seed,
            "blocked": self.blocked, "secret_cells": self.secret_cells,
            "placements": [
                {"entry_id": p.entry.id, "word_id": p.entry.word_id,
                 "answer": p.entry.answer, "clue": p.entry.clue,
                 "category": p.entry.category, "row": p.row,
                 "col": p.col, "direction": p.direction}
                for p in self.placements
            ]}, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Puzzle:
        if len(text) > 2_000_000:
            raise ValueError("Krydsordsfilen er for stor (maksimum 2 MB tekst).")
        try:
            obj = json.loads(text)
            if obj["format"] != "krydsord" or obj["version"] != 1:
                raise ValueError("Ukendt filformat eller versionsnummer.")
            items = obj["placements"]
            if not isinstance(items, list) or len(items) > 600:
                raise ValueError("Ugyldig ordliste.")
            placements = []
            for item in items:
                for key in ("entry_id", "word_id"):
                    if type(item.get(key, 0)) is not int:
                        raise ValueError("Et ord-ID skal være et heltal.")
                entry = Entry.create(item["answer"], item["clue"], item.get("category", ""),
                                     item.get("entry_id", 0), item.get("word_id", 0))
                placements.append(Placement(entry, item["row"], item["col"], item["direction"]))
            result = cls(obj["rows"], obj["cols"], obj["title"], placements,
                         obj.get("note", ""), obj.get("seed"),
                         [tuple(x) for x in obj.get("blocked", [])],
                         [tuple(x) for x in obj.get("secret_cells", [])])
            result.validate()
            result.renumber()
            return result
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Filen er ikke en gyldig krydsordsfil.") from exc