# reddit/scraper.py

import datetime
import os
import time
import requests
import xml.etree.ElementTree as ET
import re
import html

from db.reader import is_already_processed
from db.writer import insert_post
from reddit.discovery import discover_adjacent_subreddits
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import load_json, save_json, truncate
from reddit.rate_limiter import RedditRateLimiter

log = setup_logger()
config = get_config()

limiter = RedditRateLimiter(config["scraper"].get("rate_limit_per_minute", 20))
EXPLORATORY_FILE = "data/exploratory_subreddits.json"

# XML namespace mapping for Atom feeds
ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}

def is_post_in_age_range(created_utc, min_days, max_days) -> bool:
    post_date = datetime.datetime.fromtimestamp(created_utc, datetime.timezone.utc)
    age_days = (datetime.datetime.now(datetime.timezone.utc) - post_date).days
    return min_days <= age_days <= max_days

def clean_html(raw_html):
    """Strip HTML tags and unescape text from Atom feed content blocks."""
    if not raw_html:
        return ""
    # Unescape HTML entities (e.g., &lt; to <)
    clean = html.unescape(raw_html)
    # Strip HTML tags
    clean = re.sub(r'<[^>]*>', '', clean)
    # Clean duplicate newlines
    clean = re.sub(r'\n+', '\n', clean).strip()
    return clean

def fetch_comments_for_post(permalink, post_id, post_title, post_body, subreddit_name, min_days, max_days, seen_ids) -> list:
    """Fetch and parse comments for a post using the public RSS comments endpoint."""
    results = []
    
    # Custom feed User-Agent to prevent 403 blocks
    user_agent = config["reddit"].get("user_agent") or "FeedReader/1.0 (by /u/snapgo_operator)"
    if "your_username" in user_agent or "your_user" in user_agent:
        user_agent = "SnapgoCommuteApp/2.0 (by /u/snapgo_operator)"
        
    headers = {
        "User-Agent": user_agent
    }
    
    url = f"https://www.reddit.com{permalink.rstrip('/')}.rss"
    
    try:
        limiter.wait()
        response = requests.get(url, headers=headers, timeout=10)
        
        # Retry with backoff if rate-limited
        if response.status_code == 429:
            log.warning(f"Rate limited (429) on comments for post {post_id}. Backing off for 12s...")
            time.sleep(12)
            limiter.wait()
            response = requests.get(url, headers=headers, timeout=10)
            
        if response.status_code != 200:
            log.warning(f"Failed to fetch comments RSS for post {post_id}: Status {response.status_code}")
            return []
            
        root = ET.fromstring(response.content)
        entries = root.findall('atom:entry', ATOM_NS)
        
        for entry in entries:
            cid_text = entry.find('atom:id', ATOM_NS).text
            cid = cid_text.split('/')[-1] if '/' in cid_text else cid_text
            if '_' in cid:
                cid = cid.split('_')[-1]
                
            # Skip parent post entry, duplicate comments, or already processed ones
            if cid == post_id or cid in seen_ids or is_already_processed(cid):
                continue
            seen_ids.add(cid)
            
            updated_str = entry.find('atom:updated', ATOM_NS).text
            dt = datetime.datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            created_utc = dt.timestamp()
            
            if not is_post_in_age_range(created_utc, min_days, max_days):
                continue
                
            content_elem = entry.find('atom:content', ATOM_NS)
            raw_content = content_elem.text if content_elem is not None else ""
            body = clean_html(raw_content)
            
            # Local keyword filtering to save downstream AI token costs
            keywords = config["scraper"].get("keywords", [])
            post_text = f"{post_title} {post_body}".lower()
            comment_text = body.lower()
            
            if not keywords or any(kw.lower() in comment_text or kw.lower() in post_text for kw in keywords):
                results.append({
                    "id": cid,
                    "title": post_title,
                    "body": body,
                    "post_body": post_body,
                    "created_utc": created_utc,
                    "subreddit": subreddit_name,
                    "url": f"https://www.reddit.com{entry.find('atom:link', ATOM_NS).attrib.get('href', permalink)}",
                    "type": "comment",
                    "parent_post_id": post_id,
                })
                
    except Exception as e:
        log.warning(f"Error parsing comments Atom feed for post {post_id}: {e}")
        
    return results

def fetch_posts_from_subreddit(subreddit_name, limit=200) -> list:
    """Fetch transportation posts from a subreddit using the public Reddit Search RSS endpoint with a combined query."""
    min_days = config["scraper"]["min_post_age_days"]
    max_days = config["scraper"]["max_post_age_days"]
    include_comments = config["scraper"].get("include_comments", False)
    keywords = config["scraper"].get("keywords", [])
    results = []
    seen_ids = set()

    user_agent = config["reddit"].get("user_agent") or "FeedReader/1.0 (by /u/snapgo_operator)"
    if "your_username" in user_agent or "your_user" in user_agent:
        user_agent = "SnapgoCommuteApp/2.0 (by /u/snapgo_operator)"
        
    headers = {
        "User-Agent": user_agent
    }

    # Format keywords with OR logic
    if keywords:
        formatted_kws = []
        for kw in keywords:
            if " " in kw:
                formatted_kws.append(f'"{kw}"')
            else:
                formatted_kws.append(kw)
        query_string = " OR ".join(formatted_kws)
    else:
        query_string = "commute"

    log.info(f"Fetching posts from r/{subreddit_name} using public search RSS...")
    start_time = time.time()

    try:
        log.info(f"Querying RSS search with query: {query_string} in r/{subreddit_name}...")
        url = f"https://www.reddit.com/r/{subreddit_name}/search.rss"
        params = {
            "q": query_string,
            "restrict_sr": 1,
            "t": "month",
            "limit": limit
        }
        
        limiter.wait()
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        # Backoff for rate limits
        if response.status_code == 429:
            log.warning(f"Rate limited (429) on search.rss in r/{subreddit_name}. Sleeping for 30s...")
            time.sleep(30)
            limiter.wait()
            response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            log.error(f"Failed to fetch public RSS for query in r/{subreddit_name}: Status {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        entries = root.findall('atom:entry', ATOM_NS)
        log.info(f"Found {len(entries)} RSS search entries in r/{subreddit_name}")

        for entry in entries:
            # Parse unique ID
            id_text = entry.find('atom:id', ATOM_NS).text
            post_id = id_text.split('/')[-1] if '/' in id_text else id_text
            if '_' in post_id:
                post_id = post_id.split('_')[-1]
                
            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            # Parse timestamp
            updated_str = entry.find('atom:updated', ATOM_NS).text
            dt = datetime.datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            created_utc = dt.timestamp()

            if not is_post_in_age_range(created_utc, min_days, max_days):
                continue
            if is_already_processed(post_id):
                continue

            title = entry.find('atom:title', ATOM_NS).text
            link_elem = entry.find('atom:link', ATOM_NS)
            permalink = link_elem.attrib.get('href') if link_elem is not None else ""
            
            content_elem = entry.find('atom:content', ATOM_NS)
            raw_content = content_elem.text if content_elem is not None else ""
            body = clean_html(raw_content)

            results.append({
                "id": post_id,
                "title": title,
                "body": body,
                "created_utc": created_utc,
                "subreddit": subreddit_name,
                "url": permalink,
                "type": "post"
            })

            # Fetch comments if enabled
            if include_comments and permalink:
                time.sleep(3.0) # rate limit politeness delay
                comments = fetch_comments_for_post(
                    permalink.replace("https://www.reddit.com", ""), post_id, title, body, subreddit_name, 
                    min_days, max_days, seen_ids
                )
                results.extend(comments)

    except Exception as e:
        log.error(f"Error querying public RSS search in r/{subreddit_name}: {e}")
        time.sleep(3)

    log.info(f"Finished fetching public posts from r/{subreddit_name} in {time.time() - start_time:.2f} seconds. Extracted {len(results)} items.")
    return results

def get_exploratory_subreddits():
    if not os.path.exists(EXPLORATORY_FILE):
        return []

    data = load_json(EXPLORATORY_FILE)
    last_updated = data.get("last_updated", "")
    refresh_days = config["subreddits"]["exploratory_refresh_days"]

    if not last_updated or (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(last_updated)).days >= refresh_days:
        log.info("Exploratory subreddit list needs refresh")
        return []

    return data.get("subreddits", [])

def update_exploratory_subreddits(new_subreddits):
    data = {
        "last_updated": datetime.datetime.utcnow().isoformat(),
        "subreddits": new_subreddits
    }
    os.makedirs("data", exist_ok=True)
    save_json(data, EXPLORATORY_FILE)
    log.info(f"Updated exploratory subreddits: {', '.join(new_subreddits)}")

def scrape_subreddits() -> list:
    """Scrapes target queries using the Playwright browser automation scraper."""
    from reddit.playwright_scraper import scrape_subreddits_playwright
    return scrape_subreddits_playwright()
