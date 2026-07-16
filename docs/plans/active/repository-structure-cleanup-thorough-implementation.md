# Repository Structure Cleanup Thorough Implementation

## Purpose

This document is the formal implementation plan for the repository-wide structure cleanup.

It is intended to guide the next phase of cleanup work with a clear scope, execution order, risks, and verification expectations.

## Why This Exists

The repository has already accumulated useful cleanup work around the knowledge-base domain, but several areas are still not intuitive:

- documentation entrypoints are now better grouped, but not all structure docs are clean and authoritative
- some backend shared utility paths still mix active implementation, compatibility layers, and transitional code
- frontend knowledge-base files have been grouped by domain, but repository-wide discoverability is still uneven
- generated artifacts, compatibility files, and historical leftovers still increase reading cost

This plan focuses on turning the current direction into a complete, maintainable repository organization strategy.

## Cleanup Goals

1. Make the top-level repository structure easier to understand for new contributors.
2. Make documentation entrypoints stable and easy to navigate.
3. Make knowledge-base frontend code clearly grouped by domain.
4. Distinguish backend active utilities from compatibility-oriented paths more explicitly.
5. Reduce repository noise without changing business behavior.

## Guiding Principles

1. Preserve runtime behavior while restructuring files.
2. Prefer domain grouping over purely technical flattening.
3. Keep compatibility shims when direct removal would create unnecessary risk.
4. Update docs together with structural changes.
5. Verify each batch with focused, relevant checks.

## In Scope

- `docs/` navigation and formal design documents
- frontend knowledge-base API and component grouping
- backend shared utility structure clarification
- repository structure navigation and cleanup planning docs
- light cleanup of repository noise when it improves maintainability

## Out Of Scope

- rewriting core knowledge-base business logic
- large-scale backend architecture replacement
- unrelated frontend feature refactors outside this cleanup goal
- mass removal of legacy paths without compatibility review

## Target Repository Direction

### Documentation

`docs/` should become the canonical home for structural guidance, design notes, and cleanup plans.

Recommended stable entrypoints:

```text
docs/
  frontend/
  knowledge-space/
  plans/
  project-structure-navigation.md
```

### Frontend Knowledge Domain

Knowledge-base related frontend code should remain grouped under domain-oriented paths:

```text
frontend/src/api/knowledge/
frontend/src/components/knowledge/
frontend/src/views/space/
```

The goal is to keep knowledge-base APIs, navigation helpers, parsing config UI, and document utilities discoverable in one place.

### Backend Shared Utilities

`backend/src/shared/utils/` should be easier to interpret at a glance.

The longer-term direction is to clearly separate:

- active utilities
- compatibility-oriented adapters
- transitional shims
- system and security helpers

This does not require immediate mass relocation, but it does require explicit classification and documentation.

## Execution Batches

### Batch 1: Documentation Entry Cleanup

Goal:
Make `docs/` the primary home for repository navigation and formal design material.

Actions:

1. Keep frontend design documents under `docs/frontend/`.
2. Keep knowledge-base design and migration documents under `docs/knowledge-space/`.
3. Keep cleanup and refactor plans under `docs/plans/`.
4. Maintain `docs/project-structure-navigation.md` as the canonical repository navigation file.
5. Update references from root-level or legacy paths.

Verification:

1. Main docs open correctly and are readable.
2. Moved document references point to current paths.
3. No important root-level navigation doc remains orphaned.

### Batch 2: Frontend Knowledge-Base Domain Grouping

Goal:
Keep knowledge-base frontend files organized by domain rather than by generic shared folders.

Actions:

1. Group knowledge APIs under `frontend/src/api/knowledge/`.
2. Group knowledge UI helpers and components under `frontend/src/components/knowledge/`.
3. Update consuming views and stores to use the grouped imports.
4. Remove or retire replaced flat files after imports are migrated.

Verification:

1. Knowledge-base views resolve imports from the new grouped paths.
2. No stale imports remain for deleted flat knowledge API files.
3. Knowledge-related views remain type-safe within the scope of their own imports.

### Batch 3: Backend Utility Clarification

Goal:
Make shared backend utilities easier to understand without risky mass movement.

Actions:

1. Add explanatory `README.md` files where paths are easy to misread.
2. Label directories and files as active utility, compatibility layer, or transitional shim.
3. Identify candidates for future regrouping under clearer categories such as compatibility, text processing, security, and system helpers.
4. Avoid moving widely imported modules unless there is a compatibility path.

Verification:

1. Existing imports remain valid.
2. Utility responsibilities are documented.
3. Cleanup does not introduce behavioral changes.

### Batch 4: Repository Noise Reduction

Goal:
Reduce friction caused by scattered historical leftovers.

Actions:

1. Remove replaced files once all imports and references are migrated.
2. Keep migration summaries and commit guidance in `docs/plans/` or `docs/knowledge-space/` as appropriate.
3. Avoid duplicate navigation docs in multiple locations.
4. Document any intentionally preserved legacy file.

Verification:

1. Deleted files have clear replacements.
2. Documentation reflects the new structure.
3. Git diff remains understandable and reviewable.

## Risks

1. Breaking imports by moving paths without updating all consumers.
2. Leaving behind duplicate files that confuse future contributors.
3. Mixing structural cleanup with unrelated feature changes.
4. Treating compatibility files as dead code when they are still used.

## Risk Controls

1. Use small, reviewable batches.
2. Search imports before deleting replaced files.
3. Keep documentation synchronized with moves.
4. Prefer explicit migration summaries when the diff is large.

## Verification Standard

Before calling this cleanup complete, the following should be true:

1. The major repository entrypoints are documented in readable form.
2. Knowledge-base frontend files are grouped under clear domain paths.
3. Replaced knowledge-base frontend imports no longer point to deleted flat files.
4. Backend shared utility responsibilities are documented where structure is not self-explanatory.
5. The cleanup diff is in a state that can be reviewed and committed coherently.

## Completion Criteria

This thorough cleanup phase can be considered complete when:

1. the formal docs are readable and stored in their intended locations
2. the knowledge-base frontend grouping is consistent and verified
3. remaining structural risks are documented rather than hidden
4. the git history can record this cleanup as a clear repository-organization change
