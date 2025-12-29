import requests
import json
import sys
import os
from dotenv import load_dotenv
from pathlib import Path # <--- Add this

# 1. Force the script to look for .env in the SAME folder as the script
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# 2. Get the variables
API_KEY = os.getenv("HEVY_API_KEY")
SAVE_PATH = os.getenv("SAVE_PATH")

# ... rest of script stays the same

# Check if the key loaded correctly (for debugging)
if not API_KEY:
    print("❌ Error: Could not find HEVY_API_KEY in .env file.")
    sys.exit(1)

BASE_URL = "https://api.hevyapp.com/v1"
HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}

def get_or_create_folder(folder_name):
    """Finds a folder by name, or creates it if it doesn't exist."""
    res = requests.get(f"{BASE_URL}/routine_folders", headers=HEADERS)
    res.raise_for_status()
    folders = res.json().get("routine_folders", [])
    
    for f in folders:
        if f["title"] == folder_name:
            print(f"📂 Found existing folder: '{folder_name}' (ID: {f['id']})")
            return f["id"]
    
    print(f"📂 Folder '{folder_name}' not found. Creating it...")
    payload = {"routine_folder": {"title": folder_name}}
    res = requests.post(f"{BASE_URL}/routine_folders", headers=HEADERS, json=payload)
    res.raise_for_status()
    return res.json()["routine_folder"]["id"]

def create_routine(payload, folder_id):
    """Creates a routine inside the specific folder."""
    payload["routine"]["folder_id"] = folder_id
    
    try:
        res = requests.post(f"{BASE_URL}/routines", headers=HEADERS, json=payload)
        res.raise_for_status()
        title = payload["routine"]["title"]
        print(f"✅ Success! Routine '{title}' created.")
    except requests.exceptions.HTTPError as err:
        print(f"❌ Error creating routine: {err}")
        print(f"Response: {res.text}")

if __name__ == "__main__":
    # Ensure the script runs in the same directory as the .env file
    # or provide the full path to load_dotenv(r"Path\To\.env") if it's elsewhere.
    
    folder_name = input("Enter the Training Block Name (e.g., 'Jan 2025 Hypertrophy'): ").strip()
    if not folder_name:
        folder_name = "Gemini Workouts"
        
    try:
        target_folder_id = get_or_create_folder(folder_name)
    except requests.exceptions.HTTPError as err:
        print(f"❌ Connection Error: {err}")
        print("Check your API Key in the .env file.")
        sys.exit(1)
    
    print("\nPaste the JSON from Gemini below (Press Ctrl+Z then Enter to save):")
    user_input = sys.stdin.read()
    
    if user_input.strip():
        try:
            data = json.loads(user_input)
            if isinstance(data, list):
                for routine in data:
                    create_routine(routine, target_folder_id)
            else:
                create_routine(data, target_folder_id)
        except json.JSONDecodeError:
            print("❌ Invalid JSON.")