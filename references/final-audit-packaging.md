# Final audit and archive publication pattern

Use this when a SuperGoal final audit must publish a deterministic artifact ZIP
and retain machine-verifiable completion authority.

## Avoid the self-referential bundle trap

Do not hand-write a bundle hash into a file that is itself inside that bundle.
Do not patch `reports/final-audit.json`, its Markdown projection, an archive
manifest, or a receipt after the package runtime has validated it.

The package-local Python authorities separate these records:

1. Record criterion and auxiliary evidence through `record-evidence`.
2. Run `python scripts/sgctl.py audit`; treat `reports/final-audit.json` as the
   audit authority and its Markdown file as a projection.
3. Publish the ZIP to an absolute path outside the package:

   ```text
   python scripts/sgctl.py archive <package-root> --out <absolute-external-zip> --manifest <package-root>/out/final-artifacts-manifest.json
   ```

4. Let `archive` perform deterministic readback and atomically publish its
   separate result record. Never add the result record or mutable receipts back
   into the archive generation they describe.
5. Complete any required delivery reservation and receipt before terminal
   finalization.
6. Transition legally to `DONE`, run `python scripts/sgctl.py finalize`, then
   require `python scripts/sgctl.py validate-terminal` to accept the exact
   `reports/terminal-record.txt`.

The archive, archive result, delivery receipt, audit projection, and transcript
markers are evidence with distinct owners. None substitutes for the exact
package-bound terminal record.

## Reporting rule

Report the external ZIP path/hash, final-audit paths, delivery receipt when
required, and the fresh `validate-terminal` result. The compatibility lines
`AUDIT_COMPLETE`, `SUPERGOAL_RUN_COMPLETE`, and `Goal complete: yes` may be
shown only as the exact finalized record; never search arbitrary Markdown for
them or hand-compose them as completion proof.
