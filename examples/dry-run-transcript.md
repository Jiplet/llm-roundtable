# Roundtable: Should a small team adopt a monorepo?

**Members:** haiku (claude_cli/haiku), sonnet (claude_cli/sonnet)
**Chair:** sonnet

## Stage 1: first opinions

### haiku

[haiku's view]

Start from the failure mode you are trying to avoid. Version-skew bugs across services point toward one repo; one team blocking another's CI point away from it. Pick the structure that matches the actual failure you have seen, not the one you fear.

### sonnet

[sonnet's view]

On balance, yes, but only once the team has felt the pain the change is meant to fix. Adopt it for a concrete reason (shared release cadence, duplicated tooling, a cross-cutting refactor that keeps stalling at the repo boundary), not as a default.

## Stage 2: anonymised peer review

Each reviewer saw the other members' answers under a private, per-reviewer label shuffle. Labels below are resolved back to real names after the fact.

### haiku's review

- **A** (sonnet): accuracy: 8/10, insight: 6/10, completeness: 7/10
  Notes: Concrete and testable: gives a condition to check rather than a rule of thumb.

**Ranking:** sonnet
**Reasoning:** Favoured the response with the most testable, decision-shaped claim.

### sonnet's review

- **A** (haiku): accuracy: 8/10, insight: 6/10, completeness: 7/10
  Notes: Concrete and testable: gives a condition to check rather than a rule of thumb.

**Ranking:** haiku
**Reasoning:** Favoured the response with the most testable, decision-shaped claim.

## Stage 3: chair synthesis

Chair synthesis (fake provider): the council converges on a conditional answer rather than a flat yes or no. Adopt the change when the failure mode it fixes has actually been observed; treat it as a default otherwise, and revisit once a specific, named pain point shows up.

## Stage 4: dissent ledger

### Dissent ledger (fake provider)

1. **Claim in dispute:** whether the decision should default to yes or default to no.
   - Member 1: default to no until a concrete failure mode is observed.
   - Member 2: default to yes once release coupling is confirmed, without waiting for a failure.
   - Minority view: Member 2's earlier trigger point.
   - What would settle it: a small pilot measuring coordination overhead before and after, over one release cycle.
   - Chair's decision: kept the conditional framing and named the pilot as the next step rather than picking a side outright.

## Run metadata

| stage | member | elapsed (s) | input tokens | output tokens |
|---|---|---|---|---|
| opinion | haiku | 0.00 | 77 | 66 |
| opinion | sonnet | 0.00 | 77 | 66 |
| review | haiku | 0.00 | 263 | 59 |
| review | sonnet | 0.00 | 263 | 59 |
| synthesis | sonnet | 0.00 | 336 | 68 |
| dissent | sonnet | 0.00 | 418 | 146 |
| **total** | | | **1434** | **464** |

Total tokens: 1434 in / 464 out.
