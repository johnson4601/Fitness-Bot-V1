import requests
import csv
import os
import time
from datetime import datetime
from dotenv import load_dotenv  # <--- Loads the secret file

import os
import sys
import platform
from dotenv import load_dotenv

# 1. Load configuration immediately
load_dotenv()

# 2. Get the settings (with defaults for safety)
# On Raspberry Pi/Linux: Set CHECK_MOUNT_STATUS=True in .env to enable mount verification
# On Windows: Mount check is automatically skipped (unless explicitly enabled)
check_mount = os.getenv("CHECK_MOUNT_STATUS", "False").lower() == "true"
drive_path = os.getenv("DRIVE_MOUNT_PATH", "/home/pi/google_drive")

# 3. Platform-Aware Safety Check
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

# ... rest of your code ...

# --- CONFIGURATION VIA ENVIRONMENT ---
# 1. Load the secrets
load_dotenv()

# 2. Get variables safely
API_KEY = os.getenv("HEVY_API_KEY")
SAVE_PATH = os.getenv("SAVE_PATH")

# 3. Construct the path
if SAVE_PATH:
    CSV_FILE = os.path.join(SAVE_PATH, "hevy_stats.csv")
else:
    print("WARNING: SAVE_PATH not set in .env. Using current folder.")
    CSV_FILE = "hevy_stats.csv"

# Parse command line arguments
# Usage: python history_hevy_import.py [start_date] [--force]
#   start_date: Optional start date (default: 2023-01-01)
#   --force: Overwrite existing data with fresh Hevy data (re-sync all)
DEFAULT_START_DATE = "2023-01-01"
START_DATE = DEFAULT_START_DATE
FORCE_MODE = False

for arg in sys.argv[1:]:
    if arg == "--force":
        FORCE_MODE = True
        print("FORCE MODE: Will overwrite existing data with fresh Hevy data")
    elif not arg.startswith("-"):
        START_DATE = arg
        print(f"Using command-line start date: {START_DATE}")

# Extract year for API filtering, but also use full date for precise filtering
START_YEAR = int(START_DATE.split('-')[0])
START_DATE_OBJ = datetime.fromisoformat(START_DATE)
# -------------------------------------

def main():
    # Safety Check
    if not API_KEY:
        print("CRITICAL ERROR: 'HEVY_API_KEY' not found in .env file.")
        return

    headers = {
        "api-key": API_KEY,
        "Accept": "application/json"
    }
    
    print(f"--- STARTING HEVY HISTORY PULL (Since {START_YEAR}) ---")
    print(f"Target File: {CSV_FILE}")
    
    # 1. Create Folder if Missing (Robustness)
    folder_path = os.path.dirname(CSV_FILE)
    if folder_path and not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            print(f"Created new folder: {folder_path}")
        except Exception as e:
            print(f"Error creating folder: {e}")
            # We continue anyway, in case it's a root drive issue
            
    # 2. Load existing data
    file_exists = os.path.isfile(CSV_FILE)
    existing_entries = set()
    existing_rows = []

    if file_exists:
        try:
            with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                _csv_header = next(reader, None)  # Skip header row
                for row in reader:
                    if row:
                        # Create unique key: date, workout, exercise, set number
                        key = (row[0], row[1], row[2], row[3])
                        existing_entries.add(key)
                        existing_rows.append(row)
            if FORCE_MODE:
                print(f"   Found {len(existing_rows)} existing records (will overwrite)")
                existing_rows = []
                existing_entries = set()
            else:
                print(f"   Found {len(existing_rows)} existing records (will preserve)")
        except Exception as e:
            print(f"   Warning: Could not read existing file: {e}")
    else:
        try:
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Workout", "Exercise", "Set", "Weight (lbs)", "Reps", "RPE", "Type"])
        except Exception as e:
            print(f"Error creating file: {e}")
            return

    page = 1
    total_new = 0
    keep_going = True
    all_new_rows = list(existing_rows)  # Start with existing data

    # 3. Fetch Loop
    while keep_going:
        print(f"Fetching Page {page}...", end="", flush=True)

        url = "https://api.hevyapp.com/v1/workouts"
        params = {"page": page, "pageSize": 10}

        try:
            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                print(f"\nCRITICAL ERROR: {response.status_code}")
                print(f"Server Message: {response.text}")
                break

            data = response.json()
            workouts = data.get('workouts', [])

            if not workouts:
                print(" No more workouts found. Done.")
                break

            page_rows = []

            for workout in workouts:
                w_date_str = workout.get('start_time')
                if not w_date_str: continue

                # Convert UTC to local time before extracting the date
                w_dt = datetime.fromisoformat(w_date_str).astimezone().replace(tzinfo=None)

                # Check Date Limit (stop if before start date)
                if w_dt < START_DATE_OBJ:
                    print(f"\nReached {w_dt.date()}. Stopping (before {START_DATE}).")
                    keep_going = False
                    break

                w_date_clean = w_dt.strftime("%Y-%m-%d")
                w_title = workout.get('title', 'Unknown Workout')

                exercises = workout.get('exercises', [])
                for exercise in exercises:
                    ex_name = exercise.get('title', 'Unknown Exercise')
                    sets = exercise.get('sets', [])

                    for i, s in enumerate(sets):
                        # SAFE GETS
                        weight_kg = s.get('weight_kg', 0)
                        weight_lbs = round(weight_kg * 2.20462, 1) if weight_kg else 0
                        reps = s.get('reps', 0)
                        s_type = s.get('type', 'normal')

                        # Skip if already exists (unless force mode)
                        key = (w_date_clean, w_title, ex_name, str(i + 1))
                        if key in existing_entries:
                            continue

                        row = [
                            w_date_clean,
                            w_title,
                            ex_name,
                            i + 1,
                            weight_lbs,
                            reps,
                            s.get('rpe', ''),
                            s_type
                        ]
                        page_rows.append(row)
                        total_new += 1

            if page_rows:
                all_new_rows.extend(page_rows)
                print(f" Found {len(page_rows)} new sets.")
            else:
                print(" (Page empty).")

            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"\nGlobal Error: {e}")
            break

    # 4. Save to CSV (sorted newest to oldest)
    if all_new_rows:
        # Sort by date descending (newest first)
        all_new_rows.sort(key=lambda x: x[0], reverse=True)
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Workout", "Exercise", "Set", "Weight (lbs)", "Reps", "RPE", "Type"])
            writer.writerows(all_new_rows)
        print(f"   Written {len(all_new_rows)} total records (sorted newest to oldest).")

    print(f"--- COMPLETE. Added {total_new} new records. ---")

if __name__ == "__main__":
    main()