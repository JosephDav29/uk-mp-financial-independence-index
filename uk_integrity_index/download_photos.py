import time
from pathlib import Path
import pandas as pd
import requests

BASE_URL='https://members-api.parliament.uk/api/Members'
PROJECT=Path(__file__).resolve().parent
SCORES=PROJECT/'data'/'scores.csv'
PHOTO_DIR=PROJECT/'static'/'photos'
PHOTO_DIR.mkdir(parents=True,exist_ok=True)

def mid(v):
    try:return str(int(float(v)))
    except:return None

def find_url(o):
    if isinstance(o,str) and o.startswith(('http://','https://')): return o
    if isinstance(o,dict):
        for k in ('url','Url','imageUrl','ImageUrl','href','Href','value','Value'):
            if k in o:
                x=find_url(o[k])
                if x:return x
        for v in o.values():
            x=find_url(v)
            if x:return x
    if isinstance(o,list):
        for v in o:
            x=find_url(v)
            if x:return x
    return None

def main():
    if not SCORES.exists():
        print('ERROR: scores.csv not found:',SCORES); return
    df=pd.read_csv(SCORES)
    if 'Mnis Id' not in df.columns:
        print("ERROR: 'Mnis Id' column not found."); return
    ids=[]
    for v in df['Mnis Id'].dropna().unique():
        x=mid(v)
        if x and x not in ids: ids.append(x)
    print(f'Found {len(ids)} unique MP IDs.')
    s=requests.Session(); s.headers['User-Agent']='UK-Integrity-Index/1.0'
    ok=missing=0
    for i,x in enumerate(ids,1):
        out=PHOTO_DIR/f'{x}.jpg'
        if out.exists() and out.stat().st_size>1000:
            print(f'[{i}/{len(ids)}] {x}: already exists'); ok+=1; continue
        try:
            r=s.get(f'{BASE_URL}/{x}/Portrait',params={'cropType':'ThreeFour','webVersion':'true'},timeout=30)
            if r.ok and r.headers.get('content-type','').lower().startswith('image/') and len(r.content)>1000:
                out.write_bytes(r.content); print(f'[{i}/{len(ids)}] {x}: downloaded'); ok+=1; time.sleep(.05); continue
            r=s.get(f'{BASE_URL}/{x}/PortraitUrl',timeout=30)
            u=find_url(r.json()) if r.ok else None
            if u:
                r=s.get(u,timeout=30)
                if r.ok and r.headers.get('content-type','').lower().startswith('image/') and len(r.content)>1000:
                    out.write_bytes(r.content); print(f'[{i}/{len(ids)}] {x}: downloaded'); ok+=1; time.sleep(.05); continue
            print(f'[{i}/{len(ids)}] {x}: no portrait'); missing+=1
        except Exception as e:
            print(f'[{i}/{len(ids)}] {x}: failed - {e}'); missing+=1
    print(f'Finished. Downloaded/already present: {ok}; missing/failed: {missing}')
    print('Photos:',PHOTO_DIR)

if __name__=='__main__': main()
