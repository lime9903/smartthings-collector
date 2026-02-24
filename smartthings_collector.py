"""
=== 프로그램 설명 ===
1. 필요한 라이브러리:
   - pip install aiohttp

2. 실행 순서:
   - 최초 1회: smartthings_auth.py 실행 → 토큰 파일 생성
   - 이후: 이 스크립트만 실행하면 됩니다. 토큰은 자동 갱신됩니다.

3. 데이터 수집 로직:
   - 10분마다 모든 기기의 메타데이터를 업데이트합니다.
   - 12초마다 모든 기기의 상태를 병렬로 조회합니다.
   - 수집된 데이터는 YYYYMMDD 형식의 날짜 기반 폴더 안에 CSV 파일로 저장됩니다.
   - 조회 중 필드 누락 또는 오류가 발생한 기기는 "밴 목록"에 추가됩니다.

4. 토큰 관리:
   - access_token은 24시간마다 만료됩니다.
   - 만료 30분 전에 refresh_token을 사용해 자동으로 갱신합니다.
   - 401 응답 수신 시 즉시 토큰 갱신을 시도합니다.
   - 토큰 갱신 실패 시 프로그램을 안전하게 종료합니다.

5. 네트워크 오류 처리:
   - DNS 오류 등 일시적 오류 발생 시 지수 백오프로 재시도합니다. (최대 5회)
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

# === 로깅 설정 ===
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

# === OAuth 설정 ===
CLIENT_ID     = "075a7bc0-263d-4343-b383-c855f9380654"
CLIENT_SECRET = "776977f3-99bb-4e3e-81c0-668800235b15"
REDIRECT_URI  = "https://httpbin.org/get"
TOKEN_URL     = "https://api.smartthings.com/oauth/token"
TOKEN_FILE    = os.path.abspath("C:/smartthings_data/tokens/oauth_token.json")
os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

# === API 설정 ===
API_BASE_URL = "https://api.smartthings.com/v1"

# === 경로 설정 ===
CSV_BASE_DIR  = os.path.abspath("C:/smartthings_data/csv_data")
METADATA_FILE = os.path.abspath("C:/smartthings_data/metadata/device_metadata.json")
BAN_LIST_FILE = os.path.abspath("C:/smartthings_data/ban_list.json")
os.makedirs(os.path.dirname(METADATA_FILE), exist_ok=True)

# === 인터벌 설정 (초) ===
DEVICE_UPDATE_INTERVAL = 600
DEVICE_STATUS_INTERVAL = 60

# === 재시도 설정 ===
MAX_RETRIES     = 5
BASE_RETRY_WAIT = 5
MAX_RETRY_WAIT  = 60

# === 토큰 만료 여유 시간 ===
TOKEN_REFRESH_MARGIN = timedelta(minutes=30)  # 만료 30분 전 갱신

# === 세션 타임아웃 ===
SESSION_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

# === 로컬 관리 데이터 ===
device_metadata  = []
ban_list         = []
running          = True
current_date     = datetime.now().strftime("%Y%m%d")
last_update_time = None

# === 토큰 관리 ===
token_data = {
    "access_token":  None,
    "refresh_token": None,
    "expires_at":    None,
}
token_refreshing = False  # race condition 방지: 동시에 하나의 갱신만 허용

# === 대시보드 공유 상태 ===
dashboard_state = {
    "status":        "초기화 중",
    "last_cycle":    None,
    "token_expires": None,
    "total":         0,
    "success":       0,
    "fail":          0,
    "devices":       [],
}
on_data_updated = None  # 수집 완료 시 대시보드가 등록하는 콜백 함수

# === 네트워크 오류 판별 ===
# ClientConnectorDNSError는 aiohttp 버전에 따라 없을 수 있으므로 동적으로 처리
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
# 토큰 관리 함수
# ==============================

def load_token():
    """저장된 토큰 파일을 로드합니다."""
    global token_data
    if not os.path.exists(TOKEN_FILE):
        logging.error(
            f"토큰 파일이 없습니다: {TOKEN_FILE}\n"
            "smartthings_auth.py를 먼저 실행해서 토큰을 발급받아주세요."
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
        f"토큰 로드 완료. 만료 시각: {token_data['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}"
    )
    dashboard_state["token_expires"] = token_data["expires_at"].strftime("%Y-%m-%d %H:%M:%S")
    return True


def save_token():
    """현재 토큰 데이터를 파일에 저장합니다."""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "access_token":  token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_at":    token_data["expires_at"].isoformat(),
        }, f, ensure_ascii=False, indent=4)
    logging.info("토큰 파일이 갱신되었습니다.")
    dashboard_state["token_expires"] = token_data["expires_at"].strftime("%Y-%m-%d %H:%M:%S")


def get_headers():
    """현재 access_token으로 Authorization 헤더를 반환합니다."""
    return {"Authorization": f"Bearer {token_data['access_token']}"}


def make_basic_auth_header():
    """SmartThings 토큰 엔드포인트용 Basic Auth 헤더를 생성합니다."""
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def is_token_expiring():
    """토큰이 만료 30분 이내이면 True를 반환합니다."""
    if token_data["expires_at"] is None:
        return True
    return datetime.now() >= token_data["expires_at"] - TOKEN_REFRESH_MARGIN


async def refresh_access_token():
    """
    refresh_token으로 새 access_token을 발급받습니다.
    - 동시 갱신 요청은 락으로 차단 (race condition 방지)
    - refresh_token 만료(401) 시 명확한 오류 메시지 출력
    - 성공 시 True, 실패 시 False 반환
    """
    global token_data, token_refreshing

    # 이미 갱신 중이면 완료될 때까지 대기 후 True 반환 (중복 갱신 방지)
    if token_refreshing:
        logging.info("다른 요청이 토큰을 갱신 중입니다. 완료를 기다립니다...")
        while token_refreshing:
            await asyncio.sleep(0.5)
        return token_data["access_token"] is not None

    token_refreshing = True
    logging.info("access_token 갱신을 시작합니다...")

    if not token_data["refresh_token"]:
        logging.error("refresh_token이 없습니다. smartthings_auth.py를 다시 실행해주세요.")
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
                        f"access_token 갱신 성공. "
                        f"새 만료 시각: {token_data['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    token_refreshing = False
                    return True
                elif resp.status == 401:
                    # refresh_token 자체가 만료된 경우
                    logging.error("refresh_token이 만료되었습니다. (29일 미사용 시 만료) smartthings_auth.py를 다시 실행해서 재인증해주세요.")
                    token_refreshing = False
                    return False
                else:
                    text = await resp.text()
                    logging.error(f"토큰 갱신 실패 ({resp.status}): {text}")
                    token_refreshing = False
                    return False
    except Exception as e:
        logging.error(f"토큰 갱신 중 오류: {type(e).__name__}: {e}")
        token_refreshing = False
        return False


# ==============================
# 메타데이터 / 밴 목록 관리
# ==============================

def load_metadata():
    global device_metadata
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            device_metadata = json.load(f)
        logging.info(f"메타데이터 로드 완료. ({len(device_metadata)}개 기기)")
    else:
        logging.warning("메타데이터 파일이 없습니다. 초기 업데이트가 필요합니다.")

def save_metadata():
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(device_metadata, f, ensure_ascii=False, indent=4)
    logging.info(f"메타데이터 저장 완료: {METADATA_FILE}\n")

def load_ban_list():
    global ban_list
    if os.path.exists(BAN_LIST_FILE):
        with open(BAN_LIST_FILE, "r", encoding="utf-8") as f:
            ban_list = json.load(f)
        logging.info(f"밴 목록 로드 완료. ({len(ban_list)}개 기기)")
    else:
        logging.info("밴 목록 파일이 없습니다. 초기화된 상태로 시작합니다.")

def save_ban_list():
    with open(BAN_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(ban_list, f, ensure_ascii=False, indent=4)
    logging.info(f"밴 목록 저장 완료. ({len(ban_list)}개 기기)")


# ==============================
# CSV 저장
# ==============================

def save_to_csv(device_status, device_id):
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
                writer.writerow(["Timestamp", "Label", "Location Name", "Power (W)", "Energy (Wh)"])
            writer.writerow([
                device_status["timestamp"],
                device_status["label"],
                device_status["location_name"],
                device_status["power"],
                device_status["energy"]
            ])
        logging.info(
            f"CSV 저장: Label={device_status['label']}, "
            f"Power={device_status['power']}W, Energy={device_status['energy']}Wh"
        )
    except Exception as e:
        logging.error(f"CSV 저장 중 오류: {e}")


# ==============================
# API 요청 (재시도 + 401 자동 갱신)
# ==============================

async def request_with_retry(session, url, context="요청"):
    """
    GET 요청을 수행합니다.
    - 요청 전 토큰 만료 임박 시 자동 갱신
    - 네트워크 오류 시 지수 백오프로 최대 MAX_RETRIES 회 재시도
    - 401 응답 시 토큰 갱신 후 1회만 재시도 (중복 갱신 방지)
    - 403 응답 시 최대 2회 재시도 (일시적 권한 오류 대응)
    - 모든 재시도 실패 시 None 반환
    """
    global running
    wait = BASE_RETRY_WAIT
    token_refreshed = False  # 이 요청에서 이미 토큰 갱신을 했는지 추적

    # 요청 전 토큰 만료 임박 확인
    if is_token_expiring():
        success = await refresh_access_token()
        if not success:
            logging.error("토큰 갱신 실패로 요청을 중단합니다.")
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
                        # 이미 갱신했는데도 401이면 refresh_token 문제 → 종료
                        logging.error(
                            f"[{context}] 토큰 갱신 후에도 401 발생. "
                            "refresh_token이 만료되었을 수 있습니다. 프로그램을 종료합니다."
                        )
                        running = False
                        return None
                    logging.warning(f"[{context}] 401 Unauthorized → 토큰 갱신 시도...")
                    success = await refresh_access_token()
                    if not success:
                        logging.error("토큰 갱신 실패. 프로그램을 종료합니다.")
                        running = False
                        return None
                    token_refreshed = True
                    continue  # 갱신 후 즉시 재시도

                elif resp.status == 403:
                    # 403은 일시적 권한 오류일 수 있으므로 최대 2회 재시도
                    if attempt <= 2:
                        logging.warning(
                            f"[{context}] HTTP 403. ({attempt}/2회) "
                            f"{wait}초 후 재시도..."
                        )
                        await asyncio.sleep(wait)
                        wait = min(wait * 2, MAX_RETRY_WAIT)
                        continue
                    else:
                        logging.warning(f"[{context}] HTTP 403. 재시도 초과, 건너뜁니다.")
                        return None

                elif 400 <= resp.status < 500:
                    # 그 외 4xx는 재시도해도 의미 없음
                    logging.warning(f"[{context}] HTTP {resp.status}. 재시도하지 않습니다.")
                    return None

                else:
                    logging.warning(f"[{context}] HTTP {resp.status}. (시도 {attempt}/{MAX_RETRIES})")

        except RETRIABLE_EXCEPTIONS as e:
            logging.warning(
                f"[{context}] 네트워크 오류 (시도 {attempt}/{MAX_RETRIES}): "
                f"{type(e).__name__}: {e}"
            )
        except Exception as e:
            logging.error(f"[{context}] 예상치 못한 오류: {type(e).__name__}: {e}")
            return None

        if attempt < MAX_RETRIES:
            logging.info(f"[{context}] {wait}초 후 재시도...")
            await asyncio.sleep(wait)
            wait = min(wait * 2, MAX_RETRY_WAIT)

    logging.error(f"[{context}] 최대 재시도 초과. 이번 요청을 건너뜁니다.")
    return None


# ==============================
# API 조회 함수
# ==============================

async def fetch_device_list(session):
    global device_metadata, ban_list
    data = await request_with_retry(session, f"{API_BASE_URL}/devices", context="기기 목록 조회")
    if data is None:
        logging.error("기기 목록 조회 실패. 기존 메타데이터를 유지합니다.")
        return

    metadata = []
    for device in data.get("items", []):
        label     = device["label"]
        device_id = device["deviceId"]
        if label.startswith("SMP"):
            location_name = await fetch_location_name(session, device["locationId"])
            metadata.append({"id": device_id, "label": label, "location_name": location_name})
        else:
            if device_id not in ban_list:
                ban_list.append(device_id)
                logging.warning(f"밴 목록 추가: {label} (ID={device_id})")

    device_metadata = metadata
    save_ban_list()
    logging.info(f"기기 목록 업데이트 완료. 총 {len(device_metadata)}개 기기.")
    save_metadata()


async def fetch_location_name(session, location_id):
    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/locations/{location_id}",
        context=f"위치 조회 ({location_id})"
    )
    return data.get("name", "Unknown") if data else "Unknown"


async def fetch_device_status(session, device):
    device_id = device["id"]
    if device_id in ban_list:
        return None

    data = await request_with_retry(
        session,
        f"{API_BASE_URL}/devices/{device_id}/status",
        context=f"기기 상태 ({device['label']})"
    )
    if data is None:
        # None은 네트워크/토큰 오류 → ban_list에 추가하지 않음
        return None

    try:
        main   = data.get("components", {}).get("main", {})
        power  = main.get("powerMeter",  {}).get("power",  {}).get("value")
        energy = main.get("energyMeter", {}).get("energy", {}).get("value")

        if power is None or energy is None:
            raise KeyError("필드 누락")

        device_status = {
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label":         device["label"],
            "location_name": device["location_name"],
            "power":         power,
            "energy":        energy,
        }
        save_to_csv(device_status, device_id)
        return device_status

    except KeyError as e:
        # 필드 누락은 기기 자체의 문제 → ban_list에 추가
        logging.error(f"필드 누락으로 ban_list에 추가: {device['label']} ({e})")
        if device_id not in ban_list:
            ban_list.append(device_id)
            save_ban_list()
        return None


# ==============================
# 주기적 작업
# ==============================

async def periodic_tasks(session):
    global last_update_time
    last_update_time = None

    while running:
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"================= 시간: {start_time} =================")

        # 10분마다 기기 목록 업데이트
        now = datetime.now()
        if now.minute % 10 == 0 and (
            last_update_time is None or last_update_time.minute != now.minute
        ):
            last_update_time = now
            await fetch_device_list(session)

        # 모든 기기 상태 병렬 조회
        tasks   = [fetch_device_status(session, device) for device in device_metadata]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # dashboard_state 업데이트
        device_rows   = []
        success_count = 0
        fail_count    = 0
        for result, device in zip(results, device_metadata):
            if isinstance(result, Exception) or result is None:
                fail_count += 1
                device_rows.append({
                    "label":    device["label"],
                    "location": device["location_name"],
                    "power":    "-",
                    "energy":   "-",
                    "status":   "실패",
                    "updated":  start_time,
                })
                if isinstance(result, Exception):
                    logging.error(f"기기 {device['label']} 오류: {result}")
            else:
                success_count += 1
                device_rows.append({
                    "label":    device["label"],
                    "location": device["location_name"],
                    "power":    result["power"],
                    "energy":   result["energy"],
                    "status":   "성공",
                    "updated":  start_time,
                })

        dashboard_state["status"]      = "수집 중"
        dashboard_state["last_cycle"]  = start_time
        dashboard_state["total"]       = len(device_metadata)
        dashboard_state["success"]     = success_count
        dashboard_state["fail"]        = fail_count
        dashboard_state["devices"]     = device_rows

        # 대시보드에 갱신 알림
        if on_data_updated:
            try:
                on_data_updated()
            except Exception:
                pass

        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"================= 완료: {end_time} =================\n")

        await asyncio.sleep(DEVICE_STATUS_INTERVAL)


# ==============================
# 스케줄러
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
                logging.info("최신 기기 목록을 불러옵니다...")
                await fetch_device_list(session)

                while running:
                    await periodic_tasks(session)

        except RETRIABLE_EXCEPTIONS as e:
            logging.error(
                f"세션 수준 네트워크 오류: {type(e).__name__}: {e}\n"
                f"{BASE_RETRY_WAIT}초 후 세션을 재생성합니다..."
            )
            await asyncio.sleep(BASE_RETRY_WAIT)

        except Exception as e:
            if not running:
                break
            logging.error(
                f"스케줄러 오류: {type(e).__name__}: {e}\n"
                f"{BASE_RETRY_WAIT}초 후 재시작합니다..."
            )
            await asyncio.sleep(BASE_RETRY_WAIT)

    logging.info("스케줄러가 안전하게 종료되었습니다.")


# ==============================
# 유틸리티
# ==============================

def print_device_list():
    if not device_metadata:
        logging.warning("기기 목록이 비어 있습니다.")
    else:
        logging.info("=== 현재 기기 목록 ===")
        for idx, device in enumerate(device_metadata, start=1):
            logging.info(
                f"{idx}. ID={device['id']}, Label={device['label']}, "
                f"Location={device['location_name']}"
            )
        logging.info("======================\n")

def shutdown_handler(signum, frame):
    global running
    logging.info("종료 요청 감지. 정리 중...")
    running = False


# ==============================
# 메인
# ==============================

if __name__ == "__main__":
    signal.signal(signal.SIGINT,  shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logging.info("스마트띵스 데이터 수집을 시작합니다.")

    # 토큰 로드 (없으면 종료)
    if not load_token():
        logging.error("smartthings_auth.py를 먼저 실행해주세요.")
        exit(1)

    load_metadata()
    load_ban_list()
    print_device_list()

    try:
        logging.info("데이터 수집을 시작합니다. 종료하려면 Ctrl+C를 누르세요.")
        asyncio.run(scheduler())
    finally:
        try:
            asyncio.run(asyncio.sleep(0))
        except RuntimeError:
            pass
        logging.info("프로그램이 정상적으로 종료되었습니다.")
