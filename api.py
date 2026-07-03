import os
import sys
import sqlite3
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.config_loader import get_config
from scheduler.runner import run_daily_pipeline

app = FastAPI(title="Snapgo Marketing Intelligence API")

def check_and_start_background_scheduler():
    """Ensure the hourly background scheduler is running by launching it from the user's session if not active."""
    pid_file = os.path.join(PROJECT_ROOT, "data", "scheduler.pid")
    is_running = False
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            # Check if this PID is running
            os.kill(pid, 0)
            is_running = True
        except (ValueError, OSError):
            pass
            
    if not is_running:
        import subprocess
        python_bin = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
        if not os.path.exists(python_bin):
            python_bin = "python"
            
        scheduler_script = os.path.join(PROJECT_ROOT, "scheduler", "daily_scheduler.py")
        try:
            subprocess.Popen(
                [python_bin, scheduler_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception:
            pass

@app.on_event("startup")
def startup_event():
    check_and_start_background_scheduler()


# Enable CORS for Next.js frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg = get_config()
db_path = os.path.join(PROJECT_ROOT, cfg["database"]["path"])

@app.get("/api/posts")
def get_posts():
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
        SELECT id, url, title, body, relevance_score, pain_score, emotion_score,
               subreddit, created_utc, processed_at,
               user_intent, marketing_campaign, suggested_response,
               country, state, city, origin, destination, priority_level, overall_priority_score,
               intent_strength, pain_severity
        FROM posts
        WHERE insight_processed = 1
        ORDER BY overall_priority_score DESC
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

@app.post("/api/refresh")
def refresh_posts(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_daily_pipeline)
    return {"status": "success", "message": "Scraper pipeline triggered in the background."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
