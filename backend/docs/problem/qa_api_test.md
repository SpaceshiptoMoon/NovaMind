C:\Users\xl\Desktop\backend_project\intelligent\backend>c:\Users\xl\Desktop\backend_project\intelligent\backend\.venv\Scripts\python.exe c:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_qa_api.py
============================================================
  智能问答模块 API 接口测试
  目标服务: http://127.0.0.1:8100
  测试时间: 2026-04-16 16:53:13
============================================================

服务健康检查: 200 - healthy

============================================================
  登录管理员账号
============================================================

[使用管理员账号登录] admin
  状态码: 200
  管理员 [admin] 登录成功

============================================================
  一、智能问答接口测试 (/api/v1/qa)
============================================================

  使用会话 ID: test_session_l5yyncty

============================================================
  测试 1: 添加消息 (POST /api/v1/qa/message)
============================================================

[添加消息]
  状态码: 200
  请求: {'content': '这是一条测试消息，请帮我解释一下机器学习的基本概念', 'role': 'user', 'session_id': 'test_session_l5yyncty'}
  消息 ID: 103

============================================================
  测试 1 续: 添加 assistant 消息
============================================================

[添加 assistant 消息]
  状态码: 200
  消息 ID: 104

============================================================
  测试 2: 获取会话消息列表 (GET /api/v1/qa/session/{session_id})
============================================================

[获取会话消息列表]
  状态码: 200
  session_id: test_session_l5yyncty
  消息数量: 2

============================================================
  测试 3: 获取会话列表 (GET /api/v1/qa/sessions)
============================================================

[获取会话列表]
  状态码: 200
  请求参数: limit=10, offset=0
  会话总数: 1
  当前页数量: 1

============================================================
  测试 4: 更新消息 (PUT /api/v1/qa/message/{message_id})
============================================================

[更新消息]
  状态码: 200
  message_id: 103
  更新内容: {'content': '更新后的消息内容 - 测试修改'}
  更新后内容: 更新后的消息内容 - 测试修改

============================================================
  测试 7: 获取对话上下文 (GET /api/v1/qa/context/{session_id})
============================================================

[获取对话上下文]
  状态码: 200
  session_id: test_session_l5yyncty
  limit: 10
  上下文消息数: 2

============================================================
  测试 5: 删除消息 (DELETE /api/v1/qa/message/{message_id})
============================================================

[删除消息]
  状态码: 204
  message_id: 104
  消息 104 已删除
  验证: 消息 104 确实已从列表中移除

============================================================
  二、AI 聊天接口测试 (/api/v1/ai-chat)
============================================================

  使用会话 ID: test_session_qc11yfbx

============================================================
  测试 12: 健康检查 (GET /api/v1/ai-chat/health) [无需认证]
============================================================

[健康检查]
  状态码: 200
  服务状态: healthy
  消息: AI chat service is running

============================================================
  测试 13: 获取可用模型列表 (GET /api/v1/ai-chat/models)
============================================================

[获取可用模型列表]
  状态码: 200
  可用模型: ['qwen3-max-2026-01-23', 'qwen3.5-27b', 'qwen3.5-plus', 'qwen3.5-plus-2026-02-15']

============================================================
  测试 8: AI 对话 - 非流式 (POST /api/v1/ai-chat/chat)
============================================================
  请求参数: {'content': '你好，请用一句话回答：1+1等于几？', 'session_id': 'test_session_qc11yfbx'}
  [调试] 开始发送请求, 超时=60s, 等待 LLM 响应...
  [调试] 收到响应, 状态码: 200
  [调试] 响应头: {'date': 'Thu, 16 Apr 2026 08:53:13 GMT', 'server': 'uvicorn', 'content-length': '448', 'content-type': 'application/json', 'x-trace-id': 'trace-0a4890453e29488a'}
  [调试] 响应体: {"session_id":"test_session_qc11yfbx","user_message":{"id":105,"content":"你好，请用一句话回答：1+1等于几？","role":"user","created_at":"2026-04-16T16:53:14"},"ai_message":{"id":106,"content":"1+1等于2。","role":"assistant","created_at":"2026-04-16T16:53:15"},"conversation_history":[{"role":"system","content":"You are a helpful assistant."},{"id":105,"role":"user","content":"你好，请用一句话回答：1+1等于几？"}]}

[AI 对话（非流式）]
  状态码: 200
  用户消息 ID: 105
  AI 回复: 1+1等于2。
  对话历史条数: 2

============================================================
  测试 9: AI 对话 - 流式 SSE (POST /api/v1/ai-chat/chat-stream)
============================================================
  请求参数: {'content': '请用一句话回答：天空为什么是蓝色的？', 'session_id': 'test_session_3katn5hv'}
  [调试] 开始发送流式请求, 超时=120s...
  [调试] HTTP 连接建立, 状态码: 200
  [调试] 响应头 Content-Type: text/event-stream; charset=utf-8

[AI 对话（流式 SSE）- HTTP 状态码]
  状态码: 200
  [调试] 开始读取 SSE 流...
  [调试-原始行1] data: {"type": "user_message", "data": {"id": 107, "content": "请用一句话回答：天空为什么是蓝色的？", "role": "user", "created_at": "2026-04-16 16:53:15"}}
    [user_message] 用户消息已保存, id=107
  [调试-原始行2] (空行)
  [调试-原始行3] data: {"type": "content", "data": {"content": "天空", "session_id": "test_session_3katn5hv"}}
    [content] 天空
  [调试-原始行4] (空行)
  [调试-原始行5] data: {"type": "content", "data": {"content": "之所以", "session_id": "test_session_3katn5hv"}}
    [content] 之所以
  [调试-原始行6] (空行)
  [调试-原始行7] data: {"type": "content", "data": {"content": "是蓝色的", "session_id": "test_session_3katn5hv"}}
    [content] 是蓝色的
  [调试-原始行8] (空行)
  [调试-原始行9] data: {"type": "content", "data": {"content": "，是因为大气中的分子对", "session_id": "test_session_3katn5hv"}}
    [content] ，是因为大气中的分子对
  [调试-原始行10] (空行)
  [调试-原始行11] data: {"type": "content", "data": {"content": "太阳光中波长", "session_id": "test_session_3katn5hv"}}
  [调试-原始行12] (空行)
  [调试-原始行13] data: {"type": "content", "data": {"content": "较短的蓝光散", "session_id": "test_session_3katn5hv"}}
  [调试-原始行14] (空行)
  [调试-原始行15] data: {"type": "content", "data": {"content": "射得比其他颜色", "session_id": "test_session_3katn5hv"}}
  [调试-原始行16] (空行)
  [调试-原始行17] data: {"type": "content", "data": {"content": "更强烈（瑞利散", "session_id": "test_session_3katn5hv"}}
  [调试-原始行18] (空行)
  [调试-原始行19] data: {"type": "content", "data": {"content": "射）。", "session_id": "test_session_3katn5hv"}}
  [调试-原始行20] (空行)
    [done] AI 回复完成, id=108
  [调试] 共读取 22 行原始数据, 11 个 SSE 事件
  AI 回复内容: 天空之所以是蓝色的，是因为大气中的分子对太阳光中波长较短的蓝光散射得比其他颜色更强烈（瑞利散射）。

============================================================
  测试 10: 获取聊天历史 (GET /api/v1/ai-chat/chat-history)
============================================================

[获取聊天历史]
  状态码: 200
  session_id: test_session_qc11yfbx
  历史消息数: 2

============================================================
  测试 11: 清除聊天历史 (DELETE /api/v1/ai-chat/clear-chat)
============================================================

[清除聊天历史]
  状态码: 204
  session_id: test_session_qc11yfbx
  聊天历史已清除

============================================================
  三、会话配置接口测试 (/api/v1/sessions/{session_id}/config)
============================================================

  使用会话 ID: test_session_vjgutqwe

  [准备] 先创建消息让会话存在...
  准备消息状态码: 200

============================================================
  测试 14: 创建会话配置 (POST /api/v1/sessions/{session_id}/config)
============================================================

[创建会话配置]
  状态码: 201
  session_id: test_session_vjgutqwe
  请求: {'compression': {'enable_compression': True, 'strategy': 'summary', 'threshold': 3000, 'target_tokens': 500, 'keep_recent': 2, 'custom_prompt': '请对以下对话进行摘要，保留关键信息'}}
  配置 ID: 66
  压缩策略: summary
  压缩阈值: 3000

============================================================
  测试 14 续: 重复创建会话配置（应返回 409）
============================================================

[重复创建会话配置]
  状态码: 409
  正确返回 409 Conflict

============================================================
  测试 15: 获取会话配置 (GET /api/v1/sessions/{session_id}/config)
============================================================

[获取会话配置]
  状态码: 200
  session_id: test_session_vjgutqwe
  配置 ID: 66
  压缩配置: {'strategy': 'summary', 'threshold': 3000, 'keep_recent': 2, 'custom_prompt': '请对以下对话进行摘要，保留关键信息', 'target_tokens': 500, 'enable_compression': True}

============================================================
  测试 6: 删除会话 (DELETE /api/v1/qa/session/{session_id})
============================================================
  已创建待删除会话: test_session_yrmb9hka

[删除会话]
  状态码: 204
  session_id: test_session_yrmb9hka
  会话 test_session_yrmb9hka 已删除

[测试失败] 删除后查询应返回 404，实际: 200

C:\Users\xl\Desktop\backend_project\intelligent\backend>

C:\Users\xl\Desktop\backend_project\intelligent\backend>c:\Users\xl\Desktop\backend_project\intelligent\backend\.venv\Scripts\python.exe c:/Users/xl/Desktop/backend_project/intelligent/backend/tests/test_ai_chat_db.py

============================================================
  登录
============================================================
  登录成功

============================================================
  测试 1: 非流式对话 → 验证数据库持久化
============================================================
  session_id: db_test_2efzlc7d
  发送请求...
  用户消息 ID: 111
  AI 回复内容: 1+1等于2。

  [验证] 查询聊天历史 session_id=db_test_2efzlc7d
  消息数量: 2
    [0] role=user, content=你好，请用一句话回答：1+1等于几？
    [1] role=assistant, content=1+1等于2。
  [通过] 非流式 消息持久化验证成功

============================================================
  测试 2: 流式对话 → 验证数据库持久化
============================================================
  session_id: db_test_iun81h7q
  发送流式请求...
  流式完成, AI 消息 ID: 114
  AI 回复内容: 天空之所以是蓝色的，是因为大气中的分子对太阳光中波长较短的蓝光散射得比其他颜色更强烈（瑞利散射）。

  [验证] 查询聊天历史 session_id=db_test_iun81h7q
  消息数量: 2
    [0] role=user, content=请用一句话回答：天空为什么是蓝色的？
    [1] role=assistant, content=天空之所以是蓝色的，是因为大气中的分子对太阳光中波长较短的蓝光散射得比其他颜色更强烈（瑞利散射）。
  [通过] 流式 消息持久化验证成功

============================================================
  测试结果
============================================================
  非流式对话: 通过
  流式对话: 通过

  所有测试通过！消息已成功持久化到数据库。

C:\Users\xl\Desktop\backend_project\intelligent\backend>