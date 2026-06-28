import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        # Setup context with a realistic viewport and user agent
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://www.reddit.com/"
        print(f"Loading URL: {url}")
        await page.goto(url)
        print("Reddit Home URL:", page.url)
        print("Reddit Home Title:", await page.title())
        await page.screenshot(path="data/www_reddit_home.png")
        print("Screenshot saved to data/www_reddit_home.png")
        
        url_sub_search = "https://www.reddit.com/r/delhi/search/?q=carpool&restrict_sr=1"
        print(f"Loading URL: {url_sub_search}")
        await page.goto(url_sub_search)
        print("Delhi Subreddit Search URL:", page.url)
        print("Delhi Subreddit Search Title:", await page.title())
        await page.screenshot(path="data/www_reddit_sub_search.png")
        print("Screenshot saved to data/www_reddit_sub_search.png")
        
        results = await page.locator(".search-result").all()
        print(f"Found {len(results)} search results on old.reddit.com!")
        
        for idx, res in enumerate(results[:3], 1):
            title_node = res.locator(".search-title")
            title = await title_node.text_content() if await title_node.count() > 0 else "N/A"
            
            link_node = res.locator(".search-title")
            href = await link_node.get_attribute("href") if await link_node.count() > 0 else "N/A"
            
            subreddit_node = res.locator(".search-subreddit")
            sub = await subreddit_node.text_content() if await subreddit_node.count() > 0 else "N/A"
            
            author_node = res.locator(".author")
            author = await author_node.text_content() if await author_node.count() > 0 else "N/A"
            
            score_node = res.locator(".search-score")
            score = await score_node.text_content() if await score_node.count() > 0 else "N/A"
            
            comments_node = res.locator(".search-comments")
            comments = await comments_node.text_content() if await comments_node.count() > 0 else "N/A"
            
            time_node = res.locator("time")
            post_time = await time_node.get_attribute("datetime") if await time_node.count() > 0 else "N/A"
            
            print(f"\n{idx}. Title: {title.strip()}")
            print(f"   URL: {href}")
            print(f"   Subreddit: {sub.strip()}")
            print(f"   Author: {author.strip()}")
            print(f"   Score: {score.strip()}")
            print(f"   Comments: {comments.strip()}")
            print(f"   Time: {post_time}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
