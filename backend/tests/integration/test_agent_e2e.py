"""Agent 域端到端集成测试——真实服务 :8100 全链路（93e9c595 工程化收编面 + 对话主链）。

前置：后端已启动在 :8100，admin 凭据经环境变量 ``ADMIN_PASSWORD`` 提供
（缺省回落本地开发默认，与仓库其他集成测试一致）。

覆盖：
  1. GET /api/v1/agent/tools-runtime 权限矩阵（admin 200 / 未认证 401 /
     普通用户 403）
  2. GET /api/v1/agent/tools 用户版工具清单可用
  3. Agent 列表与默认助手可达
  4. WS 对话全链路：subprotocol ``bearer.<jwt>`` 认证 → action=chat →
     收 done 事件 → 会话消息持久化（user+assistant 落库）→ 未知 action 错误路径

WS 对话依赖真实 LLM：无模型配置的环境会收到 error 事件而非 done——该场景
按「LLM 不可用」skip（与 deep_research WS 测试同款兜底），错误路径与权限
矩阵不依赖 LLM，始终执行。
"""

import os
import time

import pytest
import requests

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8100"
WS_BASE = "ws://127.0.0.1:8100"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123456")

# 测试桩凭据（非真实账户）：注册即用即删，email 不能用保留域名（.test/.local
# 会被 pydantic email-validator 拒绝，见 user_routes ResponseValidationError）
PROBE_PASSWORD = "E2eProbe#2026a"

access_token = None
probe_user_id = None
probe_token = None
created_session_ids = []


def _headers(token=None):
    return {"Authorization": f"Bearer {token or access_token}"}


def setup_module(module=None):
    global access_token, probe_user_id, probe_token
    resp = requests.post(
        f"{BASE_URL}/api/v1/user/users/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip("integration 环境不可用（admin 登录失败）")
    access_token = resp.json()["access_token"]

    # 普通用户（403 场景）：注册 + 登录；已存在则直接尝试登录（上一轮残留）
    suffix = int(time.time())
    probe_name = f"agent_e2e_probe_{suffix}"
    reg = requests.post(
        f"{BASE_URL}/api/v1/user/users/register",
        json={
            "username": probe_name,
            "password": PROBE_PASSWORD,
            "email": f"{probe_name}@example.com",
        },
        timeout=10,
    )
    if reg.status_code in (200, 201):
        probe_user_id = reg.json().get("id") or (reg.json().get("data") or {}).get("id")
    login = requests.post(
        f"{BASE_URL}/api/v1/user/users/login",
        json={"username": probe_name, "password": PROBE_PASSWORD},
        timeout=10,
    )
    if login.status_code == 200:
        probe_token = login.json()["access_token"]


def teardown_module(module=None):
    for sid in created_session_ids:
        requests.delete(
            f"{BASE_URL}/api/v1/agent/sessions/{sid}",
            headers=_headers(),
            timeout=10,
        )
    if probe_user_id:
        requests.delete(
            f"{BASE_URL}/api/v1/user/users/{probe_user_id}",
            headers=_headers(),
            timeout=10,
        )


# ==================== tools-runtime 权限矩阵 ====================


def test_tools_runtime_admin_ok():
    """admin 访问 tools-runtime：200 + 内置工具与函数总数结构完整。"""
    resp = requests.get(f"{BASE_URL}/api/v1/agent/tools-runtime", headers=_headers(), timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["builtin_tools"], list) and data["builtin_tools"]
    assert data["total_functions"] >= 10
    provider = data["builtin_tools"][0]
    assert {"provider", "functions", "default_timeout_ms"} <= set(provider.keys())


def test_tools_runtime_unauthenticated_401():
    """无 token 访问 tools-runtime：401。"""
    resp = requests.get(f"{BASE_URL}/api/v1/agent/tools-runtime", timeout=10)
    assert resp.status_code == 401


def test_tools_runtime_non_admin_403():
    """普通用户访问 tools-runtime：403（agent.manage_system 门禁）。"""
    if not probe_token:
        pytest.skip("integration 环境不可用（探针用户注册/登录失败）")
    resp = requests.get(
        f"{BASE_URL}/api/v1/agent/tools-runtime",
        headers={"Authorization": f"Bearer {probe_token}"},
        timeout=10,
    )
    assert resp.status_code == 403


def test_tools_user_endpoint_open_to_authenticated():
    """用户版 /tools：认证即可访问（无 manage_system 门禁）。"""
    resp = requests.get(f"{BASE_URL}/api/v1/agent/tools", headers=_headers(), timeout=10)
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list) and tools
    assert {"name", "tools"} <= set(tools[0].keys())


# ==================== Agent 列表与默认助手 ====================


def test_agents_list_and_default():
    """/agents 列表可达；默认助手端点返回 is_default 标记的助手。"""
    resp = requests.get(f"{BASE_URL}/api/v1/agent/agents", headers=_headers(), timeout=10)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert isinstance(items, list)

    resp = requests.get(f"{BASE_URL}/api/v1/agent/agents/default", headers=_headers(), timeout=10)
    assert resp.status_code == 200
    assert resp.json()["extra_config"].get("is_default") is True


# ==================== WS 对话全链路 ====================


def _get_default_agent_id():
    resp = requests.get(f"{BASE_URL}/api/v1/agent/agents/default", headers=_headers(), timeout=10)
    if resp.status_code != 200:
        return None
    return resp.json()["id"]


def test_ws_chat_full_pipeline():
    """WS 对话主链：认证通过 → session 事件 → done 事件 → 消息持久化。

    依赖真实 LLM：若服务端以 error 事件收尾（模型不可用/未配置），skip。
    """
    import json

    import websockets

    agent_id = _get_default_agent_id()
    if not agent_id:
        pytest.skip("integration 环境不可用（默认助手不存在）")

    url = f"{WS_BASE}/api/v1/agent/agents/{agent_id}/ws"
    events = []

    async def _run():
        async with websockets.connect(url, subprotocols=[f"bearer.{access_token}"]) as ws:
            await ws.send(
                json.dumps(
                    {
                        "action": "chat",
                        "payload": {
                            "content": "端到端测试：请用一句话回答 1+1 等于几",
                        },
                    }
                )
            )
            while True:
                raw = await asyncio.wait_for(ws.recv(), 180)
                event = json.loads(raw)
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

    import asyncio

    asyncio.run(_run())

    types = [e.get("type") for e in events]
    if types[-1] == "error":
        # LLM 未配置/不可用环境：主链无法验证，但不视为产品缺陷
        pytest.skip(f"LLM 不可用，WS 对话主链 skip：{events[-1]}")

    assert "session" in types, types
    assert types[-1] == "done", types

    session_id = next(
        e["data"].get("session_id") or e["data"].get("id") for e in events if e["type"] == "session"
    )
    created_session_ids.append(session_id)

    # 会话消息持久化：user + assistant 两条落库
    resp = requests.get(
        f"{BASE_URL}/api/v1/agent/sessions/{session_id}/messages",
        headers=_headers(),
        timeout=10,
    )
    assert resp.status_code == 200
    messages = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", [])
    roles = [m["role"] for m in messages]
    assert "user" in roles and "assistant" in roles, roles


def test_ws_unknown_action_error_path():
    """未知 action：服务端回 error 事件并关闭（不依赖 LLM，始终执行）。"""
    import json

    import websockets

    agent_id = _get_default_agent_id()
    if not agent_id:
        pytest.skip("integration 环境不可用（默认助手不存在）")

    url = f"{WS_BASE}/api/v1/agent/agents/{agent_id}/ws"

    async def _run():
        async with websockets.connect(url, subprotocols=[f"bearer.{access_token}"]) as ws:
            await ws.send(json.dumps({"action": "download_database"}))
            raw = await asyncio.wait_for(ws.recv(), 15)
            return json.loads(raw)

    import asyncio

    event = asyncio.run(_run())
    assert event["type"] == "error"
    assert "未知 action" in event["data"]["content"]


def test_ws_bad_token_rejected():
    """无效 JWT subprotocol：WS close 4401（accept 后以 close frame 传达）。"""
    import asyncio

    import websockets

    agent_id = _get_default_agent_id()
    if not agent_id:
        pytest.skip("integration 环境不可用（默认助手不存在）")

    url = f"{WS_BASE}/api/v1/agent/agents/{agent_id}/ws"

    async def _run():
        async with websockets.connect(url, subprotocols=["bearer.invalid.token.here"]) as ws:
            try:
                await asyncio.wait_for(ws.recv(), 10)
                return "received"
            except websockets.exceptions.ConnectionClosed as exc:
                return exc.rcvd.code if exc.rcvd else None

    result = asyncio.run(_run())
    assert result == 4401, result
