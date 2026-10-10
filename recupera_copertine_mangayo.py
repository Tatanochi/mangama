"""Build a conservative MangaYo image index for MANGAMA.
Run from an internet-enabled machine: pip install requests beautifulsoup4
It never invents image URLs; only metadata returned by MangaYo product pages is saved.
"""
import json, re, time, unicodedata, urllib.parse
from pathlib import Path
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
BASE='https://mangayo.it'
S=requests.Session();S.headers.update({'User-Agent':'MANGAMA personal collection metadata indexer (low request rate)'})

def fetch(url):
    time.sleep(0.7)
    r=S.get(url, timeout=25);r.raise_for_status()
    return r.text

def norm(s):
    s=unicodedata.normalize('NFKD',s.lower())
    s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def slugs(url):
    return urllib.parse.unquote(urllib.parse.urlparse(url).path).rstrip('/').split('/')[-1]

def sitemap_candidates():
    options=[BASE+'/sitemap.xml', BASE+'/1_it_0_sitemap.xml',BASE+'/sitemap_index.xml']
    try:
        txt=fetch(BASE+'/robots.txt')
        options=[*re.findall(r'(?im)^sitemap:\s*(\S+)',txt),*options]
    except Exception as exc: print('robots.txt non raggiungibile:',exc)
    seen=set();found=set()
    def scan(u, depth=0):
        if depth>3 or u in seen or len(seen)>100: return
        seen.add(u)
        try: root=ET.fromstring(fetch(u))
        except Exception:return
        urls=[node.text.strip() for node in root.iter() if node.tag.endswith('loc') and node.text]
        for link in urls:
            if link.endswith('.xml'):scan(link,depth+1)
            elif '/manga/' in link and re.search(r'/\d+-',link): found.add(link)
    for opt in options:scan(opt)
    return sorted(found)

def search_candidates(title, edition):
    # Backup where MangaYo's sitemap is unavailable; limited to first search page.
    phrase=f'{title} {edition}'.strip()
    urls=[BASE+'/ricerca?controller=search&s='+urllib.parse.quote(phrase),BASE+'/search?controller=search&s='+urllib.parse.quote(title)]
    found=set()
    for link in urls:
        try:
            soup=BeautifulSoup(fetch(link),'html.parser')
            for a in soup.find_all('a',href=True):
                u=urllib.parse.urljoin(BASE,a['href'])
                if u.startswith(BASE+'/manga/') and re.search(r'/\d+-',u):found.add(u.split('?')[0])
        except Exception as e: print('Ricerca non disponibile',str(e)[:70])
    return sorted(found)

def image_for_page(url):
    soup=BeautifulSoup(fetch(url),'html.parser')
    og=soup.find('meta',attrs={'property':'og:image'}) or soup.find('meta',attrs={'name':'twitter:image'})
    title=(soup.find('meta',attrs={'property':'og:title'}) or soup.find('h1'))
    name=(title.get('content') if title and title.name=='meta' else title.get_text(' ',strip=True) if title else '').strip()
    img=urllib.parse.urljoin(BASE,og.get('content','')) if og else ''
    if not img.startswith('https://') or not re.search(r'\.(?:jpg|jpeg|png|webp)(?:$|\?)',img,re.I):return name,''
    return name,img

def exact_match(series, product, num):
    # Strictly require the exact volume number at the end, and product title containing series.
    a=norm(series['title']); p=norm(product)
    if not p.endswith(' '+str(num)):return False
    body=p[:-(len(str(num))+1)].strip()
    if not (body==a or body.startswith(a+' ')):return False
    ed=norm(series['edition'])
    # Strong disambiguation for collector's editions.
    qualifiers={'ultimate':['ultimate','deluxe'],'new edition':['new edition'],'full color':['color'],'grimoire':['grimoire'],'serie nera':['nera'],'deluxe':['deluxe'],'collection':['collection']}
    for marker,required in qualifiers.items():
        if marker in ed and not any(word in body for word in required):return False
    return True

def main():
    series=json.loads((ROOT/'mangama-series.json').read_text())
    out=ROOT/'copertine-mangayo.json'
    data=json.loads(out.read_text()) if out.exists() else {'source':'mangayo.it','covers':{}}
    data.setdefault('covers',{})
    candidates=sitemap_candidates()
    print('Schede prodotto in sitemap:',len(candidates))
    for s in series:
        name=s['title']; ed=s['edition']; mapping=data['covers'].setdefault(s['id'],{})
        urls=[u for u in candidates if norm(name) in norm(slugs(u))]
        if not urls:urls=search_candidates(name,ed)
        # Only fetch candidate pages plausibly ending with a volume number.
        by_vol={}
        for url in urls:
            match=re.search(r'-(\d+)\.html$',slugs(url))
            # PrestaShop URL: last token can be volume; skip numeric product ID prefix
            if match:
                n=int(match.group(1))
                if 1<=n<=s['volumes']:by_vol.setdefault(n,[]).append(url)
        for n in range(1,s['volumes']+1):
            if str(n) in mapping:continue
            for url in by_vol.get(n,[])[:3]:
                try:
                    title,img=image_for_page(url)
                    if exact_match(s,title,n) and img:
                        mapping[str(n)]=img;print('OK',name,ed,n);break
                except Exception as e: print('SKIP',str(e)[:70])
        data['covers'][s['id']]=mapping
        out.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    total=sum(len(v) for v in data['covers'].values())
    print('Totale immagini associate:',total,'/ posizioni volume:',sum(s['volumes'] for s in series))

if __name__=='__main__': main()
