import requests

# Let's check a public post detail RSS
url = "https://www.reddit.com/r/delhi/comments/1dlhgh2/title_placeholder.rss"
headers = {
    "User-Agent": "FeedReader/1.0 (by /u/snapgo_operator)"
}

response = requests.get(url, headers=headers, timeout=10)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print("Success! Comments RSS loaded!")
    print(response.text[:500])
else:
    print(response.text[:200])
