# Agent prompt templates (condensed from the proven briefs)

Write these as shared files in the session scratchpad and point every agent at them; add per-issue specifics in the dispatch prompt (issue number, worktree path, DB name, what earlier waves already changed in "their" files).

## Plan comment (posted on each issue before any implementation)

An implementing agent must be able to execute it with ZERO re-investigation. Sections, in order:
1. **Root cause (grounded)** — file:line re-verified against the CURRENT code (never trust stale line numbers), tables/columns/ledger codes named.
2. **Ask-vs-Decide gate** — money/tax → Moiz+CA; schema/security → Moiz; in-spec bugfix → proceed. State the needed decision + a recommended default.
3. **Fix design** — cite the in-repo reference implementation to copy (e.g. JV posting's lock pattern for concurrency).
4. **Migration** — exact DDL, `down_revision` = current head, backfill, backward-compat. Or "None".
5. **TDD tests first** — named tests incl. the exact repro (must fail pre-fix); races need threads.
6. **Edge cases & regressions** · 7. **Acceptance checklist** · 8. **Copy-paste verification** (reuse the QA repro).
9. **Dependencies/risk/rollout** — incl. detection + repair for already-corrupted rows.
10. **Effort & files touched.**

## Implementer brief (Opus, one issue, TDD)

- Workspace is STRICT: only your worktree + your DB; never the main checkout or another worktree.
- The posted plan is authoritative; if the code disagrees, trust the code and note the deviation.
- TDD: failing integration test first, for the right reason. One migration max, `down_revision` = the worktree's current head, applied to your DB.
- Gated items: implement + test FULLY, mark `PENDING MOIZ/CA SIGN-OFF` in commit + retro, commit to your branch only — never merge/push/rebase.
- **Commit each green checkpoint** (environment interruptions are normal here).
- Run your tests + the broader affected suites + ruff/mypy on changed files.
- Final report: files + migration id, test names + exact counts, repro before→after, deviations, gate status, what the verifier should probe. Honesty about anything unfinished.

## Verifier brief (fresh agent, adversarial, read-only on app code)

- You did not write this and you do not trust it. Fresh DB from the template; apply the branch's migration yourself (proves it applies cleanly).
- **Theater check is mandatory**: checkout the fork-point (`git merge-base HEAD <integration>`) version of the changed source, run the new tests, confirm they FAIL for the claimed reason, restore, confirm clean tree. For concurrency: confirm real threads/Barrier/separate sessions and re-run the race with the lock removed to prove the lock (not a side effect) carries it.
- Diff review vs the plan's root cause; migration single-head + round-trip; run the issue's suite + every suite the diff touches (exact counts); ruff/mypy; re-run the ORIGINAL QA repro; walk the acceptance checklist; check the gate is honestly flagged.
- Verdict: PASS / PASS-WITH-CONCERNS / FAIL, with the minimal fix if not PASS. A rubber-stamp is worse than useless.
- Tell the verifier about known cross-wave fallout in advance ("if you see exactly failure X in file Y, it's the known #194 issue being fixed separately — anything else is fair game") so it doesn't mis-attribute.

## Orchestrator conduct

- Dispatch verifier the moment its implementer reports; merge the moment the verifier passes; keep ≤2 heavy agents live.
- Trivial verifier concerns (a lint line): fix inline yourself, commit, merge. Real non-blockers: file a follow-up issue.
- Cross-issue test fallout is YOURS to fix on the integration branch, as its own attributed commit.
- Every P0 claim gets an independent orchestrator reproduction before it's treated as fact.
