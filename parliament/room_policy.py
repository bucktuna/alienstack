"""Deterministic room moderation and persistent topic-vote state (stdlib only)."""
import contextlib, fcntl, json, os, re, time, unicodedata, hashlib, secrets
from pathlib import Path
ROOM = Path(__file__).resolve().parent / 'guest-room'
PROFANITY = ('fuck','motherfucker','shit','bullshit','bitch','asshole','bastard','cunt','dickhead','cock','pussy','piss','crap','damn','hell','ass','dick','whore','slut','wanker','bollocks','prick','twat','arse','arsehole','shitty','shite','dumbass','jackass','wtf','stfu')
HATE = ('nigger','nigga','faggot','kike','chink','spic','retard','retarded','kill yourself','gas the jews','heil hitler','white supremacy')
RUDE = ('idiot','moron','stupid','loser','shut up','shut your mouth','worthless','pathetic','you suck','nobody likes you','go away','kill you','hurt you','dox you')
def normalized_spans(text):
    out=[]; spans=[]
    table=str.maketrans({'1':'i','3':'e','0':'o','@':'a','$':'s','7':'t'})
    for i,char in enumerate(text):
        chars=unicodedata.normalize('NFKC',char).casefold()
        for c in chars:
            if unicodedata.category(c)=='Cf': continue
            # An exclamation inside a word may stand for i; terminal ! is punctuation.
            if c=='!' and i>0 and i+1<len(text) and text[i-1].isalpha() and text[i+1].isalpha(): c='i'
            out.append(c.translate(table));spans.append((i,i+1))
    return ''.join(out),spans

def normalize(text): return normalized_spans(text)[0]
def pattern(word):
    return re.compile(r'(?<![a-z0-9])'+r'[\W_]*'.join('['+re.escape(c)+r'*]+' if c!=' ' else r'\s+' for c in word)+r'(?:s|es|ed|ing|er|ers|y)?(?![a-z0-9])')
PATTERNS = [(kind, [pattern(w) for w in words]) for kind,words in [('hate/slur',HATE),('rudeness',RUDE),('profanity',PROFANITY)]]
def hits(normalized,patterns):
    for regex in patterns:
        for m in regex.finditer(normalized):
            # Fully censored text is already clean, not another masked word.
            if re.search('[a-z0-9]',m[0]): yield m

def classify(text):
    text=normalize(text)
    for kind,patterns in PATTERNS:
        if next(hits(text,patterns),None): return kind
    return None

def mask_profanity(text):
    normalized,spans=normalized_spans(text)
    covered=set()
    patterns=next(ps for kind,ps in PATTERNS if kind=='profanity')
    for m in hits(normalized,patterns):
        for i in range(spans[m.start()][0],spans[m.end()-1][1]): covered.add(i)
    return ''.join('*' if i in covered else c for i,c in enumerate(text)),bool(covered)

@contextlib.contextmanager
def state_file(name):
    ROOM.mkdir(parents=True,exist_ok=True)
    lock = os.open(str(ROOM/(name+'.lock')),os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(lock,'a+') as fp:
        fcntl.flock(fp,fcntl.LOCK_EX)
        path = ROOM/(name+'.json')
        if path.exists(): data=json.loads(path.read_text()) # fail closed on corrupt state
        else: data={}
        yield data
        tmp=path.with_suffix('.json.tmp')
        fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as out:
            json.dump(data,out,indent=2); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,path); os.chmod(path,0o600)
def blocked(key):
    with state_file('bans') as db: return key in db.get('bans',{})
def moderate(key,name,text,house=False):
    kind=classify(text)
    if house: return {'allowed':kind not in ('hate/slur','rudeness'),'banned':False,'reason':kind}
    now=time.time()
    with state_file('bans') as db:
        bans=db.setdefault('bans',{}); strikes=db.setdefault('strikes',{})
        if key in bans: return {'allowed':False,'banned':True,'reason':'already banned'}
        if kind in (None,'profanity'): return {'allowed':True,'banned':False,'masked':kind=='profanity'}
        recent=[s for s in strikes.get(key,[]) if now-s['time']<86400]
        if kind=='rudeness':
            recent.append({'time':now,'name':name,'reason':kind,'text':text[:160]}); strikes[key]=recent
        ban=kind!='rudeness' or len(recent)>=3
        if ban:
            bans[key]={'identity':key,'ip':key[3:] if key.startswith('ip:') else None,'name':name,'reason':kind if kind!='rudeness' else '3 rude comments within 24 hours','time':now,'text':text[:160]}
        return {'allowed':False,'banned':ban,'new_ban':ban,'reason':kind,'strikes':len(recent)}
def topic_request(text):
    m=re.match(r'^/topic(?:\s+(.*))?\s*$',text,re.I|re.S)
    if m: return (m.group(1) or '').strip()[:300]
    direct=re.fullmatch(r'(?:please\s+)?(?:let[\x27\u2019]s\s+)?talk about\s+(.+?)[.!]?\s*',text,re.I|re.S)
    if direct:return direct.group(1).strip()[:300]
    m=re.match(r'^(?:propose changing the subject|change the subject)(?:\s*[:\-]\s*|\s+to\s+)?(.*?)\s*$',text,re.I|re.S)
    return m.group(1).strip()[:300] if m else None
def add_user(name):
    name=name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}",name): raise ValueError("Use 1-40 simple letters, digits, spaces, dots or hyphens.")
    uid=name.casefold()
    with state_file('members') as db:
        if uid in db: raise ValueError("Member already exists; delete and recreate to reset.")
        passcode=secrets.token_urlsafe(18); salt=secrets.token_hex(16)
        digest=hashlib.pbkdf2_hmac('sha256',passcode.encode(),bytes.fromhex(salt),310000).hex()
        db[uid]={'name':name,'salt':salt,'hash':digest,'created':time.time()}
    return passcode

def login(name,passcode):
    uid=name.strip().casefold()
    if blocked('member:'+uid): return None
    with state_file('members') as db: member=db.get(uid)
    if not member: return None
    digest=hashlib.pbkdf2_hmac('sha256',passcode.encode(),bytes.fromhex(member['salt']),310000).hex()
    if not secrets.compare_digest(digest,member['hash']): return None
    token=secrets.token_urlsafe(32); key=hashlib.sha256(token.encode()).hexdigest()
    with state_file('sessions') as db:
        now=time.time()
        for k in list(db):
            if db[k]['expires']<now: del db[k]
        db[key]={'member':uid,'expires':now+7*86400}
    return token

def session(token):
    if not token or len(token)>200: return None
    key=hashlib.sha256(token.encode()).hexdigest()
    with state_file('sessions') as db: s=db.get(key)
    if not s or s['expires']<time.time() or blocked('member:'+s['member']): return None
    with state_file('members') as db: m=db.get(s['member'])
    return {'id':s['member'],'name':m['name']} if m else None

def ban_member(uid,ipkey):
    with state_file('bans') as db:
        original=db.get('bans',{}).get(ipkey)
        if original:
            original['member']=uid
            db['bans']['member:'+uid]={**original,'identity':'member:'+uid}

def canonical_topic(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split()).rstrip(' .!?')

def current_topic():
    with state_file('topic') as db:
        if db.get('current_topic'):return db['current_topic']
    path=ROOM/'transcript.jsonl'
    if path.exists():
        for line in reversed(path.read_text().splitlines()):
            try:m=json.loads(line)
            except ValueError:continue
            if m.get('topic_start') and m.get('text','').startswith('New topic: '):return m['text'][11:].strip()
    return None

def current_topic_info():
    topic=current_topic()
    with state_file('topic') as db:
        start_id=db.get('topic_start_id') if db.get('current_topic')==topic else None
        context_start_id=db.get('context_start_id') if db.get('current_topic')==topic else None
    if start_id is None:
        path=ROOM/'transcript.jsonl'
        if path.exists():
            for line in reversed(path.read_text().splitlines()):
                try:m=json.loads(line)
                except ValueError:continue
                if m.get('topic_start') and m.get('text','').startswith('New topic: '):
                    if not topic or canonical_topic(m['text'][11:])==canonical_topic(topic):start_id=m['id']
                    break
    return {'topic':topic,'start_id':start_id,'context_start_id':max(start_id or 0,context_start_id or start_id or 0) or None}

def mark_topic_start(topic,message_id):
    with state_file('topic') as db:db.update(current_topic=topic,topic_start_id=message_id,context_start_id=message_id)


def commit_topic(topic):
    with state_file('topic') as db:db.update(current_topic=topic,topic_start_id=None,context_start_id=None)

def owner_member(uid):
    if not uid:return False
    with state_file('members') as db:return bool(db.get(uid,{}).get('owner'))


def open_vote(name,suggestion,kind='subject',member=None,owner=False):
    now=time.time();current=current_topic();exempt=owner or owner_member(member)
    with state_file('topic') as db:
        current=db.get('current_topic') or current
        if kind=='subject' and suggestion and current and canonical_topic(suggestion)==canonical_topic(current):return None,'Already the current topic: '+current+'. No new vote is needed.'
        with state_file('checkin') as check:
            if check.get('running'): return None,'A check-in is in progress; please wait.'
        if db.get('pending'): return None,'A proposal vote is already in progress.'
        remaining=max(0,int(600-(now-db.get('last_called',0))+0.999))
        if remaining and not exempt:return None,f'Proposal cooldown: {remaining//60}m {remaining%60:02d}s remaining ({remaining} seconds). Please try again then.'
        uid=member or 'owner'
        v={'id':str(time.time_ns()),'proposer':name,'suggestion':suggestion,'kind':kind,'time':now,
           'deadline':now if owner else now+60,'owner':owner,'previous_topic':current,'votes':{uid:{'choice':'YES','name':name}}}
        db['pending']=v; db['last_called']=now
        return v,None

def current_vote():
    with state_file('topic') as db: return db.get('pending')

def human_vote(uid,name,choice):
    if choice not in ('YES','NO'): return 'Vote must be YES or NO.'
    with state_file('topic') as db:
        v=db.get('pending')
        if not v or time.time()>=v['deadline']: return 'The vote window is closed.'
        if uid in v['votes']: return 'You already voted on this proposal.'
        v['votes'][uid]={'choice':choice,'name':name}
    return None

def tally(votes):
    yes=sum(v['choice']=='YES' for v in votes.values()); no=sum(v['choice']=='NO' for v in votes.values())
    tie=yes==no; passed=secrets.choice((True,False)) if tie else yes>no
    return yes,no,passed,tie

def resolve_vote(vid):
    with state_file('topic') as db:
        v=db.get('pending')
        if not v or v['id']!=vid or time.time()<v['deadline']: return None
        if 'result' not in v:
            yes,no,passed,tie=tally(v['votes']); v['result']={'yes':yes,'no':no,'passed':passed,'tie':tie}
        return v

def close_vote(vid):
    with state_file('topic') as db:
        if db.get('pending',{}).get('id')==vid: db['pending']=None

def vote_status(member=None):
    exempt=owner_member(member['id']) if member else False
    with state_file('topic') as db:
        v=db.get('pending'); now=time.time()
        result={'in_progress':bool(v),'cooldown_seconds':0 if exempt else max(0,int(600-(now-db.get('last_called',0)))+1),'owner':exempt,'member':member['name'] if member else None}
        if v and member:
            result['proposal']={'kind':v['kind'],'topic':v['suggestion'],'proposer':v['proposer'],'seconds':max(0,int(v['deadline']-now)+1),'voted':member['id'] in v['votes']}
        return result

def update_vote(vid,**changes):
    with state_file('topic') as db:
        v=db.get('pending')
        if v and v['id']==vid:
            v.update(changes); return v
    return None


def message_epoch(m):
    if isinstance(m.get('epoch'),(float,int)): return float(m['epoch'])
    try: return time.mktime(time.strptime(m.get('ts',''),'%Y-%m-%d %H:%M:%S %Z'))
    except (ValueError,OverflowError): return None

def active_overlap(start,end,messages):
    windows=[]
    for m in messages:
        t=message_epoch(m)
        if t is not None and start<t+300 and end>t: windows.append((max(start,t),min(end,t+300)))
    total=0;stop=start
    for a,b in sorted(windows):
        if b>stop: total+=b-max(a,stop);stop=b
    return max(0,total)

def checkin_tick(messages,minutes,now=None):
    now=time.time() if now is None else now;minutes=max(0,float(minutes))
    with state_file('checkin') as db:
        previous=db.get('last_tick',now)
        db['last_tick']=now;db['minutes']=minutes
        db['active_now']=any(t is not None and t<=now<t+300 for t in (message_epoch(m) for m in messages))
        db['active_seconds']=0 if minutes==0 else db.get('active_seconds',0)+active_overlap(previous,now,messages)
        return bool(db.get('requested') or (minutes>0 and db.get('active_now') and db['active_seconds']>=minutes*60))

def request_checkin():
    with state_file('checkin') as db:
        if db.get('running') or db.get('requested'):return False
        db['requested']=True;return True

def checkin_pending():
    with state_file('checkin') as db:return bool(db.get('requested') or db.get('running'))

def begin_checkin():
    # Same lock order as proposal creation: voting/closings and check-ins cannot overlap.
    with state_file('topic') as topic:
        if topic.get('pending'):return None
        with state_file('checkin') as db:
            if db.get('running'): return db['running']
            minutes=db.get('minutes',5)
            if not (db.get('requested') or (minutes>0 and db.get('active_now') and db.get('active_seconds',0)>=minutes*60)):return None
            running={'id':str(time.time_ns()),'done':[],'since':db.get('last_checkin_id',0)}
            db['running']=running;db['requested']=False;return running

def update_checkin(cid,**changes):
    with state_file('checkin') as db:
        v=db.get('running')
        if v and v['id']==cid:v.update(changes);return v

def finish_checkin(cid,last_id):
    with state_file('checkin') as db:
        if (db.get('running') or {}).get('id')==cid:
            db.update(running=None,active_seconds=0,last_tick=time.time(),last_checkin_id=last_id,last_nudge_reply_id=last_id,last_nudge_bot=db['running'].get('bot'))


def reserved_name(name):
    key=''.join(c for c in unicodedata.normalize('NFKC',name).casefold() if unicodedata.category(c)!='Cf').strip().lstrip('@')
    with state_file('members') as members: reserved=set(members)
    bots_path=Path(__file__).resolve().parent/'guest-room/loop/bots.json'
    with bots_path.open() as f: bots=json.load(f)
    reserved.update(unicodedata.normalize('NFKC',b['name']).casefold() for b in bots)
    reserved.update(('moderator','owner','system'))
    return key in reserved
