import requests

url = "https://www.reddit.com/r/delhi/search.json"
params = {
    "q": "metro",
    "restrict_sr": 1,
    "t": "month",
    "limit": 5
}
headers = {
    "User-Agent": "SnapgoCommuteBot/1.0.0 (by /u/snapgo_operator)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5"
}

response = requests.get(url, params=params, headers=headers, timeout=10)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print("Success! JSON search loaded.")
else:
    print(response.text[:200])
