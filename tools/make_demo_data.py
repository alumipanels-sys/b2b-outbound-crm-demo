"""Generate English demo data covering all system features.

Usage:
    python tools/make_demo_data.py                 # rebuild full English demo data
    python tools/make_demo_data.py --clear --yes   # clear demo tables

This is a thin CLI wrapper around the English demo seed used by the
one-click reset in System Settings. No personal data is included.
"""

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def rebuild():
    from services.demo_seed import reset_demo_data
    db = _get_db()
    try:
        result = reset_demo_data(db)
        print(f"Done: {result.get('prospects', 0)} English demo customers created.")
    finally:
        db.close()


def clear_all():
    from services.demo_seed import _clear_demo_tables
    db = _get_db()
    try:
        _clear_demo_tables(db)
        print("Demo tables cleared.")
    finally:
        db.close()


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "--clear" in args:
        if "--yes" not in args:
            answer = input("This deletes all demo data. Type yes to continue: ").strip().lower()
            if answer != "yes":
                print("Cancelled.")
                return
        clear_all()
        return
    rebuild()


if __name__ == "__main__":
    main()
