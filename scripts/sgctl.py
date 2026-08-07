#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.validate import validate_contract_file, validate_loop_design, validate_package, validate_phase_markdown
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.migrate import migrate_v2_package
from chip_supergoal.diagnostics import diagnostics_to_json
from chip_supergoal.model import load_contract
from chip_supergoal.research import research_report, validate_research_gate


def emit(diags, fmt: str) -> int:
    if fmt == "json":
        sys.stdout.write(diagnostics_to_json(diags))
    elif diags:
        for d in diags:
            print(d.render_human(), file=sys.stderr)
    else:
        print("valid")
    return 1 if diags else 0


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
    args = parser.parse_args(argv)
    if args.cmd == "compile":
        compile_contract_file(args.contract, args.out, template_protocol=ROOT / "templates/PROTOCOL.md")
        print(args.out)
        return 0
    if args.cmd == "migrate-v2":
        migrate_v2_package(args.source, args.out)
        print(args.out)
        return 0
    if args.cmd == "validate-contract":
        return emit(validate_contract_file(args.path, ROOT / "spec/risk-policy.json"), args.format)
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
