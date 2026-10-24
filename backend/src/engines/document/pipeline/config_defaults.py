"""解析/切分配置默认值单一登记处。

同一参数在不同消费语境下默认值不同是历史现状（扩展性审计批次 1.1 将其
显式命名化，值即现网行为，改动视为契约变更）：

- TEXT 组：文本文档管道（deepdoc 哨兵重切 / default reader / external_ocr
  三分支共用），与 RecursiveCharacterSplitter 构造器默认一致，KB schema
  的权威默认自此处 import。
- MEDIA 组：音视频转写与图片描述文本——转写/描述文本信息密度低于排版
  文档，同等检索召回下可容忍更大块，故 chunk_size 加倍、overlap 减半。
- DIRECT 组：``split_text_items`` / ``load_with_strategy`` / ``split_md_text``
  被裸调（上游未显式传参）时的兜底，兼容旧调用方语义；批次 2 工厂化后
  预期并入构造器默认（届时值为行为变更，需评审）。
- 策略专属组：仅单一策略消费的参数。

改动任何值前先跑 ``tests/engines/document/test_splitter_dispatch_golden.py``
（装配快照逐参比对三条链）。schema 侧引用只允许 import 本模块，不得反向
（engines 层零 features 依赖是解析引擎的既有纪律）。
"""

# ---- TEXT 组：文本文档管道（与 RecursiveCharacterSplitter 构造器默认一致）----
DEFAULT_CHUNK_STRATEGY = "recursive"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_MIN_CHUNK_SIZE = 500
DEFAULT_MAX_CHUNK_SIZE = 2000
DEFAULT_SIMILARITY_THRESHOLD = 0.7
DEFAULT_EMBED_BATCH_SIZE = 20
DEFAULT_WINDOW_SIZE = 2
DEFAULT_PARENT_CHUNK_SIZE = 2000

# ---- MEDIA 组：音视频转写 / 图片描述文本 ----
DEFAULT_MEDIA_CHUNK_SIZE = 2000
DEFAULT_MEDIA_CHUNK_OVERLAP = 50
DEFAULT_MEDIA_MIN_CHUNK_SIZE = 500

# ---- DIRECT 组：切分链被裸调且上游未传参时的兜底（兼容旧调用语义）----
DEFAULT_DIRECT_CHUNK_SIZE = 500
DEFAULT_DIRECT_CHUNK_OVERLAP = 50
DEFAULT_DIRECT_MIN_CHUNK_SIZE = 50
DEFAULT_FIXED_SIZE_OVERLAP = 0

# ---- 策略专属组 ----
DEFAULT_SEMANTIC_MAX_CHUNK_SIZE = 1000
DEFAULT_MARKDOWN_MAX_CHUNK_SIZE = 1000
DEFAULT_MARKDOWN_MIN_CHUNK_SIZE = 50
DEFAULT_HIERARCHICAL_MIN_CHUNK_SIZE = 200
