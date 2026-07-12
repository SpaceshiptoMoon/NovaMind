# DeepDoc

Canonical implementation home for the backend DeepDoc integration.

This package contains:

- canonical DeepDoc parser and runtime entrypoints
- vendored parser, vision, and server integrations
- diagnostics and runtime capability helpers

CLI entrypoint:

```bash
python -m novamind.shared.knowledge.integrations.deepdoc capabilities
```

This package replaces the removed legacy `shared/utils/deepdoc/` path.
