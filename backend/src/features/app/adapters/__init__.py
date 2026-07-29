"""app（简历挖掘）宿主适配器层。

把宿主侧能力（PromptManager、ModelConfigService 等）桥接到 resume 引擎端口
（``PromptProvider`` / ``FallbackLLMProvider``），供 resume 引擎经依赖注入消费。
resume 引擎（resume_parser/analyzer/probing）不再直接 import 宿主 prompt 注册表 /
结构化日志 / user.services，切断 resume 引擎 -> 宿主导入边
（批次 6 抽 ``novamind-resume-engine`` 前提）。
"""