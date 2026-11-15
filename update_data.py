"""
Automatic updater for the UK MP Financial Independence Index.

The scoring methodology remains in scoring_engine.py. This file:
1. Downloads Commons register data from July 2024 onwards.
2. Builds the MP population from historical MPs, current MPs and register records.
3. Runs the existing scoring functions.
4. Checks the results before replacing the website data files.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests

os.environ["MPLBACKEND"] = "Agg"

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(parents=True, exist_ok=True)

import scoring_engine as engine


START_DATE = "2024-07-01"
MEMBERS_API = "https://members-api.parliament.uk/api/Members"
MINIMUM_MP_COUNT = 400
REQUEST_TIMEOUT = 60


def get_api_page(url, params):
    """Request one page from the UK Parliament Members API."""
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "UK-MP-Financial-Independence-Index/1.0"},
    )
    response.raise_for_status()
    return response.json()


def get_all_member_pages(endpoint, params):
    """Download all pages returned by a Members API endpoint."""
    members = []
    skip = 0
    take = 20

    while True:
        page_params = params.copy()
        page_params["skip"] = skip
        page_params["take"] = take

        data = get_api_page(
            MEMBERS_API + endpoint,
            page_params,
        )

        items = data.get("items", []) or []
        total = data.get("totalResults")

        if not items:
            break

        members.extend(items)

        print(
            "Downloaded",
            len(members),
            "of",
            total if total is not None else "?",
            "members",
        )

        if total is not None and len(members) >= int(total):
            break

        if len(items) < take:
            break

        skip += take

    return members


def get_current_mps():
    """Get all current Commons MPs."""
    print("\nGetting current Commons MPs...")

    return get_all_member_pages(
        "/Search",
        {
            "House": 1,
            "IsCurrentMember": True,
        },
    )




def get_historical_mps(date):
    """
    Get all Commons MPs who were members on or after
    the specified date, including former MPs.
    """

    print("\nGetting historical Commons MPs from", date)

    records = get_all_member_pages(
        "/Search",
        {
            "MembershipInDateRange.WasMemberOnOrAfter": (
                f"{date}T00:00:00"
            ),
            "MembershipInDateRange.WasMemberOfHouse": 1,
        },
    )

    print("Commons MPs found:", len(records))

    return records




def extract_member_details(record):
    """Convert a Members API record into the scoring-engine format."""

    if not isinstance(record, dict):
        return None

    if "value" in record and isinstance(record["value"], dict):
        record = record["value"]

    member_id = (
        record.get("id")
        or record.get("memberId")
        or record.get("MnisId")
        or record.get("mnisId")
    )

    if member_id is None:
        return None

    try:
        member_id = int(float(member_id))
    except (TypeError, ValueError):
        return None

    name = (
        record.get("nameDisplayAs")
        or record.get("nameListAs")
        or record.get("name")
        or record.get("Member")
        or ""
    )

    # Parliament stores the party inside latestParty.
    party = (
        record.get("latestParty")
        or record.get("party")
        or record.get("Party")
        or ""
    )

    if isinstance(party, dict):
        party = (
            party.get("name")
            or party.get("nameOfParty")
            or party.get("value")
            or ""
        )

    return {
        "Mnis Id": member_id,
        "Member": str(name).strip(),
        "Party": str(party).strip(),
    }



def add_member(population, record):
    """Add one member record to the population, keyed by numeric ID."""
    member = extract_member_details(record)

    if member is None:
        return

    member_id = member["Mnis Id"]

    # Prefer a record with a name/party over an incomplete record.
    existing = population.get(member_id, {})

    if not existing.get("Member") and member["Member"]:
        existing["Member"] = member["Member"]

    if not existing.get("Party") and member["Party"]:
        existing["Party"] = member["Party"]

    existing["Mnis Id"] = member_id
    population[member_id] = existing


def build_mp_population(register_data):
    """
    Build the MP population using three sources:
    - MPs serving on the start date (1 July 2024);
    - MPs who are current Commons members;
    - MPs named in the downloaded register records.

    The register records help retain MPs who left Parliament after
    making a declaration during the period.
    """
    print("\n" + "=" * 70)
    print("BUILDING MP POPULATION")
    print("=" * 70)

    population = {}

    historical_records = get_historical_mps(START_DATE)
    for record in historical_records:
        add_member(population, record)

    print("After adding historical MPs:", len(population))

    current_records = get_current_mps()
    for record in current_records:
        add_member(population, record)

    print("After adding current MPs:", len(population))

    if not isinstance(register_data, pd.DataFrame):
        raise RuntimeError(
            "SAFETY STOP: Register data is not a pandas DataFrame."
        )

    possible_id_columns = [
        "Mnis Id",
        "MNIS Id",
        "MnisId",
        "Member Id",
        "MemberId",
    ]

    id_column = next(
        (column for column in possible_id_columns
         if column in register_data.columns),
        None,
    )

    if id_column is None:
        raise RuntimeError(
            "SAFETY STOP: Could not find an MP ID column "
            "in the downloaded register data."
        )

    name_column = next(
        (column for column in ["Member", "Member Name", "Name"]
         if column in register_data.columns),
        None,
    )

    party_column = (
        "Party" if "Party" in register_data.columns else None
    )

    additional_members = 0

    for _, row in register_data.iterrows():
        raw_id = row[id_column]

        if pd.isna(raw_id):
            continue

        try:
            member_id = int(float(raw_id))
        except (TypeError, ValueError):
            continue

        name = ""
        if name_column is not None and pd.notna(row[name_column]):
            name = str(row[name_column]).strip()

        party = ""
        if party_column is not None and pd.notna(row[party_column]):
            party = str(row[party_column]).strip()

        if member_id not in population:
            additional_members += 1
            population[member_id] = {
                "Mnis Id": member_id,
                "Member": name,
                "Party": party,
            }
        else:
            if not population[member_id].get("Member") and name:
                population[member_id]["Member"] = name
            if not population[member_id].get("Party") and party:
                population[member_id]["Party"] = party

    print("Additional MPs found in register records:", additional_members)

    members = list(population.values())
    members.sort(key=lambda member: member["Member"].lower())

    print("\nFINAL MP POPULATION:", len(members))
    return members


def validate_results(final, all_data, scored, members):
    """Stop the update if any essential data checks fail."""
    print("\n" + "=" * 70)
    print("FINAL DATA SAFETY CHECK")
    print("=" * 70)

    if all_data is None or all_data.empty:
        raise RuntimeError(
            "SAFETY STOP: No register rows were downloaded. "
            "Existing website data has NOT been replaced."
        )

    if scored is None or scored.empty:
        raise RuntimeError(
            "SAFETY STOP: No register interests were scored. "
            "Existing website data has NOT been replaced."
        )

    if len(members) < MINIMUM_MP_COUNT:
        raise RuntimeError(
            "SAFETY STOP: MP population contains fewer than "
            + str(MINIMUM_MP_COUNT)
            + " MPs. Existing website data has NOT been replaced."
        )

    required_columns = [
        "Mnis Id",
        "Member",
        "Final Score",
        "Grade",
        "Total Raw Penalty",
        "Donations Penalty",
        "Employment Penalty",
        "Gifts Penalty",
        "Overseas Penalty",
        "Property Penalty",
        "Shareholdings Penalty",
        "Family Penalty",
        "Miscellaneous Penalty",
        "Concentration Penalty",
        "Transparency Penalty",
        "Rectification Count",
        "Land Penalty",
    ]

    missing = [
        column for column in required_columns
        if column not in final.columns
    ]

    if missing:
        raise RuntimeError(
            "SAFETY STOP: Required score columns are missing: "
            + ", ".join(missing)
        )

    if len(final) < MINIMUM_MP_COUNT:
        raise RuntimeError(
            "SAFETY STOP: Final score file contains fewer than "
            + str(MINIMUM_MP_COUNT)
            + " MPs. Existing website data has NOT been replaced."
        )

    if final["Mnis Id"].isna().any():
        raise RuntimeError(
            "SAFETY STOP: Missing MP IDs were found in final data."
        )

    if final["Mnis Id"].duplicated().any():
        raise RuntimeError(
            "SAFETY STOP: Duplicate MP IDs were found in final data."
        )

    if final["Member"].isna().any() or (
        final["Member"].astype(str).str.strip() == ""
    ).any():
        raise RuntimeError(
            "SAFETY STOP: Missing MP names were found in final data."
        )

    scores = pd.to_numeric(final["Final Score"], errors="coerce")

    if scores.isna().any() or not scores.between(0, 100).all():
        raise RuntimeError(
            "SAFETY STOP: Final scores contain missing or invalid values."
        )

    if final["Grade"].isna().any():
        raise RuntimeError(
            "SAFETY STOP: Missing grades were found in final data."
        )

    print("Final MP rows:", len(final))
    print("Register rows:", len(all_data))
    print("Scored interest rows:", len(scored))
    print("All safety checks passed.")


def save_website_data(final, all_data, registers):
    """Write validated website data using temporary files first."""
    original_final = DATA / (
        "UK_MP_FINANCIAL_INTEGRITY_FINAL_JULY_2024_ONWARDS.csv"
    )
    website_scores = DATA / "scores.csv"
    interests_file = DATA / "interests.csv.gz"
    last_update = DATA / "last_update.txt"

    temporary_final = DATA / "scores_update.tmp"
    temporary_interests = DATA / "interests_update.tmp"
    temporary_timestamp = DATA / "last_update_update.tmp"

    # Write temporary files first. Existing live data is left untouched
    # if writing or validation of a temporary file fails.
    final.to_csv(
        temporary_final,
        index=False,
        encoding="utf-8-sig",
    )

    all_data.to_csv(
        temporary_interests,
        index=False,
        compression="gzip",
    )

    latest = max(
        str(register["publishedDate"])
        for register in registers
    )

    timestamp_text = (
        "Latest Parliament register: " + latest + "\n"
        + "Registers processed: " + str(len(registers)) + "\n"
        + "MPs scored: " + str(len(final)) + "\n"
        + "Updated automatically: "
        + datetime.now(timezone.utc).isoformat()
        + "\n"
    )

    temporary_timestamp.write_text(
        timestamp_text,
        encoding="utf-8",
    )

    # Check that the temporary files can be read before replacing live files.
    check_scores = pd.read_csv(temporary_final)
    if len(check_scores) != len(final):
        raise RuntimeError(
            "SAFETY STOP: Temporary score CSV failed its row-count check."
        )

    with pd.read_csv(
        temporary_interests,
        compression="gzip",
        chunksize=1,
    ) as _:
        pass

    # Replace the files used by the website.
    os.replace(temporary_final, website_scores)
    os.replace(temporary_interests, interests_file)
    os.replace(temporary_timestamp, last_update)

    # Keep a clearly named copy of the final output as well.
    shutil.copy2(website_scores, original_final)

    print("\nWebsite data updated successfully.")
    print("Scores:", website_scores)
    print("Interests:", interests_file)
    print("Timestamp:", last_update)
    print("Full final output:", original_final)

    return latest


def main():
    print("=" * 70)
    print("AUTOMATIC UK MP FINANCIAL INDEPENDENCE INDEX UPDATE")
    print("Registers from", START_DATE, "onwards")
    print("=" * 70)

    # 1. Download the Commons registers.
    print("\nGetting Parliament registers...")
    registers = engine.get_registers()

    if not registers:
        raise RuntimeError(
            "SAFETY STOP: No Parliament registers were found."
        )

    print("Registers found:", len(registers))

    # 2. Download all register CSV data.
    print("\nDownloading register data...")
    all_data = engine.download_all_register_data(registers)

    if all_data is None or all_data.empty:
        raise RuntimeError(
            "SAFETY STOP: Register data download returned no rows."
        )

    print("Register rows downloaded:", len(all_data))

    # 3. Build the MP population.
    members = build_mp_population(all_data)

    print("\nMPs found:", len(members))

    if len(members) < MINIMUM_MP_COUNT:
        raise RuntimeError(
            "SAFETY STOP: MP population is still below "
            + str(MINIMUM_MP_COUNT)
            + ". No website data will be replaced."
        )

    ids = [member["Mnis Id"] for member in members]

    if len(ids) != len(set(ids)):
        raise RuntimeError(
            "SAFETY STOP: Duplicate MP IDs were found."
        )

    # 4. Use the original scoring engine.
    print("\n" + "=" * 70)
    print("RUNNING ORIGINAL SCORING ENGINE")
    print("=" * 70)

    scored = engine.score_all_interests(all_data)

    final = engine.build_final_scores(
        scored,
        members,
    )

    # 5. Validate before changing website files.
    validate_results(
        final,
        all_data,
        scored,
        members,
    )

    # 6. Save the new website data.
    latest = save_website_data(
        final,
        all_data,
        registers,
    )

    print("\n" + "=" * 70)
    print("AUTOMATIC UPDATE COMPLETE")
    print("=" * 70)
    print("Registers processed:", len(registers))
    print("Latest register:", latest)
    print("MPs scored:", len(final))
    print("Website scores:", DATA / "scores.csv")


if __name__ == "__main__":
    main()
