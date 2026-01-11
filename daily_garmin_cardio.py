import garth
from garminconnect import Garmin
from datetime import date, timedelta
import csv
import os
import sys
import platform
import json
from dotenv import load_dotenv

# 1. Load configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

# 2. Platform-Aware Safety Check
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
SAVE_PATH = os.getenv("SAVE_PATH")
# Match the history file
CSV_FILE = os.path.join(SAVE_PATH, "garmin_cardio.csv") if SAVE_PATH else "garmin_cardio.csv"
TOKEN_DIR = os.path.join(SCRIPT_DIR, ".garth")
# ---------------------

def safe_get(data, key, default=None):
    return data.get(key, default)

def main():
    # 1. Read Existing Data
    existing_rows = []
    existing_ids = set()
    
    folder_path = os.path.dirname(CSV_FILE)
    if folder_path and not os.path.exists(folder_path):
        os.makedirs(folder_path)

    if os.path.isfile(CSV_FILE):
        try:
            with open(CSV_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None) # Save header
                if header:
                    existing_rows.append(header)
                
                for row in reader:
                    if len(row) > 1:
                        existing_rows.append(row)
                        # Composite Key: Date_Time
                        existing_ids.add(f"{row[0]}_{row[1]}")
        except Exception as e:
            print(f"Warning reading existing file: {e}")

    # 2. Login
    try:
        garth.resume(TOKEN_DIR)
        api = Garmin("dummy", "dummy")
        api.garth = garth.client
    except Exception as e:
        print(f"Login Error: {e}")
        return

    # 3. Check Last 5 Days
    today = date.today()
    start_check = today - timedelta(days=5)
    
    print(f"Checking cardio activities from {start_check}...")

    try:
        activities = api.get_activities_by_date(start_check.isoformat(), today.isoformat(), "")
        
        new_activities_found = False
        
        if activities:
            for act in activities:
                start_local = act.get('startTimeLocal', '')
                date_str = start_local[:10]
                time_str = start_local[11:]
                
                sig = f"{date_str}_{time_str}"
                if sig in existing_ids:
                    continue

                # --- FIELD EXTRACTION ---
                title = act.get('activityName', 'Activity')
                atype_key = act.get('activityType', {}).get('typeKey', 'unknown')
                
                dur = act.get('duration', 0)
                elapsed = act.get('elapsedDuration', 0)
                moving = act.get('movingDuration', 0)
                
                avg_spd = act.get('averageSpeed', 0)
                avg_hr = act.get('averageHR')
                max_hr = act.get('maxHR')
                steps = act.get('steps')
                
                ascent = act.get('elevationGain', 0)
                descent = act.get('elevationLoss', 0)
                dist = act.get('distance', 0)
                
                te_label = act.get('trainingEffectLabel')
                load = act.get('activityTrainingLoad')
                min_lap = act.get('minActivityLapDuration')

                z1 = act.get('hrTimeInZone_1')
                z2 = act.get('hrTimeInZone_2')
                z3 = act.get('hrTimeInZone_3')
                z4 = act.get('hrTimeInZone_4')

                # Power metrics
                avg_power = act.get('avgPower')
                max_power = act.get('maxPower')
                norm_power = act.get('normPower')

                new_row = [
                    date_str, time_str, title, atype_key,
                    dur, elapsed, moving, avg_spd, avg_hr, max_hr, steps,
                    ascent, descent, dist,
                    te_label, load, min_lap, z1, z2, z3, z4,
                    avg_power, max_power, norm_power
                ]
                
                existing_rows.append(new_row)
                new_activities_found = True

        if new_activities_found:
            # Sort by date (first column) to keep it tidy, skipping header if present
            header_row = None
            data_rows = []
            
            if existing_rows:
                if existing_rows[0][0] == "Date":
                    header_row = existing_rows[0]
                    data_rows = existing_rows[1:]
                else:
                    data_rows = existing_rows
            
            # Sort data rows
            data_rows.sort(key=lambda x: x[0])
            
            # Reassemble
            final_rows = []
            if header_row:
                final_rows.append(header_row)
            else:
                # Add default header if missing
                final_rows.append([
                     "Date", "Time", "activityName", "activityType_typeKey",
                     "duration", "elapsedDuration", "movingDuration",
                     "averageSpeed", "averageHR", "maxHR", "steps",
                     "totalAscent", "totalDescent", "distance",
                     "trainingEffectLabel", "activityTrainingLoad", "minActivityLapDuration",
                     "hrTimeInZone_1", "hrTimeInZone_2", "hrTimeInZone_3", "hrTimeInZone_4",
                     "avgPower", "maxPower", "normPower"
                 ])
            final_rows.extend(data_rows)

            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(final_rows)
            print(f"SUCCESS: Database updated.")
        else:
            print("No new activities found.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
