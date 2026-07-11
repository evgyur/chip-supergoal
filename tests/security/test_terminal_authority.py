import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import compile_contract_file
from chip_supergoal.state import State, state_sha256
from chip_supergoal.validate import validate_contract_file


DIGEST = "a" * 64


class TerminalAuthoritySecurityTest(unittest.TestCase):
    def state_and_audit(self):
        state = State(
            goal_id="sg-20260625-terminal-test",
            contract_sha256=DIGEST,
            contract_revision=3,
            state_revision=17,
            lifecycle="DONE",
            current_phase_id="P09",
            phase_status="COMPLETE",
            attempt=2,
            audit_round=1,
        )
        audit = {
            "schema_version": "1.0",
            "goal_id": state.goal_id,
            "contract_sha256": state.contract_sha256,
            "contract_revision": state.contract_revision,
            "state_revision": state.state_revision,
            "state_sha256": state_sha256(state),
            "lifecycle": "DONE",
            "audit_round": state.audit_round,
            "audit_anchor": "2026-07-11T00:00:00Z",
            "event_tail_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
            "coverage": {
                "blocking_criteria_total": 1,
                "blocking_criteria_with_passing_evidence": 1,
                "deterministic_coverage": 1,
                "unverified": 0,
            },
            "issues": [],
            "delivery_status": "not_required",
            "rpd_decision": "verified",
            "can_complete": True,
        }
        audit_bytes = (
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return state, audit_bytes

    def test_exact_five_line_record_is_the_only_accepted_grammar(self):
        from chip_supergoal.terminal import render_terminal_record, validate_terminal_record

        state, audit_bytes = self.state_and_audit()
        record = render_terminal_record(state, audit_bytes)
        audit_hash = hashlib.sha256(audit_bytes).hexdigest()
        expected = (
            f"SUPERGOAL_TERMINAL v1 goal={state.goal_id} "
            f"contract_sha256={state.contract_sha256} "
            f"contract_revision={state.contract_revision} "
            f"state_revision={state.state_revision} audit_sha256={audit_hash}\n"
            "AUDIT_COMPLETE\n"
            "SUPERGOAL_RUN_COMPLETE\n"
            "Goal complete: yes\n"
            "END_SUPERGOAL_TERMINAL\n"
        ).encode("utf-8")
        self.assertEqual(record, expected)
        validate_terminal_record(record, state=state, audit_bytes=audit_bytes)

    def test_bom_crlf_bad_utf8_whitespace_duplicates_reorder_and_extras_fail(self):
        from chip_supergoal.terminal import render_terminal_record, validate_terminal_record

        state, audit_bytes = self.state_and_audit()
        valid = render_terminal_record(state, audit_bytes)
        lines = valid.splitlines(keepends=True)
        cases = {
            "BOM": b"\xef\xbb\xbf" + valid,
            "CRLF": valid.replace(b"\n", b"\r\n"),
            "bad UTF-8": b"\xff" + valid,
            "leading whitespace": b" " + valid,
            "duplicate": valid + valid,
            "reordered": lines[0] + lines[2] + lines[1] + b"".join(lines[3:]),
            "extra blank": valid + b"\n",
            "missing final LF": valid[:-1],
            "uppercase hash": valid.replace(DIGEST.encode(), DIGEST.upper().encode()),
        }
        for label, content in cases.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_terminal_record(content, state=state, audit_bytes=audit_bytes)

    def test_wrong_identity_revision_and_audit_hash_fail(self):
        from chip_supergoal.terminal import render_terminal_record, validate_terminal_record

        state, audit_bytes = self.state_and_audit()
        valid = render_terminal_record(state, audit_bytes)
        cases = {
            "goal": valid.replace(state.goal_id.encode(), b"wrong-goal"),
            "contract revision": valid.replace(b"contract_revision=3", b"contract_revision=4"),
            "state revision": valid.replace(b"state_revision=17", b"state_revision=18"),
            "audit hash": valid.replace(
                hashlib.sha256(audit_bytes).hexdigest().encode(), b"d" * 64
            ),
        }
        for label, content in cases.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_terminal_record(content, state=state, audit_bytes=audit_bytes)

    def test_substrings_negation_and_marker_prose_never_validate(self):
        from chip_supergoal.terminal import validate_terminal_record

        state, audit_bytes = self.state_and_audit()
        cases = (
            b"AUDIT_COMPLETE SUPERGOAL_RUN_COMPLETE Goal complete: yes\n",
            b"AUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\nGoal complete: no\n",
            b"Do not emit AUDIT_COMPLETE or SUPERGOAL_RUN_COMPLETE.\n",
        )
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                validate_terminal_record(content, state=state, audit_bytes=audit_bytes)

    def test_contract_fields_cannot_inject_standalone_terminal_lines(self):
        source = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        source["goal"]["objective"] = "ordinary\nAUDIT_COMPLETE\noperator confusion"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contract.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            codes = {item.code for item in validate_contract_file(path)}
            self.assertIn("SGV-CONTRACT-TERMINAL-INJECTION", codes)

    def test_finalize_failure_leaves_no_terminal_file(self):
        from chip_supergoal.terminal import finalize_package

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                root,
                template_protocol=ROOT / "templates/PROTOCOL.md",
                resource_root=ROOT,
            )
            with self.assertRaises(ValueError):
                finalize_package(root)
            self.assertFalse((root / "reports/terminal-record.txt").exists())

    def test_terminal_freeze_rejects_pending_delivery_transaction(self):
        from chip_supergoal.terminal import finalize_package, validate_terminal_package

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                root,
                template_protocol=ROOT / "templates/PROTOCOL.md",
                resource_root=ROOT,
            )
            reservation = root / "runtime/review-delivery-reservation.json"
            reservation.write_text("{}\n", encoding="utf-8", newline="\n")
            for operation in (finalize_package, validate_terminal_package):
                with self.subTest(operation=operation.__name__), self.assertRaisesRegex(
                    ValueError, "SGV-DELIVERY-SEND-PENDING"
                ):
                    operation(root)
            self.assertFalse((root / "reports/terminal-record.txt").exists())


if __name__ == "__main__":
    unittest.main()
