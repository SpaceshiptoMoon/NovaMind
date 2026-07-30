# Shared Utils Guide

## Purpose

`backend/src/shared/utils/` 保留**宿主专属**的通用工具。批次 6b 已将不依赖宿主 `setting` 的
通用工具迁移到独立引擎包 `novamind-engine-core`（见 `packages/novamind-engine-core/`）。

## What Belongs Here Now

当前仅保留：

- `crypto.py` —— AES-256-GCM 凭证加解密，读取 `setting.yaml_config` 的
  `security.encryption_key`，属宿主安全职责，依赖 `novamind.setting`，故不随引擎包迁出。
- `__init__.py` —— 惰性 `__getattr__` 占位。

## What Moved to novamind-engine-core

以下模块已迁入 `novamind_engine_core.utils`，宿主代码改用 `from novamind_engine_core.utils.<leaf> import ...`：

- `text_utils/`（`TokenCounter` / `TextCompressor`）
- `ansi_strip.py`
- `heartbeat.py`
- `redact.py`
- `time_utils.py`

旧路径 `novamind.shared.utils.<leaf>` 经 `backend/src/novamind/__init__.py` 的 shim 别名仍可
解析到同一模块对象（过渡兼容），但新代码应直接使用 `novamind_engine_core.utils.*`。

## What Does Not Belong Here

知识库解析实现代码不应放在此处，仍归：

- `backend/src/shared/knowledge/document_processing/`
- `backend/src/shared/knowledge/media_processing/`
- `backend/src/shared/knowledge/integrations/deepdoc/`

## Contributor Rule

若工具依赖 `novamind.setting` 或宿主 ORM/feature，留在宿主 `shared/utils/`；
若为纯通用、零宿主依赖的工具，归 `novamind_engine_core.utils`。