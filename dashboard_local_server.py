import os
import sys
import time
import subprocess
import json
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

# Paths
DRIVE_PATH = os.getenv("DRIVE_MOUNT_PATH", "/home/pi/GDrive")
SAVE_PATH = os.getenv("SAVE_PATH", "/home/pi/GDrive/Gemini Gems/Personal trainer")
BACKUP_PATH = os.path.join(DRIVE_PATH, "Backups")

# Project paths (with sensible defaults)
PROJECT_DIR = os.getenv("PROJECT_DIR", os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.getenv("LOG_FILE", "/home/pi/cron_log.txt")
HEVY_API_KEY = os.getenv("HEVY_API_KEY")

# For prompt file
if os.path.exists(PROJECT_DIR):
    PROMPT_FILE = os.path.join(PROJECT_DIR, "MONTHLY_PROMPT_TEXT.txt")
else:
    PROMPT_FILE = os.path.join(os.getcwd(), "MONTHLY_PROMPT_TEXT.txt")

# CSV file paths
HEVY_STATS_FILE = os.path.join(SAVE_PATH, "hevy_stats.csv")
GARMIN_STATS_FILE = os.path.join(SAVE_PATH, "garmin_stats.csv")
GARMIN_RUNS_FILE = os.path.join(SAVE_PATH, "garmin_runs.csv")
HEVY_EXERCISES_FILE = os.path.join(SAVE_PATH, "HEVY APP exercises.csv")

# Tracked Files & Commands (using environment-based paths)
TRACKED_FILES = {
    "Garmin Health": {
        "path": os.path.join(SAVE_PATH, "garmin_stats.csv"),
        "interval": "hourly",
        "sched": {"minute": 30},
        "command": f"cd {PROJECT_DIR} && /usr/bin/python3 daily_garmin_health.py >> {LOG_FILE} 2>&1"
    },
    "Hevy Workouts": {
        "path": os.path.join(SAVE_PATH, "hevy_stats.csv"),
        "interval": "hourly",
        "sched": {"minute": 35},
        "command": f"cd {PROJECT_DIR} && /usr/bin/python3 daily_hevy_workouts.py >> {LOG_FILE} 2>&1"
    },
    "Garmin Runs": {
        "path": os.path.join(SAVE_PATH, "garmin_runs.csv"),
        "interval": "hourly",
        "sched": {"minute": 40},
        "command": f"cd {PROJECT_DIR} && /usr/bin/python3 daily_garmin_runs.py >> {LOG_FILE} 2>&1"
    },
    "Hevy Ticker": {
        "path": os.path.join(os.path.dirname(PROJECT_DIR), "Hevy_Ticker", "ticker.log"),
        "interval": "hourly",
        "sched": {"minute": 45},
        "command": f"cd {os.path.join(os.path.dirname(PROJECT_DIR), 'Hevy_Ticker')} && /usr/bin/python3 Hevy_Ticker.py >> {LOG_FILE} 2>&1"
    },
    "System Maint": {
        "path": os.path.join(PROJECT_DIR, "update.log"),
        "interval": "daily",
        "sched": {"hour": 4, "minute": 0},
        "command": f"{os.path.join(PROJECT_DIR, 'update.sh')} >> {LOG_FILE} 2>&1"
    },
    "System Backup": {
        "path": BACKUP_PATH,
        "interval": "weekly",
        "sched": {"dow": 0, "hour": 3, "minute": 0},
        "command": f"{os.path.join(os.path.dirname(PROJECT_DIR), 'system_backup.sh')} >> {LOG_FILE} 2>&1"
    },
    "Monthly AI Plan": {
        "path": os.path.join(PROJECT_DIR, "Gemini_Hevy.py"),
        "interval": "monthly",
        "sched": {"day": 1, "hour": 1, "minute": 0},
        "command": f"cd {PROJECT_DIR} && {os.path.join(PROJECT_DIR, 'venv', 'bin', 'python')} Gemini_Hevy.py >> {LOG_FILE} 2>&1"
    }
}

# Exercise to muscle group mapping
MUSCLE_GROUP_MAP = {
    # Shoulders
    'shoulder': 'Shoulders',
    'lateral raise': 'Shoulders',
    'rear delt': 'Shoulders',
    'front raise': 'Shoulders',
    'shrug': 'Shoulders',
    'face pull': 'Shoulders',
    # Chest
    'bench press': 'Chest',
    'chest': 'Chest',
    'pec': 'Chest',
    'fly': 'Chest',
    'push up': 'Chest',
    'pushup': 'Chest',
    # Back
    'row': 'Back',
    'lat pulldown': 'Back',
    'pull up': 'Back',
    'pullup': 'Back',
    'deadlift': 'Back',
    'back extension': 'Back',
    # Arms - Biceps
    'bicep': 'Biceps',
    'curl': 'Biceps',
    'hammer curl': 'Biceps',
    # Arms - Triceps
    'tricep': 'Triceps',
    'pushdown': 'Triceps',
    'skull crusher': 'Triceps',
    'dip': 'Triceps',
    # Legs - Quads
    'squat': 'Quads',
    'leg press': 'Quads',
    'leg extension': 'Quads',
    'lunge': 'Quads',
    # Legs - Hamstrings
    'leg curl': 'Hamstrings',
    'romanian deadlift': 'Hamstrings',
    'rdl': 'Hamstrings',
    # Legs - Glutes
    'hip thrust': 'Glutes',
    'glute': 'Glutes',
    'hip abduction': 'Glutes',
    'hip adduction': 'Glutes',
    # Calves
    'calf': 'Calves',
    # Core
    'ab': 'Core',
    'crunch': 'Core',
    'plank': 'Core',
    'core': 'Core',
}

# Cardio exercises to filter out of strength training charts
CARDIO_KEYWORDS = ['stair', 'treadmill', 'bike', 'elliptical', 'run', 'cardio', 'walk']


def get_muscle_group(exercise_name):
    """Map exercise name to muscle group"""
    name_lower = exercise_name.lower()
    for keyword, muscle in MUSCLE_GROUP_MAP.items():
        if keyword in name_lower:
            return muscle
    return 'Other'


def is_cardio_exercise(exercise_name):
    """Check if exercise is cardio-based"""
    name_lower = exercise_name.lower()
    return any(keyword in name_lower for keyword in CARDIO_KEYWORDS)


# --- DATA LOADING FUNCTIONS ---
@st.cache_data(ttl=300)
def load_hevy_data():
    """Load and prepare hevy workout data"""
    if not os.path.exists(HEVY_STATS_FILE):
        return None
    try:
        df = pd.read_csv(HEVY_STATS_FILE)
        # Handle mixed date formats (ISO and US format)
        df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=False)
        df['primary_muscle_group'] = df['Exercise'].apply(get_muscle_group)
        df['is_cardio'] = df['Exercise'].apply(is_cardio_exercise)
        df['Volume'] = df['Weight (lbs)'].fillna(0) * df['Reps'].fillna(0)
        return df
    except Exception as e:
        st.error(f"Error loading Hevy data: {e}")
        return None


@st.cache_data(ttl=300)
def load_garmin_data():
    """Load and prepare garmin health data"""
    if not os.path.exists(GARMIN_STATS_FILE):
        return None
    try:
        df = pd.read_csv(GARMIN_STATS_FILE)
        # Handle mixed date formats (ISO and US format)
        df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=False)
        # Remove duplicate dates, keeping the last entry
        df = df.drop_duplicates(subset=['Date'], keep='last')
        df = df.sort_values('Date').reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Error loading Garmin data: {e}")
        return None


@st.cache_data(ttl=300)
def load_garmin_runs():
    """Load garmin running data"""
    if not os.path.exists(GARMIN_RUNS_FILE):
        return None
    try:
        df = pd.read_csv(GARMIN_RUNS_FILE)
        # Handle mixed date formats (ISO and US format)
        df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=False)
        return df
    except Exception as e:
        st.error(f"Error loading Garmin runs data: {e}")
        return None


# --- HEVY API FUNCTIONS ---
def get_or_create_hevy_folder(folder_name):
    headers = {"api-key": HEVY_API_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get("https://api.hevyapp.com/v1/routine_folders", headers=headers)
        if res.status_code == 200:
            for folder in res.json().get('routine_folders', []):
                if folder['title'] == folder_name:
                    return folder['id']
        payload = {"routine_folder": {"title": folder_name}}
        res = requests.post("https://api.hevyapp.com/v1/routine_folders", headers=headers, json=payload)
        if res.status_code in [200, 201]:
            return res.json()['routine_folder']['id']
    except Exception as e:
        st.error(f"Hevy API Error: {e}")
    return None


def upload_routine_json(json_data, folder_name):
    if not HEVY_API_KEY:
        return "Error: HEVY_API_KEY missing in .env"
    try:
        data = json.loads(json_data)
        if isinstance(data, dict):
            routines = data.get('routines', [])
        elif isinstance(data, list):
            if data and isinstance(data[0], dict) and 'routine' in data[0]:
                routines = [item['routine'] for item in data]
            else:
                routines = data
        else:
            routines = []

        if not routines:
            return "Error: No routines found in JSON"

        folder_id = None
        if folder_name and folder_name.strip():
            folder_id = get_or_create_hevy_folder(folder_name)
            if not folder_id:
                return "Error: Could not create/access folder on Hevy."

        headers = {"api-key": HEVY_API_KEY, "Content-Type": "application/json"}
        success_count = 0
        errors = []

        for idx, routine in enumerate(routines):
            payload = {"routine": routine}
            if folder_id:
                payload["routine"]["folder_id"] = folder_id
            res = requests.post("https://api.hevyapp.com/v1/routines", headers=headers, json=payload)
            if res.status_code in [200, 201]:
                success_count += 1
            else:
                try:
                    error_detail = res.json() if res.headers.get('content-type') == 'application/json' else res.text
                except:
                    error_detail = res.text
                errors.append(f"#{idx+1} '{routine.get('title', 'Unknown')}': {error_detail}")

        msg = f"Uploaded {success_count}/{len(routines)} routines"
        if folder_name and folder_id and success_count > 0:
            msg += f" to '{folder_name}'"
        if errors:
            msg += f" | Issues: {'; '.join(errors[:3])}"
        return msg

    except json.JSONDecodeError as je:
        return f"Error: Invalid JSON - {str(je)}"
    except requests.exceptions.RequestException as re:
        return f"Network Error: {str(re)}"
    except Exception as e:
        return f"System Error: {str(e)}"


# --- SYSTEM MONITORING FUNCTIONS ---
def check_internet():
    try:
        subprocess.check_call(["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "ONLINE", "green"
    except:
        return "OFFLINE", "red"


def check_git_status():
    try:
        output = subprocess.check_output(["git", "describe", "--always", "--dirty"],
                                         cwd=PROJECT_DIR).decode().strip()
        if "dirty" in output:
            return f"{output} (Unsaved)", "orange"
        return output, "green"
    except:
        return "Git Error", "red"


def check_error_count():
    if not os.path.exists(LOG_FILE):
        return 0, "green"
    try:
        cmd = f"tail -n 2000 {LOG_FILE} | grep -c -i -E 'ERROR|Traceback'"
        count = int(subprocess.check_output(cmd, shell=True).decode().strip())
        if count == 0:
            return "0 Found", "green"
        else:
            return f"{count} ISSUES", "red"
    except subprocess.CalledProcessError:
        return "0 Found", "green"
    except:
        return "Scan Failed", "orange"


def get_logs():
    if not os.path.exists(LOG_FILE):
        return ["Log file not found."]
    try:
        lines = subprocess.check_output(['tail', '-n', '30', LOG_FILE]).decode('utf-8').splitlines()
        return lines[::-1]
    except:
        return ["Error reading log."]


def get_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            seconds = float(f.readline().split()[0])
        return str(timedelta(seconds=int(seconds)))
    except:
        return "Unknown"


def get_cpu_load():
    try:
        load1, load5, _ = os.getloadavg()
        return f"{load1:.2f} / {load5:.2f}"
    except:
        return "N/A"


def get_ram_usage():
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                meminfo[parts[0].strip(':')] = int(parts[1])
        total = meminfo.get('MemTotal', 1)
        used = total - meminfo.get('MemAvailable', 1)
        return f"{int(used/1024)}MB / {int(total/1024)}MB ({int(used/total*100)}%)"
    except:
        return "N/A"


def get_poe_fan():
    try:
        with open("/sys/class/thermal/cooling_device0/cur_state", "r") as f:
            speed = int(f.read())
        return "OFF" if speed == 0 else f"ON (Lvl {speed})"
    except:
        return "N/A"


def get_disk_usage(path):
    try:
        if not os.path.exists(path):
            return "N/A"
        st_fs = os.statvfs(path)
        total = st_fs.f_blocks * st_fs.f_frsize
        used = total - (st_fs.f_bavail * st_fs.f_frsize)
        return f"{int(used/(1024**3))}GB / {int(total/(1024**3))}GB ({int(used/total*100)}%)"
    except:
        return "Error"


def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000.0
    except:
        return 0


# --- SCHEDULING FUNCTIONS ---
def get_next_run(interval, sched):
    now = datetime.now()
    if interval == 'hourly':
        target = now.replace(minute=sched.get('minute', 0), second=0, microsecond=0)
        if target <= now:
            target += timedelta(hours=1)
    elif interval == 'daily':
        target = now.replace(hour=sched.get('hour', 0), minute=sched.get('minute', 0), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
    elif interval == 'weekly':
        cron_dow = sched.get('dow', 0)
        target_dow = (cron_dow - 1) % 7
        target = now.replace(hour=sched.get('hour', 0), minute=sched.get('minute', 0), second=0, microsecond=0)
        days_ahead = target_dow - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        target += timedelta(days=days_ahead)
        if days_ahead == 0 and target <= now:
            target += timedelta(days=7)
    elif interval == 'monthly':
        target = now.replace(day=sched.get('day', 1), hour=sched.get('hour', 0),
                             minute=sched.get('minute', 0), second=0, microsecond=0)
        if target <= now:
            month = 1 if now.month == 12 else now.month + 1
            year = now.year + (1 if now.month == 12 else 0)
            target = target.replace(month=month, year=year)
    else:
        target = now
    return target


def get_last_scheduled_run(interval, sched):
    """Calculate when the task was last supposed to run"""
    now = datetime.now()
    if interval == 'hourly':
        target = now.replace(minute=sched.get('minute', 0), second=0, microsecond=0)
        if target > now:
            target -= timedelta(hours=1)
    elif interval == 'daily':
        target = now.replace(hour=sched.get('hour', 0), minute=sched.get('minute', 0), second=0, microsecond=0)
        if target > now:
            target -= timedelta(days=1)
    elif interval == 'weekly':
        cron_dow = sched.get('dow', 0)
        target_dow = (cron_dow - 1) % 7
        target = now.replace(hour=sched.get('hour', 0), minute=sched.get('minute', 0), second=0, microsecond=0)
        days_back = (now.weekday() - target_dow) % 7
        target -= timedelta(days=days_back)
        if target > now:
            target -= timedelta(days=7)
    elif interval == 'monthly':
        target = now.replace(day=sched.get('day', 1), hour=sched.get('hour', 0),
                            minute=sched.get('minute', 0), second=0, microsecond=0)
        if target > now:
            # Go back to previous month
            if now.month == 1:
                target = target.replace(year=now.year - 1, month=12)
            else:
                target = target.replace(month=now.month - 1)
    else:
        target = now
    return target


def analyze_task(name, config):
    filepath = config['path']
    interval = config['interval']
    sched = config['sched']

    if filepath and os.path.exists(filepath):
        mod_ts = os.path.getmtime(filepath)
        dt_mod = datetime.fromtimestamp(mod_ts)
        last_run_str = dt_mod.strftime("%b %d %H:%M")
        seconds_ago = (datetime.now() - dt_mod).total_seconds()
        exists = True
    else:
        if filepath and os.path.exists(os.path.dirname(filepath)):
            last_run_str = "NO FILE"
        else:
            last_run_str = "BAD FOLDER"
        seconds_ago = 999999999
        exists = False

    # Calculate next and last scheduled run times
    next_dt = get_next_run(interval, sched)
    last_scheduled = get_last_scheduled_run(interval, sched)

    # Time since last scheduled run
    time_since_scheduled = (datetime.now() - last_scheduled).total_seconds()

    # Grace periods (in seconds)
    GRACE_PERIOD = 24 * 3600  # 24 hours grace before "STALE"
    OUTDATED_PERIOD = 48 * 3600  # 48 hours before "OUTDATED"

    status = "STALE"
    color = "orange"

    # Special handling for Hevy Ticker (LED display process)
    if name == "Hevy Ticker":
        if not exists:
            status, color = "NO LOG", "gray"
        elif seconds_ago < 7200:  # Updated within 2 hours
            status, color = "ACTIVE", "green"
        elif seconds_ago < 14400:  # 2-4 hours
            status, color = "CHECK", "orange"
        else:  # More than 4 hours
            status, color = "INACTIVE", "red"
    # Standard scheduled task logic
    elif exists:
        # Did it run after the last scheduled time?
        ran_on_schedule = dt_mod >= last_scheduled - timedelta(minutes=5)

        if ran_on_schedule:
            status, color = "UPDATED", "green"
        elif time_since_scheduled < GRACE_PERIOD:
            status, color = "WAITING", "blue"
        elif time_since_scheduled < OUTDATED_PERIOD:
            status, color = "STALE", "orange"
        else:
            status, color = "OUTDATED", "red"
    else:
        status = last_run_str
        color = "gray"

    # Format next run string
    if next_dt.date() == datetime.now().date():
        next_run_str = f"Today {next_dt.strftime('%H:%M')}"
    elif next_dt.date() == (datetime.now() + timedelta(days=1)).date():
        next_run_str = f"Tomorrow {next_dt.strftime('%H:%M')}"
    else:
        next_run_str = next_dt.strftime("%b %d %H:%M")

    return {
        "name": name,
        "last_run": last_run_str,
        "next_run": next_run_str,
        "status": status,
        "color": color,
        "command": config.get('command', '')
    }


# --- PROMPT EDITOR FUNCTIONS ---
def load_prompt_content():
    try:
        if os.path.exists(PROMPT_FILE):
            with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "ERROR: Prompt file not found at " + PROMPT_FILE
    except Exception as e:
        return f"ERROR: Could not read prompt file: {e}"


def save_prompt_content(content):
    try:
        with open(PROMPT_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, "Prompt saved successfully!"
    except Exception as e:
        return False, f"ERROR: Could not save prompt: {e}"


# --- STREAMLIT APP ---
st.set_page_config(
    page_title="Fitness Command Center",
    page_icon="💪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark theme
st.markdown("""
<style>
    .stMetric {
        background-color: #1a1e28;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #282c34;
    }
    .status-green { color: #4caf50; font-weight: bold; }
    .status-blue { color: #2196f3; font-weight: bold; }
    .status-orange { color: #ff9800; font-weight: bold; }
    .status-red { color: #f44336; font-weight: bold; }
    .status-gray { color: #7f8c8d; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR: Date Range Filter ---
st.sidebar.title("Filters")
st.sidebar.markdown("---")

# Date range filter
default_end = datetime.now().date()
default_start = default_end - timedelta(days=30)

date_range = st.sidebar.date_input(
    "Date Range",
    value=(default_start, default_end),
    max_value=default_end,
    key="date_range"
)

if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = default_start, default_end

start_datetime = pd.Timestamp(start_date)
end_datetime = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

st.sidebar.markdown("---")
st.sidebar.info(f"Showing data from {start_date} to {end_date}")

# Chart options
st.sidebar.markdown("---")
st.sidebar.subheader("Chart Options")
show_trend_lines = st.sidebar.checkbox("Show Trend Lines", value=True, help="Overlay smooth average trend lines on charts")

# Mission Status filter
st.sidebar.markdown("---")
st.sidebar.subheader("Mission Status")
all_tasks = list(TRACKED_FILES.keys())
selected_tasks = st.sidebar.multiselect(
    "Tasks to Display",
    options=all_tasks,
    default=all_tasks,
    help="Select which tasks to show in Mission Status"
)

# --- MAIN CONTENT ---
st.title("Fitness Command Center")

# Create tabs for fitness data
tab1, tab2, tab3 = st.tabs(["Training (Hevy)", "Recovery (Garmin)", "System & Tools"])

# --- TAB 1: Training (Hevy) ---
with tab1:
    hevy_df = load_hevy_data()

    if hevy_df is None:
        st.warning("Hevy workout data file not found. Please check the file path.")
    else:
        # Filter by date range
        mask = (hevy_df['Date'] >= start_datetime) & (hevy_df['Date'] <= end_datetime)
        filtered_hevy = hevy_df[mask].copy()

        if filtered_hevy.empty:
            st.warning("No workout data found for the selected date range.")
        else:
            # Calculate previous period for comparison
            period_days = (end_datetime - start_datetime).days + 1
            prev_start = start_datetime - pd.Timedelta(days=period_days)
            prev_end = start_datetime - pd.Timedelta(seconds=1)
            prev_mask = (hevy_df['Date'] >= prev_start) & (hevy_df['Date'] <= prev_end)
            prev_hevy = hevy_df[prev_mask].copy()

            # Metric Cards
            col1, col2, col3, col4 = st.columns(4)

            # Current period metrics
            total_workouts = filtered_hevy.groupby(['Date', 'Workout']).ngroups
            total_volume = filtered_hevy['Volume'].sum()
            total_sets = len(filtered_hevy)
            unique_exercises = filtered_hevy['Exercise'].nunique()

            # Previous period metrics for comparison
            prev_workouts = prev_hevy.groupby(['Date', 'Workout']).ngroups if not prev_hevy.empty else 0
            prev_volume = prev_hevy['Volume'].sum() if not prev_hevy.empty else 0
            prev_sets = len(prev_hevy) if not prev_hevy.empty else 0

            # Calculate deltas
            delta_workouts = total_workouts - prev_workouts if prev_workouts > 0 else None
            delta_volume = total_volume - prev_volume if prev_volume > 0 else None
            delta_sets = total_sets - prev_sets if prev_sets > 0 else None

            with col1:
                st.metric("Total Workouts", total_workouts,
                         delta=f"{delta_workouts:+d}" if delta_workouts is not None else None)
            with col2:
                st.metric("Total Volume", f"{total_volume:,.0f} lbs",
                         delta=f"{delta_volume:+,.0f}" if delta_volume is not None else None)
            with col3:
                st.metric("Total Sets", total_sets,
                         delta=f"{delta_sets:+d}" if delta_sets is not None else None)
            with col4:
                st.metric("Unique Exercises", unique_exercises)

            st.markdown("---")

            # Charts Row
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                st.subheader("Volume Progression")
                # Calculate weekly volume
                weekly_volume = filtered_hevy.copy()
                weekly_volume['Week'] = weekly_volume['Date'].dt.to_period('W').dt.start_time
                weekly_agg = weekly_volume.groupby('Week')['Volume'].sum().reset_index()

                fig_volume = go.Figure()

                # Main line
                fig_volume.add_trace(go.Scatter(
                    x=weekly_agg['Week'],
                    y=weekly_agg['Volume'],
                    mode='lines+markers',
                    name='Weekly Volume',
                    line=dict(color='#61afef'),
                    marker=dict(color='#98c379')
                ))

                # Add trend line if enabled
                if show_trend_lines and len(weekly_agg) >= 3:
                    # Use exponential weighted moving average for smoother trend
                    span = max(4, len(weekly_agg) // 3)
                    weekly_agg['Trend'] = weekly_agg['Volume'].ewm(span=span, adjust=False).mean()
                    fig_volume.add_trace(go.Scatter(
                        x=weekly_agg['Week'],
                        y=weekly_agg['Trend'],
                        mode='lines',
                        name='Trend',
                        line=dict(color='#e5c07b', width=3, shape='spline')
                    ))

                fig_volume.update_layout(
                    title="Weekly Training Volume (Weight x Reps)",
                    xaxis_title="Week",
                    yaxis_title="Volume (lbs)",
                    template="plotly_dark",
                    height=400,
                    legend=dict(x=0.5, y=1.1, xanchor='center', orientation='h')
                )
                st.plotly_chart(fig_volume, use_container_width=True)

            with chart_col2:
                st.subheader("Muscle Group Split")
                # Filter out cardio from muscle group analysis
                strength_only = filtered_hevy[~filtered_hevy['is_cardio']].copy()
                muscle_volume = strength_only.groupby('primary_muscle_group')['Volume'].sum().reset_index()
                muscle_volume = muscle_volume.sort_values('Volume', ascending=False)

                fig_muscle = px.pie(
                    muscle_volume,
                    values='Volume',
                    names='primary_muscle_group',
                    title="Volume per Muscle Group (lbs)",
                    hole=0.4
                )
                fig_muscle.update_layout(
                    template="plotly_dark",
                    height=400
                )
                st.plotly_chart(fig_muscle, use_container_width=True)

            # Additional muscle group bar chart
            st.subheader("Muscle Group Distribution")
            fig_bar = px.bar(
                muscle_volume,
                x='primary_muscle_group',
                y='Volume',
                title="Total Volume by Muscle Group (Strength Training Only)",
                color='Volume',
                color_continuous_scale='Blues'
            )
            fig_bar.update_layout(
                xaxis_title="Muscle Group",
                yaxis_title="Volume (lbs)",
                template="plotly_dark",
                height=350
            )
            st.plotly_chart(fig_bar, use_container_width=True)

            # TODO: Muscle Heat Map Visualization (disabled - needs mannequin-style body map)
            # muscle_dict = dict(zip(muscle_volume['primary_muscle_group'], muscle_volume['Volume']))

            # --- CARDIO SECTION ---
            st.markdown("---")
            st.subheader("Cardio Training (Garmin Runs)")

            runs_df = load_garmin_runs()
            if runs_df is not None:
                # Distance unit toggle
                distance_unit = st.radio(
                    "Distance Unit",
                    options=["Kilometers", "Miles"],
                    horizontal=True,
                    key="cardio_distance_unit"
                )
                use_miles = distance_unit == "Miles"
                km_to_miles = 0.621371

                # Filter by date range
                runs_mask = (runs_df['Date'] >= start_datetime) & (runs_df['Date'] <= end_datetime)
                filtered_runs = runs_df[runs_mask].copy()

                if not filtered_runs.empty:
                    # Calculate previous period for comparison (trend arrows)
                    period_days = (end_datetime - start_datetime).days + 1
                    prev_start = start_datetime - pd.Timedelta(days=period_days)
                    prev_end = start_datetime - pd.Timedelta(seconds=1)
                    prev_runs_mask = (runs_df['Date'] >= prev_start) & (runs_df['Date'] <= prev_end)
                    prev_runs = runs_df[prev_runs_mask].copy()

                    # Cardio metrics
                    cardio_col1, cardio_col2, cardio_col3, cardio_col4, cardio_col5 = st.columns(5)

                    total_runs = len(filtered_runs)
                    prev_total_runs = len(prev_runs) if not prev_runs.empty else 0

                    # Calculate distance from speed and duration if distance column doesn't exist
                    if 'distance' in filtered_runs.columns:
                        total_distance_km = filtered_runs['distance'].sum() / 1000
                    elif 'averageSpeed' in filtered_runs.columns and 'duration' in filtered_runs.columns:
                        filtered_runs['distance_calc'] = filtered_runs['averageSpeed'] * filtered_runs['duration']
                        total_distance_km = filtered_runs['distance_calc'].sum() / 1000
                    else:
                        total_distance_km = 0

                    # Previous period distance
                    if not prev_runs.empty:
                        if 'distance' in prev_runs.columns:
                            prev_distance_km = prev_runs['distance'].sum() / 1000
                        elif 'averageSpeed' in prev_runs.columns and 'duration' in prev_runs.columns:
                            prev_runs['distance_calc'] = prev_runs['averageSpeed'] * prev_runs['duration']
                            prev_distance_km = prev_runs['distance_calc'].sum() / 1000
                        else:
                            prev_distance_km = 0
                    else:
                        prev_distance_km = 0

                    # Calculate average distance per run
                    avg_distance_km = total_distance_km / total_runs if total_runs > 0 else 0
                    prev_avg_distance_km = prev_distance_km / prev_total_runs if prev_total_runs > 0 else 0

                    avg_hr = filtered_runs['averageHR'].mean() if 'averageHR' in filtered_runs.columns else 0
                    prev_avg_hr = prev_runs['averageHR'].mean() if not prev_runs.empty and 'averageHR' in prev_runs.columns else None

                    avg_duration = filtered_runs['duration'].mean() / 60 if 'duration' in filtered_runs.columns else 0
                    prev_avg_duration = prev_runs['duration'].mean() / 60 if not prev_runs.empty and 'duration' in prev_runs.columns else None

                    # Convert to display units
                    if use_miles:
                        total_distance = total_distance_km * km_to_miles
                        prev_distance = prev_distance_km * km_to_miles
                        avg_distance = avg_distance_km * km_to_miles
                        prev_avg_distance = prev_avg_distance_km * km_to_miles
                        dist_unit = "mi"
                    else:
                        total_distance = total_distance_km
                        prev_distance = prev_distance_km
                        avg_distance = avg_distance_km
                        prev_avg_distance = prev_avg_distance_km
                        dist_unit = "km"

                    # Calculate deltas
                    delta_runs = total_runs - prev_total_runs if prev_total_runs > 0 else None
                    delta_distance = total_distance - prev_distance if prev_distance > 0 else None
                    delta_avg_distance = avg_distance - prev_avg_distance if prev_avg_distance > 0 else None
                    delta_hr = avg_hr - prev_avg_hr if prev_avg_hr is not None and pd.notna(prev_avg_hr) else None
                    delta_duration = avg_duration - prev_avg_duration if prev_avg_duration is not None and pd.notna(prev_avg_duration) else None

                    with cardio_col1:
                        st.metric("Total Runs", total_runs,
                                 delta=f"{delta_runs:+d}" if delta_runs is not None else None)
                    with cardio_col2:
                        st.metric("Total Distance", f"{total_distance:.1f} {dist_unit}",
                                 delta=f"{delta_distance:+.1f}" if delta_distance is not None else None)
                    with cardio_col3:
                        st.metric("Avg Run Distance", f"{avg_distance:.2f} {dist_unit}",
                                 delta=f"{delta_avg_distance:+.2f}" if delta_avg_distance is not None else None)
                    with cardio_col4:
                        st.metric("Avg Heart Rate", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "N/A",
                                 delta=f"{delta_hr:+.0f}" if delta_hr is not None else None,
                                 delta_color="inverse")
                    with cardio_col5:
                        st.metric("Avg Duration", f"{avg_duration:.1f} min" if pd.notna(avg_duration) else "N/A",
                                 delta=f"{delta_duration:+.1f}" if delta_duration is not None else None)

                    # Cardio charts
                    cardio_chart_col1, cardio_chart_col2 = st.columns(2)

                    with cardio_chart_col1:
                        # Distance over time
                        if 'averageSpeed' in filtered_runs.columns and 'duration' in filtered_runs.columns:
                            filtered_runs['distance_km'] = (filtered_runs['averageSpeed'] * filtered_runs['duration']) / 1000
                            if use_miles:
                                filtered_runs['distance_display'] = filtered_runs['distance_km'] * km_to_miles
                            else:
                                filtered_runs['distance_display'] = filtered_runs['distance_km']
                            fig_distance = px.bar(
                                filtered_runs,
                                x='Date',
                                y='distance_display',
                                title="Running Distance Over Time",
                                color='averageHR',
                                color_continuous_scale='Reds'
                            )
                            fig_distance.update_layout(
                                xaxis_title="Date",
                                yaxis_title=f"Distance ({dist_unit})",
                                template="plotly_dark",
                                height=350
                            )
                            st.plotly_chart(fig_distance, use_container_width=True)

                    with cardio_chart_col2:
                        # Heart Rate Zones
                        zone_cols = ['hrTimeInZone_1', 'hrTimeInZone_2', 'hrTimeInZone_3', 'hrTimeInZone_4']
                        available_zones = [c for c in zone_cols if c in filtered_runs.columns]

                        if available_zones:
                            zone_sums = {col: filtered_runs[col].sum() / 60 for col in available_zones}  # Convert to minutes
                            zone_labels = ['Zone 1 (Easy)', 'Zone 2 (Fat Burn)', 'Zone 3 (Cardio)', 'Zone 4 (Peak)']
                            zone_data = pd.DataFrame({
                                'Zone': zone_labels[:len(available_zones)],
                                'Minutes': list(zone_sums.values())
                            })

                            fig_zones = px.pie(
                                zone_data,
                                values='Minutes',
                                names='Zone',
                                title="Heart Rate Zone Distribution (Total Minutes)",
                                hole=0.4,
                                color_discrete_sequence=['#4CAF50', '#FFC107', '#FF9800', '#F44336']
                            )
                            fig_zones.update_layout(
                                template="plotly_dark",
                                height=350
                            )
                            st.plotly_chart(fig_zones, use_container_width=True)

                    # Speed/Pace trend
                    if 'averageSpeed' in filtered_runs.columns:
                        # Convert m/s to pace (min/km or min/mi)
                        filtered_runs['pace_min_km'] = 1000 / (filtered_runs['averageSpeed'] * 60)
                        if use_miles:
                            # Convert min/km to min/mi (1 mile = 1.60934 km)
                            filtered_runs['pace_display'] = filtered_runs['pace_min_km'] * 1.60934
                            pace_unit = "min/mi"
                        else:
                            filtered_runs['pace_display'] = filtered_runs['pace_min_km']
                            pace_unit = "min/km"
                        fig_pace = px.line(
                            filtered_runs,
                            x='Date',
                            y='pace_display',
                            markers=True,
                            title="Running Pace Trend (lower is faster)"
                        )
                        fig_pace.update_layout(
                            xaxis_title="Date",
                            yaxis_title=f"Pace ({pace_unit})",
                            template="plotly_dark",
                            height=300
                        )
                        fig_pace.update_traces(line_color='#e06c75', marker_color='#e5c07b')
                        st.plotly_chart(fig_pace, use_container_width=True)
                else:
                    st.info("No running data found for the selected date range.")
            else:
                st.info("Garmin runs data file not found.")


# --- TAB 2: Recovery (Garmin) ---
with tab2:
    garmin_df = load_garmin_data()

    if garmin_df is None:
        st.warning("Garmin health data file not found. Please check the file path.")
    else:
        # Filter by date range
        mask = (garmin_df['Date'] >= start_datetime) & (garmin_df['Date'] <= end_datetime)
        filtered_garmin = garmin_df[mask].copy()

        if filtered_garmin.empty:
            st.warning("No Garmin data found for the selected date range.")
        else:
            # Calculate previous period for comparison
            period_days = (end_datetime - start_datetime).days + 1
            prev_start = start_datetime - pd.Timedelta(days=period_days)
            prev_end = start_datetime - pd.Timedelta(seconds=1)
            prev_mask = (garmin_df['Date'] >= prev_start) & (garmin_df['Date'] <= prev_end)
            prev_garmin = garmin_df[prev_mask].copy()

            # Metric Cards
            col1, col2, col3, col4 = st.columns(4)

            # Current period metrics
            avg_sleep = filtered_garmin['Sleep Score'].mean()

            # Calculate HRV properly - check if column exists and has any non-null values
            if 'HRV Avg' in filtered_garmin.columns:
                hrv_values = filtered_garmin['HRV Avg'].dropna()
                avg_hrv = hrv_values.mean() if not hrv_values.empty else None
            else:
                avg_hrv = None

            avg_rhr = filtered_garmin['RHR'].mean() if 'RHR' in filtered_garmin.columns else None
            avg_steps = filtered_garmin['Steps'].mean() if 'Steps' in filtered_garmin.columns else None

            # Previous period metrics
            prev_sleep = prev_garmin['Sleep Score'].mean() if not prev_garmin.empty else None
            prev_hrv = None
            if not prev_garmin.empty and 'HRV Avg' in prev_garmin.columns:
                prev_hrv_values = prev_garmin['HRV Avg'].dropna()
                prev_hrv = prev_hrv_values.mean() if not prev_hrv_values.empty else None
            prev_rhr = prev_garmin['RHR'].mean() if not prev_garmin.empty and 'RHR' in prev_garmin.columns else None
            prev_steps = prev_garmin['Steps'].mean() if not prev_garmin.empty and 'Steps' in prev_garmin.columns else None

            # Calculate deltas
            delta_sleep = avg_sleep - prev_sleep if pd.notna(avg_sleep) and pd.notna(prev_sleep) else None
            delta_hrv = avg_hrv - prev_hrv if avg_hrv is not None and prev_hrv is not None else None
            delta_rhr = avg_rhr - prev_rhr if pd.notna(avg_rhr) and pd.notna(prev_rhr) else None
            delta_steps = avg_steps - prev_steps if pd.notna(avg_steps) and pd.notna(prev_steps) else None

            with col1:
                st.metric("Avg Sleep Score", f"{avg_sleep:.1f}" if pd.notna(avg_sleep) else "N/A",
                         delta=f"{delta_sleep:+.1f}" if delta_sleep is not None else None)
            with col2:
                st.metric("Avg HRV", f"{avg_hrv:.1f}" if avg_hrv is not None and pd.notna(avg_hrv) else "No data",
                         delta=f"{delta_hrv:+.1f}" if delta_hrv is not None else None)
            with col3:
                st.metric("Avg RHR", f"{avg_rhr:.1f} bpm" if avg_rhr is not None and pd.notna(avg_rhr) else "N/A",
                         delta=f"{delta_rhr:+.1f}" if delta_rhr is not None else None,
                         delta_color="inverse")  # Lower RHR is better
            with col4:
                st.metric("Avg Steps", f"{avg_steps:,.0f}" if avg_steps is not None and pd.notna(avg_steps) else "N/A",
                         delta=f"{delta_steps:+,.0f}" if delta_steps is not None else None)

            st.markdown("---")

            # Charts Row
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                st.subheader("Body Weight Trend")
                weight_data = filtered_garmin[filtered_garmin['Weight (lbs)'].notna()].copy()

                if not weight_data.empty:
                    fig_weight = go.Figure()

                    # Main weight line
                    fig_weight.add_trace(go.Scatter(
                        x=weight_data['Date'],
                        y=weight_data['Weight (lbs)'],
                        mode='lines+markers',
                        name='Weight',
                        line=dict(color='#e06c75'),
                        marker=dict(color='#e5c07b')
                    ))

                    # Add trend line if enabled
                    if show_trend_lines and len(weight_data) >= 3:
                        weight_data = weight_data.sort_values('Date')
                        span = max(7, len(weight_data) // 4)
                        weight_data['Trend'] = weight_data['Weight (lbs)'].ewm(span=span, adjust=False).mean()
                        fig_weight.add_trace(go.Scatter(
                            x=weight_data['Date'],
                            y=weight_data['Trend'],
                            mode='lines',
                            name='Trend',
                            line=dict(color='#c678dd', width=3, shape='spline')
                        ))

                    fig_weight.update_layout(
                        title="Body Weight Over Time",
                        xaxis_title="Date",
                        yaxis_title="Weight (lbs)",
                        template="plotly_dark",
                        height=400,
                        legend=dict(x=0.5, y=1.1, xanchor='center', orientation='h')
                    )
                    st.plotly_chart(fig_weight, use_container_width=True)
                else:
                    st.info("No weight data available for the selected period.")

            with chart_col2:
                st.subheader("Sleep & HRV")
                # Create multi-line chart for Sleep Score and HRV
                fig_recovery = go.Figure()

                if 'Sleep Score' in filtered_garmin.columns:
                    sleep_data = filtered_garmin[filtered_garmin['Sleep Score'].notna()].copy()
                    sleep_data = sleep_data.sort_values('Date')
                    fig_recovery.add_trace(go.Scatter(
                        x=sleep_data['Date'],
                        y=sleep_data['Sleep Score'],
                        mode='lines+markers',
                        name='Sleep Score',
                        line=dict(color='#98c379'),
                        yaxis='y'
                    ))

                    # Add sleep trend line
                    if show_trend_lines and len(sleep_data) >= 3:
                        span = max(7, len(sleep_data) // 4)
                        sleep_data['Sleep_Trend'] = sleep_data['Sleep Score'].ewm(span=span, adjust=False).mean()
                        fig_recovery.add_trace(go.Scatter(
                            x=sleep_data['Date'],
                            y=sleep_data['Sleep_Trend'],
                            mode='lines',
                            name='Sleep Trend',
                            line=dict(color='#98c379', width=3, shape='spline'),
                            yaxis='y'
                        ))

                if 'HRV Avg' in filtered_garmin.columns:
                    hrv_data = filtered_garmin[filtered_garmin['HRV Avg'].notna()].copy()
                    if not hrv_data.empty:
                        hrv_data = hrv_data.sort_values('Date')
                        fig_recovery.add_trace(go.Scatter(
                            x=hrv_data['Date'],
                            y=hrv_data['HRV Avg'],
                            mode='lines+markers',
                            name='HRV Avg',
                            line=dict(color='#61afef'),
                            yaxis='y2'
                        ))

                        # Add HRV trend line
                        if show_trend_lines and len(hrv_data) >= 3:
                            span = max(7, len(hrv_data) // 4)
                            hrv_data['HRV_Trend'] = hrv_data['HRV Avg'].ewm(span=span, adjust=False).mean()
                            fig_recovery.add_trace(go.Scatter(
                                x=hrv_data['Date'],
                                y=hrv_data['HRV_Trend'],
                                mode='lines',
                                name='HRV Trend',
                                line=dict(color='#61afef', width=3, shape='spline'),
                                yaxis='y2'
                            ))

                fig_recovery.update_layout(
                    title="Sleep Score vs HRV Average",
                    xaxis_title="Date",
                    yaxis=dict(title="Sleep Score", side='left', color='#98c379'),
                    yaxis2=dict(title="HRV Avg", side='right', overlaying='y', color='#61afef'),
                    template="plotly_dark",
                    height=400,
                    legend=dict(x=0.5, y=1.15, xanchor='center', orientation='h')
                )
                st.plotly_chart(fig_recovery, use_container_width=True)

            # Steps and RHR trends
            st.subheader("Daily Activity Metrics")
            steps_col, rhr_col = st.columns(2)

            with steps_col:
                if 'Steps' in filtered_garmin.columns:
                    steps_data = filtered_garmin[filtered_garmin['Steps'].notna()]
                    if not steps_data.empty:
                        fig_steps = px.bar(
                            steps_data,
                            x='Date',
                            y='Steps',
                            title="Daily Steps"
                        )
                        fig_steps.update_layout(
                            template="plotly_dark",
                            height=300
                        )
                        fig_steps.update_traces(marker_color='#c678dd')
                        st.plotly_chart(fig_steps, use_container_width=True)

            with rhr_col:
                if 'RHR' in filtered_garmin.columns:
                    rhr_data = filtered_garmin[filtered_garmin['RHR'].notna()]
                    if not rhr_data.empty:
                        fig_rhr = px.line(
                            rhr_data,
                            x='Date',
                            y='RHR',
                            markers=True,
                            title="Resting Heart Rate"
                        )
                        fig_rhr.update_layout(
                            template="plotly_dark",
                            height=300
                        )
                        fig_rhr.update_traces(line_color='#e06c75', marker_color='#e5c07b')
                        st.plotly_chart(fig_rhr, use_container_width=True)


# --- TAB 3: System & Tools ---
with tab3:
    # Create sub-sections
    st.header("Hevy JSON Uploader")

    with st.form("hevy_upload_form"):
        folder_name = st.text_input("Folder Name (optional)", value="Dashboard Uploads",
                                    help="Leave empty for no folder")
        json_data = st.text_area("Paste JSON Routine", height=200,
                                 placeholder='{"routines": [{"title": "Chest Day", "exercises": [...]}]}')

        col1, col2 = st.columns([1, 4])
        with col1:
            submitted = st.form_submit_button("Upload to Hevy", type="primary")

        if submitted:
            if json_data.strip():
                result = upload_routine_json(json_data, folder_name)
                if "Error" in result or "error" in result.lower():
                    st.error(result)
                else:
                    st.success(result)
            else:
                st.warning("Please paste JSON data before uploading.")

    st.markdown("---")

    # Mission Status
    st.header("Mission Status")

    # Filter tasks based on sidebar selection
    filtered_tracked = {k: v for k, v in TRACKED_FILES.items() if k in selected_tasks}
    tasks = [analyze_task(name, conf) for name, conf in filtered_tracked.items()]

    if not tasks:
        st.info("No tasks selected. Use the sidebar to choose which tasks to display.")
    else:
        # Create task table
        task_cols = st.columns([2, 2, 2, 1, 1])
        task_cols[0].markdown("**Task**")
        task_cols[1].markdown("**Last Update**")
        task_cols[2].markdown("**Next Run**")
        task_cols[3].markdown("**Status**")
        task_cols[4].markdown("**Action**")

    for task in tasks:
        cols = st.columns([2, 2, 2, 1, 1])
        cols[0].write(task['name'])
        cols[1].write(task['last_run'])
        cols[2].write(task['next_run'])

        # Use color class directly from task
        cols[3].markdown(f"<span class='status-{task['color']}'>{task['status']}</span>",
                         unsafe_allow_html=True)

        if cols[4].button("Run", key=f"run_{task['name']}"):
            if task['command']:
                subprocess.Popen(task['command'], shell=True)
                st.toast(f"Started: {task['name']}")
                time.sleep(0.5)
                st.rerun()

    st.markdown("---")

    # History Import Section
    st.header("History Import")
    st.caption("Import historical data from Garmin and Hevy. Select a start date and run the imports.")

    # Date picker for history import
    history_col1, history_col2 = st.columns([1, 2])

    with history_col1:
        history_start_date = st.date_input(
            "Start Date",
            value=datetime.now().date() - timedelta(days=365),
            max_value=datetime.now().date(),
            key="history_start_date",
            help="Import data from this date forward"
        )

    with history_col2:
        st.markdown(f"**Selected:** {history_start_date.isoformat()}")
        st.caption("Data will be imported from this date to yesterday.")

    # History import buttons
    hist_col1, hist_col2, hist_col3, hist_col4 = st.columns(4)

    history_date_str = history_start_date.isoformat()

    with hist_col1:
        if st.button("Import Garmin Health", key="run_history_garmin"):
            cmd = f"cd {PROJECT_DIR} && /usr/bin/python3 history_garmin_import.py {history_date_str} >> {LOG_FILE} 2>&1"
            subprocess.Popen(cmd, shell=True)
            st.toast(f"Started: Garmin Health History (from {history_date_str})")
            st.success("Garmin Health import started! Check logs for progress.")

    with hist_col2:
        if st.button("Import Garmin Runs", key="run_history_runs"):
            cmd = f"cd {PROJECT_DIR} && /usr/bin/python3 history_garmin_runs.py {history_date_str} >> {LOG_FILE} 2>&1"
            subprocess.Popen(cmd, shell=True)
            st.toast(f"Started: Garmin Runs History (from {history_date_str})")
            st.success("Garmin Runs import started! Check logs for progress.")

    with hist_col3:
        if st.button("Import Hevy Workouts", key="run_history_hevy"):
            cmd = f"cd {PROJECT_DIR} && /usr/bin/python3 history_hevy_import.py {history_date_str} >> {LOG_FILE} 2>&1"
            subprocess.Popen(cmd, shell=True)
            st.toast(f"Started: Hevy History (from {history_date_str})")
            st.success("Hevy Workouts import started! Check logs for progress.")

    with hist_col4:
        if st.button("Run All Imports", type="primary", key="run_all_history"):
            # Run all three imports
            cmd1 = f"cd {PROJECT_DIR} && /usr/bin/python3 history_garmin_import.py {history_date_str} >> {LOG_FILE} 2>&1"
            cmd2 = f"cd {PROJECT_DIR} && /usr/bin/python3 history_garmin_runs.py {history_date_str} >> {LOG_FILE} 2>&1"
            cmd3 = f"cd {PROJECT_DIR} && /usr/bin/python3 history_hevy_import.py {history_date_str} >> {LOG_FILE} 2>&1"
            subprocess.Popen(cmd1, shell=True)
            subprocess.Popen(cmd2, shell=True)
            subprocess.Popen(cmd3, shell=True)
            st.toast(f"Started: All History Imports (from {history_date_str})")
            st.success("All imports started! Check logs for progress.")

    st.markdown("---")

    # System Vitals
    st.header("System Vitals")

    vitals_col1, vitals_col2, vitals_col3 = st.columns(3)

    with vitals_col1:
        internet_status, internet_color = check_internet()
        git_status, git_color = check_git_status()
        error_count, error_color = check_error_count()

        st.markdown(f"**Internet:** :{internet_color}[{internet_status}]")
        st.markdown(f"**Git Version:** :{git_color}[{git_status}]")
        st.markdown(f"**Log Errors:** :{error_color}[{error_count}]")

    with vitals_col2:
        st.markdown(f"**Uptime:** {get_uptime()}")
        cpu_temp = get_cpu_temp()
        temp_color = "red" if cpu_temp > 70 else "green"
        st.markdown(f"**CPU Temp:** :{temp_color}[{cpu_temp}C]")
        st.markdown(f"**CPU Load:** {get_cpu_load()}")

    with vitals_col3:
        st.markdown(f"**RAM:** {get_ram_usage()}")
        st.markdown(f"**Storage (SD):** {get_disk_usage('/')}")
        drive_online = os.path.ismount(DRIVE_PATH)
        drive_color = "green" if drive_online else "red"
        drive_text = "ONLINE" if drive_online else "OFFLINE"
        st.markdown(f"**Drive Mount:** :{drive_color}[{drive_text}]")

    st.markdown("---")

    # System Controls
    st.header("System Controls")

    # Initialize session state for restart confirmation
    if 'confirm_restart' not in st.session_state:
        st.session_state.confirm_restart = False
    if 'confirm_dashboard_restart' not in st.session_state:
        st.session_state.confirm_dashboard_restart = False

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns(3)

    with ctrl_col1:
        if st.button("Restart Dashboard", type="secondary"):
            st.session_state.confirm_dashboard_restart = True

        if st.session_state.confirm_dashboard_restart:
            st.warning("Restart dashboard service?")
            confirm_col1, confirm_col2 = st.columns(2)
            with confirm_col1:
                if st.button("Yes, Restart Dashboard", type="primary", key="confirm_dash_restart"):
                    try:
                        subprocess.Popen(["sudo", "systemctl", "restart", "ai-fitness-dashboard.service"])
                        st.success("Dashboard restart initiated...")
                        st.session_state.confirm_dashboard_restart = False
                        time.sleep(2)
                    except Exception as e:
                        st.error(f"Error: {e}")
            with confirm_col2:
                if st.button("Cancel", key="cancel_dash_restart"):
                    st.session_state.confirm_dashboard_restart = False
                    st.rerun()

    with ctrl_col2:
        if st.button("Reboot System", type="secondary"):
            st.session_state.confirm_restart = True

        if st.session_state.confirm_restart:
            st.warning("Are you sure you want to reboot the Raspberry Pi?")
            confirm_col1, confirm_col2 = st.columns(2)
            with confirm_col1:
                if st.button("Yes, Reboot", type="primary", key="confirm_reboot"):
                    try:
                        subprocess.Popen(["sudo", "reboot"])
                        st.success("System reboot initiated...")
                        st.session_state.confirm_restart = False
                    except Exception as e:
                        st.error(f"Error: {e}")
            with confirm_col2:
                if st.button("Cancel", key="cancel_reboot"):
                    st.session_state.confirm_restart = False
                    st.rerun()

    with ctrl_col3:
        if st.button("Clear Streamlit Cache", type="secondary"):
            st.cache_data.clear()
            st.success("Cache cleared!")
            time.sleep(1)
            st.rerun()

    st.markdown("---")

    # Configuration Section
    st.header("Configuration")

    with st.expander("View/Edit Environment Settings (.env)", expanded=False):
        env_file = os.path.join(PROJECT_DIR, ".env")

        if os.path.exists(env_file):
            try:
                with open(env_file, 'r') as f:
                    env_content = f.read()

                # Parse and display settings (hide passwords)
                st.markdown("**Current Settings:**")
                for line in env_content.split('\n'):
                    if line.strip() and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Mask sensitive values
                        if 'PASSWORD' in key.upper() or 'KEY' in key.upper() or 'SECRET' in key.upper():
                            if len(value) > 8:
                                display_value = value[:4] + "****" + value[-4:]
                            else:
                                display_value = "****"
                        else:
                            display_value = value
                        st.text(f"{key} = {display_value}")
            except Exception as e:
                st.error(f"Error reading .env: {e}")
        else:
            st.warning("No .env file found. Run setup.py to configure.")

        st.markdown("---")
        st.markdown("**Run Setup Script:**")
        st.code(f"cd {PROJECT_DIR} && python3 setup.py", language="bash")
        st.caption("Run this command in terminal to reconfigure settings interactively.")

    st.markdown("---")

    # Monthly Prompt Editor
    st.header("Monthly Prompt Editor")

    prompt_content = load_prompt_content()

    # Initialize session state for prompt editor
    if 'original_prompt' not in st.session_state:
        st.session_state.original_prompt = prompt_content
    if 'confirm_save' not in st.session_state:
        st.session_state.confirm_save = False

    edited_prompt = st.text_area("Edit AI Training Prompt", value=prompt_content, height=300, key="prompt_editor")

    # Check if content has changed
    has_changes = edited_prompt != st.session_state.original_prompt

    st.caption(f"File: MONTHLY_PROMPT_TEXT.txt | {len(edited_prompt)} characters" +
               (" | **Unsaved changes**" if has_changes else ""))

    col_save, col_reset = st.columns([1, 1])

    with col_save:
        if st.button("Save Prompt", type="primary", disabled=not has_changes):
            st.session_state.confirm_save = True

    with col_reset:
        if st.button("Reset Changes", disabled=not has_changes):
            st.session_state.original_prompt = prompt_content
            st.rerun()

    # Confirmation dialog
    if st.session_state.confirm_save:
        st.warning("Are you sure you want to save these changes?")
        confirm_col1, confirm_col2 = st.columns([1, 1])
        with confirm_col1:
            if st.button("Yes, Save", type="primary"):
                success, message = save_prompt_content(edited_prompt)
                if success:
                    st.session_state.original_prompt = edited_prompt
                    st.session_state.confirm_save = False
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
        with confirm_col2:
            if st.button("Cancel"):
                st.session_state.confirm_save = False
                st.rerun()

    st.markdown("---")

    # System Logs
    st.header("System Logs (Newest First)")

    logs = get_logs()
    log_text = "\n".join(logs)
    st.code(log_text, language="text")

    if st.button("Refresh Logs"):
        st.rerun()
