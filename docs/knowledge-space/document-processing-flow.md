# Document Processing Flow

## Overview

```mermaid
flowchart TD
  A[Frontend upload] --> B[API upload_document]
  B --> C{File type valid?}
  C -- No --> C1[Reject at API layer]
  C -- Yes --> D[Save to MinIO + create Document]
  D --> E{Need process now?}
  E -- No --> E1[Uploaded only]
  E -- Yes --> F[Create document_tasks batch]
  F --> G[Create document_task_items task item]
  G --> H[Enqueue arq job]
  H --> I[Worker process_document_task]
  I --> J{File modality}
  J -- text --> K[Document pipeline]
  J -- image --> L[Image OCR / VLM]
  J -- video --> M[Normalize video -> extract frames]
  J -- audio --> N[ASR / segmentation]
  K --> O{Success?}
  L --> O
  M --> O
  N --> O
  O -- Yes --> P[Mark COMPLETED]
  O -- No --> Q{Retryable?}
  Q -- Yes --> R[Auto retry until max_tries]
  Q -- No --> S[Mark FAILED]
  R --> I
  S --> T[Frontend shows failed task]
  P --> U[Frontend shows completed task]
```

## Key Tables

- `document_tasks`: batch header
- `document_task_items`: real execution items
- `documents`: file metadata only

## Retry Rule

- Auto retry happens inside the worker
- Manual retry creates a new batch and a new task item
- Deterministic validation errors should be rejected before entering worker
