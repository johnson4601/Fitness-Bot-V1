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

# Accept start date from command line argument (e.g., python history_hevy_import.py 2023-01-01)
DEFAULT_START_DATE = "2023-01-01"
if len(sys.argv) > 1:
    START_DATE = sys.argv[1]
    print(f"Using command-line start date: {START_DATE}")
else:
    START_DATE = DEFAULT_START_DATE

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
            
    # 2. Write Headers (if file is new)
    file_exists = os.path.isfile(CSV_FILE)
    if not file_exists:
        try:
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Workout", "Exercise", "Set", "Weight (lbs)", "Reps", "RPE", "Type"])
        except Exception as e:
            print(f"Error creating file: {e}")
            return

    page = 1
    total_sets = 0
    keep_going = True
    all_new_rows = []  # Collect all rows first

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

                w_dt = datetime.fromisoformat(w_date_str).replace(tzinfo=None)

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

            if page_rows:
                all_new_rows.extend(page_rows)
                print(f" Found {len(page_rows)} sets.")
                total_sets += len(page_rows)
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
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(all_new_rows)
        print(f"Saved {total_sets} sets (sorted newest to oldest).")

    print(f"--- COMPLETE. Total Sets Saved: {total_sets} ---")

if __name__ == "__main__":
    main()