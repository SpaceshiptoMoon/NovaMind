# Agent Handover - 2026-07-09

## Context

This repository went through a substantial refactor around the knowledge-space document processing pipeline, task model split, and frontend task list UX.

The user explicitly said:

- the database was deleted and can be rebuilt from scratch
- ORM models can be changed freely
- avoid SQLAlchemy relationship-based coupling because it has been causing mapper/init issues

This file records what was changed, what is already committed, what is still uncommitted, what broke during startup, and what the next agent should watch carefully.

## Commits Already Created

Two commits were created successfully:

1. `ea31b8b`
   `feat(knowledge): split document tasks into parent tasks and task items`

2. `1f50ff6`
   `feat: apply remaining workspace updates excluding test data`

## High-Level Refactor Already Done

### 1. Task model split

The intended final naming was:

- `document_tasks`
  parent task table
  one row per user action
  examples:
  - process 3 documents
  - reprocess 1 document
  - retry 5 documents

- `document_task_items`
  child item table
  one row per document in that action

Compatibility strategy was used in Python code:

- `DocumentTaskBatch` maps to real table `document_tasks`
- `DocumentTask` maps to real table `document_task_items`
- `document_task_item.py` is an alias module exporting `DocumentTaskItem = DocumentTask`

### 2. API / response semantics

Externally, API responses were moved away from `batch_id` semantics:

- single process/reprocess/retry response:
  - `task_id` = parent task id
  - `task_item_id` = child task item id

- batch process response:
  - `task_id` = parent task id

### 3. Frontend task page

The frontend now uses a standalone task list page:

- route path:
  `/home/spaces/:id/knowledge-bases/:kbId/tasks`

- route name:
  `DocumentTasks`

- page file currently kept as:
  `frontend/src/views/space/DocumentTaskBatchView.vue`

The file name is legacy, but UI semantics were changed to "任务列表".

### 4. Parsed text flow

`DocumentProcessor` logic was changed to conceptually separate:

- load raw/full parsed text first
- upload parsed full text to MinIO
- then split text

This was done to fix the earlier incorrect flow of "split first, then reassemble into full document".

## Important Startup / Runtime Issues Already Encountered

### Issue A: FastAPI Body default assertion

Observed error:

- `AssertionError: Body default value cannot be set in Annotated for 'body'`

Cause:

- FastAPI version in this environment does not accept:
  - `Annotated[Optional[T], Body(default=None)] = None`

Fix applied in:

- `backend/src/features/knowledge_space/api/document_routes.py`

Changed to:

- `body: Optional[DocumentProcessRequest] = Body(default=None)`
- `body: DocumentBatchProcessRequest = Body(...)`

This fix is currently uncommitted.

### Issue B: SQLAlchemy mapper init failure from relationship name resolution

Observed error:

- `expression 'DocumentTaskItem.id.desc()' failed to locate a name`

Cause:

- `DocumentTaskItem` was only a Python alias export
- actual SQLAlchemy mapped class name remained `DocumentTask`
- relationship string resolution failed during mapper init

Initial fix:

- changed `Document.tasks` order_by target from `DocumentTaskItem.id.desc()` to `DocumentTask.id.desc()`

After that, the user requested a stronger direction:

- do not use ORM relationships at all

## Current Uncommitted Changes

At the time this handover file was written, these files are modified and not yet committed:

- `.gitignore`
- `backend/src/features/knowledge_space/api/document_routes.py`
- `backend/src/features/knowledge_space/models/document.py`
- `backend/src/features/knowledge_space/models/document_task.py`
- `backend/src/features/knowledge_space/models/document_task_batch.py`
- `backend/src/features/knowledge_space/models/knowledge_base.py`
- `backend/src/features/knowledge_space/repository/document_repository.py`
- `backend/src/features/knowledge_space/repository/knowledge_base_repository.py`

These uncommitted changes are the post-commit fixes and further simplifications described below.

## ORM "No Relationship" Simplification In Progress

Because the user deleted the DB and explicitly allowed ORM changes, knowledge-space models were further simplified to reduce mapper complexity.

### What has already been changed in working tree

#### `backend/src/features/knowledge_space/models/document.py`

- removed `relationship` import
- removed:
  - `knowledge_base = relationship(...)`
  - `tasks = relationship(...)`

#### `backend/src/features/knowledge_space/models/document_task.py`

- removed `relationship` import
- removed:
  - `document = relationship(...)`
  - `batch = relationship(...)`

- added real column:
  - `pipeline_config = Column(JSON, nullable=True, ...)`

- removed derived property that depended on `self.batch.pipeline_config`

This is important because task items should now carry their own processing config snapshot, instead of pulling it through a parent relationship.

#### `backend/src/features/knowledge_space/models/document_task_batch.py`

- removed `relationship` import
- removed:
  - `tasks = relationship(...)`

#### `backend/src/features/knowledge_space/models/knowledge_base.py`

- removed `relationship` import
- removed:
  - `documents = relationship(...)`

There is still one stale comment mentioning the old bidirectional relation. It is harmless but should ideally be cleaned.

#### `backend/src/features/knowledge_space/repository/knowledge_base_repository.py`

- removed `selectinload` import
- removed the `include_documents` eager-load branch using `selectinload(KnowledgeBase.documents)`

#### `backend/src/features/knowledge_space/repository/document_repository.py`

- removed unused `selectinload` import

### Why this matters

The goal is:

- no mapper graph dependencies between knowledge-space models
- no string-based relationship target resolution
- easier boot after DB reset
- easier independent schema evolution

## Validation Already Performed

These checks were run successfully after the no-relationship simplification:

- `python -m py_compile backend/src/features/knowledge_space/models/document.py`
- `python -m py_compile backend/src/features/knowledge_space/models/document_task.py`
- `python -m py_compile backend/src/features/knowledge_space/models/document_task_batch.py`
- `python -m py_compile backend/src/features/knowledge_space/models/knowledge_base.py`
- `python -m py_compile backend/src/features/knowledge_space/repository/knowledge_base_repository.py`
- `python -m py_compile backend/src/features/knowledge_space/repository/document_repository.py`
- `python -m py_compile backend/src/features/knowledge_space/api/document_routes.py`
- `python -m py_compile backend/src/features/knowledge_space/services/document_service.py`
- `python -m py_compile backend/src/features/knowledge_space/services/media_processing.py`
- `python -m py_compile backend/src/shared/mq/__init__.py`

Also verified:

- no remaining active `relationship(...)` usage under
  `backend/src/features/knowledge_space/models`
- no remaining `selectinload(...)` usage in the modified knowledge-space repositories

## Critical Behavioral Detail

### `DocumentTask.pipeline_config`

This is now duplicated onto the task item model itself.

That is deliberate and useful:

- processing should be reproducible per item
- item processing no longer depends on ORM access to parent task
- service code that reads `task.pipeline_config` still works

This is a better fit for the user's current preference than relationship-based parent lookup.

## SQL / Schema Notes

There is already a SQL file in the repo:

- `backend/sql/2026-07-08_add_document_task_batches.sql`

However, the semantic target discussed with the user was:

- parent table = `document_tasks`
- child table = `document_task_items`

Be careful:

- file name still says `task_batches`
- some compatibility names still say `batch`
- Python compatibility classes still intentionally keep `Batch` naming in places

If the DB is recreated from scratch, the next agent should verify:

1. whether this SQL file exactly matches the latest ORM state
2. whether `document_task_items.pipeline_config` now needs to exist in SQL too
3. whether any old `document_tasks` child-table assumptions remain in worker SQL or raw SQL strings

## Likely Next Checks For The Next Agent

If startup still fails after the user's next run, check in this order:

1. raw SQL or worker code still assuming old schema
   - especially `backend/src/shared/mq/worker.py`

2. model/table mismatch
   - especially after adding `pipeline_config` to `document_task_items`

3. repository or service code that expected relationship-backed navigation
   - `task.batch`
   - `kb.documents`
   - `document.tasks`

4. startup initialization paths
   - `backend/src/core/middleware/startup_manager.py`
   - `backend/src/features/user/api/startup.py`

## Git State / Operational Notes

### Safe directory

Git in this environment required:

- `git -c safe.directory=C:/Users/xl/Desktop/backend_project/intelligent ...`

because repository ownership differs from the sandbox user.

### Commands already approved for escalation

The environment has already approved command prefixes for:

- `git -c safe.directory=C:/Users/xl/Desktop/backend_project/intelligent add`
- `git -c safe.directory=C:/Users/xl/Desktop/backend_project/intelligent commit`

### Test data

The user explicitly wanted test data excluded from commits.

`test_data/` was left uncommitted.

## Recommendation To Next Agent

Before doing any more feature work:

1. inspect current uncommitted diff
2. verify ORM models and SQL schema are aligned
3. run backend startup again
4. if startup succeeds, consider committing the current no-relationship cleanup as a separate commit

Suggested commit theme if needed:

- `refactor(knowledge): remove ORM relationships from knowledge-space models`

## Files Most Relevant To Continue From Here

- `backend/src/features/knowledge_space/api/document_routes.py`
- `backend/src/features/knowledge_space/models/document.py`
- `backend/src/features/knowledge_space/models/document_task.py`
- `backend/src/features/knowledge_space/models/document_task_batch.py`
- `backend/src/features/knowledge_space/models/knowledge_base.py`
- `backend/src/features/knowledge_space/repository/document_repository.py`
- `backend/src/features/knowledge_space/repository/knowledge_base_repository.py`
- `backend/src/features/knowledge_space/services/document_service.py`
- `backend/src/features/knowledge_space/services/media_processing.py`
- `backend/src/shared/mq/__init__.py`
- `backend/src/shared/mq/worker.py`
- `backend/sql/2026-07-08_add_document_task_batches.sql`

