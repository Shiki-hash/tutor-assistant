import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from datetime import datetime, timezone
import server


def fake_generate(case, knowledge, config):
    return dict(case_id=case['id'], synthetic_input=case['synthetic'], input=case,
                created_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=0,
                source_cards=[], draft=dict(student_reply='模拟测试草稿', evidence=[],
                assistant_checks=['模拟核查'], missing_info=[], suggested_status='待老师核实'), limitations='自动化测试，不是模型输出')


class HistoryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ['cases.json','knowledge.json']:
            (self.root/name).write_bytes((server.ROOT/name).read_bytes())
        for name,value in [('ROOT',self.root),('settings',lambda:{}),('generate',fake_generate)]:
            p=patch.object(server,name,value);p.start();self.addCleanup(p.stop)
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
        self.url=f'http://127.0.0.1:{self.http.server_port}'
        self.client=build_opener(ProxyHandler({}))

    def request(self,path,data=None,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Workbench-Token']=server.TOKEN
        req=Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with self.client.open(req) as response:return response.status,json.load(response)
        except HTTPError as e:return e.code,json.load(e)

    def test_full_lifecycle_and_stale_conflicts(self):
        payload=dict(case_id='F010',message='测试疑问',context='知识点已知',teacher_result='尚未核查')
        status,one=self.request('/api/generate',payload);self.assertEqual(status,200)
        root=one['record']['issue_id'];oldbytes=(self.root/'outputs'/one['run_id']/'result.json').read_bytes()
        review=dict(run_id=one['run_id'],revision=one['revision'],reply='人工回复',reviewed=True,status='已解决',note='')
        self.assertEqual(self.request('/api/review',review)[0],400)
        review['note']='测试解决依据';status,saved=self.request('/api/review',review);self.assertEqual(status,200)
        child=dict(payload,issue_id=root,revision=one['revision'],followup='老师补充信息')
        self.assertEqual(self.request('/api/generate',child)[0],409)
        child['revision']=saved['revision'];status,two=self.request('/api/generate',child);self.assertEqual(status,200)
        self.assertIn('老师补充信息',two['record']['input']['context'])
        self.assertEqual(self.request('/api/review',review)[0],409)
        status,history=self.request('/api/history');self.assertEqual(len(history['issues']),1)
        self.assertEqual(history['issues'][0]['status'],'待审核')
        status,timeline=self.request('/api/issue?id='+root);self.assertEqual(len(timeline['versions']),2)
        self.assertEqual(timeline['versions'][0]['reviews'][0]['reply'],'人工回复')
        self.assertEqual((self.root/'outputs'/one['run_id']/'result.json').read_bytes(),oldbytes)
        self.assertEqual(self.request('/api/history',token=False)[0],403)
        self.assertEqual(self.request('/api/issue?id=../.env')[0],400)

    def test_failed_continuation_preserves_only_original(self):
        payload=dict(case_id='F010',message='测试',context='背景',teacher_result='尚未核查')
        _,one=self.request('/api/generate',payload)
        with patch.object(server,'generate',side_effect=RuntimeError('hidden')):
            status,_=self.request('/api/generate',dict(payload,issue_id=one['run_id'],revision=one['revision'],followup='新信息'))
        self.assertEqual(status,502)
        self.assertEqual(len(list((self.root/'outputs').glob('*/result.json'))),1)
