# -*- coding: utf-8 -*-
"""
AI 聊天数据库持久化测试

仅测试：发送 AI 聊天消息后，用户消息和 AI 回复是否成功保存到数据库。
通过 API 接口验证，不直接操作数据库。

测试内容：
  1. 非流式对话 → 查询聊天历史验证 user + assistant 消息都在
  2. 流式对话   → 查询聊天历史验证 user + assistant 消息都在

运行方式：python tests/test_ai_chat_db.py
前置条件：后端服务已启动在 http://127.0.0.1:8100
"""

import json
import os
import random
import string
import sys

import requests
import pytest

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8100"
TIMEOUT = 30
STREAM_TIMEOUT = 120

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-admin-password")


def generate_session_id() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"db_test_{suffix}"


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def get_auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login() -> str:
    print_header("登录")
    resp = requests.post(
        f"{BASE_URL}/api/v1/user/users/login",
        json={"username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"  登录失败: {resp.text}")
        sys.exit(1)
    token = resp.json()["access_token"]
    print(f"  登录成功")
    return token


def verify_history(headers: dict, session_id: str, expected_roles: list[str], label: str) -> bool:
    """
    查询聊天历史，验证消息角色是否与预期一致。

    Args:
        headers: 认证头
        session_id: 会话 ID
        expected_roles: 期望的消息角色列表，如 ["user", "assistant"]
        label: 测试标签（用于打印）

    Returns:
        True 表示验证通过
    """
    print(f"\n  [验证] 查询聊天历史 session_id={session_id}")
    resp = requests.get(
        f"{BASE_URL}/api/v1/ai-chat/chat-history",
        params={"session_id": session_id},
        headers=headers,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"  [失败] 查询聊天历史返回 {resp.status_code}: {resp.text[:300]}")
        return False

    data = resp.json()
    messages = data.get("messages", [])
    actual_roles = [m["role"] for m in messages]

    print(f"  消息数量: {len(messages)}")
    for i, msg in enumerate(messages):
        content_preview = (msg.get("content") or "")[:80]
        print(f"    [{i}] role={msg['role']}, content={content_preview}")

    if actual_roles != expected_roles:
        print(f"  [失败] {label} 角色不匹配: 期望 {expected_roles}, 实际 {actual_roles}")
        return False

    # 额外检查 assistant 消息有实际内容
    for msg in messages:
        if msg["role"] == "assistant":
            if not msg.get("content") or not msg["content"].strip():
                print(f"  [失败] {label} assistant 消息内容为空")
                return False

    print(f"  [通过] {label} 消息持久化验证成功")
    return True


def test_non_stream(token: str) -> bool:
    """测试非流式对话的消息持久化"""
    print_header("测试 1: 非流式对话 → 验证数据库持久化")
    headers = get_auth_headers(token)
    session_id = generate_session_id()

    chat_payload = {
        "content": "你好，请用一句话回答：1+1等于几？",
        "session_id": session_id,
    }
    print(f"  session_id: {session_id}")
    print(f"  发送请求...")

    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/ai-chat/chat",
            json=chat_payload,
            headers=headers,
            timeout=60,
        )
    except requests.exceptions.RequestException as e:
        print(f"  [跳过] 请求异常: {type(e).__name__}: {e}")
        return False

    if resp.status_code != 200:
        print(f"  [跳过] 返回 {resp.status_code}: {resp.text[:300]}")
        return False

    chat_data = resp.json()
    user_msg = chat_data.get("user_message", {})
    ai_msg = chat_data.get("ai_message", {})
    print(f"  用户消息 ID: {user_msg.get('id')}")
    print(f"  AI 回复内容: {(ai_msg.get('content') or '')[:200]}")

    # 查询历史验证持久化
    return verify_history(headers, session_id, ["user", "assistant"], "非流式")


def test_stream(token: str) -> bool:
    """测试流式对话的消息持久化"""
    print_header("测试 2: 流式对话 → 验证数据库持久化")
    headers = get_auth_headers(token)
    session_id = generate_session_id()

    stream_payload = {
        "content": "请用一句话回答：天空为什么是蓝色的？",
        "session_id": session_id,
    }
    print(f"  session_id: {session_id}")
    print(f"  发送流式请求...")

    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/ai-chat/chat-stream",
            json=stream_payload,
            headers=headers,
            stream=True,
            timeout=STREAM_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        print(f"  [跳过] 请求异常: {type(e).__name__}: {e}")
        return False

    if resp.status_code != 200:
        print(f"  [跳过] 返回 {resp.status_code}: {resp.text[:300]}")
        return False

    # 读取 SSE 流，等待 done 事件
    got_done = False
    collected = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line or line.startswith(": "):
            continue
        if line.startswith("data: "):
            try:
                event = json.loads(line[6:])
                event_type = event.get("type")
                if event_type == "content":
                    collected.append(event.get("data", {}).get("content", ""))
                elif event_type == "done":
                    got_done = True
                    print(f"  流式完成, AI 消息 ID: {event.get('data', {}).get('id')}")
                elif event_type == "error":
                    print(f"  [错误] SSE error: {event}")
            except json.JSONDecodeError:
                pass

    full_content = "".join(collected)
    print(f"  AI 回复内容: {full_content[:200] if full_content else '(无)'}")

    if not got_done:
        print(f"  [失败] 未收到 done 事件，流式对话可能未正常完成")
        return False

    # 查询历史验证持久化
    return verify_history(headers, session_id, ["user", "assistant"], "流式")


def main():
    token = login()

    results = []
    results.append(("非流式对话", test_non_stream(token)))
    results.append(("流式对话", test_stream(token)))

    print_header("测试结果")
    all_pass = True
    for name, passed in results:
        status = "通过" if passed else "失败"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n  所有测试通过！消息已成功持久化到数据库。")
    else:
        print("\n  部分测试失败，请检查上方日志。")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
