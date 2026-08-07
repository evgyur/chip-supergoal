# Private revision-corpus execution lessons

Use for strict-v3 SuperGoals that reconstruct `draft → preview → edit → publish` chains from private Telegram sources and learn only shadow rules.

## Authority wiring

- Keep the broad source registry and volatile Telegram baseline as separate signed evidence artifacts when the contract does so. A consumer must validate both authorities explicitly; do not assume the registry embeds a `telegram_baseline` object.
- Pin expected chat IDs, usernames, authority endpoint, and ownership in the baseline. Reject aliases or mismatched IDs before fetching raw messages.
- If a package command accepts only the source-registry path, resolve the sibling baseline from the fixed evidence directory and validate its exact path. Do not search arbitrary paths.

## Telegram read parsing without leakage

Telegram read APIs may render records differently for private and public chats. Parse records by stable boundaries:

```text
ID: <id> | <variable metadata> | Date: <date> | <variable metadata> | Message: <body>
```

Do not require one exact `Sender:` layout. Public records may add channel/stat fields before `Message:`.

- Treat `page_size` as an API request hint, not proof of returned record count. Some pages expand grouped/forwarded records. Continue the configured page budget and stop only on an actually empty page.
- Never print raw parser samples while debugging. Print only type, byte/record counts, IDs, date ranges, status counts, or a structure-only rendering with every letter and digit replaced.
- Keep fetched raw bodies only under the fixed private staging root with `0700` directories, `0600` regular files, no-follow opens, and aggregate-only evidence under `.supergoal/`.

## Reproducible historical matching

- Baseline reproduction is a blocking characterization gate. Do not lower expected chain/pair counts merely because the first page window is too shallow.
- Increase historical page depth until the baseline date range is covered. Record only aggregate date ranges and counts outside private staging.
- Avoid quadratic full-text diff work across the whole corpus. Before `SequenceMatcher` or another expensive diff, apply cheap guards in this order: publication must follow preview, bounded lead window, token-overlap floor. Then run full normalized/raw similarity only on plausible pairs.
- Keep raw similarity separate from editorial similarity. Normalize automation-only changes such as footers, emoji, counters, and service whitespace before classifying human editorial changes.
- Reject post-publication candidates, ambiguous top scores, and low-confidence matches. Historical inferred pairs remain shadow-only.

## Learner governance

Every candidate report must contain an opaque candidate ID, scope, lifecycle state, opaque support event IDs/hashes, independent-chain count, counterexamples, confidence, regression harms, and a falsifier. Never include raw text or private Telegram IDs in reviewer artifacts.

Promotion eligibility must be derived per candidate from validated support metadata:

- enough independent chains;
- same-channel threshold where required;
- confidence threshold;
- every supporting event marked as immutable live evidence with its event hash validated.

Historical inferred support alone can reach a shadow/promotion-candidate lifecycle label, but it must remain `promotion_eligible=false`. Automatic TOV mutation stays disabled; promotion is a separate manual gate.

## Bounded implementation safety

- Never overwrite a critical transaction/activation tool with a placeholder or incomplete stub. Build a complete candidate file, syntax-check it, then atomically replace the target.
- If a user stop arrives, stop tool calls immediately. Report the exact phase/state and any syntactically invalid or partial artifact so the next continuation repairs it before running more phase commands.
