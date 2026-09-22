# UK MP FINANCIAL INTEGRITY INDEX
# Full replacement script for Spyder
# Downloads all published Commons Registers from 1 July 2024 onwards,
# builds the MP population, scores interests cumulatively, and saves results.

import os
import re
import zipfile
import shutil
from datetime import datetime
from pathlib import Path

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

for folder in [BASE_FOLDER, RAW_FOLDER, EXTRACTED_FOLDER, RESULTS_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalise_text(value):
    text = clean_text(value).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_empty(value):
    text = normalise_text(value)
    return text in {"", "nan", "none", "null", "n/a", "na", "-", "—"}


def get_request(url, params=None, binary=False):
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "UK-MP-Financial-Integrity-Index/1.0"}
            )
            response.raise_for_status()

            if binary:
                return response.content

            return response.json()

        except Exception as error:
            last_error = error
            print("Request failed, retry", attempt + 1, "of 3:", error)

    raise last_error


def safe_filename(text):
    text = clean_text(text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:150]

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

        data = get_request(MEMBERS_API, request_params)
        items = data.get("items", []) or []
        total = data.get("totalResults", None)

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
    """The Members API returns MemberItem objects containing value."""

    if not isinstance(record, dict):
        return None

    member = record.get("value", record)

    if not isinstance(member, dict):
        return None

    member_id = member.get("id")

    if member_id is None:
        return None

    name = (
        member.get("nameDisplayAs")
        or member.get("nameListAs")
        or member.get("nameFullTitle")
        or "Unknown"
    )

    party = member.get("party") or ""

    return {
        "Mnis Id": int(member_id),
        "Member": clean_text(name),
        "Party": clean_text(party)
    }


def get_all_mps():
    print("\n" + "=" * 70)
    print("GETTING MP POPULATION")
    print("=" * 70)

    print("\nGetting Commons MPs who were members on or after", START_DATE)

    params = {
        "House": 1,
        "MembershipInDateRange.WasMemberOnOrAfter":
            START_DATE + "T00:00:00"
    }

    records = get_members(params)

    members = []

    for record in records:
        member = normalise_member_record(record)
        if member is not None:
            members.append(member)

    # Deduplicate by Parliament member ID.
    unique_members = {}

    for member in members:
        unique_members[member["Mnis Id"]] = member

    members = list(unique_members.values())
    members.sort(key=lambda x: x["Member"].lower())

    print("\nRaw API records:", len(records))
    print("Unique Commons MPs:", len(members))

    if len(members) < 400:
        print("\nWARNING: MP population is unexpectedly small.")
        print("The scoring will NOT be trusted unless this is checked.")

    print("\nFirst 20 MPs:")
    for member in members[:20]:
        print(member["Mnis Id"], "-", member["Member"])

    return members

# ============================================================
# REGISTER LIST
# ============================================================

def get_registers():
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

        data = get_request(REGISTERS_API, params)
        items = data.get("items", []) or []
        total = data.get("totalResults", None)

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
        published = clean_text(register.get("publishedDate"))
        register_type = clean_text(register.get("type"))

        if not published:
            continue

        if published < START_DATE:
            continue

        # We only want the Commons Register, not Commons Staff.
        if register_type.lower() != "commons":
            continue

        registers.append({
            "id": int(register["id"]),
            "publishedDate": published,
            "type": register_type
        })

    registers.sort(key=lambda x: x["publishedDate"])

    print("\nCommons registers from", START_DATE + ":", len(registers))

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
    register_id = register["id"]
    published = register["publishedDate"]

    name = safe_filename(
        str(register_id) + "_" + published
    )

    zip_path = RAW_FOLDER / (name + ".zip")
    extract_path = EXTRACTED_FOLDER / name

    if not zip_path.exists():
        print("\nDownloading register", register_id, published)

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
        print("\nAlready downloaded:", zip_path.name)

    if not extract_path.exists():
        extract_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_path)

    return extract_path


def read_register_csvs(extract_path, register):
    csv_files = list(extract_path.rglob("*.csv"))

    if not csv_files:
        print("WARNING: no CSV files found in", extract_path)
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
            print("Could not read", csv_file.name, ":", error)
            continue

        if df.empty:
            continue

        df["_Register_ID"] = register["id"]
        df["_Register_Date"] = register["publishedDate"]
        df["_Source_File"] = csv_file.name

        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(
        frames,
        ignore_index=True,
        sort=False
    )

    return combined


def download_all_register_data(registers):
    print("\n" + "=" * 70)
    print("DOWNLOADING ALL REGISTERS")
    print("=" * 70)

    all_frames = []

    for number, register in enumerate(registers, start=1):
        print(
            "\nREGISTER",
            number,
            "of",
            len(registers),
            "-",
            register["publishedDate"]
        )

        extract_path = download_register(register)
        df = read_register_csvs(extract_path, register)

        print("Rows read:", len(df))

        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        raise RuntimeError("No register CSV data was downloaded/read.")

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
    lookup = {normalise_text(c): c for c in df.columns}

    for name in possible_names:
        key = normalise_text(name)
        if key in lookup:
            return lookup[key]

    return None


def get_member_id(row):
    for name in ["Mnis Id", "MNIS Id", "Member Id", "Member ID"]:
        if name in row.index:
            value = row[name]
            if not is_empty(value):
                try:
                    return int(float(value))
                except Exception:
                    pass
    return None


def get_member_name(row):
    for name in ["Member", "Member Name", "Name"]:
        if name in row.index:
            value = clean_text(row[name])
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
            value = row[column]
            if not is_empty(value):
                candidates.append(version)

    if candidates:
        return max(candidates)

    # Fallback: find the highest populated Version N field.
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
    """Return ordinary columns plus only the latest Version N values."""

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

            if latest_version is not None and version == latest_version:
                values[base_name] = row[column]

        else:
            values[column_text] = row[column]

    values["_Latest_Version"] = latest_version

    return values


def values_to_text(values):
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
    if value is None or is_empty(value):
        return 0.0

    text = clean_text(value).lower()

    multiplier = 1

    if "million" in text or re.search(r"£\s*[0-9,.]+\s*m\b", text):
        multiplier = 1_000_000
    elif "thousand" in text or re.search(r"£\s*[0-9,.]+\s*k\b", text):
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
        return max(float(x.replace(",", "")) for x in matches) * multiplier
    except Exception:
        return 0.0


def parse_percentage(value):
    if value is None or is_empty(value):
        return 0.0

    text = clean_text(value).replace(",", "")

    match = re.search(r"([0-9]+(?:\.\d+)?)\s*%", text)

    if match:
        return float(match.group(1))

    try:
        number = float(text)
        if 0 <= number <= 1:
            return number * 100
        return number
    except Exception:
        return 0.0


def first_value(values, names):
    lookup = {normalise_text(k): k for k in values.keys()}

    for name in names:
        key = normalise_text(name)
        if key in lookup:
            value = values[lookup[key]]
            if not is_empty(value):
                return value

    return ""


def all_values_text(values):
    return values_to_text(values).lower()

# ============================================================
# CATEGORY DETECTION
# ============================================================

def normalise_category(value):
    text = normalise_text(value)

    # Category number is the safest signal when present.
    match = re.match(r"^(\d+)\b", text)

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
            10: "Miscellaneous",
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
    if "land" in text or "property" in text:
        return "Property"
    if "shareholding" in text or "shares" in text:
        return "Shareholdings"
    if "family" in text:
        return "Family"

    return "Miscellaneous"

# ============================================================
# SCORING RULES
# ============================================================

def cap_penalty(value):
    return min(float(value), 15.0)


def score_donation(values):
    text = all_values_text(values)
    amount = parse_money(first_value(values, [
        "Value", "Amount", "Donation", "Value of Donation",
        "Payment", "Financial Value"
    ]))

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
    elif "company" in text or "limited" in text or " plc" in text:
        score *= 1.5

    return cap_penalty(score)


def score_employment(values):
    text = all_values_text(values)
    amount = parse_money(first_value(values, [
        "Payment", "Payments", "Amount", "Value",
        "Financial Value", "Earnings"
    ]))

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
    amount = parse_money(first_value(values, [
        "Value", "Amount", "Gift Value", "Financial Value"
    ]))

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
    elif "company" in text or "limited" in text or " plc" in text:
        score += 2

    return cap_penalty(score)


def score_overseas(values):
    text = all_values_text(values)
    amount = parse_money(first_value(values, [
        "Value", "Amount", "Visit Value", "Financial Value"
    ]))

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
    elif "company" in text or "limited" in text or " plc" in text:
        score += 2

    return cap_penalty(score)


def score_property(values):
    text = all_values_text(values)

    score = 2

    if "commercial" in text:
        score += 3
    if "development" in text or "developer" in text:
        score += 4
    if "agricultural" in text or "farmland" in text:
        score += 2
    if "land" in text:
        score += 1
    if "rental income" in text or "rent" in text:
        score += 2

    return cap_penalty(score)


def score_shareholding(values):
    text = all_values_text(values)

    percentage = parse_percentage(first_value(values, [
        "Percentage", "Shareholding", "Shares", "Percentage Held"
    ]))

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
    if "company" in text or "limited" in text or " plc" in text:
        score += 1

    return cap_penalty(score)


def score_interest(category, values):
    if category == "Donations":
        return score_donation(values)
    if category == "Employment":
        return score_employment(values)
    if category == "Gifts":
        return score_gift(values)
    if category == "Overseas":
        return score_overseas(values)
    if category == "Property":
        return score_property(values)
    if category == "Shareholdings":
        return score_shareholding(values)
    if category == "Family":
        return score_family(values)
    return score_miscellaneous(values)

# ============================================================
# INTEREST IDENTIFICATION
# ============================================================

def get_interest_id(row):
    for name in [
        "Id",
        "Interest ID",
        "Interest Id",
        "InterestID"
    ]:
        if name in row.index and not is_empty(row[name]):
            try:
                return str(int(float(row[name])))
            except Exception:
                return clean_text(row[name])

    # Fallback fingerprint if the API export has no interest ID.
    member = get_member_id(row)
    category = clean_text(row.get("Category", ""))
    summary = clean_text(row.get("Summary", ""))

    return "fallback|" + str(member) + "|" + category + "|" + summary


def get_fingerprint(values):
    pieces = []

    for key in sorted(values.keys()):
        if key.startswith("_"):
            continue

        value = clean_text(values[key])

        if value:
            pieces.append(
                normalise_text(key) + "=" + normalise_text(value)
            )

    return "|".join(pieces)

# ============================================================
# SCORE ALL INTERESTS CUMULATIVELY
# ============================================================

def score_all_interests(all_data):
    print("\n" + "=" * 70)
    print("SCORING ALL INTERESTS")
    print("=" * 70)

    history = {}
    scored_rows = []

    all_data = all_data.sort_values(
        by=["_Register_Date", "_Register_ID"],
        kind="stable"
    )

    for counter, (_, row) in enumerate(all_data.iterrows(), start=1):

        values = get_latest_values(row)

        member_id = get_member_id(row)
        member_name = get_member_name(row)

        if member_id is None:
            continue

        category_value = first_value(
            values,
            ["Category", "Category Name"]
        )

        category = normalise_category(category_value)

        interest_id = get_interest_id(row)
        fingerprint = get_fingerprint(values)

        if interest_id not in history:
            status = "NEW"
            multiplier = 1.0
        else:
            if history[interest_id] == fingerprint:
                status = "UNCHANGED"
                multiplier = 0.0
            else:
                status = "UPDATED"
                multiplier = 0.25

        normal_penalty = score_interest(category, values)
        applied_penalty = normal_penalty * multiplier

        history[interest_id] = fingerprint

        scored_rows.append({
            "Mnis Id": member_id,
            "Member": member_name,
            "Category": category,
            "Original Category": clean_text(category_value),
            "Interest ID": interest_id,
            "Register ID": row.get("_Register_ID", ""),
            "Register Date": row.get("_Register_Date", ""),
            "Status": status,
            "Normal Interest Penalty": normal_penalty,
            "Applied Cumulative Penalty": applied_penalty,
            "Latest Version": values.get("_Latest_Version", ""),
            "Interest Description": values_to_text(values)
        })

        if counter % 1000 == 0:
            print("Processed", counter, "rows")

    scored = pd.DataFrame(scored_rows)

    return scored

# ============================================================
# TRANSPARENCY / RECTIFICATION
# ============================================================

def calculate_transparency(scored):
    transparency = {}

    for member_id, group in scored.groupby("Mnis Id"):
        rectification_count = 0

        for _, row in group.iterrows():
            text = normalise_text(row.get("Interest Description", ""))

            if "rectif" in text or "correction" in text:
                rectification_count += 1

        transparency[member_id] = rectification_count

    return transparency

# ============================================================
# CONCENTRATION
# ============================================================

def concentration_penalty(category_penalties):
    total = sum(category_penalties.values())

    if total <= 0:
        return 0.0

    largest = max(category_penalties.values())
    share = largest / total

    if share < 0.40:
        return 0.0
    elif share < 0.60:
        return 3.0
    elif share < 0.75:
        return 6.0
    elif share < 0.90:
        return 8.0
    else:
        return 10.0

# ============================================================
# FINAL MP SCORES
# ============================================================

def grade(score):
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
    else:
        return "F"


def build_final_scores(scored, members):
    print("\n" + "=" * 70)
    print("BUILDING FINAL MP SCORES")
    print("=" * 70)

    # Category weights are already reflected in the individual penalties.
    category_names = [
        "Donations",
        "Employment",
        "Gifts",
        "Overseas",
        "Property",
        "Shareholdings",
        "Family",
        "Miscellaneous"
    ]

    rows = []

    transparency = calculate_transparency(scored)

    # Raw cumulative penalties before concentration/transparency.
    raw_by_member = {}

    for member_id, group in scored.groupby("Mnis Id"):
        category_totals = {
            category: float(
                group.loc[
                    group["Category"] == category,
                    "Applied Cumulative Penalty"
                ].sum()
            )
            for category in category_names
        }

        raw_total = sum(category_totals.values())

        raw_by_member[member_id] = {
            "category_totals": category_totals,
            "raw_total": raw_total
        }

    positive_raw = [
        x["raw_total"]
        for x in raw_by_member.values()
        if x["raw_total"] > 0
    ]

    if positive_raw:
        K = float(np.median(positive_raw))
    else:
        K = 1.0

    if K <= 0:
        K = 1.0

    print("Median positive raw penalty K =", round(K, 4))

    member_lookup = {
        member["Mnis Id"]: member
        for member in members
    }

    for member_id, member in member_lookup.items():
        if member_id in raw_by_member:
            category_totals = raw_by_member[member_id]["category_totals"]
            raw_total = raw_by_member[member_id]["raw_total"]
        else:
            category_totals = {category: 0.0 for category in category_names}
            raw_total = 0.0

        concentration = concentration_penalty(category_totals)

        rectification_count = transparency.get(member_id, 0)
        transparency_penalty = 5.0 if rectification_count > 0 else 0.0

        total_raw_penalty = (
            raw_total
            + concentration
            + transparency_penalty
        )

        # Continuous 0-100 transformation.
        score = 100.0 / (1.0 + total_raw_penalty / K)
        score = max(0.0, min(100.0, score))

        row = {
            "Mnis Id": member_id,
            "Member": member["Member"],
            "Party": member.get("Party", ""),
        }

        for category in category_names:
            row[category + " Penalty"] = category_totals[category]

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

    # Sort by score for analysis, but this is simply the output of the
    # specified scoring formula rather than a political recommendation.
    final = final.sort_values(
        ["Final Score", "Member"],
        ascending=[False, True]
    ).reset_index(drop=True)

    return final

# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(members, all_data, scored, final):
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

    population_df.to_csv(population_path, index=False, encoding="utf-8-sig")
    scored.to_csv(interest_path, index=False, encoding="utf-8-sig")
    final.to_csv(final_path, index=False, encoding="utf-8-sig")

    # Raw data can be large, but saving it makes the calculation auditable.
    all_data.to_csv(raw_path, index=False, encoding="utf-8-sig")

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
    print("\nCreating graphs...")

    # Histogram of continuous scores.
    plt.figure(figsize=(12, 7))
    plt.hist(
        final["Final Score"],
        bins=25,
        edgecolor="black"
    )
    plt.xlabel("Final Score")
    plt.ylabel("Number of MPs")
    plt.title("UK MP Financial Integrity Index - Score Distribution")
    plt.xlim(0, 100)
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    histogram_path = RESULTS_FOLDER / (
        "UK_MP_FINANCIAL_INTEGRITY_DISTRIBUTION.png"
    )
    plt.savefig(histogram_path, dpi=200)
    plt.close()

    # Grade distribution.
    grade_order = [
        "A+", "A", "A-", "B+", "B", "B-",
        "C+", "C", "C-", "D+", "D", "D-", "F"
    ]

    counts = final["Grade"].value_counts()
    grade_counts = [counts.get(g, 0) for g in grade_order]

    plt.figure(figsize=(12, 7))
    plt.bar(grade_order, grade_counts)
    plt.xlabel("Grade")
    plt.ylabel("Number of MPs")
    plt.title("UK MP Financial Integrity Index - Grade Distribution")
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    grades_path = RESULTS_FOLDER / (
        "UK_MP_FINANCIAL_INTEGRITY_GRADES.png"
    )
    plt.savefig(grades_path, dpi=200)
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
    plt.savefig(scatter_path, dpi=200)
    plt.close()

    print("Graphs saved to:")
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

    # --------------------------------------------------------
    # 1. Get population first.
    # --------------------------------------------------------
    members = get_all_mps()

    if len(members) < 400:
        raise RuntimeError(
            "The MP population is too small (" +
            str(len(members)) +
            "). The script has stopped before scoring."
        )

    # --------------------------------------------------------
    # 2. Get every published Commons Register.
    # --------------------------------------------------------
    registers = get_registers()

    if not registers:
        raise RuntimeError("No Commons registers were found.")

    # --------------------------------------------------------
    # 3. Download every register and read every CSV.
    # --------------------------------------------------------
    all_data = download_all_register_data(registers)

    print("\nTotal raw rows:", len(all_data))
    print("Total raw columns:", len(all_data.columns))

    # --------------------------------------------------------
    # 4. Score every interest across every register.
    # --------------------------------------------------------
    scored = score_all_interests(all_data)

    if scored.empty:
        raise RuntimeError("No interests were successfully scored.")

    # --------------------------------------------------------
    # 5. Aggregate cumulatively by MP.
    # --------------------------------------------------------
    final = build_final_scores(scored, members)

    # --------------------------------------------------------
    # 6. Save everything.
    # --------------------------------------------------------
    save_results(
        members,
        all_data,
        scored,
        final
    )

    # --------------------------------------------------------
    # 7. Graphs.
    # --------------------------------------------------------
    make_graphs(final)

    # --------------------------------------------------------
    # 8. Print useful diagnostics.
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("FINAL DIAGNOSTICS")
    print("=" * 70)

    print("MP population:", len(members))
    print("Registers:", len(registers))
    print("Raw register rows:", len(all_data))
    print("Scored interest rows:", len(scored))
    print("Final MP rows:", len(final))
    print("\nGrade distribution:")
    print(final["Grade"].value_counts().sort_index())

    print("\nScore distribution summary:")
    print(final["Final Score"].describe())

    print("\nHighest numerical scores under the specified formula:")
    print(
        final[
            ["Member", "Party", "Final Score", "Grade", "Total Raw Penalty"]
        ].head(20).to_string(index=False)
    )

    print("\nLowest numerical scores under the specified formula:")
    print(
        final[
            ["Member", "Party", "Final Score", "Grade", "Total Raw Penalty"]
        ].tail(20).to_string(index=False)
    )

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print("\nEverything has been saved to:")
    print(BASE_FOLDER)


if __name__ == "__main__":
    main()
