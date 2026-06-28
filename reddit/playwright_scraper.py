import asyncio
import urllib.parse
import json
import re
import bs4
import time
from datetime import datetime, UTC
from playwright.async_api import async_playwright

from config.config_loader import get_config
from db.reader import is_already_processed, get_existing_post
from db.writer import insert_post
from utils.logger import setup_logger

log = setup_logger()
config = get_config()

def get_location_keywords() -> list:
    """Retrieve all location keywords from configuration."""
    locations = config.get("locations", {})
    primary = locations.get("primary", [])
    secondary = locations.get("secondary", [])
    return [loc.lower() for loc in (primary + secondary) if loc]

def has_locations(title: str, body: str) -> bool:
    """Check if the text contains any location keywords."""
    text = f"{title} {body}".lower()
    keywords = get_location_keywords()
    if not keywords:
        keywords = [
            "delhi", "new delhi", "noida", "greater noida", "gurugram", 
            "gurgaon", "ghaziabad", "faridabad", "bangalore", "mumbai", 
            "hyderabad", "pune"
        ]
    return any(kw in text for kw in keywords)

def extract_body_from_soup(soup) -> str:
    """Extract post body text from modern Reddit layouts."""
    # modern layout slot
    body_div = soup.find("div", slot="text-body")
    if body_div:
        return body_div.text.strip()
    
    # legacy attribute layout
    body_div = soup.find("div", attrs={"data-click-id": "text_content"})
    if body_div:
        return body_div.text.strip()
        
    # CSS classes
    for cls in ["text-neutral-content-strong", "post-body", "RichTextJSON-root"]:
        div = soup.find("div", class_=cls)
        if div:
            return div.text.strip()
            
    # Paragraph elements inside main article
    paragraphs = soup.find_all("p")
    if paragraphs:
        # filter out very short strings and footers
        lines = [p.text.strip() for p in paragraphs if len(p.text.strip()) > 10]
        return "\n".join(lines[:6])
        
    return ""

async def fetch_post_body(context, url: str) -> str:
    """Open the post URL in a new page/tab to scrape the full body text."""
    if not url:
        return ""
    try:
        page = await context.new_page()
        # Navigate and set a reasonable timeout
        await page.goto(url, timeout=15000)
        # wait a bit for hydration
        await page.wait_for_timeout(2000)
        content = await page.content()
        soup = bs4.BeautifulSoup(content, "html.parser")
        body = extract_body_from_soup(soup)
        await page.close()
        return body
    except Exception as e:
        log.warning(f"Error fetching post body from {url}: {e}")
        try:
            await page.close()
        except Exception:
            pass
        return ""

async def scrape_queries_async() -> list:
    """Core async scraper logic executing Playwright searches sequentially."""
    locations = config.get("locations", {})
    primary_locations = locations.get("primary", [])
    secondary_locations = locations.get("secondary", [])
    
    # Transportation keywords/topics
    topics = config.get("scraper", {}).get("keywords", [])
    if not topics:
        topics = [
            "carpool", "ride sharing", "commute", "office commute", "student travel",
            "college commute", "fuel cost", "petrol", "metro", "public transport",
            "traffic", "parking", "office travel", "daily travel", "bike pooling"
        ]
        
    # Generate search queries prioritizing Delhi NCR combinations
    primary_queries = [f"{topic} {loc}" for loc in primary_locations for topic in topics]
    secondary_queries = [f"{topic} {loc}" for loc in secondary_locations for topic in topics]
    all_queries = primary_queries + secondary_queries
    
    max_queries = config.get("scraper", {}).get("max_search_queries", 15)
    queries_to_run = all_queries[:max_queries]
    
    stored_posts = []
    seen_ids = set()
    
    log.info("Starting Playwright...")
    
    async with async_playwright() as p:
        # Launch Google Chrome with automation-bypass arguments
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # Land on the Reddit home page first to set session cookies
        log.info("Establishing Reddit session cookies...")
        try:
            page = await context.new_page()
            await page.goto("https://www.reddit.com/", timeout=15000)
            await page.wait_for_timeout(3000)
            await page.close()
        except Exception as e:
            log.warning(f"Error establishing session on home page: {e}")
            
        search_page = await context.new_page()
        
        for query in queries_to_run:
            log.info(f"Searching: {query}")
            query_encoded = urllib.parse.quote(query)
            search_url = f"https://www.reddit.com/search/?q={query_encoded}&sort=relevance&t=month"
            
            total_found = 0
            stored_count = 0
            skipped_dup_count = 0
            
            try:
                # Load search URL
                await search_page.goto(search_url, timeout=15000)
                await search_page.wait_for_timeout(5000)
                
                # Check for network security block
                page_title = await search_page.title()
                if "Blocked" in page_title or "whoa there" in (await search_page.content()).lower():
                    log.warning(f"Reddit blocked search for query '{query}'. Retrying navigation once...")
                    await search_page.wait_for_timeout(3000)
                    await search_page.goto(search_url, timeout=15000)
                    await search_page.wait_for_timeout(5000)
                    
                content = await search_page.content()
                soup = bs4.BeautifulSoup(content, "html.parser")
                
                # Locate telemetry trackers containing search results metadata
                trackers = soup.find_all("search-telemetry-tracker", attrs={"data-testid": "search-sdui-post"})
                total_found = len(trackers)
                
                posts_to_process = []
                for tracker in trackers:
                    try:
                        context_str = tracker.get("data-faceplate-tracking-context")
                        if not context_str:
                            continue
                        
                        context_data = json.loads(context_str)
                        post_info = context_data.get("post", {})
                        sub_info = context_data.get("subreddit", {})
                        profile_info = context_data.get("profile", {})
                        
                        post_id = post_info.get("id", "").split("_")[-1]
                        if not post_id:
                            continue
                            
                        title = post_info.get("title", "")
                        subreddit = sub_info.get("name", "")
                        author = profile_info.get("name", "anonymous")
                        nsfw = post_info.get("nsfw", False)
                        
                        # Filter NSFW
                        if nsfw:
                            continue
                            
                        # Filter deleted or removed posts
                        if not title or title.strip() in ("[deleted]", "[removed]"):
                            continue
                            
                        # Filter duplicates in memory
                        if post_id in seen_ids:
                            skipped_dup_count += 1
                            continue
                            
                        seen_ids.add(post_id)
                        
                        # Extract URL link
                        title_link = tracker.find("a", attrs={"data-testid": "post-title"})
                        permalink = title_link.get("href") if title_link else ""
                        if permalink.startswith("http"):
                            url = permalink
                        else:
                            url = f"https://www.reddit.com{permalink}" if permalink else ""
                        
                        # Extract upvotes & comments
                        upvotes = 0
                        comments = 0
                        number_tags = tracker.find_all("faceplate-number")
                        if len(number_tags) >= 2:
                            upvotes = int(number_tags[0].get("number", 0))
                            comments = int(number_tags[1].get("number", 0))
                        elif len(number_tags) == 1:
                            upvotes = int(number_tags[0].get("number", 0))
                            
                        # Extract timestamp
                        post_time = ""
                        time_tag = tracker.find("faceplate-timeago")
                        if time_tag:
                            post_time = time_tag.get("ts", "")
                            
                        # Parse time to seconds since epoch
                        created_utc = time.time()
                        if post_time:
                            try:
                                dt = datetime.fromisoformat(post_time.replace('Z', '+00:00'))
                                created_utc = dt.timestamp()
                            except Exception:
                                pass
                                
                        posts_to_process.append({
                            "id": post_id,
                            "url": url,
                            "title": title,
                            "subreddit": subreddit,
                            "created_utc": created_utc,
                            "upvotes": upvotes,
                            "comments": comments
                        })
                    except Exception as pe:
                        log.debug(f"Error parsing post metadata element: {pe}")
                
                # Fetch all post bodies concurrently in parallel
                if posts_to_process:
                    tasks = [fetch_post_body(context, p["url"]) for p in posts_to_process]
                    bodies = await asyncio.gather(*tasks)
                    
                    import sqlite3
                    for p, body in zip(posts_to_process, bodies):
                        if body.strip() in ("[deleted]", "[removed]"):
                            continue
                            
                        # Query SQLite database for existing record
                        existing_post = get_existing_post(p["id"], p["url"])
                        if existing_post:
                            content_changed = (existing_post["title"] != p["title"]) or (existing_post["body"] != body)
                            is_processed = existing_post["insight_processed"] == 1
                            
                            if is_processed and not content_changed:
                                # Content is identical and already processed. Skip AI processing.
                                skipped_dup_count += 1
                                continue
                            
                            # Content changed: reset AI processing status in SQLite
                            if content_changed:
                                try:
                                    conn = sqlite3.connect(config["database"]["path"])
                                    conn.execute("UPDATE posts SET insight_processed = 0 WHERE id = ?", (existing_post["id"],))
                                    conn.commit()
                                    conn.close()
                                    log.info(f"Post {p['id']} content changed. Resetting AI processing status.")
                                except Exception as dbe:
                                    log.warning(f"Failed to reset insight_processed for post {p['id']}: {dbe}")
                        
                        # Prepare post dictionary for SQLite write
                        tags_list = ["transit"]
                        has_loc = has_locations(p["title"], body)
                        if has_loc:
                            tags_list.append("has-location-keywords")
                            
                        post_dict = {
                            "id": p["id"],
                            "url": p["url"],
                            "title": p["title"],
                            "body": body,
                            "subreddit": p["subreddit"],
                            "created_utc": p["created_utc"],
                            "type": "post",
                            "tags": tags_list
                        }
                        
                        # Store in SQLite database (handles URL deduplication / upserts)
                        insert_post(post_dict, community_type="primary")
                        stored_posts.append(post_dict)
                        stored_count += 1
                        
            except Exception as se:
                log.warning(f"Error executing search query '{query}': {se}. Continuing with next query.")
                
            log.info(f"Found {total_found} posts")
            log.info(f"Stored {stored_count} posts")
            log.info(f"Skipped {skipped_dup_count} duplicate posts")
            # Rate limit politeness delay between queries
            await asyncio.sleep(2)
            
        await search_page.close()
        await browser.close()
        
    log.info(f"Playwright scraping completed. Stored a total of {len(stored_posts)} unique posts.")
    return stored_posts

def scrape_subreddits_playwright() -> list:
    """Synchronous wrapper for the async Playwright scraper."""
    try:
        return asyncio.run(scrape_queries_async())
    except Exception as e:
        log.error(f"Playwright scraping engine failed: {e}")
        return []
