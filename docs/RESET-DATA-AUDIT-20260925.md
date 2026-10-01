# Reset data semantics audit

## Decision

The active chatbot path is evidence-first: query planning → server-side authorization → canonical data API → deterministic aggregation/rules → Vietnamese renderer. The language layer never supplies numeric facts.

## Manifest

| Classification | Scope |
|---|---|
| KEEP | domain source, migrations, tests, API contracts, existing operational data until migration is verified |
| REPLACE | synthetic generator, query semantics for current/list/aggregation/trend, temporal normalization |
| REGENERATE | `data/canonical_reset`, train-ready manifests and golden evaluation fixtures |
| BLOCKED | legacy model artifacts trained on synthetic/insufficient history; not loaded for farmer answers |
| UNKNOWN | legacy reports whose provenance cannot be verified; retained outside the active query path |

One technical backup was created at `backup/reset-data-semantics-20260925` before regeneration.

## Canonical reset dataset

The reproducible generator is `scripts/reset_semantics.py` with seed `20260925`, timezone `Asia/Ho_Chi_Minh`, three farmers and three days. It includes normal, missing-quality, stale/offline, no-flow, fertilizer and command/alert scenarios. Its status is `PIPELINE_TEST_ONLY`.
