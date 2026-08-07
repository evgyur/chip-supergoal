# Offline agent-evaluation integrity: tools, long context, and no-crutches

Use this reference when a SuperGoal must prove agent/tool behavior and context-budget integrity before any live provider benchmark.

## Scope boundary

Offline fixtures can prove protocol handling, deterministic fallback, evaluator integrity, and source-trace consistency. They **cannot** prove current provider quality, routing, latency, or billing. Keep live route claims explicitly unverified until a later approval-bound phase produces provider receipts.

## Tool-loop fidelity

Replay both paths through the real request/response entrypoint:

1. **Tool-first:** the model emits an OpenAI-compatible tool call. Assert a non-empty `tool_call.id`, function name, arguments, and `finish_reason=tool_calls`.
2. **Post-tool continuation:** feed the assistant tool-call message and matching tool result back into the real route, then require a complete visible answer.

When text-normalizing tool transcripts for text-only subcalls, preserve `tool_call_id:function_name` in the assistant marker and the same `tool_call_id` in the following tool-result label. Assert assistant-before-tool ordering. A generic “tool was called” marker loses attribution and is insufficient.

Run both flows at the minimum compatibility visible budget and the default visible budget (normally 2048 and 4096). Do not treat a successful tool-call envelope as proof that the post-tool final answer is complete.

## Long-session simulation

Test raw context occupancy at several pressure points, typically 65%, 85%, and 95% of the declared window.

- Generate **raw occupancy independently** of the production compaction/token estimator.
- Then run the production compactor and estimator on that raw transcript.
- Assert the latest user intent survives, message/character bounds hold, and `compacted_context + internal_completion_envelope <= declared_context_window`.
- Assert visible completion remains its own quantity; context tokens must never be copied into or mistaken for the visible-output budget.

Pitfall: if the simulator uses the production estimator in its generation loop, and that estimator already truncates to the latest N messages, the loop may never reach the requested raw occupancy. This can hang tests while appearing conceptually correct.

## No-crutches verifier

Helpers may transport fixtures and grade schema/outputs only. They must not generate answers, contain accepted answers, or relabel the model source.

A strict offline receipt should bind each case to:

- unique case ID and non-empty answer;
- declared and response model identities;
- non-empty trace ID;
- SHA-256 of the accepted output;
- `helper_generated_answer=false`;
- `helper_answer_access=false`;
- `network_used=false` when running in the offline phase.

Negative tests must reject:

- accepted answer embedded in transport/grader fixtures;
- declared-model/response-model mismatch;
- missing or incorrect output hash;
- helper-generated or relabeled output;
- strict invocation without the explicit no-network gate.

A self-declared fixture trace proves fixture integrity only. Call it an `offline declared-model fixture`, not a live model receipt. Promotion/default-readiness still requires later immutable candidate and approval-bound live evidence.

## Closeout evidence

Retain the no-crutches receipt and SHA-256, run focused tool/long-session/CLI tests, then run the full suite, candidate-scoped lint, compile checks, diff checks, and secret scan. Record any corrected test-design defect in the phase RPD review before marking done.
