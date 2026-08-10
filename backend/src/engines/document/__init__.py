"""文档处理引擎族（engines/document）。

承载知识库文档处理的可复用纯逻辑组件，供任意 feature 装配导入：

- ``pipeline/``：文档解析管道（DocumentLoader / DocumentProcessor / DocumentRegistry）
- ``splitters/``：文本切块器（recursive / semantic / fixed_size / markdown）
- ``converters/``：文档格式转换器
- ``media/``：多模态处理（audio / video / vlm；image 为占位）
- ``integrations/deepdoc/``：DeepDoc PDF 布局解析器（vendored，自包含）

本子包是 ``features → engines → shared`` 分层中的 engines 层：纯逻辑，不得
import ``novamind.features.*`` / ``novamind.setting.*`` / ORM 模型 / ``core.database``
ORM 会话；外部资源（模型客户端、存储）经端口在 feature 装配点注入。与
``shared/document/readers/``（跨 feature 通用文件格式读取器）的边界：
readers 负责通用格式读取，本子包负责知识库领域的解析编排/切块/多模态/布局解析。
"""