#!/usr/bin/env python3
import argparse
import csv, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / 'docs' / 'chip-supergoal-user-stories.csv'

def text(rel):
    return (ROOT / rel).read_text(encoding='utf-8')
def exists(rel):
    return (ROOT / rel).exists()
def contains(rel, *needles):
    s = text(rel)
    return all(n in s for n in needles)
def any_contains(rel, *needles):
    s = text(rel)
    return any(n in s for n in needles)
def no_actual_launch_body(rel):
    return not any(line.startswith('SUPERGOAL_GOAL_BODY:') for line in text(rel).splitlines())
def only_launch_template_has_body():
    hits=[]
    for p in ROOT.rglob('*'):
        if p.is_file() and '.git' not in p.parts:
            try: s=p.read_text(encoding='utf-8')
            except UnicodeDecodeError: continue
            for i,line in enumerate(s.splitlines(),1):
                if line.startswith('SUPERGOAL_GOAL_BODY:'):
                    hits.append(p.relative_to(ROOT).as_posix())
    return hits == ['templates/LAUNCH_GOAL.md']
def validate_phase_script_has(strict_words):
    s=text('scripts/validate-phase.sh')
    return all(w in s for w in strict_words)

def delivery_script(rel):
    return exists(rel) and any_contains(rel, 'receipt', 'sent', 'ok')

def protocol_has(*markers):
    return contains('templates/PROTOCOL.md', *markers)

def ref_has(rel, *words):
    return contains(rel, *words)

def script_has(rel, *words):
    return exists(rel) and contains(rel, *words)

CHECKS = {
'SG-001': lambda: contains('SKILL.md','/chip-supergoal','standing SuperGoal continuation/repair','Do **not** use for tiny edits'),
'SG-002': lambda: contains('SKILL.md','**Plan-only + honest-state boundary**','must not execute numbered implementation phases'),
'SG-003': lambda: only_launch_template_has_body(),
'SG-004': lambda: contains('SKILL.md','One standard `/goal`','LAUNCH_GOAL.md') and ref_has('references/upstream-goal-compatibility.md','/goal'),
'SG-005': lambda: all(contains('SKILL.md', x) for x in ['THINKING.md','LOOP_DESIGN.md','ROADMAP.md','STATE.md','PROTOCOL.md','LAUNCH_GOAL.md','phases/phase-N.md','scripts/repo-state.sh']),
'SG-006': lambda: validate_phase_script_has(['SUPERGOAL_PHASE_START','Work','Acceptance criteria','RPD required']) ,
'SG-007': lambda: contains('SKILL.md','RPD_PLAN_REVIEW') and ref_has('references/rpd-review-gates.md','checked-holds'),
'SG-008': lambda: contains('SKILL.md','Risky work gets Senior Gate','RPD required: yes|no') and ref_has('references/production-safety.md','approval'),
'SG-009': lambda: protocol_has('AUDIT_COMPLETE','SUPERGOAL_RUN_COMPLETE','RPD_FINAL_REVIEW'),
'SG-010': lambda: delivery_script('templates/delivery/send-review-md-files.sh') and delivery_script('templates/delivery/send-final-artifacts.sh'),
'SG-011': lambda: contains('SKILL.md','Only two gates are allowed','Stage 1 clarifying questions','Stage 6 plan review'),
'SG-012': lambda: contains('SKILL.md','Resolve live skill dir') and ref_has('references/skill-maintenance.md','Live path first'),
'SG-013': lambda: contains('SKILL.md','Brownfield asks 0–2 questions','greenfield batches up to 4'),
'SG-014': lambda: all(exists(p) for p in ['scripts/detect-stack.sh','scripts/detect-env.sh','scripts/summarize-repo.sh']) and contains('SKILL.md','Recon'),
'SG-015': lambda: ref_has('references/research-and-architecture-gates.md','RESEARCH.md') and exists('templates/RESEARCH.md'),
'SG-016': lambda: ref_has('references/architect-plus-lite.md','Architect+ lite') and exists('references/architecture-decision-supergoal.md'),
'SG-017': lambda: contains('SKILL.md','as many phases as the task requires') and ref_has('references/phase-design.md','phase'),
'SG-018': lambda: contains('templates/STATE.md','runtime/STATE.json','authority','generated human-readable projection') and contains('lib/chip_supergoal/state.py','Current phase:','State revision:','Phase status:','Attempt:','Audit round:','Blocker:'),
'SG-019': lambda: protocol_has('SUPERGOAL_PHASE_START','SUPERGOAL_STATUS','SUPERGOAL_PHASE_VERIFY','AUDIT_START','BLOCKED_BY_APPROVAL','SUPERGOAL_RUN_COMPLETE'),
'SG-020': lambda: protocol_has('Do not stop','at numbered phase boundaries','Weak blockers are forbidden','SUPERGOAL_TURN_YIELD'),
'SG-021': lambda: protocol_has('Select the current phase from `runtime/STATE.json`','execute the work items and commands exactly') and ref_has('references/standing-goal-continuation-completion.md','not a request for another status summary'),
'SG-022': lambda: ref_has('references/repeated-complete-continuations.md','stop the loop') and exists('references/repeated-completed-wrapper-guard.md'),
'SG-023': lambda: protocol_has('BLOCKED_BY_APPROVAL','exact class and scope match the current action') and ref_has('references/execution-state-machine.md','READY_FOR_DELETE_APPROVAL'),
'SG-024': lambda: protocol_has('FAILURE_PROBE','FAILURE_ESCALATE','FAILURE_HANDOFF'),
'SG-025': lambda: contains('SKILL.md','Preflight smoke','PREFLIGHT_GREEN','PREFLIGHT_RED'),
'SG-026': lambda: script_has('scripts/repo-state.sh','name_status_for_path','git diff --name-status') and exists('references/repo-state-comparison.md'),
'SG-027': lambda: (contains('SKILL.md','dispatch-map.md') or contains('references/dispatch-map.md','ignored-supergoal-package-hygiene.md')) and ref_has('references/ignored-supergoal-package-hygiene.md','.supergoal'),
'SG-028': lambda: ref_has('references/skill-maintenance.md','Validation','skill_view') and exists('scripts/test.sh'),
'SG-029': lambda: exists('references/upstream-goal-reconciliation.md') and ref_has('references/supergoal-hermes-update-preservation.md','hermes_cli/goals.py'),
'SG-030': lambda: (contains('SKILL.md','dispatch-map.md') or contains('references/dispatch-map.md','supergoal-goal-code-review-hardening.md')) and exists('references/supergoal-goal-code-review-hardening.md'),
'SG-031': lambda: (contains('SKILL.md','dispatch-map.md') or contains('references/dispatch-map.md','rpd-to-supergoal-handoff.md')) and ref_has('references/rpd-to-supergoal-handoff.md','stale'),
'SG-032': lambda: exists('references/telegram-launch-and-delivery.md') and exists('references/telegram-launch-card-ux.md'),
'SG-033': lambda: all(exists(p) for p in ['references/telegram-md-goal-launch-hardening.md','references/telegram-md-goal-launch-ux.md','references/telegram-md-launch-pipeline-hardening.md']),
'SG-034': lambda: ref_has('references/telegram-goal-live-verification.md','visible') and exists('references/telegram-button-goal-session-key.md'),
'SG-035': lambda: exists('references/telegram-review-file-delivery-gate.md') and delivery_script('templates/delivery/send-review-md-files.sh'),
'SG-036': lambda: exists('references/telegram-file-delivery-idempotency.md') and exists('references/telegram-delivery-idempotency.md') and exists('templates/delivery/package-final-artifacts.sh'),
'SG-037': lambda: all(exists(p) for p in ['references/production-safety.md','references/production-deploy-gates.md','references/process-integrity-production-runs.md']),
'SG-038': lambda: all(exists(p) for p in ['references/gateway-restart-live-proof.md','references/gateway-restart-proof-and-bogus-goal.md','references/gateway-goal-startup-recovery.md']),
'SG-039': lambda: exists('references/goal-identity-and-audit-lookup.md') and exists('references/standing-goal-disambiguation-and-audit-lookup.md'),
'SG-040': lambda: ref_has('references/supergoal-status-snapshots.md','Live status snapshot') and protocol_has('SUPERGOAL_STATUS','do not replace evidence records or state transitions'),
'SG-041': lambda: script_has('scripts/probe-dev-history-contracts.py','Dev-history') or exists('scripts/probe-dev-history-contracts.py'),
'SG-042': lambda: exists('scripts/probe-upstream-goal-compat.py') and exists('references/upstream-goal-compatibility.md'),
'SG-043': lambda: script_has('scripts/detect-env.sh','gh auth status'),
'SG-044': lambda: script_has('scripts/detect-stack.sh','git status --porcelain','Remote:'),
'SG-045': lambda: exists('scripts/summarize-repo.sh'),
'SG-046': lambda: (contains('SKILL.md','dispatch-map.md') and contains('references/dispatch-map.md','legacy-monolith-2026-06-19.md')) and exists('references/legacy-monolith-2026-06-19.md'),
'SG-047': lambda: exists('references/auth-ux-polish-phase.md') and ref_has('references/auth-ux-polish-phase.md','role="status"'),
'SG-048': lambda: exists('references/auth-oauth-provider-audit.md') and ref_has('references/auth-oauth-provider-audit.md','OAuth'),
'SG-049': lambda: exists('references/manual-provider-resource-adoption.md') and ref_has('references/manual-provider-resource-adoption.md','manual'),
'SG-050': lambda: all(exists(p) for p in ['references/money-skill-safe-lane-vs-live-rail.md','references/polymarket-live-activation-goal-correction.md','references/polymarket-privy-live-activation-goals.md']),
'SG-051': lambda: exists('references/bounded-manifest-no-internal-approvals.md') and exists('references/no-internal-approval-standing-goal.md'),
'SG-052': lambda: exists('references/goal-state-compression-migration.md') and ref_has('references/goal-state-compression-migration.md','compression'),
'SG-053': lambda: exists('references/supergoal-continuation-and-package-path-drift.md') and exists('references/context-anchor-and-wrong-goal-recovery.md'),
'SG-054': lambda: all(exists(p) for p in ['references/goalmanager-completion-loop-incidents.md','references/standing-goal-final-audit-completion.md','references/rollout-final-audit-lessons.md']),
'SG-055': lambda: exists('README.md') and any_contains('README.md','SuperGoal','chip-supergoal'),
}
parser = argparse.ArgumentParser(description='Validate chip-supergoal user-story coverage.')
parser.add_argument('--update-csv', action='store_true', help='write updated status/evidence columns back to docs/chip-supergoal-user-stories.csv')
args = parser.parse_args()

rows=list(csv.DictReader(CSV_PATH.open(encoding='utf-8')))
# Some historical rows may contain extra comma-split fields if edited manually.
# Do not let DictWriter crash on the implicit None key; the targeted assertions
# below are the canonical regression source.
for r in rows:
    r.pop(None, None)
fail=[]
updated_rows=[]
for r in rows:
    ok=CHECKS.get(r['id'], lambda: False)()
    new_r=dict(r)
    if ok:
        new_r['status']='passed'
        new_r['evidence']='scripts/test-user-stories.py targeted assertion passed'
        new_r['errors']=''
        new_r['retest_status']='passed'
    else:
        new_r['status']='failed'
        new_r['evidence']='scripts/test-user-stories.py targeted assertion failed'
        new_r['errors']='expected behaviour not proven by static/source assertion'
        new_r['retest_status']='not_retested'
        fail.append(r['id'])
    updated_rows.append(new_r)
if args.update_csv:
    with CSV_PATH.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=updated_rows[0].keys(), lineterminator='\n')
        w.writeheader(); w.writerows(updated_rows)
else:
    drift=[]
    for old,new in zip(rows, updated_rows):
        for field in ('status','evidence','errors','retest_status'):
            if old.get(field,'') != new.get(field,''):
                drift.append(f"{old.get('id')}:{field}")
    if drift:
        print('CSV_STATUS_DRIFT '+','.join(drift[:20]))
        print('Run scripts/test-user-stories.py --update-csv to refresh stored evidence.')
        fail.extend(['csv-drift'])
print(f'USER_STORY_TESTS total={len(rows)} passed={len(rows)-len([x for x in fail if x != "csv-drift"])} failed={len([x for x in fail if x != "csv-drift"])}')
if fail:
    print('FAILED '+','.join(fail))
    sys.exit(1)
