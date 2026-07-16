# Repository Structure Cleanup Execution Plan

> Historical note: this document is an execution-phase cleanup plan, not the canonical description of the current repository layout.
> Some paths and actions below reflect planning-time assumptions or partially realized cleanup goals.
> For current navigation, prefer [`../README.md`](../README.md), [`../project-structure-navigation.md`](../project-structure-navigation.md), and [`../knowledge-space/current/README.md`](../knowledge-space/current/README.md).

## Purpose

This document turns the repository-wide cleanup direction into an execution-ready plan.

Unlike the earlier knowledge-base restructuring work, this plan targets full repository navigation clarity, including:

- documentation entrypoints
- backend compatibility and utility layering
- frontend knowledge-base domain organization
- generated artifact cleanup

It is intended to guide a "thorough cleanup" pass rather than a minimal polish pass.

## Expected Change Size

This plan is expected to affect roughly `25` to `45` files, depending on how many frontend components and compatibility shims are adjusted during execution.

The changes are not expected to be algorithmically risky, but they are structurally broad and cross-cutting.

## Cleanup Objectives

1. Make the repository easier to understand from the top level.
2. Make compatibility layers more explicit and less visually misleading.
3. Reduce mixed-purpose directories.
4. Bring frontend structure closer to the knowledge-base domain model.
5. Keep compatibility behavior intact while clarifying structure.

## Execution Strategy

The cleanup should be executed in small, reviewable batches rather than as one monolithic move.

Recommended batch order:

1. documentation and navigation cleanup
2. backend utility and compatibility cleanup
3. frontend knowledge-domain cleanup
4. generated artifact cleanup

## Batch 1: Documentation And Navigation Cleanup

### Goal

Reduce document-entry fragmentation and make `docs/` the primary home for repository navigation material.

### Current friction

Current repository navigation is split across:

- `README.md`
- `docs/project-structure-navigation.md`
- `docs/knowledge-space/*`
- `docs/deepdoc/*`
- `docs/plans/*`
- root-level loose files inside `docs/`

### Planned actions

1. Create `docs/frontend/` if frontend-specific design docs are expected to grow.
2. Keep `docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md` as the formal frontend design document location.
3. Keep `docs/knowledge-space/process/IMPROVEMENT-enterprise-kb.md` as the formal knowledge-space improvement-history document location.
4. Keep `docs/project-structure-navigation.md` as the canonical repository navigation document.
5. Update all references in:
   - `CLAUDE.md`
   - `backend/CLAUDE.md`
   - `frontend/CLAUDE.md`
   - any docs that still reference the old paths
6. Ensure `README.md` points to the canonical document navigation entrypoints.

### Expected file impact

Roughly `8` to `15` files.

### Verification

1. All moved document links resolve.
2. `README.md` points to the right docs.
3. No stale references to the old root-level document paths remain.

## Batch 2: Backend Utility And Compatibility Cleanup

### Goal

Make `backend/src/shared/utils/` clearly distinguish between:

- compatibility-only surfaces
- still-valid implementation utilities

### Current friction

`shared/utils/` still contains a mix of:

- legacy compatibility surfaces:
  - `deepdoc/`
  - `document_readers/`
  - `media_utils.py`
  - `vlm_utils.py`
- actual utilities:
  - `text_utils/`
  - `ansi_strip.py`
  - `crypto.py`
  - `heartbeat.py`
  - `redact.py`
  - `time_utils.py`
- transitional leftovers:
  - `file_validator.py`

### Planned actions

#### 2.1 Clarify the role of `shared/utils/`

Add a short structural guide such as:

- `backend/src/shared/utils/README.md`

This file should explicitly classify each path as:

- compatibility-only
- active utility
- deprecated transitional entrypoint

#### 2.2 Introduce clearer internal grouping

Preferred target direction:

```text
backend/src/shared/utils/
  compat/
    deepdoc/
    document_readers/
    media_utils.py
    vlm_utils.py
  text_utils/
  security/
    crypto.py
    redact.py
  system/
    ansi_strip.py
    heartbeat.py
    time_utils.py
```

If a full move would create too much import churn, an intermediate version is acceptable:

1. keep current paths
2. add explicit compatibility documentation
3. only move the simplest non-runtime-sensitive utility files first

#### 2.3 Normalize `file_validator.py`

Decide whether it should:

- become a shim to `shared/document_processing/validation/`, or
- be removed if fully superseded and unused

#### 2.4 Clarify `backend/src/src/...`

Keep the compatibility bridge package, but add:

- `backend/src/src/README.md`

The README should explain:

- why the package exists
- why it is intentionally minimal
- that no new implementation code should be added there

#### 2.5 Add compatibility verification

Add or extend tests that confirm:

1. legacy import bridges still resolve
2. new packages remain the implementation home
3. source-root bridge packages still work in the expected import path layout

### Expected file impact

Roughly `12` to `22` files.

### Verification

1. Focused import tests pass.
2. Knowledge-base runtime tests still pass.
3. No new implementation code is introduced under `backend/src/src/...`.

## Batch 3: Frontend Knowledge-Domain Cleanup

### Goal

Make the frontend reflect the knowledge-base domain more clearly instead of scattering knowledge-base UI concerns across generic folders.

### Current friction

`frontend/src/components/` currently contains:

- `chat/`
- `common/`

There is no dedicated `knowledge/` domain component area yet.

### Planned actions

#### 3.1 Add a dedicated knowledge component directory

Target addition:

```text
frontend/src/components/knowledge/
```

#### 3.2 Move knowledge-base UI fragments into it

Candidate contents:

- parsing configuration form sections
- chunking configuration panels
- multimodal configuration panels
- knowledge-base settings cards

#### 3.3 Reduce view-level overloading

If knowledge-base UI logic currently lives directly in views, extract reusable pieces into `components/knowledge/`.

#### 3.4 Knowledge API grouping status

The knowledge-base frontend API has now been grouped under:

```text
frontend/src/api/knowledge/
  knowledgeBase.ts
  document.ts
  search.ts
  evaluation.ts
```

This is no longer just a follow-up idea; it is part of the active target structure and should be preserved for future additions.

### Expected file impact

Roughly `8` to `18` files.

### Verification

1. Frontend builds successfully.
2. Component imports resolve.
3. Knowledge-base pages still render as expected.

## Batch 4: Generated Artifact Cleanup

### Goal

Reduce non-source noise in repository navigation.

### Planned actions

1. Remove visible `__pycache__` directories from the worktree.
2. Confirm they are ignored by version control.
3. Review whether files like `kb_typecheck.log` should remain in the repository root.

### Expected file impact

Potentially many deleted generated files, but low semantic risk.

### Verification

1. No tracked cache directories remain.
2. Ignore rules are sufficient to prevent reintroduction.

## Risk Profile

### Low risk

- document moves with reference updates
- adding READMEs and structure guides
- generated artifact cleanup

### Medium risk

- frontend component moves
- utility regrouping with import updates

### Highest risk within this plan

- moving compatibility surfaces under `shared/utils/`
- any path move that could affect older imports, packaging assumptions, or tests

These should always be accompanied by focused compatibility verification.

## Delivery Standard Per Batch

Each batch should satisfy all of the following:

1. The repository structure is more intuitive than before.
2. Compatibility behavior is preserved or explicitly replaced by thin shims.
3. Documentation is updated together with code moves.
4. Focused verification is run for the changed structure.

## Recommended Commit / PR Split

Suggested split:

1. `docs(repo): unify documentation entrypoints and navigation`
2. `refactor(shared): reorganize utility and compatibility layers`
3. `refactor(frontend): introduce knowledge domain components`
4. `chore(repo): remove generated structure noise`

## Expected End State

After completing this execution plan, the repository should have:

- one clearer documentation entry flow
- visibly separated compatibility and implementation layers
- a more discoverable backend utility structure
- a more domain-oriented frontend component structure
- lower navigation noise for future contributors
