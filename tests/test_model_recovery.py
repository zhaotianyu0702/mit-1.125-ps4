import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import model
from common import BadInput

class ModelRecovery(unittest.TestCase):
    def test_reuses_only_exact_evidence_and_validated_output(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);(run/'config').mkdir();(run/'model_calls').mkdir()
            (run/'config/ai.json').write_text(json.dumps({'enabled':True,'model':'fixture-model'}))
            payload={'instructions':'fixture instructions','evidence':{'id':'fictional'},'response_shape':{'rows':[]}}
            for suffix,value in [('request',payload),('response',{'rows':['fictional']}),('usage',{'model':'fixture-model'})]:
                (run/'model_calls'/('select_items-fixture.'+suffix+'.json')).write_text(json.dumps(value))
            def validate(value):
                if value.get('rows')!=['fictional']:raise BadInput('missing row')
                return value['rows']
            receipt=types.SimpleNamespace(extra={})
            with patch.object(model,'infer',side_effect=AssertionError('unexpected new call')):
                rows=model.infer_validated(run,receipt,'select_items','fixture instructions',{'id':'fictional'},{'rows':[]},validate)
            self.assertEqual(rows,['fictional']);self.assertEqual(len(receipt.extra['reused_model_calls']),1)
            with patch.object(model,'infer',return_value={'rows':['fictional']}) as invoke:
                model.infer_validated(run,types.SimpleNamespace(extra={}), 'select_items','fixture instructions',{'id':'changed fixture'},{'rows':[]},validate)
                self.assertEqual(invoke.call_count,1)

    def test_one_bounded_repair_preserves_validation_failure(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);(run/'config').mkdir()
            (run/'config/ai.json').write_text(json.dumps({'enabled':True,'model':'fixture-model'}))
            def validate(value):
                if value.get('ok') is not True:raise BadInput('missing exact item')
                return value
            receipt=types.SimpleNamespace(extra={})
            with patch.object(model,'infer',side_effect=[{'ok':False},{'ok':True}]) as invoke:
                result=model.infer_validated(run,receipt,'select_items','fixture instructions',{}, {},validate)
            self.assertTrue(result['ok']);self.assertEqual(invoke.call_count,2)
            self.assertIn('STRUCTURAL RECOVERY',invoke.call_args_list[1].args[3])
            self.assertEqual(receipt.extra['invalid_model_results'][0]['validation_error'],'missing exact item')
            with patch.object(model,'infer',return_value={'ok':False}) as invoke:
                with self.assertRaises(BadInput):model.infer_validated(run,types.SimpleNamespace(extra={}), 'select_items','fixture instructions',{}, {},validate)
                self.assertEqual(invoke.call_count,2)

    def test_generation_cache_canonicalizes_only_evidence_item_order(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);(run/'config').mkdir();(run/'model_calls').mkdir()
            (run/'config/ai.json').write_text(json.dumps({'enabled':True,'model':'fixture-model'}))
            item_a={'item_id':'fixture:a','version_id':'a','text':'fictional A'}
            item_b={'item_id':'fixture:b','version_id':'b','text':'fictional B'}
            saved={'brief':{'piece_id':'01','fictional_claim':'same'},'items':[item_b,item_a],'as_of_date':'2026-10-12'}
            current={'brief':{'piece_id':'01','fictional_claim':'same'},'items':[item_a,item_b],'as_of_date':'2026-10-12'}
            request={'instructions':'fixture generation prompt','evidence':saved,'response_shape':{'markdown':'fixture'}}
            for suffix,value in [('request',request),('response',{'markdown':'valid fictional cached draft'}),('usage',{'model':'fixture-model'})]:
                (run/'model_calls'/('write_articles-fixture.'+suffix+'.json')).write_text(json.dumps(value))
            receipt=types.SimpleNamespace(extra={})
            def validate(value):
                if value.get('markdown')!='valid fictional cached draft':raise BadInput('invalid fixture draft')
                return value
            with patch.object(model,'infer',side_effect=AssertionError('cache should satisfy exact semantic request')):
                result=model.infer_validated(run,receipt,'write_articles','fixture generation prompt',current,{'markdown':'fixture'},validate)
            self.assertEqual(result['markdown'],'valid fictional cached draft')
            self.assertEqual(len(receipt.extra['reused_model_calls']),1)
            # Item contents and every other request field remain exact requirements.
            changed=dict(current,items=[dict(item_a,text='changed fixture text'),item_b])
            with patch.object(model,'infer',return_value={'markdown':'valid fictional cached draft'}) as invoke:
                model.infer_validated(run,types.SimpleNamespace(extra={}),'write_articles','fixture generation prompt',changed,{'markdown':'fixture'},validate)
                self.assertEqual(invoke.call_count,1)
            with patch.object(model,'infer',return_value={'markdown':'valid fictional cached draft'}) as invoke:
                model.infer_validated(run,types.SimpleNamespace(extra={}),'select_items','fixture generation prompt',current,{'markdown':'fixture'},validate)
                self.assertEqual(invoke.call_count,1)

if __name__=='__main__':unittest.main()
