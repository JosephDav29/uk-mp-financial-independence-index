"""
Automatic updater for the UK MP Financial Independence Index.

This script deliberately runs the original scoring_engine.py
rather than recreating the scoring methodology.
"""

import os
import shutil
from pathlib import Path

# Prevent matplotlib from trying to open a window on GitHub Actions.
os.environ["MPLBACKEND"] = "Agg"

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"

DATA.mkdir(exist_ok=True)

import scoring_engine as engine


def main():

    print("=" * 70)
    print("AUTOMATIC UK MP FINANCIAL INDEPENDENCE INDEX UPDATE")
    print("=" * 70)

    # --------------------------------------------------------
    # Run the ORIGINAL working scoring program.
    # --------------------------------------------------------
    print("\nRunning the original scoring_engine.py...")
    engine.main()

    # --------------------------------------------------------
    # Find the final output produced by the original script.
    # --------------------------------------------------------
    original_final = DATA / (
        "UK_MP_FINANCIAL_INTEGRITY_FINAL_JULY_2024_ONWARDS.csv"
    )

    website_scores = DATA / "scores.csv"

    if not original_final.exists():
        raise RuntimeError(
            "The original scoring script did not create its final CSV."
        )

    # --------------------------------------------------------
    # Safety checks before replacing the website data.
    # --------------------------------------------------------
    import pandas as pd

    final = pd.read_csv(original_final)

    print("\nSafety check:")
    print("Final MP rows:", len(final))

    if len(final) < 400:
        raise RuntimeError(
            "SAFETY STOP: The new final CSV contains fewer than 400 MPs. "
            "The existing website scores.csv has NOT been replaced."
        )

    required_columns = [
        "Mnis Id",
        "Member",
        "Final Score",
        "Grade"
    ]

    missing = [
        column for column in required_columns
        if column not in final.columns
    ]

    if missing:
        raise RuntimeError(
            "SAFETY STOP: Required columns are missing: "
            + ", ".join(missing)
        )

    if final["Mnis Id"].duplicated().any():
        raise RuntimeError(
            "SAFETY STOP: Duplicate MP IDs were found. "
            "The existing website scores.csv has NOT been replaced."
        )

    if final["Member"].isna().any():
        raise RuntimeError(
            "SAFETY STOP: Missing MP names were found. "
            "The existing website scores.csv has NOT been replaced."
        )

    # --------------------------------------------------------
    # Only after all checks pass, update the website CSV.
    # --------------------------------------------------------
    shutil.copy2(original_final, website_scores)

    print("\nWebsite scores updated successfully:")
    print(website_scores)

    # --------------------------------------------------------
    # Get the latest register date for the website.
    # --------------------------------------------------------
    registers = engine.get_registers()

    latest = ""

    if registers:
        latest = max(
            register["publishedDate"]
            for register in registers
        )

    last_update = DATA / "last_update.txt"

    last_update.write_text(
        "Latest Parliament register: " + latest + "\n"
        + "Registers processed: " + str(len(registers)) + "\n"
        + "MPs scored: " + str(len(final)) + "\n",
        encoding="utf-8"
    )

    print("\n" + "=" * 70)
    print("AUTOMATIC UPDATE COMPLETE")
    print("=" * 70)
    print("Registers processed:", len(registers))
    print("Latest register:", latest)
    print("MPs scored:", len(final))
    print("Website scores:", website_scores)


if __name__ == "__main__":
    main()
