# 鏅鸿兘鐭ヨ瘑搴撳墠绔紑鍙戣鍒?
## 鐜版湁浠ｇ爜瀹¤缁撴灉

> **鏇存柊 (2026-07)**锛氫互涓?8 涓弗閲嶉棶棰樺拰 6 涓己澶卞姛鑳藉凡鍏ㄩ儴淇/瀹炵幇锛岀姸鎬佹爣娉ㄥ涓嬨€備唬鐮佽川閲忛棶棰橀儴鍒嗗凡鏍稿疄褰撳墠鐘舵€併€?
### 涓ラ噸闂锛堜細瀵艰嚧杩愯鏃跺穿婧冿級

| # | 闂 | 鐘舵€?|
|---|------|------|
| 1 | 鍝嶅簲鎷︽埅鍣ㄥ亣璁惧悗绔繑鍥?`{code, message, data}` 鍖呰锛屼絾鍚庣瀹為檯鐩存帴杩斿洖瑁告暟鎹?| 鉁?宸蹭慨澶?鈥?`api/index.ts` 鐩存帴杩斿洖 `response.data` |
| 2 | 鎼滅储 API 璺緞瀹屽叏閿欒锛屽悗绔敤 `/spaces/{id}/knowledge-bases/{kbId}/search`锛屽墠绔敤 `/spaces/{id}/search?kb_id=` | 鉁?宸蹭慨澶?鈥?`api/knowledge/search.ts` 浣跨敤姝ｇ‘璺緞 |
| 3 | `clearChatHistory` 鐢?POST 璇锋眰锛屽悗绔姹?DELETE | 鉁?宸蹭慨澶?鈥?浣跨敤 `request.delete()` |
| 4 | `updateSystemPrompt` 璋冪敤涓嶅瓨鍦ㄧ殑鎺ュ彛 | 鉁?宸蹭慨澶?鈥?鍑芥暟宸茬Щ闄?|
| 5 | `ResearchRequest` 璇锋眰浣撶粨鏋勯敊璇紝鍚庣闇€瑕佸祵濂楀璞★紙`internal_search`/`external_search`/`llm`锛夛紝鍓嶇鍙戞墎骞冲瓧娈?| 鉁?宸蹭慨澶?鈥?`types.ts` 浣跨敤宓屽缁撴瀯 |
| 6 | `SearchRequest` 鍚屾牱鐨勫祵濂楃粨鏋勯敊璇?| 鉁?宸蹭慨澶?鈥?`types.ts` 浣跨敤宓屽 `weights`/`rerank`/`llm`/`query_rewrite` |
| 7 | SSE 娴佸紡鍝嶅簲鐨?error 浜嬩欢琚唴閮?catch 鍚炴帀锛岀敤鎴锋案杩滅湅涓嶅埌閿欒 | 鉁?宸蹭慨澶?鈥?Store 鏄庣‘璁剧疆 `error.value` |
| 8 | `SessionConfig` 绫诲瀷缁撴瀯涓庡悗绔笉鍖归厤锛堟墎骞?vs 宓屽 `compression_config`锛?| 鉁?宸蹭慨澶?鈥?浣跨敤宓屽 `compression` 瀵硅薄 |

### 缂哄け鐨勫姛鑳?
| # | 缂哄け鍐呭 | 鐘舵€?|
|---|---------|------|
| 1 | 鐢ㄦ埛妯″瀷閰嶇疆绠＄悊锛圠LM/Embedding/Rerank 绉佹湁閰嶇疆 CRUD + 杩炴帴娴嬭瘯锛?| 鉁?宸插疄鐜?鈥?`api/user.ts` 鍏ㄩ儴 9 涓柟娉?|
| 2 | QA 娑堟伅/浼氳瘽 CRUD锛堟坊鍔犳秷鎭€佽幏鍙栨秷鎭垪琛ㄣ€佽幏鍙栦細璇濆垪琛ㄣ€佹洿鏂?鍒犻櫎娑堟伅銆佸垹闄や細璇濄€佽幏鍙栦笂涓嬫枃锛?| 鉁?宸插疄鐜?鈥?`api/session.ts` 鍏ㄩ儴 7 涓柟娉?|
| 3 | 浼氳瘽閰嶇疆绠＄悊锛堝垱寤?鑾峰彇/鍒犻櫎鍘嬬缉閰嶇疆锛?| 鉁?宸插疄鐜?鈥?`api/session.ts` 3 涓柟娉?|
| 4 | 璺敱缂哄皯 `/403` 椤甸潰锛堝畧鍗凡閲嶅畾鍚戜絾鏃犺矾鐢憋級 | 鉁?宸插疄鐜?鈥?璺敱鍜?`ForbiddenView.vue` 鍧囧瓨鍦?|
| 5 | 鏃?Token 鑷姩鍒锋柊鏈哄埗锛?0 鍒嗛挓寮哄埗鐧诲嚭锛?| 鉁?宸插疄鐜?鈥?`api/index.ts` 401 鑷姩鍒锋柊 + 璇锋眰闃熷垪 |
| 6 | SSE 娴佹棤 AbortController锛堟棤娉曞彇娑堣繘琛屼腑鐨勬祦锛?| 鉁?宸插疄鐜?鈥?`createSSEStream` 鎺ュ彈 `signal`锛孲tore 浣跨敤 AbortController |

### 浠ｇ爜璐ㄩ噺闂

| # | 闂 | 鏂囦欢 | 褰卞搷 |
|---|------|------|------|
| 1 | 鍝嶅簲鎷︽埅鍣ㄥ亣璁惧悗绔繑鍥?`{code, message, data}` 鍖呰锛屼絾鍚庣瀹為檯鐩存帴杩斿洖瑁告暟鎹?| `api/index.ts` | 鎵€鏈夋帴鍙ｅ彲鑳借鍒や负閿欒 |
| 2 | 鎼滅储 API 璺緞瀹屽叏閿欒锛屽悗绔敤 `/spaces/{id}/knowledge-bases/{kbId}/search`锛屽墠绔敤 `/spaces/{id}/search?kb_id=` | `api/knowledge/search.ts` | 鎼滅储鍔熻兘瀹屽叏涓嶅彲鐢?|
| 3 | `clearChatHistory` 鐢?POST 璇锋眰锛屽悗绔姹?DELETE | `api/chat.ts` | 娓呴櫎鑱婂ぉ鍘嗗彶鎶?405 |
| 4 | `updateSystemPrompt` 璋冪敤涓嶅瓨鍦ㄧ殑鎺ュ彛 | `api/chat.ts` | 濮嬬粓 404 |
| 5 | `ResearchRequest` 璇锋眰浣撶粨鏋勯敊璇紝鍚庣闇€瑕佸祵濂楀璞★紙`internal_search`/`external_search`/`llm`锛夛紝鍓嶇鍙戞墎骞冲瓧娈?| `api/types.ts` | 娣卞害鐮旂┒楂樼骇鍙傛暟鍏ㄩ儴涓㈠け |
| 6 | `SearchRequest` 鍚屾牱鐨勫祵濂楃粨鏋勯敊璇?| `api/knowledge/search.ts` | 鎼滅储楂樼骇鍙傛暟鍏ㄩ儴涓㈠け |
| 7 | SSE 娴佸紡鍝嶅簲鐨?error 浜嬩欢琚唴閮?catch 鍚炴帀锛岀敤鎴锋案杩滅湅涓嶅埌閿欒 | `stores/chat.ts`, `stores/research.ts` | 娴佸紡閿欒闈欓粯涓㈠け |
| 8 | `SessionConfig` 绫诲瀷缁撴瀯涓庡悗绔笉鍖归厤锛堟墎骞?vs 宓屽 `compression_config`锛?| `api/types.ts` | 浼氳瘽閰嶇疆鍔熻兘涓嶅彲鐢?|

### 缂哄け鐨勫姛鑳?
| # | 缂哄け鍐呭 | 鍚庣鎺ュ彛鏁伴噺 |
|---|---------|-------------|
| 1 | 鐢ㄦ埛妯″瀷閰嶇疆绠＄悊锛圠LM/Embedding/Rerank 绉佹湁閰嶇疆 CRUD + 杩炴帴娴嬭瘯锛?| 9 涓帴鍙?|
| 2 | QA 娑堟伅/浼氳瘽 CRUD锛堟坊鍔犳秷鎭€佽幏鍙栨秷鎭垪琛ㄣ€佽幏鍙栦細璇濆垪琛ㄣ€佹洿鏂?鍒犻櫎娑堟伅銆佸垹闄や細璇濄€佽幏鍙栦笂涓嬫枃锛?| 7 涓帴鍙?|
| 3 | 浼氳瘽閰嶇疆绠＄悊锛堝垱寤?鑾峰彇/鍒犻櫎鍘嬬缉閰嶇疆锛?| 3 涓帴鍙?|
| 4 | 璺敱缂哄皯 `/403` 椤甸潰锛堝畧鍗凡閲嶅畾鍚戜絾鏃犺矾鐢憋級 | - |
| 5 | 鏃?Token 鑷姩鍒锋柊鏈哄埗锛?0 鍒嗛挓寮哄埗鐧诲嚭锛?| - |
| 6 | SSE 娴佹棤 AbortController锛堟棤娉曞彇娑堣繘琛屼腑鐨勬祦锛?| - |

### 浠ｇ爜璐ㄩ噺闂

| # | 闂 | 褰撳墠鐘舵€?|
|---|------|---------|
| 1 | 6 涓€氱敤缁勪欢宸茬紪鍐欎絾浠庢湭琚换浣曢〉闈娇鐢?| 鉂?寰呮牳瀹?鈥?閮ㄥ垎缁勪欢锛堝 Pagination銆丼tatusTag銆丼earchBar锛夊凡琚〉闈娇鐢紝闇€閫愮粍浠舵牳瀹?|
| 2 | `MainLayout` 渚ц竟鏍忔棤娉曢珮浜祵濂楄矾鐢憋紙`/spaces/1/knowledge-bases` 涓嶄細婵€娲?鐭ヨ瘑绌洪棿"鑿滃崟锛?| 鉂?寰呮牳瀹?鈥?闇€妫€鏌?`MainLayout.vue` 涓?`route.matched` 閫昏緫 |
| 3 | 鏃?`.env` 鏂囦欢锛屾棤 Vite 寮€鍙戜唬鐞嗛厤缃紝鏃犳硶鑱旇皟鍚庣 | 鉁?宸蹭慨澶?鈥?`.env.development`銆乣.env.production`銆乣.env.example` 鍧囧凡瀛樺湪锛宍vite.config.ts` 宸查厤缃唬鐞?|
| 4 | 澶氬 `ElMessageBox` 鍙栨秷鍒ゆ柇浣跨敤涓嶅畨鍏ㄧ殑 `(error as string) !== 'cancel'` | 鈿狅笍 閮ㄥ垎淇 鈥?闇€閫愭枃浠舵鏌ユ槸鍚︿粛鏈夋绫诲啓娉?|
| 5 | vitest 宸查厤缃絾鏃犱换浣曟祴璇曟枃浠?| 鉂?浠嶆湭瑙ｅ喅 鈥?`src/` 涓嬫棤浠讳綍 `.test.ts` 鎴?`.spec.ts` 鏂囦欢 |
| 6 | 璺敱瀹堝崼鐩存帴璇?`localStorage` 鑰岄潪浣跨敤 user store | 鉂?寰呮牳瀹?鈥?闇€妫€鏌?`router/guards.ts` 褰撳墠瀹炵幇 |

---

## 寮€鍙戣鍒?
> **璇存槑**锛氫互涓?Stage 0-9 涓?2026-05 鍒跺畾鐨勫紑鍙戣鍒掞紝褰撳墠椤圭洰宸插熀鏈畬鎴愬ぇ閮ㄥ垎闃舵銆傚叾涓?Stage 0-4锛堝熀纭€璁炬柦/API/Store/甯冨眬/鐢ㄦ埛绠＄悊锛夈€丼tage 6锛圓I 瀵硅瘽锛夈€丼tage 7锛堟繁搴︾爺绌讹級宸插熀鏈疄鐜帮紱Stage 5锛堢煡璇嗙┖闂撮珮绾ф悳绱㈤厤缃級鍜?Stage 8-9锛堢粍浠剁粺涓€/娴嬭瘯锛変粛鏈夐儴鍒嗘湭瀹屾垚銆備互涓嬭鍒掍繚鐣欎綔涓哄弬鑰冿紝褰撳墠搴斾紭鍏堝叧娉ㄤ唬鐮佽川閲忛棶棰樼殑淇鍜屾祴璇曡鐩栥€?
### 鎬讳綋绛栫暐

**浠庡簳灞傚埌涓婂眰锛岄€愬眰閲嶅缓**锛氬熀纭€璁炬柦 鈫?API 灞?鈫?鐘舵€佺鐞?鈫?椤甸潰瑙嗗浘 鈫?鎵撶（浼樺寲銆傛瘡涓樁娈靛畬鎴愬悗鍙嫭绔嬮獙璇併€?
---

## 闃舵 0锛氬熀纭€璁炬柦淇锛堥璁?1-2 灏忔椂锛?
> 鐩爣锛氳椤圭洰鑳藉湪寮€鍙戠幆澧冩甯歌繍琛岋紝涓庡悗绔仈璋冦€?
### 0.1 鐜閰嶇疆

- 鍒涘缓 `.env.development`锛氬畾涔?`VITE_API_BASE_URL=http://localhost:8100`
- 鍒涘缓 `.env.production`锛氬畾涔?`VITE_API_BASE_URL=`锛堜娇鐢ㄧ浉瀵硅矾寰勶紝閮ㄧ讲鏃跺悓鍩燂級
- 鍒涘缓 `.env.example`锛氭ā鏉挎枃浠?- 閰嶇疆 `vite.config.ts` 寮€鍙戜唬鐞嗭細灏?`/api` 浠ｇ悊鍒?`http://localhost:8100`

### 0.2 淇 Axios 瀹炰緥

**閲嶅啓 `src/api/index.ts`**锛?
- 绉婚櫎 `ApiResponse` 鍖呰绫诲瀷鐨勫亣璁锯€斺€斿悗绔洿鎺ヨ繑鍥炴暟鎹垨閿欒
- 鍝嶅簲鎷︽埅鍣細200-299 鐩存帴杩斿洖 `response.data`锛屽叾浣欒蛋閿欒澶勭悊
- 娣诲姞 **闈欓粯 Token 鍒锋柊鏈哄埗**锛?  - 401 鍝嶅簲鏃讹紝浣跨敤 `refresh_token` 鑷姩鑾峰彇鏂?token
  - 鍒锋柊鏈熼棿鍏朵粬璇锋眰鎺掗槦绛夊緟锛堥伩鍏嶅苟鍙戝埛鏂帮級
  - 鍒锋柊澶辫触鎵嶈烦杞櫥褰曢〉
- 娣诲姞 **璇锋眰鍙栨秷鏀寔**锛氬熀浜?`AbortController`
- 鍒犻櫎杈呭姪鏂规硶淇濇寔涓嶅彉锛坲pload銆乨ownload 绛夛級
- SSE 娴佸紡璇锋眰缁х画浣跨敤鍘熺敓 `fetch`锛屼絾缁熶竴 token 鑾峰彇鏂瑰紡

### 0.3 淇璺敱

- 娣诲姞 `/403` 璺敱鎸囧悜 `ForbiddenView.vue`锛堟柊寤猴級
- 淇 `MainLayout` 渚ц竟鏍?active 楂樹寒閫昏緫锛氫娇鐢?`route.matched` 鎴栨墜鍔ㄨ绠?
### 0.4 楠屾敹鏍囧噯

- [ ] `npm run dev` 鍚姩鏃犳姤閿?- [ ] 鐧诲綍椤佃兘姝ｅ父鏄剧ず
- [ ] 鐧诲綍鍚庤兘鑾峰彇鐢ㄦ埛淇℃伅
- [ ] Token 杩囨湡鑳借嚜鍔ㄥ埛鏂拌€岄潪寮哄埗鐧诲嚭
- [ ] 鏃犳潈闄愭椂姝ｇ‘鏄剧ず 403 椤甸潰

---

## 闃舵 1锛欰PI 灞傞噸寤猴紙棰勮 3-4 灏忔椂锛?
> 鐩爣锛氭墍鏈?API 璋冪敤涓庡悗绔帴鍙ｆ枃妗?100% 瀵归綈锛岀被鍨嬪畾涔夊畬鏁村噯纭€?
### 1.1 閲嶅啓绫诲瀷瀹氫箟 `src/api/types.ts`

鎸夊悗绔枃妗ｉ€愬瓧娈垫牎楠岋紝**涓ユ牸瀵归綈**鎵€鏈夋帴鍙ｇ殑璇锋眰鍜屽搷搴旂被鍨嬶細

**鐢ㄦ埛妯″潡绫诲瀷**锛?- `User`銆乣LoginRequest`銆乣LoginResponse`銆乣RefreshTokenRequest`銆乣RefreshTokenResponse`
- `CreateUserRequest`銆乣UpdateUserRequest`锛堝尯鍒嗘櫘閫氱敤鎴?绠＄悊鍛樺彲淇敼瀛楁锛?- `ModelConfig`銆乣CreateModelConfigRequest`銆乣UpdateModelConfigRequest`銆乣ModelConfigTestRequest`銆乣ModelConfigTestResponse`
- `AvailableModels`銆乣AvailableModelDetail`銆乣AvailableModelItem`

**鐭ヨ瘑绌洪棿妯″潡绫诲瀷**锛?- `Space`銆乣SpaceConfig`銆乣CreateSpaceRequest`銆乣UpdateSpaceRequest`銆乣SpaceListResponse`
- `KnowledgeBase`銆乣KBConfig`銆乣SplittingConfig`锛堣仈鍚堢被鍨嬶細recursive/fixed_size/markdown/semantic锛夈€乣ParsingConfig`銆乣EmbeddingConfig`銆乣QuestionGenerationConfig`
- `CreateKBRequest`銆乣UpdateKBRequest`銆乣KBConfigResponse`
- `Document`銆乣DocumentDetail`锛堝惈 chunks锛夈€乣Chunk`銆乣DocumentStatus`
- `Member`銆乣InviteRequest`銆乣InviteResponse`銆乣JoinRequest`銆乣UpdateMemberRoleRequest`

**鎼滅储妯″潡绫诲瀷**锛?- `SearchRequest`锛堝祵濂?`weights`銆乣rerank`銆乣llm`銆乣query_rewrite` 瀵硅薄锛?- `SearchResult`锛堝惈 `chunk_id`銆乣kb_id`銆乣metadata`銆乣file_info`锛?- `SearchResponse`锛堝惈 `original_mode`銆乣mode_fallback`銆乣answer`銆乣answer_model`銆乣elapsed_ms`銆乣cached`锛?- `SearchMode`銆乣SearchModelConfig`

**闂瓟妯″潡绫诲瀷**锛?- `ChatRequest`锛堝惈 `llm_model`銆乣max_tokens`銆乣temperature`銆乣top_p`銆乣system_prompt`锛?- `ChatResponse`锛堝惈 `session_id`銆乣user_message`銆乣ai_message`銆乣conversation_history`锛?- `QAMessage`锛堝惈瀹屾暣瀛楁锛歚id`銆乣content`銆乣role`銆乣user_id`銆乣session_id`銆乣space_id`銆乣kb_id`銆乣extra`銆乣created_at`锛?- `SessionListItem`锛坄session_id` + `preview`锛?- `SessionListResponse`锛坄items` + `total` + `limit` + `offset`锛?- `AddMessageRequest`銆乣UpdateMessageRequest`

**浼氳瘽閰嶇疆绫诲瀷**锛?- `CompressionConfig`锛坄enable_compression`銆乣strategy`銆乣threshold`銆乣target_tokens`銆乣keep_recent`銆乣custom_prompt`锛?- `CreateSessionConfigRequest`锛堝祵濂?`compression` 瀵硅薄锛?- `SessionConfigResponse`锛堝惈 `id`銆乣session_id`銆乣user_id`銆乣compression_config`銆乣created_at`銆乣updated_at`锛?
**娣卞害鐮旂┒绫诲瀷**锛?- `ResearchRequest`锛堝祵濂?`internal_search`銆乣external_search`銆乣llm` 瀵硅薄锛?- `Research`锛堝惈 `research_tasks`銆乣search_source`銆乣external_provider`銆乣search_summary`銆乣stats`锛?- `ResearchTask`銆乣SearchSummary`銆乣ResearchStats`
- SSE 浜嬩欢绫诲瀷锛歚ProgressEvent`銆乣ContentEvent`銆乣DoneEvent`銆乣ErrorEvent`

### 1.2 閲嶅啓 API 妯″潡

**`src/api/user.ts`**鈥斺€旇ˉ鍏呯己澶辩殑 9 涓ā鍨嬮厤缃帴鍙ｏ細

```
getAvailableModels()          鈫?GET /user/model-configs/available
getAvailableModelDetails()    鈫?GET /user/model-configs/available/detail
getModelConfigs(modelType?)   鈫?GET /user/model-configs
createModelConfig(data)       鈫?POST /user/model-configs
getModelConfig(configId)      鈫?GET /user/model-configs/{configId}
updateModelConfig(configId, data) 鈫?PUT /user/model-configs/{configId}
deleteModelConfig(configId)   鈫?DELETE /user/model-configs/{configId}
testModelConfig(data)         鈫?POST /user/model-configs/test
deleteModelConfigByModel(modelType, model) 鈫?DELETE /user/model-configs/by-model/{modelType}/{model}
```

**`src/api/space.ts`**鈥斺€旈獙璇佸苟淇鎵€鏈?7 涓┖闂存帴鍙ｈ矾寰?
**`src/api/member.ts`**鈥斺€旈獙璇佸苟淇鎵€鏈?7 涓垚鍛樻帴鍙ｈ矾寰?
**`src/api/knowledge/knowledgeBase.ts`**鈥斺€旈獙璇佸苟淇鎵€鏈?7 涓煡璇嗗簱鎺ュ彛璺緞

**`src/api/knowledge/document.ts`**鈥斺€旈獙璇佸苟淇鎵€鏈?9 涓枃妗ｆ帴鍙ｈ矾寰?
**`src/api/knowledge/search.ts`**鈥斺€?*閲嶅啓**锛屼慨姝?URL 璺緞鍜岃姹備綋缁撴瀯锛?```
search(spaceId, kbId, body)     鈫?POST /spaces/{spaceId}/knowledge-bases/{kbId}/search
getSearchModes(spaceId, kbId)   鈫?GET /spaces/{spaceId}/knowledge-bases/{kbId}/search/modes
getSearchModelConfig(spaceId, kbId) 鈫?GET /spaces/{spaceId}/knowledge-bases/{kbId}/search/model-config
```

**`src/api/chat.ts`**鈥斺€?*閲嶅啓**锛?- 淇 `clearChatHistory` 鏀逛负 DELETE 鏂规硶
- 鍒犻櫎涓嶅瓨鍦ㄧ殑 `updateSystemPrompt`
- 鏂板 `src/api/qa.ts`鈥斺€擰A 娑堟伅/浼氳瘽绠＄悊锛? 涓帴鍙ｏ級锛?```
addMessage(data)                    鈫?POST /qa/message
getSessionMessages(sessionId)       鈫?GET /qa/session/{sessionId}
getSessions(limit?, offset?)        鈫?GET /qa/sessions
updateMessage(messageId, data)      鈫?PUT /qa/message/{messageId}
deleteMessage(messageId)            鈫?DELETE /qa/message/{messageId}
deleteSession(sessionId)            鈫?DELETE /qa/session/{sessionId}
getContext(sessionId, limit?)       鈫?GET /qa/context/{sessionId}
```
- 鏂板 `src/api/sessionConfig.ts`鈥斺€斾細璇濆帇缂╅厤缃紙3 涓帴鍙ｏ級锛?```
createSessionConfig(sessionId, data) 鈫?POST /sessions/{sessionId}/config
getSessionConfig(sessionId)          鈫?GET /sessions/{sessionId}/config
deleteSessionConfig(sessionId)       鈫?DELETE /sessions/{sessionId}/config
```

**`src/api/research.ts`**鈥斺€斾慨姝ｈ姹備綋缁撴瀯涓哄祵濂楁牸寮?
### 1.3 楠屾敹鏍囧噯

- [ ] 鎵€鏈?API 鍑芥暟鐨?URL 璺緞涓庡悗绔枃妗ｅ畬鍏ㄤ竴鑷?- [ ] 鎵€鏈夎姹?鍝嶅簲 TypeScript 绫诲瀷涓庡悗绔枃妗ｅ畬鍏ㄤ竴鑷?- [ ] `npm run type-check` 閫氳繃
- [ ] 鏃犵‖缂栫爜 token 璇诲彇锛岀粺涓€浣跨敤 tokenManager

---

## 闃舵 2锛氱姸鎬佺鐞嗛噸鏋勶紙棰勮 2-3 灏忔椂锛?
> 鐩爣锛氫慨澶嶆墍鏈?Store 鐨?bug锛岃ˉ鍏呯己澶卞姛鑳斤紝缁熶竴閿欒澶勭悊鍜?loading 妯″紡銆?
### 2.1 閲嶅啓 `src/stores/user.ts`

- 娣诲姞 `loading`銆乣error` 鐘舵€?- Token 杩囨湡妫€鏌ワ紙瑙ｇ爜 JWT `exp` 瀛楁锛?- `fetchProfile` 淇敼鍙橀噺閬斀闂
- 娣诲姞 `modelConfigs` 鐘舵€佸拰鐩稿叧 actions锛堣幏鍙?鍒涘缓/鏇存柊/鍒犻櫎/娴嬭瘯妯″瀷閰嶇疆锛?
### 2.2 閲嶅啓 `src/stores/chat.ts`

- 淇 SSE 娴佸紡鍝嶅簲涓?error 浜嬩欢琚悶鎺夌殑 bug
- 娣诲姞 **AbortController** 鏀寔锛宍sendMessageStream` 鍙彇娑?- 娣诲姞 `sendMessageStream` 鐨?`onAbort` 澶勭悊
- 淇 `currentMessages`锛堢Щ闄ゅ啑浣?computed锛?- 淇闈炴祦寮忓彂閫佸け璐ユ椂鐢ㄦ埛娑堟伅涓㈠け闂
- 鏁村悎 QA 妯″潡鐨勪細璇濈鐞嗭細浣跨敤 `/qa/sessions` 鑾峰彇浼氳瘽鍒楄〃锛宍/qa/session/{id}` 鑾峰彇娑堟伅
- 娣诲姞浼氳瘽閰嶇疆 actions锛堝垱寤?鑾峰彇/鍒犻櫎鍘嬬缉閰嶇疆锛?
### 2.3 閲嶅啓 `src/stores/research.ts`

- 淇 SSE 娴佸紡鍝嶅簲涓?error 浜嬩欢琚悶鎺夌殑 bug
- 娣诲姞 **AbortController** 鏀寔
- 淇璇锋眰浣撲负宓屽缁撴瀯
- `onDone` 浜嬩欢姝ｇ‘鏄犲皠鍒?`Research` 绫诲瀷

### 2.4 閲嶅啓 `src/stores/space.ts`

- 娣诲姞 `error` 鐘舵€?- 淇 `deleteSpace` 鏃犻敊璇鐞?- 淇骞跺彂 loading 鐘舵€侀棶棰橈紙鎸夋搷浣滅被鍨嬪尯鍒?loading锛?- `fetchPublicSpaces` 涓嶅啀闈欓粯鍚為敊璇?
### 2.5 楠屾敹鏍囧噯

- [ ] 鎵€鏈?Store 鏈?`loading` + `error` 鐘舵€?- [ ] SSE 娴佸彲閫氳繃 AbortController 鍙栨秷
- [ ] SSE error 浜嬩欢鑳芥纭紶閫掑埌 UI 灞?- [ ] Token 鍒锋柊鍦?Store 灞傝嚜鍔ㄥ鐞?- [ ] `npm run type-check` 閫氳繃

---

## 闃舵 3锛氬竷灞€涓庤矾鐢卞畬鍠勶紙棰勮 2 灏忔椂锛?
> 鐩爣锛氬畬鍠勫簲鐢ㄩ鏋讹紝娣诲姞缂哄け鐨勯〉闈㈠叆鍙ｃ€?
### 3.1 淇 `MainLayout.vue`

- 渚ц竟鏍忚彍鍗曢珮浜慨澶嶏細浣跨敤 `route.matched[0]?.path` 鍖归厤鐖惰矾鐢?- 娣诲姞"娣卞害鐮旂┒"鑿滃崟鍏ュ彛锛堥渶鍏堥€夋嫨鐭ヨ瘑绌洪棿锛?- 娣诲姞"妯″瀷閰嶇疆"鑿滃崟鍏ュ彛锛坄/settings/models`锛?
### 3.2 鏂板璺敱

```
/settings/models           鈫?ModelConfigView.vue  锛堟ā鍨嬮厤缃鐞嗭級
/403                       鈫?ForbiddenView.vue    锛堟棤鏉冮檺椤甸潰锛?```

### 3.3 淇璺敱瀹堝崼 `guards.ts`

- 浣跨敤 user store 鑰岄潪鐩存帴璇诲彇 localStorage
- 娣诲姞 Token 杩囨湡棰勬锛堣В鐮?exp 瀛楁锛?
### 3.4 鏂板缓 `ForbiddenView.vue`

- 鏄剧ず 403 鏃犳潈闄愭彁绀?- 鎻愪緵杩斿洖棣栭〉鎸夐挳

### 3.5 楠屾敹鏍囧噯

- [ ] 渚ц竟鏍忔墍鏈夎彍鍗曟纭珮浜?- [ ] 鎵€鏈夎矾鐢卞彲姝ｅ父璁块棶
- [ ] 鏃犳潈闄愭椂姝ｇ‘鏄剧ず 403
- [ ] 瀹堝崼姝ｇ‘鎷︽埅鏈櫥褰?鏃犳潈闄愯闂?
---

## 闃舵 4锛氱敤鎴风鐞嗘ā鍧楋紙棰勮 2-3 灏忔椂锛?
> 鐩爣锛氬畬鍠勭櫥褰曘€佷釜浜轰腑蹇冦€佺敤鎴风鐞嗐€佹ā鍨嬮厤缃〉闈€?
### 4.1 浼樺寲 `LoginView.vue`

- 娣诲姞鐧诲綍loading鐘舵€?- 娣诲姞琛ㄥ崟楠岃瘉鍙嶉
- 閿欒鎻愮ず鍙嬪ソ鍖栵紙鍖哄垎"鐢ㄦ埛鍚嶆垨瀵嗙爜閿欒"鍜?缃戠粶寮傚父"锛?
### 4.2 浼樺寲 `UserProfileView.vue`

- 灞曠ず瀹屾暣鐢ㄦ埛淇℃伅
- 淇敼瀵嗙爜鍔熻兘锛堥渶鍚庣鎺ュ彛鏀寔鎴栭€氳繃 updateUser 鐨?password 瀛楁锛?- 鍏宠仈妯″瀷閰嶇疆蹇嵎鍏ュ彛

### 4.3 浼樺寲 `UserManageView.vue`锛堢鐞嗗憳锛?
- 琛ㄦ牸鍒楀畬鏁村睍绀猴紙鐘舵€佷娇鐢?`StatusTag` 缁勪欢锛?- 鎵归噺鎿嶄綔鏀寔
- 纭寮圭獥浣跨敤 `ConfirmDialog` 缁勪欢

### 4.4 鏂板缓 `ModelConfigView.vue`

**鏍稿績鍔熻兘**锛?- 涓変釜 Tab锛歀LM / Embedding / Rerank
- 姣忎釜绫诲瀷灞曠ず鐢ㄦ埛绉佹湁閰嶇疆锛堝彲缂栬緫锛?- 鏂板/缂栬緫閰嶇疆琛ㄥ崟锛氭ā鍨嬬被鍨嬨€侀€氫俊鍗忚銆佹ā鍨嬪悕绉般€丅ase URL銆丄PI Key銆佹墿灞曢厤缃?- **杩炴帴娴嬭瘯**鎸夐挳锛氭祴璇曢厤缃槸鍚︽湁鏁堬紝鏄剧ず寤惰繜鍜?Embedding 缁村害
- 鍒犻櫎閰嶇疆锛堝鐞?409 鍏宠仈璧勬簮鎻愮ず锛?- API Key 杈撳叆妗嗕娇鐢ㄥ瘑鐮佹ā寮?
### 4.5 楠屾敹鏍囧噯

- [ ] 鐧诲綍娴佺▼瀹屾暣锛岄敊璇彁绀哄弸濂?- [ ] 涓汉涓績鍙甯告煡鐪嬪拰淇敼淇℃伅
- [ ] 绠＄悊鍛樺彲瀹屾暣绠＄悊鐢ㄦ埛锛堝垱寤?缂栬緫/鍒犻櫎/鍋滅敤/婵€娲?寮哄埗鐧诲嚭锛?- [ ] 妯″瀷閰嶇疆椤甸潰鍙?CRUD + 娴嬭瘯杩炴帴

---

## 闃舵 5锛氱煡璇嗙┖闂存ā鍧楋紙棰勮 4-5 灏忔椂锛?
> 鐩爣锛氬畬鍠勭┖闂淬€佺煡璇嗗簱銆佹枃妗ｃ€佹垚鍛樸€佹悳绱簲澶у瓙妯″潡銆?
### 5.1 浼樺寲 `SpaceListView.vue`

- 绌洪棿鍗＄墖灞曠ず瀹屾暣淇℃伅锛堟枃妗ｆ暟銆佸瓨鍌ㄧ敤閲忋€佸彲瑙佹€ф爣绛撅級
- 鎼滅储鍔熻兘浣跨敤 `SearchBar` 缁勪欢
- 鍏紑绌洪棿鍒楄〃灞曠ず
- 绌虹姸鎬佷娇鐢?`EmptyState` 缁勪欢
- 鍒嗛〉浣跨敤 `Pagination` 缁勪欢

### 5.2 浼樺寲 `SpaceDetailView.vue`

- 绌洪棿澶撮儴瀹屾暣淇℃伅灞曠ず
- Tab 瀵艰埅锛堢煡璇嗗簱/鎴愬憳/鎼滅储/娣卞害鐮旂┒锛?- 缂栬緫绌洪棿閰嶇疆瀵硅瘽妗嗭紙鍚嶇О銆佸彲瑙佹€с€佹弿杩般€佹爣绛撅級
- 鍒犻櫎绌洪棿纭

### 5.3 浼樺寲 `KnowledgeBaseView.vue`

- 鐭ヨ瘑搴撹〃鏍煎畬鏁村睍绀?- **鍒涘缓/缂栬緫瀵硅瘽妗嗚ˉ鍏呭畬鏁撮厤缃?*锛?  - 鍩烘湰淇℃伅Tab锛氬悕绉般€佹弿杩?  - 鍒囧垎绛栫暐Tab锛氭敮鎸?4 绉嶇瓥鐣ュ垏鎹紙recursive/fixed_size/markdown/semantic锛夛紝姣忕鏄剧ず瀵瑰簲鍙傛暟
  - 瑙ｆ瀽閰嶇疆Tab锛氭彁鍙栧浘鐗囥€佹彁鍙栬〃鏍笺€丱CR銆佷繚鐣欑粨鏋勩€佺紪鐮?  - 鍚戦噺鍖栭厤缃甌ab锛氭ā鍨嬮€夋嫨锛堜笅鎷夋浠庡彲鐢ㄦā鍨嬪垪琛ㄨ幏鍙栵級銆佺淮搴︺€佹壒澶勭悊澶у皬
  - 闂鐢熸垚Tab锛氬惎鐢ㄥ紑鍏炽€丩LM 閫夋嫨銆佹瘡鍧楁渶澶ч棶棰樻暟銆佽嚜瀹氫箟鎻愮ず璇?- 鐭ヨ瘑搴撻厤缃鎯呮煡鐪?- 褰掓。/鍙栨秷褰掓。

### 5.4 浼樺寲 `DocumentView.vue`

- 鏂囨。琛ㄦ牸灞曠ず瀹屾暣瀛楁锛堢姸鎬佷娇鐢?`StatusTag`锛屾枃浠跺ぇ灏忔牸寮忓寲锛屽鐞嗚繘搴︼級
- **鎷栨嫿涓婁紶**淇濈暀锛堝凡鏈夊疄鐜帮級
- 涓婁紶杩涘害鏉?- **澶勭悊涓殑鏂囨。鑷姩杞鍒锋柊鐘舵€?*
- 鎵归噺瑙﹀彂瑙ｆ瀽鍔熻兘
- 閲嶆柊瑙ｆ瀽鍔熻兘
- 涓嬭浇鏂囨。鍔熻兘
- 浣跨敤 `Pagination` 缁勪欢

### 5.5 浼樺寲 `DocumentDetailView.vue`

- 鏂囨。鍩烘湰淇℃伅灞曠ず
- 鍒嗗潡鍒楄〃锛堜娇鐢?`Pagination` 鍒嗛〉锛?- 鍒嗗潡鍐呭灞曠ず
- 鍋囪鎬ч棶棰樻爣绛惧睍绀?
### 5.6 浼樺寲 `MemberView.vue`

- 鎴愬憳鍒楄〃琛ㄦ牸锛堣鑹蹭娇鐢?`StatusTag` 鎴栬嚜瀹氫箟 Tag锛?- 閭€璇锋垚鍛樺璇濇锛堥偖绠便€佽鑹查€夋嫨銆佹湁鏁堟湡锛?- 閭€璇烽摼鎺ュ鍒跺姛鑳?- 瑙掕壊淇敼
- 绉婚櫎鎴愬憳纭
- 绂诲紑绌洪棿鍔熻兘

### 5.7 閲嶅啓 `SearchView.vue`

- **鍏堥€夋嫨鐭ヨ瘑搴?*锛屽啀杩涜鎼滅储
- 鎼滅储妯″紡浠庡悗绔幏鍙栧彲鐢ㄦā寮忓垪琛?- 楂樼骇璁剧疆闈㈡澘锛?  - 鏉冮噸閰嶇疆锛堝悜閲忔潈閲?+ BM25 鏉冮噸锛屾€诲拰 = 1 鐨勮仈鍔ㄦ牎楠岋級
  - Rerank 閰嶇疆锛堝惎鐢ㄥ紑鍏炽€乼op_k銆佹ā鍨嬮€夋嫨锛?  - LLM 鍥炵瓟閰嶇疆锛堝惎鐢ㄥ紑鍏炽€佹ā鍨嬨€佹俯搴︺€乼op_p锛?  - 鏌ヨ鏀瑰啓閰嶇疆锛堢瓥鐣ラ€夋嫨銆佸弬鏁伴厤缃級
  - 鍒嗘暟闃堝€笺€佺紦瀛樺紑鍏?- 缁撴灉鍗＄墖灞曠ず锛氬唴瀹归珮浜€佹潵婧愭枃妗ｃ€佸垎鏁般€佹枃浠朵俊鎭?- LLM 鍥炵瓟鍗曠嫭灞曠ず鍖哄煙
- 鎼滅储鑰楁椂鍜岀紦瀛樼姸鎬佹彁绀?- 浣跨敤 `EmptyState` 缁勪欢

### 5.8 楠屾敹鏍囧噯

- [ ] 绌洪棿瀹屾暣 CRUD 娴佺▼
- [ ] 鐭ヨ瘑搴撳垱寤烘椂鍙厤缃畬鏁村垏鍒?瑙ｆ瀽/鍚戦噺鍖?闂鐢熸垚鍙傛暟
- [ ] 鏂囨。涓婁紶鈫掕Е鍙戣В鏋愨啋鏌ョ湅鍒嗗潡瀹屾暣娴佺▼
- [ ] 鎼滅储鍔熻兘姝ｅ父锛岄珮绾у弬鏁扮敓鏁?- [ ] 鎴愬憳閭€璇封啋鍔犲叆鈫掕鑹插彉鏇村畬鏁存祦绋?- [ ] 鎵€鏈夊垪琛ㄩ〉鍒嗛〉姝ｅ父
- [ ] 鎵€鏈夌姸鎬佸瓧娈典娇鐢?Tag 缁勪欢灞曠ず

---

## 闃舵 6锛欰I 瀵硅瘽妯″潡锛堥璁?3-4 灏忔椂锛?
> 鐩爣锛氬畬鍠勮亰澶╃晫闈紝淇 SSE 娴佸紡闂锛屾坊鍔犱細璇濈鐞嗐€?
### 6.1 閲嶅啓 `ChatView.vue`

**宸︿晶杈规爮**锛?- 浼氳瘽鍒楄〃锛堜粠 `/qa/sessions` 鑾峰彇锛屽甫鍒嗛〉/鏃犻檺婊氬姩锛?- 鏂板缓浼氳瘽鎸夐挳
- 浼氳瘽椤癸細棰勮鏂囨湰 + 鍒犻櫎鎸夐挳 + 璁剧疆鎸夐挳
- 浼氳瘽鎼滅储锛堝彲閫夛級

**涓昏亰澶╁尯**锛?- 娑堟伅姘旀场鍒楄〃锛堢敤鎴?AI 鍖哄垎鏍峰紡锛?- AI 娑堟伅 Markdown 娓叉煋锛堜唬鐮侀珮浜級
- **SSE 娴佸紡杈撳嚭**锛氶€愬瓧杩藉姞鏄剧ず锛屽甫鍏夋爣鍔ㄧ敾
- 鑷姩婊氬姩鍒板簳閮?- 绌虹姸鎬佹杩庣晫闈?
**杈撳叆鍖哄煙**锛?- 澶氳鏂囨湰杈撳叆妗?- 鍙戦€佹寜閽紙Enter 鍙戦€侊紝Shift+Enter 鎹㈣锛?- 娴佸紡/闈炴祦寮忓垏鎹㈠紑鍏?- 妯″瀷閫夋嫨涓嬫媺妗嗭紙浠?`/ai-chat/models` 鑾峰彇锛?- 楂樼骇鍙傛暟鎶樺彔闈㈡澘锛坱emperature銆乼op_p銆乵ax_tokens銆乻ystem_prompt锛?
**浼氳瘽閰嶇疆瀵硅瘽妗?*锛?- 鍘嬬缉鍚敤寮€鍏?- 鍘嬬缉绛栫暐閫夋嫨锛坰ummary/sliding_window/keep_recent/truncate锛?- 闃堝€奸厤缃紙trigger threshold銆乼arget tokens锛?- 淇濈暀鏈€杩戞秷鎭暟
- 鑷畾涔夋憳瑕佹彁绀鸿瘝

**鍏抽敭淇**锛?- SSE 娴佹坊鍔?AbortController锛屾敮鎸佸彇娑?- SSE error 浜嬩欢姝ｇ‘鏄剧ず缁欑敤鎴?- 缁勪欢鍗歌浇鏃跺彇娑堣繘琛屼腑鐨勬祦
- 鏂颁細璇濈殑棣栨潯娑堟伅鍙戦€佸悗锛屼粠鍝嶅簲涓幏鍙?`session_id` 骞舵洿鏂颁細璇濆垪琛?
### 6.2 楠屾敹鏍囧噯

- [ ] 鑳芥甯稿彂閫佹秷鎭苟鏀跺埌 AI 鍥炲
- [ ] 娴佸紡杈撳嚭閫愬瓧鏄剧ず锛屽彲涓€斿彇娑?- [ ] 浼氳瘽鍒楄〃姝ｇ‘灞曠ず锛屽彲鍒囨崲/鍒犻櫎
- [ ] 浼氳瘽閰嶇疆鍙垱寤?鏌ョ湅/鍒犻櫎
- [ ] 妯″瀷閫夋嫨鍜岄珮绾у弬鏁扮敓鏁?- [ ] 缁勪欢鍗歌浇鏃舵棤鍐呭瓨娉勬紡

---

## 闃舵 7锛氭繁搴︾爺绌舵ā鍧楋紙棰勮 2-3 灏忔椂锛?
> 鐩爣锛氬畬鍠勭爺绌跺彂璧枫€佽繘搴﹀睍绀恒€佹姤鍛婃煡鐪嬪姛鑳姐€?
### 7.1 閲嶅啓 `ResearchView.vue`

**鐮旂┒鍙戣捣琛ㄥ崟**锛?- 鐭ヨ瘑绌洪棿閫夋嫨锛堝繀閫夛級
- 鐮旂┒鏌ヨ杈撳叆
- 鐮旂┒妯″紡閫夋嫨锛坬uick/standard/deep锛屾樉绀鸿€楁椂棰勪及锛?- 鎼滅储鏉ユ簮閫夋嫨锛坕nternal/external/hybrid锛?- 楂樼骇璁剧疆鎶樺彔闈㈡澘锛?  - 鍐呴儴妫€绱㈤厤缃紙鐭ヨ瘑搴撻€夋嫨銆佹绱㈡ā寮忋€乼op_k銆佸悜閲?BM25 鏉冮噸銆丷erank 閰嶇疆銆佹煡璇㈡敼鍐欓厤缃級
  - 澶栭儴鎼滅储閰嶇疆锛堟湇鍔″晢閫夋嫨銆佹渶澶х粨鏋滄暟銆佹悳绱㈡繁搴︺€佹椂闂磋寖鍥达級
  - LLM 閰嶇疆锛堟ā鍨嬮€夋嫨銆佹俯搴︺€乼op_p銆乵ax_tokens锛?
**鐮旂┒杩涘害灞曠ず**锛?- 杩涘害鏉★紙鐧惧垎姣旓級
- 褰撳墠姝ラ鎻忚堪
- 闃舵鎸囩ず锛堝垎鏋愪腑鈫掓绱腑鈫掔敓鎴愭姤鍛婁腑锛?- 宸插畬鎴?鎬讳换鍔℃暟
- **鍙栨秷鎸夐挳**锛堢湡姝ｄ腑鏂?SSE 娴侊級

**鐮旂┒鎶ュ憡灞曠ず**锛?- Markdown 娓叉煋锛堜唬鐮侀珮浜€佺洰褰曞鑸級
- 澶嶅埗鎶ュ憡鍐呭
- 鎼滅储鎽樿锛堝唴閮?澶栭儴妫€绱㈡鏁般€佸叧閿潵婧愶級
- 缁熻淇℃伅锛堣€楁椂銆佹绱㈡鏁般€佺粨鏋滄暟銆佹姤鍛婂瓧鏁般€佹潵婧愭暟锛?
### 7.2 浼樺寲 `ResearchHistoryView.vue`

- 鍘嗗彶璁板綍琛ㄦ牸锛堢姸鎬佺瓫閫夈€佸垎椤碉級
- 鐘舵€佷娇鐢?`StatusTag` 缁勪欢
- 鎶ュ憡璇︽儏瀵硅瘽妗嗭紙Markdown 娓叉煋锛?- 鍒犻櫎纭锛堣繍琛屼腑鐨勭爺绌舵彁绀轰笉鍙垹闄わ級
- 鐮旂┒浠诲姟鍒楄〃灞曠ず
- 鎼滅储缁撴灉鏉ユ簮鍒楄〃

### 7.3 楠屾敹鏍囧噯

- [ ] 鑳芥甯稿彂璧锋繁搴︾爺绌讹紙蹇€?鏍囧噯/娣卞害涓夌妯″紡锛?- [ ] SSE 娴佸紡杩涘害瀹炴椂灞曠ず
- [ ] 鐮旂┒鎶ュ憡 Markdown 娓叉煋姝ｇ‘
- [ ] 鍙彇娑堣繘琛屼腑鐨勭爺绌?- [ ] 鍘嗗彶璁板綍瀹屾暣灞曠ず锛屽彲鏌ョ湅/鍒犻櫎
- [ ] 楂樼骇鍙傛暟锛堝唴閮?澶栭儴鎼滅储閰嶇疆锛夋纭紶閫掔粰鍚庣

---

## 闃舵 8锛氶€氱敤缁勪欢涓庢牱寮忕粺涓€锛堥璁?2 灏忔椂锛?
> 鐩爣锛氱粺涓€缁勪欢浣跨敤锛屾秷闄ら噸澶嶄唬鐮併€?
### 8.1 纭繚閫氱敤缁勪欢琚疄闄呬娇鐢?
鎵€鏈夊垪琛ㄩ〉浣跨敤锛?- `Pagination.vue` 鈥?鍒嗛〉
- `SearchBar.vue` 鈥?鎼滅储
- `StatusTag.vue` 鈥?鐘舵€佹爣绛?- `EmptyState.vue` 鈥?绌虹姸鎬?- `LoadingOverlay.vue` 鈥?鍔犺浇閬僵
- `ConfirmDialog.vue` 鈥?纭寮圭獥

### 8.2 琛ュ厖缂哄け鐨勯€氱敤缁勪欢

- `MarkdownRenderer.vue` 鈥?缁熶竴鐨?Markdown 娓叉煋缁勪欢锛坈hat + research 鍏辩敤锛?- `SSEStreamText.vue` 鈥?娴佸紡鏂囨湰灞曠ず缁勪欢锛堝甫鍏夋爣鍔ㄧ敾锛?- `ModelSelect.vue` 鈥?妯″瀷閫夋嫨涓嬫媺妗嗭紙浠庡彲鐢ㄦā鍨嬪垪琛ㄨ幏鍙栭€夐」锛?
### 8.3 鏍峰紡缁熶竴

- 缁熶竴浣跨敤 Element Plus CSS 鍙橀噺瑕嗙洊
- 纭繚鎵€鏈夐〉闈竴鑷寸殑闂磋窛銆佸渾瑙掋€侀槾褰遍鏍?- 鍝嶅簲寮忓竷灞€鍩虹閫傞厤

### 8.4 楠屾敹鏍囧噯

- [ ] 鎵€鏈夊垪琛ㄩ〉浣跨敤 `Pagination` 缁勪欢
- [ ] 鎵€鏈夋悳绱娇鐢?`SearchBar` 缁勪欢
- [ ] 鎵€鏈夌姸鎬佸瓧娈典娇鐢?`StatusTag` 缁勪欢
- [ ] Chat 鍜?Research 鍏辩敤 `MarkdownRenderer` 缁勪欢
- [ ] 鏃犻噸澶嶇殑 Markdown 娓叉煋閫昏緫

---

## 闃舵 9锛氭祴璇曚笌浼樺寲锛堥璁?2-3 灏忔椂锛?
> 鐩爣锛氭牳蹇冮€昏緫鏈夋祴璇曡鐩栵紝鎬ц兘鍜屼綋楠屼紭鍖栥€?
### 9.1 鍗曞厓娴嬭瘯

- API 灞傛祴璇曪紙mock axios锛岄獙璇佽姹傚弬鏁板拰 URL锛?- Store 娴嬭瘯锛堥獙璇?actions 鍜岀姸鎬佸彉鏇达級
- 宸ュ叿鍑芥暟娴嬭瘯锛坒ormat銆乻torage銆乵arkdown锛?
### 9.2 鎬ц兘浼樺寲

- 璺敱鎳掑姞杞斤紙宸叉湁锛岄獙璇侊級
- 澶у垪琛ㄨ櫄鎷熸粴鍔紙鏂囨。鍒楄〃銆佹秷鎭垪琛級
- Markdown 娓叉煋闃叉姈
- 鍥剧墖/璧勬簮鎸夐渶鍔犺浇

### 9.3 鐢ㄦ埛浣撻獙浼樺寲

- 鎵€鏈夋搷浣滄坊鍔?loading 鐘舵€?- 閿欒鎻愮ず鍙嬪ソ鍖?- 琛ㄥ崟杈撳叆璁板繂锛堥珮绾ц缃姌鍙犻潰鏉跨姸鎬侊級
- 鏂囨。澶勭悊鐘舵€佽疆璇紙processing 鈫?completed锛?- 閿洏蹇嵎閿紙鎼滅储 Ctrl+K锛屾柊寤?Ctrl+N锛?
### 9.4 楠屾敹鏍囧噯

- [ ] 鏍稿績妯″潡鏈夊崟鍏冩祴璇?- [ ] `npm run test:unit` 閫氳繃
- [ ] `npm run lint` 閫氳繃
- [ ] `npm run type-check` 閫氳繃
- [ ] `npm run build` 鏋勫缓鎴愬姛

---

## 寮€鍙戦『搴忔€荤粨

```
闃舵 0: 鍩虹璁炬柦 鈹€鈹€鈹€鈹€鈹€鈹€鈫?鍙仈璋冨悗绔?闃舵 1: API 灞傞噸寤?鈹€鈹€鈹€鈹€鈫?鎵€鏈夋帴鍙ｅ彲鐢?闃舵 2: Store 閲嶆瀯 鈹€鈹€鈹€鈹€鈫?鐘舵€佺鐞嗗彲闈?闃舵 3: 甯冨眬璺敱 鈹€鈹€鈹€鈹€鈹€鈹€鈫?搴旂敤楠ㄦ灦瀹屾暣
闃舵 4: 鐢ㄦ埛绠＄悊 鈹€鈹€鈹€鈹€鈹€鈹€鈫?璁よ瘉+鐢ㄦ埛+妯″瀷閰嶇疆
闃舵 5: 鐭ヨ瘑绌洪棿 鈹€鈹€鈹€鈹€鈹€鈹€鈫?鏍稿績 CRUD 妯″潡
闃舵 6: AI 瀵硅瘽 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈫?鑱婂ぉ鍔熻兘瀹屾暣
闃舵 7: 娣卞害鐮旂┒ 鈹€鈹€鈹€鈹€鈹€鈹€鈫?鐮旂┒鍔熻兘瀹屾暣
闃舵 8: 缁勪欢鏍峰紡 鈹€鈹€鈹€鈹€鈹€鈹€鈫?浠ｇ爜璐ㄩ噺缁熶竴
闃舵 9: 娴嬭瘯浼樺寲 鈹€鈹€鈹€鈹€鈹€鈹€鈫?鍙氦浠?```

**鎬昏棰勪及锛?0-28 灏忔椂**

---

## 鎶€鏈喅绛?
| 鍐崇瓥椤?| 閫夋嫨 | 鐞嗙敱 |
|--------|------|------|
| SSE 娴佸紡瀹炵幇 | 鍘熺敓 `fetch` + `ReadableStream` | POST 璇锋眰涓嶆敮鎸?EventSource |
| Token 鍒锋柊 | 璇锋眰鎷︽埅鍣ㄨ嚜鍔ㄥ埛鏂?+ 璇锋眰闃熷垪 | 鐢ㄦ埛浣撻獙浼樺厛锛岄伩鍏嶉绻佺櫥鍑?|
| 鐘舵€佺鐞?| Pinia Composition API | 椤圭洰宸蹭娇鐢紝淇濇寔涓€鑷?|
| UI 缁勪欢搴?| Element Plus | 椤圭洰宸蹭娇鐢紝淇濇寔涓€鑷?|
| Markdown 娓叉煋 | `marked` + `highlight.js` | 椤圭洰宸蹭娇鐢紝淇濇寔涓€鑷?|
| 鏂囦欢缁撴瀯 | 鎸夊姛鑳芥ā鍧楀垝鍒嗭紙api/stores/views/components锛?| 鐜版湁缁撴瀯鍚堢悊锛屼繚鎸佷笉鍙?|

