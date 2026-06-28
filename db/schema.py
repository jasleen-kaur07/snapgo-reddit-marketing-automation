# db/schema.py

import sqlite3
import os
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import ensure_directory_exists

log = setup_logger()
config = get_config()
DB_PATH = config["database"]["path"]

def create_tables():
    """Create the SQLite tables if they don't exist."""
    ensure_directory_exists(os.path.dirname(DB_PATH))
    log.info(f"Initializing database at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY,
        url TEXT,
        title TEXT,
        body TEXT,
        subreddit TEXT,
        created_utc REAL,
        last_active REAL,
        processed_at TEXT,
        relevance_score REAL,
        emotion_score REAL,
        pain_score REAL,
        tags TEXT,
        roi_weight INTEGER,
        community_type TEXT,
        type TEXT,  -- 'post' or 'comment'
        post_body TEXT,  -- parent post body for comments
        parent_post_id TEXT,  -- links comments to their parent post (for dedup)
        implementability_score REAL,
        technical_depth_score REAL,
        insight_processed INTEGER DEFAULT 0,
        insight_processed_at TEXT,
        user_intent TEXT,
        marketing_campaign TEXT,
        suggested_response TEXT,
        review_status TEXT DEFAULT 'pending',
        country TEXT,
        state TEXT,
        city TEXT,
        origin TEXT,
        destination TEXT,
        priority_level TEXT DEFAULT 'Low',
        overall_priority_score REAL DEFAULT 0.0,
        intent_strength REAL DEFAULT 5.0,
        pain_severity REAL DEFAULT 5.0
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id TEXT PRIMARY KEY,
        processed_at TEXT
    );
    """)

    # Migration: add technical_depth_score column if missing (for existing databases)
    try:
        c.execute("ALTER TABLE posts ADD COLUMN technical_depth_score REAL")
        log.info("Added technical_depth_score column to posts table")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add parent_post_id column if missing (for existing databases)
    try:
        c.execute("ALTER TABLE posts ADD COLUMN parent_post_id TEXT")
        log.info("Added parent_post_id column to posts table")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add user_intent column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN user_intent TEXT")
        log.info("Added user_intent column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add marketing_campaign column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN marketing_campaign TEXT")
        log.info("Added marketing_campaign column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add suggested_response column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN suggested_response TEXT")
        log.info("Added suggested_response column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add review_status column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN review_status TEXT DEFAULT 'pending'")
        log.info("Added review_status column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add country column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN country TEXT")
        log.info("Added country column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add state column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN state TEXT")
        log.info("Added state column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add city column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN city TEXT")
        log.info("Added city column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add origin column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN origin TEXT")
        log.info("Added origin column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add destination column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN destination TEXT")
        log.info("Added destination column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add priority_level column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN priority_level TEXT DEFAULT 'Low'")
        log.info("Added priority_level column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add overall_priority_score column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN overall_priority_score REAL DEFAULT 0.0")
        log.info("Added overall_priority_score column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add intent_strength column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN intent_strength REAL DEFAULT 5.0")
        log.info("Added intent_strength column to posts table")
    except sqlite3.OperationalError:
        pass

    # Migration: add pain_severity column if missing
    try:
        c.execute("ALTER TABLE posts ADD COLUMN pain_severity REAL DEFAULT 5.0")
        log.info("Added pain_severity column to posts table")
    except sqlite3.OperationalError:
        pass

    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_processed_at ON posts(processed_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_relevance ON posts(relevance_score);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_roi ON posts(roi_weight);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON posts(subreddit);")

    conn.commit()
    conn.close()
    log.info("Database tables created successfully")

if __name__ == "__main__":
    create_tables()
    print(f"Database initialized at {DB_PATH}")
