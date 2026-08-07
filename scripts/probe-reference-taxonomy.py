#!/usr/bin/env python3
"""Reference taxonomy regression probes for chip-supergoal."""
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
failures = []

def require(cond, msg):
    if not cond:
        failures.append(msg)

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

skill = read('SKILL.md')
index = read('references/INDEX.md')
dispatch = read('references/dispatch-map.md')
artifact = read('references/artifact-boundaries.md')

canonical = [
    'dispatch-map.md',
    'core-planning-contract.md',
    'artifact-boundaries.md',
    'artifact-schemas.md',
    'execution-state-machine.md',
    'upstream-goal-compatibility.md',
    'loop-design-gate.md',
    'rpd-review-gates.md',
    'telegram-launch-and-delivery.md',
    'production-safety.md',
    'skill-maintenance.md',
]
for ref in canonical:
    require((ROOT / 'references' / ref).is_file(), f'missing canonical ref {ref}')
    require(f'`{ref}`' in index or f'references/{ref}' in index, f'INDEX missing {ref}')

for rel in [
    'references/dispatch-map.md',
    'references/artifact-boundaries.md',
    'references/telegram-launch-and-delivery.md',
    'references/execution-state-machine.md',
]:
    require(rel in skill or Path(rel).name in skill, f'root does not surface {rel}')

for phrase in [
    'startup_pack_v4',
    'Superseded incident clusters',
    'Banned active-policy phrases',
    'Artifact boundaries / startup pack v4',
]:
    require(phrase in dispatch, f'dispatch-map missing {phrase}')

for phrase in [
    'THINKING.md', 'ROADMAP.md', 'LAUNCH_GOAL.md',
    'pack_version: "startup_pack_v4"',
    'exactly three real Telegram `message_ids`',
    'Planning delivery failure blocks `READY_TO_DISPATCH`',
]:
    require(phrase in artifact, f'artifact-boundaries missing {phrase}')

# Active policy must not contain stale phrases. Incident/archive files may retain
# old examples only if they are not canonical dispatch targets.
active = [
    Path('SKILL.md'),
    Path('references/dispatch-map.md'),
    Path('references/artifact-boundaries.md'),
    Path('references/telegram-launch-and-delivery.md'),
    Path('references/execution-state-machine.md'),
    Path('references/upstream-goal-compatibility.md'),
    Path('templates/PROTOCOL.md'),
]
banned = [
    'startup_pack_v3',
    'one numbered phase per turn',
    'stop with SUPERGOAL_TURN_YIELD',
    'do not chain phases',
    'execute only current phase',
]
for rel in active:
    text = (ROOT / rel).read_text(encoding='utf-8', errors='ignore')
    for phrase in banned:
        require(phrase not in text, f'{rel} contains stale phrase: {phrase}')

# Root should stay a controller, not a full catalog.
root_dispatch_lines = []
in_dispatch = False
for line in skill.splitlines():
    if line.startswith('## Reference dispatch'):
        in_dispatch = True
        continue
    if in_dispatch and line.startswith('## '):
        break
    if in_dispatch and line.startswith('- '):
        root_dispatch_lines.append(line)
require(len(root_dispatch_lines) <= 14, f'root dispatch bloated: {len(root_dispatch_lines)} bullet lines')
require(len(skill.splitlines()) <= 210, f'root too long after dispatch diet: {len(skill.splitlines())} lines')

if failures:
    print('\n'.join('FAIL: ' + f for f in failures), file=sys.stderr)
    sys.exit(1)
print('PASS: reference taxonomy contracts')
