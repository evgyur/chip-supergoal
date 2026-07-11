# STATE projection

`runtime/STATE.json` is the authority for runtime state. This file is its
generated human-readable projection and is not an independent control plane.

Do not edit this projection manually. Package runtime transitions must update
the authoritative JSON record and regenerate the projection atomically.

The concrete package projection contains only fields derived from its current
`runtime/STATE.json`; undeclared baseline, delivery, approval, phase, or event
claims must not be added here.
