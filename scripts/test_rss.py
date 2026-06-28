import requests
import xml.etree.ElementTree as ET
import time

url = "https://www.reddit.com/r/delhi/search.rss"
q = 'carpool OR commute OR metro OR bus OR train OR "fuel cost" OR "office travel" OR "student travel" OR traffic OR parking'
params = {
    "q": q,
    "restrict_sr": 1,
    "t": "month",
    "limit": 10
}
headers = {
    "User-Agent": "SnapgoCommuteApp/2.0 (by /u/snapgo_operator)"
}

print(f"Testing combined RSS query: {q}")
response = requests.get(url, params=params, headers=headers, timeout=10)
print(f"Response status: {response.status_code}")
if response.status_code == 200:
    root = ET.fromstring(response.content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('atom:entry', ns)
    print(f"Success! Got {len(entries)} entries with combined query!")
    for idx, entry in enumerate(entries[:5], 1):
        print(f"{idx}. {entry.find('atom:title', ns).text}")
else:
    print("Response text:", response.text[:300])
