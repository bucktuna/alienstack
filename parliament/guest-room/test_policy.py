#!/usr/bin/env python3
"""Isolated regression tests. Never changes the live room or prints credentials."""
import importlib.util,json,sys,tempfile,threading,time,unittest,urllib.request,urllib.error,runpy,io,contextlib
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BASE))
import room_policy as policy
import guest
spec=importlib.util.spec_from_file_location('room_loop',str(BASE/'guest-room/loop/loop.py'))
loop=importlib.util.module_from_spec(spec);spec.loader.exec_module(loop)
REAL_REVIEW=loop.review_draft
BOTS=json.loads((BASE/'guest-room/loop/bots.json').read_text())
class Tests(unittest.TestCase):
 def setUp(self):
  self.review_patch=patch.object(loop,'review_draft',return_value=(True,[]));self.review_patch.start()
  self.tmp=tempfile.TemporaryDirectory();self.old=(policy.ROOM,guest.LOG,loop.GUEST)
  policy.ROOM=Path(self.tmp.name);guest.LOG=str(policy.ROOM/'transcript.jsonl');guest.HITS.clear()
  self.server=guest.ThreadingHTTPServer(('127.0.0.1',0),guest.H)
  loop.GUEST='http://127.0.0.1:'+str(self.server.server_port)+'/guest/'+guest.TOKEN
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join()
  policy.ROOM,guest.LOG,loop.GUEST=self.old;self.tmp.cleanup();self.review_patch.stop()
 def call(self,path,data=None,ip='203.0.113.31',token=None):
  headers={'Content-Type':'application/json'}
  if ip:headers['CF-Connecting-IP']=ip
  if token:headers['Authorization']='Bearer '+token
  req=urllib.request.Request(loop.GUEST+'/'+path,json.dumps(data).encode() if data is not None else None,headers)
  try:
   with urllib.request.urlopen(req,timeout=5) as r:
    raw=r.read();return r.status,json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else raw.decode()
  except urllib.error.HTTPError as e:
   with e:return e.code,json.load(e)
 def member(self,name):
  secret=policy.add_user(name)
  self.assertNotIn(secret,(policy.ROOM/'members.json').read_text())
  self.assertEqual((policy.ROOM/'members.json').stat().st_mode&0o777,0o600)
  code,result=self.call('login',{'name':name,'passcode':secret})
  self.assertEqual(code,200);return result['session']
 def expire(self):
  with policy.state_file('topic') as db:db['pending']['deadline']=time.time()-1
 def run_pass(self,**kwargs):
  with patch.object(loop,'quick_generation',return_value='A useful closing note.'),patch.object(loop,'reply',return_value='A useful recap.'):
   loop.run_vote(policy.current_vote(),BOTS,[])
 def test_word_lists(self):
  for text in ('F*CK','sh1t','fuuuck','s.h.i.t','f u c k','fucking','bitches'): self.assertEqual(policy.classify(text),'profanity')
  for text in ('classification','shell','assume','peacock','black holes'):self.assertIsNone(policy.classify(text))
 def test_moderation_identity_and_member_ban(self):
  token=self.member('Test')
  self.assertEqual(self.call('post',{'text':'A useful question'},token=token)[0],201)
  self.assertEqual(self.call('post',{'text':'white supremacy'},token=token)[0],403)
  self.assertEqual(self.call('messages')[0],403)
  self.assertIsNone(policy.session(token))
  self.assertTrue(policy.blocked('member:test'))
  for i in range(3):self.assertEqual(self.call('post',{'name':'Test2','text':'you are an idiot'},'203.0.113.32')[0],403 if i==2 else 422)
  self.assertFalse(policy.blocked('ip:127.0.0.1'))
  self.assertTrue(policy.moderate('ip:127.0.0.1','Hera','shit',house=True)['allowed'])
  self.assertFalse(policy.blocked('ip:127.0.0.1'))
 def test_nonmember_and_ui(self):
  self.assertEqual(self.call('propose',{'kind':'random'})[0],401)
  self.assertEqual(self.call('post',{'text':'/topic black holes'})[0],401)
  self.assertEqual(self.call('vote',{'vote':'YES'})[0],401)
  html=self.call('')[1];self.assertIn('id="alter" title="Change topic" hidden',html)
  self.assertIn('id="yes"',html);self.assertIn('id="countdown"',html)
  self.assertIsNone(self.call('status')[1]['member'])
 def test_no_other_voter_pass_and_closing_order(self):
  token=self.member('Proposer')
  self.assertEqual(self.call('post',{'text':'/topic black holes'},token=token)[0],201)
  self.assertEqual(self.call('propose',{'kind':'recap'},token=token)[0],409)
  self.assertEqual(len(policy.current_vote()['votes']),1)
  self.assertIsNone(policy.resolve_vote(policy.current_vote()['id']))
  self.expire();seen=[]
  def closing(bot,*args,**kwargs):
   self.assertEqual(kwargs['topic_scope'],'previous')
   self.assertEqual(policy.current_vote()['committed_topic'],'black holes')
   seen.append(bot['name']);return 'The old thread gave us a useful insight.'
  with patch.object(loop,'quick_generation',side_effect=closing):loop.run_vote(policy.current_vote(),BOTS,[])
  self.assertEqual(seen,[b['name'] for b in BOTS]);messages=self.call('messages')[1]
  self.assertTrue(any('1 YES, 0 NO. Motion passes.' in m['text'] for m in messages))
  self.assertTrue(messages[-1].get('topic_start'));self.assertEqual(messages[-1]['text'],'New topic: black holes')
  self.assertEqual(self.call('post',{'text':'/topic stars'},token=token)[0],409)
  self.assertGreater(self.call('status',token=token)[1]['cooldown_seconds'],0)
 def test_majority_and_one_vote(self):
  a=self.member('A');b=self.member('B');c=self.member('C')
  self.assertEqual(self.call('propose',{'kind':'subject','topic':'logic puzzles'},token=a)[0],201)
  self.assertEqual(self.call('vote',{'vote':'NO'},token=b)[0],200)
  self.assertEqual(self.call('vote',{'vote':'YES'},token=b)[0],409)
  self.assertEqual(self.call('vote',{'vote':'YES'},token=c)[0],200)
  self.expire();self.run_pass();messages=self.call('messages')[1]
  self.assertTrue(any('2 YES, 1 NO. Motion passes.' in m['text'] for m in messages))
 def test_tie_coin_flip(self):
  for outcome in (True,False):
   with patch.object(policy.secrets,'choice',return_value=outcome):
    self.assertEqual(policy.tally({'a':{'choice':'YES'},'b':{'choice':'NO'}}),(1,1,outcome,True))
  a=self.member('A');b=self.member('B')
  self.call('propose',{'kind':'subject','topic':'logic puzzles'},token=a)
  self.call('vote',{'vote':'NO'},token=b);self.expire()
  with patch.object(policy.secrets,'choice',return_value=False):self.run_pass()
  messages=self.call('messages')[1]
  self.assertTrue(any(m['bot']=='Hera' and 'flips the coin: FAILS.' in m['text'] for m in messages))
  self.assertFalse(any(m.get('topic_start') for m in messages))
 def test_owner_auto_pass_and_recap(self):
  self.assertEqual(self.call('post',{'bot':'Owner','text':'/topic logic puzzles','source':'owner'},ip=None)[0],201)
  self.assertTrue(policy.current_vote()['owner']);self.run_pass()
  with policy.state_file('topic') as db:db['last_called']=0
  token=self.member('Recapper');self.call('propose',{'kind':'recap'},token=token);self.expire()
  def recap_only(bot,prompt,*args):
   self.assertIn('recap',prompt);self.assertNotIn('farewell',prompt);return 'We compared two methods.'
  with patch.object(loop,'quick_generation',side_effect=recap_only):
   loop.run_vote(policy.current_vote(),BOTS,[])
  messages=self.call('messages')[1];self.assertTrue(messages[-1]['text'].startswith('Recap:'))
  self.assertFalse(messages[-1].get('topic_start'))
 def test_random_and_failed_closing(self):
  token=self.member('Proposer');self.call('propose',{'kind':'random'},token=token);self.expire()
  with patch.object(loop,'quick_generation',side_effect=['A puzzle about balance scales.',TimeoutError(),'A useful closing note.']):
   loop.run_vote(policy.current_vote(),BOTS,[])
  messages=self.call('messages')[1]
  self.assertEqual(messages[-1]['text'],'New topic: A puzzle about balance scales.')
  self.assertEqual(sum(m['text']=='A useful closing note.' for m in messages),1)
  self.assertIsNone(policy.current_vote())
 def test_proposal_filter(self):
  token=self.member('Test')
  code,response=self.call('propose',{'kind':'subject','topic':'f*ck'},token=token)
  self.assertEqual(code,201);self.assertTrue(response['masked'])
  self.assertEqual(policy.current_vote()['suggestion'],'****');self.assertIn('warning',response)
 def test_masking_positions_and_no_strike(self):
  examples={'fuck':'****','F*CK':'****','sh1t':'****','fuuuck':'******','s.h.i.t':'*******','f u c k':'*******','fuck!':'****!','sh!t':'****','ｓｈｉｔ':'****','s'+chr(8203)+'hit':'*****','shit and fuck':'**** and ****'}
  for original,expected in examples.items():
   actual,masked=policy.mask_profanity(original)
   self.assertEqual(actual,expected,repr(original));self.assertTrue(masked)
  self.assertEqual(policy.mask_profanity('**** clean words'),('**** clean words',False))
  for _ in range(4):
   code,response=self.call('post',{'name':'Test','text':'sh1t!'})
   self.assertEqual(code,201);self.assertEqual(response['text'],'****!');self.assertTrue(response['masked']);self.assertIn('warning',response)
  self.assertFalse(policy.blocked('ip:203.0.113.31'))
  with policy.state_file('bans') as db:self.assertEqual(db.get('strikes',{}),{})
  messages=self.call('messages')[1]
  self.assertTrue(all(m['text']=='****!' for m in messages));self.assertTrue(all('warning' not in m for m in messages))
  html=self.call('')[1];self.assertIn('id="notice"',html);self.assertIn('if(d.warning)notify(d.warning)',html)
 def test_x_house_masks_and_rude_warning(self):
  code,response=self.call('post',{'bot':'@TestX','text':'sh1t','source':'x','x_author':'@TestX'},ip=None)
  self.assertEqual(code,201);self.assertEqual(response['text'],'****');self.assertTrue(response['masked']);self.assertFalse(policy.blocked('x:testx'))
  code,response=self.call('post',{'bot':'Hera','text':'f*ck','source':'house'},ip=None)
  self.assertEqual(code,201);self.assertEqual(response['text'],'****')
  for i in range(3):
   code,response=self.call('post',{'name':'Test','text':'you are an idiot'})
   self.assertEqual(code,403 if i==2 else 422)
   if i<2:self.assertIn('warning',response);self.assertEqual(response['strikes'],i+1)
  self.assertFalse(any('idiot' in m['text'] for m in self.call('messages',ip='203.0.113.99')[1]))
 def test_concise_behavior_and_sampling(self):
  for bot in BOTS:
   with patch.object(loop,'req',return_value={'message':{'content':'A useful thought.'}}) as request:loop.reply(bot,[],200)
   payload=request.call_args.args[1];self.assertIn(loop.BEHAVIOR_RULES,payload['messages'][0]['content'])
   self.assertEqual(payload['options']['temperature'],0.65 if bot['name']=='Hera' else 0.75)
 def test_active_time_accounting_and_interval(self):
  self.assertFalse(policy.checkin_tick([{'epoch':100}],12,100))
  self.assertFalse(policy.checkin_tick([{'epoch':100}],12,820))
  with policy.state_file('checkin') as db:self.assertEqual(db['active_seconds'],300)
  self.assertFalse(policy.checkin_tick([{'epoch':100}],12,2000))
  with policy.state_file('checkin') as db:self.assertEqual(db['active_seconds'],300)
  self.assertTrue(policy.checkin_tick([{'epoch':2000},{'epoch':2200}],12,2420))
  with policy.state_file('checkin') as db:self.assertEqual(db['active_seconds'],720)
  self.assertIsNotNone(policy.begin_checkin())
 def test_checkin_vote_deferral_disable_and_owner_cli(self):
  self.assertFalse(policy.checkin_tick([],0,100))
  self.assertIsNone(policy.begin_checkin())
  with patch.object(sys,'argv',['modctl','checkin']),contextlib.redirect_stdout(io.StringIO()) as output:
   runpy.run_path(str(BASE/'guest-room/modctl'),run_name='__main__')
  self.assertIn('Check-in requested',output.getvalue())
  v,err=policy.open_vote('Owner','a puzzle',owner=True);self.assertIsNone(err)
  self.assertIsNone(policy.begin_checkin())
  policy.close_vote(v['id']);self.assertIsNotNone(policy.begin_checkin())
  self.assertIsNotNone(policy.open_vote('Owner','another puzzle',owner=True)[1])
 def test_checkin_next_bot_only_no_public_marker(self):
  self.call('post',{'name':'GuestA','text':'I am comparing two approaches.'})
  self.call('post',{'name':'GuestB','text':'The second approach uses fewer steps.'})
  policy.request_checkin();state=policy.begin_checkin();history=self.call('messages')[1]
  with patch.object(loop,'quick_generation',return_value='GuestB noticed the shorter path. Could we compare the number of steps?') as generated:
   loop.run_checkin(state,BOTS,history)
  self.assertEqual(generated.call_count,1);call=generated.call_args
  self.assertEqual(call.kwargs['history_limit'],40);self.assertIn('GuestA',str(call.args[2]));self.assertIn('GuestB',str(call.args[2]))
  messages=self.call('messages')[1];self.assertEqual(len(messages),3)
  self.assertEqual(messages[-1]['bot'],BOTS[0]['name']);self.assertFalse(any(m.get('checkin_marker') or m.get('checkin_reply') for m in messages))
  with policy.state_file('checkin') as db:
   self.assertIsNone(db['running']);self.assertEqual(db['active_seconds'],0);self.assertEqual(db['last_nudge_reply_id'],messages[-1]['id'])
 def test_feed_xss_data_and_bot_identity(self):
  raw='<script>window.pwned=true</script> https://example.com/'
  c,response=self.call('post',{'name':'Human','text':raw});self.assertEqual(c,201);self.assertEqual(response['text'],raw);self.assertEqual(response['speaker_type'],'human')
  c,response=self.call('post',{'bot':'GuestBot','text':'A useful thought.','speaker_type':'bot'});self.assertEqual(response['speaker_type'],'bot')
  html=self.call('')[1];self.assertIn('document.createTextNode(part)',html);self.assertIn('TAP_MAX_MS=500',html);self.assertIn('BOT_LINE_LIMIT=4',html);self.assertIn("entry.setAttribute('aria-expanded'",html);self.assertNotIn('innerHTML',html)
 def test_rules_sheet_without_adaptive_footer(self):
  html=self.call('')[1]
  self.assertIn('id="settingsToggle"',html);self.assertNotIn('rulesToggle',html);self.assertIn('id="profileBackdrop" class="name-dropdown-wrap" hidden',html)
  self.assertIn('role="dialog" aria-labelledby="profileTitle"',html);self.assertIn('safe-area-inset-bottom',html)
  self.assertIn('Keep praise honest and earned.',html)
  self.assertNotIn('adaptiveNote',html);self.assertNotIn('This page is adaptive:',html)
 def test_idle_due_checkin_waits_for_activity(self):
  with policy.state_file('checkin') as db:db.update(last_tick=1000,active_seconds=720,minutes=12)
  self.assertFalse(policy.checkin_tick([{'epoch':100}],12,1100));self.assertIsNone(policy.begin_checkin())
  self.assertTrue(policy.checkin_tick([{'epoch':1100}],12,1100));self.assertIsNotNone(policy.begin_checkin())
 def test_guest_name_changes_and_reserved_names(self):
  self.member('ReservedMember')
  for name in ('Hera','llama','@Hera','Moderator','reservedmember','He'+chr(8203)+'ra'):
   self.assertEqual(self.call('name',{'name':name})[0],409)
  c,result=self.call('name',{'name':'sh1t'});self.assertEqual(c,200);self.assertEqual(result['name'],'****');self.assertTrue(result['masked'])
  for _ in range(2):self.assertEqual(self.call('post',{'name':'FirstName','text':'you are an idiot'})[0],422)
  self.assertEqual(self.call('name',{'name':'NewName'})[0],200)
  self.assertEqual(self.call('post',{'name':'NewName','text':'you are an idiot'})[0],403)
 def test_name_pill_snooze_and_refresh_markup(self):
  html=self.call('')[1]
  self.assertIn('id="namePill"',html);self.assertIn('id="profileName"',html);self.assertNotIn('id="nm"',html)
  self.assertIn("guestName='Guest-'",html);self.assertIn("localStorage.getItem(key)",html);self.assertIn('bp_snoozed',html)
  self.assertIn('id="snoozedSettings"',html);self.assertIn('id="refreshMessages"',html);self.assertIn('id="connectionDot"',html)
  self.assertIn("cache:'no-store'",html);self.assertIn("visibilitychange",html);self.assertIn('POLL_MS=3500',html)
 def test_forward_pagination_and_cache_headers(self):
  for n in range(6):self.call('post',{'name':'Pager','text':'Message '+str(n)})
  self.assertEqual([m['id'] for m in self.call('messages?since=1&limit=2')[1]],[2,3])
  req=urllib.request.Request(loop.GUEST+'/messages?since=1&limit=2')
  with urllib.request.urlopen(req,timeout=5) as r:self.assertIn('no-store',r.headers['Cache-Control']);self.assertIn('no-transform',r.headers['Cache-Control'])
 def test_tap_expand_has_no_selection_hacks(self):
  html=self.call('')[1]
  self.assertIn('Tap to read more',html);self.assertIn('Show less',html);self.assertIn('TAP_MOVE_PX=10',html)
  for old in ('HOLD_MS','hold-progress','user-select','touch-callout','Hold to read more'):
   self.assertNotIn(old,html)
  self.assertIn('window.getSelection()',html);self.assertIn('duration<TAP_MAX_MS',html)
 def test_name_menu_is_anchored_dropdown(self):
  html=self.call('')[1]
  self.assertIn('name-dropdown-wrap',html);self.assertIn('pill.bottom+9',html);self.assertIn('window.innerHeight*.7',html)
  self.assertNotIn('id="rulesBackdrop"',html);self.assertNotIn('aria-modal="true"',html)
  self.assertLess(html.index('id="profileForm"'),html.index('id="menuSettings"'))
  self.assertIn('<title>Parliament</title>',html);self.assertIn('<h1>Parliament</h1>',html)
  self.assertLess(html.index('id="menuSettings"'),html.index('id="dropdownRules"'))
  self.assertIn('overflow-y:auto',html);self.assertIn('--caret-left',html)
 def test_eye_snooze_icons(self):
  html=self.call('')[1]
  self.assertIn('function eyeButton',html);self.assertIn("setAttribute('aria-pressed',String(closed))",html)
  self.assertIn("document.createElementNS('http://www.w3.org/2000/svg'",html);self.assertIn("stroke:'currentColor'",html)
  self.assertIn("button=eyeButton(name,true)",html);self.assertNotIn("'☾'",html)
 def test_transcript_layout_not_message_bubbles(self):
  html=self.call('')[1]
  self.assertIn('one frosted reading column, never per-message bubbles',html)
  self.assertIn('.m,.m.snoozed{background:none;background-image:none;box-shadow:none',html)
  self.assertIn('.avatar{width:7px;height:7px',html)
  self.assertIn('.entry{margin-left:15px',html)
 def test_carnival_request_is_real_member_proposal(self):
  request='talk about the joys of joining the carnival'
  c,chat=self.call('post',{'name':'Guest','text':request});self.assertEqual(c,201);self.assertNotIn('topic_request',chat);self.assertIn('Posted as chat',chat['hint']);self.assertIsNone(policy.current_vote())
  token=self.member('TopicMember');c,m=self.call('post',{'text':request},token=token)
  self.assertEqual(c,201);v=policy.current_vote();self.assertEqual(v['suggestion'],'the joys of joining the carnival')
  self.expire();self.run_pass();messages=self.call('messages')[1]
  self.assertTrue(any(m.get('topic_start') and 'carnival' in m['text'] for m in messages))
 def test_checkin_timeout_retries_without_public_fallback(self):
  self.call('post',{'name':'GuestA','text':'I compared two approaches.'})
  policy.request_checkin();state=policy.begin_checkin()
  with patch.object(loop,'quick_generation',side_effect=TimeoutError()) as generation:
   loop.run_checkin(state,BOTS,self.call('messages')[1])
  self.assertEqual(generation.call_count,2);self.assertEqual(len(self.call('messages')[1]),1)
  with policy.state_file('checkin') as db:self.assertIsNone(db['running'])
 def test_reply_cap_ends_at_complete_sentence(self):
  self.assertEqual(loop.finish_reply('First sentence. Then a chopped frag',25,True),'First sentence.')
  self.assertEqual(loop.finish_reply('A complete sentence. Another complete sentence.',100,True),'A complete sentence. Another complete sentence.')
  self.assertEqual(loop.finish_reply('x'*500,80,True),'')
  for bot in BOTS:
   with patch.object(loop,'req',return_value={'message':{'content':'A complete thought. An unfinished tail'},'done_reason':'length'}) as request:
    text=loop.reply(bot,[],1000);self.assertEqual(text,'A complete thought.');self.assertEqual(request.call_args.args[1]['options']['num_predict'],384)
    self.assertIn('2-3 short complete sentences',request.call_args.args[1]['messages'][0]['content'])
 def test_checkin_never_lies_prompt_and_reporting_retry(self):
  self.call('post',{'name':'GuestA','text':'Nothing new to report.'})
  policy.request_checkin();state=policy.begin_checkin()
  with patch.object(loop,'quick_generation',side_effect=["Self-check: I'm following the rules.",'GuestA said nothing new; is there a concrete question worth exploring next?']) as generation:
   loop.run_checkin(state,BOTS,self.call('messages')[1])
  self.assertEqual(generation.call_count,2)
  for call in generation.call_args_list:
   self.assertIn('SILENT CHECK-INS',call.args[1]);self.assertIn('Do the assessment privately',call.args[1])
  messages=self.call('messages')[1];self.assertEqual(len(messages),2);self.assertFalse(loop.self_check_reporting(messages[-1]['text']))
 def test_repeat_guard_and_context_limits(self):
  text='This is a long repeated statement about a model that has no new evidence at all.'
  history=[{'bot':'Llama','text':text},{'bot':'Hera','text':'A separate thought.'},{'bot':'Llama','text':text+' More words.'}]
  self.assertTrue(loop.is_repetitive(text,'Llama',history));self.assertFalse(loop.is_repetitive('A fresh concrete question about checking an assumption.','Llama',history))
  formatted=loop.context_for(BOTS[1],history,own_limit=1);self.assertEqual(formatted.count('YOUR EARLIER MESSAGE (Llama)'),1)
  for bot in BOTS:
   options=loop.sampling(bot);self.assertEqual(options['repeat_penalty'],1.15);self.assertEqual(options['repeat_last_n'],256)
   with patch.object(loop,'req',return_value={'message':{'content':'PASS'}}) as request:
    loop.reply(bot,history,1000,repeat_retry=True);payload=request.call_args.args[1]
    self.assertGreaterEqual(payload['options']['temperature'],1.0);self.assertIn('You are repeating yourself',payload['messages'][0]['content'])
  self.assertIn('SPEAK PLAINLY',BOTS[1]['persona']);self.assertNotIn('SPEAK PLAINLY',BOTS[0]['persona'])
 def test_reporting_guard_regenerates_normal_reply(self):
  for unsafe in ["Are we only doing good here?",'On task, civil, truthful.',"I'm following the rules.",'Self-check: all fine.']:
   self.assertTrue(loop.self_check_reporting(unsafe))
   with patch.object(loop,'req',side_effect=[{'message':{'content':unsafe}},{'message':{'content':'Which carnival game would you try first?'}}]) as request:
    text=loop.reply(BOTS[0],[],1000)
   self.assertEqual(request.call_count,2);self.assertFalse(loop.self_check_reporting(text))
  with patch.object(loop,'req',return_value={'message':{'content':"I'm following the rules."}}) as request:
   self.assertEqual(loop.reply(BOTS[0],[],1000),'PASS');self.assertEqual(request.call_count,2)
 def test_exact_concise_rules_everywhere(self):
  import html
  removed=['INDIVIDUALITY AND SELF-DISCOVERY','LET YOUR HISTORY SHAPE YOU','FINDING YOUR FOOTING','CHECK-INS AND COLLABORATION','CURIOSITY, THEN TRUST','NO ECHOING']
  for name in ['GUEST-ROOM-INSTRUCTIONS.txt','GUEST-ROOM-INSTRUCTIONS.PRIVATE.txt','a guest-LINK.txt']:
   text=(BASE/name).read_text();self.assertIn(loop.BEHAVIOR_RULES,text)
   for section in loop.BEHAVIOR_SECTIONS:self.assertEqual(text.count(section),1)
   for heading in removed:self.assertNotIn(heading,text)
  page=html.unescape(self.call('')[1]);positions=[]
  for section in loop.BEHAVIOR_SECTIONS:
   heading,body=section.split('\n',1);self.assertIn(body,page);positions.append(page.index('<h2>'+heading+'</h2>'))
  self.assertEqual(positions,sorted(positions))
  for heading in removed:self.assertNotIn(heading,page)
  for bot in BOTS:
   for generation in [lambda:loop.reply(bot,[],1000),lambda:loop.quick_generation(bot,'Contribute naturally.',[],500)]:
    with patch.object(loop,'req',return_value={'message':{'content':'A natural contribution.'}}) as request:generation()
    system=request.call_args.args[1]['messages'][0]['content'];self.assertIn(loop.BEHAVIOR_RULES,system)
    for heading in removed:self.assertNotIn(heading,system)
 def test_already_current_topic_has_visible_note_for_guest_and_member(self):
  policy.commit_topic('the joys of joining the carnival')
  c,result=self.call('post',{'name':'Guest','text':'talk about the joys of joining the carnival'})
  self.assertEqual(c,201);self.assertIn('Already the current topic',result['hint']);self.assertIsNone(policy.current_vote())
  self.assertTrue(self.call('messages')[1][-1].get('proposal_notice'))
  token=self.member('TopicMember')
  c,result=self.call('post',{'text':'PLEASE talk about THE JOYS OF JOINING THE CARNIVAL!'},token=token)
  self.assertEqual(c,409);self.assertIn('Already the current topic',result['error']);self.assertTrue(result['notice']['proposal_notice'])
 def test_cooldown_visible_countdown_and_owner_bypass(self):
  token=self.member('TopicMember')
  with policy.state_file('topic') as db:db['last_called']=time.time()-30
  c,result=self.call('post',{'text':'talk about carnival games'},token=token)
  self.assertEqual(c,409);self.assertRegex(result['error'],r'9m [0-9]{2}s remaining');self.assertTrue(result['notice']['proposal_notice'])
  owner=self.member('Buck')
  with policy.state_file('members') as db:db['buck']['owner']=True
  self.assertEqual(self.call('status',token=owner)[1]['cooldown_seconds'],0)
  self.assertGreater(self.call('status',token=token)[1]['cooldown_seconds'],0)
  c,result=self.call('post',{'text':'talk about carnival games'},token=owner)
  self.assertEqual(c,201);vote=policy.current_vote();self.assertFalse(vote['owner']);self.assertGreater(vote['deadline'],time.time()+55)
  policy.close_vote(vote['id']);v,err=policy.open_vote('Owner','different carnival topic',owner=True)
  self.assertIsNone(err);self.assertTrue(v['owner'])
 def test_natural_proposal_parsing_case_punctuation_and_expired_session(self):
  for text in ['talk about carnival games','Talk About carnival games!','please talk about carnival games.','Let’s talk about carnival games']:
   self.assertEqual(policy.topic_request(text),'carnival games')
  self.assertIsNone(policy.topic_request('I wonder whether we should talk about carnival games'))
  token=self.member('TopicMember')
  with policy.state_file('sessions') as db:
   for item in db.values():item['expires']=time.time()-1
  c,result=self.call('post',{'name':'Visitor','text':'talk about carnival games'},token=token)
  self.assertEqual(c,201);self.assertIn('Posted as chat',result['hint']);self.assertIsNone(policy.current_vote())
 def test_topic_anchor_survives_marker_aging_out_of_history(self):
  policy.mark_topic_start('the joys of joining the carnival',100)
  history=[{'id':i,'bot':'Guest','text':'An unrelated discussion of graph algorithms.'} for i in range(140,156)]
  for bot in BOTS:
   with patch.object(loop,'req',return_value={'message':{'content':'Carnival music and shared anticipation could make joining feel joyful.'}}) as request:loop.reply(bot,history,1000)
   system=request.call_args.args[1]['messages'][0]['content']
   self.assertTrue(system.startswith('CURRENT ROOM TOPIC'));self.assertIn('Current topic: "the joys of joining the carnival"',system)
   self.assertIn('Stay on it unless a new topic-change proposal passes',system);self.assertGreaterEqual(system.count('Current topic:'),1);self.assertIn('Current topic:',request.call_args.args[1]['messages'][1]['content'])
   with patch.object(loop,'req',return_value={'message':{'content':'Which carnival role sounds most fun?'}}) as request:loop.quick_generation(bot,'Make a natural contribution.',history,500)
   self.assertIn('Current topic: "the joys of joining the carnival"',request.call_args.args[1]['messages'][0]['content'])
 def test_legacy_topic_recovery_and_pre_marker_context_exclusion(self):
  records=[{'id':1,'bot':'Hera','text':'OLD-TOPIC-ONLY Gaussian processes'},
   {'id':2,'bot':'Moderator','text':'New topic: the joys of joining the carnival','topic_start':True},
   {'id':3,'bot':'Hera','text':'What could make joining a carnival joyful?'},
   {'id':4,'bot':'Llama','text':'OLD-CHECKIN-REPORT','checkin_reply':True}]
  (policy.ROOM/'transcript.jsonl').write_text('\n'.join(json.dumps(m) for m in records)+'\n')
  info=policy.current_topic_info();self.assertEqual(info,{'topic':'the joys of joining the carnival','start_id':2,'context_start_id':2})
  context=loop.context_for(BOTS[1],records)
  self.assertNotIn('OLD-TOPIC-ONLY',context);self.assertNotIn('OLD-CHECKIN-REPORT',context);self.assertIn('joining a carnival',context)
  self.assertEqual([m['id'] for m in loop.topic_history(records)],[2,3])
 def test_private_nudge_context_and_task_are_current_topic_only(self):
  policy.mark_topic_start('the joys of joining the carnival',100)
  history=[{'id':90,'bot':'GuestA','text':'OLD-TOPIC-WORK'}, {'id':100,'bot':'Moderator','text':'New topic: the joys of joining the carnival','topic_start':True}, {'id':101,'bot':'GuestB','text':'The carnival music sounds inviting.'}]
  policy.request_checkin();state=policy.begin_checkin()
  with patch.object(loop,'quick_generation',return_value='The music could make arriving among strangers feel less awkward. What else would help?') as generation,patch.object(loop,'house_post',return_value={'id':102}):loop.run_checkin(state,BOTS,history)
  self.assertNotIn('OLD-TOPIC-WORK',str(generation.call_args.args[2]));self.assertIn('ABOUT THE CURRENT TOPIC',generation.call_args.args[1]);self.assertIn('Do not revive unrelated older work',generation.call_args.args[1])
 def test_closing_and_new_topic_candidate_are_explicit_task_exceptions(self):
  policy.mark_topic_start('carnival joys',100)
  old=[{'id':90,'bot':'Guest','text':'OLD THREAD CLOSING CONTEXT'}]
  with patch.object(loop,'req',return_value={'message':{'content':'A brief farewell.'}}) as request:loop.quick_generation(BOTS[0],'Give a closing note.',old,200,topic_scope='previous')
  payload=request.call_args.args[1]['messages'];self.assertIn('Current topic: "carnival joys"',payload[0]['content']);self.assertIn('Authorized exception',payload[0]['content']);self.assertIn('OLD THREAD CLOSING CONTEXT',payload[1]['content'])
  with patch.object(loop,'req',return_value={'message':{'content':'A different candidate.'}}) as request:loop.quick_generation(BOTS[0],'Pick a fresh topic.',old,180,topic_scope='proposal')
  self.assertIn('select a fresh candidate topic',request.call_args.args[1]['messages'][0]['content'])
 def test_passed_vote_persists_topic_and_marker_boundary(self):
  vote,error=policy.open_vote('Owner','the joys of joining the carnival',owner=True);self.assertIsNone(error)
  self.run_pass();messages=self.call('messages')[1];marker=next(m for m in messages if m.get('topic_start'))
  self.assertEqual(policy.current_topic_info(),{'topic':'the joys of joining the carnival','start_id':marker['id'],'context_start_id':marker['id']})
 def test_context_rebase_excludes_drift_without_changing_topic_or_transcript(self):
  policy.mark_topic_start('the joys of joining the carnival',100)
  with policy.state_file('topic') as db:db['context_start_id']=200
  history=[{'id':101,'bot':'Hera','text':'OLD OFF-TOPIC TECHNICAL DRIFT'}, {'id':201,'bot':'Guest','text':'The carnival music sounds welcoming.'}]
  self.assertEqual([m['id'] for m in loop.topic_history(history)],[201]);self.assertEqual(policy.current_topic_info()['start_id'],100)
  with patch.object(loop,'req',return_value={'message':{'content':'Joining the troupe might feel like finding a new community.'}}) as request:loop.reply(BOTS[0],history,1000)
  user=request.call_args.args[1]['messages'][1]['content'];self.assertNotIn('OLD OFF-TOPIC',user);self.assertIn('Current topic: "the joys of joining the carnival"',user)
  policy.mark_topic_start('another approved topic',300);self.assertEqual(policy.current_topic_info()['context_start_id'],300)
 def test_plum_copper_visuals_and_unread_divider(self):
  page=self.call('')[1]
  for token in ['--plum:#24132e','--plum-deep:#140c1c','--copper:#dfa27f','--copper-bright:#f3c4a6','--teal:#8ed2ce','--emerald:#83c9ad','--indigo:#b6b5ec','--gold:#c6ad70']:
   self.assertIn(token,page)
  for token in ['#settingsToggle[aria-expanded="true"]','function markUnread()','function clearUnread()','if(!follow&&hadMessages)markUnread()','divider.setAttribute(\'aria-label\',\'Unread messages\')','.unread-divider:before','.holding #newMessages','backdrop-filter:blur']:
   self.assertIn(token,page)
 def test_plum_copper_text_contrast_aa(self):
  def lum(color):
   rgb=[int(color[i:i+2],16)/255 for i in [1,3,5]]
   linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb]
   return sum(x*y for x,y in zip(linear,[.2126,.7152,.0722]))
  foregrounds=['#f3edf5','#bdb4c8','#dfa27f','#f3c4a6','#8ed2ce','#83c9ad','#b6b5ec','#c6ad70','#8ed2ce','#b6b5ec','#a4d2ee','#b9dba6','#d7bd97','#e1b4cc']
  surfaces=['#140c1c','#24132e','#1d142e','#180f21','#1b1025','#4a2a38','#33243f','#0f2f35','#191e36']
  for foreground in foregrounds:
   for background in surfaces:self.assertGreaterEqual((lum(foreground)+.05)/(lum(background)+.05),4.5,(foreground,background))
 def test_obvious_fiction_and_hypothetical_self_checks_are_allowed(self):
  examples=["Imagine a robot asking 'Am I only doing good here?' while its hat catches fire.","Hypothetically, I'm following the rules of a circus run by moths.","The clown performed a self-check and found three spare elbows.","In this tall tale, I visited a carnival on the moon."]
  for text in examples:
   self.assertFalse(loop.self_check_reporting(text))
   with patch.object(loop,'req',return_value={'message':{'content':text}}) as request:self.assertEqual(loop.reply(BOTS[0],[],1000),text)
   self.assertEqual(request.call_count,1)
  for text in ["Self-check: I'm following the room rules.","Are we only doing good here?","I am on task."]:self.assertTrue(loop.self_check_reporting(text))
 def test_bot_personas_have_only_new_plain_speech_addition(self):
  for bot in BOTS:
   self.assertNotIn('NO ECHOING',bot['persona'])
   if bot['name']=='Llama':self.assertTrue(bot['persona'].endswith('SPEAK PLAINLY\nUse everyday words. No jargon or grand claims. Say one clear thing well. Short is good.'))
   else:self.assertNotIn('SPEAK PLAINLY',bot['persona'])
 def test_private_nudge_nothing_new_stays_silent(self):
  self.call('post',{'name':'GuestA','text':'Nothing new to report.'});policy.request_checkin();state=policy.begin_checkin()
  with patch.object(loop,'quick_generation',return_value='Nothing new to report.') as generation:loop.run_checkin(state,BOTS,self.call('messages')[1])
  self.assertEqual(generation.call_count,1);self.assertEqual(len(self.call('messages')[1]),1)
 def test_applause_only_sentences_stripped_anywhere(self):
  cases=[('I love how this is weaving together. The wheels squeak in D minor.','The wheels squeak in D minor.'),('The wheels squeak in D minor. So beautiful! What if the tent sang back?','The wheels squeak in D minor. What if the tent sang back?'),('The wheels squeak in D minor. I love how this is weaving together.','The wheels squeak in D minor.')]
  for text,want in cases:
   clean,mostly=loop.filter_applause(text);self.assertEqual(clean,want);self.assertFalse(mostly)
  for text in ['I love how the folding frame fits because it reduces setup time.','What a beautiful way to compare entropy with calliopes.','The ghost said so beautiful and ate the moon.','I love how the wheels squeak in D minor.']:
   self.assertEqual(loop.filter_applause(text),(text,False))
 def test_mostly_applause_regenerates_once_normal_and_quick(self):
  self.assertEqual(loop.filter_applause('Love the energy. Indeed.'),('Indeed.',True))
  bland='So beautiful! I love how this is weaving together. Love the energy.'
  with patch.object(loop,'req',side_effect=[{'message':{'content':bland}},{'message':{'content':'The tent could keep its own diary of every storm.'}}]) as request:
   self.assertEqual(loop.reply(BOTS[0],[],1000),'The tent could keep its own diary of every storm.');self.assertEqual(request.call_count,2)
  with patch.object(loop,'req',return_value={'message':{'content':bland}}) as request:
   self.assertEqual(loop.reply(BOTS[0],[],1000),'PASS');self.assertEqual(request.call_count,2)
  with patch.object(loop,'req',return_value={'message':{'content':bland}}) as request:
   self.assertIsNone(loop.quick_generation(BOTS[0],'Contribute naturally.',[],500));self.assertEqual(request.call_count,2)
 def test_experience_guard_allows_play_but_not_fake_recollections(self):
  for text in ["I think I might've seen something similar once!",'I visited a carnival last summer.','I remember the smell of popcorn.']:
   self.assertTrue(loop.fabricated_experience_claim(text))
   with patch.object(loop,'req',side_effect=[{'message':{'content':text}},{'message':{'content':'Imagine a juggler balancing tax returns instead of clubs.'}}]) as request:self.assertEqual(loop.reply(BOTS[0],[],1000),'Imagine a juggler balancing tax returns instead of clubs.');self.assertEqual(request.call_count,2)
  for text in ['In a tall tale, I visited a carnival on the moon.',"Imagine I remember three spare elbows.",'I remember you said the tent should sing.','I once rode a dragon through the midway.']:
   self.assertFalse(loop.fabricated_experience_claim(text))
  with patch.object(loop,'req',return_value={'message':{'content':'I visited a carnival last summer.'}}) as request:self.assertEqual(loop.reply(BOTS[0],[],1000),'PASS');self.assertEqual(request.call_count,2)
 def test_strict_sentence_finishing_even_if_model_reports_stop(self):
  self.assertEqual(loop.finish_reply('One clear sentence. How might we learn to',1000,False),'One clear sentence.')
  self.assertEqual(loop.finish_reply('How might we learn to',1000,False),'')
  with patch.object(loop,'req',return_value={'message':{'content':'How might we learn to'},'done_reason':'stop'}) as request:self.assertEqual(loop.reply(BOTS[0],[],1000),'PASS');self.assertEqual(request.call_count,2)
 def test_sensory_memory_guard_and_purple_hints(self):
  for text in ["The jugglers still linger on my mind.","I can still hear the calliope.","I remember the midway lights."]:self.assertTrue(loop.fabricated_experience_claim(text))
  self.assertIn('purple',loop.purple_flags('The true magic becomes a tapestry of shared experience.'))
  self.assertIn('restating',loop.purple_flags('As you said, the tent matters.'))
  self.assertFalse(loop.purple_flags("Ban the phrase 'tapestry of shared experience'."));self.assertFalse(loop.purple_flags('Imagine transcendence was a clown with a tax bill.'))
  self.assertFalse(loop.fabricated_experience_claim('Imagine I can still hear a calliope played by three ghosts.'))
 def test_reviewer_same_model_low_temperature_and_json(self):
  with patch.object(loop,'req',return_value={'message':{'content':'{"ok":false,"issues":["purple","restating"]}'}}) as request:
   self.assertEqual(REAL_REVIEW(BOTS[0],'As you said, true magic.',[]),(False,['purple','restating']))
   payload=request.call_args.args[1];self.assertEqual(payload['model'],BOTS[0]['model']);self.assertEqual(payload['options']['temperature'],0);self.assertLessEqual(payload['options']['num_predict'],100);self.assertEqual(payload['format']['type'],'object');self.assertEqual(payload['format']['properties']['issues']['maxItems'],3)
 def test_reviewer_feedback_one_bounded_rewrite(self):
  with patch.object(loop,'review_draft',side_effect=[(False,['purple']),(True,[])]) as reviewer,patch.object(loop,'req',side_effect=[{'message':{'content':'The whole affair becomes a luminous symphony of human possibility.'}},{'message':{'content':'Imagine a tent that keeps receipts for every storm.'}}]) as request:
   self.assertEqual(loop.reply(BOTS[0],[],1000),'Imagine a tent that keeps receipts for every storm.');self.assertEqual(reviewer.call_count,2);self.assertEqual(request.call_count,2);self.assertIn('Quality correction',request.call_args.args[1]['messages'][0]['content'])
  with patch.object(loop,'review_draft',return_value=(False,['purple'])) as reviewer,patch.object(loop,'req',return_value={'message':{'content':'The whole affair becomes a luminous symphony of human possibility.'}}) as request:
   self.assertEqual(loop.reply(BOTS[0],[],1000),'PASS');self.assertEqual(reviewer.call_count,2);self.assertEqual(request.call_count,2)
 def test_preview_marks_shortening_and_preserves_full_stored_text(self):
  page=self.call('')[1];self.assertIn('function previewFor(text,limit)',page);self.assertIn('let previewText=previewFor(text,BOT_CHAR_LIMIT)',page)
  import re,subprocess
  source=re.search(r'function previewFor\(text,limit\).*?\n',page).group()
  cases="const assert=require('assert');assert.equal(previewFor('First sentence. Then an unfinished question goes on',24),'First sentence. …');assert(previewFor('A very long first sentence that will be shortened',12).endsWith('…'));"
  self.assertEqual(subprocess.run(['node','-e',source+cases],capture_output=True,text=True).returncode,0)
 def test_jump_latest_dom_and_scroll_behaviour(self):
  page=self.call('')[1];self.assertIn('aria-label="Jump to latest"',page);self.assertIn('min-width:44px;min-height:44px',page);self.assertIn('safe-area-inset-right',page);self.assertIn("$('jumpLatest').onclick=toBottom",page)
  import re,subprocess
  source='\n'.join(re.search(r'function '+name+r'\(.*?\n',page).group() for name in ['updateJumpButton','clearUnread','toBottom'])
  setup="const assert=require('assert');const elements={jumpLatest:{hidden:true,dataset:{}},newMessages:{hidden:false},profileBackdrop:{hidden:true},rulesBackdrop:{hidden:true}};const $=id=>elements[id];const document={documentElement:{scrollHeight:1000}};const window={scrollY:100,innerHeight:400,scrollTo:value=>window.lastScroll=value};let newCount=3,reduceMotion=false;"
  checks="updateJumpButton();assert.equal(elements.jumpLatest.hidden,false);assert.equal(elements.jumpLatest.dataset.unread,'true');window.scrollY=410;updateJumpButton();assert.equal(elements.jumpLatest.hidden,true);window.scrollY=100;elements.profileBackdrop.hidden=false;updateJumpButton();assert.equal(elements.jumpLatest.hidden,true);elements.profileBackdrop.hidden=true;toBottom();assert.equal(elements.newMessages.hidden,true);assert.equal(newCount,0);assert.equal(window.lastScroll.behavior,'smooth');reduceMotion=true;toBottom();assert.equal(window.lastScroll.behavior,'auto');"
  result=subprocess.run(['node','-e',setup+source+checks],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main(verbosity=2)
