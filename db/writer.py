import sqlite3
from config.config_loader import get_config
from datetime import datetime, UTC
from pathlib import Path

config = get_config()
DB_PATH = config["database"]["path"]

_conn = None

def _get_connection():
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn

def insert_post(post: dict, community_type: str = "primary"):
    conn = _get_connection()
    try:
        # Check if URL already exists
        cursor = conn.cursor()
        existing = cursor.execute("SELECT id FROM posts WHERE url = ?", (post["url"],)).fetchone()
        
        if existing:
            # Update the existing post content to keep it fresh
            conn.execute("""
            UPDATE posts SET
                title = ?,
                body = ?,
                subreddit = ?,
                created_utc = ?,
                last_active = ?,
                processed_at = ?,
                community_type = ?,
                type = ?,
                post_body = ?,
                parent_post_id = ?
            WHERE id = ?
            """, (
                post["title"],
                post.get("body", ""),
                post["subreddit"],
                post["created_utc"],
                post["created_utc"],
                datetime.now(UTC).date().isoformat(),
                community_type,
                post.get("type", "post"),
                post.get("post_body", ""),
                post.get("parent_post_id"),
                existing[0]
            ))
        else:
            # Insert new post
            conn.execute("""
            INSERT OR IGNORE INTO posts (
                id, url, title, body, subreddit, created_utc, last_active,
                processed_at, community_type, type, post_body, parent_post_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                post["id"],
                post["url"],
                post["title"],
                post.get("body", ""),
                post["subreddit"],
                post["created_utc"],
                post["created_utc"],
                datetime.now(UTC).date().isoformat(),
                community_type,
                post.get("type", "post"),
                post.get("post_body", ""),
                post.get("parent_post_id")
            ))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite Insert Error] {e}")

def mark_posts_in_history(post_ids: list[str]):
    """Bulk-insert post IDs into the history table after AI processing succeeds."""
    conn = _get_connection()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO history (id, processed_at) VALUES (?, ?)",
            [(pid, datetime.now(UTC).isoformat()) for pid in post_ids]
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite mark_posts_in_history Error] {e}")

def update_post_filter_scores(post_id: str, scores: dict):
    """Update filtering phase scores only (relevance, emotion, pain, implementability, technical depth, intent_strength, pain_severity)."""
    conn = _get_connection()
    try:
        conn.execute("""
        UPDATE posts SET
            relevance_score = ?,
            emotion_score = ?,
            pain_score = ?,
            implementability_score = ?,
            technical_depth_score = ?,
            intent_strength = ?,
            pain_severity = ?,
            processed_at = ?
        WHERE id = ?
        """, (
            scores.get("relevance_score"),
            scores.get("emotional_intensity"),
            scores.get("pain_point_clarity"),
            scores.get("implementability_score"),
            scores.get("technical_depth_score"),
            scores.get("intent_strength", 5.0),
            scores.get("pain_severity", 5.0),
            datetime.now(UTC).date().isoformat(),
            post_id
        ))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite update_post_filter_scores Error] {e}")
def update_post_insight(post_id: str, insight: dict):
    """Update deeper insights (tags, roi_weight, user_intent, marketing_campaign, suggested_response, country, state, city, origin, destination, priority_level, overall_priority_score). Safe from overwriting with nulls."""
    conn = _get_connection()
    cursor = conn.cursor()

    fields = {
        "tags": ", ".join(insight["tags"]) if "tags" in insight else None,
        "roi_weight": insight.get("roi_weight"),
        "user_intent": insight.get("user_intent"),
        "marketing_campaign": insight.get("marketing_campaign"),
        "suggested_response": insight.get("suggested_response"),
        "country": insight.get("country"),
        "state": insight.get("state"),
        "city": insight.get("city"),
        "origin": insight.get("origin"),
        "destination": insight.get("destination"),
        "priority_level": insight.get("priority_level"),
        "overall_priority_score": insight.get("overall_priority_score")
    }

    updates = [f"{key} = ?" for key, value in fields.items() if value is not None]
    values = [value for value in fields.values() if value is not None]

    if not updates:
        return  # No valid fields to update

    updates.append("insight_processed = 1")
    updates.append("insight_processed_at = ?")
    values.append(datetime.utcnow().isoformat())

    query = f"""
        UPDATE posts SET {', '.join(updates)}
        WHERE id = ?
    """
    try:
        cursor.execute(query, values + [post_id])
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite update_post_insight Error] {e}")

def mark_insight_processed(post_id: str):
    """Mark a post as having been processed for deep insight."""
    conn = _get_connection()
    try:
        conn.execute("""
        UPDATE posts SET insight_processed = 1
        WHERE id = ?
        """, (post_id,))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite mark_insight_processed Error] {e}")

