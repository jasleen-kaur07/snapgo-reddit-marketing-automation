# scheduler/daily_scheduler.py

import time
import os
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from scheduler.runner import run_daily_pipeline
from utils.logger import setup_logger

log = setup_logger()

def start_scheduler():
    """Start the background scheduler to run the pipeline hourly."""
    scheduler = BackgroundScheduler()

    # Run every 30 minutes
    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(minute="*/30"),
        id="hourly_reddit_pipeline",
        name="30-Minute Reddit Scraping Pipeline",
        replace_existing=True
    )

    scheduler.start()
    log.info("Scheduler started. Pipeline will run hourly.")

    try:
        # Keep the main thread alive
        while True:
            time.sleep(3600)  # Sleep for 1 hour
            log.debug(f"Scheduler running. Current time: {datetime.now().isoformat()}")
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Scheduler shutdown.")

def check_and_write_pid():
    pid_file = os.path.join(PROJECT_ROOT, "data", "scheduler.pid")
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            # Check if this PID is running
            os.kill(pid, 0)
            log.warning(f"Scheduler is already running with PID {pid}. Exiting.")
            sys.exit(0)
        except (ValueError, OSError):
            # PID not running or invalid file, overwrite it
            pass
            
    # Write current PID
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

if __name__ == "__main__":
    check_and_write_pid()
    log.info("Starting scheduler for Reddit scraping pipeline...")
    start_scheduler()
