"""
=== Program Overview ===
1. Required libraries:
   - pip install aiohttp

2. Execution order:
   - First run: execute smartthings_auth.py → token file created
   - After: just run this script. Token is refreshed automatically.

3. Data collection logic:
   - Updates device metadata every 10 minutes.
   - Fetches all device statuses in parallel every 1 minute.
   - Collected data is saved to CSV files under YYYYMMDD date folders.
   - Saved to separate CSV files by device type:
     * Smart plug (SMP): power, energy
     * Motion sensor: motion, temperature
   - Devices with missing fields or errors are added to the ban list.

4. Token management:
   - access_token expires every 24 hours.
   - Automatically refreshes using refresh_token 30 minutes before expiry.
   - Immediately attempts token refresh on 401 response.
   - Safely shuts down on token refresh failure.

5. Network error handling:
   - Retries with exponential backoff on transient errors like DNS failures. (max 5 times)
"""

import os
import csv
import json
import base64
import aiohttp
import asyncio
import logging
import signal
from datetime import datetime, timedelta
from pathlib import Path

# === Load config.json ===
def _load_config():
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            "config.json not found.\n"
            "Copy config.example.json to config.json\n"
            "and fill in CLIENT_ID and CLIENT_SECRET."
        )
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)

_config = _load_config()

# === Logging setup ===
LOG_FILE = os.path.abspath("C:/smartthings_data/logs/smartthings.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# === OAuth settings ===
CLIENT_ID     = _config["CLIENT_ID"]
CLIENT_SECRET = _config["CLIENT_SECRET"]
REDIRECT_URI  = "https://httpbin.org/get"
TOKEN_URL     = "https://api.smartthings.com/oauth/token"
TOKEN_FILE    = os.path.abspath("C:/smartthings_data/tokens/oauth_token.json")
os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

# === API settings ===
API_BASE_URL = "https://api.smartthings.com/v1"

# === Path settings ===
CSV_BASE_DIR  = os.path.abspath("C:/smartthings_data/csv_data")
METADATA_FILE = os.path.abspath("C:/smartthings_data/metadata/device_metadata.json")
BAN_LIST_FILE = os.path.abspath("C:/smartthings_data/ban_list.json")
os.makedirs(os.path.dirname(METADATA_FILE), exist_ok=True)

# === Interval settings (seconds) ===
DEVICE_UPDATE_INTERVAL = 600
DEVICE_STATUS_INTERVAL = 60

# === Retry settings ===
MAX_RETRIES     = 5
BASE_RETRY_WAIT = 5
MAX_RETRY_WAIT  = 60

# === Token expiry margin ===
TOKEN_REFRESH_MARGIN = timedelta(minutes=30)

# === Session timeout ===
SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

# === Local state ===
device_metadata  = []
ban_list         = []
running          = True
current_date     = datetime.now().strftime("%Y%m%d")
last_update_time = None

# === Token state ===
token_data = {
    "access_token":  None,
    "refresh_token": None,
    "expires_at":    None,
}
token_refreshing = False

# === Shared dashboard state ===
dashboard_state = {
    "status":        "Initializing",
    "last_cycle":    None,
    "token_expires": None,
    "total":         0,
    "success":       0,
    "fail":          0,
    "devices":       [],
}
on_data_updated = None

# === Network error types ===
_retriable = [
    aiohttp.ClientConnectorError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientOSError,
    asyncio.TimeoutError,
]
if hasattr(aiohttp, "ClientConnectorDNSError"):
    _retriable.append(aiohttp.ClientConnectorDNSError)
RETRIABLE_EXCEPTIONS = tuple(_retriable)


# ==============================
# Token management
# ==============================

def load_token():
    global token_data
    if not os.path.exists(TOKEN_FILE):
        logging.error(
            f"Token file not found: {TOKEN_FILE}\n"
            "Please run smartthings_auth.py first to obtain a token."
        )
        return False

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    token_data["access_token"]  = raw.get("access_token")
    token_data["refresh_token"] = raw.get("refresh_token")

    if "expires_at" in raw:
        token_data["expires_at"] = datetime.fromisoformat(raw["expires_at"])
    elif "expires_in" in raw:
        token_data["expires_at"] = datetime.now() + timedelta(seconds=int(raw["expires_in"]))
    else:
        token_data["expires_at"] = datetime.now() + timedelta(hours=24)

    logging.info(
        f"Token loaded. Expires at: {token_data['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}"
    )
    dashboard_state["token_expires"] = token_data["expires_at"].strftime("%Y-%m-%d %H:%M:%S")
    return True


def save_token():
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "access_token":  token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_at":    token_data["expires_at"].isoformat(),
        }, f, ensure_ascii=False, indent=4)
    logging.info("Token file updated.")
    dashboard_state["token_expires"] = token_data["expires_at"].strftime("%Y-%m-%d %H:%M:%S")


def get_headers():
    return {"Authorization": f"Bearer {token_data['access_token']}"}


def make_basic_auth_header():
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def is_token_expiring():
    if token_data["expires_at"] is None:
        return True
    return datetime.now() >= token_data["expires_at"] - TOKEN_REFRESH_MARGIN


async def refresh_access_token():
    global token_data, token_refreshing

    if token_refreshing:
        logging.info("Another request is refreshing the token. Waiting...")
        while token_refreshing:
            await asyncio.sleep(0.5)
        return token_data["access_token"] is not None

    token_refreshing = True
    logging.info("Starting access_token refresh...")

    if not token_data["refresh_token"]:
        logging.error("No refresh_token. Please re-run smartthings_auth.py.")
        token_refreshing = False
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": token_data["refresh_token"],
                    "client_id":     CLIENT_ID,
                },
                headers={
                    "Content-Type":  "application/x-www-form-urlencoded",
                    "Authorization": make_basic_auth_header(),
                },
                timeout=SESSION_TIMEOUT
            ) as resp:
                if resp.status == 200:
                    raw = await resp.json()
                    token_data["access_token"] = raw["access_token"]
                    if "refresh_token" in raw:
                        token_data["refresh_token"] = raw["refresh_token"]
                    expires_in = int(raw.get("expires_in", 86400))
                    token_data["expires_at"] = datetime.now() + timedelta(seconds=expires_in)
                    save_token()
                    logging.info(
                        f"access_token refreshed successfully. "
                        f"New expiry: {token_data['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    token_refreshing = False
                    return True
                elif resp.status == 401:
                    logging.error(
                        "refresh_token has expired. (Expires after 29 days of inactivity) "
                        "Please re-run smartthings_auth.py to re-authenticate."
                    )
                    token_refreshing = False
                    return False
                else:
                    text = await resp.text()
                    logging.error(f"Token refresh failed ({resp.status}): {text}")
                    token_refreshing = False
                    return False
    except Exception as e:
        logging.error(f"Error during token refresh: {type(e).__name__}: {e}")
        token_refreshing = False
        return False


# ==============================
# Metadata / Ban list
# ==============================

def load_metadata():
    global device_metadata
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            device_metadata = json.load(f)
        logging.info(f"Metadata loaded. ({len(device_metadata)} device(s))")
    else:
        logging.warning("Metadata file not found. Initial update required.")

def save_metadata():
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(device_metadata, f, ensure_ascii=False, indent=4)
    logging.info(f"Metadata saved: {METADATA_FILE}\n")

def load_ban_list():
    global ban_list
    if os.path.exists(BAN_LIST_FILE):
        with open(BAN_LIST_FILE, "r", encoding="utf-8") as f:
            ban_list = json.load(f)
        logging.info(f"Ban list loaded. ({len(ban_list)} device(s))")
    else:
        logging.info("Ban list file not found. Starting fresh.")

def save_ban_list():
    with open(BAN_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(ban_list, f, ensure_ascii=False, indent=4)
    logging.info(f"Ban list saved. ({len(ban_list)} device(s))")


# ==============================
# CSV saving
# ==============================

def save_plug_to_csv(device_status, device_id):
    """Save smart plug data: power, energy."""
    global current_date
    today_date  = datetime.now().strftime("%Y%m%d")
    folder_path = os.path.join(CSV_BASE_DIR, today_date)
    if today_date != current_date or not os.path.exists(folder_path):
        current_date = today_date
        os.makedirs(folder_path, exist_ok=True)

    filename    = f"{device_status['label']}_{device_id}_{today_date}.csv"
    filepath    = os.path.join(folder_path, filename)
    file_exists = os.path.isfile(filepath)

    try:
        with open(filepath, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow([
                    "Timestamp", "Label", "Location", "Room",
                    "Power (W)", "Energy (Wh)"
                ])
            writer.writerow([
                device_status["timestamp"],
                device_status["label"],
                device_status["location_name"],
                device_status["room_name"],
                device_status["power"],
                device_status["energy"],
            ])
        logging.info(
            f"CSV saved [Plug]: {device_status['label']} | "
            f"Power={device_status['power']}W, Energy={device_status['energy']}Wh"
        )
    except Exception as e:
        logging.error(f"CSV save error ({device_status['label']}): {e}")


def save_motion_to_csv(device_status, device_id):
    """Save motion sensor data: motion, temperature."""
    global current_date
    today_date  = datetime.now().strftime("%Y%m%d")
    folder_path = os.path.join(CSV_BASE_DIR, today_date)
    if today_date != current_date or not os.path.exists(folder_path):
        current_date = today_date
        os.makedirs(folder_path, exist_ok=True)

    filename    = f"{device_status['label']}_{device_id}_{today_date}.csv"
    filepath    = os.path.join(folder_path, filename)
    file_exists = os.path.isfile(filepath)

    try:
        with open(filepath, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow([
                    "Timestamp", "Label", "Location", "Room",
                    "Motion", "Temperature (°C)"
                ])
            writer.writerow([
                device_status["timestamp"],
                device_status["label"],
                device_status["location_name"],
                device_status["room_name"],
                device_status["motion"],
                device_status["temperature"],
            ])
        logging.info(
            f"CSV saved [Motion]: {device_status['label']} | "
            f"Motion={device_status['motion']}, "
            f"Temp={device_status['temperature']}°C"
        )
    except Exception as e:
        logging.error(f"CSV save error ({device_status['label']}): {e}")


# ==============================
# API requests (retry + auto 401 refresh)
# ==============================

async def request_with_retry(session, url, context="request"):
    global running
    wait = BASE_RETRY_WAIT
    token_refreshed = False

    if is_token_expiring():
        success = await refresh_access_token()
        if not success:
            logging.error("Halting request due to token refresh failure.")
            return None
        token_refreshed = True

    for attempt in range(1, MAX_RETRIES + 1):
        if not running:
            return None
        try:
            async with session.get(url, headers=get_headers()) as resp:
                if resp.status == 200:
                    return await resp.json()

                elif resp.status == 401:
                    if token_refreshed:
                        logging.error(
                            f"[{context}] 401 persists after token refresh. Shutting down."
                        )
                        running = False
                        return None
                    logging.warning(f"[{context}] 401 Unauthorized → attempting token refresh...")
                    success = await refresh_access_token()
                    if not success:
                        logging.error("Token refresh failed. Shutting down.")
                        running = False
                        return None
                    token_refreshed = True
                    continue

                elif resp.status == 403:
                    if attempt <= 2:
                        logging.warning(f"[{context}] HTTP 403 ({attempt}/2 attempt(s). {wait}s, retrying...")
                        await asyncio.sleep(wait)
                        wait = min(wait * 2, MAX_RETRY_WAIT)
                        continue
                    else:
                        logging.warning(f"[{context}] HTTP 403. Retry limit reached.")
                        return None

                elif 400 <= resp.status < 500:
                    logging.warning(f"[{context}] HTTP {resp.status}. Not retrying.")
                    return None

                else:
                    logging.warning(f"[{context}] HTTP {resp.status}. (attempt {attempt}/{MAX_RETRIES})")

        except RETRIABLE_EXCEPTIONS as e:
            logging.warning(
                f"[{context}] Network error (attempt {attempt}/{MAX_RETRIES}): "
                f"{type(e).__name__}: {e}"
            )
        except Exception as e:
            logging.error(f"[{context}] Unexpected error: {type(e).__name__}: {e}")
            return None

        if attempt < MAX_RETRIES:
            logging.info(f"[{context}] {wait}s, retrying...")
            await asyncio.sleep(wait)
            wait = min(wait * 2, MAX_RETRY_WAIT)

    logging.error(f"[{context}] Max retries exceeded.")
    return None


# ==============================
# API fetch functions
# ==============================

async def fetch_location_name(session, location_id):
    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/locations/{location_id}",
        context=f"Location lookup ({location_id})"
    )
    return data.get("name", "Unknown") if data else "Unknown"


async def fetch_room_name(session, location_id, room_id):
    """Fetch room name. Returns empty string if roomId is missing."""
    if not room_id:
        return ""
    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/locations/{location_id}/rooms/{room_id}",
        context=f"Room lookup ({room_id})"
    )
    return data.get("name", "") if data else ""


async def fetch_device_list(session):
    """Fetch device list and update metadata.
    - Smart plugs starting with SMP
    - Motion sensors (label contains "Motion" or type is ZIGBEE)
    All others are added to the ban list.
    """
    global device_metadata, ban_list

    data = await request_with_retry(session, f"{API_BASE_URL}/devices", context="Device list fetch")
    if data is None:
        logging.error("Device list fetch failed. Keeping existing metadata.")
        return

    metadata = []
    location_cache = {}  # Cache: location_id → location_name

    for device in data.get("items", []):
        label       = device.get("label", "")
        device_id   = device["deviceId"]
        location_id = device.get("locationId", "")
        room_id     = device.get("roomId", "")  # None or empty string if missing

        # Smart plug (SMP)
        is_plug   = label.startswith("SMP")
        # Motion sensor (label contains "Motion" or device name contains "motion")
        dev_name  = device.get("name", "")
        is_motion = "motion" in dev_name.lower() or "Motion Sensor" in label

        if not (is_plug or is_motion):
            if device_id not in ban_list:
                ban_list.append(device_id)
                logging.info(f"Not a target device, added to ban list: {label} (ID={device_id})")
            continue

        # Cache location name (avoid duplicate API calls)
        if location_id not in location_cache:
            location_cache[location_id] = await fetch_location_name(session, location_id)
        location_name = location_cache[location_id]

        # Fetch room name
        room_name = await fetch_room_name(session, location_id, room_id)

        device_type = "plug" if is_plug else "motion"
        metadata.append({
            "id":            device_id,
            "label":         label,
            "location_id":   location_id,
            "location_name": location_name,
            "room_name":     room_name,
            "type":          device_type,
        })
        logging.info(
            f"Device registered: [{device_type}] {label} | "
            f"Location={location_name}, Room={room_name or '(none)'}"
        )

    device_metadata = metadata
    save_ban_list()
    logging.info(
        f"Device list updated. "
        f"Plugs: {sum(1 for d in metadata if d['type']=='plug')}, "
        f"Motion sensors: {sum(1 for d in metadata if d['type']=='motion')}"
    )
    save_metadata()


async def fetch_plug_status(session, device):
    """Fetch smart plug status: power, energy."""
    device_id = device["id"]
    if device_id in ban_list:
        return None

    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/devices/{device_id}/status",
        context=f"Plug status ({device['label']})"
    )
    if data is None:
        return None

    try:
        main   = data.get("components", {}).get("main", {})
        power  = main.get("powerMeter",  {}).get("power",  {}).get("value")
        energy = main.get("energyMeter", {}).get("energy", {}).get("value")

        if power is None or energy is None:
            raise KeyError("power/energy field missing")

        status = {
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label":         device["label"],
            "location_name": device["location_name"],
            "room_name":     device["room_name"],
            "power":         power,
            "energy":        energy,
            "type":          "plug",
        }
        save_plug_to_csv(status, device_id)
        return status

    except KeyError as e:
        logging.error(f"Missing field, added to ban list: {device['label']} ({e})")
        if device_id not in ban_list:
            ban_list.append(device_id)
            save_ban_list()
        return None


async def fetch_motion_status(session, device):
    """Fetch motion sensor status: motion, temperature."""
    device_id = device["id"]
    if device_id in ban_list:
        return None

    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/devices/{device_id}/status",
        context=f"Motion status ({device['label']})"
    )
    if data is None:
        return None

    try:
        main        = data.get("components", {}).get("main", {})
        motion      = main.get("motionSensor",   {}).get("motion",      {}).get("value")
        temperature = main.get("temperatureMeasurement", {}).get("temperature", {}).get("value")

        if motion is None:
            raise KeyError("motion field missing")

        status = {
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label":         device["label"],
            "location_name": device["location_name"],
            "room_name":     device["room_name"],
            "motion":        motion,       # "active" or "inactive"
            "temperature":   temperature,  # float (°C), None if unavailable
            "type":          "motion",
        }
        save_motion_to_csv(status, device_id)
        return status

    except KeyError as e:
        logging.error(f"Missing field, added to ban list: {device['label']} ({e})")
        if device_id not in ban_list:
            ban_list.append(device_id)
            save_ban_list()
        return None


# ==============================
# Periodic tasks
# ==============================

async def periodic_tasks(session):
    global last_update_time

    while running:
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"================= Time: {start_time} =================")

        # Update device list every 10 minutes
        now = datetime.now()
        if now.minute % 10 == 0 and (
            last_update_time is None or last_update_time.minute != now.minute
        ):
            last_update_time = now
            await fetch_device_list(session)

        # Fetch all devices in parallel (plug/motion)
        tasks = []
        for device in device_metadata:
            if device["type"] == "plug":
                tasks.append(fetch_plug_status(session, device))
            else:
                tasks.append(fetch_motion_status(session, device))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update dashboard_state
        device_rows   = []
        success_count = 0
        fail_count    = 0

        for result, device in zip(results, device_metadata):
            if isinstance(result, Exception) or result is None:
                fail_count += 1
                device_rows.append({
                    "label":    device["label"],
                    "location": device["location_name"],
                    "room":     device["room_name"],
                    "type":     device["type"],
                    "power":    "-",
                    "energy":   "-",
                    "motion":   "-",
                    "temp":     "-",
                    "battery":  "-",
                    "status":   "Fail",
                    "updated":  start_time,
                })
                if isinstance(result, Exception):
                    logging.error(f"Device {device['label']} error: {result}")
            else:
                success_count += 1
                if device["type"] == "plug":
                    device_rows.append({
                        "label":    device["label"],
                        "location": device["location_name"],
                        "room":     device["room_name"],
                        "type":     "plug",
                        "power":    result["power"],
                        "energy":   result["energy"],
                        "motion":   "-",
                        "temp":     "-",
                        "battery":  "-",
                        "status":   "OK",
                        "updated":  start_time,
                    })
                else:
                    device_rows.append({
                        "label":    device["label"],
                        "location": device["location_name"],
                        "room":     device["room_name"],
                        "type":     "motion",
                        "power":    "-",
                        "energy":   "-",
                        "motion":   result["motion"],
                        "temp":     result["temperature"] if result["temperature"] is not None else "-",
                        "battery":  "-",
                        "status":   "OK",
                        "updated":  start_time,
                    })

        dashboard_state["status"]    = "Collecting"
        dashboard_state["last_cycle"] = start_time
        dashboard_state["total"]     = len(device_metadata)
        dashboard_state["success"]   = success_count
        dashboard_state["fail"]      = fail_count
        dashboard_state["devices"]   = device_rows

        if on_data_updated:
            try:
                on_data_updated()
            except Exception:
                pass

        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"================= Done: {end_time} =================\n")

        await asyncio.sleep(DEVICE_STATUS_INTERVAL)


# ==============================
# Scheduler
# ==============================

async def scheduler():
    global running
    os.makedirs(CSV_BASE_DIR, exist_ok=True)

    while running:
        try:
            connector = aiohttp.TCPConnector(
                limit=20,
                ttl_dns_cache=300,
                enable_cleanup_closed=True
            )
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=SESSION_TIMEOUT
            ) as session:
                logging.info("Fetching latest device list...")
                await fetch_device_list(session)

                while running:
                    await periodic_tasks(session)

        except RETRIABLE_EXCEPTIONS as e:
            logging.error(
                f"Session-level network error: {type(e).__name__}: {e}\n"
                f"{BASE_RETRY_WAIT}s, recreating session..."
            )
            await asyncio.sleep(BASE_RETRY_WAIT)

        except Exception as e:
            if not running:
                break
            logging.error(
                f"Scheduler error: {type(e).__name__}: {e}\n"
                f"{BASE_RETRY_WAIT}s, restarting..."
            )
            await asyncio.sleep(BASE_RETRY_WAIT)

    logging.info("Scheduler shut down safely.")


# ==============================
# Utilities
# ==============================

def print_device_list():
    if not device_metadata:
        logging.warning("Device list is empty.")
    else:
        logging.info("=== Current Device List ===")
        for idx, device in enumerate(device_metadata, start=1):
            logging.info(
                f"{idx}. [{device['type']}] {device['label']} | "
                f"Location={device['location_name']}, Room={device['room_name'] or '(none)'}"
            )
        logging.info("======================\n")


def shutdown_handler(signum, frame):
    global running
    logging.info("Shutdown signal received. Cleaning up...")
    running = False


# ==============================
# Main
# ==============================

if __name__ == "__main__":
    signal.signal(signal.SIGINT,  shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logging.info("Starting SmartThings data collection.")

    if not load_token():
        logging.error("Please run smartthings_auth.py first.")
        exit(1)

    load_metadata()
    load_ban_list()
    print_device_list()

    try:
        logging.info("Starting data collection. Press Ctrl+C to stop.")
        asyncio.run(scheduler())
    finally:
        try:
            asyncio.run(asyncio.sleep(0))
        except RuntimeError:
            pass
        logging.info("Program terminated normally.")
