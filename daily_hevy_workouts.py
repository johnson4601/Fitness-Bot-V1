import requests
import csv
import os
from datetime import datetime, timedelta
import sys
import platform
import traceback
from dotenv import load_dotenv

# 1. Load configuration immediately
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

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

# --- CONFIGURATION VIA ENVIRONMENT ---
# 1. (Already loaded above via absolute path)

# 2. Get variables safely
API_KEY = os.getenv("HEVY_API_KEY")
SAVE_PATH = os.getenv("SAVE_PATH")

# 3. Construct the full file path
# This joins the folder path from .env with the filename
if SAVE_PATH:
    CSV_FILE = os.path.join(SAVE_PATH, "hevy_stats.csv")
else:
    # Fallback if someone forgets to set the .env
    print("WARNING: SAVE_PATH not found in .env. Using current directory.")
    CSV_FILE = "hevy_stats.csv"
# -------------------------------------

def main():
    print("DEBUG: Starting script...", flush=True)
    
    # Safety Check: Did the user actually set the key?
    if not API_KEY:
        print("CRITICAL ERROR: 'HEVY_API_KEY' not found. Please create a .env file.", flush=True)
        return

    print(f"DEBUG: API Key found (Length: {len(API_KEY)})", flush=True)

    headers = {
        "api-key": API_KEY,
        "Accept": "application/json"
    }
    
    # 1. READ EXISTING DATA (Smart Deduplication & Full Load)
    existing_sets = set()
    all_rows = []
    
    # Check if directory exists first
    folder = os.path.dirname(CSV_FILE)
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
            print(f"Created directory: {folder}")
        except OSError:
            pass # Drive might not be mounted yet

    if os.path.isfile(CSV_FILE):
        try:
            with open(CSV_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                file_header = next(reader, None) # Skip header
                if file_header:
                    all_rows.append(file_header) # Keep header
                
                for row in reader:
                    if len(row) > 3:
                        all_rows.append(row)
                        # Signature: Date_Workout_Exercise_Set
                        signature = f"{row[0]}_{row[1]}_{row[2]}_{row[3]}"
                        existing_sets.add(signature)
        except Exception as e:
            print(f"Warning reading file: {e}")
    else:
        # Default header if file doesn't exist
        all_rows.append(["Date", "Workout", "Exercise", "Set", "Weight (lbs)", "Reps", "RPE", "Type"])

    # 2. FETCH RECENT WORKOUTS
    cutoff_date = datetime.now() - timedelta(days=2)
    print(f"Checking Hevy for workouts since {cutoff_date.date()}...")
    
    url = "https://api.hevyapp.com/v1/workouts"
    params = {"page": 1, "pageSize": 10}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return

        data = response.json()
        workouts = data.get('workouts', [])
        
        print(f"DEBUG: Found {len(workouts)} workouts in API response.")
        
        if not workouts:
            print("No workouts found.")
            return

        new_rows = []
        skipped_count = 0
        
        for workout in workouts:
            w_date_str = workout.get('start_time')
            if not w_date_str: 
                print("DEBUG: Skipping workout (no start_time)")
                continue

            w_dt = datetime.fromisoformat(w_date_str).replace(tzinfo=None)
            
            # DEBUG
            # print(f"DEBUG: Checking workout '{workout.get('title')}' on {w_dt} (Cutoff: {cutoff_date})")
            
            if w_dt < cutoff_date:
                # print("DEBUG: Too old.")
                continue
            
            w_date_clean = w_dt.strftime("%Y-%m-%d")
            w_title = workout.get('title', 'Unknown Workout')

            for exercise in workout.get('exercises', []):
                ex_name = exercise.get('title', 'Unknown')
                
                for i, s in enumerate(exercise.get('sets', [])):
                    set_num = str(i + 1)

                    signature = f"{w_date_clean}_{w_title}_{ex_name}_{set_num}"

                    if signature in existing_sets:
                        skipped_count += 1
                        continue

                    weight_kg = s.get('weight_kg', 0)
                    weight_lbs = round(weight_kg * 2.20462, 1) if weight_kg else 0
                    reps = s.get('reps', 0)

                    row = [
                        w_date_clean,
                        w_title,
                        ex_name,
                        set_num,
                        weight_lbs,
                        reps,
                        s.get('rpe', ''),
                        s.get('type', 'normal')
                    ]
                    new_rows.append(row)

        # 3. SAVE (Write Full File to avoid Append issues)
        if new_rows:
            all_rows.extend(new_rows)
            # Optional: Sort by date
            # header = all_rows[0]
            # data = all_rows[1:]
            # data.sort(key=lambda x: x[0])
            # all_rows = [header] + data

            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(all_rows)
            print(f"SUCCESS: Added {len(new_rows)} new sets. (Skipped {skipped_count} duplicates)")
        else:
            print(f"No *new* sets found. (Skipped {skipped_count} duplicates)")

    except Exception as e:
        traceback.print_exc()
        print(f"Error: {e}")

if __name__ == "__main__":
    main()