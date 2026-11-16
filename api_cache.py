"""Process-local paced API access with atomic persistent JSON cache."""
import os, time, json, hashlib, threading, tempfile
from pathlib import Path
from datetime import datetime, timezone
import requests

_LOCK=threading.RLock()
_NEXT=0.0
class RateLimited(ValueError): pass

def fetch_cached(key, base, endpoint, pairs, worker=False, ttl=600):
    global _NEXT
    root=Path(os.environ.get('NBA_CACHE_DIR','.nba_api_cache'))
    root.mkdir(parents=True,exist_ok=True)
    token=hashlib.sha256(json.dumps([hashlib.sha256(key.encode()).hexdigest(),base,endpoint,list(pairs)],sort_keys=True).encode()).hexdigest()
    path=root/(token+'.json')
    with _LOCK:
        old=None
        try: old=json.loads(path.read_text())
        except (OSError,ValueError): pass
        if old and time.time()-old['epoch']<ttl: return old['rows'],old['updated']
        deadline=time.monotonic()+(1080 if worker else 100)
        try:
            rows=[]; cursor=None; seen=set()
            for _ in range(250):
                params=list(pairs)+[('per_page',100)]
                if cursor is not None: params.append(('cursor',cursor))
                for attempt in range(3):
                    delay=max(0,_NEXT-time.monotonic())
                    if time.monotonic()+delay+30>deadline: raise RateLimited('API 等候時間過長')
                    time.sleep(delay)
                    r=requests.get(base+endpoint,params=params,headers={'Authorization':key},timeout=30)
                    _NEXT=time.monotonic()+max(0,float(os.environ.get('NBA_API_INTERVAL','13')))
                    if r.status_code!=429: break
                    try: retry=float(r.headers.get('Retry-After',65))
                    except ValueError: retry=65
                    _NEXT=max(_NEXT,time.monotonic()+max(1,retry))
                    if not worker: break
                if r.status_code==429: raise RateLimited('API 次數限制，請稍後再試')
                if r.status_code in (401,403): raise ValueError('API Key 無效或方案未授權')
                r.raise_for_status(); obj=r.json(); data=obj['data']; rows.extend(data if isinstance(data,list) else [data])
                cursor=obj.get('meta',{}).get('next_cursor')
                if cursor is None:
                    updated=datetime.now(timezone.utc).isoformat(timespec='seconds')
                    with tempfile.NamedTemporaryFile(mode='w',dir=root,delete=False) as f:
                        json.dump(dict(rows=rows,updated=updated,epoch=time.time()),f); temp=f.name
                    os.replace(temp,path); return rows,updated
                if cursor in seen: raise ValueError('API 分頁異常')
                seen.add(cursor)
            raise ValueError('API 分頁未完整')
        except (RateLimited,requests.RequestException) as e:
            if old and not worker and time.time()-old['epoch']<max(ttl*2,86400): return old['rows'],old['updated']
            raise e
