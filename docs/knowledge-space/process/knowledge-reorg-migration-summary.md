# Knowledge Reorganization Migration Summary

## Scope

This note summarizes the repository moves already landed for the knowledge-base reorganization work.

## Frontend API

Moved from flat API files to domain grouping:

- `frontend/src/api/knowledgeBase.ts` -> `frontend/src/api/knowledge/knowledgeBase.ts`
- `frontend/src/api/document.ts` -> `frontend/src/api/knowledge/document.ts`
- `frontend/src/api/search.ts` -> `frontend/src/api/knowledge/search.ts`
- `frontend/src/api/evaluation.ts` -> `frontend/src/api/knowledge/evaluation.ts`

Domain export entry:

- `frontend/src/api/knowledge/index.ts`

## Frontend Components

Moved knowledge-specific UI out of generic locations:

- `frontend/src/components/common/KbSidebar.vue` -> `frontend/src/components/knowledge/KbSidebar.vue`
- `frontend/src/utils/document.ts` -> `frontend/src/components/knowledge/document.ts`

New domain component area:

- `frontend/src/components/knowledge/`

Key files:

- `KbSidebar.vue`
- `KbTextParsingSection.vue`
- `KbMultimodalParsingSection.vue`
- `KbSplittingSection.vue`
- `KbQuestionGenerationSection.vue`
- `kbConfig.ts`
- `navigation.ts`
- `index.ts`

## Documentation

Moved or formalized document locations:

- `docs/FRONTEND-MULTIMODAL-DESIGN.md` -> `docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md`
- `docs/IMPROVEMENT-enterprise-kb.md` -> `docs/knowledge-space/process/IMPROVEMENT-enterprise-kb.md`
- `项目结构导航.md` -> `docs/project-structure-navigation.md`

## Updated Consumers

The knowledge-base views now consume the regrouped domain entrypoints rather than the deleted flat files.

Representative updated areas:

- `frontend/src/views/space/DocumentView.vue`
- `frontend/src/views/space/DocumentDetailView.vue`
- `frontend/src/views/space/DocumentTaskBatchView.vue`
- `frontend/src/views/space/KbConfigView.vue`
- `frontend/src/views/space/KbEvaluationView.vue`
- `frontend/src/views/space/SearchView.vue`
- `frontend/src/views/space/KnowledgeBaseView.vue`
- `frontend/src/views/space/SpaceListView.vue`
- `frontend/src/views/space/SpaceSettingsView.vue`
- `frontend/src/views/chat/ChatView.vue`
- `frontend/src/components/chat/SessionConfigDialog.vue`

## Remaining Follow-up

This migration summary does not claim the whole frontend is type-clean.

Remaining work is mainly:

- historical text-encoding cleanup in a few legacy files
- unrelated TypeScript issues in chat, agent, research, resume, and notification modules
- final git staging/commit of moved and newly added files

