"""文档处理引擎族（engines/document）：解析管道/切块器/格式转换/多模态/DeepDoc 布局解析，供任意 feature 装配导入。
engines 层禁 import features.* / setting.* / ORM 模型 / core.database，外部资源经端口在 feature 装配点注入。
与 shared/document/readers/ 的边界：readers 负责通用格式读取，本子包负责知识库领域的解析编排/切块/多模态/布局解析。
"""
