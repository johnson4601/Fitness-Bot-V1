import garth
from garminconnect import Garmin
from datetime import date, timedelta, datetime
import csv
import os
import time
import random

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
SAVE_PATH = os.getenv("SAVE_PATH")

if SAVE_PATH:
    CSV_FILE = os.path.join(SAVE_PATH, "garmin_stats.csv")
else:
    print("WARNING: SAVE_PATH not set in .env. Using current folder.")
    CSV_FILE = "garmin_stats.csv"

TOKEN_DIR = ".garth"
DEFAULT_START_DATE = "2024-08-08"

# Try to read start date from .env first, then use default
START_DATE = os.getenv("GARMIN_START_DATE", DEFAULT_START_DATE)
BACKFILL_MODE = False
FORCE_MODE = False

# Parse command line arguments (command-line overrides .env)
# Usage: python history_garmin_import.py [start_date] [--backfill] [--force]
#   start_date: Optional start date (overrides .env GARMIN_START_DATE)
#   --backfill: Update existing rows with missing data (e.g., new columns like BP)
#   --force: Overwrite existing data with fresh Garmin data (re-sync all)
for arg in sys.argv[1:]:
    if arg == "--backfill":
        BACKFILL_MODE = True
        print("BACKFILL MODE: Will update existing rows with missing data")
    elif arg == "--force":
        FORCE_MODE = True
        print("FORCE MODE: Will overwrite existing data with fresh Garmin data")
    elif not arg.startswith("-"):
        START_DATE = arg
        print(f"Using command-line start date: {START_DATE}")
# ---------------------

def get_safe(data, *keys):
    try:
        for key in keys:
            data = data[key]
        return data
    except (KeyError, TypeError, AttributeError):
        return None

def main():
    # 1. Login
    try:
        garth.resume(TOKEN_DIR)
        api = Garmin("dummy", "dummy")
        api.garth = garth.client
        try:
            api.display_name = api.garth.profile['displayName']
        except:
            pass
    except Exception as e:
        print(f"Login failed: {e}")
        return

    # 2. Setup Date Loop
    start = date.fromisoformat(START_DATE)
    end = date.today() - timedelta(days=1) # Stop at yesterday (daily script handles today)
    delta = timedelta(days=1)
    
    current_date = start
    
    print(f"--- STARTING HISTORY PULL ---")
    print(f"From {start} to {end}")
    print("Press Ctrl+C to stop at any time.")
    
    # 3. Create CSV Header
    headers = [
        "Date",
        "Weight (lbs)", "Muscle Mass (lbs)", "Body Fat %", "Water %",
        "Sleep Total (hr)", "Sleep Deep (hr)", "Sleep REM (hr)", "Sleep Score",
        "RHR", "Min HR", "Max HR", "Avg Stress", "Respiration", "SpO2",
        "VO2 Max", "Training Status", "HRV Status", "HRV Avg",
        "BP Systolic", "BP Diastolic",
        "Steps", "Step Goal", "Cals Total", "Cals Active",
        "Activities"
    ]
    
    # Load existing data
    existing_dates = set()
    existing_data = {}  # For backfill/force mode: {date_str: row_list}

    def normalize_date(date_str):
        """Normalize date to ISO format"""
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                month, day, year = parts
                return f"{year}-{int(month):02d}-{int(day):02d}"
        return date_str

    if os.path.isfile(CSV_FILE):
        try:
            with open(CSV_FILE, mode='r', newline='') as f:
                reader = csv.reader(f)
                file_headers = next(reader, None)  # Read actual headers from file

                # Build column mapping: old position -> new position
                col_mapping = {}
                if file_headers:
                    for old_idx, col_name in enumerate(file_headers):
                        if col_name in headers:
                            new_idx = headers.index(col_name)
                            col_mapping[old_idx] = new_idx

                for row in reader:
                    if row:
                        date_str = normalize_date(row[0])
                        existing_dates.add(date_str)
                        if BACKFILL_MODE or FORCE_MODE:
                            # Remap columns to match new header order
                            new_row = [''] * len(headers)
                            for old_idx, value in enumerate(row):
                                if old_idx in col_mapping:
                                    new_row[col_mapping[old_idx]] = value
                            existing_data[date_str] = new_row
            if FORCE_MODE:
                print(f"Found {len(existing_dates)} existing dates (will overwrite with fresh data)")
            elif BACKFILL_MODE:
                print(f"Found {len(existing_dates)} existing dates (will update missing values)")
            else:
                print(f"Found {len(existing_dates)} existing dates in file (will skip)")
        except Exception as e:
            print(f"Warning: Could not read existing file: {e}")
    else:
        with open(CSV_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    # 4. The Loop
    while current_date <= end:
        day_str = current_date.isoformat()

        # Skip if date already exists (unless backfill or force mode)
        if day_str in existing_dates and not BACKFILL_MODE and not FORCE_MODE:
            print(f"Skipping {day_str} (already exists)")
            current_date += delta
            continue

        if FORCE_MODE and day_str in existing_dates:
            print(f"Refreshing {day_str}...", end="", flush=True)
        elif BACKFILL_MODE and day_str in existing_dates:
            print(f"Backfilling {day_str}...", end="", flush=True)
        else:
            print(f"Processing {day_str}...", end="", flush=True)

        try:
            # --- FETCH DATA (Same logic as Daily Script) ---
            # Core
            try:
                user_stats = api.get_user_summary(day_str)
                rhr = get_safe(user_stats, 'restingHeartRate')
                min_hr = get_safe(user_stats, 'minHeartRate')
                max_hr = get_safe(user_stats, 'maxHeartRate')
                stress = get_safe(user_stats, 'averageStressLevel')
                steps = get_safe(user_stats, 'totalSteps')
                vo2 = get_safe(user_stats, 'vo2Max')
                spo2 = get_safe(user_stats, 'averageSpO2')
                resp = get_safe(user_stats, 'averageRespirationValue')
                cals_tot = get_safe(user_stats, 'totalKilocalories')
                cals_act = get_safe(user_stats, 'activeKilocalories')
                cals_goal = get_safe(user_stats, 'dailyStepGoal')
            except:
                rhr, min_hr, max_hr, stress, steps, vo2, spo2, resp, cals_tot, cals_act, cals_goal = [None]*11

            # SpO2 fallback - try dedicated endpoint if not in user summary
            if spo2 is None:
                try:
                    spo2_data = api.get_spo2_data(day_str)
                    if spo2_data:
                        spo2 = get_safe(spo2_data, 'averageSpO2')
                        if spo2 is None:
                            spo2 = get_safe(spo2_data, 'latestSpO2')
                        if spo2 is None:
                            spo2 = get_safe(spo2_data, 'latestSpO2Value')
                except:
                    pass

            # Respiration fallback - try dedicated endpoint if not in user summary
            if resp is None:
                try:
                    resp_data = api.get_respiration_data(day_str)
                    if resp_data:
                        resp = get_safe(resp_data, 'avgWakingRespirationValue')
                        if resp is None:
                            resp = get_safe(resp_data, 'avgSleepRespirationValue')
                except:
                    pass

            # VO2 Max fallback - try max metrics endpoint
            if vo2 is None:
                try:
                    if hasattr(api, 'get_max_metrics'):
                        max_metrics = api.get_max_metrics(day_str)
                        if max_metrics:
                            for metric in max_metrics if isinstance(max_metrics, list) else [max_metrics]:
                                if get_safe(metric, 'generic', 'vo2MaxPreciseValue'):
                                    vo2 = get_safe(metric, 'generic', 'vo2MaxPreciseValue')
                                    break
                                if get_safe(metric, 'vo2MaxPreciseValue'):
                                    vo2 = get_safe(metric, 'vo2MaxPreciseValue')
                                    break
                except:
                    pass

            # Sleep
            try:
                sleep_data = api.get_sleep_data(day_str)
                s_tot = get_safe(sleep_data, 'dailySleepDTO', 'sleepTimeSeconds')
                s_deep = get_safe(sleep_data, 'dailySleepDTO', 'deepSleepSeconds')
                s_rem = get_safe(sleep_data, 'dailySleepDTO', 'remSleepSeconds')
                s_score = get_safe(sleep_data, 'dailySleepDTO', 'sleepScores', 'overall', 'value')
                if s_tot: s_tot = round(s_tot / 3600, 2)
                if s_deep: s_deep = round(s_deep / 3600, 2)
                if s_rem: s_rem = round(s_rem / 3600, 2)
            except:
                s_tot, s_deep, s_rem, s_score = None, None, None, None

            # Training Status
            t_status = None
            try:
                if hasattr(api, 'get_training_status'):
                    ts = api.get_training_status(day_str)
                    # Try multiple paths for training status
                    t_status = get_safe(ts, 'mostRecentTerminatedTrainingStatus', 'status')
                    if t_status is None:
                        t_status = get_safe(ts, 'trainingStatusData', 'status')
                    if t_status is None:
                        t_status = get_safe(ts, 'status')
                    if t_status is None and isinstance(ts, list) and len(ts) > 0:
                        t_status = get_safe(ts[0], 'status')

                    # Also try to get VO2 max from training status if still missing
                    if vo2 is None and ts:
                        vo2 = get_safe(ts, 'vo2MaxValue')
                        if vo2 is None:
                            vo2 = get_safe(ts, 'mostRecentTerminatedTrainingStatus', 'vo2MaxValue')
            except:
                pass

            # Body Comp
            wt, mus, fat, h2o = None, None, None, None
            try:
                bc = api.get_body_composition(day_str)
                if bc and 'totalAverage' in bc:
                    avg = bc['totalAverage']
                    if avg.get('weight'): wt = round(avg.get('weight')/453.592, 1)
                    if avg.get('muscleMass'): mus = round(avg.get('muscleMass')/453.592, 1)
                    fat = avg.get('bodyFat')
                    h2o = avg.get('bodyWater')
            except:
                pass

            # HRV
            hrv_s, hrv_a = None, None
            try:
                if hasattr(api, 'get_hrv_data'):
                    h = api.get_hrv_data(day_str)
                else:
                    h = api.connectapi(f"/hrv-service/hrv/daily/{day_str}")

                hrv_s = get_safe(h, 'hrvSummary', 'status')

                # Try multiple HRV value sources in order of preference
                hrv_a = get_safe(h, 'hrvSummary', 'weeklyAverage')
                if hrv_a is None:
                    hrv_a = get_safe(h, 'hrvSummary', 'lastNightAvg')
                if hrv_a is None:
                    hrv_a = get_safe(h, 'lastNightAvg')
                if hrv_a is None:
                    # Try to get from HRV values array
                    hrv_values = get_safe(h, 'hrvValues')
                    if hrv_values and len(hrv_values) > 0:
                        hrv_a = get_safe(hrv_values[-1], 'hrvValue')
                if hrv_a is None:
                    hrv_a = get_safe(h, 'hrvValue')
            except:
                pass

            # Blood Pressure
            bp_sys, bp_dia = None, None
            try:
                if hasattr(api, 'get_blood_pressure'):
                    bp_data = api.get_blood_pressure(day_str)
                else:
                    bp_data = api.connectapi(f"/bloodpressure/{day_str}")

                if bp_data:
                    summaries = get_safe(bp_data, 'measurementSummaries')
                    if summaries and len(summaries) > 0:
                        # Try to get from measurements array first (most accurate)
                        measurements = get_safe(summaries[0], 'measurements')
                        if measurements and len(measurements) > 0:
                            bp_sys = get_safe(measurements[0], 'systolic')
                            bp_dia = get_safe(measurements[0], 'diastolic')

                        # Fallback to summary high values
                        if bp_sys is None:
                            bp_sys = get_safe(summaries[0], 'highSystolic')
                            bp_dia = get_safe(summaries[0], 'highDiastolic')
            except:
                pass

            # Activities
            act_str = ""
            try:
                acts = api.get_activities_by_date(day_str, day_str)
                if acts:
                    names = [f"{a['activityName']} ({a['activityType']['typeKey']})" for a in acts]
                    act_str = "; ".join(names)
            except:
                pass

            # Build Row
            row = [
                day_str, wt, mus, fat, h2o, s_tot, s_deep, s_rem, s_score,
                rhr, min_hr, max_hr, stress, resp, spo2, vo2, t_status, hrv_s, hrv_a,
                bp_sys, bp_dia,
                steps, cals_goal, cals_tot, cals_act, act_str
            ]

            if FORCE_MODE:
                # Force mode: completely replace with fresh data
                existing_data[day_str] = row
                print(" Done.")
            elif BACKFILL_MODE:
                # Merge with existing data - only fill empty values
                if day_str in existing_data:
                    old_row = existing_data[day_str]
                    merged_row = []
                    for i, (old_val, new_val) in enumerate(zip(old_row, row)):
                        # Keep old value if it exists and is not empty
                        if old_val is not None and str(old_val).strip() != '':
                            merged_row.append(old_val)
                        else:
                            merged_row.append(new_val)
                    existing_data[day_str] = merged_row
                else:
                    existing_data[day_str] = row
                print(" Done.")
            else:
                # Normal mode: append immediately
                with open(CSV_FILE, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                print(" Done.")

        except Exception as e:
            print(f" Failed ({e})")

        # Increment Date & Sleep to be nice to API
        current_date += delta
        time.sleep(random.uniform(1.5, 3.0)) # Sleep 1.5 to 3 seconds

    # In backfill or force mode, write all data back to file
    if (BACKFILL_MODE or FORCE_MODE) and existing_data:
        print("Writing updated data to file...")
        # Sort by date (newest first)
        sorted_dates = sorted(existing_data.keys(), reverse=True)
        with open(CSV_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for d in sorted_dates:
                writer.writerow(existing_data[d])
        print(f"Updated {len(existing_data)} rows.")

    print("--- HISTORY PULL COMPLETE ---")

if __name__ == "__main__":
    main()
