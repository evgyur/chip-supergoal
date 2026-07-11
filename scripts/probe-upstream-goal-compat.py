#!/usr/bin/env python3
"""Static probes for standard Hermes /goal compatibility."""
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
failures = []

def require(cond, msg):
    if not cond:
        failures.append(msg)

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

required = [
    'references/upstream-goal-compatibility.md',
    'templates/LAUNCH_GOAL.md',
    'templates/PROTOCOL.md',
]
for rel in required:
    require((ROOT / rel).is_file(), f'missing {rel}')

skill = read('SKILL.md')
index = read('references/INDEX.md')
compat = read('references/upstream-goal-compatibility.md')
launch = read('templates/LAUNCH_GOAL.md')
protocol = read('templates/PROTOCOL.md')

require('references/upstream-goal-compatibility.md' in skill, 'root does not dispatch upstream-goal-compatibility')
require('upstream-goal-compatibility.md' in index, 'INDEX does not list upstream-goal-compatibility')
require('standard Hermes `/goal`' in launch, 'LAUNCH_GOAL does not name standard Hermes /goal')
require('custom runner' in compat and 'Forbidden' in compat, 'compat reference missing custom-runner boundary')

actual=[]
for p in ROOT.rglob('*.md'):
    if '.git' in p.parts:
        continue
    for n,line in enumerate(p.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
        if line.startswith('SUPERGOAL_GOAL_BODY:'):
            actual.append(f'{p.relative_to(ROOT).as_posix()}:{n}')
require(len(actual)==1 and actual[0].startswith('templates/LAUNCH_GOAL.md:'), f'launch body not single-sourced: {actual}')

launch_body = next((line for line in launch.splitlines() if line.startswith('SUPERGOAL_GOAL_BODY:')), '')
for phrase in [
    'standard Hermes `/goal` continuation only',
    'Resolve the package root',
    'authoritative runtime/STATE.json',
    'contract-declared boundary',
    'runtime authority permits completion',
    '`AUDIT_COMPLETE`',
    '`SUPERGOAL_RUN_COMPLETE`',
    'Goal complete: yes',
]:
    require(phrase in launch_body, f'launch body missing {phrase}')
require('PROTOCOL.md' in launch, 'LAUNCH_GOAL context does not load PROTOCOL.md')

# The launch body is intentionally concise in v3. Detailed continuation and
# blocker semantics remain package-local in PROTOCOL.md plus the compatibility
# reference instead of being duplicated into a second runtime contract.
for phrase in [
    'continue from `STATE.md` rather than chat memory',
    'phase boundaries are checkpoints, not stop points',
    'Goal complete: no',
    'Completion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.',
    'BLOCKED_BY_APPROVAL',
    'FAILURE_HANDOFF',
    'AUDIT_HANDOFF',
]:
    require(phrase in compat, f'compatibility reference missing {phrase}')
for phrase in [
    'Do not stop at numbered phase boundaries',
    'Weak blockers are forbidden',
    'runtime/STATE.json` is the authoritative runtime state',
]:
    require(phrase in protocol, f'protocol missing continuation authority: {phrase}')

for phrase in [
    '## Standard Hermes `/goal` compatibility',
    'Goal complete: no',
    'Goal complete: yes',
    'AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response',
    'Do not use `Goal complete: yes` anywhere else',
]:
    require(phrase in protocol, f'protocol missing {phrase}')

# Simulated judge semantics: these are deterministic contract assertions, not LLM calls.
def classify(resp: str) -> str:
    if any(x in resp for x in ['BLOCKED_BY_APPROVAL', 'FAILURE_HANDOFF', 'AUDIT_HANDOFF']):
        return 'blocked_done'
    if 'AUDIT_COMPLETE' in resp and 'SUPERGOAL_RUN_COMPLETE' in resp and 'Goal complete: yes' in resp:
        return 'done'
    return 'continue'

fixtures = {
    'phase_done': ('SUPERGOAL_PHASE_DONE\nSUPERGOAL_TURN_YIELD\nGoal complete: no\nNext: phase 2\nCompletion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.', 'continue'),
    'audit_only': ('AUDIT_COMPLETE\nGoal complete: no\nCompletion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.', 'continue'),
    'run_only': ('SUPERGOAL_RUN_COMPLETE\nGoal complete: no\nCompletion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.', 'continue'),
    'full_complete': ('AUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\nGoal complete: yes', 'done'),
    'approval_block': ('BLOCKED_BY_APPROVAL\nRequired input: bounded manifest', 'blocked_done'),
}
for name, (resp, expected) in fixtures.items():
    got = classify(resp)
    require(got == expected, f'judge fixture {name}: got {got}, expected {expected}')

if failures:
    print('\n'.join('FAIL: '+f for f in failures), file=sys.stderr)
    sys.exit(1)
print('PASS: upstream /goal compatibility contracts')
