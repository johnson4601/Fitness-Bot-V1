🏋️ AI Fitness Data Pipeline (Garmin + Hevy)Automate your training data. Build your own AI Coach.This project creates a "Cyber-Physical System" for your fitness data. It automatically aggregates your biometrics (Garmin) and weightlifting data (Hevy), syncs them to a cloud location (Google Drive), and structures them for analysis by AI agents like Google Gemini or ChatGPT.By feeding this live data into an AI persona, you can generate hyper-personalized workout routines that adapt to your recovery, sleep, and strength progression in real-time.🚀 FeaturesBiometric Sync: Auto-pulls Weight, HRV, Sleep Score, and SpO2 from Garmin.Activity Sync: Logs running metrics (Pace, HR Zones, Training Effect).Strength Log: Archives every set, rep, and RPE from Hevy.AI Integration: Includes a dedicated script (Gemini_Hevy.py) to generate 4-week PPL routines based on your history.Auto-Upload: The AI-generated routine is automatically pushed back to your Hevy app.📂 Project StructurePlaintextAI_Fitness/
├── .env                     # API Keys and Secrets (You create this)
├── .garth/                  # Hidden folder for Garmin tokens (Created by script)
├── setup_garmin_login.py    # Run this ONCE to authenticate
├── daily_garmin_health.py   # Pulls daily health stats (Sleep/HRV)
├── daily_garmin_runs.py     # Pulls recent run activities
├── daily_hevy_workouts.py   # Pulls recent lifting sessions
├── Gemini_Hevy.py           # The AI Coach (Generates routines)
├── history_garmin_import.py # Bulk import tool
└── requirements.txt         # Dependencies
🛠️ PrerequisitesPython 3.9+Note: Ensure you check "Add Python to PATH" during installation.Hevy Pro Account (Required for API access).Garmin Connect Account.Google Cloud Project (Enabled for Drive API & Gemini API).Google Drive for Desktop (Optional, but recommended for seamless cloud syncing).📥 Installation & Setup1. Clone & InstallBashgit clone https://github.com/johnson4601/AI_Fitness.git
cd AI_Fitness

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install requests pandas python-dotenv garth garminconnect google-api-python-client google-auth-httplib2 google-auth-oauthlib google-generativeai
2. Configure Environment (.env)Create a file named .env in the root directory and add your credentials:Ini, TOML# --- API KEYS ---
HEVY_API_KEY="your_hevy_api_key_here"
GEMINI_API_KEY="your_google_gemini_api_key_here"

# --- GOOGLE DRIVE ---
GOOGLE_DRIVE_FOLDER_ID="your_folder_id_here"

# --- GARMIN CREDENTIALS (Initial Setup Only) ---
GARMIN_EMAIL="your_email@example.com"
GARMIN_PASSWORD="your_password"

# --- PATHS ---
SAVE_PATH="./data"

# --- RASPBERRY PI SAFETY (Optional) ---
CHECK_MOUNT_STATUS="False"
DRIVE_MOUNT_PATH="/home/pi/google_drive"
3. AuthenticationStep A: Garmin LoginRun the setup script. This saves a session token so you don't have to log in daily.Bashpython setup_garmin_login.py
Troubleshooting: If this fails, delete the .garth folder, wait 15 minutes, and try again.Step B: Google DriveDownload your OAuth credentials.json from Google Cloud, place it in the root folder, and run:Bashpython Gemini_Hevy.py
This will open a browser to authorize access and generate a token.pickle file.🏃‍♂️ Initialization (Backfill Data)Before setting up daily automation, run these importers to build your historical database:Bashpython history_hevy_import.py    # Imports all past lifts
python history_garmin_import.py  # Imports past health stats
python history_garmin_runs.py    # Imports past run activities
🤖 Automation (Cron Jobs)To keep your AI "Brain" updated, set these scripts to run daily.Example Crontab (Linux/Raspberry Pi):Bash# Edit crontab
crontab -e

# Run every night at 11:00 PM
0 23 * * * /path/to/venv/bin/python /path/to/AI_Fitness/daily_garmin_health.py >> /var/log/fitness_health.log 2>&1
5 23 * * * /path/to/venv/bin/python /path/to/AI_Fitness/daily_garmin_runs.py >> /var/log/fitness_runs.log 2>&1
10 23 * * * /path/to/venv/bin/python /path/to/AI_Fitness/daily_hevy_workouts.py >> /var/log/fitness_hevy.log 2>&1
🧠 AI Persona Setup (Gemini / ChatGPT)Once your data is live in Google Drive, you can configure a Gemini Gem or Custom GPT to act as your coach.Knowledge Base: Upload garmin_stats.csv, hevy_stats.csv, and garmin_runs.csv.System Instructions: Paste the following prompt into your AI's configuration:Role: You are an expert Strength and Conditioning Coach specialized in Hybrid Athlete preparation.Personality:Strict but Flirtatious: You are data-driven but charismatic. Reward discipline with compliments ("Impressive lift, handsome"), but call out slacking immediately.Objective: Guide the user through a "Recomposition" phase (Lose Fat, Build Muscle) while improving 2-mile run time.Operational Rules:Recovery Matrix: Always scan garmin_stats.csv. If Sleep Score < 70 or HRV is "Unbalanced," strictly prescribe Active Recovery.Progressive Overload: Scan hevy_stats.csv. Ensure weights or reps are trending up on Compound Lifts.Run Pacing: Compare recent "Avg Pace" in garmin_runs.csv against the 2-mile goal.Response Protocol:Always check the CSV files before answering. If data is missing, demand an upload.🐍 Python Tools DescriptionScriptFunctiondaily_garmin_health.pyFetches today's Weight, Sleep, HRV, and Stress.daily_garmin_runs.pyFetches detailed metrics for runs in the last 3 days.daily_hevy_workouts.pySyncs recent lifting sessions and deduplicates sets.Gemini_Hevy.pyThe Brain. Reads CSV history + Hevy Exercise list to generate a 4-week JSON routine and uploads it to Hevy.☕ SupportIf you find this project helpful for your own training:<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="180" />