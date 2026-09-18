# Repository Structure Cleanup Plan

> Historical note: this is a planning document rather than the source of truth for the current repository layout.
> Some paths below reflect the planning-time structure or unrealized target states.
> Current navigation should follow [`../README.md`](../README.md), [`../project-structure-navigation.md`](../project-structure-navigation.md), and [`../knowledge-space/current/README.md`](../knowledge-space/current/README.md).

## Background

The knowledge-base project reorganization has already clarified the main backend architecture:

- business logic stays in `backend/src/features/knowledge_space/`
- reusable processing stays in `backend/src/shared/document_processing/` and `backend/src/shared/media_processing/`
- DeepDoc implementation stays in `backend/src/shared/integrations/deepdoc/`

At this point, the main remaining structure issues are no longer about the knowledge-base runtime itself, but about repository-wide navigation clarity, compatibility-layer discoverability, and document-entry consistency.

This document records the next cleanup plan for the overall repository structure.

## Cleanup Goals

1. Make the repository easier to navigate for new contributors.
2. Separate implementation directories from compatibility layers more explicitly.
3. Reduce mixed-purpose top-level and utility directories.
4. Unify document entrypoints and reduce flat document sprawl.
5. Keep all cleanup changes low-risk and compatible with the current runtime.

## Current Structure Friction

### 1. `backend/src/shared/utils/` still mixes compatibility layers and real utilities

Current contents include:

- compatibility surfaces:
  - `deepdoc/`
  - `document_readers/`
  - `media_utils.py`
  - `vlm_utils.py`
- real utilities:
- `text_utils/`
  - `ansi_strip.py`
  - `crypto.py`
  - `heartbeat.py`
  - `redact.py`
  - `time_utils.py`

This makes it hard to tell which paths are implementation homes versus legacy import bridges.

### 2. `backend/src/src/...` is structurally valid but visually confusing

The package now only exists for source-root/install compatibility, but the path name itself is unintuitive and easy to misunderstand during navigation.

### 3. `docs/` is partially grouped, but still has root-level loose files

Current grouped document areas include:

- `docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md`
- `docs/knowledge-space/current/`
- `docs/knowledge-space/process/`

These sit beside grouped folders such as:

- `docs/knowledge-space/`
- `docs/deepdoc/`
- `docs/handover/`
- `docs/plans/`

The mixed organization reduces consistency.

### 4. `docs/superpowers/` is semantically isolated from the main document taxonomy

This directory may still be useful, but its relationship to `plans/`, `handover/`, and the main architecture docs is not obvious from the current layout.

### 5. Root-level document entrypoints are split across multiple places

The repository root currently includes:

- `README.md`
- `docs/project-structure-navigation.md`
- `AGENTS.md`
- `CLAUDE.md`

This creates multiple “starting points” for understanding the repo.

### 6. Frontend still lacks a knowledge-base domain component area

Current `frontend/src/components/` includes:

- `chat/`
- `common/`

There is no dedicated `knowledge/` component area yet, so knowledge-base UI pieces are likely to remain scattered.

### 7. Generated cache directories still reduce readability

Multiple `__pycache__` directories remain visible during repository browsing, which makes the structure feel noisier than it is.

## Target Cleanup Direction

### Backend utilities

Clarify `backend/src/shared/utils/` so that compatibility surfaces and real utilities are not visually mixed.

Preferred direction:

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

If moving paths is too disruptive, an acceptable intermediate step is:

1. add `backend/src/shared/utils/README.md`
2. explicitly mark each path as either:
   - compatibility-only
   - implementation utility

### Source-root compatibility package

Keep `backend/src/src/...` only as a bridge package, but make that intent explicit.

Preferred direction:

- retain the current minimal bridge structure
- add a short `README.md` under `backend/src/src/`
- state clearly that no new implementation code should be added there

### Documentation layout

Prefer grouped document ownership over loose files in `docs/`.

Suggested direction:

- move `FRONTEND-MULTIMODAL-DESIGN.md` into:
  - `docs/frontend/`, or
  - `docs/plans/`
- keep knowledge-space design-history materials under:
  - `docs/knowledge-space/process/`, or
  - `docs/plans/`
- evaluate whether `docs/superpowers/` should:
  - stay as an independent document domain, or
  - merge into `docs/plans/` / `docs/handover/`

### Root-level navigation

Reduce duplicate root-level navigation documents where possible.

Suggested direction:

- keep `README.md` as the main human entrypoint
- keep `AGENTS.md` / `CLAUDE.md` as tool- or agent-facing instructions
- formalize `docs/project-structure-navigation.md` as the repository navigation document under `docs/`
- update all references to point at the new location

### Frontend domain organization

Introduce a dedicated knowledge-base component area.

Suggested direction:

```text
frontend/src/components/
  chat/
  common/
  knowledge/
```

Candidate contents for `knowledge/`:

- parsing configuration form sections
- chunking configuration components
- multimodal configuration components
- knowledge-base settings cards

## Proposed Cleanup Phases

### Phase A: Documentation and navigation cleanup

1. regroup loose files under `docs/`
2. decide the role of `docs/superpowers/`
3. formalize `docs/project-structure-navigation.md` as the repository navigation document
4. update all document references

### Phase B: Utility-layer clarity cleanup

1. document the role of `shared/utils/`
2. explicitly mark compatibility-only paths
3. optionally create a `shared/utils/compat/` namespace
4. keep runtime behavior unchanged

### Phase C: Compatibility-bridge explanation cleanup

1. add explanation for `backend/src/src/...`
2. ensure bridge-only intent is documented
3. keep install/import behavior unchanged

### Phase D: Frontend domain cleanup

1. add `frontend/src/components/knowledge/`
2. migrate knowledge-base UI fragments into it
3. optionally regroup knowledge-related API modules later

### Phase E: Generated artifact cleanup

1. clean `__pycache__` from the worktree
2. verify ignore rules
3. avoid treating generated cache directories as source structure

## Execution Principles

1. Do not break compatibility imports unless they are replaced by thin shims.
2. Do not move runtime-critical packages without focused verification.
3. Prefer documentation-first cleanup when a directory still exists for compatibility reasons.
4. Keep cleanup changes small and reviewable.
5. Treat repository navigation clarity as the main outcome, not just fewer directories.

## Suggested Priority

Recommended order of execution:

1. `docs/` regrouping and root document cleanup
2. `shared/utils/` clarification
3. `backend/src/src/...` explanation cleanup
4. frontend `components/knowledge/` introduction
5. generated cache cleanup

## Expected Outcome

After this cleanup, the repository should have:

- a clearer difference between real implementation and compatibility layers
- a more consistent documentation taxonomy
- fewer misleading root-level entrypoints
- a more obvious frontend knowledge-base area
- lower navigation noise for future contributors
