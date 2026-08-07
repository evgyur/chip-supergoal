#!/usr/bin/env python3
"""Static regression probes for Dev-history SuperGoal hardening contracts."""
from pathlib import Path
import json, re, sys

ROOT = Path(__file__).resolve().parents[1]
failures = []

def require(cond, msg):
    if not cond:
        failures.append(msg)

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

required_files = [
    'references/dev-history-hardening.md',
    'templates/delivery/send-review-md-files.sh',
    'templates/delivery/package-final-artifacts.sh',
    'templates/delivery/send-final-artifacts.sh',
    'templates/delivery/review-md-files-delivery-receipt.schema.json',
    'templates/delivery/final-artifacts-delivery-receipt.schema.json',
]
for rel in required_files:
    require((ROOT / rel).is_file(), f'missing {rel}')

skill = read('SKILL.md')
index = read('references/INDEX.md')
protocol = read('templates/PROTOCOL.md')
dev = read('references/dev-history-hardening.md')
prod = read('references/production-safety.md')
skillm = read('references/skill-maintenance.md')
execsm = read('references/execution-state-machine.md')

dispatch = read('references/dispatch-map.md')
require('references/dev-history-hardening.md' in skill or 'dev-history-hardening.md' in dispatch, 'root/dispatch-map does not dispatch dev-history-hardening')
require('dev-history-hardening.md' in index, 'INDEX does not list dev-history-hardening')
for marker in [
    'Retrieval-before-ask', 'Safe-lane approval', 'Bounded live manifest',
    'Repo/private delivery', 'Gateway restart/autoresume', 'Continuation over status-only'
]:
    require(marker in protocol, f'PROTOCOL missing {marker}')
for phrase in ['у тебя они уже есть', 'startup_pack_v4', 'remote HEAD', 'bounded manifest']:
    require(phrase in dev, f'dev-history reference missing {phrase}')
artifact_boundaries = read('references/artifact-boundaries.md')
for phrase in ['startup_pack_v4', 'THINKING.md', 'ROADMAP.md', 'LAUNCH_GOAL.md', 'Planning delivery failure blocks `READY_TO_DISPATCH`']:
    require(phrase in artifact_boundaries, f'artifact boundaries missing {phrase}')
require('Safe-lane vs live-lane approval matrix' in prod, 'production safety missing approval matrix')
require('Repo/private delivery gate' in skillm, 'skill maintenance missing repo/private delivery gate')
require('Retrieval-before-ask gate' in execsm, 'execution state machine missing retrieval gate')
require('Repo delivery completion gate' in execsm, 'execution state machine missing repo delivery gate')

# Launch body must be single-sourced.
actual=[]
for p in ROOT.rglob('*.md'):
    if '.git' in p.parts:
        continue
    for n,line in enumerate(p.read_text(encoding='utf-8', errors='ignore').splitlines(),1):
        if line.startswith('SUPERGOAL_GOAL_BODY:'):
            actual.append(f'{p.relative_to(ROOT)}:{n}')
require(len(actual)==1 and actual[0].startswith('templates/LAUNCH_GOAL.md:'), f'launch body not single-sourced: {actual}')

# Receipt schemas must be valid JSON and enforce ok/sent true.
for rel in ['templates/delivery/review-md-files-delivery-receipt.schema.json','templates/delivery/final-artifacts-delivery-receipt.schema.json']:
    schema=json.loads(read(rel))
    require(schema['properties']['ok'].get('const') is True, f'{rel} does not require ok=true')
    require(schema['properties']['sent'].get('const') is True, f'{rel} does not require sent=true')
review_schema=json.loads(read('templates/delivery/review-md-files-delivery-receipt.schema.json'))
require(review_schema['properties']['pack_version'].get('const') == 'startup_pack_v4', 'review schema missing startup_pack_v4')
require(review_schema['properties']['files'].get('const') == ['THINKING.md', 'ROADMAP.md', 'LAUNCH_GOAL.md'], 'review schema does not enforce exact three-file inventory')
require(review_schema['properties']['message_ids'].get('minItems') == 3 and review_schema['properties']['message_ids'].get('maxItems') == 3, 'review schema does not enforce exactly three message ids')

if failures:
    print('\n'.join('FAIL: '+f for f in failures), file=sys.stderr)
    sys.exit(1)
print('PASS: dev-history hardening contracts')
