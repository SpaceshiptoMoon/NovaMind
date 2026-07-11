# 全模态前端设计需求

> 后端"全模态转文本"已完成，本文档列出前端需要适配的所有新场景、用途和对应接口。

---

## 一、空间创建/配置 —— 模态多选

**场景**: 创建空间或修改空间配置时，选择该空间支持的模态类型。

**接口**: `POST/PATCH /api/v1/spaces/{id}/config`

**数据结构变化**:
```diff
// SpaceConfig.space_type
- "text" | "multimodal"                 // 旧: 单选字符串
+ ["text", "image", "video", "audio"]   // 新: 多选列表 (至少选一个)
```

**前端要做**:
- 空间创建页 / 空间设置页：将原来的单选（文本 / 多模态）改为多选 checkbox
  - `text` → 文本文档 (pdf/docx/txt/md/csv/xlsx/pptx/html/json)
  - `image` → 图片 (jpg/png/gif/webp)
  - `video` → 视频 (mp4/mov/avi/mkv/webm)
  - `audio` → 音频 (mp3/wav/flac/aac/ogg/m4a)
- 选中的模态决定上传时的文件类型白名单
- 空间详情页：展示当前空间支持的模态标签

---

## 二、知识库解析配置 —— 视频/音频参数

**场景**: 在知识库配置向导中，新增视频和音频的解析参数设置。

**接口**: `GET/PATCH /api/v1/spaces/{id}/knowledge-bases/{kb_id}/config`

**新增字段** (`ParsingConfig`):
```json
{
  "parsing": {
    // ... 原有字段 ...
    "video": {
      "frame_interval": 5.0,    // 抽帧间隔(秒), 1-60, 默认5
      "max_frames": 60           // 最多抽帧数, 1-200, 默认60
    },
    "audio": {
      "asr_model": "whisper-1",             // ASR模型名
      "chunk_split_strategy": "sentence",   // "sentence" | "fixed"
      "chunk_size": 1000                    // 仅 fixed 模式, 100-4000
    }
  }
}
```

**前端要做**:
- KB 配置页 (KbConfigView.vue)：当空间包含 `video` 模态时，显示视频解析区块
  - 帧间隔滑块 (1-60s)
  - 最大帧数输入 (1-200)
- 当空间包含 `audio` 模态时，显示音频解析区块
  - ASR 模型选择（从用户可用模型列表过滤）
  - 切片策略切换（句子 / 固定大小），固定大小时显示字符数输入框

---

## 三、文档上传 —— 新文件类型 + 大小限制

**场景**: 上传视频/音频文件，支持更大的文件体积。

**接口**: `POST /api/v1/spaces/{id}/knowledge-bases/{kb_id}/documents`

**变化**:
| 项 | 旧 | 新 |
|------|------|------|
| 允许格式 | 12 文本 + 5 图片 | + 5 视频 + 6 音频 |
| 最大体积 | 固定 100MB | 按模态: 文本100MB / 图片100MB / 视频500MB / 音频200MB |
| 校验 | text空间拒图, multimodal空间拒文 | 根据 space_type 合集自动判断 |

**前端要做**:
- 上传对话框的文件类型过滤：根据当前空间的 `space_type` 动态设置 `accept`
- 文件大小提示：视频显示 500MB 上限，音频 200MB，其余 100MB
- 上传前客户端校验：超过上限的文件在选中时就提示，不发起请求
- 错误提示：后端返回 `DocumentInvalidTypeError` (400) 或 `DocumentSizeExceededError` (400) 时展示友好信息

---

## 四、文档列表/详情 —— 新字段展示

**场景**: 文档列表和详情页展示视频/音频专属的处理统计。

**接口**: `GET /api/v1/spaces/{id}/knowledge-bases/{kb_id}/documents`  
`GET /api/v1/spaces/{id}/knowledge-bases/{kb_id}/documents/{doc_id}`

**DocumentResponse 新增信息** (在 `doc_metadata` 中):
```json
{
  "doc_metadata": {
    "chunk_count": 3,
    "chunk_type": "video",       // text | image | video | audio
    "frame_count": 18,           // 仅 video
    "segment_count": 35,         // 仅 audio
    "vlm_description": true,     // 仅 image (VLM开启时)
    "description_length": 500    // 仅 image (VLM开启时)
  }
}
```

**ChunkResponse 新增字段**:
```json
{
  "chunk_type": "video",        // text | image | video | audio
  "media_url": "https://...",   // 媒体文件预签名URL (图片/视频/音频)
  "image_url": "https://...",   // 已废弃，但仍返回 (向后兼容)
  "metadata": {
    "start_time": 0.0,          // 音视频: 片段起始时间(秒)
    "end_time": 15.0,           // 音视频: 片段结束时间(秒)
    "frame_paths": [            // 仅 video: 该chunk对应的帧图片MinIO路径
      "kb/3/abc.mp4_frames/frame_0000.jpg",
      "kb/3/abc.mp4_frames/frame_0001.jpg"
    ]
  }
}
```

**前端要做**:
- 文档列表：文件类型列显示视频/音频的专属图标 (mp4→🎬, mp3→🎵)
- 文档列表：处理状态列对视频/音频显示额外信息 (帧数/分段数)
- 文档详情页 / 分块列表：
  - `chunk_type = "video"` 时：显示视频图标，`metadata.frame_paths` 转为预览缩略图
  - `chunk_type = "audio"` 时：显示音频图标，`metadata.start_time/end_time` 显示时间范围
  - `media_url` 优先于 `image_url`（前端统一用 `media_url`）
- 帧缩略图获取：`frame_paths` 是 MinIO object_name，需要通过 API 转为可访问 URL
  - 方式1：调用 `GET /documents/{id}/image?path={frame_path}` 或新增帧预览端点
  - 方式2：前端直传 frame_path 到后端生成 presigned URL

---

## 五、搜索结果展示 —— 多媒体结果渲染

**场景**: 搜索命中的 chunk 可能是视频描述或音频转写文本，需要区分展示。

**接口**: `POST /api/v1/spaces/{id}/knowledge-bases/{kb_id}/search`

**SearchResult 新增字段**:
```json
{
  "chunk_type": "video",          // text | image | video | audio
  "media_url": "https://...",     // 媒体文件 presigned URL
  "image_url": "https://...",     // 已废弃 (仍返回)
  "metadata": {
    "start_time": 0.0,
    "end_time": 15.0,
    "frame_paths": ["kb/3/abc.mp4_frames/frame_0000.jpg", ...]
  },
  "file_info": {
    "filename": "demo.mp4",
    "file_type": "mp4"
  }
}
```

**前端要做**:
- 搜索卡片根据 `chunk_type` 显示不同的类型标签和图标
  - `text` → 📄 文档
  - `image` → 🖼 图片
  - `video` → 🎬 视频
  - `audio` → 🎵 音频
- `chunk_type = "video"`：
  - 显示 content（VLM 描述文本）
  - 展示帧缩略图（从 `metadata.frame_paths` 转 URL）
  - `metadata.start_time` → 可点击跳转到视频对应时间点
  - `media_url` → 点击可预览完整视频
- `chunk_type = "audio"`：
  - 显示 content（ASR 转写文本）
  - `metadata.start_time/end_time` → 显示时间范围，可点击跳转播放
  - `media_url` → 点击可播放音频片段

---

## 六、检索模式选择 —— 图片检索条件显示

**场景**: 知识库的可用检索模式取决于空间模态，包含 `image` 模态的空间可额外用图片检索模式。

**接口**: `GET /api/v1/spaces/{id}/knowledge-bases/{kb_id}/search/modes`

**SearchModesResponse 新增**:
```json
// 包含 image 模态的空间额外返回:
{
  "modes": [
    {"mode": "text_to_image", "label": "以文搜图", "description": "..."},
    {"mode": "image_vector", "label": "以图搜图", "description": "..."}
  ]
}
```

**前端要做**:
- 检索模式下拉：根据 `GET /search/modes` 返回的模式列表动态渲染，而非前端硬编码
- 选择 `text_to_image` / `image_vector` 时使用 `POST /search/multimodal-search` 端点

---

## 七、多模态检索 —— 以图搜图/以文搜图

**场景**: 在包含 `image` 模态的空间中，用图片或文本搜索图片。

**接口**: `POST /api/v1/spaces/{id}/knowledge-bases/{kb_id}/search/multimodal-search`

**MultimodalSearchRequest**:

| 模式 | 必填参数 |
|------|---------|
| `text_to_image` | `query` (文本) |
| `image_to_image` | `image_base64` (Base64图片) |

```json
// 以文搜图
{ "query": "红色汽车", "search_mode": "text_to_image", "top_k": 10 }

// 以图搜图
{ "image_base64": "iVBORw0KGgo...", "search_mode": "image_to_image", "top_k": 10 }
```

**前端要做**:
- 搜索框旁增加图片上传按钮（仅在包含 `image` 模态的空间/知识库中显示）
- `text_to_image`：和普通文本搜索类似，但走 multimodal-search 端点
- `image_to_image`：拖拽/粘贴/上传图片 → 前端转 base64 → 发送请求 → 展示相似图片结果
- 搜索结果展示和普通搜索一致（`SearchResult` 结构相同）

---

## 八、API 变更汇总

| 接口 | 方法 | 变化 |
|------|------|------|
| `/spaces` | POST | `config.space_type` 改为 `List[str]`，多选 |
| `/spaces/{id}/config` | GET/PATCH | 同上 |
| `/spaces/{id}/knowledge-bases` | POST | `config.parsing` 新增 `video`/`audio` 子配置 |
| `/spaces/{id}/knowledge-bases/{kb_id}/config` | GET/PATCH | 同上 |
| `/spaces/{id}/knowledge-bases/{kb_id}/documents` | POST | 允许 10 种新格式，体积上限按模态区分 |
| `/spaces/{id}/knowledge-bases/{kb_id}/documents` | GET | 返回 `doc_metadata.chunk_type`, `doc_metadata.frame_count` 等 |
| `/spaces/{id}/knowledge-bases/{kb_id}/documents/{id}` | GET | `ChunkResponse` 新增 `media_url`, `chunk_type` 扩展, `metadata` 新字段 |
| `/spaces/{id}/knowledge-bases/{kb_id}/documents/{id}/chunks` | GET | 同上 |
| `/spaces/{id}/knowledge-bases/{kb_id}/search` | POST | `SearchResult` 新增 `media_url`, `chunk_type` 扩展, `metadata.frame_paths` |
| `/spaces/{id}/knowledge-bases/{kb_id}/search/modes` | GET | 包含 `image` 模态时额外返回 `text_to_image`/`image_vector` |
| `/spaces/{id}/knowledge-bases/{kb_id}/search/multimodal-search` | POST | 空间类型校验放宽为包含 `image` 即可 |

---

## 九、建议实现优先级

| 优先级 | 功能 | 理由 |
|--------|------|------|
| P0 | 空间创建 — 模态多选 | 不然后端无法创建新模态空间 |
| P0 | 文档上传 — 新格式 + 大小提示 | 用户需要上传视频/音频 |
| P1 | 文档列表 — 文件类型图标 + 处理状态 | 上传后看不到状态会困惑 |
| P1 | 搜索结果 — chunk_type 标签 + 图标 | 搜索结果混在一起分不清 |
| P2 | KB 配置 — 视频/音频解析参数 | 默认值已可用，调优时才需要 |
| P2 | 帧缩略图 — frame_paths → URL | 搜索结果体验提升，但文本已够用 |
| P2 | 多模态检索 — 以图搜图入口 | 仅含 image 模态空间需要 |
| P3 | 视频/音频播放器 | media_url 已返回，可直接用原生 player |
