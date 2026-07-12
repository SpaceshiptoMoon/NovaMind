# 鏂囨。澶勭悊绠￠亾閲嶆瀯璁″垝

> 鏃ユ湡: 2026-07-06 | 鐘舵€? 寰呭闃?
---

## 涓€銆佺洰鏍?
灏嗘枃妗ｅ鐞嗕粠"浠?Document 涓轰腑蹇?閲嶆瀯涓?Document + Task + KB 閰嶇疆"涓夊眰娓呮櫚鑱岃矗锛?
1. **Document** 鈥?绾枃浠跺厓鏁版嵁锛屼笉鍐嶅瓨鍌ㄥ鐞嗙姸鎬?2. **DocumentTask** 鈥?鏂板缓锛岃褰曟瘡娆″鐞嗙殑瀹屾暣鐢熷懡鍛ㄦ湡
3. **KnowledgeBase.config** 鈥?绠￠亾閰嶇疆锛岀粨鏋勫寲鍒囧垎鍙傛暟

---

## 浜屻€佺幇鐘堕棶棰?
### 2.1 鑱岃矗娣蜂贡

Document 琛ㄥ悓鏃舵壙鎷呮枃浠跺厓鏁版嵁 + 澶勭悊鐘舵€佽拷韪袱浠朵簨锛?- `status` (UPLOADED/PROCESSING/COMPLETED/FAILED/DELETED) 娣峰湪涓€璧?- `status_info` 瀛橀敊璇?閲嶈瘯锛屾槸绾换鍔℃暟鎹?- `doc_metadata` 瀛?pipeline 缁撴灉锛坈hunk_count 绛夛級锛屼篃鏄换鍔℃暟鎹?- `processing_started_at` / `processed_at` 鏄换鍔℃椂闂寸嚎

### 2.2 绠￠亾鍒囧垎涓嶇粺涓€

- 鏂囨湰锛歚processor.load_with_strategy()` 涓€姝ュ畬鎴愯В鏋?鍒囧垎锛孧D 鏄?chunks 鎷煎洖鏉ョ殑
- 闊抽锛氱洿鎺ュ `segments` 鍒囧垎锛坄_merge_segments_by_size`锛夛紝涓嶈蛋 MD
- 瑙嗛锛氱洿鎺ュ `descriptions` 鍒囧垎锛坄_aggregate_descriptions`锛夛紝涓嶈蛋 MD
- MD 鏂囨。鍙槸"椤轰究涓婁紶"鐨勫壇浜у搧锛屼笉鏄垏鍒嗙殑杈撳叆婧?
### 2.3 閰嶇疆浣嶇疆涓嶅

- `audio.chunk_split_strategy` 鍜?`audio.chunk_size` 鏀惧湪 `parsing.audio` 閲岋紝浣嗚繖鏄垏鍒嗗弬鏁?- 鍓嶇鎶婇煶棰戝垏鐗囨斁鍦?Step 4锛堝垏鍒嗙瓥鐣ワ級锛屽悗绔湪 `config.parsing.audio` 閲?
### 2.4 浠诲姟杩借釜鍏ㄥ湪 Redis

- Redis `doc_task_tracker` Hash + `doc_cancel:{id}` String锛?澶?1灏忔椂TTL
- 娌℃湁鎸佷箙浠诲姟璁板綍锛屾棤娉曡拷婧?杩欎釜鏂囨。鐢ㄤ粈涔堥厤缃鐞嗙殑"

### 2.5 姝讳唬鐮?
| 浠ｇ爜 | 浣嶇疆 | 鐘舵€?|
|------|------|------|
| `version_info` / `get_version_info` / `get_version_number` | document.py:60,139-145 | 鏃犲閮ㄥ紩鐢?|
| `increment_retry()` | document.py:128-133 | 鏃犲閮ㄨ皟鐢?|
| `update_status()` | document_repository.py:226 | 鏃犲閮ㄨ皟鐢?|
| `get_by_space()` | document_repository.py:131 | 鏃犲閮ㄨ皟鐢?|
| `get_storage_size()` | document_repository.py:350 | 鏃犲閮ㄨ皟鐢?|
| `get_processing_documents()` | document_repository.py:444 | 鏃犲閮ㄨ皟鐢?|
| `get_uploaded_documents()` | document_repository.py:451 | 鏃犲閮ㄨ皟鐢?|
| `search_by_filename()` | document_repository.py:410 | 鏃犲閮ㄨ皟鐢?|

---

## 涓夈€佹柊鏋舵瀯

### 3.1 Document 鈥?绾枃浠跺厓鏁版嵁

```python
class Document(BaseModel):
    __tablename__ = "documents"

    id            # PK
    space_id      # FK 鈫?knowledge_spaces
    kb_id         # FK 鈫?knowledge_bases
    uploader_id   # FK 鈫?users

    filename      # 鍘熷鏂囦欢鍚?    file_type     # pdf/docx/txt/mp3/mp4/...
    file_size     # 瀛楄妭鏁?    file_hash     # SHA-256锛堝幓閲嶏級

    storage       # JSON: {minio_bucket, minio_object_name, parsed_text_object}

    created_at / updated_at / deleted_at

    # 鍏崇郴
    tasks = relationship("DocumentTask", back_populates="document")
```

**鍒犻櫎鐨勫瓧娈碉細**
- ~~status~~ 鈫?DocumentTask.status
- ~~status_info~~ 鈫?DocumentTask.error_message / step_progress
- ~~doc_metadata~~ 鈫?DocumentTask.pipeline_result
- ~~processing_started_at~~ 鈫?DocumentTask.started_at
- ~~processed_at~~ 鈫?DocumentTask.completed_at
- ~~version_info~~ 鈫?鍒犻櫎锛堟棤澶栭儴寮曠敤锛屾浠ｇ爜锛?
**淇濈暀鐨勫瓧娈碉細**
- `storage` 鈥?MinIO 璺緞 + `parsed_text_object`锛堟枃浠剁殑娲剧敓璧勬簮锛?- `deleted_at` 鈥?杞垹闄わ紙鏂囦欢鐢熷懡鍛ㄦ湡锛?- `chunk_count` / `token_count` 鈥?淇濈暀鍦?API 鍝嶅簲涓紙浠?Task 鐨勬渶鏂拌褰曟淳鐢燂級
- `file_hash` 鈥?鏂囦欢鍘婚噸

### 3.2 DocumentTask 鈥?鏂板缓

```python
class DocumentTask(BaseModel):
    __tablename__ = "document_tasks"

    id              # PK
    document_id     # FK 鈫?documents.id
    kb_id           # 鍐椾綑锛屾柟渚挎煡璇?    space_id        # 鍐椾綑锛屾柟渚挎煡璇?
    # 鐘舵€?    status          # PENDING 鈫?PROCESSING 鈫?COMPLETED / FAILED / CANCELLED
    job_id          # arq job ID

    # 閰嶇疆蹇収锛堝鐞嗗紑濮嬫椂 KB.config 鐨勫畬鏁存嫹璐濓級
    pipeline_config  # JSON

    # 閫愭楠よ繘搴?    step_progress    # JSON: {"parsed": "done", "split": "done", ...}

    # 澶勭悊缁撴灉
    pipeline_result  # JSON: {"chunk_count": 42, "segment_count": 120, ...}

    # 閿欒杩借釜
    error_message    # TEXT
    retry_count      # INTEGER

    # 鏃堕棿
    queued_at        # 鍏ラ槦鏃堕棿
    started_at       # 寮€濮嬪鐞?    completed_at     # 瀹屾垚/澶辫触

    created_at / updated_at

    # 鍏崇郴
    document = relationship("Document", back_populates="tasks")
```

**TaskStatus 鏋氫妇锛?*
```python
class TaskStatus(IntEnum):
    PENDING = 0      # 寰呭鐞?    PROCESSING = 1   # 澶勭悊涓?    COMPLETED = 2    # 宸插畬鎴?    FAILED = 3       # 澶辫触
    CANCELLED = 4    # 宸插彇娑?```

**绱㈠紩锛?*
```python
__table_args__ = (
    Index("idx_task_document", "document_id"),
    Index("idx_task_kb_status", "kb_id", "status"),
    Index("idx_task_status", "status"),
)
```

### 3.3 KnowledgeBase.config 鈥?鏈€缁堢粨鏋?
```yaml
config:
  space_type: ["text", "image", "video", "audio"]
  description: ""

  # ===== 瑙ｆ瀽锛氬師濮嬫枃浠?鈫?MD =====
  parsing:
    # 鏂囨湰瑙ｆ瀽
    extract_images: false
    extract_tables: true
    ocr_enabled: false
    preserve_structure: true
    encoding: "utf-8"

    # 鍥剧墖瑙ｆ瀽
    vlm_description_enabled: false

    # 瑙嗛瑙ｆ瀽
    video:
      frame_interval: 5.0       # 鎶藉抚闂撮殧(绉?
      max_frames: 60            # 鏈€澶у抚鏁?
    # 闊抽瑙ｆ瀽锛堝彧淇濈暀ASR锛?    audio:
      asr_model: "whisper-1"   # ASR 妯″瀷鍚?
  # ===== 鍒囧垎锛歁D 鈫?chunks锛堟ā鎬佺粺涓€锛?=====
  splitting:
    strategy: "recursive"      # recursive | fixed_size | markdown | semantic
    chunk_size: 2000
    chunk_overlap: 100
    min_chunk_size: 500        # recursive 涓撳睘
    max_chunk_size: 2000       # markdown/semantic 涓撳睘
    similarity_threshold: 0.7  # semantic 涓撳睘
    batch_size: 20             # semantic 涓撳睘

    # 鍙€夛細闊抽涓撳睘鍒囧垎锛屼笉閰嶅垯璧伴粯璁?    audio:
      strategy: "sentence"     # sentence | fixed
      chunk_size: 1000         # fixed 妯″紡涓嬬殑瀛楃鏁?
    # 鍙€夛細瑙嗛涓撳睘鍒囧垎锛屼笉閰嶅垯璧伴粯璁?    video:
      strategy: "fixed"        # fixed锛堟寜瀛楁暟鑱氬悎锛?      chunk_size: 1500

  # ===== 鐢熸垚锛氬亣璁炬€ч棶棰?=====
  question_generation:
    enabled: false
    max_questions_per_chunk: 5
    prompt_template: null
    llm:
      model: null
      temperature: 0.3
      top_p: 0.9
      max_tokens: 2048
```

### 3.4 鏍稿績鍘熷垯锛歁D 鏄В鏋愪笌鍒囧垎涔嬮棿鐨勫敮涓€妗ユ

涓嶇鍘熷鏂囦欢鏄粈涔堟牸寮忥紙txt / pdf / docx / xlsx / pptx / html / json / jpg / png / mp3 / wav / mp4 / mkv ...锛夛紝**瑙ｆ瀽闃舵鐨勫敮涓€浜х墿鏄竴浠?Markdown 鏂囨。**锛岃繖浠?MD 闅忓悗涓婁紶鍒?MinIO锛屽啀琚垏鍒嗗櫒璇诲彇骞跺垏鍒嗕负 chunks銆?
```
瑙ｆ瀽锛堟ā鎬佺浉鍏筹級              鍒囧垎锛堟ā鎬佹棤鍏筹級
鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€              鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  txt/pdf/docx/xlsx/...  鈹€鈹€鈫? full_text.md  鈹€鈹€鈫?splitter 鈹€鈹€鈫?chunks
  mp3/wav/flac/...       鈹€鈹€鈫? transcript.md 鈹€鈹€鈫?splitter 鈹€鈹€鈫?chunks
  mp4/mov/avi/...        鈹€鈹€鈫? descriptions.md 鈹€鈹€鈫?splitter 鈹€鈹€鈫?chunks
  jpg/png/gif/...        鈹€鈹€鈫? description.md 鈹€鈹€鈫?splitter 鈹€鈹€鈫?chunks
```

**璁捐鎰忓浘锛?*
- **鍙璁?* 鈥?浠讳綍鏃跺€欓兘鑳戒粠 MinIO 鎷夊洖杩欎唤 MD锛屾煡鐪?鍒板簳浠€涔堝唴瀹硅繘鍏ヤ簡鍒囧垎鍣?
- **鍙鐜?* 鈥?鍒囧垎绛栫暐鍙皟鏁村悗瀵瑰悓涓€浠?MD 閲嶆柊鍒囧垎锛屾棤闇€閲嶆柊瑙ｆ瀽鍘熸枃浠?- **鍙墿灞?* 鈥?鏂板鏂囦欢绫诲瀷鍙渶鍐欎竴涓?"鍘熷鏂囦欢鈫扢D" 鐨勮В鏋愬櫒锛屾棤闇€鏀瑰姩鍒囧垎銆丒mbedding銆丒S 绱㈠紩

### 3.5 绠￠亾鎵ц娴佺▼

```
涓婁紶鏂囦欢
  鈹?  鈻?Document (绾厓鏁版嵁璁板綍)
  鈹?  鈻?enqueue 鈫?DocumentTask (status=PENDING, pipeline_config=KB.config蹇収)
  鈹?  鈻?Worker 鍙栧嚭
  鈹?  鈹溾攢 mark_processing()  鈫?Task.started_at
  鈹?  鈹溾攢 Step 1: Parse 鈥?鍘熷鏂囦欢 鈫?MD鍏ㄦ枃
  鈹?  鈹?  鈹?  鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?  鈹? 鈹?鏂囦欢绫诲瀷    鈹?瑙ｆ瀽鏂瑰紡                            鈹?  鈹?  鈹? 鈹溾攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?  鈹? 鈹?txt/md     鈹?鐩存帴璇诲彇 UTF-8 鏂囨湰                  鈹?  鈹?  鈹? 鈹?pdf/docx   鈹?DocumentReader 鎻愬彇鍏ㄦ枃              鈹?  鈹?  鈹? 鈹?xlsx/csv   鈹?琛ㄦ牸杞?Markdown table                鈹?  鈹?  鈹? 鈹?pptx       鈹?骞荤伅鐗囧唴瀹归€愰〉鎷兼帴                    鈹?  鈹?  鈹? 鈹?html/json  鈹?鎻愬彇鏂囨湰鍐呭                         鈹?  鈹?  鈹? 鈹?jpg/png    鈹?VLM 鐢熸垚鍥剧墖鎻忚堪                     鈹?  鈹?  鈹? 鈹?mp3/wav    鈹?ASR 杞啓 鈫?[HH:MM:SS] 甯︽椂闂存埑鏂囨湰   鈹?  鈹?  鈹? 鈹?mp4/mkv    鈹?鎶藉抚 鈫?VLM 閫愬抚鎻忚堪 鈫?甯︽椂闂存埑鑱氬悎    鈹?  鈹?  鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?  鈹?  鈹?  鈹斺攢鈫?浜у嚭: full_text (绾枃鏈?Markdown)
  鈹?  鈹溾攢 Step 2: 涓婁紶 MD 鈫?MinIO
  鈹?  鈹?璺緞: spaces/{space_id}/kbs/{kb_id}/parsed/{file_hash}.md
  鈹?  鈹?璁板綍: Document.storage.parsed_text_object = 涓婅堪璺緞
  鈹?  鈹?钀藉簱: session.commit()  鈫?绔嬪嵆鎸佷箙鍖栵紝涓嶇瓑鍚庣画姝ラ
  鈹?  鈹斺攢 Task.step_progress.parsed = "done"
  鈹?  鈹溾攢 Step 3: Split 鈥?MD鍏ㄦ枃 鈫?chunks
  鈹?  鈹?杈撳叆: 浠?MinIO 鎴栧唴瀛樿鍙?Step 2 鐨?MD 鍏ㄦ枃
  鈹?  鈹?绛栫暐: splitting.{modality} 鏈夐厤 鈫?涓撳睘绛栫暐
  鈹?  鈹?       splitting.{modality} 娌￠厤 鈫?splitting 榛樿绛栫暐
  鈹?  鈹斺攢 Task.step_progress.split = "done"
  鈹?  鈹溾攢 Step 4: Embedding 鈫?Task.step_progress.embedded = "done"
  鈹?  鈹溾攢 Step 5: ES Index 鈫?Task.step_progress.indexed = "done"
  鈹?  鈹斺攢 mark_completed() 鈫?Task (status=COMPLETED, completed_at, pipeline_result)
```

---

## 鍥涖€佹秹鍙婃枃浠?
### 4.1 鍚庣 鈥?鏂板

| 鏂囦欢 | 璇存槑 |
|------|------|
| `models/document_task.py` | DocumentTask ORM 妯″瀷 + TaskStatus 鏋氫妇 |
| `schemas/document_task_schema.py` | DocumentTask Pydantic Schema |
| `repository/document_task_repository.py` | DocumentTask 鏁版嵁璁块棶灞?|

### 4.2 鍚庣 鈥?淇敼

| 鏂囦欢 | 鏀瑰姩瑕佺偣 |
|------|---------|
| `models/document.py` | 鍒犻櫎 status/status_info/doc_metadata/processing_started_at/processed_at/version_info锛涘垹闄?mark_*/set_error/increment_retry/get_version_info/revive 鏂规硶锛涙坊鍔?tasks 鍏崇郴 |
| `models/__init__.py` | 瀵煎嚭 DocumentTask, TaskStatus |
| `schemas/document_schema.py` | DocumentResponse 鍘绘帀 status/status_info/retry_count/error_message/processing_started_at/processed_at锛泂tatus 鏀逛负浠?Task 娲剧敓锛涗繚鐣?chunk_count/token_count |
| `schemas/knowledge_base_schema.py` | AudioParsingConfig 鍘绘帀 chunk_split_strategy/chunk_size锛汼plittingConfig 鏂板 audio/VideoSplitting 瀛愰厤缃紱KnowledgeBaseConfigUpdate 鏂板 splitting.audio/splitting.video |
| `services/document_service.py` | upload_document 涓嶅啀鍐?status锛涚閬撴柟娉曟敼涓哄啓 Task 鑰岄潪 Document锛沞xecute_document_pipeline 鎷嗗垎 parse鈫抯plit鈫抏mbed+index |
| `services/media_processing.py` | process_audio/process_video 鍘绘帀鍐呴儴鍒囧垎閫昏緫锛屽彧鍋氳浆鍐?鎻忚堪鈫掓嫾MD鈫掍笂浼狅紱鍒囧垎缁熶竴璧版枃鏈垏鍒嗗櫒 |
| `services/knowledge_base_service.py` | get_kb_document_stats 鏀圭敤 Task 琛ㄨ鏁帮紱鍒犻櫎 document status 鐩稿叧鏌ヨ |
| `repository/document_repository.py` | 鍒犻櫎 status 杩囨护鍙傛暟锛坓et_by_kb/count_by_kb锛夛紱鍒犻櫎姝讳唬鐮佹柟娉曪紱stats 鏌ヨ鏀逛负 join Task |
| `api/document_routes.py` | 鍝嶅簲鏍煎紡璋冩暣锛涚姸鎬佸弬鏁版敼涓轰粠 Task 鏌ヨ锛涙柊澧?GET /{doc_id}/tasks |
| `api/exceptions.py` | DocumentAlreadyProcessingError 鏀瑰悕涓?TaskAlreadyProcessingError |
| `api/startup.py` | 寮傚父娉ㄥ唽鏇存柊 |
| `shared/mq/worker.py` | 鍏ㄩ噺鏀逛负鎿嶄綔 Task锛沖ensure_mark_failed raw SQL 鏀逛负 tasks 琛紱recover_orphan_documents 鏀逛负鏌?Task |
| `shared/mq/task_tracker.py` | bind/unbind/active_count 绛夊嚱鏁版敼涓?Task 鎸佷箙鍖栨搷浣滐紱淇濈暀 Redis 鍙栨秷鏍囪锛堢簿纭彇娑堥渶瑕佷綆寤惰繜锛?|
| `shared/mq/__init__.py` | enqueue_process_document 澧炲姞鍒涘缓 Task 璁板綍 |
| `shared/utils/media_utils.py` | upload_parsed_text_to_minio 璺緞鏀逛负 `parsed/{file_hash}.md` |

### 4.3 鍓嶇 鈥?淇敼

| 鏂囦欢 | 鏀瑰姩瑕佺偣 |
|------|---------|
| `api/types.ts` | Document 鎺ュ彛鍘绘帀 status/status_info/retry_count/error_message/processing_started_at/processed_at锛涙柊澧?DocumentTask 鎺ュ彛锛汼plittingConfig 鏂板 audio/video锛汚udioParsingConfig 鍘绘帀 chunk_split_strategy/chunk_size |
| `api/knowledge/document.ts` | 鏂板 getDocumentTask()锛沺rocess 绫绘帴鍙ｈ繑鍥?task_id |
| `views/space/DocumentView.vue` | status 杩囨护/灞曠ず鏀圭敤 Task锛沬sProcessing/isFailed/canProcess 璇?Task 鐘舵€?|
| `views/space/DocumentDetailView.vue` | 璇︽儏椤靛睍绀?Task 淇℃伅锛沜hunk_count 鏀逛负浠?pipeline_result 娲剧敓 |
| `views/space/KbConfigView.vue` | 闊抽鍒囩墖浠?Step 3 绉诲埌 Step 4 splitting.audio锛涜棰戝垏鍒嗛厤缃柊澧?splitting.video |
| `components/knowledge/document.ts` | docStatusMap 鏀逛负 taskStatusMap锛涙柊澧?taskStatusMap锛屽苟浣滀负鐭ヨ瘑搴撻鍩熷叡鐢ㄥ伐鍏峰叆鍙?|

---

## 浜斻€佸紑鍙戞楠?
### Step 1: 鏂板缓 DocumentTask 妯″瀷
1. 鍒涘缓 `models/document_task.py`
2. 鍒涘缓 `schemas/document_task_schema.py`
3. 鍒涘缓 `repository/document_task_repository.py`
4. 鏇存柊 `models/__init__.py` 瀵煎嚭

### Step 2: 鏀归€?Document 妯″瀷
1. 鍒犻櫎 version_info 瀛楁鍜屾柟娉?2. 鍒犻櫎 status/status_info/doc_metadata/processing_started_at/processed_at
3. 鍒犻櫎 mark_*/set_error/increment_retry/get_version_info/revive
4. 鍒犻櫎 DELETED 鏋氫妇鍊硷紙deleted_at 瓒充互鍒ゆ柇杞垹闄わ級
5. 娣诲姞 `tasks` 鍏崇郴

### Step 3: 鏀归€?KB Config 缁撴瀯
1. AudioParsingConfig 鍘绘帀 chunk_split_strategy / chunk_size
2. SplittingConfig 鏂板 AudioOverride / VideoOverride 鍙€夊瓙閰嶇疆
3. KnowledgeBaseConfigUpdate 鍚屾鏇存柊
4. 鍓嶇 types.ts 鍚屾

### Step 4: 閲嶆瀯绠￠亾閫昏緫
1. 鎷嗗垎 `execute_document_pipeline` 鏂囨湰鍒嗘敮锛歳eader 鈫?MD涓婁紶 鈫?splitter
2. 閲嶅啓 `process_audio_document`锛欰SR 鈫?鎷糓D 鈫?涓婁紶 鈫?缁熶竴splitter
3. 閲嶅啓 `process_video_document`锛氭娊甯?VLM 鈫?鎷糓D 鈫?涓婁紶 鈫?缁熶竴splitter
4. 鏂板缁熶竴鐨?MD splitter锛堣緭鍏?MD鍏ㄦ枃锛岃緭鍑?chunks锛屾敮鎸?modality override锛?5. MD 涓婁紶璺緞鏀逛负 `spaces/{s}/kbs/{kb}/parsed/{file_hash}.md`

### Step 5: 鏀归€?Worker
1. 浠庢搷浣?Document 鈫?鎿嶄綔 DocumentTask
2. enqueue 鏃跺垱寤?Task锛坰tatus=PENDING, pipeline_config=蹇収锛?3. `mark_processing()` 鈫?Task
4. 绠￠亾鍚勯樁娈垫洿鏂?Task.step_progress
5. `mark_completed()` 鈫?Task (pipeline_result)
6. `_ensure_mark_failed` raw SQL 鈫?tasks 琛?7. `recover_orphan_documents` 鈫?鏌?Task 琛?
### Step 6: 鏀?Repository + Service
1. document_repository.py 鍒犻櫎姝讳唬鐮併€佺Щ闄?status 杩囨护鍙傛暟
2. stats 鏌ヨ鏀逛负 join Task 琛紙鐘舵€佽鏁伴儴鍒嗭級
3. document_service.py 鐘舵€佹鏌ユ敼涓烘煡 Task
4. knowledge_base_service.py get_kb_document_stats 鏀圭敤 Task

### Step 7: 鏀?API Routes
1. 鏂囨。鍒楄〃/璇︽儏鐨?status 瀛楁鏀逛负浠?Task 娲剧敓
2. 鏂板 `GET /{kb_id}/documents/{doc_id}/tasks`
3. process/reprocess/retry/cancel 杩斿洖 task_id

### Step 8: 鏀瑰墠绔?1. api/types.ts 鈥?鏂板 DocumentTask锛孌ocument 鍘荤姸鎬佸瓧娈?2. api/knowledge/document.ts 鈥?鏂板 getDocumentTask()
3. DocumentView 鈥?鐘舵€佸睍绀?杩囨护璇?Task
4. DocumentDetailView 鈥?璇︽儏鍔?Task 淇℃伅
5. KbConfigView 鈥?splitting 鍔?audio/video 瑕嗙洊
6. components/knowledge/document.ts 鈥?docStatusMap 鈫?taskStatusMap

### Step 9: 娓呯悊 task_tracker
1. 鎸佷箙鍖栫粦瀹?鍙栨秷缁戝畾鏀逛负 DB 鎿嶄綔
2. 淇濈暀 Redis 鍙栨秷鏍囪锛堥渶瑕佷綆寤惰繜鍙栨秷妫€鏌ワ級

### Step 10: 楠岃瘉
1. 鍚庣缂栬瘧 `py_compile` 鍏ㄩ儴淇敼鏂囦欢
2. 鍓嶇 `type-check` + `build-only`
3. 鍚姩鍚庣纭寤鸿〃鎴愬姛锛堟柊寤?tasks 琛級
4. 璧伴€氬畬鏁翠笂浼犫啋瑙ｆ瀽鈫掑垏鍒嗏啋绱㈠紩娴佺▼

---

## 鍏€佷笉鍙樼殑閮ㄥ垎

- ES 绱㈠紩缁撴瀯涓嶆敼鍙?- MinIO 瀛樺偍缁撴瀯锛堥櫎 MD 璺緞鍛藉悕锛?- 鐢ㄦ埛璁よ瘉閾捐矾
- AI 妯″瀷璋冪敤锛圠LM/Embedding/ASR/VLM锛?- arq 浠诲姟闃熷垪鏈哄埗锛坢ax_tries銆乺etry_base_delay 绛夛級
- 鎼滅储 / 璇勪及 / Agent / Skill 绛夋ā鍧椾笉娑夊強鏂囨。澶勭悊绠￠亾

---

## 涓冦€佸畬鏁存€у鏌ョ粨鏋滐紙3 agent 浜ゅ弶楠岃瘉锛?
### 7.1 鍏抽敭閬楁紡锛圕ritical锛?
| # | 閬楁紡 | 褰卞搷 | 琛ュ厖鍒?|
|---|------|------|--------|
| 1 | `enqueue_process_document()` 涓嶅垱寤?Task 璁板綍 | 鏍稿績闇€姹傜己澶憋紝鏃?Task 蹇収 | Step 5.2 |
| 2 | `execute_document_pipeline()` 鏃?Task 鍙傛暟 | 鏃犳硶鍐欏叆 Task.step_progress / pipeline_result | Step 4 |
| 3 | `_build_stats_select()` 鐘舵€佽仛鍚堥渶閲嶅啓 JOIN | 缁熻鏌ヨ澶嶆潅搴﹀ぇ澧?| Step 6.2 |
| 4 | `SplittingConfig` 姝ц鑱斿悎鏃犳硶瀹圭撼 audio/video 瀛愰厤缃?| Schema 缁撴瀯涓嶅吋瀹?| Step 3.2 |
| 5 | `_validate_config_updates()` 涓嶆牎楠?splitting.audio/video | 鍒囧垎绛栫暐鏂板瓧娈垫棤鏍￠獙 | Step 3.3 |
| 6 | `revive()` 鍒犻櫎鍚?`upload_document()` 澶嶆椿閫昏緫闇€瑕佹浛浠ｆ柟妗?| 鍚屾枃浠堕噸浼犲姛鑳界己澶?| Step 2.3 |
| 7 | `process_kb_documents()` 鐨?`status=UPLOADED` 鏌ヨ鏃犳浛浠?| 鎵归噺澶勭悊鍏ュ彛澶辨晥 | Step 6.1 |
| 8 | 骞跺彂闃叉姢鏃?DB 绾х害鏉燂紙 `UNIQUE (document_id) WHERE status IN (PENDING,PROCESSING)` 锛?| 绔炴€佹潯浠堕闄?| Step 1.3 |
| 9 | `recover_orphan_documents()` 鏌?`Document.status` 闇€鏀规煡 Task | 閲嶅惎鎭㈠澶辨晥 | Step 5.7 |
| 10 | `process_resume_task()` 鍏辩敤 `TaskTracker` 鍩虹璁炬柦锛岄渶鍐冲畾鍚屾杩佺Щ杩樻槸鍒嗗弶 | 绠€鍘嗙閬撳彈褰卞搷 | Step 9 |

### 7.2 鍚庣閬楁紡锛圚igh锛?
| # | 閬楁紡 | 琛ュ厖鍒?|
|---|------|--------|
| 11 | ES chunk 鐨?`start_time`/`end_time`/`frame_paths` 鍏冩暟鎹湪缁熶竴 MD 鍒囧垎鍚庡浣曚繚鐣?| Step 4.4 |
| 12 | `_generate_questions_for_chunks_static()` 璇?LIVE KB config 鑰岄潪 `Task.pipeline_config` 蹇収 | Step 5.5 |
| 13 | `_handle_final_failure()` 宸叉槸姝讳唬鐮侊紝搴斿垹闄ゆ垨姝ｅ紡鍚敤 | Step 5.6 |
| 14 | `_ensure_mark_failed()` raw SQL 鍐?`documents` 琛ㄩ渶鏀逛负 `document_tasks` | Step 5.6 |
| 15 | `delete_by_kb()` 杞垹鏃?Task 琛屼笉鍋氱骇鑱斿鐞?| Step 2.4 |
| 16 | `_list_by_parent()` 鐨?`status` 鍙傛暟闇€鏀逛负 Task join | Step 6.1 |
| 17 | `DEFAULT_STORAGE` 甯搁噺姝讳唬鐮侊紝鍙竴骞舵竻鐞?| Step 2 |
| 18 | `get_deleted_by_hash()` 鍦?revive 鍒犻櫎鍚庡彉涓烘浠ｇ爜 | Step 2.3 |
| 19 | `DocumentProcessor` 闇€鏂板 `read_full_text()`锛坮eader-only锛夊拰 `split_text()`锛坰plitter-only锛変袱涓柊鏂规硶 | Step 4.1 |
| 20 | `ai_chat_service.py` 璋冪敤浜?`DocumentProcessor.load_with_strategy()`锛岄渶閫傞厤 | Step 4.6 |

### 7.3 鍓嶇閬楁紡锛圚igh锛?
| # | 閬楁紡 | 琛ュ厖鍒?|
|---|------|--------|
| 21 | Status 杩囨护鍊间粠 `uploaded`鈫抈pending`锛屾柊澧?`cancelled` | Step 8.3 |
| 22 | `isProcessing`/`isFailed`/`canProcess` 鐘舵€佸父閲忔槧灏勬洿鏂?| Step 8.3 |
| 23 | `KbConfigView.onSave()` 闊抽鍒囧垎浠?`parsing.audio` 绉诲埌 `splitting.audio` | Step 8.5 |
| 24 | `KbConfigView.onLoad()` 闊抽鍒囧垎浠?`parsing.audio` 璇绘敼涓?`splitting.audio` | Step 8.5 |
| 25 | `buildSplittingConfig()` 闇€鍖呭惈 audio/video 瀛愰厤缃?| Step 8.5 |
| 26 | `ProcessDocumentResponse` / `BatchProcessResponse` 闇€鏂板 `task_id` | Step 8.1 |
| 27 | `SplittingConfig` 绫诲瀷闇€鏂板 audio/video override 瀛楁 | Step 8.1 |
| 28 | `KBStats.uploaded_documents` 璇箟鍙樺寲锛堟槸鍚﹂噸鍛藉悕涓?`pending_documents`锛?| Step 8.1 |
| 29 | `DocumentDetailView` 涓?`doc_metadata.chunk_type/frame_count/segment_count` 鏀逛负璇?`pipeline_result` | Step 8.4 |
| 30 | 鍓嶇鐩墠鏃?Task 杞/Store 鏈哄埗鐢ㄤ簬瀹炴椂杩涘害灞曠ず | Step 8.8 |
| 31 | `KbConfigView` 缂哄皯瑙嗛鍒囧垎 UI锛坒orm fields for videoChunkStrategy/videoChunkSize锛?| Step 8.5 |
| 32 | `canReprocess`/`isProcessing`/`isFailed` 璁＄畻灞炴€ч渶鐘舵€侀敭鍊兼洿鏂?| Step 8.4 |
| 33 | `DocumentDetailView.status` 灞曠ず婧愪笉鏄庣‘锛圓PI 娲剧敓 vs 鍗曠嫭 Task 绔偣锛?| Step 8.4 |
| 34 | `getMaxFileSizeText` 宸叉槸姝讳唬鐮?| Step 8.7 |

### 7.4 璁捐鍐崇瓥寰呭畾

| # | 鍐崇瓥鐐?| 寰呭畾椤?|
|---|--------|--------|
| A | `SplittingConfig` 缁撴瀯璋冩暣 | 鎷嗗嚭 top-level 瀛楁 `audio`/`video`锛屼笉鍐嶇敤姝ц鑱斿悎鍖呰９ |
| B | ES metadata 淇濈暀鏂规 | 鏃堕棿鎴冲垏鍒嗭細鎸?`[HH:MM:SS]` 鏍囪杈圭晫锛屼笉鍦ㄤ袱娈典箣闂存埅鏂?|
| C | 鍙栨秷鏍囪 | Redis锛堜綆寤惰繜锛? Task.status=CANCELLED锛堟寔涔咃級锛屽弻閲嶄繚闅?|
| D | 骞跺彂闃叉姢 | 搴旂敤灞?check + DB partial unique index |
| E | 杞垹绾ц仈 | Task 涓嶇骇鑱旇蒋鍒狅紙FK 浠嶆湁鏁堬級锛屾煡璇㈡椂鎺掗櫎 `document.deleted_at IS NOT NULL` |

---

## 鍏€侀闄╃偣锛堟洿鏂帮級

## 涓冦€侀闄╃偣

| 椋庨櫓 | 缂撹В鎺柦 |
|------|---------|
| Document.status 鍦?30+ 澶勮鏌ヨ杩囨护 | 閫愬瀹¤锛屽垎姝ユ浛鎹负 Task join锛屼笉涓€娆℃€ф敼鍔?|
| 鍓嶇渚濊禆 status 瀛楁鐨勫睍绀洪€昏緫 | 鍚庣 API 鍏煎杩斿洖 status锛堜粠 Task 娲剧敓锛夛紝鍓嶇娓愯繘閫傞厤 |
| Raw SQL 鐩存帴鍐?documents 琛?| worker.py:208 涓夊眰鍏滃簳鏀逛负鍐?tasks 琛紝鐙珛娴嬭瘯 |
| Stats 鏌ヨ渚濊禆 Document.status 鐨?CASE WHEN | 鏀逛负 join Task 琛紝鎬ц兘鐩稿綋锛圱ask 琛ㄦ洿灏忥級 |

