import garth
from garminconnect import Garmin
from datetime import date
import csv
import os
from dotenv import load_dotenv

import os
import sys
import platform
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

# ... rest of your code ...

# --- CONFIGURATION VIA ENVIRONMENT ---
SAVE_PATH = os.getenv("SAVE_PATH")

if SAVE_PATH:
    CSV_FILE = os.path.join(SAVE_PATH, "garmin_stats.csv")
else:
    print("WARNING: SAVE_PATH not set in .env. Using current folder.")
    CSV_FILE = "garmin_stats.csv"

TOKEN_DIR = os.path.join(SCRIPT_DIR, ".garth")
# -------------------------------------

def get_safe(data, *keys):
    try:
        for key in keys:
            data = data[key]
        return data
    except (KeyError, TypeError, AttributeError):
        return None

def main():
    try:
        print("1. Loading tokens...")
        garth.resume(TOKEN_DIR)
        
        # Initialize API
        api = Garmin("dummy", "dummy")
        api.garth = garth.client
        try:
            api.display_name = api.garth.profile['displayName']
        except:
            pass
        
        today = date.today().isoformat()
        print(f"2. Pulling data for {today}...")

        # --- DATA PULLING ---
        # 1. Core Biometrics
        try:
            user_stats = api.get_user_summary(today)
            rhr = get_safe(user_stats, 'restingHeartRate')
            min_hr = get_safe(user_stats, 'minHeartRate')
            max_hr = get_safe(user_stats, 'maxHeartRate')
            stress_avg = get_safe(user_stats, 'averageStressLevel')
            steps = get_safe(user_stats, 'totalSteps')
            vo2_max = get_safe(user_stats, 'vo2Max')
            spo2_avg = get_safe(user_stats, 'averageSpO2')
            respiration_avg = get_safe(user_stats, 'averageRespirationValue')
            cals_total = get_safe(user_stats, 'totalKilocalories')
            cals_active = get_safe(user_stats, 'activeKilocalories')
            cals_goal = get_safe(user_stats, 'dailyStepGoal')
        except:
            rhr, min_hr, max_hr, stress_avg, steps, vo2_max, spo2_avg, respiration_avg, cals_total, cals_active, cals_goal = [None] * 11

        # 1b. Try dedicated endpoints for missing metrics
        # SpO2
        if spo2_avg is None:
            try:
                spo2_data = api.get_spo2_data(today)
                if spo2_data:
                    spo2_avg = get_safe(spo2_data, 'averageSpO2')
                    if spo2_avg is None:
                        spo2_avg = get_safe(spo2_data, 'latestSpO2')
                    if spo2_avg is None:
                        spo2_avg = get_safe(spo2_data, 'latestSpO2Value')
            except:
                pass

        # Respiration
        if respiration_avg is None:
            try:
                resp_data = api.get_respiration_data(today)
                if resp_data:
                    respiration_avg = get_safe(resp_data, 'avgWakingRespirationValue')
                    if respiration_avg is None:
                        respiration_avg = get_safe(resp_data, 'avgSleepRespirationValue')
            except:
                pass

        # VO2 Max - try fitness stats
        if vo2_max is None:
            try:
                if hasattr(api, 'get_max_metrics'):
                    max_metrics = api.get_max_metrics(today)
                    if max_metrics:
                        # Look for VO2 max in various locations
                        for metric in max_metrics if isinstance(max_metrics, list) else [max_metrics]:
                            if get_safe(metric, 'generic', 'vo2MaxPreciseValue'):
                                vo2_max = get_safe(metric, 'generic', 'vo2MaxPreciseValue')
                                break
                            if get_safe(metric, 'vo2MaxPreciseValue'):
                                vo2_max = get_safe(metric, 'vo2MaxPreciseValue')
                                break
            except:
                pass

        # 2. Sleep
        try:
            sleep_data = api.get_sleep_data(today)
            sleep_total = get_safe(sleep_data, 'dailySleepDTO', 'sleepTimeSeconds')
            sleep_deep = get_safe(sleep_data, 'dailySleepDTO', 'deepSleepSeconds')
            sleep_rem = get_safe(sleep_data, 'dailySleepDTO', 'remSleepSeconds')
            sleep_score = get_safe(sleep_data, 'dailySleepDTO', 'sleepScores', 'overall', 'value')
            
            if sleep_total: sleep_total = round(sleep_total / 3600, 2)
            if sleep_deep: sleep_deep = round(sleep_deep / 3600, 2)
            if sleep_rem: sleep_rem = round(sleep_rem / 3600, 2)
        except:
            sleep_total, sleep_deep, sleep_rem, sleep_score = None, None, None, None

        # 3. Training Status
        training_status = None
        t_status = None
        try:
            if hasattr(api, 'get_training_status'):
                t_status = api.get_training_status(today)
                # Try multiple paths for training status
                training_status = get_safe(t_status, 'mostRecentTerminatedTrainingStatus', 'status')
                if training_status is None:
                    training_status = get_safe(t_status, 'trainingStatusData', 'status')
                if training_status is None:
                    training_status = get_safe(t_status, 'status')
                if training_status is None and isinstance(t_status, list) and len(t_status) > 0:
                    training_status = get_safe(t_status[0], 'status')

                # Also try to get VO2 max from training status if still missing
                if vo2_max is None and t_status:
                    vo2_max = get_safe(t_status, 'vo2MaxValue')
                    if vo2_max is None:
                        vo2_max = get_safe(t_status, 'mostRecentTerminatedTrainingStatus', 'vo2MaxValue')
        except:
            pass

        # 4. Body Comp
        weight, muscle_mass, fat_pct, water_pct = None, None, None, None
        try:
            body_comp = api.get_body_composition(today)
            if body_comp and 'totalAverage' in body_comp:
                avg = body_comp['totalAverage']
                w_g = avg.get('weight')
                if w_g: weight = round(w_g / 453.592, 1)
                m_g = avg.get('muscleMass')
                if m_g: muscle_mass = round(m_g / 453.592, 1)
                fat_pct = avg.get('bodyFat')
                water_pct = avg.get('bodyWater')
        except:
            pass

        # 5. HRV
        hrv_status, hrv_avg = None, None
        try:
            if hasattr(api, 'get_hrv_data'):
                h = api.get_hrv_data(today)
            else:
                h = api.connectapi(f"/hrv-service/hrv/daily/{today}")

            hrv_status = get_safe(h, 'hrvSummary', 'status')

            # Try multiple HRV value sources in order of preference
            hrv_avg = get_safe(h, 'hrvSummary', 'weeklyAverage')
            if hrv_avg is None:
                hrv_avg = get_safe(h, 'hrvSummary', 'lastNightAvg')
            if hrv_avg is None:
                hrv_avg = get_safe(h, 'lastNightAvg')
            if hrv_avg is None:
                # Try to get from HRV values array
                hrv_values = get_safe(h, 'hrvValues')
                if hrv_values and len(hrv_values) > 0:
                    # Get the most recent HRV reading
                    hrv_avg = get_safe(hrv_values[-1], 'hrvValue')
            if hrv_avg is None:
                hrv_avg = get_safe(h, 'hrvValue')
        except Exception as e:
            print(f"HRV fetch error: {e}")

        # 6. Blood Pressure
        bp_systolic, bp_diastolic = None, None
        try:
            if hasattr(api, 'get_blood_pressure'):
                bp_data = api.get_blood_pressure(today)
            else:
                bp_data = api.connectapi(f"/bloodpressure/{today}")

            if bp_data:
                summaries = get_safe(bp_data, 'measurementSummaries')
                if summaries and len(summaries) > 0:
                    # Try to get from measurements array first (most accurate)
                    measurements = get_safe(summaries[0], 'measurements')
                    if measurements and len(measurements) > 0:
                        bp_systolic = get_safe(measurements[0], 'systolic')
                        bp_diastolic = get_safe(measurements[0], 'diastolic')
        except:
            pass

        # 7. Activities
        activity_str = ""
        try:
            activities = api.get_activities_by_date(today, today)
            if activities:
                names = [f"{act['activityName']} ({act['activityType']['typeKey']})" for act in activities]
                activity_str = "; ".join(names)
        except:
            pass

        # --- PREPARE ROW ---
        new_row = [
            today, 
            weight, muscle_mass, fat_pct, water_pct,
            sleep_total, sleep_deep, sleep_rem, sleep_score,
            rhr, min_hr, max_hr, stress_avg, respiration_avg, spo2_avg,
            vo2_max, training_status, hrv_status, hrv_avg,
            bp_systolic, bp_diastolic,
            steps, cals_goal, cals_total, cals_active,
            activity_str
        ]

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

        # --- SMART SAVE ---
        rows = []
        folder_path = os.path.dirname(CSV_FILE)
        if folder_path and not os.path.exists(folder_path):
            os.makedirs(folder_path)

        file_exists = os.path.isfile(CSV_FILE)
        
        if file_exists:
            try:
                with open(CSV_FILE, mode='r', newline='') as f:
                    reader = csv.reader(f)
                    all_data = list(reader)
                    if all_data:
                        rows = [row for row in all_data[1:] if row and row[0] != today]
            except Exception as e:
                print(f"Warning reading existing CSV: {e}")

        rows.append(new_row)
        rows.sort(key=lambda x: x[0])

        with open(CSV_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
            
        print(f"SUCCESS! Saved data for {today} to {CSV_FILE}")

    except Exception as e:
        print(f"Global Error: {e}")

if __name__ == "__main__":
    main()