"""SmartThings Data Collector Launcher
- Runs the collection backend in a background thread
- Runs the tkinter dashboard on the main thread (required by tkinter)
- input() unavailable in exe environment, replaced with tkinter popups
"""

import os
import sys
import threading
import asyncio
import logging
import subprocess
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# === Path settings ===
BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
TOKEN_FILE = Path("C:/smartthings_data/tokens/oauth_token.json")
LOG_FILE   = Path("C:/smartthings_data/logs/launcher.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
)


def show_error(title, message):
    """Show tkinter error popup (replaces input() in exe environment)."""
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()


def show_info(title, message):
    """Show tkinter info popup."""
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(title, message)
    root.destroy()


def check_token():
    """Run auth script if token file is missing."""
    if TOKEN_FILE.exists():
        return

    logging.warning("Token file not found. Starting authentication...")

    auth_script = BASE_DIR / "smartthings_auth.py"

    if not auth_script.exists():
        show_error(
            "Auth File Missing",
            f"smartthings_auth.py not found.\nPath: {auth_script}\n\nExiting."
        )
        sys.exit(1)

    show_info(
        "Authentication Required",
        "SmartThings account authentication is required.\n\n"
        "1. Click OK to open a terminal window.\n"
        "2. Log in with your Samsung account and grant permissions.\n"
        "3. Copy the 'code' value from the redirected page JSON and paste it into the terminal.\n"
        "4. Once authentication is complete and the terminal closes, the app will start automatically."
    )

    try:
        subprocess.run(
            [sys.executable, str(auth_script)],
            check=False,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
    except Exception as e:
        show_error("Auth Error", f"An error occurred while running the auth script.\n{e}")
        sys.exit(1)

    if not TOKEN_FILE.exists():
        show_error(
            "Authentication Failed",
            "Authentication was not completed.\nToken file was not created.\n\nExiting."
        )
        sys.exit(1)

    logging.info("Authentication complete.")


def run_collector(collector):
    """Run the collector in a background thread."""
    try:
        collector.load_token()
        collector.load_metadata()
        collector.load_ban_list()
        logging.info("Data collection started.")
        asyncio.run(collector.scheduler())
    except Exception as e:
        logging.error(f"Collector error: {e}")
        show_error("Collector Error", f"An error occurred during data collection.\n{e}")


def main():
    logging.info("SmartThings Data Collector starting.")

    # 1. Check token
    check_token()

    # 2. Import collector
    try:
        import smartthings_collector as collector
    except Exception as e:
        show_error("Initialization Error", f"Failed to load collector module:\n{e}")
        sys.exit(1)

    # 3. Start collector in background thread
    t = threading.Thread(target=run_collector, args=(collector,), daemon=True)
    t.start()

    # 4. Run tkinter dashboard on main thread
    try:
        import smartthings_dashboard as dashboard
        dashboard.run_dashboard(collector)
    except Exception as e:
        logging.error(f"Dashboard error: {e}")
        show_error("Dashboard Error", f"An error occurred while running the dashboard.\n{e}")


if __name__ == "__main__":
    main()
