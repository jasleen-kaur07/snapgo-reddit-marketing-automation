import requests
import xml.etree.ElementTree as ET
import datetime
import re
import html
import time

def clean_html(raw_html):
    if not raw_html:
        return ""
    # Unescape HTML entities
    clean = html.unescape(raw_html)
    # Strip HTML tags
    clean = re.sub(r'<[^>]*>', '', clean)
    clean = re.sub(r'\n+', '\n', clean).strip()
    return clean

# Sleep for a bit to clear rate limit
print("Sleeping for 10 seconds to avoid 429...")
time.sleep(10)

url = "https://www.reddit.com/r/delhi/search.rss"
params = {
    "q": "metro",
    "restrict_sr": 1,
    "t": "month",
    "limit": 5
}
headers = {
    "User-Agent": "SnapgoCommuteApp/2.0 (by /u/snapgo_operator)"
}

response = requests.get(url, params=params, headers=headers, timeout=10)
print("Status:", response.status_code)
if response.status_code == 200:
    root = ET.fromstring(response.content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('atom:entry', ns)
    print(f"Fetched {len(entries)} entries successfully!")
    for idx, entry in enumerate(entries[:3], 1):
        title = entry.find('atom:title', ns).text
        link_elem = entry.find('atom:link', ns)
        link = link_elem.attrib.get('href') if link_elem is not None else ""
        updated_str = entry.find('atom:updated', ns).text
        
        # Parse timestamp
        dt = datetime.datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
        created_utc = dt.timestamp()
        
        # Parse ID
        id_text = entry.find('atom:id', ns).text
        post_id = id_text.split('/')[-1] if '/' in id_text else id_text
        if '_' in post_id:
            post_id = post_id.split('_')[-1]
            
        content_elem = entry.find('atom:content', ns)
        raw_content = content_elem.text if content_elem is not None else ""
        body = clean_html(raw_content)
        
        print(f"\n{idx}. Title: {title}")
        print(f"   Post ID: {post_id}")
        print(f"   Created UTC: {created_utc} ({dt.isoformat()})")
        print(f"   Body snippet: {body[:150]}")
else:
    print("Fail:", response.text[:200])
