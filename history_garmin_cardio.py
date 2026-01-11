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
TOKEN_DIR = os.path.join(SCRIPT_DIR, ".garth")
SAVE_PATH = os.getenv("SAVE_PATH")
# Rename output file to reflect broader scope
CSV_FILE = os.path.join(SAVE_PATH, "garmin_cardio.csv") if SAVE_PATH else "garmin_cardio.csv"
# Updated Start Date
START_DATE = "2025-12-01" 
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

    print(f"2. Fetching cardio activities (Cycling/Running/etc) from {START_DATE}...")

    # Ensure folder exists
    folder_path = os.path.dirname(CSV_FILE)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # Store all rows in memory to allow full file rewrites (avoids append mode issues)
    all_rows = []
    headers = [
         "Date", "Time", "activityName", "activityType_typeKey",
         "duration", "elapsedDuration", "movingDuration",
         "averageSpeed", "averageHR", "maxHR", "steps",
         "totalAscent", "totalDescent", "distance", # Added useful cardio metrics
         "trainingEffectLabel", "activityTrainingLoad", "minActivityLapDuration",
         "hrTimeInZone_1", "hrTimeInZone_2", "hrTimeInZone_3", "hrTimeInZone_4",
         "avgPower", "maxPower", "normPower"
    ]
    all_rows.append(headers)

    # WRITE HEADERS (Initial file creation)
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(all_rows)

    start = date.fromisoformat(START_DATE)
    end = date.today()
    current = start
    total_saved = 0

    while current < end:
        chunk_end = current + timedelta(days=30)
        if chunk_end > end: chunk_end = end
        
        print(f"   Processing {current} to {chunk_end}...", end="", flush=True)
        
        try:
            # Passing "" as the activity type fetches ALL activities (Cycling, Running, etc.)
            activities = api.get_activities_by_date(current.isoformat(), chunk_end.isoformat(), "")
            
            new_rows = []
            if activities:
                for act in activities:
                    # Filter for Cardio-ish types if needed, or keep all. 
                    # For now, we keep all as requested ("any cardio activity")
                    # Common types: 'cycling', 'running', 'lap_swimming', 'cardio'
                    
                    start_local = act.get('startTimeLocal', '')
                    date_str = start_local[:10]
                    time_str = start_local[11:]
                    
                    # Extract Data
                    title = act.get('activityName', 'Activity')
                    atype_key = act.get('activityType', {}).get('typeKey', 'unknown')
                    
                    dur = act.get('duration', 0)
                    elapsed = act.get('elapsedDuration', 0)
                    moving = act.get('movingDuration', 0)
                    avg_spd = act.get('averageSpeed', 0)
                    avg_hr = act.get('averageHR')
                    max_hr = act.get('maxHR')
                    steps = act.get('steps')
                    
                    # Elevation / Distance (Useful for cycling)
                    ascent = act.get('elevationGain', 0)
                    descent = act.get('elevationLoss', 0)
                    dist = act.get('distance', 0)
                    
                    te_lbl = act.get('trainingEffectLabel')
                    load = act.get('activityTrainingLoad')
                    min_lap = act.get('minActivityLapDuration')
                    
                    # Zones
                    z1 = act.get('hrTimeInZone_1')
                    z2 = act.get('hrTimeInZone_2')
                    z3 = act.get('hrTimeInZone_3')
                    z4 = act.get('hrTimeInZone_4')

                    # Power metrics
                    avg_power = act.get('avgPower')
                    max_power = act.get('maxPower')
                    norm_power = act.get('normPower')

                    new_rows.append([
                        date_str, time_str, title, atype_key,
                        dur, elapsed, moving, avg_spd, avg_hr, max_hr, steps,
                        ascent, descent, dist,
                        te_lbl, load, min_lap, z1, z2, z3, z4,
                        avg_power, max_power, norm_power
                    ])
            
            if new_rows:
                new_rows.sort(key=lambda x: x[0])
                all_rows.extend(new_rows)
                
                # RE-WRITE FULL FILE (Safe for mounted drives)
                with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerows(all_rows)
                    
                print(f" Saved {len(new_rows)}.")
                total_saved += len(new_rows)
            else:
                print(" No data.")

        except Exception as e:
            print(f" Error: {e}")

        current = chunk_end + timedelta(days=1)
        time.sleep(1) 

    print(f"--- COMPLETE. Saved {total_saved} records to {CSV_FILE} ---")

if __name__ == "__main__":
    main()
