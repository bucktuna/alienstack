#!/usr/bin/env python3
"""Oracle: phone-first voice sound-design studio (LAN + optional public quick tunnel).

Service/install names stay voice-studio for compatibility."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
from collections import deque
from urllib.parse import urlsplit
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from threading import BoundedSemaphore, Lock
import time
from typing import Optional
from uuid import UUID, uuid4

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
import ipaddress
from pydantic import BaseModel, Field, ConfigDict

from voicepipe import Pipeline, Style, ROOT, SR, parse
import oracle
import talk
import threading
import queue

APP = FastAPI(title='Oracle', docs_url='/api/docs')
OUTPUT = ROOT/'renders'
OUTPUT.mkdir(exist_ok=True)
SETTINGS_FILE = ROOT/'settings.json'
HISTORY_FILE = ROOT/'oracle-history.json'
TOKEN_FILE = ROOT/'.oracle-token'
VOICE_NAMES = sorted(np.load(ROOT/'models/voices-v1.0.bin',allow_pickle=False).files)
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice-render')
SLOT = BoundedSemaphore(1)
LOCK = Lock()
ORACLE_LOCK = Lock()
WAITERS = BoundedSemaphore(3)   # small max queue for Oracle requests waiting on the model/render slot
RATE = {}                      # public client key -> deque of request times
RATE_LOCK = Lock()
PUBLIC_PER_MIN, PUBLIC_TOTAL_PER_MIN = 6, 30
RATE_PATHS = ('/api/render', '/api/oracle')
TALK_PER_MIN, TALK_TOTAL_PER_MIN = 6, 24
TALK_MAX_BYTES = 1_500_000
TALK_DIR = ROOT/'renders'/'talk'
TALK_DIR.mkdir(parents=True, exist_ok=True)
TALK_FILE = ROOT/'talk-history.json'
TALKS = {}
TALK_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='talk')
FILE_LOCK = Lock()
JOBS = {}
ENGINE = Pipeline(ROOT/'models/kokoro-v1.0.onnx',ROOT/'models/voices-v1.0.bin')

if not TOKEN_FILE.exists():
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(24) + '\n')
os.chmod(TOKEN_FILE, 0o600)
TOKEN = TOKEN_FILE.read_text().strip()

VOICE_INFO = {
    'af_heart': ('Heart', 'Warm, friendly American woman'), 'af_bella': ('Bella', 'Bright, expressive American woman'),
    'af_nicole': ('Nicole', 'Soft, close, ASMR-ish American woman'), 'af_sarah': ('Sarah', 'Clear, even American woman'),
    'af_sky': ('Sky', 'Light, airy American woman'), 'af_nova': ('Nova', 'Crisp, modern American woman'),
    'af_jessica': ('Jessica', 'Casual, chatty American woman'), 'af_river': ('River', 'Calm, steady American woman'),
    'af_alloy': ('Alloy', 'Neutral, smooth American woman'), 'af_aoede': ('Aoede', 'Gentle, lyrical American woman'),
    'af_kore': ('Kore', 'Confident American woman'),
    'am_adam': ('Adam', 'Relaxed American man'), 'am_michael': ('Michael', 'Warm, solid American man'),
    'am_onyx': ('Onyx', 'Deep, dark American man'), 'am_echo': ('Echo', 'Clear, mid-range American man'),
    'am_eric': ('Eric', 'Straightforward American man'), 'am_fenrir': ('Fenrir', 'Gravelly, bold American man'),
    'am_liam': ('Liam', 'Young, easygoing American man'), 'am_puck': ('Puck', 'Playful, cheeky American man'),
    'am_santa': ('Santa', 'Jolly, rounded American man'),
    'bf_emma': ('Emma', 'Polished British woman'), 'bf_alice': ('Alice', 'Bright British woman'),
    'bf_isabella': ('Isabella', 'Elegant British woman'), 'bf_lily': ('Lily', 'Soft British woman'),
    'bm_george': ('George', 'Classic, deep British man'), 'bm_daniel': ('Daniel', 'Calm British man'),
    'bm_fable': ('Fable', 'Storyteller British man'), 'bm_lewis': ('Lewis', 'Rich, low British man'),
}
LANG = {'e':'Spanish','f':'French','h':'Hindi','i':'Italian','j':'Japanese','p':'Portuguese','z':'Chinese'}
def voice_catalog():
    out = []
    for v in VOICE_NAMES:
        if v in VOICE_INFO:
            name, desc = VOICE_INFO[v]; group = 'English'
        else:
            name = v.split('_', 1)[1].replace('_', ' ').title()
            lang = LANG.get(v[0], 'Other')
            desc = f"{lang} {'woman' if v[1]=='f' else 'man'} (reads English with an accent)"; group = 'More accents'
        out.append({'id': v, 'name': name, 'desc': desc, 'group': group})
    return out

DEFAULT_SETTINGS = {'voice': 'af_heart', 'blend': {'on': False, 'voice': 'bf_emma', 'mix': .3},
                    'overlay': {'enabled': False, 'voice': 'am_onyx', 'gain': .5, 'pitch': -12, 'delay_ms': 20},
                    'pitch': 0, 'speed': 1, 'formant': 1, 'seed': 42}

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default

def write_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)

EXAMPLES = [
    {'name':'A little mischief', 'mood':'Warm · musical · playful', 'text':(ROOT/'demo.txt').read_text()},
    {'name':'Copper radio', 'mood':'Low · cinematic · glitchy', 'text':'<speed 0.9><formant 0.93>Good evening, my king. You are tuned to Copper Radio.</formant></speed> [breath out 0.5s] <contour 0,-2,-4>Somewhere between a dream and a broken satellite.</contour> [glitch ring 0.45s] [whistle arch 1s] Signal restored.'},
    {'name':'Pocket songbird', 'mood':'Airy · bright · melodic', 'text':'Hello, sunshine. [breath in 0.35s] <pitch +2><contour 0,2,-1>Let us take the scenic route.</contour></pitch> [whistle C6,E6,G6,B6,G6,E6,C6 2s] <speed 0.9>There. A tiny adventure.</speed>'},
    {'name':'Beautiful malfunction', 'mood':'Granular · strange · charming', 'text':'Everything is perfectly normal. [glitch bitcrush 0.3s] <pitch -3>Absolutely normal.</pitch> [glitch stutter 0.35s] [glitch slip 0.3s] [glitch bleep 0.4s] [sweep down 0.6s] [breath out 0.4s] Mostly.'},
]

class Blend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    voice: str
    weight: float = Field(ge=0,le=1)

class Overlay(BaseModel):
    model_config = ConfigDict(extra='ignore')
    voice: str
    gain: float = Field(default=.5, ge=0, le=1)
    pitch: float = Field(default=0, ge=-12, le=12)
    delay_ms: float = Field(default=0, ge=0, le=500)
    enabled: bool = True

class RenderRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=6000)
    voice: str = 'af_heart'
    blends: list[Blend] = Field(default_factory=list,max_length=3)
    pitch: float = Field(default=0,ge=-24,le=24)
    speed: float = Field(default=1,ge=.5,le=2)
    formant: float = Field(default=1,ge=.7,le=1.4)
    seed: int = Field(default=42,ge=0,le=2**32-1)
    overlay: Optional[Overlay] = None
    title: str = Field(default='', max_length=80)
    source: str = Field(default='studio', max_length=20)

class OracleRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    prompt: str = Field(min_length=1, max_length=1000)
    settings: Optional[dict] = None
    source: str = 'chat'

def is_public(request):
    """Requests through the Cloudflare tunnel carry Cf-Connecting-IP; LAN/local requests never do."""
    return 'cf-connecting-ip' in request.headers or 'cf-ray' in request.headers

VID_COOKIE = 'oracle_vid'
VID_RE = re.compile(r'[A-Za-z0-9_-]{16,64}')

def who(request):
    """'lan' for Buck's LAN; for public visitors an opaque per-browser id (random first-party cookie)."""
    if not is_public(request):
        return 'lan'
    vid = getattr(request.state, 'vid', None) or request.cookies.get(VID_COOKIE) or ''
    return 'pub:' + hashlib.sha256(vid.encode()).hexdigest()[:16]

def rate_key(request):
    ip = request.headers.get('cf-connecting-ip') or (request.client.host if request.client else '?')
    try:
        a = ipaddress.ip_address(ip)
        if a.version == 6:  # rotating IPv6 addresses share a /64
            ip = str(ipaddress.ip_network(f'{ip}/64', strict=False))
    except ValueError:
        pass
    return 'ip:' + hashlib.sha256(ip.encode()).hexdigest()[:16]

PUBLIC_HIDDEN = ('/api/docs', '/openapi.json', '/docs', '/redoc', '/api/docs/oauth2-redirect')
ASSET_V = {}
def asset_version(name):
    p = ROOT/'web'/name
    m = p.stat().st_mtime_ns
    if ASSET_V.get(name, (None,))[0] != m:
        ASSET_V[name] = (m, hashlib.sha256(p.read_bytes()).hexdigest()[:10])
    return ASSET_V[name][1]

def rate_ok(key, per=PUBLIC_PER_MIN, total_cap=PUBLIC_TOTAL_PER_MIN, bucket=''):
    now = time.monotonic()
    with RATE_LOCK:
        total = RATE.setdefault(bucket+'*', deque())
        mine = RATE.setdefault(bucket+key, deque())
        for q in (total, mine):
            while q and now - q[0] > 60: q.popleft()
        if len(mine) >= per or len(total) >= total_cap:
            return False
        mine.append(now); total.append(now)
        if len(RATE) > 5000:
            for k in [k for k, q in RATE.items() if k != '*' and not q][:2500]: RATE.pop(k, None)
        return True

def token_ok(request):
    supplied = request.headers.get('x-oracle-token') or ''
    return bool(supplied) and hmac.compare_digest(supplied.encode(), TOKEN.encode())

@APP.middleware('http')
async def same_origin(request: Request, call_next):
    origin=request.headers.get('origin')
    public = is_public(request)
    trusted = token_ok(request) and not public
    if origin and not trusted:
        o = urlsplit(origin)
        # Same-origin = the page's own host (LAN IP, localhost or the tunnel hostname). Scheme may differ
        # behind the tunnel (browser https, cloudflared -> http), so compare host:port only.
        if o.scheme not in ('http','https') or o.netloc.lower() != (request.headers.get('host') or '').lower():
            return JSONResponse({'detail':'Cross-origin requests are not enabled.'},status_code=403)
    new_vid = None
    if public:
        path, method = request.url.path, request.method
        if path in PUBLIC_HIDDEN:
            return JSONResponse({'detail':'Not Found'},status_code=404)
        vid = request.cookies.get(VID_COOKIE) or ''
        if not VID_RE.fullmatch(vid):
            new_vid = secrets.token_urlsafe(18)
        request.state.vid = new_vid or vid
        if path == '/api/oracle/text' or (method == 'DELETE') or (method == 'PUT' and path == '/api/settings'):
            return JSONResponse({'detail':'Not available from the public link.'},status_code=403)
        if method == 'POST' and path in RATE_PATHS and not rate_ok(rate_key(request)):
            return JSONResponse({'detail':'Slow down a little: at most 6 renders a minute. Try again shortly.'},status_code=429)
        if method == 'POST' and path == '/api/talk' and not rate_ok(rate_key(request), TALK_PER_MIN, TALK_TOTAL_PER_MIN, 'talk:'):
            return JSONResponse({'detail':'Hera needs a breather. Try again in a minute.'},status_code=429)
    if request.url.path == '/api/oracle/text' and not trusted and not origin:
        return JSONResponse({'detail':'Missing or invalid X-Oracle-Token header.'},status_code=401)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    if request.url.path in ('/','/oracle','/oracle/'):
        response.headers['Cache-Control']='no-store'
    elif request.url.path in ('/studio.js','/studio.css'):
        response.headers['Cache-Control']='no-cache' if 'v' not in request.query_params else 'public, max-age=31536000, immutable'
    if new_vid:
        response.set_cookie(VID_COOKIE, new_vid, max_age=31536000, httponly=True, secure=True, samesite='lax', path='/')
    return response

@APP.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    if is_public(request):
        fields = sorted({str(e.get('loc', ['?'])[-1]) for e in exc.errors()})
        return JSONResponse({'detail': f"Invalid request ({', '.join(fields)})."}, status_code=422)
    return JSONResponse({'detail': exc.errors()}, status_code=422)

@APP.get('/')
@APP.get('/oracle')
@APP.get('/oracle/')
def home():
    html = (ROOT/'web/index.html').read_text()
    html = html.replace('href="/studio.css"', f'href="/studio.css?v={asset_version("studio.css")}"')
    html = html.replace('src="/studio.js"', f'src="/studio.js?v={asset_version("studio.js")}"')
    return HTMLResponse(html)

@APP.get('/studio.js')
def javascript():
    return FileResponse(ROOT/'web/studio.js',media_type='text/javascript')

@APP.get('/studio.css')
def stylesheet():
    return FileResponse(ROOT/'web/studio.css',media_type='text/css')

@APP.get('/api/config')
def config(request: Request):
    return {'voices':VOICE_NAMES,'voice_catalog':voice_catalog(),'examples':EXAMPLES,'sample_rate':SR,'title':'Oracle',
            'settings':{**DEFAULT_SETTINGS, **read_json(SETTINGS_FILE, {})},'public':is_public(request)}

@APP.get('/api/health')
def health(request: Request):
    if is_public(request):
        return {'status':'ok'}
    return {'status':'ok','model':'Kokoro-82M v1.0','device':'CPU','loaded':ENGINE.engine is not None}

@APP.get('/api/settings')
def get_settings():
    return {**DEFAULT_SETTINGS, **read_json(SETTINGS_FILE, {})}

@APP.put('/api/settings')
def put_settings(body: dict):
    clean = {k: body[k] for k in DEFAULT_SETTINGS if k in body}
    with FILE_LOCK:
        write_json(SETTINGS_FILE, {**DEFAULT_SETTINGS, **read_json(SETTINGS_FILE, {}), **clean})
    return get_settings()

def update(job_id,**values):
    with LOCK: JOBS[job_id].update(values)

def work(job_id, request, meta):
    try:
        update(job_id,status='rendering',progress=5,message='Warming up…')
        ENGINE.voice=request.voice
        if request.blends:
            active=[b for b in request.blends if b.weight>0]
            ENGINE.voice=','.join(f'{b.voice}:{b.weight}' for b in active)
        ov=request.overlay
        ENGINE.overlay=dict(voice=ov.voice,gain=ov.gain,pitch=ov.pitch,delay_ms=ov.delay_ms) if ov and ov.enabled and ov.gain>0 else None
        ENGINE.rng=np.random.default_rng(request.seed)
        def progress(done,total,kind):
            update(job_id,progress=round(5+80*done/total),message=f'Shaping {kind} · {done} of {total}')
        started=time.monotonic()
        audio,stats=ENGINE.render(request.text,Style(pitch=request.pitch,speed=request.speed,formant=request.formant),progress=progress,voices=VOICE_NAMES)
        wav=OUTPUT/f'{job_id}.wav'
        sf.write(wav,audio,SR,subtype='PCM_16')
        (OUTPUT/f'{job_id}.json').write_text(json.dumps(stats,indent=2)+'\n')
        update(job_id,progress=90,message='Encoding MP3…')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(wav),'-codec:a','libmp3lame','-b:a','192k',str(OUTPUT/f'{job_id}.mp3')],check=True,timeout=90,capture_output=True)
        waveform=[round(float(np.max(np.abs(a))),4) if len(a) else 0 for a in np.array_split(audio,420)]
        render_s=round(time.monotonic()-started,2)
        meta.update(duration=round(stats['duration'],2),render_seconds=render_s)
        (OUTPUT/f'{job_id}.meta.json').write_text(json.dumps(meta,indent=1))
        update(job_id,status='ready',progress=100,message='Your voice is ready.',duration=stats['duration'],peak=stats['peak'],rms=stats['rms'],events=stats['events'],waveform=waveform,wav=f'/audio/{job_id}.wav',mp3=f'/audio/{job_id}.mp3',sidecar=f'/audio/{job_id}.json',render_seconds=render_s,title=meta.get('title'))
    except Exception as e:
        message=str(e) if isinstance(e,ValueError) else f'Render failed ({type(e).__name__}). Check the server console.'
        if not isinstance(e,ValueError):
            import traceback; traceback.print_exc()
        update(job_id,status='error',message=message,progress=0)
    finally:
        SLOT.release()

def validate(request):
    if request.voice not in VOICE_NAMES or any(b.voice not in VOICE_NAMES for b in request.blends):
        raise HTTPException(400,'Choose a built-in Kokoro voice.')
    if request.overlay and request.overlay.enabled and request.overlay.voice not in VOICE_NAMES:
        raise HTTPException(400,'Choose a built-in Kokoro voice for the overlay.')
    if request.blends and sum(b.weight for b in request.blends)<=0:
        raise HTTPException(400,'At least one blend weight must be above zero.')
    try: parse(request.text,Style(pitch=request.pitch,speed=request.speed,formant=request.formant),VOICE_NAMES)
    except ValueError as e: raise HTTPException(400,str(e))

def start_job(request, wait_slot=0, owner='lan'):
    validate(request)
    if not SLOT.acquire(timeout=wait_slot) if wait_slot else not SLOT.acquire(blocking=False):
        raise HTTPException(429,'A render is in progress. Wait for it to finish.')
    job_id=str(uuid4())
    title=request.title or ' '.join(re.sub(r'<[^>]*>|\[[^\]]*\]',' ',request.text).split()[:6]) or 'Untitled'
    meta={'id':job_id,'title':title[:80],'text':request.text,'created':time.time(),'source':request.source,
          'settings':request.model_dump(exclude={'text','title','source'}),'who':owner}
    with LOCK:
        JOBS[job_id]={'id':job_id,'status':'queued','progress':1,'message':'Preparing your sound…','created':time.time()}
        if len(JOBS)>100:
            for old in list(JOBS)[:-100]: JOBS.pop(old,None)
    POOL.submit(work,job_id,request,meta)
    return {'id':job_id,'status_url':f'/api/jobs/{job_id}'}

@APP.post('/api/render',status_code=202)
def render(request: RenderRequest, http: Request):
    return start_job(request, owner=who(http))

@APP.get('/api/jobs/{job_id}')
def job(job_id: str):
    with LOCK:
        result=JOBS.get(job_id)
        if not result: raise HTTPException(404,'Unknown job; server restarts clear the job list.')
        return dict(result)

@APP.get('/api/clips')
def clips(request: Request, limit: int = 40):
    items=[]; me=who(request); limit=max(1,min(limit,200))
    for m in sorted(OUTPUT.glob('*.meta.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        if len(items)>=limit: break
        d=read_json(m,None)
        if d and d.get('who','lan')==me and (OUTPUT/f"{d['id']}.mp3").exists():
            items.append({k:d.get(k) for k in ('id','title','created','duration','source','text')} | {'mp3':f"/audio/{d['id']}.mp3",'wav':f"/audio/{d['id']}.wav"})
    return {'clips':items}

@APP.delete('/api/clips/{job_id}')
def delete_clip(job_id: str):
    try: UUID(job_id)
    except ValueError: raise HTTPException(404)
    removed=0
    for ext in ('wav','mp3','json','meta.json'):
        p=OUTPUT/f'{job_id}.{ext}'
        if p.exists(): p.unlink(); removed+=1
    if not removed: raise HTTPException(404,'No such clip')
    return {'deleted':job_id}

@APP.get('/audio/{job_id}.{extension}')
def audio(job_id: str,extension: str):
    try: UUID(job_id)
    except ValueError: raise HTTPException(404)
    if extension not in ('wav','mp3','json'): raise HTTPException(404)
    path=OUTPUT/f'{job_id}.{extension}'
    if not path.is_file(): raise HTTPException(404)
    media={'wav':'audio/wav','mp3':'audio/mpeg','json':'application/json'}[extension]
    return FileResponse(path,media_type=media,filename=f'oracle-{job_id[:8]}.{extension}',content_disposition_type='inline')

# ------------------------------------------------------------------ The Oracle
def settings_to_request(script, s, title, source):
    blends=[]
    b=s.get('blend') or {}
    if b.get('on') and b.get('voice') in VOICE_NAMES:
        mix=min(1,max(0,float(b.get('mix',.3))))
        blends=[{'voice':s['voice'],'weight':round(1-mix,3)},{'voice':b['voice'],'weight':round(mix,3)}]
        if sum(x['weight'] for x in blends)<=0: blends=[]
    ov=s.get('overlay') or {}
    overlay=ov if ov.get('enabled') and ov.get('voice') in VOICE_NAMES else None
    return RenderRequest(text=script,voice=s.get('voice','af_heart'),blends=blends,pitch=float(s.get('pitch',0)),speed=float(s.get('speed',1)),
                         formant=float(s.get('formant',1)),seed=int(s.get('seed',42)),overlay=overlay,title=title[:80],source=source)

def oracle_turn(prompt, ui_settings, source, wait_slot=0, owner='lan'):
    defaults={**DEFAULT_SETTINGS, **read_json(SETTINGS_FILE, {}), **(ui_settings or {})}
    with FILE_LOCK:
        history=[m for m in read_json(HISTORY_FILE, []) if m.get('who','lan')==owner]
    if not WAITERS.acquire(blocking=False):
        raise HTTPException(429,'The Oracle is busy with a few requests already. Try again in a moment.')
    try:
        return _oracle_turn(prompt, defaults, history, source, wait_slot, owner)
    finally:
        WAITERS.release()

def _oracle_turn(prompt, defaults, history, source, wait_slot, owner):
    if not ORACLE_LOCK.acquire(timeout=120):
        raise HTTPException(429,'The Oracle is still thinking about another request.')
    try:
        try:
            result=oracle.ask(prompt, defaults, history, VOICE_NAMES)
        except Exception as e:
            raise HTTPException(502,'The Oracle is resting right now. Try again in a moment.')
    finally:
        ORACLE_LOCK.release()
    settings={**defaults, **result['settings']}
    job=start_job(settings_to_request(result['script'],settings,result['title'],source), wait_slot=wait_slot, owner=owner)
    now=time.time()
    user_msg={'role':'user','text':prompt.strip(),'time':now,'source':source,'who':owner}
    reply={'role':'oracle','title':result['title'],'script':result['script'],'settings':settings,'job_id':job['id'],
           'mp3':f"/audio/{job['id']}.mp3",'wav':f"/audio/{job['id']}.wav",'time':now,'model':result['model'],
           'llm_seconds':result['llm_seconds'],'repaired':result['repaired'],'source':source,'who':owner}
    with FILE_LOCK:
        history=read_json(HISTORY_FILE, [])
        history+= [user_msg, reply]
        write_json(HISTORY_FILE, history[-400:])
    return reply, job

@APP.post('/api/oracle',status_code=202)
def oracle_ask(body: OracleRequest, http: Request):
    reply, job = oracle_turn(body.prompt, body.settings, body.source if body.source in ('chat','chip','mic') else 'chat', wait_slot=90, owner=who(http))
    return {'reply':{k:v for k,v in reply.items() if k not in ('model','who')},'job':job}

@APP.get('/api/oracle/history')
def oracle_history(request: Request):
    me=who(request)
    with FILE_LOCK:
        return {'messages':[{k:v for k,v in m.items() if k not in ('who','model')} for m in read_json(HISTORY_FILE, []) if m.get('who','lan')==me][-60:]}

@APP.delete('/api/oracle/history')
def oracle_clear():
    with FILE_LOCK:
        write_json(HISTORY_FILE, [m for m in read_json(HISTORY_FILE, []) if m.get('who','lan')!='lan'])
    return {'cleared':True}

@APP.post('/api/oracle/text')
async def oracle_text(request: Request, wait: int = 0):
    raw=(await request.body()).decode('utf-8','replace').strip()
    if raw.startswith('{'):
        try: raw=str(json.loads(raw).get('text',''))
        except ValueError: pass
    if not raw or len(raw)>1000:
        raise HTTPException(400,'Send 1..1000 characters of plain text.')
    from starlette.concurrency import run_in_threadpool
    reply, job = await run_in_threadpool(oracle_turn, raw, None, 'text', 120 if wait else 0)
    base=str(request.base_url).rstrip('/')
    out={'title':reply['title'],'script':reply['script'],'job_id':job['id'],'status_url':base+job['status_url'],
         'mp3':base+reply['mp3'],'wav':base+reply['wav'],'status':'queued','llm_seconds':reply['llm_seconds']}
    if wait:
        import asyncio
        for _ in range(600):
            state=JOBS.get(job['id'],{})
            if state.get('status') in ('ready','error'): break
            await asyncio.sleep(.5)
        out['status']=state.get('status','unknown')
        if state.get('status')=='error': out['error']=state.get('message')
        out['duration']=state.get('duration'); out['render_seconds']=state.get('render_seconds')
    return out

# ------------------------------------------------------------------ Talk mode (Hera)
HERA = {'voice': 'af_heart:0.55,bf_isabella:0.45', 'speed': 1.0, 'pitch': 0, 'formant': 0.97,
        'overlay': {'voice': 'bf_isabella', 'gain': .38, 'pitch': -12, 'delay_ms': 18}}
HERA_WRAP = ('<wobble rate=5 depth=0.35>', '</wobble>')
HERA_CUES = ('[glitch ring 0.12s] ', '[glitch slip 0.15s] ', '')

def talk_history(owner):
    with FILE_LOCK:
        return [m for m in read_json(TALK_FILE, []) if m.get('who','lan')==owner]

def talk_save(owner, heard, reply):
    now=time.time()
    with FILE_LOCK:
        h=read_json(TALK_FILE, [])
        h+=[{'role':'you','text':heard,'time':now,'who':owner},{'role':'hera','text':reply,'time':now,'who':owner}]
        write_json(TALK_FILE, h[-800:])

def talk_cleanup():
    cutoff=time.time()-3*3600
    for f in TALK_DIR.glob('*.mp3'):
        try:
            if f.stat().st_mtime<cutoff: f.unlink()
        except OSError: pass
    with LOCK:
        for k in [k for k,v in TALKS.items() if v['created']<cutoff]: TALKS.pop(k,None)

def talk_update(tid, **kw):
    with LOCK: TALKS[tid].update(kw)

def render_sentence(text, index, seed):
    script=(HERA_CUES[index % len(HERA_CUES)] if index else '')+HERA_WRAP[0]+text+HERA_WRAP[1]
    if not SLOT.acquire(timeout=90):
        raise RuntimeError('busy')
    try:
        ENGINE.voice=HERA['voice']; ENGINE.overlay=dict(HERA['overlay']); ENGINE.rng=np.random.default_rng(seed+index)
        try:
            audio,stats=ENGINE.render(script,Style(pitch=HERA['pitch'],speed=HERA['speed'],formant=HERA['formant']),voices=VOICE_NAMES)
        except ValueError:
            audio,stats=ENGINE.render(HERA_WRAP[0]+text+HERA_WRAP[1],Style(pitch=HERA['pitch'],speed=HERA['speed'],formant=HERA['formant']),voices=VOICE_NAMES)
    finally:
        SLOT.release()
    sid=str(uuid4()); wav=TALK_DIR/f'{sid}.wav'
    sf.write(wav,audio,SR,subtype='PCM_16')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(wav),'-codec:a','libmp3lame','-b:a','112k',str(TALK_DIR/f'{sid}.mp3')],check=True,timeout=30,capture_output=True)
    wav.unlink(missing_ok=True)
    return {'i':index,'text':text,'mp3':f'/talk-audio/{sid}.mp3','duration':round(stats['duration'],2)}

def talk_turn(tid, raw, typed, owner):
    t0=time.monotonic(); marks={}
    try:
        if typed is None:
            talk_update(tid,status='listening',message='Listening…')
            audio,secs=talk.decode(raw)
            heard=talk.transcribe(audio)
            marks['stt_s']=round(time.monotonic()-t0,2); marks['clip_s']=round(secs,1)
            if not heard:
                talk_update(tid,status='error',message="I didn't catch that. Try again a little closer to the mic.",**marks); return
        else:
            heard=typed
        talk_update(tid,status='thinking',heard=heard,message='Hera is thinking…',**marks)
        history=talk_history(owner)
        q=queue.Queue(); seed=int.from_bytes(os.urandom(2),'big')
        def renderer():
            i=0
            while True:
                s=q.get()
                if s is None: return
                try:
                    seg=render_sentence(s,i,seed)
                except Exception:
                    import traceback; traceback.print_exc(); seg=None
                if seg:
                    with LOCK:
                        t=TALKS[tid]; t['segments'].append(seg); t['status']='speaking'; t['message']='Hera is speaking…'
                        t.setdefault('first_audio_s',round(time.monotonic()-t0,2))
                i+=1
        rt=threading.Thread(target=renderer,daemon=True); rt.start()
        def on_sentence(s):
            with LOCK:
                TALKS[tid]['reply']=((TALKS[tid].get('reply') or '')+' '+s).strip()
                TALKS[tid].setdefault('first_text_s',round(time.monotonic()-t0,2))
            q.put(s)
        if not ORACLE_LOCK.acquire(timeout=60):
            q.put(None); talk_update(tid,status='error',message='Hera is busy with someone else. Try again in a moment.'); return
        try:
            tl=time.monotonic()
            try:
                reply=talk.stream_reply(heard,history,on_sentence)
            except Exception:
                import traceback; traceback.print_exc(); reply=''
            marks['llm_s']=round(time.monotonic()-tl,2)
        finally:
            ORACLE_LOCK.release()
            q.put(None)
        rt.join(timeout=180)
        if not reply:
            talk_update(tid,status='error',message='Hera is resting right now. Try again in a moment.',**marks); return
        talk_save(owner,heard,reply)
        with LOCK:
            t=TALKS[tid]; ok=bool(t['segments'])
            t.update(status='done' if ok else 'error',message='' if ok else 'Hera lost her voice for a moment. Try again.',total_s=round(time.monotonic()-t0,2),**marks)
    except ValueError as e:
        talk_update(tid,status='error',message=str(e))
    except Exception:
        import traceback; traceback.print_exc()
        talk_update(tid,status='error',message='Something went wrong. Try again.')
    finally:
        WAITERS.release()

PUBLIC_TALK_KEYS=('id','status','message','heard','reply','segments','first_text_s','first_audio_s','total_s','stt_s','llm_s','clip_s')

@APP.post('/api/talk',status_code=202)
async def talk_start(request: Request):
    ctype=(request.headers.get('content-type') or '').split(';')[0].strip().lower()
    clen=request.headers.get('content-length')
    if clen and clen.isdigit() and int(clen)>TALK_MAX_BYTES:
        raise HTTPException(413,'That recording is too long. Keep it under 20 seconds.')
    raw=b''
    async for chunk in request.stream():
        raw+=chunk
        if len(raw)>TALK_MAX_BYTES: raise HTTPException(413,'That recording is too long. Keep it under 20 seconds.')
    typed=None
    if ctype=='application/json':
        try: typed=str(json.loads(raw or b'{}').get('text','')).strip()
        except (ValueError,AttributeError): raise HTTPException(400,'Send {"text": "..."} or an audio recording.')
        typed=re.sub(r'[\x00-\x1f\x7f]',' ',typed)[:500].strip()
        if not typed: raise HTTPException(400,'Say or type something first.')
    elif not ctype.startswith(('audio/','video/','application/octet-stream')) or len(raw)<200:
        raise HTTPException(400,'Send an audio recording.')
    if not WAITERS.acquire(blocking=False):
        raise HTTPException(429,'Hera is talking with a few people already. Try again in a moment.')
    talk_cleanup()
    tid=str(uuid4()); owner=who(request)
    with LOCK:
        TALKS[tid]={'id':tid,'status':'queued','message':'Uploading…','segments':[],'created':time.time(),'who':owner}
    try:
        TALK_POOL.submit(talk_turn,tid,raw,typed,owner)
    except Exception:
        WAITERS.release(); raise
    return {'id':tid,'status_url':f'/api/talk/{tid}'}

@APP.get('/api/talk/history')
def talk_hist(request: Request):
    return {'messages':[{k:m[k] for k in ('role','text','time')} for m in talk_history(who(request))][-40:]}

@APP.post('/api/talk/clear')
def talk_clear(request: Request):
    me=who(request)
    with FILE_LOCK:
        write_json(TALK_FILE,[m for m in read_json(TALK_FILE, []) if m.get('who','lan')!=me])
    return {'cleared':True}

@APP.get('/api/talk/{tid}')
def talk_status(tid: str, request: Request):
    with LOCK:
        t=TALKS.get(tid)
        if not t or t['who']!=who(request): raise HTTPException(404,'Unknown turn.')
        return {k:(list(t[k]) if k=='segments' else t[k]) for k in PUBLIC_TALK_KEYS if k in t}

@APP.get('/talk-audio/{sid}.mp3')
def talk_audio(sid: str):
    try: UUID(sid)
    except ValueError: raise HTTPException(404)
    path=TALK_DIR/f'{sid}.mp3'
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path,media_type='audio/mpeg')

talk.preload()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',default=7860,type=int)
    a=p.parse_args()
    import uvicorn
    uvicorn.run(APP,host=a.host,port=a.port,server_header=False)
