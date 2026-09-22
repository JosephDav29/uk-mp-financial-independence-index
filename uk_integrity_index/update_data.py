"""
Automatic updater for the UK MP Financial Independence Index.

This script uses the original scoring_engine.py for all scoring.
The only special handling here is MP population retrieval, because
the Parliament current-member API is not returning the full population
needed for the historical 2024-onwards dataset.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

import requests
import pandas as pd

os.environ["MPLBACKEND"] = "Agg"

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"

DATA.mkdir(exist_ok=True)

import scoring_engine as engine


MEMBERS_API = "https://members-api.parliament.uk/api/Members"


def get_api_page(url, params):
    """Get one page from the Parliament Members API."""

    response = requests.get(
        url,
        params=params,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


def get_current_mps():
    """
    Get current Commons MPs.

    We deliberately do not use the old date-range query here because
    that query is currently returning only around 300 records.
    """

    print("\nGetting current Commons MPs...")

    members = []

    skip = 0
    take = 20

    while True:

        data = get_api_page(
            MEMBERS_API + "/Search",
            {
                "House": 1,
                "IsCurrentMember": True,
                "skip": skip,
                "take": take
            }
        )

        items = data.get("items", [])

        if not items:
            break

        members.extend(items)

        print(
            "Downloaded",
            len(members),
            "current MPs"
        )

        if len(items) < take:
            break

        skip += take

    return members


def get_historical_mps(date_string):
    """
    Get Commons MPs who were members on a specific historical date.

    This uses Parliament's historical-member endpoint rather than the
    current-member endpoint.
    """

    print(
        "\nGetting historical Commons MPs for",
        date_string
    )

    members = []

    skip = 0
    take = 20

    while True:

        data = get_api_page(
            MEMBERS_API + "/SearchHistorical",
            {
                "dateToSearchFor": date_string,
                "skip": skip,
                "take": take
            }
        )

        items = data.get("items", [])

        if not items:
            break

        members.extend(items)

        print(
            "Downloaded",
            len(members),
            "historical MPs"
        )

        if len(items) < take:
            break

        skip += take

    return members


def extract_member_details(record):
    """
    Convert a Parliament API member record into the format expected
    by the original scoring engine.
    """

    if "value" in record:
        record = record["value"]

    member_id = (
        record.get("id")
        or record.get("memberId")
        or record.get("MnisId")
        or record.get("mnisId")
    )

    name = (
        record.get("nameDisplayAs")
        or record.get("name")
        or record.get("Member")
        or ""
    )

    party = (
        record.get("party")
        or record.get("Party")
        or ""
    )

    return {
        "Mnis Id": member_id,
        "Member": name,
        "Party": party
    }


def build_mp_population(register_data):
    """
    Build the MP population needed by the original scoring engine.

    Population is constructed from:

    1. MPs present at the beginning of the current Parliament.
    2. Current Commons MPs.
    3. MPs appearing in the downloaded registers.

    This catches MPs who subsequently left Parliament as well as
    MPs who entered Parliament later.
    """

    print("\n" + "=" * 70)
    print("BUILDING MP POPULATION")
    print("=" * 70)

    population = {}

    # --------------------------------------------------------------
    # 1. Historical MPs at the start of the current Parliament
    # --------------------------------------------------------------

   historical_records = get_historical_mps(
    "2024-07-10"
)
    for record in historical_records:

        member = extract_member_details(record)

        member_id = member["Mnis Id"]

        if member_id is not None:
            population[str(member_id)] = member

    print(
        "\nHistorical MPs added:",
        len(population)
    )

    # --------------------------------------------------------------
    # 2. Current MPs
    # --------------------------------------------------------------

    current_records = get_current_mps()

    for record in current_records:

        member = extract_member_details(record)

        member_id = member["Mnis Id"]

        if member_id is not None:
            population[str(member_id)] = member

    print(
        "After adding current MPs:",
        len(population)
    )

    # --------------------------------------------------------------
    # 3. MPs appearing in the actual registers
    # --------------------------------------------------------------

    if isinstance(register_data, pd.DataFrame):

        possible_id_columns = [
            "Mnis Id",
            "MnisId",
            "Member Id",
            "MemberId"
        ]

        id_column = None

        for column in possible_id_columns:

            if column in register_data.columns:
                id_column = column
                break

        if id_column is not None:

            print(
                "\nAdding MPs found directly in register data..."
            )

            name_column = None

            for column in [
                "Member",
                "Member Name",
                "Name"
            ]:

                if column in register_data.columns:
                    name_column = column
                    break

            party_column = None

            for column in [
                "Party"
            ]:

                if column in register_data.columns:
                    party_column = column
                    break

            for _, row in register_data.iterrows():

                raw_id = row[id_column]

                if pd.isna(raw_id):
                    continue

                member_id = str(raw_id)

                if member_id not in population:

                    name = ""

                    if name_column is not None:
                        if not pd.isna(row[name_column]):
                            name = str(row[name_column])

                    party = ""

                    if party_column is not None:
                        if not pd.isna(row[party_column]):
                            party = str(row[party_column])

                    population[member_id] = {
                        "Mnis Id": raw_id,
                        "Member": name,
                        "Party": party
                    }

    print(
        "\nFinal MP population:",
        len(population)
    )

    return list(population.values())


def main():

    print("=" * 70)
    print("AUTOMATIC UK MP FINANCIAL INDEPENDENCE INDEX UPDATE")
    print("=" * 70)

    # --------------------------------------------------------------
    # Download registers first
    # --------------------------------------------------------------

    print("\nGetting Parliament registers...")

    registers = engine.get_registers()

    if not registers:
        raise RuntimeError(
            "SAFETY STOP: No Parliament registers were found."
        )

    print(
        "Registers found:",
        len(registers)
    )

    # --------------------------------------------------------------
    # Download register data
    # --------------------------------------------------------------

    print("\nDownloading register data...")

    all_data = engine.download_all_register_data(
        registers
    )

    if all_data is None:
        raise RuntimeError(
            "SAFETY STOP: Register data download returned nothing."
        )

    # --------------------------------------------------------------
    # Build corrected MP population
    # --------------------------------------------------------------

    members = build_mp_population(
        all_data
    )

    # --------------------------------------------------------------
    # Population safety check
    # --------------------------------------------------------------

    print("\n" + "=" * 70)
    print("POPULATION SAFETY CHECK")
    print("=" * 70)

    print(
        "MPs found:",
        len(members)
    )

    if len(members) < 400:

        raise RuntimeError(
            "SAFETY STOP: MP population is still below 400. "
            "No website data will be replaced."
        )

    # Check IDs

    ids = [
        str(member["Mnis Id"])
        for member in members
        if member.get("Mnis Id") is not None
    ]

    if len(ids) != len(set(ids)):

        raise RuntimeError(
            "SAFETY STOP: Duplicate MP IDs were found."
        )

    print(
        "Population check passed."
    )

    # --------------------------------------------------------------
    # Run the ORIGINAL scoring functions
    # --------------------------------------------------------------

    print("\n" + "=" * 70)
    print("RUNNING ORIGINAL SCORING ENGINE")
    print("=" * 70)

    scored = engine.score_all_interests(
        all_data
    )

    final = engine.build_final_scores(
        scored,
        members
    )

    # --------------------------------------------------------------
    # Final safety checks
    # --------------------------------------------------------------

    print("\n" + "=" * 70)
    print("FINAL DATA SAFETY CHECK")
    print("=" * 70)

    print(
        "Final MP rows:",
        len(final)
    )

    if len(final) < 400:

        raise RuntimeError(
            "SAFETY STOP: Final score file contains fewer than "
            "400 MPs. Existing website data has NOT been replaced."
        )

    required_columns = [
        "Mnis Id",
        "Member",
        "Final Score",
        "Grade"
    ]

    missing = [
        column
        for column in required_columns
        if column not in final.columns
    ]

    if missing:

        raise RuntimeError(
            "SAFETY STOP: Required columns are missing: "
            + ", ".join(missing)
        )

    if final["Mnis Id"].duplicated().any():

        raise RuntimeError(
            "SAFETY STOP: Duplicate MP IDs were found in final data."
        )

    if final["Member"].isna().any():

        raise RuntimeError(
            "SAFETY STOP: Missing MP names were found in final data."
        )

    # --------------------------------------------------------------
    # Save the original engine's normal output
    # --------------------------------------------------------------

    engine.save_results(
        final,
        scored,
        all_data,
        members
    )

    original_final = DATA / (
        "UK_MP_FINANCIAL_INTEGRITY_FINAL_JULY_2024_ONWARDS.csv"
    )

    website_scores = DATA / "scores.csv"

    if not original_final.exists():

        raise RuntimeError(
            "SAFETY STOP: Original final CSV was not created."
        )

    # --------------------------------------------------------------
    # Only NOW replace website scores.csv
    # --------------------------------------------------------------

    shutil.copy2(
        original_final,
        website_scores
    )

    print(
        "\nWebsite scores updated successfully:"
    )

    print(
        website_scores
    )

    # --------------------------------------------------------------
    # Update interests file
    # --------------------------------------------------------------

    interests_file = DATA / "interests.csv.gz"

    all_data.to_csv(
        interests_file,
        index=False,
        compression="gzip"
    )

    # --------------------------------------------------------------
    # Update timestamp
    # --------------------------------------------------------------

    latest = max(
        register["publishedDate"]
        for register in registers
    )

    last_update = DATA / "last_update.txt"

    last_update.write_text(
        "Latest Parliament register: "
        + latest
        + "\n"
        + "Registers processed: "
        + str(len(registers))
        + "\n"
        + "MPs scored: "
        + str(len(final))
        + "\n"
        + "Updated automatically: "
        + datetime.now(timezone.utc).isoformat()
        + "\n",
        encoding="utf-8"
    )

    print("\n" + "=" * 70)
    print("AUTOMATIC UPDATE COMPLETE")
    print("=" * 70)

    print(
        "Registers processed:",
        len(registers)
    )

    print(
        "Latest register:",
        latest
    )

    print(
        "MPs scored:",
        len(final)
    )

    print(
        "Website scores:",
        website_scores
    )


if __name__ == "__main__":
    main()
