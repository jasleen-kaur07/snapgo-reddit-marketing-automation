import streamlit as st
import sqlite3
import json
import pandas as pd
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is importable when running via `streamlit run gui/gui.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.config_loader import get_config
from db.writer import update_post_review_status

# Configure Streamlit page
st.set_page_config(
    page_title="Snapgo Reddit Marketing Operator Dashboard",
    page_icon="🚗",
    layout="wide"
)

# Custom CSS for rich aesthetics and glassmorphism styling
st.markdown("""
<style>
    .reportview-container {
        background: #0f172a;
    }
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 15px;
        text-align: center;
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
           user_intent, marketing_campaign, suggested_response, review_status,
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
    posts_df['review_status'] = posts_df['review_status'].fillna('pending')
    
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
        col1, col2, col3, col4, col5 = st.columns([1.5, 1, 1, 1.5, 8])

        with col1:
            st.metric("Priority Score", f"{post['overall_priority_score']:.1f}")
        with col2:
            st.metric("Relevance", f"{post['relevance_score']:.1f}")
        with col3:
            st.metric("Frustration", f"{post['emotion_score']:.1f}")
        with col4:
            # Color-coded status badge
            status = post['review_status'].upper()
            if status == "APPROVED":
                badge_style = "background-color: #2e7d32; color: white;"
            elif status == "REJECTED":
                badge_style = "background-color: #c62828; color: white;"
            else:
                badge_style = "background-color: #f57c00; color: white;"
            
            st.markdown(
                f"<div style='text-align: center; font-size: 11px; font-weight: bold; border-radius: 6px; padding: 4px; margin-top: 10px; {badge_style}'>{status}</div>",
                unsafe_allow_html=True
            )
        with col5:
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
        tags_list = [tag.strip() for tag in post['tags'].split(',') if tag.strip()]
        tags_html = "".join(map(lambda tag: f"<span style='background-color: #3b82f6; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-right: 4px; display: inline-block;'>{tag}</span>", tags_list))
        st.markdown(tags_html, unsafe_allow_html=True)

    # Contextual suggested reply
    st.markdown("**💬 Suggested Reply Draft** *(Click inside code block to copy)*")
    response_key = f"response_{post['id']}"
    
    # Editable box for human-in-the-loop review
    edited_text = st.text_area(
        label="Edit Reply Draft",
        value=post['suggested_response'],
        key=response_key,
        height=110,
        label_visibility="collapsed"
    )
    
    # Streamlit Code blocks support single-click copy to clipboard natively
    st.code(edited_text, language="text")

    # Review status controls
    btn_col1, btn_col2, btn_col3 = st.columns([1.5, 1.5, 9])
    with btn_col1:
        if st.button("👍 Approve", key=f"app_{post['id']}"):
            update_post_review_status(post['id'], 'approved', edited_text)
            st.success("Status: Approved!")
            st.rerun()
            
    with btn_col2:
        if st.button("👎 Reject", key=f"rej_{post['id']}"):
            update_post_review_status(post['id'], 'rejected', edited_text)
            st.warning("Status: Rejected")
            st.rerun()

    # Original discussion text expander
    with st.expander("🔍 Show Original Thread Context"):
        st.markdown("**Subreddit:** r/" + post['subreddit'])
        body_text = post['body']
        if len(body_text) > 800:
            st.write(body_text[:800] + "...")
        else:
            st.write(body_text)


def main():
    st.title("🚗 Snapgo Reddit Marketing Dashboard")
    st.markdown("Identify transportation discussions, review geographic targets, and approve response suggestions.")

    # Load configurations
    cfg = get_config()
    provider = cfg["ai"]["provider"]
    db_path = cfg["database"]["path"]
    insights_dir = cfg.get("paths", {}).get("batch_responses_dir", "data/batch_responses")

    # Verify if database and directory paths exist
    if not os.path.exists(db_path):
        st.error(f"SQLite Database not found at {db_path}. Please run populate_mock_data.py or scraper pipeline first.")
        return

    if not os.path.exists(insights_dir):
        os.makedirs(insights_dir, exist_ok=True)

    # Cache buster using file system mtimes
    insight_files = list(Path(insights_dir).glob("*.jsonl"))
    latest_insight_mtime = max((f.stat().st_mtime for f in insight_files), default=0.0)
    data_version = max(os.path.getmtime(db_path), latest_insight_mtime)

    # Load records
    with st.spinner("Retrieving records from database..."):
        try:
            df = load_posts_with_insights(db_path, insights_dir, provider, data_version)
        except Exception as e:
            st.error(f"Failed to query database: {str(e)}")
            return

    if df.empty:
        st.warning("No processed transit leads found in the database.")
        return

    # Sidebar parameters
    st.sidebar.header("🔧 Filters & Operators")

    # Filter by Review Status
    review_statuses = ["All", "Pending", "Approved", "Rejected"]
    selected_status = st.sidebar.selectbox("Review Status", review_statuses, index=0)

    # Filter by Marketing Campaign
    campaign_options = [
        "All", "Student Commute", "Office Commute", "Carpool Promotion",
        "Fuel Savings", "Traffic & Congestion", "Public Transport", "General Transportation"
    ]
    selected_campaign = st.sidebar.selectbox("Marketing Campaign", campaign_options, index=0)

    # Filter by Priority Level
    priority_options = ["All", "Highest", "Medium", "Low", "Very Low"]
    selected_priority = st.sidebar.selectbox("Priority Level", priority_options, index=0)

    # Geographic dynamic filters
    st.sidebar.subheader("🌍 Geography Filters")
    
    countries = ["All"] + sorted([c for c in df['country'].unique() if c])
    selected_country = st.sidebar.selectbox("Country", countries, index=0)

    states = ["All"] + sorted([s for s in df['state'].unique() if s])
    selected_state = st.sidebar.selectbox("State", states, index=0)

    cities = ["All"] + sorted([c for c in df['city'].unique() if c])
    selected_city = st.sidebar.selectbox("City", cities, index=0)

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
    if selected_status != "All":
        filtered_df = filtered_df[filtered_df['review_status'] == selected_status.lower()]

    if selected_campaign != "All":
        filtered_df = filtered_df[filtered_df['marketing_campaign'] == selected_campaign]

    if selected_priority != "All":
        filtered_df = filtered_df[filtered_df['priority_level'] == selected_priority]

    if selected_country != "All":
        filtered_df = filtered_df[filtered_df['country'] == selected_country]

    if selected_state != "All":
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    if selected_city != "All":
        filtered_df = filtered_df[filtered_df['city'] == selected_city]

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

    # Sidebar Summary Metrics panel
    if len(filtered_df) > 0:
        st.sidebar.subheader("📈 Campaign Summary Stats")
        st.sidebar.metric("Total Matches", len(filtered_df))
        st.sidebar.metric("Avg Priority Score", f"{filtered_df['overall_priority_score'].mean():.2f}")
        st.sidebar.metric("Avg Relevance Score", f"{filtered_df['relevance_score'].mean():.2f}")
        st.sidebar.metric("Avg Frustration Score", f"{filtered_df['emotion_score'].mean():.2f}")


if __name__ == "__main__":
    main()
