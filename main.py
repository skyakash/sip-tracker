"""
CLI for the AMFI SIP tracker.

Usage:
    python main.py seed                     # load bootstrap_seed.csv as a starting point
    python main.py discover                 # list available months + download links found on AMFI
    python main.py fetch-month "May 2026"    # download that month's AMFI Monthly Note PDF and parse it
    python main.py fetch-month "May 2026" --force   # re-download + show field diffs (revision check)
    python main.py show                      # print the current processed table
    python main.py chart                     # render a quick trend chart to data/processed/sip_trend.png
    python main.py report                    # render chart + key insights to data/processed/report.html

This is intentionally simple (no async, no retries/backoff yet) since it only
needs to run once a month. Harden it later if you turn this into something
that runs unattended.

NOTE: fetch-month uses the AMFI Monthly Note (narrative PDF), not the
"AMFI Monthly" Excel/PDF -- the latter is AMFI's Monthly Cumulative Report
(scheme/folio counts by category) and has no SIP-specific figures at all.
See src/parse_excel.py's docstring for how that was confirmed.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from src import discover, fetch, parse_pdf, db, report


def cmd_seed():
    db.seed_from_bootstrap()


def cmd_discover():
    print("=== AMFI Monthly (PDF + Excel) ===")
    for link in discover.discover_amfi_monthly():
        print(f"  {link.month_label}: pdf={link.pdf_url}  excel={link.excel_url}")

    print("\n=== AMFI Monthly Note (PDF only, narrative) ===")
    for link in discover.discover_amfi_monthly_note():
        print(f"  {link.month_label}: pdf={link.pdf_url}")


def cmd_fetch_month(month_label: str, force: bool = False):
    # The "AMFI Monthly" page (discover_amfi_monthly) turns out to be the
    # Monthly Cumulative Report -- scheme/folio counts by category, with no
    # SIP contribution/AUM/accounts data at all. The only place AMFI itself
    # publishes those figures is the AMFI Monthly Note (narrative PDF), so
    # that's the primary source here, not a fallback.
    note_links = discover.discover_amfi_monthly_note()
    match = next((l for l in note_links if l.month_label.lower() == month_label.lower()), None)
    if not match:
        print(f"Couldn't find '{month_label}' on the AMFI Monthly Note page. Run `discover` to see what's available.")
        return

    iso_month = fetch._normalize_month(match.month_label)

    path = fetch.download(match.pdf_url, match.month_label, "pdf", force=force)
    print(f"Downloaded Monthly Note PDF to {path}")
    record = parse_pdf.parse_pdf(path, iso_month)

    # Surface revisions: AMFI has restated legacy figures before, so on a
    # re-fetch show exactly which fields changed vs the stored row.
    existing = next((r for r in db.load_all() if r.get("month") == iso_month), None)
    if existing:
        changes = []
        for field, new_val in record.to_dict().items():
            if field in ("month", "retrieved_at", "notes", "source"):
                continue
            old_raw = existing.get(field, "")
            old_val = None if old_raw in ("", None) else float(old_raw)
            if old_val != new_val:
                changes.append(f"  {field}: {old_val} -> {new_val}")
        if changes:
            print(f"REVISED fields for {iso_month} vs stored row:")
            print("\n".join(changes))
        else:
            print(f"No field changes vs stored row for {iso_month}.")

    db.upsert(record)
    print(f"Saved record for {iso_month}:")
    print(record.to_dict())


def cmd_show():
    rows = db.load_all()
    if not rows:
        print("No data yet. Run `python main.py seed` to load bootstrap data, or `fetch-month` for live data.")
        return
    for row in rows:
        print(row)


def cmd_chart():
    if not db.load_all():
        print("No data to chart yet.")
        return
    path = report.draw_chart(report.load_full_df())
    print(f"Chart saved to {path}")


def cmd_report():
    if not db.load_all():
        print("No data to report on yet.")
        return
    path = report.build_report()
    print(f"Report saved to {path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    if cmd == "seed":
        cmd_seed()
    elif cmd == "discover":
        cmd_discover()
    elif cmd == "fetch-month":
        args = [a for a in sys.argv[2:] if a != "--force"]
        force = "--force" in sys.argv[2:]
        if not args:
            print('Usage: python main.py fetch-month "May 2026" [--force]')
            return
        cmd_fetch_month(args[0], force=force)
    elif cmd == "show":
        cmd_show()
    elif cmd == "chart":
        cmd_chart()
    elif cmd == "report":
        cmd_report()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
