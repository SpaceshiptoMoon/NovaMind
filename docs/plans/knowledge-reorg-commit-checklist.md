# Knowledge Reorganization Commit Checklist

## Goal

This checklist captures the files involved in the knowledge-base repository reorganization so the migration can be staged and committed coherently.

## 1. New Directories And Files To Add

### Frontend knowledge API domain

Add:

- `frontend/src/api/knowledge/document.ts`
- `frontend/src/api/knowledge/evaluation.ts`
- `frontend/src/api/knowledge/index.ts`
- `frontend/src/api/knowledge/knowledgeBase.ts`
- `frontend/src/api/knowledge/search.ts`

### Frontend knowledge component domain

Add:

- `frontend/src/components/knowledge/document.ts`
- `frontend/src/components/knowledge/index.ts`
- `frontend/src/components/knowledge/kbConfig.ts`
- `frontend/src/components/knowledge/KbMultimodalParsingSection.vue`
- `frontend/src/components/knowledge/KbQuestionGenerationSection.vue`
- `frontend/src/components/knowledge/KbSidebar.vue`
- `frontend/src/components/knowledge/KbSplittingSection.vue`
- `frontend/src/components/knowledge/KbTextParsingSection.vue`
- `frontend/src/components/knowledge/navigation.ts`

### Documentation and navigation

Add:

- `docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md`
- `docs/knowledge-space/IMPROVEMENT-enterprise-kb.md`
- `docs/knowledge-space/knowledge-reorg-migration-summary.md`
- `docs/plans/repository-structure-cleanup-execution-plan.md`
- `docs/plans/repository-structure-cleanup-implementation.md`
- `docs/plans/repository-structure-cleanup-plan.md`
- `docs/plans/repository-structure-cleanup-thorough-implementation.md`
- `docs/plans/knowledge-reorg-commit-checklist.md`
- `docs/project-structure-navigation.md`

### Backend clarification docs

Add:

- `backend/src/shared/utils/README.md`
- `backend/src/src/README.md`

## 2. Old Files To Remove

Remove:

- `docs/FRONTEND-MULTIMODAL-DESIGN.md`
- `docs/IMPROVEMENT-enterprise-kb.md`
- `frontend/src/api/document.ts`
- `frontend/src/api/evaluation.ts`
- `frontend/src/api/knowledgeBase.ts`
- `frontend/src/api/search.ts`
- `frontend/src/components/common/KbSidebar.vue`
- `frontend/src/utils/document.ts`

## 3. Existing Files Updated To New Structure

### Frontend consumers

Update:

- `frontend/src/components/chat/SessionConfigDialog.vue`
- `frontend/src/stores/space.ts`
- `frontend/src/views/chat/ChatView.vue`
- `frontend/src/views/space/DocumentDetailView.vue`
- `frontend/src/views/space/DocumentTaskBatchView.vue`
- `frontend/src/views/space/DocumentView.vue`
- `frontend/src/views/space/KbConfigView.vue`
- `frontend/src/views/space/KbEvaluationView.vue`
- `frontend/src/views/space/KnowledgeBaseView.vue`
- `frontend/src/views/space/SearchView.vue`
- `frontend/src/views/space/SpaceListView.vue`
- `frontend/src/views/space/SpaceSettingsView.vue`

### Docs synchronized to new locations

Update:

- `docs/knowledge-space/knowledge-reorg-plan.md`
- `docs/knowledge-space/knowledge-reorg-status.md`
- `docs/plans/REFACTOR-qa-rag-pipeline.md`
- `docs/plans/refactoring-plan.md`

## 4. Suggested Staging Order

1. Stage new docs and moved doc replacements.
2. Stage frontend knowledge API domain files.
3. Stage frontend knowledge component domain files.
4. Stage consumer updates in `views/`, `stores/`, and `components/chat/`.
5. Stage removals of the replaced flat files.
6. Stage backend README clarifications.

## 5. Verification Notes

Before commit, re-check:

- no remaining imports from deleted flat knowledge API files
- no remaining imports from `@/utils/document`
- no remaining imports from `@/components/common/KbSidebar`
- `docs/project-structure-navigation.md` points to `frontend/src/api/knowledge/*`
- knowledge pages import from `@/api/knowledge` and `@/components/knowledge`

## 6. Known Non-Blocking Follow-up

Not required to treat this migration as structurally complete:

- remaining historical encoding cleanup in some legacy files
- unrelated frontend TypeScript errors outside the knowledge-base reorganization scope
