# DeepDoc Deployment

The canonical DeepDoc deployment package is:

- `novamind.features.knowledge_space.integrations.deepdoc`

Examples:

```bash
python -m novamind.features.knowledge_space.integrations.deepdoc doctor
python -m novamind.features.knowledge_space.integrations.deepdoc prepare --include-text-concat
python -m novamind.features.knowledge_space.integrations.deepdoc serve --host 127.0.0.1 --port 8001
```

This file replaces deployment guidance previously anchored under the legacy
`shared/utils/deepdoc/` path.
