"""
SmartThings 데이터 수집기 런처
- 수집 백엔드를 별도 스레드에서 실행
- tkinter 대시보드를 메인 스레드에서 실행 (tkinter는 메인 스레드 필수)
"""

import os
import sys
import threading
import asyncio
import logging
import subprocess
from pathlib import Path

# === 경로 설정 ===
BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
TOKEN_FILE = Path("C:/smartthings_data/tokens/oauth_token.json")
LOG_FILE   = Path("C:/smartthings_data/logs/launcher.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)


def check_token():
    """토큰 파일이 없으면 인증 스크립트를 실행."""
    if not TOKEN_FILE.exists():
        logging.warning("토큰 파일이 없습니다. 인증을 시작합니다...")
        auth_script = BASE_DIR / "smartthings_auth.py"
        if auth_script.exists():
            subprocess.run([sys.executable, str(auth_script)], check=False)
        else:
            print(f"\n❌ smartthings_auth.py 파일을 찾을 수 없습니다: {auth_script}")
            input("\nEnter를 눌러 종료하세요.")
            sys.exit(1)

        if not TOKEN_FILE.exists():
            print("\n❌ 인증이 완료되지 않았습니다.")
            input("\nEnter를 눌러 종료하세요.")
            sys.exit(1)

        logging.info("인증 완료.")


def run_collector(collector):
    """수집기를 별도 스레드에서 실행."""
    try:
        collector.load_token()
        collector.load_metadata()
        collector.load_ban_list()
        logging.info("데이터 수집 시작.")
        asyncio.run(collector.scheduler())
    except Exception as e:
        logging.error(f"수집기 오류: {e}")


def main():
    print("=" * 55)
    print("  SmartThings 데이터 수집기")
    print("=" * 55)

    # 1. 토큰 확인
    check_token()

    # 2. collector import
    import smartthings_collector as collector

    # 3. 수집기를 백그라운드 스레드로 실행
    t = threading.Thread(target=run_collector, args=(collector,), daemon=True)
    t.start()

    # 4. tkinter 대시보드를 메인 스레드에서 실행 (tkinter 필수 조건)
    import smartthings_dashboard as dashboard
    dashboard.run_dashboard(collector)


if __name__ == "__main__":
    main()
