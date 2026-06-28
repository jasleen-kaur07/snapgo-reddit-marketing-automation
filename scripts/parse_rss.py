import requests
import xml.etree.ElementTree as ET

url = "https://www.reddit.com/r/delhi/search.rss"
params = {
    "q": "metro",
    "restrict_sr": 1,
    "t": "month",
    "limit": 5
}
headers = {
    "User-Agent": "FeedReader/1.0 (by /u/snapgo_operator)"
}

response = requests.get(url, params=params, headers=headers)
if response.status_code == 200:
    root = ET.fromstring(response.content)
    # Namespaces are commonly used in Atom feeds
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    print("Feed Title:", root.find('atom:title', ns).text)
    
    entries = root.findall('atom:entry', ns)
    print(f"Found {len(entries)} entries:")
    for idx, entry in enumerate(entries, 1):
        title = entry.find('atom:title', ns).text
        link_elem = entry.find("atom:link", ns)
        link = link_elem.attrib.get('href') if link_elem is not None else ""
        updated = entry.find('atom:updated', ns).text
        content_elem = entry.find('atom:content', ns)
        content = content_elem.text if content_elem is not None else ""
        
        # ID is usually in format "t3_12abc" or similar (or full URI)
        id_text = entry.find('atom:id', ns).text
        # Extract the short post ID from the URI or ID text
        # Typically of the form: t3_12abc (where 12abc is the post ID)
        post_id = id_text.split('/')[-1] if '/' in id_text else id_text
        if '_' in post_id:
            post_id = post_id.split('_')[-1]
            
        print(f"\n{idx}. Title: {title}")
        print(f"   ID: {post_id}")
        print(f"   Link: {link}")
        print(f"   Updated: {updated}")
        print(f"   Content Length: {len(content)}")
else:
    print("Error:", response.status_code)
