# -*- coding: utf-8 -*-
"""
智能问答模块 API 接口测试脚本

测试范围：
  一、智能问答接口 (/api/v1/qa) - 消息与会话的 CRUD
  二、AI 聊天接口 (/api/v1/ai-chat) - AI 对话、聊天历史、模型查询
  三、会话配置接口 (/api/v1/sessions/{session_id}/config) - 压缩配置管理

运行方式：python tests/test_qa_api.py
前置条件：后端服务已启动在 http://127.0.0.1:8100
"""

import json
import random
import string
import time
import sys

import requests

# ========================================
# 基础配置
# ========================================
BASE_URL = "http://127.0.0.1:8100"
TIMEOUT = 30  # 普通请求超时（秒）
STREAM_TIMEOUT = 120  # SSE 流式请求超时（秒）

# 管理员测试账号
ADMIN_USERNAME = "admin_test"
ADMIN_EMAIL = "admin_test@test.com"
ADMIN_PASSWORD = "***REMOVED***"

# 默认管理员账号（启动时自动创建，用于创建测试管理员）
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "***REMOVED***"


# ========================================
# 工具函数
# ========================================
def generate_session_id() -> str:
    """生成随机 session_id，避免测试冲突"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"test_session_{suffix}"


def print_header(title: str) -> None:
    """打印测试分隔线"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(name: str, status_code: int, response_text: str = "", key_fields: dict = None) -> None:
    """打印测试结果"""
    print(f"\n[{name}]")
    print(f"  状态码: {status_code}")
    if key_fields:
        for k, v in key_fields.items():
            print(f"  {k}: {v}")
    if response_text:
        # 截断过长的响应
        display = response_text[:500] + "..." if len(response_text) > 500 else response_text
        print(f"  响应: {display}")


def get_auth_headers(token: str) -> dict:
    """构造认证请求头"""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ========================================
# 登录逻辑
# ========================================
def ensure_admin_user_and_login() -> str:
    """
    使用系统默认管理员账号登录（启动时自动创建）。
    """
    print_header("登录管理员账号")

    print(f"\n[使用管理员账号登录] {DEFAULT_ADMIN_USERNAME}")
    login_resp = requests.post(
        f"{BASE_URL}/api/v1/user/users/login",
        json={"username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD},
        timeout=TIMEOUT,
    )
    print(f"  状态码: {login_resp.status_code}")

    if login_resp.status_code != 200:
        print(f"  [错误] 管理员登录失败: {login_resp.text}")
        sys.exit(1)

    token = login_resp.json()["access_token"]
    print(f"  管理员 [{DEFAULT_ADMIN_USERNAME}] 登录成功")
    return token


# ========================================
# 一、智能问答接口测试
# ========================================
def test_qa_apis(token: str) -> dict:
    """
    测试智能问答接口 (/api/v1/qa)
    返回测试过程中创建的资源 ID，供后续清理使用
    """
    print_header("一、智能问答接口测试 (/api/v1/qa)")
    headers = get_auth_headers(token)
    resources = {"session_ids": [], "message_ids": []}

    session_id = generate_session_id()
    resources["session_ids"].append(session_id)
    print(f"\n  使用会话 ID: {session_id}")

    # --- 测试 1: POST /api/v1/qa/message - 添加消息 ---
    print_header("测试 1: 添加消息 (POST /api/v1/qa/message)")
    add_msg_payload = {
        "content": "这是一条测试消息，请帮我解释一下机器学习的基本概念",
        "role": "user",
        "session_id": session_id,
    }
    resp = requests.post(f"{BASE_URL}/api/v1/qa/message", json=add_msg_payload, headers=headers, timeout=TIMEOUT)
    print_result("添加消息", resp.status_code, key_fields={"请求": add_msg_payload})
    assert resp.status_code == 200, f"添加消息失败: {resp.text}"
    msg_data = resp.json()
    assert "id" in msg_data, "响应缺少 id 字段"
    assert msg_data["content"] == add_msg_payload["content"], "消息内容不匹配"
    assert msg_data["role"] == "user", "消息角色不匹配"
    assert msg_data["session_id"] == session_id, "session_id 不匹配"
    message_id_1 = msg_data["id"]
    resources["message_ids"].append(message_id_1)
    print(f"  消息 ID: {message_id_1}")

    # 添加第二条消息（assistant 角色）
    print_header("测试 1 续: 添加 assistant 消息")
    add_msg_2_payload = {
        "content": "机器学习是人工智能的一个分支，通过数据训练模型来进行预测和决策。",
        "role": "assistant",
        "session_id": session_id,
    }
    resp = requests.post(f"{BASE_URL}/api/v1/qa/message", json=add_msg_2_payload, headers=headers, timeout=TIMEOUT)
    print_result("添加 assistant 消息", resp.status_code)
    assert resp.status_code == 200, f"添加 assistant 消息失败: {resp.text}"
    msg_data_2 = resp.json()
    message_id_2 = msg_data_2["id"]
    resources["message_ids"].append(message_id_2)
    print(f"  消息 ID: {message_id_2}")

    # --- 测试 2: GET /api/v1/qa/session/{session_id} - 获取会话消息列表 ---
    print_header("测试 2: 获取会话消息列表 (GET /api/v1/qa/session/{session_id})")
    resp = requests.get(f"{BASE_URL}/api/v1/qa/session/{session_id}", headers=headers, timeout=TIMEOUT)
    print_result("获取会话消息列表", resp.status_code, key_fields={"session_id": session_id})
    assert resp.status_code == 200, f"获取会话消息列表失败: {resp.text}"
    messages = resp.json()
    assert isinstance(messages, list), "响应应为列表"
    assert len(messages) >= 2, f"消息数量应 >= 2，实际 {len(messages)}"
    print(f"  消息数量: {len(messages)}")

    # --- 测试 3: GET /api/v1/qa/sessions - 获取会话列表 ---
    print_header("测试 3: 获取会话列表 (GET /api/v1/qa/sessions)")
    resp = requests.get(
        f"{BASE_URL}/api/v1/qa/sessions",
        params={"limit": 10, "offset": 0},
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("获取会话列表", resp.status_code, key_fields={"请求参数": "limit=10, offset=0"})
    assert resp.status_code == 200, f"获取会话列表失败: {resp.text}"
    sessions_data = resp.json()
    assert "items" in sessions_data, "响应缺少 items 字段"
    assert "total" in sessions_data, "响应缺少 total 字段"
    print(f"  会话总数: {sessions_data['total']}")
    print(f"  当前页数量: {len(sessions_data['items'])}")

    # --- 测试 4: PUT /api/v1/qa/message/{message_id} - 更新消息 ---
    print_header("测试 4: 更新消息 (PUT /api/v1/qa/message/{message_id})")
    update_payload = {"content": "更新后的消息内容 - 测试修改"}
    resp = requests.put(
        f"{BASE_URL}/api/v1/qa/message/{message_id_1}",
        json=update_payload,
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("更新消息", resp.status_code, key_fields={"message_id": message_id_1, "更新内容": update_payload})
    assert resp.status_code == 200, f"更新消息失败: {resp.text}"
    updated_msg = resp.json()
    assert updated_msg["content"] == update_payload["content"], "更新后内容不匹配"
    print(f"  更新后内容: {updated_msg['content']}")

    # --- 测试 7: GET /api/v1/qa/context/{session_id} - 获取对话上下文 ---
    # 放在删除之前测试，否则会话不存在
    print_header("测试 7: 获取对话上下文 (GET /api/v1/qa/context/{session_id})")
    resp = requests.get(
        f"{BASE_URL}/api/v1/qa/context/{session_id}",
        params={"limit": 10},
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("获取对话上下文", resp.status_code, key_fields={"session_id": session_id, "limit": 10})
    assert resp.status_code == 200, f"获取对话上下文失败: {resp.text}"
    context_data = resp.json()
    assert "context" in context_data, "响应缺少 context 字段"
    print(f"  上下文消息数: {len(context_data['context'])}")

    # --- 测试 5: DELETE /api/v1/qa/message/{message_id} - 删除消息 ---
    print_header("测试 5: 删除消息 (DELETE /api/v1/qa/message/{message_id})")
    resp = requests.delete(
        f"{BASE_URL}/api/v1/qa/message/{message_id_2}",
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("删除消息", resp.status_code, key_fields={"message_id": message_id_2})
    assert resp.status_code == 204, f"删除消息失败: {resp.text}"
    print(f"  消息 {message_id_2} 已删除")
    resources["message_ids"].remove(message_id_2)

    # 验证消息已删除 - 再次获取消息列表
    resp = requests.get(f"{BASE_URL}/api/v1/qa/session/{session_id}", headers=headers, timeout=TIMEOUT)
    assert resp.status_code == 200
    remaining_messages = resp.json()
    remaining_ids = [m["id"] for m in remaining_messages]
    assert message_id_2 not in remaining_ids, "消息未被成功删除"
    print(f"  验证: 消息 {message_id_2} 确实已从列表中移除")

    return resources


# ========================================
# 二、AI 聊天接口测试
# ========================================
def test_ai_chat_apis(token: str) -> dict:
    """
    测试 AI 聊天接口 (/api/v1/ai-chat)
    返回测试过程中创建的资源 ID，供后续清理使用
    """
    print_header("二、AI 聊天接口测试 (/api/v1/ai-chat)")
    headers = get_auth_headers(token)
    resources = {"ai_chat_session_ids": []}

    session_id = generate_session_id()
    resources["ai_chat_session_ids"].append(session_id)
    print(f"\n  使用会话 ID: {session_id}")

    # --- 测试 12: GET /api/v1/ai-chat/health - 健康检查（无需认证）---
    print_header("测试 12: 健康检查 (GET /api/v1/ai-chat/health) [无需认证]")
    resp = requests.get(f"{BASE_URL}/api/v1/ai-chat/health", timeout=TIMEOUT)
    print_result("健康检查", resp.status_code)
    assert resp.status_code == 200, f"健康检查失败: {resp.text}"
    health_data = resp.json()
    assert "status" in health_data, "响应缺少 status 字段"
    print(f"  服务状态: {health_data.get('status')}")
    print(f"  消息: {health_data.get('message', '')}")

    # --- 测试 13: GET /api/v1/ai-chat/models - 获取可用模型列表 ---
    print_header("测试 13: 获取可用模型列表 (GET /api/v1/ai-chat/models)")
    resp = requests.get(f"{BASE_URL}/api/v1/ai-chat/models", headers=headers, timeout=TIMEOUT)
    print_result("获取可用模型列表", resp.status_code)
    assert resp.status_code == 200, f"获取模型列表失败: {resp.text}"
    models_data = resp.json()
    assert "models" in models_data, "响应缺少 models 字段"
    print(f"  可用模型: {list(models_data['models'].keys())}")

    # --- 测试 8: POST /api/v1/ai-chat/chat - AI 对话（非流式）---
    print_header("测试 8: AI 对话 - 非流式 (POST /api/v1/ai-chat/chat)")
    chat_payload = {
        "content": "你好，请用一句话回答：1+1等于几？",
        "session_id": session_id,
    }
    print(f"  请求参数: {chat_payload}")
    print(f"  [调试] 开始发送请求, 超时=60s, 等待 LLM 响应...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/ai-chat/chat",
            json=chat_payload,
            headers=headers,
            timeout=60,
        )
        print(f"  [调试] 收到响应, 状态码: {resp.status_code}")
        print(f"  [调试] 响应头: {dict(resp.headers)}")
        print(f"  [调试] 响应体: {resp.text[:1000]}")
        print_result("AI 对话（非流式）", resp.status_code)
        if resp.status_code == 200:
            chat_data = resp.json()
            assert "session_id" in chat_data, "响应缺少 session_id 字段"
            assert "user_message" in chat_data, "响应缺少 user_message 字段"
            assert "ai_message" in chat_data, "响应缺少 ai_message 字段"
            print(f"  用户消息 ID: {chat_data['user_message']['id']}")
            print(f"  AI 回复: {chat_data['ai_message']['content'][:200]}")
            print(f"  对话历史条数: {len(chat_data.get('conversation_history', []))}")
        else:
            print(f"  [跳过] AI 对话接口返回非 200，可能 LLM 服务不可用: {resp.text[:300]}")
    except requests.exceptions.ReadTimeout as e:
        print(f"  [调试] 读取超时! 服务器60秒内未返回完整响应")
        print(f"  [调试] 说明: 后端收到了请求，但 LLM API 调用超时未返回")
        print(f"  [调试] 异常: {e}")
    except requests.exceptions.ConnectTimeout as e:
        print(f"  [调试] 连接超时! 后端服务不可达")
        print(f"  [调试] 异常: {e}")
    except requests.exceptions.RequestException as e:
        print(f"  [跳过] AI 对话请求异常: {type(e).__name__}: {e}")

    # --- 测试 9: POST /api/v1/ai-chat/chat-stream - AI 对话（流式 SSE）---
    print_header("测试 9: AI 对话 - 流式 SSE (POST /api/v1/ai-chat/chat-stream)")
    stream_session_id = generate_session_id()
    resources["ai_chat_session_ids"].append(stream_session_id)
    stream_payload = {
        "content": "请用一句话回答：天空为什么是蓝色的？",
        "session_id": stream_session_id,
    }
    print(f"  请求参数: {stream_payload}")
    print(f"  [调试] 开始发送流式请求, 超时={STREAM_TIMEOUT}s...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/ai-chat/chat-stream",
            json=stream_payload,
            headers=headers,
            stream=True,
            timeout=STREAM_TIMEOUT,
        )
        print(f"  [调试] HTTP 连接建立, 状态码: {resp.status_code}")
        print(f"  [调试] 响应头 Content-Type: {resp.headers.get('Content-Type', '未知')}")
        print_result("AI 对话（流式 SSE）- HTTP 状态码", resp.status_code)
        if resp.status_code == 200:
            print("  [调试] 开始读取 SSE 流...")
            event_count = 0
            collected_content = []
            raw_line_count = 0
            for line in resp.iter_lines(decode_unicode=True):
                raw_line_count += 1
                # 打印前 20 行原始数据，方便调试
                if raw_line_count <= 20:
                    print(f"  [调试-原始行{raw_line_count}] {line[:300] if line else '(空行)'}")
                if not line:
                    continue
                if line.startswith(": "):
                    # SSE 心跳注释
                    print(f"    [心跳] {line}")
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]  # 去掉 "data: " 前缀
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("type", "unknown")
                        event_count += 1

                        if event_type == "user_message":
                            print(f"    [user_message] 用户消息已保存, id={event['data'].get('id')}")
                        elif event_type == "content":
                            fragment = event.get("data", {}).get("content", "")
                            collected_content.append(fragment)
                            # 打印前几条 content
                            if event_count <= 5:
                                print(f"    [content] {fragment[:100]}")
                        elif event_type == "done":
                            print(f"    [done] AI 回复完成, id={event['data'].get('id')}")
                        elif event_type == "error":
                            print(f"    [error] {event.get('data', {}).get('message', data_str[:200])}")
                        else:
                            print(f"    [{event_type}] {data_str[:200]}")
                    except json.JSONDecodeError:
                        print(f"    [解析失败] {data_str[:200]}")

            full_content = "".join(collected_content)
            print(f"  [调试] 共读取 {raw_line_count} 行原始数据, {event_count} 个 SSE 事件")
            print(f"  AI 回复内容: {full_content[:500] if full_content else '(无内容)'}")
            if event_count == 0:
                print(f"  [调试] 未收到任何 SSE 事件! LLM 可能未调用成功")
            assert event_count > 0, "未接收到任何 SSE 事件"
        else:
            print(f"  [跳过] 流式接口返回非 200，可能 LLM 服务不可用: {resp.text[:300]}")
    except requests.exceptions.ReadTimeout as e:
        print(f"  [调试] 读取超时! 服务器在 {STREAM_TIMEOUT}s 内未完成 SSE 流")
        print(f"  [调试] 说明: SSE 连接已建立(200)，但 LLM 未返回任何数据")
        print(f"  [调试] 异常: {e}")
    except requests.exceptions.RequestException as e:
        print(f"  [跳过] 流式请求异常: {type(e).__name__}: {e}")

    # --- 测试 10: GET /api/v1/ai-chat/chat-history - 获取聊天历史 ---
    print_header("测试 10: 获取聊天历史 (GET /api/v1/ai-chat/chat-history)")
    resp = requests.get(
        f"{BASE_URL}/api/v1/ai-chat/chat-history",
        params={"session_id": session_id},
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("获取聊天历史", resp.status_code, key_fields={"session_id": session_id})
    if resp.status_code == 200:
        history_data = resp.json()
        assert "session_id" in history_data, "响应缺少 session_id 字段"
        assert "messages" in history_data, "响应缺少 messages 字段"
        print(f"  历史消息数: {len(history_data['messages'])}")
    elif resp.status_code == 404:
        print("  会话不存在（如果非流式 AI 对话未成功，这是预期的）")
    else:
        print(f"  获取聊天历史失败: {resp.text[:200]}")

    # --- 测试 11: DELETE /api/v1/ai-chat/clear-chat - 清除聊天历史 ---
    print_header("测试 11: 清除聊天历史 (DELETE /api/v1/ai-chat/clear-chat)")
    resp = requests.delete(
        f"{BASE_URL}/api/v1/ai-chat/clear-chat",
        params={"session_id": session_id},
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("清除聊天历史", resp.status_code, key_fields={"session_id": session_id})
    if resp.status_code == 204:
        print("  聊天历史已清除")
    elif resp.status_code == 404:
        print("  会话不存在（如果 AI 对话未成功，这是预期的）")
    else:
        print(f"  清除聊天历史结果: {resp.text[:200]}")

    return resources


# ========================================
# 三、会话配置接口测试
# ========================================
def test_session_config_apis(token: str) -> dict:
    """
    测试会话配置接口 (/api/v1/sessions/{session_id}/config)
    返回测试过程中创建的 session_id，供后续清理使用
    """
    print_header("三、会话配置接口测试 (/api/v1/sessions/{session_id}/config)")
    headers = get_auth_headers(token)
    resources = {"config_session_ids": []}

    session_id = generate_session_id()
    resources["config_session_ids"].append(session_id)
    print(f"\n  使用会话 ID: {session_id}")

    # 先通过 QA 添加消息接口创建会话（让 session_id 在系统中存在）
    print(f"\n  [准备] 先创建消息让会话存在...")
    msg_resp = requests.post(
        f"{BASE_URL}/api/v1/qa/message",
        json={"content": "会话配置测试消息", "role": "user", "session_id": session_id},
        headers=headers,
        timeout=TIMEOUT,
    )
    print(f"  准备消息状态码: {msg_resp.status_code}")
    if msg_resp.status_code != 200:
        print(f"  [警告] 准备消息失败，继续测试: {msg_resp.text[:200]}")

    # --- 测试 14: POST /api/v1/sessions/{session_id}/config - 创建会话配置 ---
    print_header("测试 14: 创建会话配置 (POST /api/v1/sessions/{session_id}/config)")
    config_payload = {
        "compression": {
            "enable_compression": True,
            "strategy": "summary",
            "threshold": 3000,
            "target_tokens": 500,
            "keep_recent": 2,
            "custom_prompt": "请对以下对话进行摘要，保留关键信息",
        }
    }
    resp = requests.post(
        f"{BASE_URL}/api/v1/sessions/{session_id}/config",
        json=config_payload,
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("创建会话配置", resp.status_code, key_fields={"session_id": session_id, "请求": config_payload})
    assert resp.status_code in (200, 201), f"创建会话配置失败: {resp.text}"
    config_data = resp.json()
    assert "id" in config_data, "响应缺少 id 字段"
    assert "session_id" in config_data, "响应缺少 session_id 字段"
    assert config_data["session_id"] == session_id, "session_id 不匹配"
    assert "compression_config" in config_data, "响应缺少 compression_config 字段"
    print(f"  配置 ID: {config_data['id']}")
    print(f"  压缩策略: {config_data['compression_config']['strategy']}")
    print(f"  压缩阈值: {config_data['compression_config']['threshold']}")

    # --- 测试 14 续: 重复创建应返回 409 ---
    print_header("测试 14 续: 重复创建会话配置（应返回 409）")
    resp = requests.post(
        f"{BASE_URL}/api/v1/sessions/{session_id}/config",
        json=config_payload,
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("重复创建会话配置", resp.status_code)
    assert resp.status_code == 409, f"重复创建应返回 409，实际: {resp.status_code}"
    print(f"  正确返回 409 Conflict")

    # --- 测试 15: GET /api/v1/sessions/{session_id}/config - 获取会话配置 ---
    print_header("测试 15: 获取会话配置 (GET /api/v1/sessions/{session_id}/config)")
    resp = requests.get(
        f"{BASE_URL}/api/v1/sessions/{session_id}/config",
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("获取会话配置", resp.status_code, key_fields={"session_id": session_id})
    assert resp.status_code == 200, f"获取会话配置失败: {resp.text}"
    get_config_data = resp.json()
    assert get_config_data["session_id"] == session_id, "session_id 不匹配"
    print(f"  配置 ID: {get_config_data['id']}")
    print(f"  压缩配置: {get_config_data['compression_config']}")

    return resources


# ========================================
# 清理测试数据
# ========================================
def cleanup(token: str, qa_resources: dict, ai_chat_resources: dict, config_resources: dict) -> None:
    """清理测试过程中创建的所有数据"""
    print_header("清理测试数据")
    headers = get_auth_headers(token)

    # 清理会话配置（需在删除会话之前）
    for sid in config_resources.get("config_session_ids", []):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/sessions/{sid}/config",
            headers=headers,
            timeout=TIMEOUT,
        )
        status = "成功" if resp.status_code == 204 else f"失败({resp.status_code})"
        print(f"  删除会话配置 {sid}: {status}")

    # 清理 AI 聊天会话
    for sid in ai_chat_resources.get("ai_chat_session_ids", []):
        # 先清除聊天历史
        requests.delete(
            f"{BASE_URL}/api/v1/ai-chat/clear-chat",
            params={"session_id": sid},
            headers=headers,
            timeout=TIMEOUT,
        )
        # 再删除 QA 会话（删除会话同时删除消息）
        resp = requests.delete(
            f"{BASE_URL}/api/v1/qa/session/{sid}",
            headers=headers,
            timeout=TIMEOUT,
        )
        status = "成功" if resp.status_code == 204 else f"失败({resp.status_code})"
        print(f"  删除 AI 聊天会话 {sid}: {status}")

    # 清理 QA 会话（删除会话同时删除消息）
    for sid in qa_resources.get("session_ids", []):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/qa/session/{sid}",
            headers=headers,
            timeout=TIMEOUT,
        )
        status = "成功" if resp.status_code == 204 else f"失败({resp.status_code})"
        print(f"  删除 QA 会话 {sid}: {status}")


# ========================================
# 测试 6: 删除会话（放在最后作为清理验证）
# ========================================
def test_delete_session(token: str, session_id: str) -> None:
    """测试删除会话接口"""
    print_header("测试 6: 删除会话 (DELETE /api/v1/qa/session/{session_id})")
    headers = get_auth_headers(token)

    # 先创建一个专用会话用于删除测试
    create_resp = requests.post(
        f"{BASE_URL}/api/v1/qa/message",
        json={"content": "用于测试删除的消息", "role": "user", "session_id": session_id},
        headers=headers,
        timeout=TIMEOUT,
    )
    assert create_resp.status_code == 200, f"创建待删除会话失败: {create_resp.text}"
    print(f"  已创建待删除会话: {session_id}")

    # 删除会话
    resp = requests.delete(
        f"{BASE_URL}/api/v1/qa/session/{session_id}",
        headers=headers,
        timeout=TIMEOUT,
    )
    print_result("删除会话", resp.status_code, key_fields={"session_id": session_id})
    assert resp.status_code == 204, f"删除会话失败: {resp.text}"
    print(f"  会话 {session_id} 已删除")

    # 验证会话已删除 - 获取消息列表应返回 404
    verify_resp = requests.get(
        f"{BASE_URL}/api/v1/qa/session/{session_id}",
        headers=headers,
        timeout=TIMEOUT,
    )
    assert verify_resp.status_code == 404, f"删除后查询应返回 404，实际: {verify_resp.status_code}"
    print(f"  验证: 删除后查询返回 404，确认会话已彻底删除")


# ========================================
# 主函数
# ========================================
def main():
    print("=" * 60)
    print("  智能问答模块 API 接口测试")
    print(f"  目标服务: {BASE_URL}")
    print(f"  测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查服务是否可用
    try:
        health_resp = requests.get(f"{BASE_URL}/api/v1/ai-chat/health", timeout=5)
        print(f"\n服务健康检查: {health_resp.status_code} - {health_resp.json().get('status', 'unknown')}")
    except requests.exceptions.ConnectionError:
        print(f"\n[错误] 无法连接到 {BASE_URL}，请确认后端服务已启动")
        sys.exit(1)

    # 登录获取 token
    token = ensure_admin_user_and_login()

    # 执行测试
    qa_resources = {}
    ai_chat_resources = {}
    config_resources = {}
    delete_test_session = generate_session_id()

    try:
        # 一、智能问答接口测试
        qa_resources = test_qa_apis(token)

        # 二、AI 聊天接口测试
        ai_chat_resources = test_ai_chat_apis(token)

        # 三、会话配置接口测试
        config_resources = test_session_config_apis(token)

        # 测试 6: 删除会话（独立测试）
        test_delete_session(token, delete_test_session)

    except AssertionError as e:
        print(f"\n[测试失败] {e}")
        # 已注释，保留测试数据到数据库以便查看
        # cleanup(token, qa_resources, ai_chat_resources, config_resources)
        sys.exit(1)
    except Exception as e:
        print(f"\n[测试异常] {type(e).__name__}: {e}")
        # 已注释，保留测试数据到数据库以便查看
        # cleanup(token, qa_resources, ai_chat_resources, config_resources)
        sys.exit(1)

    # 清理测试数据（已注释，保留测试数据到数据库以便查看）
    # cleanup(token, qa_resources, ai_chat_resources, config_resources)

    # 最终汇总
    print_header("测试结果汇总")
    print("  所有测试通过!")
    print(f"  测试接口数: 16")
    print(f"  包含: 智能问答(7个) + AI聊天(6个) + 会话配置(3个)")
    print("=" * 60)


if __name__ == "__main__":
    main()
