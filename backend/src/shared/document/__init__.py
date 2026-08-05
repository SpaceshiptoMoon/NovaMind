"""跨 feature 公用的文档解析与校验能力（readers / validation）。

知识库专属的解析流水线（pipeline/splitters/converters/media/deepdoc）归
``features/knowledge_space/``；仅 readers（多 feature 跨用）与 validation
（qa/knowledge_space 跨用）留此中立层。
"""