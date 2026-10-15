"""Cross-cutting file, contract and receipt utilities; no pipeline business logic."""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]

class BadInput(ValueError):
    pass

def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def repo_path(value):
    p = (ROOT / value).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise BadInput('Path must remain inside the repository')
    return p

def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))

def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError) as exc:
        raise BadInput(f'Cannot read JSON: {path}: {exc}') from exc

def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def read_jsonl(stream):
    records = []
    for n, line in enumerate(stream, 1):
        if line.strip():
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise BadInput(f'Malformed JSONL at line {n}') from exc
            if not isinstance(value, dict):
                raise BadInput(f'JSONL line {n} must be an object')
            records.append(value)
    return records

def read_records(path):
    with Path(path).open(encoding='utf-8') as f:
        return read_jsonl(f)

def emit(records):
    for record in records:
        print(json.dumps(record, ensure_ascii=False))

class Receipt:
    def __init__(self, run, stage, tools=None):
        self.run, self.stage = Path(run), stage
        self.started_at = utcnow()
        self.input_count = None
        self.output_count = None
        self.tools = tools or ['python3']
        self.cost_usd = None
        self.cost_is_estimate = False
        self.errors = []
        self.extra = {}
        self.status = 'completed'

    def error(self, message):
        self.errors.append(str(message))
        self.status = 'failed'
        print(f'{self.stage}: {message}', file=sys.stderr)

    def save(self, code=0):
        if code:
            self.status = 'invalid' if code == 2 else 'failed'
        value = dict(stage=self.stage, status=self.status, exit_code=code,
                     input_count=self.input_count, output_count=self.output_count,
                     started_at=self.started_at, finished_at=utcnow(), tools=self.tools,
                     cost_usd=self.cost_usd, cost_is_estimate=self.cost_is_estimate,
                     errors=self.errors, **self.extra)
        name = self.stage.replace('/', '_').replace('.', '_')
        write_json(self.run / 'logs' / f'{self.started_at.replace(":", "")}-{name}-{uuid.uuid4().hex[:12]}.json', value)

def stage_main(name, function):
    if len(sys.argv) != 2:
        print(f'Usage: {name} RUN_DIR', file=sys.stderr)
        return 2
    try:
        run = repo_path(sys.argv[1])
        if not (run / 'run.json').is_file():
            raise BadInput('RUN_DIR must contain run.json')
    except BadInput as exc:
        print(str(exc), file=sys.stderr)
        return 2
    receipt = Receipt(run, name)
    code = 0
    try:
        code = function(run, receipt) or 0
    except (BadInput, KeyError, TypeError, ValueError) as exc:
        receipt.error(str(exc))
        code = 2
    except Exception as exc:
        receipt.error(f'{type(exc).__name__}: {exc}')
        code = 1
    if receipt.errors and code == 0:
        code = 1
    receipt.save(code)
    return code
