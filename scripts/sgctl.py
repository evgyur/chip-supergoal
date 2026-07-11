#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.validate import validate_contract_file, validate_loop_design, validate_package, validate_phase_markdown
from chip_supergoal.compile import CompileSafetyError, compile_contract_file
from chip_supergoal.migrate import migrate_v2_package
from chip_supergoal.diagnostics import ContractValidationError, diagnostics_to_json
from chip_supergoal.model import load_contract
from chip_supergoal.research import research_report, validate_research_gate
from chip_supergoal.audit import audit_json_bytes, audit_package
from chip_supergoal.evidence import EvidenceRecord, record_evidence
from chip_supergoal.state import State, StateStore, read_state, recover_from_events
from chip_supergoal.terminal import finalize_package, validate_terminal_package


def emit(diags, fmt: str) -> int:
    if fmt == "json":
        sys.stdout.write(diagnostics_to_json(diags))
    elif diags:
        for d in diags:
            print(d.render_human(), file=sys.stderr)
    else:
        print("valid")
    return 1 if diags else 0


def _json_stdout(value) -> None:
    sys.stdout.write(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def _runtime_error(exc: Exception) -> int:
    match = re.search(r"SGV-[A-Z0-9]+(?:-[A-Z0-9]+)*", str(exc))
    code = match.group(0) if match else "SGV-RUNTIME-ERROR"
    sys.stderr.write(
        json.dumps(
            {"code": code, "error": str(exc) or exc.__class__.__name__, "ok": False},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    return 1


def _runtime_root(args) -> Path:
    return Path(getattr(args, "root", None) or ROOT).resolve(strict=False)


def _run_runtime(args) -> int:
    root = _runtime_root(args)
    if args.cmd == "state-show":
        store = StateStore(root)
        events = store._validated_events()
        state = State.from_dict(events[-1]["state"])
        store._assert_projections_current(state)
        _json_stdout(state.to_dict())
        return 0
    if args.cmd == "state-recover":
        _json_stdout(recover_from_events(root).to_dict())
        return 0
    if args.cmd == "state-transition":
        store = StateStore(root)
        current = read_state(store.state_json, root=root)
        blocker = None
        if args.blocker_json is not None:
            blocker = json.loads(args.blocker_json)
            if not isinstance(blocker, dict):
                raise ValueError("SGV-STATE-ILLEGAL-UPDATE: blocker must be an object")
        if args.to is None or args.to == current.lifecycle:
            kwargs = {}
            if args.phase_id is not None:
                kwargs["phase_id"] = args.phase_id
            if args.phase_status is not None:
                kwargs["phase_status"] = args.phase_status
            if args.attempt is not None:
                kwargs["attempt"] = args.attempt
            if args.blocker_json is not None:
                kwargs["blocker"] = blocker
            if not kwargs:
                raise ValueError("SGV-STATE-ILLEGAL-UPDATE: no state update was supplied")
            state = store.update(expected_revision=args.expected_revision, **kwargs)
        else:
            if args.attempt is not None:
                raise ValueError(
                    "SGV-STATE-ILLEGAL-UPDATE: attempt updates require a same-lifecycle state-transition"
                )
            state = store.transition(
                args.to,
                expected_revision=args.expected_revision,
                phase_id=args.phase_id,
                phase_status=args.phase_status,
                blocker=blocker,
            )
        _json_stdout(state.to_dict())
        return 0
    if args.cmd == "record-evidence":
        raw = sys.stdin.buffer.read() if args.input == "-" else Path(args.input).read_bytes()
        try:
            payload = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("SGV-EVIDENCE-MALFORMED: input is not JSON") from exc
        record = EvidenceRecord.from_dict(payload)
        record_evidence(root, record)
        _json_stdout(record.to_dict())
        return 0
    if args.cmd == "audit":
        sys.stdout.buffer.write(audit_json_bytes(audit_package(root)))
        return 0
    if args.cmd == "finalize":
        sys.stdout.buffer.write(finalize_package(root))
        return 0
    if args.cmd == "validate-terminal":
        validate_terminal_package(root)
        print("valid")
        return 0
    raise ValueError("SGV-RUNTIME-ERROR: unsupported runtime command")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sgctl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("compile")
    p.add_argument("contract"); p.add_argument("--out", required=True)
    p = sub.add_parser("migrate-v2")
    p.add_argument("source"); p.add_argument("--out", required=True)
    p = sub.add_parser("validate-contract")
    p.add_argument("path"); p.add_argument("--format", choices=["human","json"], default="human"); p.add_argument("--strict", action="store_true")
    p = sub.add_parser("validate-package")
    p.add_argument("root"); p.add_argument("--format", choices=["human","json"], default="human"); p.add_argument("--strict", action="store_true")
    p = sub.add_parser("research-gate")
    p.add_argument("contract"); p.add_argument("--format", choices=["human","json"], default="human")
    p = sub.add_parser("validate-phase-markdown")
    p.add_argument("path"); p.add_argument("--format", choices=["human","json"], default="human")
    p = sub.add_parser("validate-loop-design")
    p.add_argument("path"); p.add_argument("--instantiated", action="store_true"); p.add_argument("--format", choices=["human","json"], default="human")
    for command in ("state-show", "state-recover", "audit", "finalize", "validate-terminal"):
        p = sub.add_parser(command)
        p.add_argument("root", nargs="?", default=None)
    p = sub.add_parser("state-transition")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--to")
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--phase-id")
    p.add_argument("--phase-status")
    p.add_argument("--attempt", type=int)
    p.add_argument("--blocker-json")
    p = sub.add_parser("record-evidence")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    if args.cmd in {
        "state-show",
        "state-transition",
        "state-recover",
        "record-evidence",
        "audit",
        "finalize",
        "validate-terminal",
    }:
        try:
            return _run_runtime(args)
        except Exception as exc:
            return _runtime_error(exc)
    if args.cmd == "compile":
        try:
            compile_contract_file(
                args.contract,
                args.out,
                template_protocol=ROOT / "templates/PROTOCOL.md",
                resource_root=ROOT,
            )
        except ContractValidationError as exc:
            for diagnostic in exc.diagnostics:
                print(diagnostic.render_human(), file=sys.stderr)
            return 1
        except CompileSafetyError as exc:
            print(f"compile error: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"compile error: {exc}", file=sys.stderr)
            return 1
        print(args.out)
        return 0
    if args.cmd == "migrate-v2":
        migrate_v2_package(args.source, args.out)
        print(args.out)
        return 0
    if args.cmd == "validate-contract":
        return emit(validate_contract_file(args.path, resource_root=ROOT), args.format)
    if args.cmd == "validate-package":
        return emit(validate_package(args.root), args.format)
    if args.cmd == "research-gate":
        contract = load_contract(args.contract)
        diags = validate_research_gate(contract, artifact=args.contract)
        if args.format == "json" and not diags:
            sys.stdout.write(json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            return 0
        return emit(diags, args.format)
    if args.cmd == "validate-phase-markdown":
        return emit(validate_phase_markdown(args.path), args.format)
    if args.cmd == "validate-loop-design":
        return emit(validate_loop_design(args.path, instantiated=args.instantiated), args.format)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
