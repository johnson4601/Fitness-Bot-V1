import garth
from garminconnect import Garmin
from datetime import date, timedelta
import csv
import os
import time

# --- CONFIGURATION ---
TOKEN_DIR = ".garth"
CSV_FILE = r"G:\My Drive\Gemini Gems\Personal trainer\garmin_runs.csv"
START_DATE = "2023-01-01" # How far back to go?
# ---------------------

def get_safe(data, *keys):
    try:
        for key in keys:
            data = data[key]
        return data
    except (KeyError, TypeError, AttributeError):
        return None

def format_pace(speed_mps):
    """Converts meters/sec to Min/Mile (e.g., 8:30)"""
    if not speed_mps or speed_mps <= 0: return None
    mins_per_mile = 26.8224 / speed_mps
    minutes = int(mins_per_mile)
    seconds = int((mins_per_mile - minutes) * 60)
    return f"{minutes}:{seconds:02d}"

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

    # Create folder if missing
    folder_path = os.path.dirname(CSV_FILE)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # Write Headers
    if not os.path.isfile(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Time", "Title", "Distance (mi)", "Duration (min)", 
                "Avg Pace (min/mi)", "Avg HR", "Max HR", "Cadence", 
                "Elevation Gain (ft)", "Aerobic TE", "Anaerobic TE", "Calories"
            ])

    # Fetch activities in chunks
    start = date.fromisoformat(START_DATE)
    end = date.today()
    
    # Garmin API fetches by "count" typically, but get_activities_by_date is easier for ranges
    # We'll do 30 day chunks to be safe
    current = start
    while current < end:
        chunk_end = current + timedelta(days=30)
        if chunk_end > end: chunk_end = end
        
        print(f"   Processing {current} to {chunk_end}...", end="", flush=True)
        
        try:
            activities = api.get_activities_by_date(current.isoformat(), chunk_end.isoformat(), "running")
            
            new_rows = []
            if activities:
                for act in activities:
                    # Basic Fields
                    start_local = act.get('startTimeLocal', '')
                    date_str = start_local[:10]
                    time_str = start_local[11:]
                    title = act.get('activityName', 'Run')
                    
                    # Metrics
                    dist_m = act.get('distance', 0)
                    dist_mi = round(dist_m * 0.000621371, 2)
                    
                    dur_s = act.get('duration', 0)
                    dur_min = round(dur_s / 60, 2)
                    
                    speed_mps = act.get('averageSpeed', 0)
                    avg_pace = format_pace(speed_mps)
                    
                    hr = act.get('averageHR')
                    max_hr = act.get('maxHR')
                    cadence = act.get('averageRunningCadenceInStepsPerMinute')
                    
                    elev_m = act.get('totalElevationGain', 0)
                    elev_ft = round(elev_m * 3.28084, 0) if elev_m else 0
                    
                    cal = act.get('calories')
                    
                    # Training Effect (TE)
                    aero_te = act.get('aerobicTrainingEffect')
                    ana_te = act.get('anaerobicTrainingEffect')

                    new_rows.append([
                        date_str, time_str, title, dist_mi, dur_min, 
                        avg_pace, hr, max_hr, cadence, elev_ft, aero_te, ana_te, cal
                    ])
            
            # Save chunk
            if new_rows:
                # Sort by date
                new_rows.sort(key=lambda x: x[0])
                with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerows(new_rows)
                print(f" Saved {len(new_rows)} runs.")
            else:
                print(" No runs.")

        except Exception as e:
            print(f" Error: {e}")

        current = chunk_end + timedelta(days=1)
        time.sleep(1) # Pause between chunks

    print("--- HISTORY PULL COMPLETE ---")

if __name__ == "__main__":
    main()