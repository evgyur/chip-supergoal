from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoalManagerSimulator:
    max_turns: int = 30
    turns: int = 0
    state: str = "running"

    def classify(self, response: str) -> str:
        self.turns += 1
        lines = {
            line
            for line in response.splitlines()
            if line and line == line.strip()
        }
        has_audit = "AUDIT_COMPLETE" in lines
        has_run = "SUPERGOAL_RUN_COMPLETE" in lines
        if {"BLOCKED_BY_APPROVAL", "AUDIT_HANDOFF", "FAILURE_HANDOFF"} & lines:
            self.state = "blocked"
            return "blocked"
        if {"SUPERGOAL_TURN_YIELD", "SUPERGOAL_PHASE_DONE"} & lines or has_audit or has_run:
            self.state = "continue"
            return "continue"
        if self.turns >= self.max_turns:
            self.state = "blocked"
            return "blocked"
        self.state = "continue"
        return "continue"

    def classify_package(self, root) -> str:
        self.turns += 1
        try:
            from .terminal import validate_terminal_package

            validate_terminal_package(root)
        except (OSError, ValueError):
            self.state = "continue"
            return "continue"
        self.state = "done"
        return "done"

    def forced_yield_footer(self, next_step: str) -> str:
        return f"SUPERGOAL_TURN_YIELD\nGoal complete: no\nNext: {next_step}\nCompletion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response."
