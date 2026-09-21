import unittest
from server import make_case


class InputTests(unittest.TestCase):
    def test_blank_rejected(self):
        with self.assertRaises(ValueError):
            make_case({'case_id':'F010','message':' ','context':'','teacher_result':'尚未核查'})

    def test_unrecognized_case_rejected(self):
        with self.assertRaises(ValueError):
            make_case({'case_id':'../.env','message':'x'})

    def test_custom_message_loses_synthetic_label(self):
        result=make_case({'case_id':'F010','message':'新消息','context':'新背景','teacher_result':'尚未核查'})
        self.assertFalse(result['synthetic'])

    def test_teacher_value_rejected(self):
        with self.assertRaises(ValueError):
            make_case({'case_id':'F010','message':'x','context':'','teacher_result':'编造核查结果'})
