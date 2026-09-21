import json
import tempfile
import unittest
from pathlib import Path
from history import detail, summaries, checked_id


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, identifier, issue=None, timestamp='2026-09-18T00:00:00+00:00'):
        p = self.root / identifier
        p.mkdir()
        r = dict(input={'message':'模拟问题'}, draft={}, case_id='F010', created_at=timestamp, synthetic_input=True)
        if issue:
            r['issue_id'] = issue
        (p / 'result.json').write_text(json.dumps(r), encoding='utf-8')
        return p

    def test_legacy_record_and_latest_review(self):
        identifier = '20260918-100000-aaaaaaaa'
        p = self.write(identifier)
        (p/'review-bbbbbbbb.json').write_text(json.dumps(dict(saved_at='2026-09-18T01:00:00+00:00', reply='人工回复', status='已解决', note='说明')), encoding='utf-8')
        self.assertEqual(summaries(self.root)[0]['status'], '已解决')
        self.assertTrue(detail(self.root, identifier)['revision'].endswith('review-bbbbbbbb.json'))

    def test_continuation_reopens_without_erasing_review(self):
        first = '20260918-100000-aaaaaaaa'
        p = self.write(first)
        (p/'review-bbbbbbbb.json').write_text(json.dumps(dict(saved_at='2026-09-18T01:00:00+00:00', reply='旧回复', status='已解决', note='说明')), encoding='utf-8')
        self.write('20260918-110000-bbbbbbbb', first, '2026-09-18T02:00:00+00:00')
        items = summaries(self.root)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['versions'], 2)
        self.assertEqual(items[0]['status'], '待审核')
        self.assertEqual(detail(self.root, first)['versions'][0]['reviews'][0]['reply'], '旧回复')

    def test_skip_broken_or_non_workbench_records(self):
        self.write('branches-example')
        p=self.root/'20260918-100000-aaaaaaaa';p.mkdir();(p/'result.json').write_text('{')
        self.assertEqual(summaries(self.root), [])

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            checked_id('../.env')
