# 知识库项目重组方案

## 目标

本次重组的目标不是单纯调整目录外观，而是把知识库相关代码的组织方式，从“按历史实现堆叠”调整为“按能力域分组”。

重组遵循三条原则：

1. 业务代码保留在 `features/knowledge_space`
2. 通用处理能力下沉到 `shared`
3. 外部引擎或大型适配层单独收敛到 `integrations`

---

## 当前主要问题

### 1. `shared/utils` 已成为知识库工具混合区

当前 `backend/src/shared/utils/` 同时放置了：

- 文档解析
- 文本切分
- 媒体处理
- VLM 工具
- 通用工具

这导致知识库处理链路的入口不直观，同类工具也没有按能力聚合。

### 2. `deepdoc` 内部职责混杂

当前 `backend/src/shared/utils/deepdoc/` 同时承载：

- 运行时编排
- 解析器实现
- 视觉解析能力
- 服务端接口
- 健康检查与依赖诊断
- 上游兼容与镜像映射

目录内部虽然功能完整，但职责边界不清晰，尤其 `parser.py`、`runtime_parser.py`、`parser/` 之间容易混淆。

### 3. 解析器命名与分布不统一

DeepDoc 解析器同时存在：

- `ragflow_xxx_parser.py`
- `parser/xxx_parser.py`

这说明现在既保留了适配层，又保留了上游镜像层，但没有通过目录结构明确区分两类实现。

### 4. 文本切分被埋在 `document_readers/splitters`

切分策略本质上是独立能力，但当前放在 reader 子目录下，容易让人误以为 splitter 只是 reader 的附属能力，而不是知识库解析配置中的独立模块。

### 5. 知识库特性模块还有少量文件位置不直观

例如：

- `knowledge_space_prompts.py` 直接位于 feature 根目录

这类文件更适合迁移到 `prompts/` 子目录。

### 6. 文档目录过于平铺

`docs/` 目前同时放置：

- DeepDoc 文档
- 知识库配置设计
- handover 文档
- 重构计划文档

继续增长后会降低可维护性。

---

## 重组总体方向

建议将知识库相关代码按以下三个层次组织：

### 1. 业务层

保留在：

`backend/src/features/knowledge_space/`

负责：

- API
- 业务服务
- 模型
- 仓储
- schema
- 提示词

### 2. 通用处理层

收敛到：

`backend/src/shared/`

负责：

- 文档读取
- 文本切分
- 媒体处理
- 通用多模态能力

### 3. 引擎适配层

收敛到：

`backend/src/shared/integrations/`

负责：

- DeepDoc
- 远程解析器适配
- 视觉解析引擎
- 诊断工具

---

## 目标目录结构

建议的后端目标目录：

```text
backend/src/
  features/
    knowledge_space/
      api/
      models/
      repository/
      schemas/
      services/
      prompts/
  shared/
    document_processing/
      readers/
      splitters/
      pipeline/
      validation/
    media_processing/
      image/
      video/
      audio/
      vlm/
    integrations/
      deepdoc/
        core/
        parsers/
        vision/
        server/
        diagnostics/
        compat/
```

---

## 一期方案：低风险归类

一期只做低风险重组，不改变核心运行逻辑，重点是提升可读性和后续迁移基础。

### 一期目标

1. 让目录语义更直观
2. 保留旧 import 兼容
3. 不大规模打断现有测试

### 一期建议动作

#### 1. 调整知识库 prompts 放置位置

将：

- `backend/src/features/knowledge_space/knowledge_space_prompts.py`

迁移到：

- `backend/src/features/knowledge_space/prompts/`

#### 2. 引入 `document_processing`

新建：

```text
backend/src/shared/document_processing/
  readers/
  splitters/
  pipeline/
  validation/
```

迁移方向：

- `document_readers/base_reader.py` -> `document_processing/readers/`
- `document_readers/pdf_reader.py` -> `document_processing/readers/`
- `document_readers/docx_reader.py` -> `document_processing/readers/`
- `document_readers/html_reader.py` -> `document_processing/readers/`
- `document_readers/md_reader.py` -> `document_processing/readers/`
- `document_readers/txt_reader.py` -> `document_processing/readers/`
- `document_readers/document_loader.py` -> `document_processing/pipeline/`
- `document_readers/splitters/*` -> `document_processing/splitters/`
- `file_validator.py` -> `document_processing/validation/`

#### 3. 引入 `media_processing`

新建：

```text
backend/src/shared/media_processing/
  image/
  video/
  audio/
  vlm/
```

迁移方向：

- `media_utils.py` 中的视频与音频工具按能力拆分
- `vlm_utils.py` 迁移到 `media_processing/vlm/`

#### 4. 文档分组

建议将 `docs/` 重组为：

```text
docs/
  knowledge-space/
  deepdoc/
  handover/
  plans/
```

### 一期兼容策略

一期必须保留兼容导出：

1. 旧文件保留为薄封装
2. 旧 import 继续可用
3. `__init__.py` 提供 re-export
4. 测试可以逐步迁移，不要求一次全部更新

---

## 二期方案：DeepDoc 按职责拆分

二期处理当前最混乱的 `deepdoc` 结构。

### 二期目标结构

```text
backend/src/shared/integrations/deepdoc/
  core/
    engine.py
    factory.py
    runtime_parser.py
    models.py
    capabilities.py
  parsers/
    pdf.py
    docx.py
    epub.py
    excel.py
    ppt.py
    html.py
    markdown.py
    json.py
    txt.py
    figure.py
    remote/
      docling.py
      mineru.py
      opendataloader.py
      paddleocr.py
      somark.py
      tcadp.py
  vision/
  server/
  diagnostics/
    doctor.py
    dependencies.py
  compat/
    compat.py
    upstream.py
    constants.py
```

### 二期建议动作

#### 1. 统一 parser 命名

不再长期混用：

- `ragflow_xxx_parser.py`
- `parser/xxx_parser.py`

建议按职责统一为：

- 本地解析器
- 远程解析器适配器

#### 2. 拆开 core 与 parser

以下文件应视为编排层：

- `engine.py`
- `factory.py`
- `runtime_parser.py`
- `models.py`

它们应进入 `core/`，不要继续与具体 parser 平铺。

#### 3. 拆开 parser 与 server

以下内容应独立：

- 解析器实现
- FastAPI 服务端
- 依赖下载脚本
- adapter
- endpoint

不要继续全部放在同一级目录。

#### 4. 诊断类工具独立

以下内容建议归到 `diagnostics/`：

- `doctor.py`
- `dependencies.py`

#### 5. 兼容与上游映射独立

以下内容建议归到 `compat/`：

- `compat.py`
- `upstream.py`
- `constants.py`

### 二期命名建议

以下命名建议做明确化：

1. `parser.py` 建议废弃或重命名
2. `runtime_parser.py` 可考虑改为 `dispatcher.py` 或 `orchestrator.py`
3. `parser/` 目录保留，但只承载解析实现，不混其他职责

---

## 三期方案：彻底收口

三期用于清理历史兼容层，把结构真正收敛完成。

### 三期建议动作

1. 清理 `shared/utils` 中已迁出的知识库相关残留
2. 审查并逐步移除 `backend/src/src/...` 兼容 shim
3. 将测试 import 批量切换到新路径
4. 清理 `__init__.py` 中过多的历史 re-export
5. 补充正式的知识库架构导航文档

### 三期完成后的理想链路

```text
features/knowledge_space/services
  -> shared/document_processing
  -> shared/media_processing
  -> shared/integrations/deepdoc
```

---

## 前端建议

前端当前结构整体问题不大，不建议作为第一阶段重点，但可以逐步做两类优化。

### 1. 知识库配置组件下沉

建议增加：

```text
frontend/src/components/knowledge/
```

用于放置：

- 知识库配置表单片段
- 解析配置组件
- 分块策略组件
- 多模态配置组件

### 2. API 按知识库域聚合

建议逐步把以下 API 从“平铺文件”演进成“知识库域内聚”：

- `api/knowledge/knowledgeBase.ts`
- `api/knowledge/document.ts`
- `api/knowledge/search.ts`
- `api/knowledge/evaluation.ts`

前端不用和后端目录完全镜像，但命名要与后端能力域一致。

---

## 实施顺序

建议按照以下顺序推进：

1. 先固化重组文档
2. 一期目录归类与兼容导出
3. 跑现有测试
4. 二期 DeepDoc 按职责拆分
5. 批量迁移 import
6. 清理兼容层
7. 补架构文档和导航说明

---

## 风险点

### 1. DeepDoc import 改动面大

DeepDoc 测试覆盖较广，二期迁移时 import churn 会很多。

### 2. `backend/src/src/...` 不能直接删除

这一层大概率是兼容导入用途，必须先确认实际引用与打包入口。

### 3. `document_loader.py` 责任过重

当前它同时承担 loader、processor、deepdoc 编排、splitter 关联，迁移时要注意避免循环依赖。

### 4. 一次性大迁移不利于回归

建议分阶段、小步提交，而不是一次性大规模移动。

---

## 推荐拆分为三个 PR

建议最终以三个 PR 推进：

1. `refactor(knowledge): reorganize docs and prompts with compatibility exports`
2. `refactor(knowledge): extract document and media processing modules`
3. `refactor(deepdoc): normalize parser package and runtime layout`

---

## 结论

本项目知识库部分当前最需要整理的不是业务层，而是工具层和引擎适配层。

优先级建议如下：

1. 先整理 `shared/utils` 的知识库相关内容
2. 再拆 `deepdoc`
3. 最后收口兼容层与历史文档

这样可以在不打断现有能力的前提下，逐步把项目结构调整为更清晰、更可维护、也更适合后续扩展多模态解析的形态。
