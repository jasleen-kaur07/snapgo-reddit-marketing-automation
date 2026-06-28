# scripts/populate_mock_data.py

import sqlite3
import json
import os
import time
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.config_loader import get_config

def main():
    cfg = get_config()
    db_path = cfg["database"]["path"]
    provider = cfg["ai"]["provider"]
    insights_dir = cfg.get("paths", {}).get("batch_responses_dir", "data/batch_responses")

    print(f"Creating location-enriched transit mock data for provider: {provider}")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(insights_dir, exist_ok=True)

    # Initialize SQLite database
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Drop old posts table if it exists to refresh schema cleanly
    c.execute("DROP TABLE IF EXISTS posts;")

    c.execute("""
    CREATE TABLE posts (
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
        type TEXT,
        post_body TEXT,
        parent_post_id TEXT,
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

    # Populate mock transport posts with marketing info
    mock_posts = [
        {
            "id": "mock_transit_ncr_1",
            "url": "https://www.reddit.com/r/delhi/comments/mock1/noida_to_gurgaon_carpool/",
            "title": "Looking for daily carpool or ride share from Noida Sector 62 to Cyber City Gurugram",
            "body": "Hi everyone, I recently shifted to Noida Sector 62 but my office is located in Cyber City Gurgaon. The daily commute via metro takes almost 2 hours each way and is extremely exhausting during rush hour. Cabs are costing me around Rs. 800 one-way. Is anyone driving along this route daily? Happy to share petrol costs and split expenses.",
            "subreddit": "delhi",
            "created_utc": time.time() - 86400 * 2,
            "last_active": time.time() - 86400 * 1,
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "relevance_score": 9.5,
            "emotion_score": 8.0,
            "pain_score": 8.5,
            "tags": "carpool, gurgaon, noida, metro, commute",
            "roi_weight": 9,
            "community_type": "primary",
            "type": "post",
            "implementability_score": 9.0,
            "technical_depth_score": 5.0,
            "insight_processed": 1,
            "insight_processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_intent": "Actively looking to join or form a daily carpool group to reduce commute exhaustion and cab costs",
            "marketing_campaign": "Carpool Promotion",
            "suggested_response": "Hey! Commuting from Noida to Gurgaon daily is definitely a massive challenge. You should try checking on Snapgo—it is a carpooling app built exactly for office commuters in Delhi NCR. It connects you with verified professionals sharing standard office routes, allowing you to split fuel/ride costs easily. Metro/cab fatigue is real, so this might save you a lot of time and energy. Cheers!",
            "review_status": "pending",
            "country": "India",
            "state": "Delhi NCR",
            "city": "Gurugram",
            "origin": "Noida Sector 62",
            "destination": "Cyber City Gurugram",
            "priority_level": "Highest",
            "overall_priority_score": 92.5,
            "intent_strength": 9.0,
            "pain_severity": 8.5
        },
        {
            "id": "mock_transit_india_2",
            "url": "https://www.reddit.com/r/bangalore/comments/mock2/outer_ring_road_traffic/",
            "title": "Outer Ring Road (ORR) traffic is getting unbearable, spending 3 hours daily in bus",
            "body": "I commute daily from Banashankari to my tech park on Outer Ring Road. The Volvo bus is always stuck in gridlock near Silk Board and Marathahalli. With diesel and fuel costs going up, cab aggregators have doubled their fares. Is there any alternate route or a ride sharing group that does this route? My travel expenses are crossing Rs. 6000 a month.",
            "subreddit": "bangalore",
            "created_utc": time.time() - 86400 * 3,
            "last_active": time.time() - 86400 * 2,
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "relevance_score": 9.0,
            "emotion_score": 8.5,
            "pain_score": 8.0,
            "tags": "traffic, bangalore, commute, volvo-bus",
            "roi_weight": 7,
            "community_type": "primary",
            "type": "post",
            "implementability_score": 8.0,
            "technical_depth_score": 5.0,
            "insight_processed": 1,
            "insight_processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_intent": "Venting about severe daily traffic delays and looking for alternate ride sharing/bus routes",
            "marketing_campaign": "Traffic & Congestion",
            "suggested_response": "ORR traffic during peak hours is a nightmare. If you want to bypass the crowded Volvo buses and avoid expensive cabs, give Snapgo a try. It is a smart ride-sharing app that helps you find colleagues or other tech park employees driving along your exact route so you can split petrol costs and carpool. It might save you some time and a lot of frustration!",
            "review_status": "pending",
            "country": "India",
            "state": "Karnataka",
            "city": "Bangalore",
            "origin": "Banashankari",
            "destination": "Outer Ring Road",
            "priority_level": "Medium",
            "overall_priority_score": 71.0,
            "intent_strength": 7.0,
            "pain_severity": 8.0
        },
        {
            "id": "mock_transit_us_3",
            "url": "https://www.reddit.com/r/commuting/comments/mock3/sf_caltrain_cost/",
            "title": "Caltrain monthly passes are too expensive, need travel saving tips",
            "body": "I commute 5 days a week from San Jose to San Francisco. Caltrain monthly zone passes are costing me almost $280. Cabs from the terminal are adding up too. Are there any carpools or cheaper vanpool programs running along the US-101 North?",
            "subreddit": "commuting",
            "created_utc": time.time() - 86400 * 1,
            "last_active": time.time() - 86400 * 0.5,
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "relevance_score": 8.5,
            "emotion_score": 7.5,
            "pain_score": 8.0,
            "tags": "caltrain, sanjose, sanfrancisco, rail",
            "roi_weight": 4,
            "community_type": "primary",
            "type": "post",
            "implementability_score": 7.5,
            "technical_depth_score": 5.0,
            "insight_processed": 1,
            "insight_processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_intent": "Looking for cheaper commuter passes or carpool options in the San Francisco Bay Area",
            "marketing_campaign": "Fuel Savings",
            "suggested_response": "Transit prices are definitely steep. Have you checked if there are carpoolers in your office? You could also look at Snapgo to see if there are any active rideshares going up 101. It connects you with other commuters going between SJ and SF to share rides and split the fuel costs.",
            "review_status": "pending",
            "country": "USA",
            "state": "California",
            "city": "San Francisco",
            "origin": "San Jose",
            "destination": "San Francisco",
            "priority_level": "Low",
            "overall_priority_score": 48.0,
            "intent_strength": 6.5,
            "pain_severity": 7.0
        }
    ]

    # Insert mock records into SQLite database
    for p in mock_posts:
        c.execute("""
        INSERT INTO posts (
            id, url, title, body, subreddit, created_utc, last_active, processed_at,
            relevance_score, emotion_score, pain_score, tags, roi_weight, community_type,
            type, implementability_score, technical_depth_score, insight_processed, insight_processed_at,
            user_intent, marketing_campaign, suggested_response, review_status,
            country, state, city, origin, destination, priority_level, overall_priority_score,
            intent_strength, pain_severity
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p["id"], p["url"], p["title"], p["body"], p["subreddit"], p["created_utc"], p["last_active"], p["processed_at"],
            p["relevance_score"], p["emotion_score"], p["pain_score"], p["tags"], p["roi_weight"], p["community_type"],
            p["type"], p["implementability_score"], p["technical_depth_score"], p["insight_processed"], p["insight_processed_at"],
            p["user_intent"], p["marketing_campaign"], p["suggested_response"], p["review_status"],
            p["country"], p["state"], p["city"], p["origin"], p["destination"], p["priority_level"], p["overall_priority_score"],
            p["intent_strength"], p["pain_severity"]
        ))
    
    conn.commit()
    conn.close()
    print("Populated transit posts database with location-enriched mock records.")

    # Write mock data to JSONL file for double-layer compatibility
    jsonl_filename = os.path.join(insights_dir, "insight_result_mock.jsonl")
    with open(jsonl_filename, "w", encoding="utf-8") as f:
        for p in mock_posts:
            insight_payload = {
                "user_intent": p["user_intent"],
                "marketing_campaign": p["marketing_campaign"],
                "country": p["country"],
                "state": p["state"],
                "city": p["city"],
                "origin": p["origin"],
                "destination": p["destination"],
                "suggested_response": p["suggested_response"],
                "roi_weight": p["roi_weight"],
                "priority_level": p["priority_level"],
                "overall_priority_score": p["overall_priority_score"],
                "tags": p["tags"].split(",")
            }
            if provider == "openai":
                line_data = {
                    "custom_id": p["id"],
                    "response": {
                        "body": {
                            "choices": [
                                {
                                    "message": {
                                        "content": json.dumps(insight_payload)
                                    }
                                }
                            ]
                        }
                    }
                }
            else: # anthropic
                line_data = {
                    "custom_id": p["id"],
                    "content": json.dumps(insight_payload),
                    "result_type": "succeeded"
                }
            f.write(json.dumps(line_data) + "\n")

    print(f"Created mock insights file: {jsonl_filename}")
    print("Mock environment successfully initialized!")

if __name__ == "__main__":
    main()
