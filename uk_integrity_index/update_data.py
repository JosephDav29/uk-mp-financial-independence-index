"""Automatically fetch the latest UK Parliament registers and rebuild website data."""
from pathlib import Path
import gzip
import shutil
import sys

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

# Import the existing, tested scoring methodology.
sys.path.insert(0, str(BASE))
import scoring_engine as engine

# Make the engine use the revised grade boundaries even if this file is reused elsewhere.
def grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 50: return "D+"
    if score >= 45: return "D"
    if score >= 40: return "D-"
    return "F"

engine.grade = grade

print("Checking UK Parliament for new Registers of Members' Financial Interests...")
members = engine.get_all_mps()
registers = engine.get_registers()
all_data = engine.download_all_register_data(registers)
scored = engine.score_all_interests(all_data)
final = engine.build_final_scores(scored, members)

# Website data files.
final.to_csv(DATA / "scores.csv", index=False, encoding="utf-8-sig")
with gzip.open(DATA / "interests.csv.gz", "wt", encoding="utf-8", newline="") as f:
    scored.to_csv(f, index=False)

# Save a simple update marker.
latest = max((r["publishedDate"] for r in registers), default="")
(DATA / "last_update.txt").write_text(
    f"Latest Parliament register: {latest}\nRegisters processed: {len(registers)}\n",
    encoding="utf-8"
)

print("\nUPDATE COMPLETE")
print("Registers processed:", len(registers))
print("Latest register:", latest)
print("MPs scored:", len(final))
print("Interests scored:", len(scored))
print("Data written to:", DATA)
