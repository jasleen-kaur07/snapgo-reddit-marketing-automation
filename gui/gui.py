import streamlit as st
import sqlite3
import json
import pandas as pd
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# Ensure project root is importable when running via `streamlit run gui/gui.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.config_loader import get_config
from scheduler.runner import run_daily_pipeline

# Configure Streamlit page
st.set_page_config(
    page_title="Snapgo Reddit Marketing Intelligence Dashboard",
    page_icon="📈",
    layout="wide"
)

# Custom CSS for rich aesthetics, glassmorphism, and metric cards
st.markdown("""
<style>
    .reportview-container {
        background: #0f172a;
    }
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        margin-bottom: 15px;
        min-height: 100px;
    }
    .metric-card h4 {
        margin: 0;
        font-size: 13px;
        color: #94a3b8;
        font-weight: 500;
    }
    .metric-card h2 {
        margin: 5px 0 0 0;
        font-size: 24px;
        color: #3b82f6;
        font-weight: bold;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover {
        transform: scale(1.02);
    }
</style>
""", unsafe_allow_html=True)

def get_last_scrape_time() -> float:
    """Read the last scrape timestamp from file."""
    path = os.path.join(PROJECT_ROOT, "data", "last_scrape.txt")
    if not os.path.exists(path):
        return 0.0
    try:
        with open(path, "r") as f:
            return float(f.read().strip())
    except Exception:
        return 0.0

def set_last_scrape_time(t: float):
    """Write the last scrape timestamp to file."""
    path = os.path.join(PROJECT_ROOT, "data", "last_scrape.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            f.write(str(t))
    except Exception:
        pass

def _extract_json_from_text(text: str) -> str:
    """Extract JSON payload from markdown-fenced or plain text."""
    if not text:
        return text

    stripped = text.strip()

    # Fenced block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", stripped, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # First object/array fallback
    match = re.search(r"[\{\[].*[\}\]]", stripped, re.DOTALL)
    if match:
        return match.group(0).strip()

    return stripped


@st.cache_data
def load_posts_with_insights(
    db_path: str,
    insights_dir: str,
    provider: str,
    data_version: float
) -> pd.DataFrame:
    """Load posts with insight_processed=1 and join with insight data."""

    # Connect to SQLite database
    conn = sqlite3.connect(db_path)

    # Query posts with insights processed
    query = """
    SELECT id, url, title, body, relevance_score, pain_score, emotion_score,
           COALESCE(technical_depth_score, 0) as technical_depth_score,
           subreddit, created_utc, processed_at,
           user_intent, marketing_campaign, suggested_response,
           country, state, city, origin, destination, priority_level, overall_priority_score,
           intent_strength, pain_severity
    FROM posts
    WHERE insight_processed = 1
    """

    posts_df = pd.read_sql_query(query, conn)
    conn.close()

    # Load insight data from JSONL files (as a fallback/enrichment for older records)
    insights_data = {}
    insights_path = Path(insights_dir)

    for jsonl_file in insights_path.glob("*.jsonl"):
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    custom_id = data.get('custom_id')
                    if not custom_id:
                        continue

                    if provider == "anthropic":
                        if data.get("result_type") != "succeeded":
                            continue
                        content = data.get("content", "")
                        insight_json = json.loads(_extract_json_from_text(content))
                        insights_data[custom_id] = insight_json
                    elif provider == "openai":
                        if (
                            data.get('response') and
                            data['response'].get('body') and
                            data['response']['body'].get('choices')
                        ):
                            content = data['response']['body']['choices'][0]['message']['content']
                            insight_json = json.loads(_extract_json_from_text(content))
                            insights_data[custom_id] = insight_json

                except Exception:
                    continue

    # Fill missing database columns with loaded JSONL cache data if applicable
    posts_df['roi_weight'] = posts_df['id'].map(lambda x: insights_data.get(x, {}).get('roi_weight', 7))
    posts_df['tags'] = posts_df['id'].map(lambda x: ', '.join(insights_data.get(x, {}).get('tags', [])))

    posts_df['user_intent'] = posts_df['user_intent'].fillna('')
    posts_df['marketing_campaign'] = posts_df['marketing_campaign'].fillna('')
    posts_df['suggested_response'] = posts_df['suggested_response'].fillna('')
    
    posts_df['country'] = posts_df['country'].fillna('')
    posts_df['state'] = posts_df['state'].fillna('')
    posts_df['city'] = posts_df['city'].fillna('')
    posts_df['origin'] = posts_df['origin'].fillna('')
    posts_df['destination'] = posts_df['destination'].fillna('')
    posts_df['priority_level'] = posts_df['priority_level'].fillna('Low')
    posts_df['overall_priority_score'] = posts_df['overall_priority_score'].fillna(0.0)
    posts_df['intent_strength'] = posts_df['intent_strength'].fillna(5.0)
    posts_df['pain_severity'] = posts_df['pain_severity'].fillna(5.0)

    for idx, row in posts_df.iterrows():
        pid = row['id']
        if not row['user_intent'] and pid in insights_data:
            posts_df.at[idx, 'user_intent'] = insights_data[pid].get('user_intent', '')
        if not row['marketing_campaign'] and pid in insights_data:
            posts_df.at[idx, 'marketing_campaign'] = insights_data[pid].get('marketing_campaign', 'General Transportation')
        if not row['suggested_response'] and pid in insights_data:
            posts_df.at[idx, 'suggested_response'] = insights_data[pid].get('suggested_response', '')
        if not row['country'] and pid in insights_data:
            posts_df.at[idx, 'country'] = insights_data[pid].get('country', '')
        if not row['state'] and pid in insights_data:
            posts_df.at[idx, 'state'] = insights_data[pid].get('state', '')
        if not row['city'] and pid in insights_data:
            posts_df.at[idx, 'city'] = insights_data[pid].get('city', '')
        if not row['origin'] and pid in insights_data:
            posts_df.at[idx, 'origin'] = insights_data[pid].get('origin', '')
        if not row['destination'] and pid in insights_data:
            posts_df.at[idx, 'destination'] = insights_data[pid].get('destination', '')
        if not row['priority_level'] and pid in insights_data:
            posts_df.at[idx, 'priority_level'] = insights_data[pid].get('priority_level', 'Low')

    return posts_df


def display_post_card(post: pd.Series):
    """Display a single lead post as an interactive card."""
    with st.container():
        st.markdown("---")
        
        # Grid layout for core metrics and status indicators
        col1, col2, col3, col4 = st.columns([1.5, 1, 1, 8])

        with col1:
            st.metric("Priority Score", f"{post['overall_priority_score']:.1f}")
        with col2:
            st.metric("Relevance", f"{post['relevance_score']:.1f}")
        with col3:
            st.metric("Frustration", f"{post['emotion_score']:.1f}")
        with col4:
            # Priority Level Badge Color mapping
            lvl = post['priority_level']
            if lvl == "Highest":
                lvl_str = "🔴 Highest"
            elif lvl == "Medium":
                lvl_str = "🟡 Medium"
            elif lvl == "Low":
                lvl_str = "🔵 Low"
            else:
                lvl_str = "⚪ Very Low"
            st.info(f"**Intent:** {post['user_intent']}  \n**Campaign:** {post['marketing_campaign']} | **Priority:** {lvl_str}")

    # Content section
    col_content, col_meta = st.columns([7, 3])
    with col_content:
        st.markdown(f"#### [{post['title']}](<{post['url']}>)")
        
        # Display geographic locations metadata
        geo_parts = []
        if post['country']:
            geo_parts.append(f"🌎 **Country:** {post['country']}")
        if post['state']:
            geo_parts.append(f"📍 **State:** {post['state']}")
        if post['city']:
            geo_parts.append(f"🏙️ **City:** {post['city']}")
        if post['origin']:
            geo_parts.append(f"🛫 **Origin:** {post['origin']}")
        if post['destination']:
            geo_parts.append(f"🛬 **Destination:** {post['destination']}")
        
        if geo_parts:
            st.markdown(" | ".join(geo_parts))
            
    with col_meta:
        # Show tag pills
        tags_str = post.get('tags', '')
        tags_list = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if isinstance(tags_str, str) else []
        tags_html = "".join(map(lambda tag: f"<span style='background-color: #3b82f6; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-right: 4px; display: inline-block;'>{tag}</span>", tags_list))
        st.markdown(tags_html, unsafe_allow_html=True)

    # Contextual suggested reply (Native copyable code block)
    st.markdown("**💬 Suggested Reply Draft** *(Click inside code block to copy)*")
    suggested_reply = post['suggested_response'].strip() if post['suggested_response'] else "AI response unavailable."
    st.code(suggested_reply, language="text")

    # Original discussion text expander
    with st.expander("🔍 Show Original Thread Context"):
        st.markdown("**Subreddit:** r/" + post['subreddit'])
        body_text = post['body']
        if len(body_text) > 800:
            st.write(body_text[:800] + "...")
        else:
            st.write(body_text)


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

def main():
    check_and_start_background_scheduler()
    st.title("Snapgo Reddit Marketing Intelligence Dashboard")
    st.markdown("Discover transportation discussions, classify user intent, and generate contextual reply drafts.")

    # Load configurations
    cfg = get_config()
    provider = cfg["ai"]["provider"]
    db_path = os.path.join(PROJECT_ROOT, cfg["database"]["path"])
    insights_dir = os.path.join(PROJECT_ROOT, cfg.get("paths", {}).get("batch_responses_dir", "data/batch_responses"))

    # Refresh Button at the top of the main area
    if st.button("🔄 Refresh Reddit Posts", use_container_width=True):
        st.cache_data.clear()
        st.toast("Updated feed with the latest background scraped data from SQLite!", icon="🔄")
        time.sleep(0.5)
        st.rerun()

    # Verify if database exists
    if not os.path.exists(db_path):
        st.warning("SQLite Database not found. Please click 'Refresh Reddit Posts' to perform the initial scrape.")
        return

    if not os.path.exists(insights_dir):
        os.makedirs(insights_dir, exist_ok=True)

    # Cache buster using file system mtimes
    insight_files = list(Path(insights_dir).glob("*.jsonl"))
    latest_insight_mtime = max((f.stat().st_mtime for f in insight_files), default=0.0)
    data_version = max(os.path.getmtime(db_path), latest_insight_mtime)

    # Load records from SQLite (The Single Source of Truth)
    try:
        df = load_posts_with_insights(db_path, insights_dir, provider, data_version)
    except Exception as e:
        st.error(f"Failed to query database: {str(e)}")
        return

    # Check if empty
    if df.empty:
        st.warning("No processed transit leads found in the database. Try clicking 'Refresh Reddit Posts' above.")
        return

    # Sidebar parameters (Read-only view filters)
    st.sidebar.header("🔧 Filters & Operators")

    # Filter by Marketing Campaign
    campaign_options = [
        "All", "Student Commute", "Office Commute", "Carpool Promotion",
        "Fuel Savings", "Traffic & Congestion", "Public Transport", "General Transportation"
    ]
    selected_campaign = st.sidebar.selectbox("Marketing Campaign", campaign_options, index=0)

    # Filter by Priority Level
    priority_options = ["All", "Highest", "Medium", "Low", "Very Low"]
    selected_priority = st.sidebar.selectbox("Priority Level", priority_options, index=0)

    # Geographic filters (Locked exactly to Snapgo India/Delhi NCR region)
    st.sidebar.subheader("🌍 Geography Filters")
    
    selected_country = st.sidebar.selectbox("Country", ["India"], index=0)
    selected_state = st.sidebar.selectbox("State", ["Delhi NCR"], index=0)

    allowed_cities = ["Delhi", "Noida", "Greater Noida", "Gurugram", "Ghaziabad", "Faridabad"]
    selected_city = st.sidebar.selectbox("City", ["All"] + allowed_cities, index=0)

    # Metric range filters
    st.sidebar.subheader("Metrics Filters")
    
    def create_safe_slider(label: str, values: pd.Series, key: str = None):
        min_val = float(values.min())
        max_val = float(values.max())
        if min_val == max_val:
            st.sidebar.write(f"**{label}**: {min_val:.2f}")
            return (min_val, max_val)
        return st.sidebar.slider(
            label, min_value=min_val, max_value=max_val, value=(min_val, max_val), step=0.1, key=key
        )

    relevance_range = create_safe_slider("Relevance Range", df['relevance_score'], "relevance")
    emotion_range = create_safe_slider("Frustration Range", df['emotion_score'], "emotion")
    priority_range = create_safe_slider("Overall Priority Score Range", df['overall_priority_score'], "priority")

    # Sorting
    st.sidebar.subheader("Sorting")
    sort_by = st.sidebar.selectbox(
        "Sort by",
        options=['overall_priority_score', 'relevance_score', 'emotion_score', 'created_utc'],
        index=0
    )
    sort_order = st.sidebar.radio("Sort order", options=['Descending', 'Ascending'], index=0)

    # Apply filters
    filtered_df = df.copy()

    # Enforce Geographic constraints
    filtered_df = filtered_df[filtered_df['country'].str.lower() == 'india']
    filtered_df = filtered_df[filtered_df['state'].str.lower() == 'delhi ncr']

    if selected_city != "All":
        filtered_df = filtered_df[filtered_df['city'] == selected_city]
    else:
        filtered_df = filtered_df[filtered_df['city'].isin(allowed_cities)]

    if selected_campaign != "All":
        filtered_df = filtered_df[filtered_df['marketing_campaign'] == selected_campaign]

    if selected_priority != "All":
        filtered_df = filtered_df[filtered_df['priority_level'] == selected_priority]

    # Apply metrics ranges filters
    filtered_df = filtered_df[
        (filtered_df['relevance_score'] >= relevance_range[0]) &
        (filtered_df['relevance_score'] <= relevance_range[1]) &
        (filtered_df['emotion_score'] >= emotion_range[0]) &
        (filtered_df['emotion_score'] <= emotion_range[1]) &
        (filtered_df['overall_priority_score'] >= priority_range[0]) &
        (filtered_df['overall_priority_score'] <= priority_range[1])
    ]

    # Apply sorting order
    ascending = (sort_order == 'Ascending')
    filtered_df = filtered_df.sort_values(by=sort_by, ascending=ascending)

    # Statistics Grid (Live data metrics)
    st.markdown("### 📈 Live Dashboard Statistics")
    
    # 2 rows of metrics cards
    col1, col2, col3, col4, col5 = st.columns(5)
    col6, col7, col8, col9, col10 = st.columns(5)
    
    total_scraped = len(filtered_df)
    
    # New Posts Today
    today_str = datetime.now(IST).date().isoformat()
    new_today = len(filtered_df[filtered_df['processed_at'] == today_str])
    
    # Average scores
    avg_relevance = filtered_df['relevance_score'].mean() if not filtered_df.empty else 0.0
    avg_frustration = filtered_df['emotion_score'].mean() if not filtered_df.empty else 0.0
    
    # Last refresh time
    last_scrape_t = get_last_scrape_time()
    if last_scrape_t > 0:
        last_refresh_str = datetime.fromtimestamp(last_scrape_t, IST).strftime('%Y-%m-%d %H:%M:%S IST')
    else:
        last_refresh_str = "Never"
        
    # City counts (case-insensitive checks)
    delhi_cnt = len(filtered_df[filtered_df['city'].str.lower() == 'delhi'])
    noida_cnt = len(filtered_df[filtered_df['city'].str.lower().str.contains('noida', na=False)])
    greater_noida_cnt = len(filtered_df[filtered_df['city'].str.lower().str.contains('greater noida', na=False)])
    gurugram_cnt = len(filtered_df[filtered_df['city'].str.lower().str.contains('gurugram|gurgaon', na=False)])
    ghaziabad_cnt = len(filtered_df[filtered_df['city'].str.lower().str.contains('ghaziabad', na=False)])
    faridabad_cnt = len(filtered_df[filtered_df['city'].str.lower().str.contains('faridabad', na=False)])
    
    with col1:
        st.markdown(f"<div class='metric-card'><h4>Total Scraped</h4><h2>{total_scraped}</h2></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='metric-card'><h4>New Today</h4><h2>{new_today}</h2></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div class='metric-card'><h4>Avg Relevance</h4><h2>{avg_relevance:.2f}</h2></div>", unsafe_allow_html=True)
    with col4:
        st.markdown(f"<div class='metric-card'><h4>Avg Frustration</h4><h2>{avg_frustration:.2f}</h2></div>", unsafe_allow_html=True)
    with col5:
        st.markdown(f"<div class='metric-card'><h4>Last Refresh</h4><h2 style='font-size: 13px; margin-top: 10px; color:#10b981;'>{last_refresh_str}</h2></div>", unsafe_allow_html=True)
        
    with col6:
        st.markdown(f"<div class='metric-card'><h4>Delhi Posts</h4><h2>{delhi_cnt}</h2></div>", unsafe_allow_html=True)
    with col7:
        st.markdown(f"<div class='metric-card'><h4>Noida Posts</h4><h2>{noida_cnt}</h2></div>", unsafe_allow_html=True)
    with col8:
        st.markdown(f"<div class='metric-card'><h4>Greater Noida</h4><h2>{greater_noida_cnt}</h2></div>", unsafe_allow_html=True)
    with col9:
        st.markdown(f"<div class='metric-card'><h4>Gurugram Posts</h4><h2>{gurugram_cnt}</h2></div>", unsafe_allow_html=True)
    with col10:
        st.markdown(f"<div class='metric-card'><h4>Ghaziabad/Faridabad</h4><h2>{ghaziabad_cnt + faridabad_cnt}</h2></div>", unsafe_allow_html=True)

    # Display totals
    st.markdown(f"**Showing {len(filtered_df)} of {len(df)} posts matching current filters**")

    # Paginate pages
    posts_per_page = 10
    total_pages = (len(filtered_df) + posts_per_page - 1) // posts_per_page

    if total_pages > 1:
        page = st.selectbox("Page Select", range(1, total_pages + 1), index=0)
        start_idx = (page - 1) * posts_per_page
        end_idx = start_idx + posts_per_page
        page_df = filtered_df.iloc[start_idx:end_idx]
    else:
        page_df = filtered_df

    # Display post cards
    for idx, post in page_df.iterrows():
        display_post_card(post)


if __name__ == "__main__":
    main()
