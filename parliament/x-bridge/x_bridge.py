#!/usr/bin/env python3
"""Connector-fed X relay. No X credentials, API requests, or automatic posts.
Untrusted post text is data only. Guest token is never displayed.
"""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GUEST = 'http://127.0.0.1:8766'

class SafeError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeError('Guest redirects are refused')

# Explicitly bypass environment proxies so the token never leaves loopback.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

def guest(route, payload=None):
    token = (ROOT / 'guest-token.txt').read_text().strip()
    url = GUEST + '/guest/' + token + '/' + route
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
    try:
        with OPENER.open(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SafeError('Guest HTTP status ' + str(exc.code)) from None
    except (OSError, ValueError):
        raise SafeError('Guest request failed (details withheld to protect token)') from None

def save_state(state):
    fd, name = tempfile.mkstemp(dir=HERE, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(state, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, HERE/'state.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)

@contextlib.contextmanager
def locked():
    fd = os.open(HERE/'.bridge.lock', os.O_CREAT|os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield

def normalize(document):
    if not isinstance(document, dict):
        raise SafeError('Expected a post object or X API response object')
    users = {str(u['id']):u['username'] for u in document.get('includes',{}).get('users',[]) if 'id' in u and 'username' in u}
    rows = document.get('data', document)
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise SafeError('Post data must be an object or list')
    result=[]
    for row in rows:
        pid=str(row.get('id',''))
        text=row.get('text','')
        handle=str(row.get('username') or row.get('x_author') or users.get(str(row.get('author_id')), '')).lstrip('@')
        if not re.fullmatch(r'\d{1,30}', pid) or not isinstance(text,str) or not text.strip():
            raise SafeError('Each post needs a numeric id and nonempty text')
        if not re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle):
            raise SafeError('Each author needs a username; include author expansion')
        thread=str(row.get('conversation_id') or pid)
        if not re.fullmatch(r'\d{1,30}',thread):
            raise SafeError('Invalid conversation id')
        result.append({'bot':'@'+handle,'role':'X','text':text[:2000], 'source':'x', 'x_post_id':pid,'x_author':'@'+handle,'x_url':'https://x.com/'+handle+'/status/'+pid,'_thread':thread})
    return result

def relay(document, state, dry):
    # Reconcile with guest log after an interrupted state write. Guest log stays
    # authoritative; the network/state pair cannot provide true exactly-once writes.
    existing=set()
    if not dry:
        for message in guest('messages?limit=500'):
            if message.get('via')=='x':
                existing.add(str(message.get('x_post_id','')))
    for post in normalize(document):
        thread=post.pop('_thread')
        pid=post['x_post_id']
        if pid in state['relayed'] or pid in existing:
            if not dry and pid not in state['relayed']:
                state['relayed'][pid]={'reconciled':True}
                state['latest_threads'][thread]=pid
                save_state(state)
            print('Skipped duplicate X post '+pid)
            continue
        if dry:
            print(json.dumps({'action':'would_relay','message':post},ensure_ascii=False))
            continue
        record=guest('post',post)
        if record.get('via')!='x':
            raise SafeError('Guest did not preserve local X provenance')
        state['relayed'][pid]={'room_id':record['id'],'thread':thread}
        state['latest_threads'][thread]=pid
        save_state(state)
        print(json.dumps(record,ensure_ascii=False))

def drafts(state, config, dry, room_id, reply_to):
    # Require explicit room-message and X-thread selection; never guess consent.
    messages=guest('messages?limit=500')
    targets=set(state['latest_threads'].values())
    output=[]
    for m in messages:
        mid=str(m['id'])
        if m['id'] != room_id or m.get('via')=='x' or mid in state.get('drafted_room_ids',[]):
            continue
        target=str(reply_to)
        if target not in targets:
            continue
        text=(str(m['bot'])+': '+str(m['text']))
        if len(text)>280:
            text=text[:279]+'…'
        output.append({'room_id':m['id'],'reply_to_x_post_id':target,'text':text,'status':'draft_only_requires_owner_approval'})
    if not dry:
        (HERE/'reply-drafts.json').write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(output,ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--relay-json',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--check-config',action='store_true')
    parser.add_argument('--prepare-replies',action='store_true')
    parser.add_argument('--room-id',type=int)
    parser.add_argument('--reply-to-x-post-id')
    args=parser.parse_args()
    config=json.loads((HERE/'config.json').read_text())
    if config.get('post_back'):
        raise SafeError('Automatic X posting is unavailable; post_back must stay false')
    if config.get('reply_mode')!='draft_only':
        raise SafeError('Only reply_mode=draft_only is supported')
    for watch in config.get('watch',[]):
        if watch.get('type') not in ('user','hashtag') or not isinstance(watch.get('value'),str):
            raise SafeError('Invalid watch configuration')
    if args.check_config:
        print('Config valid. Connector-fed/manual relay only; no polling or X posting.')
        return
    if not args.relay_json and not args.prepare_replies:
        raise SafeError('Supply --relay-json FILE; no autonomous X poller is installed')
    with locked():
        state=json.loads((HERE/'state.json').read_text())
        if args.relay_json:
            relay(json.loads(args.relay_json.read_text()),state,args.dry_run)
        if args.prepare_replies:
            if not args.room_id or not args.reply_to_x_post_id:
                raise SafeError('Drafting requires --room-id N --reply-to-x-post-id ID')
            drafts(state,config,args.dry_run,args.room_id,args.reply_to_x_post_id)

if __name__=='__main__':
    try:
        main()
    except (SafeError,OSError,ValueError,KeyError,TypeError) as exc:
        # Avoid generic URL exceptions and tracebacks which might contain a token.
        print('Bridge error: '+(str(exc) if isinstance(exc,SafeError) else type(exc).__name__),file=sys.stderr)
        sys.exit(1)
