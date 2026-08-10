"""文档处理引擎的外部集成（vendored）。

当前承载 ``deepdoc/``：DeepDoc PDF 布局解析器，自包含，内部仅引用自身子模块
与 ``shared.logging``，不依赖 features/setting/ORM。新增外部解析器集成时置于本目录。
"""