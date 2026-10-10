"""MANGAMA: incremental, conservative Google Books cover import.
Do not bypass provider throttling. Stops immediately on 429 and saves progress.
"""
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'mangama-series.json'
OUTPUT = ROOT / 'copertine-alternative.json'
MANGAYO = ROOT / 'copertine-mangayo.json'
BATCH = max(1, min(int(os.getenv('MANGAMA_BATCH', '5')), 20))
PAUSE = max(3.0, float(os.getenv('MANGAMA_PAUSE', '6')))


def norm(value):
    raw = unicodedata.normalize('NFKD', str(value).lower())
    raw = ''.join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', raw).strip()


def matches(title, series, number):
    t = norm(title)
    target = norm(series['title'])
    if target not in t or not re.search(r'(?<!\d)' + str(number) + r'(?!\d)', t):
        return False
    edition = norm(series.get('edition', ''))
    for marker, alternatives in [
        ('full color', ['full color', 'color']),
        ('grimoire', ['grimoire']),
        ('deluxe', ['deluxe', 'ultimate']),
        ('new edition', ['new edition']),
        ('box', ['box']),
        ('serie nera', ['nera']),
    ]:
        if marker in edition and not any(word in t for word in alternatives):
            return False
    return True


def write_atomic(data):
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(OUTPUT)


def main():
    series = json.loads(SOURCE.read_text(encoding='utf-8'))
    state = json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
    state.setdefault('source', 'Google Books API')
    for item, default in [('covers', {}), ('review', {}), ('checked', [])]:
        state.setdefault(item, default)
    done = set(state['checked'])
    mango = json.loads(MANGAYO.read_text(encoding='utf-8')).get('covers', {}) if MANGAYO.exists() else {}
    session = requests.Session()
    session.headers['User-Agent'] = 'MANGAMA personal library / GitHub Actions'
    attempted = added = review_count = 0
    stopped = None
    for entry in series:
        sid = str(entry['id'])
        for number in range(1, int(entry['volumes']) + 1):
            key = f'{sid}:{number}'
            if key in done or str(number) in mango.get(sid, {}) or str(number) in state['covers'].get(sid, {}):
                continue
            if attempted >= BATCH:
                stopped = 'Limite del lotto raggiunto'
                break
            if attempted:
                time.sleep(PAUSE)
            attempted += 1
            try:
                response = session.get('https://www.googleapis.com/books/v1/volumes', params={
                    'q': f'intitle:{entry["title"]} {number}', 'maxResults': 15, 'printType': 'books',
                }, timeout=20)
                if response.status_code == 429:
                    stopped = 'Google Books: HTTP 429 (limite richieste); stop immediato, riprovare in seguito'
                    print(stopped, flush=True)
                    break
                if response.status_code in (500, 502, 503, 504):
                    stopped = f'Google Books: HTTP {response.status_code}; stop per errore temporaneo'
                    print(stopped, flush=True)
                    break
                response.raise_for_status()
                candidates = []
                for obj in response.json().get('items', []):
                    info = obj.get('volumeInfo', {})
                    name = (info.get('title', '') + ' ' + info.get('subtitle', '')).strip()
                    cover = info.get('imageLinks', {}).get('thumbnail') or info.get('imageLinks', {}).get('smallThumbnail')
                    if not cover or not matches(name, entry, number):
                        continue
                    publisher = norm(info.get('publisher', ''))
                    lang = info.get('language', '')
                    isbn = next((x.get('identifier','') for x in info.get('industryIdentifiers', []) if x.get('type') == 'ISBN_13'), '')
                    italian = any(x in publisher for x in ('j pop', 'jpop', 'star comics', 'planet manga', 'panini', 'dynit', 'flashbook', 'goen', 'bd edizioni', 'magic press', 'hikari'))
                    score = 2 if italian and lang in ('it', '') else 1
                    if urlparse(cover).scheme not in ('http', 'https'):
                        continue
                    candidates.append((score, cover.replace('http:', 'https:'), name, publisher, isbn))
                high = {x[1] for x in candidates if x[0] == 2}
                if len(high) == 1:
                    state['covers'].setdefault(sid, {})[str(number)] = next(iter(high))
                    added += 1
                    print('COPERTINA', entry['title'], number, flush=True)
                elif candidates:
                    state['review'][key] = [{'url': x[1], 'title': x[2], 'publisher': x[3], 'isbn': x[4]} for x in candidates[:5]]
                    review_count += 1
                done.add(key)
                state['checked'] = sorted(done)
                write_atomic(state)
            except (requests.RequestException, ValueError) as err:
                stopped = f'Errore rete/API: {str(err)[:120]}'
                print(stopped, flush=True)
                break
        if stopped:
            break
    state['checked'] = sorted(done)
    write_atomic(state)
    print(f'RISULTATO: richieste={attempted}, nuove={added}, da_verificare={review_count}, controllati_totali={len(done)}, motivo_stop={stopped or "fine catalogo"}', flush=True)


if __name__ == '__main__':
    main()
