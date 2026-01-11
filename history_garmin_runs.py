import garth
from garminconnect import Garmin
from datetime import date, timedelta
import csv
import os
import sys
import platform
import json
import time
from dotenv import load_dotenv

# 1. Load configuration
load_dotenv()

# 2. Platform-Aware Safety Check
# On Raspberry Pi/Linux: Set CHECK_MOUNT_STATUS=True in .env to enable mount verification
# On Windows: Mount check is automatically skipped (unless explicitly enabled)
check_mount = os.getenv("CHECK_MOUNT_STATUS", "False").lower() == "true"
drive_path = os.getenv("DRIVE_MOUNT_PATH", "/home/pi/google_drive")
is_windows = platform.system() == "Windows"

if check_mount and not is_windows:
    print(f"Safety Check: Verifying mount at {drive_path}...")
    if not os.path.ismount(drive_path):
        print(f"CRITICAL ERROR: Drive is not mounted at {drive_path}.")
        print("Stopping script to prevent writing to local storage.")
        sys.exit(1)
    else:
        print("Safety Check: PASSED. Drive is mounted.")
elif check_mount and is_windows:
    print("Note: Mount check skipped on Windows (not applicable).")

# --- CONFIGURATION ---
TOKEN_DIR = ".garth"
SAVE_PATH = os.getenv("SAVE_PATH")
CSV_FILE = os.path.join(SAVE_PATH, "garmin_runs.csv") if SAVE_PATH else "garmin_runs.csv"
DEFAULT_START_DATE = "2024-08-08"

# Try to read start date from .env first, then use default
START_DATE = os.getenv("GARMIN_START_DATE", DEFAULT_START_DATE)
FORCE_MODE = False

# Parse command line arguments (command-line overrides .env)
# Usage: python history_garmin_runs.py [start_date] [--force]
#   start_date: Optional start date (overrides .env GARMIN_START_DATE)
#   --force: Overwrite existing data with fresh Garmin data (re-sync all)
for arg in sys.argv[1:]:
    if arg == "--force":
        FORCE_MODE = True
        print("FORCE MODE: Will overwrite existing data with fresh Garmin data")
    elif not arg.startswith("-"):
        START_DATE = arg
        print(f"Using command-line start date: {START_DATE}")
# ---------------------

def main():
    print("1. Loading tokens...")
    garth.resume(TOKEN_DIR)
    api = Garmin("dummy", "dummy")
    api.garth = garth.client
    try:
        api.display_name = api.garth.profile['displayName']
    except:
        pass

    print(f"2. Fetching runs from {START_DATE}...")

    # Ensure folder exists
    folder_path = os.path.dirname(CSV_FILE)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # Load existing data
    existing_dates = set()
    existing_rows = []

    if os.path.isfile(CSV_FILE):
        try:
            with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                for row in reader:
                    if row:
                        date_str = row[0]
                        time_str = row[1] if len(row) > 1 else ""
                        existing_dates.add((date_str, time_str))
                        existing_rows.append(row)
            if FORCE_MODE:
                print(f"   Found {len(existing_rows)} existing records (will overwrite)")
                existing_rows = []  # Clear existing data in force mode
                existing_dates = set()
            else:
                print(f"   Found {len(existing_rows)} existing records (will preserve)")
        except Exception as e:
            print(f"   Warning: Could not read existing file: {e}")

    start = date.fromisoformat(START_DATE)
    end = date.today()
    current = start
    total_new = 0
    all_rows = list(existing_rows)  # Start with existing data

    while current < end:
        chunk_end = current + timedelta(days=30)
        if chunk_end > end: chunk_end = end

        print(f"   Processing {current} to {chunk_end}...", end="", flush=True)
        chunk_added = 0

        try:
            activities = api.get_activities_by_date(current.isoformat(), chunk_end.isoformat(), "running")

            if activities:
                for act in activities:
                    start_local = act.get('startTimeLocal', '')
                    date_str = start_local[:10]
                    time_str = start_local[11:]

                    # Extract Data
                    title = act.get('activityName', 'Run')
                    atype_key = act.get('activityType', {}).get('typeKey', 'running')

                    dur = act.get('duration', 0)
                    elapsed = act.get('elapsedDuration', 0)
                    moving = act.get('movingDuration', 0)
                    avg_spd = act.get('averageSpeed', 0)
                    avg_hr = act.get('averageHR')
                    max_hr = act.get('maxHR')
                    steps = act.get('steps')

                    # Sets/Reps (JSON dump complex lists)
                    summ_sets = json.dumps(act.get('summarizedExerciseSets', []))
                    t_sets = act.get('totalSets')
                    a_sets = act.get('activeSets')
                    t_reps = act.get('totalReps')

                    te_lbl = act.get('trainingEffectLabel')
                    load = act.get('activityTrainingLoad')
                    min_lap = act.get('minActivityLapDuration')

                    # Zones
                    z1 = act.get('hrTimeInZone_1')
                    z2 = act.get('hrTimeInZone_2')
                    z3 = act.get('hrTimeInZone_3')
                    z4 = act.get('hrTimeInZone_4')

                    # Skip if already exists (unless force mode)
                    if (date_str, time_str) in existing_dates:
                        continue

                    all_rows.append([
                        date_str, time_str, title, atype_key,
                        dur, elapsed, moving, avg_spd, avg_hr, max_hr, steps,
                        summ_sets, t_sets, a_sets, t_reps,
                        te_lbl, load, min_lap, z1, z2, z3, z4
                    ])
                    chunk_added += 1
                    total_new += 1

                print(f" Found {len(activities)}, added {chunk_added} new.")
            else:
                print(" No data.")

        except Exception as e:
            print(f" Error: {e}")

        current = chunk_end + timedelta(days=1)
        time.sleep(1)

    # Write all data sorted newest to oldest
    if all_rows:
        all_rows.sort(key=lambda x: (x[0], x[1]), reverse=True)  # Sort by date, then time descending
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Time", "activityName", "activityType_typeKey",
                "duration", "elapsedDuration", "movingDuration",
                "averageSpeed", "averageHR", "maxHR", "steps",
                "summarizedExerciseSets", "totalSets", "activeSets", "totalReps",
                "trainingEffectLabel", "activityTrainingLoad", "minActivityLapDuration",
                "hrTimeInZone_1", "hrTimeInZone_2", "hrTimeInZone_3", "hrTimeInZone_4"
            ])
            writer.writerows(all_rows)
        print(f"   Written {len(all_rows)} total records (sorted newest to oldest).")

    print(f"--- COMPLETE. Added {total_new} new records. ---")

if __name__ == "__main__":
    main()
