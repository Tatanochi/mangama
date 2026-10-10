"""MANGAMA: conservative alternative cover lookup using the public Google Books API.
Only high-confidence per-volume matches are saved; no bypass of MangaYo restrictions.
Runs in bounded batches to respect API limits. Re-run manually to continue.
"""
import json, os, re, time, unicodedata
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'mangama-series.json'; OUTPUT=ROOT/'copertine-alternative.json'
BATCH=int(os.getenv('MANGAMA_BATCH','65'))
s=requests.Session();s.headers['User-Agent']='MANGAMA personal reading catalog (contact: via GitHub repository)'
def norm(x):
 x=unicodedata.normalize('NFKD',str(x).lower())
 return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in x if not unicodedata.combining(c))).strip()
def equivalent(t,e):
 a,b=norm(t),norm(e)
 return a in b or b in a
def matching_title(title,series,n):
 a=norm(series['title']); t=norm(title)
 if a not in t:return False
 # strict numeric volume: avoid accidentally assigning another volume
 if not re.search(r'(?<!\d)'+str(n)+r'(?!\d)', t):return False
 ed=norm(series['edition']); z=t+' '+norm(series.get('edition',''))
 for marker,words in [('full color',['full color','color']),('grimoire',['grimoire']),('deluxe',['deluxe','ultimate']),('new edition',['new edition']),('box',['box']),('serie nera',['nera'])]:
  if marker in ed and not any(w in t for w in words):return False
 return True
def run():
 series=json.loads(SOURCE.read_text()); result=json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'source':'Google Books API','covers':{},'review':{},'checked':[]}
 result.setdefault('covers',{});result.setdefault('review',{});checked=set(result.get('checked',[])); mango=json.loads((ROOT/'copertine-mangayo.json').read_text()).get('covers',{})
 attempts=0; added=0; uncertain=0
 for b in series:
  for n in range(1,int(b['volumes'])+1):
   id=str(b['id']); key=f'{id}:{n}'
   if key in checked or str(n) in mango.get(id,{}) or str(n) in result['covers'].get(id,{}):continue
   if attempts>=BATCH:break
   attempts+=1
   try:
    query=f'intitle:{b["title"]} {n}'
    response=s.get('https://www.googleapis.com/books/v1/volumes',params={'q':query,'maxResults':20,'printType':'books'},timeout=20)
    if response.status_code in (429,500,502,503):print('API temporaneamente non disponibile, riprova più tardi:',response.status_code);break
    response.raise_for_status();items=response.json().get('items',[])
    candidates=[]
    for entry in items:
     info=entry.get('volumeInfo',{}); title=info.get('title',''); subtitle=info.get('subtitle','')
     image=info.get('imageLinks',{}).get('thumbnail') or info.get('imageLinks',{}).get('smallThumbnail')
     if not image or not matching_title(title+' '+subtitle,b,n):continue
     publisher=norm(info.get('publisher','')); language=info.get('language','')
     isbn=next((x['identifier'] for x in info.get('industryIdentifiers',[]) if x.get('type')=='ISBN_13'),'')
     # Italian-specific publisher, or Italian text/language + ISBN. Without corroboration: review only.
     italian_publisher=any(p in publisher for p in ['j pop','jpop','star comics','planet manga','panini','dynit','flashbook','goen','bd edizioni','magic press','hikari'])
     if italian_publisher and language in ('it',''):
      candidates.append((2,image,title,publisher,isbn))
     else:candidates.append((1,image,title,publisher,isbn))
    good=[x for x in candidates if x[0]==2]
    # Avoid incorrect automatic matches when multiple candidate covers exist
    urls={x[1] for x in good}
    if len(urls)==1:
     result['covers'].setdefault(id,{})[str(n)]=good[0][1].replace('http:','https:');added+=1
     print('OK',b['title'],n,good[0][3])
    elif candidates:
     result['review'][key]=[{'url':x[1],'title':x[2],'publisher':x[3],'isbn':x[4]} for x in candidates[:5]]
     uncertain+=1
    checked.add(key)
   except requests.RequestException as e:
    print('Rete:',str(e)[:100]);break
   except Exception as e:
    print('Errore:',str(e)[:100]);checked.add(key)
   if attempts%10==0:print('Controllati',attempts,'nuove',added,'da verificare',uncertain,flush=True)
   time.sleep(0.35)
  if attempts>=BATCH:break
 result['checked']=sorted(checked); OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print('RISULTATO: controllati in questa esecuzione',attempts,'nuove copertine',added,'da verificare',uncertain,'progresso totale',len(checked),'di',sum(int(x['volumes']) for x in series))
if __name__=='__main__':run()
