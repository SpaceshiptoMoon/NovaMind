# Source-Root Compatibility Bridge

## Purpose

`backend/src/src/` exists only as a compatibility bridge for source-root style imports in installed or packaged environments.

It allows imports such as:

- `src.features.*`
- `src.shared.*`
- `src.shared.utils.deepdoc`

to continue resolving even when this compatibility package is imported first.

## What This Directory Is

This directory is:

- a bridge package
- intentionally thin
- not the implementation home for application logic

## What Should Live Here

Only minimal compatibility glue should live here, for example:

- package path bridging
- thin module forwarding
- import-preserving shims

## What Should Not Live Here

Do not add:

- new feature logic
- new service implementations
- new domain models
- new utility implementations

Those should live under the real source tree such as:

- `backend/src/features/`
- `backend/src/shared/`
- `backend/src/core/`

## Current Bridge Shape

The current bridge mainly covers:

- `src`
- `src.shared`
- `src.shared.utils`
- `src.shared.utils.deepdoc`

This is enough to preserve older import expectations while keeping the real implementation under `backend/src/`.

## Maintenance Rule

If you need to touch this directory, keep changes as small as possible and verify that the corresponding real package remains the implementation source of truth.
