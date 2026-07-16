# Repository Structure Cleanup Implementation

> Historical note: this file is an implementation guide for a cleanup program, not the source of truth for the repository's current layout.
> It may describe compatibility layers, target structures, or staged actions that were only partially completed.
> For the current public-facing structure, start with [`../README.md`](../README.md), [`../project-structure-navigation.md`](../project-structure-navigation.md), and [`../knowledge-space/current/README.md`](../knowledge-space/current/README.md).

## Purpose

This document is the formal implementation guide for the repository structure cleanup.

It consolidates the earlier planning notes into one execution-facing document so future work can proceed batch by batch with clear scope, risks, and verification steps.

## Scope

This cleanup is intended to improve repository clarity without changing the business behavior of the knowledge-base system.

The implementation scope includes:

- documentation and navigation entrypoints
- backend utility and compatibility-layer organization
- frontend knowledge-domain structure
- generated artifact and repository noise cleanup

The implementation does not aim to rewrite core runtime logic.

## Objectives

1. Make the repository easier to understand from the top level.
2. Separate implementation directories from compatibility layers more clearly.
3. Reduce mixed-purpose directories and loose files.
4. Make knowledge-base related frontend code more discoverable.
5. Preserve compatibility unless a path is intentionally replaced with a shim.

## Execution Principles

1. Prefer small, reviewable batches over a single large refactor.
2. Keep runtime behavior stable during structure cleanup.
3. Update documentation together with file moves.
4. When compatibility paths must remain, document them explicitly.
5. Run focused verification after each batch.

## Batch Plan

### Batch 1: Documentation And Navigation Cleanup

#### Goal

Make `docs/` the primary home for repository navigation and design material.

#### Current friction

- repository navigation is split across `README.md`, root-level navigation docs, and multiple doc folders
- `docs/` still contains loose files mixed with grouped directories
- several references still point to legacy locations

#### Planned actions

1. Create `docs/frontend/` if frontend design documents are expected to grow.
2. Standardize `docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md` as the frontend design document location.
3. Standardize `docs/knowledge-space/process/IMPROVEMENT-enterprise-kb.md` as the knowledge-space improvement-history document location.
4. Standardize `docs/project-structure-navigation.md` as the canonical repository navigation document.
5. Update references in `CLAUDE.md`, `backend/CLAUDE.md`, `frontend/CLAUDE.md`, and related docs.
6. Ensure `README.md` points to the canonical documentation entrypoints when safe to update.

#### Expected impact

Roughly `8` to `15` files.

#### Verification

1. Moved document links resolve.
2. No stale references to old document paths remain.
3. Main repository navigation points to the new canonical locations.

### Batch 2: Backend Utility And Compatibility Cleanup

#### Goal

Make `backend/src/shared/utils/` visually and structurally clearer by distinguishing active utilities from compatibility surfaces.

#### Current friction

`backend/src/shared/utils/` still mixes:

- compatibility-oriented paths such as `deepdoc/`, `document_readers/`, `media_utils.py`, and `vlm_utils.py`
- active utilities such as `text_utils/`, `crypto.py`, `redact.py`, `heartbeat.py`, and `time_utils.py`
- transitional files such as `file_validator.py`

#### Planned actions

1. Add `backend/src/shared/utils/README.md` to classify each path.
2. Mark paths as one of:
   - compatibility-only
   - active utility
   - transitional shim
3. If import risk is acceptable, introduce clearer grouping such as:

```text
backend/src/shared/utils/
  compat/
  text_utils/
  security/
  system/
```

4. Decide whether `file_validator.py` should remain a shim or be removed.
5. Add focused tests or import checks for compatibility paths.

#### Expected impact

Roughly `12` to `22` files.

#### Verification

1. Legacy import paths still resolve when intended.
2. Runtime behavior is unchanged.
3. No new implementation logic is added to compatibility-only locations.

### Batch 3: Source-Root Compatibility Clarification

#### Goal

Clarify why `backend/src/src/` exists and prevent future misuse.

#### Current friction

The directory is valid for compatibility, but visually confusing for contributors.

#### Planned actions

1. Add `backend/src/src/README.md`.
2. Explain that this package exists only for import or installation compatibility.
3. State clearly that no new implementation code should be added there.

#### Expected impact

Roughly `1` to `3` files.

#### Verification

1. The bridge package still works.
2. Its purpose is obvious from the directory itself.

### Batch 4: Frontend Knowledge-Domain Cleanup

#### Goal

Make knowledge-base related frontend code easier to find and maintain.

#### Current friction

Knowledge-base UI logic is likely spread across generic component and view directories, with no dedicated domain area.

#### Planned actions

1. Add `frontend/src/components/knowledge/`.
2. Move knowledge-base specific UI fragments into that directory.
3. Reduce view-level overload by extracting reusable knowledge components.
4. Optionally regroup knowledge-related API modules later if the current API structure is still too flat.

#### Expected impact

Roughly `8` to `18` files.

#### Verification

1. Frontend builds successfully.
2. Imports resolve after file moves.
3. Knowledge-base pages still render correctly.

### Batch 5: Generated Artifact Cleanup

#### Goal

Reduce non-source noise during repository navigation.

#### Planned actions

1. Remove visible `__pycache__` directories from the worktree.
2. Confirm they are ignored.
3. Review whether root-level generated files such as logs should remain where they are.

#### Expected impact

Potentially many generated files, but low semantic risk.

#### Verification

1. No tracked cache directories remain.
2. Ignore rules are sufficient to prevent reintroduction.

## Risk Assessment

### Low risk

- document moves with reference updates
- adding READMEs and structure guides
- generated artifact cleanup

### Medium risk

- frontend component moves
- backend utility regrouping with import updates

### Highest risk

- moving compatibility surfaces that may still be imported by older paths
- changing package layout without focused import verification

These changes should always be accompanied by compatibility checks.

## Delivery Standard

Each batch should satisfy all of the following:

1. The structure is more intuitive than before.
2. Compatibility behavior is preserved or replaced by a thin shim.
3. Documentation is updated together with structural changes.
4. Verification is run for the changed area.

## Recommended Commit Split

1. `docs(repo): unify documentation entrypoints and navigation`
2. `refactor(shared): clarify utility and compatibility structure`
3. `docs(backend): explain source-root compatibility bridge`
4. `refactor(frontend): introduce knowledge domain components`
5. `chore(repo): remove generated structure noise`

## Expected End State

After this implementation plan is completed, the repository should have:

- clearer documentation entrypoints
- a more explicit distinction between implementation and compatibility layers
- better backend utility discoverability
- a clearer frontend knowledge-domain structure
- less navigation noise for future contributors
