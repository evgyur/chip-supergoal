#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

_SCRIPT_PACKAGE_ROOT = Path(
    os.path.abspath(os.fspath(Path(__file__).parent.parent))
)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.validate import validate_contract_file, validate_loop_design, validate_package, validate_phase_markdown
from chip_supergoal.compile import CompileSafetyError, compile_contract_file
from chip_supergoal.migrate import MigrationError, migrate_v2_package
from chip_supergoal.diagnostics import ContractValidationError, diagnostics_to_json
from chip_supergoal.delivery import (
    cancel_delivery_reservation,
    check_final_delivery,
    check_review_delivery,
    final_delivery_file,
    record_final_delivery,
    record_review_delivery,
    record_review_delivery_progress,
    review_delivery_files,
    send_final_delivery,
    send_review_delivery,
    show_delivery_reservation,
)
from chip_supergoal.model import load_contract
from chip_supergoal.quality import quality_report_bytes
from chip_supergoal.portable import UnsafeFileError, read_regular_file_no_follow
from chip_supergoal.research import research_report, validate_research_gate
from chip_supergoal.audit import audit_json_bytes, audit_package
from chip_supergoal.archive import (
    deterministic_zip,
    quarantine_archive_transaction_temps,
    recover_archive_publication,
)
from chip_supergoal.evidence import EvidenceRecord, record_evidence
from chip_supergoal.events import strict_json_loads
from chip_supergoal.state import State, StateStore, read_state, recover_from_events
from chip_supergoal.terminal import finalize_package, validate_terminal_package


def _configure_utf8_stdio() -> None:
    """Make every textual CLI response independent of the Windows code page."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


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
    raw_root = getattr(args, "root", None) or _SCRIPT_PACKAGE_ROOT
    lexical_root = Path(os.path.abspath(os.fspath(raw_root)))
    if getattr(args, "cmd", None) == "archive":
        return lexical_root
    return lexical_root.resolve(strict=False)


def _delivery_authorization_from_json(raw: str) -> dict:
    try:
        envelope = strict_json_loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "SGV-DELIVERY-RECEIPT-INVALID: authorization envelope is malformed"
        ) from exc
    if (
        not isinstance(envelope, dict)
        or not {"authorization", "status"}.issubset(envelope)
        or not set(envelope) <= {"authorization", "progress", "receipt", "status"}
        or envelope.get("status")
        not in {"send_required", "send_pending", "record_required"}
        or not isinstance(envelope.get("authorization"), dict)
    ):
        raise ValueError(
            "SGV-DELIVERY-RECEIPT-INVALID: authorization envelope is invalid"
        )
    return envelope["authorization"]


_MAX_AUTHORIZATION_BYTES = 1024 * 1024


def _delivery_authorization_raw(args) -> str:
    inline = getattr(args, "authorization_json", None)
    if inline is not None:
        return inline
    source = getattr(args, "authorization_file", None)
    if source == "-":
        raw = sys.stdin.buffer.read(_MAX_AUTHORIZATION_BYTES + 1)
    elif source is not None:
        path = Path(source)
        try:
            raw = read_regular_file_no_follow(
                path,
                path.parent,
                max_bytes=_MAX_AUTHORIZATION_BYTES,
            )
        except UnsafeFileError as exc:
            if exc.kind == "limit":
                raise ValueError(
                    "SGV-DELIVERY-RECEIPT-INVALID: authorization input too large"
                ) from exc
            raise ValueError(
                "SGV-DELIVERY-RECEIPT-INVALID: authorization input is unsafe"
            ) from exc
        except OSError as exc:
            raise ValueError(
                "SGV-DELIVERY-RECEIPT-INVALID: authorization input cannot be read"
            ) from exc
    else:
        raise ValueError("SGV-DELIVERY-RECEIPT-INVALID: authorization input missing")
    if len(raw) > _MAX_AUTHORIZATION_BYTES:
        raise ValueError("SGV-DELIVERY-RECEIPT-INVALID: authorization input too large")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(
            "SGV-DELIVERY-RECEIPT-INVALID: authorization input is not UTF-8"
        ) from exc


def _delivery_authorization_from_args(args) -> dict:
    return _delivery_authorization_from_json(_delivery_authorization_raw(args))


def _write_authorization_out(args, value: dict) -> None:
    destination = getattr(args, "authorization_out", None)
    if destination is None:
        return
    data = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with Path(destination).open("xb") as stream:
        stream.write(data)


def _review_files_from_authorization_json(raw: str) -> list[str]:
    authorization = _delivery_authorization_from_json(raw)
    files = authorization.get("files")
    required = {"LAUNCH_GOAL.md", "LOOP_DESIGN.md", "ROADMAP.md", "THINKING.md"}
    if (
        authorization.get("kind") != "review-md-files"
        or not isinstance(files, list)
        or not all(
            isinstance(item, str)
            and item
            and item == Path(item).name
            and "\r" not in item
            and "\n" not in item
            for item in files
        )
        or files != sorted(files)
        or len(files) != len(set(files))
        or not required.issubset(files)
    ):
        raise ValueError(
            "SGV-DELIVERY-FILE-SET-MISMATCH: authorization file set is invalid"
        )
    return files


def _delivery_reservation_id_from_json(raw: str) -> str:
    authorization = _delivery_authorization_from_json(raw)
    reservation_id = authorization.get("reservation_id")
    if not isinstance(reservation_id, str) or not re.fullmatch(
        r"[a-f0-9]{32}", reservation_id
    ):
        raise ValueError(
            "SGV-DELIVERY-RECEIPT-INVALID: reservation identity is invalid"
        )
    return reservation_id


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
            try:
                blocker = strict_json_loads(args.blocker_json)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    "SGV-STATE-ILLEGAL-UPDATE: blocker must be strict JSON"
                ) from exc
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
            payload = strict_json_loads(raw)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("SGV-EVIDENCE-MALFORMED: input is not JSON") from exc
        record = EvidenceRecord.from_dict(payload)
        record_evidence(root, record)
        _json_stdout(record.to_dict())
        return 0
    if args.cmd == "archive":
        _json_stdout(
            deterministic_zip(
                root,
                args.out,
                args.manifest,
            )
        )
        return 0
    if args.cmd == "archive-recover":
        _json_stdout(recover_archive_publication(root))
        return 0
    if args.cmd == "archive-quarantine":
        _json_stdout(
            quarantine_archive_transaction_temps(
                root, confirm_aborted=args.confirm_aborted
            )
        )
        return 0
    if args.cmd == "delivery-review-check":
        check = check_review_delivery(
            root, target=args.target, force=args.force
        )
        if check.authorization is not None:
            envelope = {
                "authorization": check.authorization,
                "status": "send_required",
            }
            _write_authorization_out(args, envelope)
            _json_stdout(envelope)
            return 10
        _json_stdout(check.receipt)
        return 0
    if args.cmd == "delivery-review-files":
        for name in review_delivery_files(
            root,
            target=args.target,
            authorization=_delivery_authorization_from_args(args),
            force=args.force,
        ):
            print(name)
        return 0
    if args.cmd == "delivery-review-send":
        _json_stdout(
            send_review_delivery(
                root,
                target=args.target,
                authorization=_delivery_authorization_from_args(args),
                force=args.force,
            )
        )
        return 0
    if args.cmd == "delivery-review-progress":
        _json_stdout(
            record_review_delivery_progress(
                root,
                file=args.file,
                message_id=args.message_id,
                authorization=_delivery_authorization_from_args(args),
            )
        )
        return 0
    if args.cmd == "delivery-review-record":
        receipt = record_review_delivery(
            root,
            target=args.target,
            message_ids=args.message_id,
            authorization=_delivery_authorization_from_args(args),
            force=args.force,
        )
        _json_stdout(receipt)
        return 0
    if args.cmd == "delivery-final-check":
        check = check_final_delivery(
            root,
            target=args.target,
            archive=args.archive,
            force=args.force,
        )
        if check.authorization is not None:
            envelope = {
                "authorization": check.authorization,
                "status": "send_required",
            }
            _write_authorization_out(args, envelope)
            _json_stdout(envelope)
            return 10
        _json_stdout(check.receipt)
        return 0
    if args.cmd == "delivery-final-file":
        print(
            final_delivery_file(
                root,
                target=args.target,
                authorization=_delivery_authorization_from_args(args),
                force=args.force,
            )
        )
        return 0
    if args.cmd == "delivery-final-send":
        _json_stdout(
            send_final_delivery(
                root,
                target=args.target,
                authorization=_delivery_authorization_from_args(args),
                force=args.force,
            )
        )
        return 0
    if args.cmd == "delivery-final-record":
        _json_stdout(
            record_final_delivery(
                root,
                target=args.target,
                archive=args.archive,
                message_id=args.message_id,
                authorization=_delivery_authorization_from_args(args),
                force=args.force,
            )
        )
        return 0
    if args.cmd == "delivery-reservation-show":
        _json_stdout(show_delivery_reservation(root, kind=args.kind))
        return 0
    if args.cmd == "delivery-reservation-cancel":
        _json_stdout(
            cancel_delivery_reservation(
                root,
                kind=args.kind,
                authorization=_delivery_authorization_from_args(args),
                confirm_not_sent=args.confirm_not_sent,
            )
        )
        return 0
    if args.cmd == "delivery-authorization-id":
        print(_delivery_reservation_id_from_json(_delivery_authorization_raw(args)))
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


def _add_authorization_input(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--authorization-json")
    group.add_argument(
        "--authorization-file",
        help="UTF-8 authorization envelope path, or - to read standard input",
    )


def main(argv=None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(prog="sgctl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("compile")
    p.add_argument("contract"); p.add_argument("--out", required=True)
    p = sub.add_parser("migrate-v2")
    p.add_argument("source"); p.add_argument("--out", required=True)
    p = sub.add_parser("validate-contract")
    p.add_argument("path"); p.add_argument("--format", choices=["human","json"], default="human"); p.add_argument("--strict", action="store_true")
    p = sub.add_parser("quality-lint")
    p.add_argument("path"); p.add_argument("--format", choices=["human","json"], default="human")
    p = sub.add_parser("validate-package")
    p.add_argument("root"); p.add_argument("--format", choices=["human","json"], default="human"); p.add_argument("--strict", action="store_true")
    p = sub.add_parser("research-gate")
    p.add_argument("contract"); p.add_argument("--format", choices=["human","json"], default="human")
    p = sub.add_parser("validate-phase-markdown")
    p.add_argument("path"); p.add_argument("--format", choices=["human","json"], default="human")
    p = sub.add_parser("validate-loop-design")
    p.add_argument("path"); p.add_argument("--instantiated", action="store_true"); p.add_argument("--format", choices=["human","json"], default="human")
    for command in (
        "state-show",
        "state-recover",
        "archive-recover",
        "audit",
        "finalize",
        "validate-terminal",
    ):
        p = sub.add_parser(command)
        p.add_argument("root", nargs="?", default=None)
    p = sub.add_parser("archive-quarantine")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--confirm-aborted", action="store_true")
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
    p = sub.add_parser("archive")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--manifest", required=True)
    p = sub.add_parser("delivery-review-check")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--target", required=True)
    p.add_argument("--authorization-out")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("delivery-review-record")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--target", required=True)
    p.add_argument("--message-id", action="append", default=[])
    _add_authorization_input(p)
    p.add_argument("--force", action="store_true")
    for command in ("delivery-review-files", "delivery-review-send"):
        p = sub.add_parser(command)
        p.add_argument("root", nargs="?", default=None)
        p.add_argument("--target", required=True)
        _add_authorization_input(p)
        p.add_argument("--force", action="store_true")
    p = sub.add_parser("delivery-review-progress")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--file", required=True)
    p.add_argument("--message-id", required=True)
    _add_authorization_input(p)
    for command in ("delivery-final-file", "delivery-final-send"):
        p = sub.add_parser(command)
        p.add_argument("root", nargs="?", default=None)
        p.add_argument("--target", required=True)
        _add_authorization_input(p)
        p.add_argument("--force", action="store_true")
    p = sub.add_parser("delivery-reservation-show")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument(
        "--kind", choices=["review-md-files", "final-artifacts"], required=True
    )
    p = sub.add_parser("delivery-reservation-cancel")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument(
        "--kind", choices=["review-md-files", "final-artifacts"], required=True
    )
    _add_authorization_input(p)
    p.add_argument("--confirm-not-sent", action="store_true")
    p = sub.add_parser("delivery-authorization-id")
    _add_authorization_input(p)
    for command in ("delivery-final-check", "delivery-final-record"):
        p = sub.add_parser(command)
        p.add_argument("root", nargs="?", default=None)
        p.add_argument("--target", required=True)
        p.add_argument("--archive", required=True)
        if command == "delivery-final-check":
            p.add_argument("--authorization-out")
            p.add_argument("--force", action="store_true")
        else:
            p.add_argument("--message-id")
            _add_authorization_input(p)
            p.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd in {
        "state-show",
        "state-transition",
        "state-recover",
        "record-evidence",
        "archive",
        "archive-recover",
        "archive-quarantine",
        "delivery-review-check",
        "delivery-review-files",
        "delivery-review-send",
        "delivery-review-progress",
        "delivery-review-record",
        "delivery-final-check",
        "delivery-final-file",
        "delivery-final-send",
        "delivery-final-record",
        "delivery-reservation-show",
        "delivery-reservation-cancel",
        "delivery-authorization-id",
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
        try:
            migrate_v2_package(args.source, args.out)
        except (MigrationError, OSError) as exc:
            print(f"migration error: {exc}", file=sys.stderr)
            return 1
        print(args.out)
        return 0
    if args.cmd == "quality-lint":
        try:
            contract = json.loads(Path(args.path).read_text(encoding="utf-8"))
            if not isinstance(contract, dict):
                raise ValueError("contract root must be an object")
            policy = json.loads((ROOT / "spec/plan-quality-policy.json").read_text(encoding="utf-8"))
            rubric = json.loads((ROOT / "spec/quality-rubric.json").read_text(encoding="utf-8"))
            report_bytes = quality_report_bytes(contract, policy, rubric)
            report = json.loads(report_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"quality lint error: {exc}", file=sys.stderr)
            return 1
        findings = report["findings"]
        if args.format == "json":
            sys.stdout.buffer.write(report_bytes)
        elif findings:
            for item in findings:
                print(f"{item['code']} {item['pointer']}: {item['message']}", file=sys.stderr)
        else:
            print(f"quality {report['status']}")
        return 1 if findings else 0
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
