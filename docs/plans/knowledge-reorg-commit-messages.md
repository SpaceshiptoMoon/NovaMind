# Knowledge Reorganization Commit Messages

## Recommended Commit Split

If you want to keep the history clean, this reorganization can be committed in the following order.

## Option A: Three commits

1. `docs(repo): reorganize knowledge-base documentation and navigation`
2. `refactor(frontend): group knowledge-base api and components by domain`
3. `chore(repo): add migration summary and cleanup notes`

## Option B: More granular split

1. `docs(repo): move frontend and knowledge-space documents into grouped locations`
2. `docs(repo): add repository structure cleanup implementation documents`
3. `refactor(frontend): move knowledge-base api into api/knowledge`
4. `refactor(frontend): move knowledge components into components/knowledge`
5. `refactor(frontend): update knowledge-base views to new domain entrypoints`
6. `docs(knowledge): add migration summary and commit checklist`
7. `docs(backend): clarify shared utils and src bridge directories`

## If You Want One Commit Only

Use:

- `refactor(repo): reorganize knowledge-base structure and docs`

## Suggested PR Summary

You can describe the change like this:

- regroup knowledge-base frontend api into `frontend/src/api/knowledge/`
- regroup knowledge-base frontend components into `frontend/src/components/knowledge/`
- move knowledge-specific docs into `docs/frontend/` and `docs/knowledge-space/`
- add repository navigation and migration summary documents
- update knowledge-base views and stores to consume the new domain entrypoints

## Known Follow-up To Mention

- frontend still has unrelated historical TypeScript errors outside the knowledge-base reorganization scope
- some legacy files still have text-encoding cleanup opportunities
