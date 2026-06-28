import asyncio
from playwright.async_api import async_playwright
import bs4

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print("Loading Reddit Home Page first to initialize cookies...")
        await page.goto("https://www.reddit.com/")
        await page.wait_for_timeout(3000)
        
        url = "https://www.reddit.com/search/?q=carpool+delhi"
        print(f"Loading URL: {url}")
        await page.goto(url)
        print("Page URL after load:", page.url)
        print("Page Title:", await page.title())
        await page.wait_for_timeout(5000)
        
        # Save screenshot
        import os
        os.makedirs("data", exist_ok=True)
        await page.screenshot(path="data/inspect_search_dom.png")
        print("Screenshot saved to data/inspect_search_dom.png")
        
        # Look for matching search result text in HTML
        content = await page.content()
        print("Page content length:", len(content))
        soup = bs4.BeautifulSoup(content, "html.parser")
        
        # Parse search results
        content = await page.content()
        soup = bs4.BeautifulSoup(content, "html.parser")
        
        trackers = soup.find_all("search-telemetry-tracker", attrs={"data-testid": "search-sdui-post"})
        print(f"Found {len(trackers)} search post telemetry trackers!")
        
        posts = []
        for tracker in trackers[:3]:
            try:
                import json
                context_str = tracker.get("data-faceplate-tracking-context")
                context = json.loads(context_str)
                post_info = context.get("post", {})
                sub_info = context.get("subreddit", {})
                profile_info = context.get("profile", {})
                
                post_id = post_info.get("id", "").split("_")[-1]
                title = post_info.get("title", "")
                subreddit = sub_info.get("name", "")
                author = profile_info.get("name", "anonymous")
                nsfw = post_info.get("nsfw", False)
                
                # Extract URL
                title_link = tracker.find("a", attrs={"data-testid": "post-title"})
                permalink = title_link.get("href") if title_link else ""
                url = f"https://www.reddit.com{permalink}" if permalink else ""
                
                # Extract upvotes, comments, time
                upvotes = 0
                comments = 0
                post_time = ""
                
                number_tags = tracker.find_all("faceplate-number")
                if len(number_tags) >= 2:
                    upvotes = int(number_tags[0].get("number", 0))
                    comments = int(number_tags[1].get("number", 0))
                elif len(number_tags) == 1:
                    upvotes = int(number_tags[0].get("number", 0))
                    
                time_tag = tracker.find("faceplate-timeago")
                if time_tag:
                    post_time = time_tag.get("ts", "")
                    
                posts.append({
                    "id": post_id,
                    "title": title,
                    "subreddit": subreddit,
                    "author": author,
                    "url": url,
                    "upvotes": upvotes,
                    "comments": comments,
                    "time": post_time,
                    "nsfw": nsfw
                })
            except Exception as e:
                print("Error parsing post tracker:", e)
                
        print(f"Parsed {len(posts)} posts metadata successfully:")
        for idx, p in enumerate(posts, 1):
            print(f"\n{idx}. [{p['subreddit']}] {p['title']}")
            print(f"   Author: {p['author']} | Upvotes: {p['upvotes']} | Comments: {p['comments']} | Time: {p['time']}")
            print(f"   URL: {p['url']}")
            
        # Navigate to first post URL to extract body
        if posts and posts[0]["url"]:
            post_url = posts[0]["url"]
            print(f"\nNavigating to post page: {post_url} to extract body...")
            await page.goto(post_url)
            await page.wait_for_timeout(4000)
            
            post_content = await page.content()
            post_soup = bs4.BeautifulSoup(post_content, "html.parser")
            
            # Find body content
            # Modern Reddit body text is typically in a div with slot="text-body" or similar
            body_div = post_soup.find("div", slot="text-body") or post_soup.find("div", attrs={"data-click-id": "text_content"})
            if not body_div:
                # Fallback: search for post-content div or text paragraph
                body_div = post_soup.find("div", class_="text-neutral-content-strong") or post_soup.find("div", class_="post-body")
                
            body_text = ""
            if body_div:
                body_text = body_div.text.strip()
            else:
                # General fallback: check any paragraphs in the article
                paragraphs = post_soup.find_all("p")
                body_text = "\n".join([p.text.strip() for p in paragraphs[:3]])
                
            print("\nExtracted Body (First 300 chars):")
            print(body_text[:300])
                
        # Fallback inspection of search result items
        results_container = soup.find(attrs={"data-testid": "search-results-container"})
        if results_container:
            print("Found search-results-container!")
        else:
            # Find any article tags
            articles = soup.find_all("article")
            print(f"Found {len(articles)} article tags!")
            for idx, art in enumerate(articles[:2], 1):
                print(f"Article {idx} HTML:")
                print(str(art)[:800])
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
