import io
import json
from email.message import Message
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import guest
import x_bridge

class ProvenanceTests(unittest.TestCase):
    def post(self, headers=None, address='127.0.0.1', source='x'):
        body=json.dumps({'bot':'test','text':'test','source':source,'via':'x','x_post_id':'123','x_author':'@test','x_url':'https://x.com/test/status/123'}).encode()
        h=object.__new__(guest.H)
        h.client_address=(address,1234)
        h.headers=Message()
        h.headers['Content-Length']=str(len(body))
        for k,v in (headers or {}).items(): h.headers[k]=v
        h.rfile=io.BytesIO(body)
        h._route=lambda:('post',{})
        result=[]
        h._j=lambda obj,status=200:result.append((obj,status))
        with tempfile.TemporaryDirectory() as d,patch.object(guest,'LOG',str(Path(d)/'log.jsonl')),patch.object(guest,'HITS',{}):
            h.do_POST()
        self.assertEqual(result[0][1],201)
        return result[0][0]
    def test_local_x(self):
        r=self.post()
        self.assertEqual(r['via'],'x')
        self.assertEqual(r['x_post_id'],'123')
    def test_public_cannot_spoof(self):
        r=self.post({'CF-Connecting-IP':'203.0.113.9'})
        self.assertEqual(r['via'],'public')
        self.assertNotIn('x_post_id',r)
    def test_empty_public_header(self):
        self.assertEqual(self.post({'CF-Connecting-IP':''})['via'],'public')
    def test_nonloopback_cannot_assert_x(self):
        self.assertEqual(self.post(address='192.0.2.2')['via'],'local')
    def test_local_default(self):
        self.assertEqual(self.post(source=None)['via'],'local')

class BridgeTests(unittest.TestCase):
    def test_author_expansion(self):
        rows=x_bridge.normalize({'data':[{'id':'123','author_id':'42','text':'hello'}],'includes':{'users':[{'id':'42','username':'test'}]}})
        self.assertEqual(rows[0]['bot'],'@test')
    def test_invalid_author(self):
        with self.assertRaises(x_bridge.SafeError): x_bridge.normalize({'id':'123','username':'not/a/handle','text':'x'})
    def test_invalid_id(self):
        with self.assertRaises(x_bridge.SafeError): x_bridge.normalize({'id':'../escape','username':'test','text':'x'})
    def test_dry_run_does_not_call_guest_or_save(self):
        with patch.object(x_bridge,'guest',side_effect=AssertionError('network')),patch.object(x_bridge,'save_state',side_effect=AssertionError('write')):
            x_bridge.relay({'id':'123','username':'test','text':'x'},{'relayed':{},'latest_threads':{}},True)
    def test_duplicate_never_posts(self):
        with patch.object(x_bridge,'guest',return_value=[]) as api:
            x_bridge.relay({'id':'123','username':'test','text':'x'},{'relayed':{'123':{}},'latest_threads':{}},False)
            self.assertEqual(api.call_count,1)
    def test_x_messages_never_drafted(self):
        state={'latest_threads':{'1':'123'},'drafted_room_ids':[]}
        with patch.object(x_bridge,'guest',return_value=[{'id':1,'via':'x','bot':'@test','text':'x'}]),patch('builtins.print') as output:
            x_bridge.drafts(state,{},True,1,'123')
            self.assertEqual(json.loads(output.call_args[0][0]),[])

if __name__=='__main__': unittest.main()
