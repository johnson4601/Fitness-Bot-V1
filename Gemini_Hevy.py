import os
import pickle
import io
import json
import pandas as pd
import requests
import time
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
DRY_RUN = False  # Set to False to actually post workouts to Hevy
MODEL_NAME = "gemini-flash-latest" # Using latest Gemini Flash model

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HEVY_API_KEY = os.getenv("HEVY_API_KEY")
TARGET_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SCOPES = ['https://www.googleapis.com/auth/drive'] # Removed .readonly so we can upload the missing CSV if needed

# --- MONTHLY PROMPT ---
def load_monthly_prompt():
    """Load the monthly prompt from MONTHLY_PROMPT_TEXT.txt file."""
    prompt_file = "MONTHLY_PROMPT_TEXT.txt"
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"ERROR: Could not find '{prompt_file}'. Please ensure it exists in the current directory.")
        raise
    except Exception as e:
        print(f"ERROR: Failed to read '{prompt_file}': {e}")
        raise

def calculate_one_rep_max(weight, reps):
    """Calculate estimated 1RM using the Epley formula: 1RM = weight × (1 + reps/30)"""
    if reps == 0 or weight == 0:
        return 0
    return weight * (1 + reps / 30)

def aggregate_training_data(hevy_stats_df, exercise_db_df, months=6):
    """
    Aggregate training data for the last N months.

    Returns:
        - 1RM per muscle group
        - Total volume per muscle group
        - Exercise-specific PRs
    """
    from datetime import datetime, timedelta

    # Filter for last N months
    cutoff_date = datetime.now() - timedelta(days=months * 30)
    hevy_stats_df['Date'] = pd.to_datetime(hevy_stats_df['Date'])
    recent_data = hevy_stats_df[hevy_stats_df['Date'] >= cutoff_date].copy()

    if recent_data.empty:
        print("   [!] Warning: No data found in the last 6 months")
        return None

    # Calculate 1RM for each set
    recent_data['estimated_1rm'] = recent_data.apply(
        lambda row: calculate_one_rep_max(row['Weight (lbs)'], row['Reps']), axis=1
    )

    # Calculate volume for each set (Weight × Reps)
    recent_data['volume'] = recent_data['Weight (lbs)'] * recent_data['Reps']

    # Merge with exercise database to get muscle groups
    # Clean exercise names for matching
    exercise_db_df['title_clean'] = exercise_db_df['title'].str.strip()
    recent_data['Exercise_clean'] = recent_data['Exercise'].str.strip()

    merged_data = recent_data.merge(
        exercise_db_df[['title_clean', 'primary_muscle_group', 'secondary_muscle_groups']],
        left_on='Exercise_clean',
        right_on='title_clean',
        how='left'
    )

    # Aggregate by primary muscle group
    muscle_group_stats = merged_data.groupby('primary_muscle_group').agg({
        'estimated_1rm': 'max',  # Best estimated 1RM
        'volume': 'sum',  # Total volume
        'Exercise': 'count'  # Total sets
    }).round(2)

    muscle_group_stats.columns = ['Max_1RM_lbs', 'Total_Volume_lbs', 'Total_Sets']

    # Get top exercises by 1RM
    exercise_prs = merged_data.groupby('Exercise').agg({
        'estimated_1rm': 'max',
        'Weight (lbs)': 'max',
        'Reps': 'max',
        'primary_muscle_group': 'first'
    }).round(2)

    exercise_prs.columns = ['Estimated_1RM', 'Max_Weight', 'Max_Reps', 'Muscle_Group']
    exercise_prs = exercise_prs.sort_values('Estimated_1RM', ascending=False)

    return {
        'muscle_group_summary': muscle_group_stats,
        'exercise_prs': exercise_prs,
        'total_workouts': recent_data['Date'].nunique(),
        'date_range': f"{recent_data['Date'].min().strftime('%Y-%m-%d')} to {recent_data['Date'].max().strftime('%Y-%m-%d')}"
    }

def calculate_strength_trends(hevy_stats_df, recent_months=3, history_months=12):
    """
    Compare recent 1RM vs all-time 1RM to detect plateaus or regressions.
    Returns trend analysis per exercise.
    """
    from datetime import datetime
    
    now = datetime.now()
    recent_cutoff = now - pd.DateOffset(months=recent_months)
    history_cutoff = now - pd.DateOffset(months=history_months)

    df = hevy_stats_df.copy()
    df['Date'] = pd.to_datetime(df['Date'], format='mixed')
    df['estimated_1rm'] = df.apply(
        lambda row: calculate_one_rep_max(row['Weight (lbs)'], row['Reps']), axis=1
    )

    # Filter to history window
    df = df[df['Date'] >= history_cutoff]

    if df.empty:
        return None

    # Recent period (last N months)
    recent_data = df[df['Date'] >= recent_cutoff]
    if recent_data.empty:
        return None

    recent_1rm = recent_data.groupby('Exercise')['estimated_1rm'].max()

    # All-time 1RM within history window
    all_time_1rm = df.groupby('Exercise')['estimated_1rm'].max()

    # Calculate trend
    trends = pd.DataFrame({
        'Recent_1RM': recent_1rm,
        'AllTime_1RM': all_time_1rm
    }).dropna()

    if trends.empty:
        return None

    trends['Trend_Pct'] = ((trends['Recent_1RM'] - trends['AllTime_1RM']) / trends['AllTime_1RM'] * 100).round(1)
    trends['Status'] = trends['Trend_Pct'].apply(
        lambda x: 'PLATEAU' if -2 <= x <= 2 else ('REGRESSING' if x < -2 else 'PROGRESSING')
    )

    return trends.sort_values('Trend_Pct')

def validate_variable_loading(routines_json):
    """
    Validates that compound movements use variable loading (not straight sets).
    Returns list of warnings for exercises with static weights across multiple sets.
    """
    warnings = []

    routines = routines_json.get('routines', []) if isinstance(routines_json, dict) else routines_json

    for routine in routines:
        for exercise in routine.get('exercises', []):
            sets = exercise.get('sets', [])
            if len(sets) < 2:
                continue

            weights = [s.get('weight_kg', 0) for s in sets if s.get('type') == 'normal']

            # Check if all weights are identical (straight sets)
            if len(set(weights)) == 1 and len(weights) > 1:
                ex_id = exercise.get('exercise_template_id', 'unknown')
                warnings.append({
                    'routine': routine.get('title'),
                    'exercise_id': ex_id,
                    'issue': f'Static weight ({weights[0]}kg) across {len(weights)} sets - consider variable loading'
                })

    return warnings

def get_drive_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

def fetch_and_save_hevy_exercises():
    """Downloads exercise list from Hevy and saves as CSV locally."""
    print("   [!] 'HEVY APP exercises.csv' missing. Downloading from Hevy API...")
    url = "https://api.hevyapp.com/v1/exercise_templates"
    headers = {"api-key": HEVY_API_KEY}
    
    all_exercises = []
    page = 1
    page_count = 1
    
    try:
        # Hevy paginates, so we loop to get them all
        while page <= page_count:
            response = requests.get(url, headers=headers, params={"page": page, "pageSize": 50})
            if response.status_code != 200:
                print(f"Error fetching exercises: {response.text}")
                return None
            
            data = response.json()
            page_count = data.get("page_count", 1)
            all_exercises.extend(data.get("exercise_templates", []))
            page += 1
            
        # Convert to DataFrame
        df = pd.DataFrame(all_exercises)
        # Keep only what we need
        if 'title' in df.columns and 'id' in df.columns:
            df = df[['id', 'title']]
            # Save locally so we can read it
            df.to_csv("HEVY APP exercises.csv", index=False)
            print(f"   -> Successfully saved {len(df)} exercises to 'HEVY APP exercises.csv'")
            return df
        else:
            print("   -> Error: Unexpected data format from Hevy.")
            return None
            
    except Exception as e:
        print(f"   -> Failed to fetch exercises: {e}")
        return None

def get_file_content(service, filename):
    # First check if file exists locally
    if os.path.exists(filename):
        print(f"   Found '{filename}' locally.")
        with open(filename, 'rb') as f:
            return io.BytesIO(f.read())

    # If not local, search Google Drive
    print(f"   Searching for '{filename}' in Google Drive...")
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{filename}' and trashed=false"
    results = service.files().list(q=query, pageSize=1, fields="files(id, name, mimeType)").execute()
    items = results.get('files', [])

    if not items:
        print(f"   [!] Warning: Could not find '{filename}' locally or in Google Drive.")
        return None

    file_id = items[0]['id']
    mime_type = items[0]['mimeType']

    if mime_type == 'application/vnd.google-apps.spreadsheet':
        request = service.files().export_media(fileId=file_id, mimeType='text/csv')
    else:
        request = service.files().get_media(fileId=file_id)

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        _, done = downloader.next_chunk()
    fh.seek(0)
    print(f"   -> Downloaded '{filename}' from Google Drive successfully.")
    return fh

def generate_monthly_plan():
    service = get_drive_service()
    client = genai.Client(api_key=GEMINI_API_KEY)

    print("\n--- STEP 1: GATHERING DATA ---")
    hevy_stats = get_file_content(service, "hevy_stats.csv")
    exercise_db = get_file_content(service, "HEVY APP exercises.csv")

    context_str = ""
    df_stats = None
    df_ex = None

    # Load exercise database
    if exercise_db:
        df_ex = pd.read_csv(exercise_db)
        # Limit context size: randomly sample or take top 400 to fit in prompt
        context_str += f"\nAVAILABLE EXERCISE IDs (Sample):\n{df_ex[['id', 'title']].head(400).to_string()}\n"

    # Load and aggregate stats
    if hevy_stats:
        df_stats = pd.read_csv(hevy_stats)

        # Show recent raw data
        context_str += f"\nRECENT WORKOUT DATA (Last 30 sets):\n{df_stats.tail(30).to_string()}\n"

        # Calculate aggregated stats if we have both datasets
        if df_ex is not None:
            print("   Calculating 6-month aggregations (1RM & Volume)...")
            aggregated_stats = aggregate_training_data(df_stats, df_ex, months=6)

            if aggregated_stats:
                context_str += f"\n=== 6-MONTH PERFORMANCE SUMMARY ===\n"
                context_str += f"Period: {aggregated_stats['date_range']}\n"
                context_str += f"Total Workouts: {aggregated_stats['total_workouts']}\n\n"

                context_str += "MUSCLE GROUP ANALYSIS:\n"
                context_str += aggregated_stats['muscle_group_summary'].to_string() + "\n\n"

                context_str += "TOP 15 EXERCISE PRs (by Estimated 1RM):\n"
                context_str += aggregated_stats['exercise_prs'].head(15).to_string() + "\n"

            # Calculate strength trends for plateau detection
            print("   Calculating strength trends (plateau detection)...")
            strength_trends = calculate_strength_trends(df_stats, recent_months=3, history_months=12)
            if strength_trends is not None and not strength_trends.empty:
                context_str += "\n=== STRENGTH TRENDS (Recent 3mo vs 12mo History) ===\n"
                context_str += strength_trends.to_string() + "\n"
                # Highlight exercises needing attention
                plateaus = strength_trends[strength_trends['Status'] == 'PLATEAU']
                regressions = strength_trends[strength_trends['Status'] == 'REGRESSING']
                if not plateaus.empty:
                    context_str += f"\n[!] PLATEAU DETECTED ({len(plateaus)} exercises): {', '.join(plateaus.index.tolist()[:5])}\n"
                if not regressions.empty:
                    context_str += f"\n[!] REGRESSION DETECTED ({len(regressions)} exercises): {', '.join(regressions.index.tolist()[:5])}\n"
        else:
            print("   [!] Skipping aggregations: Exercise database not available")

    print("\n--- STEP 2: CONSULTING GEMINI COACH ---")
    # Load the prompt from file
    monthly_prompt = load_monthly_prompt()

    # Using 1.5 Flash to avoid Rate Limits
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=monthly_prompt + context_str,
        config=genai.types.GenerateContentConfig(
            response_mime_type='application/json'
        )
    )
    return json.loads(response.text)

def get_or_create_folder(folder_name="AI Fitness"):
    """Get the folder ID for the given folder name, or create it if it doesn't exist."""
    headers = {"api-key": HEVY_API_KEY, "Content-Type": "application/json"}

    # List existing folders
    response = requests.get("https://api.hevyapp.com/v1/routine_folders", headers=headers)
    if response.status_code == 200:
        folders = response.json().get('routine_folders', [])
        for folder in folders:
            if folder['title'] == folder_name:
                print(f"   Found existing folder '{folder_name}' (ID: {folder['id']})")
                return folder['id']

    # Folder doesn't exist, create it
    print(f"   Creating new folder '{folder_name}'...")
    payload = {"routine_folder": {"title": folder_name}}
    response = requests.post("https://api.hevyapp.com/v1/routine_folders", headers=headers, json=payload)
    if response.status_code in [200, 201]:
        folder_id = response.json()['routine_folder']['id']
        print(f"   Created folder '{folder_name}' (ID: {folder_id})")
        return folder_id
    else:
        print(f"   Failed to create folder: {response.text}")
        return None

def delete_routines_in_folder(folder_id):
    """Delete all routines in the specified folder."""
    headers = {"api-key": HEVY_API_KEY}

    # List routines in the folder
    response = requests.get(f"https://api.hevyapp.com/v1/routines?routine_folder_id={folder_id}", headers=headers)
    if response.status_code != 200:
        print(f"   Failed to list routines: {response.text}")
        return

    routines = response.json().get('routines', [])
    if not routines:
        print(f"   No existing routines to delete.")
        return

    print(f"   Deleting {len(routines)} existing routine(s)...")
    for routine in routines:
        routine_id = routine['id']
        title = routine['title']
        delete_response = requests.delete(f"https://api.hevyapp.com/v1/routines/{routine_id}", headers=headers)
        if delete_response.status_code == 200:
            print(f"   -> Deleted '{title}'")
        else:
            print(f"   -> Failed to delete '{title}': {delete_response.text}")

def post_to_hevy(routines_json):
    if DRY_RUN:
        print("\n[DRY RUN MODE ENABLED] - Skipping upload to Hevy.")
        print("Here is the exact data that WOULD be sent:")
        print(json.dumps(routines_json, indent=2))
        return

    print("\n--- STEP 3: UPLOADING TO HEVY ---")

    # Create a new dated folder each time
    from datetime import datetime
    folder_name = f"AI Fitness {datetime.now().strftime('%Y-%m-%d')}"
    folder_id = get_or_create_folder(folder_name)
    if not folder_id:
        print("ERROR: Could not get or create folder")
        return

    url = "https://api.hevyapp.com/v1/routines"
    headers = {"api-key": HEVY_API_KEY, "Content-Type": "application/json"}

    routines_list = routines_json.get('routines', []) if isinstance(routines_json, dict) else routines_json

    print(f"\n   Creating {len(routines_list)} new routine(s)...")
    for routine in routines_list:
        # Add folder_id to the routine
        routine['folder_id'] = folder_id

        payload = {"routine": routine} if "routine" not in routine else routine
        title = payload['routine']['title']
        print(f"   Posting routine: {title}...")

        response = requests.post(url, headers=headers, json=payload)
        # Hevy returns 200 or 201 for success, or the routine data itself
        if response.status_code in [200, 201] or 'routine' in response.json():
            routine_data = response.json().get('routine', [{}])
            routine_id = routine_data[0].get('id', 'unknown') if isinstance(routine_data, list) else routine_data.get('id', 'unknown')
            print(f"   -> Success! (ID: {routine_id})")
        else:
            print(f"   -> Failed: {response.text}")

if __name__ == "__main__":
    try:
        if not GEMINI_API_KEY:
             print("ERROR: GEMINI_API_KEY not found in .env file")
        else:
            plan = generate_monthly_plan()

            # Validate variable loading in generated plan
            print("\n--- VALIDATING PLAN ---")
            loading_warnings = validate_variable_loading(plan)
            if loading_warnings:
                print("   [!] Variable Loading Warnings (straight sets detected):")
                for w in loading_warnings:
                    print(f"       - {w['routine']}: {w['exercise_id']} - {w['issue']}")
            else:
                print("   Variable loading check passed.")

            post_to_hevy(plan)
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
