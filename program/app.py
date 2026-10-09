#!/usr/bin/env python3
"""Launch the desktop application, or generate a PDF without a display."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

from krydsord import __version__
from krydsord.database import Database

ROOT = Path(__file__).resolve().parent


def default_data_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "KrydsOgTvaersGenerator"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kryds & Tværs Generator: orddatabase, konstruktion og PDF.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--database", type=Path, help="Alternativ SQLite-database")
    parser.add_argument("--demo", action="store_true", help="Generér en PDF uden at starte brugerfladen")
    parser.add_argument("--output", type=Path, default=Path("krydsord.pdf"), help="PDF-fil ved --demo")
    parser.add_argument("--with-solution", action="store_true", help="Medtag facit efter opgaven ved --demo")
    parser.add_argument("--seed", type=int, default=42, help="Seed ved --demo (standard: 42)")
    parser.add_argument("--words", type=int, default=20, help="Ønsket antal ord ved --demo")
    parser.add_argument("--rows", type=int, default=17, help="Rækker ved --demo")
    parser.add_argument("--cols", type=int, default=17, help="Kolonner ved --demo")
    parser.add_argument("--category", default="", help="Kategori ved --demo, fx IT eller Natur")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        print("Programmet kræver Python 3.11 eller nyere.", file=sys.stderr)
        return 1
    database = None
    try:
        path = args.database or default_data_directory() / "krydsord.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=path.parent / "krydsord.log", level=logging.WARNING,
                            format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
        database = Database(path)
        database.seed_once(ROOT / "krydsord/sample_words.csv")
        if args.demo:
            from krydsord.generator import generate
            from krydsord.pdf_export import export_pdf
            result = generate(database.entries(category=args.category), rows=args.rows, cols=args.cols,
                              target=args.words, seed=args.seed, title="Mit krydsord", max_seconds=8)
            if len(result.puzzle.placements) < 2:
                raise ValueError("Der kunne ikke findes mindst to krydsende ord. Prøv et andet ordgrundlag.")
            export_pdf(result.puzzle, args.output, include_solution=args.with_solution)
            print(f"PDF: {args.output.resolve()}")
            print(f"Indsat {len(result.puzzle.placements)} af ønskede {args.words} ord. Seed: {result.puzzle.seed}.")
            if result.too_long:
                print("For lange ord: " + ", ".join(result.too_long))
        else:
            from krydsord.gui import Application
            Application(database).mainloop()
            database = None  # The UI owns and closes its connection.
        return 0
    except ImportError as exc:
        print(f"En nødvendig komponent mangler: {exc}\n"
              "Kør: python -m pip install -r requirements.txt\n"
              "Kontrollér også Tkinter: python -m tkinter", file=sys.stderr)
        return 1
    except Exception as exc:
        logging.exception("Application failed")
        print(f"Programmet kunne ikke fuldføre handlingen: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())