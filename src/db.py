"""
Simple CSV-backed store for MonthlyRecords. No real database needed for a
few dozen rows a year — CSV is easy to eyeball, diff in git, and load into
pandas/Excel directly.
"""

import pathlib
import csv

from .models import MonthlyRecord

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CSV_PATH = PROCESSED_DIR / "sip_monthly.csv"


def load_all() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def upsert(record: MonthlyRecord) -> None:
    """Insert a new month, or overwrite an existing row for the same month."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_all()
    rows = [r for r in rows if r.get("month") != record.month]
    rows.append({k: ("" if v is None else v) for k, v in record.to_dict().items()})
    rows.sort(key=lambda r: r["month"])

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MonthlyRecord.field_names())
        writer.writeheader()
        writer.writerows(rows)


def seed_from_bootstrap() -> None:
    """Copy the manually-sourced bootstrap seed into the main CSV if it's empty."""
    seed_path = PROCESSED_DIR / "bootstrap_seed.csv"
    if CSV_PATH.exists():
        print(f"{CSV_PATH} already exists — not overwriting. Delete it first if you want to reseed.")
        return
    if not seed_path.exists():
        print(f"No bootstrap seed found at {seed_path}")
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_text(seed_path.read_text())
    print(f"Seeded {CSV_PATH} from bootstrap data.")
