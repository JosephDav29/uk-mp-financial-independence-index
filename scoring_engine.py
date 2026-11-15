
# UK MP FINANCIAL INTEGRITY INDEX
# Replacement scoring_engine.py
#
# Downloads Commons Registers from 1 July 2024 onwards,
# identifies the latest version of each interest, scores interests,
# and produces final MP scores.
#
# Designed to work both:
# 1. As an imported scoring engine for update_data.py
# 2. As a standalone script in Spyder
#
# IMPORTANT:
# The score measures declared interests assessed under this formula.
# It is NOT a definitive measure of an MP's honesty, wealth,
# financial independence or actual conflicts of interest.

import re
import zipfile
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# SETTINGS
# ============================================================

START_DATE = "2024-07-01"

BASE_FOLDER = Path(__file__).resolve().parent

RAW_FOLDER = BASE_FOLDER / "data" / "Raw Registers"
EXTRACTED_FOLDER = BASE_FOLDER / "data" / "Extracted Registers"
RESULTS_FOLDER = BASE_FOLDER / "data"

MEMBERS_API = "https://members-api.parliament.uk/api/Members/Search"
REGISTERS_API = "https://interests-api.parliament.uk/api/v2/Registers"
CSV_API = "https://interests-api.parliament.uk/api/v2/Interests/csv"

REQUEST_TIMEOUT = 90

for folder in [
    BASE_FOLDER,
    RAW_FOLDER,
    EXTRACTED_FOLDER,
    RESULTS_FOLDER
]:
    folder.mkdir(parents=True, exist_ok=True)


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    """Convert a value into clean text."""
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def normalise_text(value):
    """Lowercase text and remove repeated whitespace."""
    text = clean_text(value).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_empty(value):
    """Check whether a value is effectively empty."""
    text = normalise_text(value)

    return text in {
        "",
        "nan",
        "none",
        "null",
        "n/a",
        "na",
        "-",
        "—"
    }


def safe_filename(text):
    """Remove characters unsuitable for filenames."""
    text = clean_text(text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:150]


def get_request(url, params=None, binary=False):
    """Make a request with three attempts."""
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "UK-MP-Financial-Independence-Index/1.0"
                    )
                }
            )

            response.raise_for_status()

            if binary:
                return response.content

            return response.json()

        except Exception as error:
            last_error = error

            print(
                "Request failed, attempt",
                attempt + 1,
                "of 3:",
                error
            )

    raise last_error


# ============================================================
# MP POPULATION
# ============================================================

def get_members(params):
    """Download every page of the Parliament Members API."""

    all_records = []
    skip = 0
    take = 20

    while True:
        request_params = params.copy()
        request_params["skip"] = skip
        request_params["take"] = take

        data = get_request(
            MEMBERS_API,
            request_params
        )

        items = data.get("items", []) or []
        total = data.get("totalResults")

        if not items:
            break

        all_records.extend(items)

        print(
            "Downloaded",
            len(all_records),
            "of",
            total if total is not None else "?",
            "members"
        )

        if total is not None and len(all_records) >= int(total):
            break

        if len(items) < take:
            break

        skip += take

    return all_records


def normalise_member_record(record):
    """
    Convert a Parliament API record into the standard format.

    The API may return the party inside latestParty rather
    than as a simple party string.
    """

    if not isinstance(record, dict):
        return None

    member = record.get("value", record)

    if not isinstance(member, dict):
        return None

    member_id = (
        member.get("id")
        or member.get("memberId")
        or member.get("MnisId")
        or member.get("mnisId")
    )

    if member_id is None:
        return None

    try:
        member_id = int(float(member_id))
    except (TypeError, ValueError):
        return None

    name = (
        member.get("nameDisplayAs")
        or member.get("nameListAs")
        or member.get("nameFullTitle")
        or member.get("Member")
        or "Unknown"
    )

    party_data = (
        member.get("latestParty")
        or member.get("party")
        or member.get("Party")
        or ""
    )

    if isinstance(party_data, dict):
        party = (
            party_data.get("name")
            or party_data.get("nameOfParty")
            or party_data.get("value")
            or ""
        )
    else:
        party = party_data

    return {
        "Mnis Id": member_id,
        "Member": clean_text(name),
        "Party": clean_text(party)
    }


def get_all_mps():
    """Get MPs who were Commons members on or after START_DATE."""

    print("\n" + "=" * 70)
    print("GETTING MP POPULATION")
    print("=" * 70)

    params = {
        "House": 1,
        "MembershipInDateRange.WasMemberOnOrAfter":
            START_DATE + "T00:00:00"
    }

    records = get_members(params)

    unique_members = {}

    for record in records:
        member = normalise_member_record(record)

        if member is None:
            continue

        unique_members[member["Mnis Id"]] = member

    members = list(unique_members.values())

    members.sort(
        key=lambda x: x["Member"].lower()
    )

    print("\nRaw API records:", len(records))
    print("Unique Commons MPs:", len(members))

    if len(members) < 400:
        print(
            "WARNING: MP population is unexpectedly small."
        )

    missing_parties = sum(
        1 for member in members
        if not member["Party"]
    )

    print("MPs without party information:", missing_parties)

    print("\nFirst 20 MPs:")

    for member in members[:20]:
        print(
            member["Mnis Id"],
            "-",
            member["Member"],
            "-",
            member["Party"]
        )

    return members


# ============================================================
# REGISTER LIST
# ============================================================

def get_registers():
    """Get all published Commons Registers from START_DATE."""

    print("\n" + "=" * 70)
    print("GETTING REGISTER LIST")
    print("=" * 70)

    all_registers = []
    skip = 0
    take = 20

    while True:
        params = {
            "Skip": skip,
            "Take": take
        }

        data = get_request(
            REGISTERS_API,
            params
        )

        items = data.get("items", []) or []
        total = data.get("totalResults")

        if not items:
            break

        all_registers.extend(items)

        print(
            "Downloaded register records:",
            len(all_registers),
            "of",
            total if total is not None else "?"
        )

        if total is not None and len(all_registers) >= int(total):
            break

        if len(items) < take:
            break

        skip += take

    registers = []

    for register in all_registers:
        published = clean_text(
            register.get("publishedDate")
        )

        register_type = clean_text(
            register.get("type")
        )

        if not published:
            continue

        if published[:10] < START_DATE:
            continue

        if register_type.lower() != "commons":
            continue

        try:
            register_id = int(register["id"])
        except (KeyError, TypeError, ValueError):
            continue

        registers.append({
            "id": register_id,
            "publishedDate": published,
            "type": register_type
        })

    registers.sort(
        key=lambda x: x["publishedDate"]
    )

    print(
        "\nCommons registers from",
        START_DATE + ":",
        len(registers)
    )

    for register in registers:
        print(
            register["id"],
            register["publishedDate"]
        )

    return registers


# ============================================================
# DOWNLOAD AND EXTRACT REGISTERS
# ============================================================

def download_register(register):
    """Download and extract one register ZIP file."""

    register_id = register["id"]
    published = register["publishedDate"]

    name = safe_filename(
        str(register_id) + "_" + published
    )

    zip_path = RAW_FOLDER / (name + ".zip")
    extract_path = EXTRACTED_FOLDER / name

    if not zip_path.exists():
        print(
            "\nDownloading register",
            register_id,
            published
        )

        content = get_request(
            CSV_API,
            params={
                "RegisterId": register_id,
                "IncludeFieldDescriptions": "false"
            },
            binary=True
        )

        with open(zip_path, "wb") as file:
            file.write(content)

    else:
        print(
            "\nAlready downloaded:",
            zip_path.name
        )

    if not extract_path.exists():
        extract_path.mkdir(
            parents=True,
            exist_ok=True
        )

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_path)

    return extract_path


def read_register_csvs(extract_path, register):
    """Read every CSV contained in an extracted register."""

    csv_files = list(
        extract_path.rglob("*.csv")
    )

    if not csv_files:
        print(
            "WARNING: No CSV files found in",
            extract_path
        )

        return pd.DataFrame()

    frames = []

    for csv_file in csv_files:
        try:
            df = pd.read_csv(
                csv_file,
                encoding="utf-8-sig",
                low_memory=False,
                on_bad_lines="skip"
            )

        except UnicodeDecodeError:
            df = pd.read_csv(
                csv_file,
                encoding="latin1",
                low_memory=False,
                on_bad_lines="skip"
            )

        except Exception as error:
            print(
                "Could not read",
                csv_file.name,
                ":",
                error
            )

            continue

        if df.empty:
            continue

        df["_Register_ID"] = register["id"]
        df["_Register_Date"] = register["publishedDate"]
        df["_Source_File"] = csv_file.name

        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(
        frames,
        ignore_index=True,
        sort=False
    )


def download_all_register_data(registers):
    """
    Download and combine all register data.

    This function is also used by update_data.py.
    """

    print("\n" + "=" * 70)
    print("DOWNLOADING ALL REGISTERS")
    print("=" * 70)

    all_frames = []

    for number, register in enumerate(
        registers,
        start=1
    ):
        print(
            "\nREGISTER",
            number,
            "of",
            len(registers),
            "-",
            register["publishedDate"]
        )

        extract_path = download_register(register)

        df = read_register_csvs(
            extract_path,
            register
        )

        print("Rows read:", len(df))

        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        raise RuntimeError(
            "No register CSV data was downloaded or read."
        )

    all_data = pd.concat(
        all_frames,
        ignore_index=True,
        sort=False
    )

    return all_data


# ============================================================
# COLUMN / VERSION HELPERS
# ============================================================

def find_column(df, possible_names):
    """Find a column without relying on exact capitalisation."""

    lookup = {
        normalise_text(column): column
        for column in df.columns
    }

    for name in possible_names:
        key = normalise_text(name)

        if key in lookup:
            return lookup[key]

    return None


def get_member_id(row):
    """Find the MP ID in a register row."""

    possible_names = [
        "Mnis Id",
        "MNIS Id",
        "MnisId",
        "Member Id",
        "Member ID",
        "MemberId"
    ]

    for name in possible_names:
        column = find_column(
            pd.DataFrame(columns=row.index),
            [name]
        )

        if column is None:
            continue

        value = row[column]

        if is_empty(value):
            continue

        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue

    return None


def get_member_name(row):
    """Find the MP's name in a register row."""

    for name in [
        "Member",
        "Member Name",
        "Name"
    ]:
        column = find_column(
            pd.DataFrame(columns=row.index),
            [name]
        )

        if column is not None:
            value = clean_text(row[column])

            if value:
                return value

    return "Unknown"


def get_latest_version_number(row):
    """Find the latest populated Version N Register Date."""

    candidates = []

    for column in row.index:
        match = re.match(
            r"^Version\s*(\d+)\s+Register Date$",
            clean_text(column),
            flags=re.IGNORECASE
        )

        if match:
            version = int(match.group(1))

            if not is_empty(row[column]):
                candidates.append(version)

    if candidates:
        return max(candidates)

    versions = []

    for column in row.index:
        match = re.match(
            r"^Version\s*(\d+)\s+",
            clean_text(column),
            flags=re.IGNORECASE
        )

        if match and not is_empty(row[column]):
            versions.append(int(match.group(1)))

    if versions:
        return max(versions)

    return None


def get_latest_values(row):
    """
    Return ordinary columns plus only the latest populated
    Version N fields.
    """

    latest_version = get_latest_version_number(row)

    values = {}

    for column in row.index:
        column_text = clean_text(column)

        match = re.match(
            r"^Version\s*(\d+)\s+(.+)$",
            column_text,
            flags=re.IGNORECASE
        )

        if match:
            version = int(match.group(1))
            base_name = match.group(2).strip()

            if (
                latest_version is not None
                and version == latest_version
            ):
                values[base_name] = row[column]

        else:
            values[column_text] = row[column]

    values["_Latest_Version"] = latest_version

    return values


def values_to_text(values):
    """Combine non-empty values into a readable description."""

    parts = []

    for key, value in values.items():
        if key.startswith("_"):
            continue

        if not is_empty(value):
            parts.append(clean_text(value))

    return " | ".join(parts)


# ============================================================
# MONEY / PERCENTAGE HELPERS
# ============================================================

def parse_money(value):
    """Extract a monetary amount from a text value."""

    if value is None or is_empty(value):
        return 0.0

    text = clean_text(value).lower()

    multiplier = 1

    if (
        "million" in text
        or re.search(r"£\s*[0-9,.]+\s*m\b", text)
    ):
        multiplier = 1_000_000

    elif (
        "thousand" in text
        or re.search(r"£\s*[0-9,.]+\s*k\b", text)
    ):
        multiplier = 1_000

    matches = re.findall(
        r"£\s*([0-9][0-9,]*(?:\.\d+)?)",
        text
    )

    if not matches:
        matches = re.findall(
            r"([0-9][0-9,]*(?:\.\d+)?)\s*(?:gbp|pounds)",
            text
        )

    if not matches:
        return 0.0

    try:
        return (
            max(
                float(x.replace(",", ""))
                for x in matches
            )
            * multiplier
        )

    except (TypeError, ValueError):
        return 0.0


def parse_percentage(value):
    """Extract a percentage from a text value."""

    if value is None or is_empty(value):
        return 0.0

    text = clean_text(value).replace(",", "")

    match = re.search(
        r"([0-9]+(?:\.\d+)?)\s*%",
        text
    )

    if match:
        return float(match.group(1))

    try:
        number = float(text)

        if 0 <= number <= 1:
            return number * 100

        return number

    except (TypeError, ValueError):
        return 0.0


def first_value(values, names):
    """Return the first populated matching field."""

    lookup = {
        normalise_text(key): key
        for key in values.keys()
    }

    for name in names:
        key = normalise_text(name)

        if key in lookup:
            value = values[lookup[key]]

            if not is_empty(value):
                return value

    return ""


def all_values_text(values):
    """Return all interest values as lowercase text."""
    return values_to_text(values).lower()


# ============================================================
# CATEGORY DETECTION
# ============================================================

def normalise_category(value):
    """
    Convert Parliament category numbers or descriptions
    into standard category names.

    Land and Property are deliberately separate.
    """

    text = normalise_text(value)

    match = re.match(
        r"^(\d+)\b",
        text
    )

    if match:
        number = int(match.group(1))

        mapping = {
            1: "Employment",
            2: "Donations",
            3: "Gifts",
            4: "Overseas",
            5: "Land",
            6: "Property",
            7: "Shareholdings",
            8: "Miscellaneous",
            9: "Family",
            10: "Miscellaneous"
        }

        if number in mapping:
            return mapping[number]

    if "employment" in text or "earnings" in text:
        return "Employment"

    if "donation" in text or "political support" in text:
        return "Donations"

    if "gift" in text or "hospitality" in text:
        return "Gifts"

    if "overseas" in text or "visit" in text:
        return "Overseas"

    if "shareholding" in text or "shares" in text:
        return "Shareholdings"

    if "family" in text:
        return "Family"

    if "land" in text:
        return "Land"

    if "property" in text:
        return "Property"

    return "Miscellaneous"


# ============================================================
# SCORING RULES
# ============================================================

def cap_penalty(value):
    """Cap an individual interest penalty at 15."""
    return min(max(float(value), 0.0), 15.0)


def score_donation(values):
    text = all_values_text(values)

    amount = parse_money(
        first_value(
            values,
            [
                "Value",
                "Amount",
                "Donation",
                "Value of Donation",
                "Payment",
                "Financial Value"
            ]
        )
    )

    score = 2

    if amount >= 100000:
        score = 10
    elif amount >= 50000:
        score = 8
    elif amount >= 10000:
        score = 5
    elif amount >= 5000:
        score = 4
    elif amount >= 1000:
        score = 3

    if "trade association" in text or "trade union" in text:
        score *= 1.75

    elif "lobby" in text or "public affairs" in text:
        score *= 2

    elif "contractor" in text:
        score *= 2

    elif "foreign" in text or "overseas" in text:
        score *= 2

    elif (
        "company" in text
        or "limited" in text
        or " plc" in text
    ):
        score *= 1.5

    return cap_penalty(score)


def score_employment(values):
    text = all_values_text(values)

    amount = parse_money(
        first_value(
            values,
            [
                "Payment",
                "Payments",
                "Amount",
                "Value",
                "Financial Value",
                "Earnings"
            ]
        )
    )

    score = 2

    if "consult" in text:
        score += 4

    if "advisory" in text or "advisor" in text:
        score += 4

    if "corporate" in text:
        score += 5

    if "public affairs" in text:
        score += 6

    if "lobby" in text or "lobbying" in text:
        score += 8

    if "trade association" in text:
        score += 6

    if "contractor" in text:
        score += 6

    if amount >= 100000:
        score += 6
    elif amount >= 50000:
        score += 5
    elif amount >= 10000:
        score += 3
    elif amount >= 5000:
        score += 2

    return cap_penalty(score)


def score_gift(values):
    text = all_values_text(values)

    amount = parse_money(
        first_value(
            values,
            [
                "Value",
                "Amount",
                "Gift Value",
                "Financial Value"
            ]
        )
    )

    score = 2

    if amount >= 10000:
        score = 10
    elif amount >= 5000:
        score = 7
    elif amount >= 2000:
        score = 5
    elif amount >= 1000:
        score = 4

    if "trade association" in text:
        score += 3

    elif "lobby" in text or "public affairs" in text:
        score += 4

    elif (
        "company" in text
        or "limited" in text
        or " plc" in text
    ):
        score += 2

    return cap_penalty(score)


def score_overseas(values):
    text = all_values_text(values)

    amount = parse_money(
        first_value(
            values,
            [
                "Value",
                "Amount",
                "Visit Value",
                "Financial Value"
            ]
        )
    )

    score = 3

    if amount >= 10000:
        score = 8
    elif amount >= 5000:
        score = 6
    elif amount >= 2000:
        score = 4

    if "trade association" in text or "industry" in text:
        score += 3

    elif "lobby" in text or "public affairs" in text:
        score += 4

    elif (
        "company" in text
        or "limited" in text
        or " plc" in text
    ):
        score += 2

    return cap_penalty(score)


def score_land(values):
    """
    Score declared land interests.

    This is a risk-screening proxy, not a valuation of the land.
    The penalty reflects features such as commercial use,
    development and rental activity.
    """

    text = all_values_text(values)

    score = 2

    if "commercial" in text:
        score += 3

    if "development" in text or "developer" in text:
        score += 4

    if "agricultural" in text or "farmland" in text:
        score += 2

    if "rental income" in text or "rent" in text:
        score += 2

    if "mineral" in text or "extraction" in text:
        score += 3

    if "energy" in text or "renewable" in text:
        score += 2

    return cap_penalty(score)


def score_property(values):
    """Score declared property interests."""

    text = all_values_text(values)

    score = 2

    if "commercial" in text:
        score += 3

    if "development" in text or "developer" in text:
        score += 4

    if "rental income" in text or "rent" in text:
        score += 2

    if "business premises" in text:
        score += 2

    return cap_penalty(score)


def score_shareholding(values):
    text = all_values_text(values)

    percentage = parse_percentage(
        first_value(
            values,
            [
                "Percentage",
                "Shareholding",
                "Shares",
                "Percentage Held"
            ]
        )
    )

    score = 4

    if percentage >= 15:
        score += 10

    if "government" in text:
        score += 3

    if "contractor" in text:
        score += 3

    if "regulated" in text:
        score += 2

    if "lobby" in text or "public affairs" in text:
        score += 3

    return cap_penalty(score)


def score_family(values):
    text = all_values_text(values)

    score = 2

    if "lobby" in text or "public affairs" in text:
        score += 2

    return cap_penalty(score)


def score_miscellaneous(values):
    text = all_values_text(values)

    score = 1

    if "director" in text:
        score += 2

    if "trustee" in text:
        score += 2

    if "consult" in text:
        score += 2

    if "lobby" in text or "public affairs" in text:
        score += 3

    if (
        "company" in text
        or "limited" in text
        or " plc" in text
    ):
        score += 1

    return cap_penalty(score)


def score_interest(category, values):
    """Apply the appropriate scoring function."""

    scoring_functions = {
        "Donations": score_donation,
        "Employment": score_employment,
        "Gifts": score_gift,
        "Overseas": score_overseas,
        "Land": score_land,
        "Property": score_property,
        "Shareholdings": score_shareholding,
        "Family": score_family,
        "Miscellaneous": score_miscellaneous
    }

    scoring_function = scoring_functions.get(
        category,
        score_miscellaneous
    )

    return scoring_function(values)


# ============================================================
# INTEREST IDENTIFICATION
# ============================================================

def get_interest_id(row):
    """Find an interest ID, or create a fallback identifier."""

    for name in [
        "Id",
        "Interest ID",
        "Interest Id",
        "InterestID"
    ]:
        column = find_column(
            pd.DataFrame(columns=row.index),
            [name]
        )

        if column is not None and not is_empty(row[column]):
            try:
                return str(int(float(row[column])))
            except (TypeError, ValueError):
                return clean_text(row[column])

    member = get_member_id(row)

    category = clean_text(
        row.get("Category", "")
    )

    summary = clean_text(
        row.get("Summary", "")
    )

    return (
        "fallback|"
        + str(member)
        + "|"
        + category
        + "|"
        + summary
    )


def get_fingerprint(values):
    """
    Create a fingerprint of the declared interest.

    Internal register metadata is excluded.
    """

    pieces = []

    for key in sorted(values.keys()):
        if key.startswith("_"):
            continue

        value = clean_text(values[key])

        if value:
            pieces.append(
                normalise_text(key)
                + "="
                + normalise_text(value)
            )

    return "|".join(pieces)


# ============================================================
# SCORE LATEST INTEREST VERSIONS
# ============================================================

def score_all_interests(all_data):
    """
    Score the latest available version of each unique interest.

    Earlier register versions are retained in all_data, but
    they do not accumulate additional penalties.

    The unique key is the combination of MP ID and Interest ID.
    """

    print("\n" + "=" * 70)
    print("SCORING LATEST INTEREST VERSIONS")
    print("=" * 70)

    if all_data is None or all_data.empty:
        return pd.DataFrame()

    required_sort_columns = [
        "_Register_Date",
        "_Register_ID"
    ]

    for column in required_sort_columns:
        if column not in all_data.columns:
            raise RuntimeError(
                "Missing required register column: " + column
            )

    ordered_data = all_data.sort_values(
        by=required_sort_columns,
        kind="stable"
    )

    latest_interests = {}

    total_rows = len(ordered_data)

    for counter, (_, row) in enumerate(
        ordered_data.iterrows(),
        start=1
    ):
        values = get_latest_values(row)

        member_id = get_member_id(row)

        if member_id is None:
            continue

        member_name = get_member_name(row)

        category_value = first_value(
            values,
            [
                "Category",
                "Category Name"
            ]
        )

        category = normalise_category(category_value)

        interest_id = get_interest_id(row)

        # Include MP ID in the key so that identical interest IDs
        # belonging to different MPs cannot be merged.
        unique_key = (
            member_id,
            interest_id
        )

        fingerprint = get_fingerprint(values)

        if unique_key not in latest_interests:
            latest_interests[unique_key] = {
                "row": row.copy(),
                "values": values,
                "member_name": member_name,
                "category": category,
                "category_value": category_value,
                "fingerprints": {fingerprint},
                "number_of_versions": 1
            }

        else:
            existing = latest_interests[unique_key]

            existing["fingerprints"].add(fingerprint)
            existing["number_of_versions"] += 1

            # Because the data is sorted chronologically,
            # this replaces the previous version with the latest.
            existing["row"] = row.copy()
            existing["values"] = values
            existing["member_name"] = member_name
            existing["category"] = category
            existing["category_value"] = category_value

        if counter % 1000 == 0:
            print(
                "Processed",
                counter,
                "of",
                total_rows,
                "register rows"
            )

    scored_rows = []

    for unique_key, record in latest_interests.items():

        member_id, interest_id = unique_key

        row = record["row"]
        values = record["values"]

        category = record["category"]

        normal_penalty = score_interest(
            category,
            values
        )

        # Identify whether this interest has changed over time.
        number_of_versions = record["number_of_versions"]
        number_of_fingerprints = len(record["fingerprints"])

        if number_of_versions == 1:
            status = "NEW"

        elif number_of_fingerprints > 1:
            status = "UPDATED"

        else:
            status = "UNCHANGED"

        # The latest interest is scored once, at its full penalty.
        # Previous versions are not added again.
        applied_penalty = normal_penalty

        scored_rows.append({
            "Mnis Id": member_id,
            "Member": record["member_name"],
            "Category": category,
            "Original Category": clean_text(
                record["category_value"]
            ),
            "Interest ID": interest_id,
            "Register ID": row.get("_Register_ID", ""),
            "Register Date": row.get("_Register_Date", ""),
            "Status": status,
            "Number of Versions": number_of_versions,
            "Normal Interest Penalty": normal_penalty,
            "Applied Cumulative Penalty": applied_penalty,
            "Latest Version": values.get(
                "_Latest_Version",
                ""
            ),
            "Interest Description": values_to_text(values)
        })

    scored = pd.DataFrame(scored_rows)

    if scored.empty:
        return scored

    print("\nRegister rows examined:", total_rows)
    print("Unique interests scored:", len(scored))

    print("\nInterest status:")
    print(
        scored["Status"].value_counts().to_string()
    )

    print("\nCategory counts:")
    print(
        scored["Category"].value_counts().to_string()
    )

    print(
        "\nTotal applied interest penalty:",
        round(
            scored["Applied Cumulative Penalty"].sum(),
            2
        )
    )

    return scored


# ============================================================
# TRANSPARENCY / RECTIFICATION
# ============================================================

def calculate_transparency(scored):
    """
    Count descriptions containing rectification or correction.

    This is reported separately. It does not automatically
    reduce the MP's score.
    """

    transparency = {}

    if scored is None or scored.empty:
        return transparency

    for member_id, group in scored.groupby("Mnis Id"):

        rectification_count = 0

        for _, row in group.iterrows():
            text = normalise_text(
                row.get("Interest Description", "")
            )

            if (
                "rectif" in text
                or "correction" in text
            ):
                rectification_count += 1

        transparency[member_id] = rectification_count

    return transparency


# ============================================================
# CONCENTRATION
# ============================================================

def concentration_penalty(category_penalties):
    """
    Calculate the concentration component.

    This is a feature of the index's chosen methodology,
    not proof that concentrated interests create a conflict.
    """

    total = sum(
        category_penalties.values()
    )

    if total <= 0:
        return 0.0

    largest = max(
        category_penalties.values()
    )

    share = largest / total

    if share < 0.40:
        return 0.0

    elif share < 0.60:
        return 3.0

    elif share < 0.75:
        return 6.0

    elif share < 0.90:
        return 8.0

    return 10.0


# ============================================================
# GRADING
# ============================================================

def grade(score):
    """Convert a numerical score into a letter grade."""

    if score >= 95:
        return "A+"

    elif score >= 90:
        return "A"

    elif score >= 85:
        return "A-"

    elif score >= 80:
        return "B+"

    elif score >= 75:
        return "B"

    elif score >= 70:
        return "B-"

    elif score >= 65:
        return "C+"

    elif score >= 60:
        return "C"

    elif score >= 55:
        return "C-"

    elif score >= 50:
        return "D+"

    elif score >= 45:
        return "D"

    elif score >= 40:
        return "D-"

    return "F"


# ============================================================
# FINAL MP SCORES
# ============================================================

def build_final_scores(scored, members):
    """
    Combine interest penalties into final MP scores.

    Includes all MPs in the population, including MPs with
    no matching register interests in the downloaded data.
    """

    print("\n" + "=" * 70)
    print("BUILDING FINAL MP SCORES")
    print("=" * 70)

    category_names = [
        "Donations",
        "Employment",
        "Gifts",
        "Overseas",
        "Land",
        "Property",
        "Shareholdings",
        "Family",
        "Miscellaneous"
    ]

    transparency = calculate_transparency(scored)

    raw_by_member = {}

    if scored is not None and not scored.empty:

        for member_id, group in scored.groupby("Mnis Id"):

            category_totals = {}

            for category in category_names:
                category_totals[category] = float(
                    group.loc[
                        group["Category"] == category,
                        "Applied Cumulative Penalty"
                    ].sum()
                )

            raw_total = sum(
                category_totals.values()
            )

            raw_by_member[member_id] = {
                "category_totals": category_totals,
                "raw_total": raw_total
            }

    positive_raw = [
        record["raw_total"]
        for record in raw_by_member.values()
        if record["raw_total"] > 0
    ]

    if positive_raw:
        K = float(
            np.median(positive_raw)
        )
    else:
        K = 1.0

    if K <= 0:
        K = 1.0

    print(
        "Median positive raw penalty K =",
        round(K, 4)
    )

    member_lookup = {
        int(member["Mnis Id"]): member
        for member in members
    }

    rows = []

    for member_id, member in member_lookup.items():

        if member_id in raw_by_member:
            category_totals = raw_by_member[
                member_id
            ]["category_totals"]

            raw_total = raw_by_member[
                member_id
            ]["raw_total"]

        else:
            category_totals = {
                category: 0.0
                for category in category_names
            }

            raw_total = 0.0

        concentration = concentration_penalty(
            category_totals
        )

        rectification_count = transparency.get(
            member_id,
            0
        )

        # Rectifications are recorded but are not automatically
        # treated as evidence of misconduct or poor transparency.
        transparency_penalty = 0.0

        total_raw_penalty = (
            raw_total
            + concentration
            + transparency_penalty
        )

        score = (
            100.0
            / (1.0 + total_raw_penalty / K)
        )

        score = max(
            0.0,
            min(100.0, score)
        )

        row = {
            "Mnis Id": member_id,
            "Member": member.get("Member", "Unknown"),
            "Party": member.get("Party", "")
        }

        for category in category_names:
            row[category + " Penalty"] = (
                category_totals[category]
            )

        row["Raw Interest Penalty"] = raw_total
        row["Concentration Penalty"] = concentration
        row["Rectification Count"] = rectification_count
        row["Transparency Penalty"] = transparency_penalty
        row["Total Raw Penalty"] = total_raw_penalty
        row["Calibration K"] = K
        row["Final Score"] = score
        row["Grade"] = grade(score)

        rows.append(row)

    final = pd.DataFrame(rows)

    final = final.sort_values(
        ["Final Score", "Member"],
        ascending=[False, True]
    ).reset_index(drop=True)

    print("\nFinal MP population:", len(final))

    print("\nGrade distribution:")
    print(
        final["Grade"].value_counts().sort_index().to_string()
    )

    print("\nScore distribution:")
    print(
        final["Final Score"].describe().to_string()
    )

    print("\nCategory penalty totals:")

    for category in category_names:
        column = category + " Penalty"

        print(
            category + ":",
            round(final[column].sum(), 2)
        )

        # DIAGNOSTIC: investigate MPs receiving exactly 100
    print("\n" + "=" * 70)
    print("INVESTIGATING MPs WITH A SCORE OF 100")
    print("=" * 70)

    interest_counts = (
        scored.groupby("Mnis Id")
        .size()
        .to_dict()
    )

    final["Interest Count"] = (
        final["Mnis Id"]
        .map(interest_counts)
        .fillna(0)
        .astype(int)
    )

    perfect_scores = final[
        final["Final Score"] == 100
    ]

    print("MPs scoring 100:", len(perfect_scores))

    print("\nTheir interest counts:")

    print(
        perfect_scores[
            ["Member", "Party", "Interest Count"]
        ].to_string(index=False)
    )

    print("\nMPs scoring 100 with no matched interests:")

    print(
        perfect_scores[
            perfect_scores["Interest Count"] == 0
        ][
            ["Member", "Party"]
        ].to_string(index=False)
    )
    return final


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(members, all_data, scored, final):
    """Save population, raw data, interest scores and final scores."""

    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)

    population_df = pd.DataFrame(members)

    population_path = RESULTS_FOLDER / (
        "UK_MP_POPULATION_JULY_2024_ONWARDS.csv"
    )

    interest_path = RESULTS_FOLDER / (
        "UK_MP_INTEREST_LEVEL_SCORING_JULY_2024_ONWARDS.csv"
    )

    final_path = RESULTS_FOLDER / (
        "UK_MP_FINANCIAL_INTEGRITY_FINAL_JULY_2024_ONWARDS.csv"
    )

    raw_path = RESULTS_FOLDER / (
        "UK_MP_ALL_REGISTER_DATA_JULY_2024_ONWARDS.csv"
    )

    population_df.to_csv(
        population_path,
        index=False,
        encoding="utf-8-sig"
    )

    scored.to_csv(
        interest_path,
        index=False,
        encoding="utf-8-sig"
    )

    final.to_csv(
        final_path,
        index=False,
        encoding="utf-8-sig"
    )

    all_data.to_csv(
        raw_path,
        index=False,
        encoding="utf-8-sig"
    )

    print("\nSaved:")
    print(population_path)
    print(interest_path)
    print(final_path)
    print(raw_path)

    return final


# ============================================================
# GRAPHS
# ============================================================

def make_graphs(final):
    """Create score distribution and penalty graphs."""

    print("\nCreating graphs...")

    # Score histogram.
    plt.figure(figsize=(12, 7))

    plt.hist(
        final["Final Score"],
        bins=25,
        edgecolor="black"
    )

    plt.xlabel("Final Score")
    plt.ylabel("Number of MPs")

    plt.title(
        "UK MP Financial Integrity Index - Score Distribution"
    )

    plt.xlim(0, 100)
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()

    histogram_path = RESULTS_FOLDER / (
        "UK_MP_FINANCIAL_INTEGRITY_DISTRIBUTION.png"
    )

    plt.savefig(
        histogram_path,
        dpi=200
    )

    plt.close()

    # Grade distribution.
    grade_order = [
        "A+",
        "A",
        "A-",
        "B+",
        "B",
        "B-",
        "C+",
        "C",
        "C-",
        "D+",
        "D",
        "D-",
        "F"
    ]

    counts = final["Grade"].value_counts()

    grade_counts = [
        counts.get(grade_name, 0)
        for grade_name in grade_order
    ]

    plt.figure(figsize=(12, 7))

    plt.bar(
        grade_order,
        grade_counts
    )

    plt.xlabel("Grade")
    plt.ylabel("Number of MPs")

    plt.title(
        "UK MP Financial Integrity Index - Grade Distribution"
    )

    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()

    grades_path = RESULTS_FOLDER / (
        "UK_MP_FINANCIAL_INTEGRITY_GRADES.png"
    )

    plt.savefig(
        grades_path,
        dpi=200
    )

    plt.close()

    # Raw penalty against final score.
    plt.figure(figsize=(12, 7))

    plt.scatter(
        final["Total Raw Penalty"],
        final["Final Score"],
        alpha=0.7
    )

    plt.xlabel("Total Raw Penalty")
    plt.ylabel("Final Score")

    plt.title("Raw Penalty vs Final Score")

    plt.grid(alpha=0.25)
    plt.tight_layout()

    scatter_path = RESULTS_FOLDER / (
        "UK_MP_PENALTY_VS_SCORE.png"
    )

    plt.savefig(
        scatter_path,
        dpi=200
    )

    plt.close()

    print("\nGraphs saved to:")
    print(histogram_path)
    print(grades_path)
    print(scatter_path)


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    print("\n" + "=" * 70)
    print("UK MP FINANCIAL INTEGRITY INDEX")
    print("Registers from", START_DATE, "onwards")
    print("=" * 70)

    # 1. Get MP population.
    members = get_all_mps()

    if len(members) < 400:
        raise RuntimeError(
            "The MP population is too small ("
            + str(len(members))
            + "). The script has stopped."
        )

    # 2. Get published Commons Registers.
    registers = get_registers()

    if not registers:
        raise RuntimeError(
            "No Commons registers were found."
        )

    # 3. Download register CSV data.
    all_data = download_all_register_data(
        registers
    )

    print("\nTotal raw rows:", len(all_data))
    print("Total raw columns:", len(all_data.columns))

    # 4. Score the latest version of each interest.
    scored = score_all_interests(
        all_data
    )

    if scored.empty:
        raise RuntimeError(
            "No interests were successfully scored."
        )

    # 5. Build final MP scores.
    final = build_final_scores(
        scored,
        members
    )

    # 6. Save results.
    save_results(
        members,
        all_data,
        scored,
        final
    )

    # 7. Create graphs.
    make_graphs(final)

    # 8. Final diagnostics.
    print("\n" + "=" * 70)
    print("FINAL DIAGNOSTICS")
    print("=" * 70)

    print("MP population:", len(members))
    print("Registers:", len(registers))
    print("Raw register rows:", len(all_data))
    print("Unique interests scored:", len(scored))
    print("Final MP rows:", len(final))

    print("\nParty distribution:")

    print(
        final["Party"]
        .replace("", "Unknown")
        .fillna("Unknown")
        .value_counts()
        .to_string()
    )

    print("\nCategory distribution:")

    print(
        scored["Category"]
        .value_counts()
        .to_string()
    )

    print("\nGrade distribution:")

    print(
        final["Grade"]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print("\nScore distribution summary:")

    print(
        final["Final Score"].describe()
    )

    print("\nHighest numerical scores:")

    print(
        final[
            [
                "Member",
                "Party",
                "Final Score",
                "Grade",
                "Total Raw Penalty"
            ]
        ].head(20).to_string(index=False)
    )

    print("\nLowest numerical scores:")

    print(
        final[
            [
                "Member",
                "Party",
                "Final Score",
                "Grade",
                "Total Raw Penalty"
            ]
        ].tail(20).to_string(index=False)
    )

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)

    print("\nEverything has been saved to:")
    print(BASE_FOLDER)


if __name__ == "__main__":
    main()
