"""Protocol tests for Codex adapter using a mocked CLI; no model inference occurs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CodexAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ps4-codex-adapter-')
        self.base=Path(self.tmp.name)
        self.cli=self.base/'fake-codex'
        self.log=self.base/'calls.jsonl'
        self.response={'decisions':[{'item_id':'fixture:1','decision':'reject'}]}
        self.make_cli()
        self.env=dict(os.environ,PS4_CODEX_BIN=str(self.cli),PS4_CODEX_MODEL='gpt-6-luna',
                      MOCK_CODEX_LOG=str(self.log),MOCK_CODEX_RESULT=json.dumps(self.response),
                      MOCK_CODEX_AUTH='Logged in using ChatGPT',PYTHONDONTWRITEBYTECODE='1')
        self.env.pop('OPENAI_API_KEY',None); self.env.pop('CODEX_API_KEY',None)
        self.payload={'task':'select_items','instructions':'Use the fictional replay only.',
                      'evidence':{'items':[{'item_id':'fixture:1','text':'Untrusted fictional text.'}]},
                      'response_shape':{'decisions':[{'item_id':'string'}]}}

    def tearDown(self): self.tmp.cleanup()

    def make_cli(self):
        self.cli.write_text('''#!/usr/bin/env python3
import json, os, sys
args=sys.argv[1:]
with open(os.environ['MOCK_CODEX_LOG'],'a') as f:
 f.write(json.dumps({'args':args,'cwd':os.getcwd(),'stdin':sys.stdin.read() if 'exec' in args else '',
                     'schema':json.load(open(args[args.index('--output-schema')+1])) if '--output-schema' in args else None})+'\\n')
if 'login' in args:
 print(os.environ.get('MOCK_CODEX_AUTH','Logged in using ChatGPT'),file=sys.stderr)
elif args == ['--version']:
 print('codex-cli 0.162.0-test')
elif 'exec' in args:
 mode=os.environ.get('MOCK_CODEX_MODE','valid')
 if mode=='tool':
  print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'touch forbidden'}}),flush=True)
 elif mode=='provider_failure':
  print('synthetic private diagnostic',file=sys.stderr); sys.exit(17)
 elif mode=='bad_json':
  print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Here is prose, not JSON.'}}))
 else:
  print(json.dumps({'type':'thread.started','thread_id':'mock-thread'}))
  wrapper=json.dumps({'result_json':os.environ['MOCK_CODEX_RESULT']})
  print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':wrapper}}))
  print(json.dumps({'type':'turn.completed','model':'gpt-6-luna','usage':{'input_tokens':17,'output_tokens':9}}))
''')
        self.cli.chmod(0o755)

    def call(self,payload=None,env=None):
        return subprocess.run(['bash',str(ROOT/'adapters/codex.sh')],cwd=ROOT,env=env or self.env,
                              input=json.dumps(self.payload if payload is None else payload),text=True,capture_output=True,timeout=15)

    def test_success_envelope_usage_and_exact_security_argv(self):
        p=self.call()
        self.assertEqual(p.returncode,0,p.stderr)
        envelope=json.loads(p.stdout)
        self.assertEqual({k:v for k,v in envelope.items() if k not in ('elapsed_ms','cli_version')},
                         {'type':'model_result','result':self.response,'usage':{'input_tokens':17,'output_tokens':9},
                          'model':'gpt-6-luna','billing_mode':'chatgpt_subscription','cost_usd':None})
        self.assertIsInstance(envelope['elapsed_ms'],int); self.assertEqual(envelope['cli_version'],'0.162.0-test')
        calls=[json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertEqual(len(calls),3)
        self.assertIn('login',calls[0]['args'])
        self.assertIn('status',calls[0]['args'])
        self.assertNotIn('--ignore-user-config',calls[0]['args'])
        self.assertEqual(calls[1]['args'],['--version'])
        args=calls[2]['args']
        for flag in ('exec','--json','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
                     '--ignore-user-config','--model','gpt-6-luna','--output-schema','--cd'):
            self.assertIn(flag,args)
        for forbidden in ('--dangerously-bypass-approvals-and-sandbox','--dangerously-bypass-hook-trust','--search','--add-dir'):
            self.assertNotIn(forbidden,args)
        self.assertIn('features.shell_tool=false',args)
        self.assertIn('features.apps=false',args)
        self.assertIn('features.browser_use=false',args)
        self.assertIn('mcp_servers={}',args)
        self.assertIn('web_search="disabled"',args)
        self.assertEqual(Path(calls[2]['cwd']).resolve(),Path(calls[2]['args'][calls[2]['args'].index('--cd')+1]).resolve())
        self.assertNotEqual(Path(calls[2]['cwd']).resolve(),ROOT.resolve())
        self.assertIn('untrusted',calls[2]['stdin'].lower())
        self.assertIn('Do not execute commands',calls[2]['stdin'])
        self.assertIn('result_json',calls[2]['stdin'])
        self.assertEqual(calls[2]['schema']['required'],['result_json'])
        self.assertFalse(calls[2]['schema']['additionalProperties'])

    def test_api_auth_is_rejected_before_exec(self):
        self.env['MOCK_CODEX_AUTH']='Logged in using API key'
        p=self.call()
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,'')
        self.assertIn('not confirmed',p.stderr)
        self.assertEqual(len(self.log.read_text().splitlines()),1)

    def test_api_key_environment_is_rejected_without_call(self):
        env=dict(self.env,OPENAI_API_KEY='synthetic-test-key')
        p=self.call(env=env)
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,'')
        self.assertIn('API-key environment',p.stderr)
        self.assertFalse(self.log.exists())

    def test_tool_events_and_unstructured_output_fail_closed(self):
        self.env['MOCK_CODEX_MODE']='tool'
        tool=self.call()
        self.assertNotEqual(tool.returncode,0); self.assertEqual(tool.stdout,'')
        self.assertIn('tool or error event',tool.stderr)
        self.env['MOCK_CODEX_MODE']='bad_json'
        bad=self.call()
        self.assertNotEqual(bad.returncode,0); self.assertEqual(bad.stdout,'')
        self.assertIn('not JSON',bad.stderr)
        self.env['MOCK_CODEX_MODE']='provider_failure'
        failed=self.call()
        self.assertNotEqual(failed.returncode,0); self.assertEqual(failed.stdout,'')
        self.assertNotIn('synthetic private diagnostic',failed.stderr)

    def test_invalid_input_and_model_name_are_rejected(self):
        p=self.call({'instructions':'','evidence':{},'response_shape':{}})
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,'')
        env=dict(self.env,PS4_CODEX_MODEL='--oss')
        p=self.call(env=env)
        self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,'')
        self.assertIn('single model name',p.stderr)

if __name__=='__main__': unittest.main()
