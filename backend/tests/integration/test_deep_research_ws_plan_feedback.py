"""深度研究 WS 计划确认（human_feedback）集成测试——deer-flow 对齐流程验证。

前置：后端已启动在 :8100。覆盖：

  1. 非流式 POST 强制 auto-accept：请求带 auto_accepted_plan=false 也直接完成
     （无双向通道，不可能挂起）。

WS 双向流程（plan_generated → plan_feedback → done）依赖真实 LLM 全链路
（背景调查 + planner + 检索 + 报告），无法在无 LLM 的 CI 环境稳定运行，
标注 skip 手动验证；交互逻辑已由单元/契约层覆盖：
  - PlanFeedbackRegistry 六态：tests/features/deep_research/test_plan_feedback_and_compat.py
  - routes 双 task 接线：starlette TestClient WS 面见架构契约测试
"""
import time

import pytest
import requests

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8100"

ADMIN_USERNAME = "admin_test"
ADMIN_EMAIL = "admin_test@test.com"
ADMIN_PASSWORD = "TestUser@12345"

access_token = None
space_id = None
created_session_ids = []


def setup_module(module=None):
    global access_token, space_id
    resp = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip("integration 环境不可用（登录失败）")
    access_token = resp.json()["data"]["access_token"]

    resp = requests.post(
        f"{BASE_URL}/api/v1/spaces",
        json={"name": f"dr_ws_feedback_test_{int(time.time())}", "description": "ws 计划确认测试"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        pytest.skip("integration 环境不可用（建空间失败）")
    space_id = resp.json()["data"]["id"]


def teardown_module(module=None):
    for sid in created_session_ids:
        requests.delete(
            f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{sid}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    if access_token and space_id:
        requests.delete(
            f"{BASE_URL}/api/v1/spaces/{space_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )


def test_non_stream_forces_auto_accept():
    """非流式 POST 强制 auto-accept：请求带 auto_accepted_plan=false 也不挂起。"""
    body = {
        "query": "RAG 与微调的对比？",
        "research_mode": "quick",
        "auto_accepted_plan": False,
    }
    resp = requests.post(
        f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research",
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=180,
    )
    if resp.status_code != 200:
        pytest.skip("LLM/搜索服务不可用")
    data = resp.json()["data"]
    # 非流式不可能挂起等待——能正常返回 completed 即证明强制 auto-accept 生效
    assert data["status"] == "completed"
    created_session_ids.append(data["session_id"])


@pytest.mark.skip(reason="WS 双向计划确认流程依赖真实 LLM 全链路，需手动环境验证（见模块 docstring）")
def test_ws_plan_feedback_full_flow_manual():
    """手动验证步骤：
    1. 前端关闭「自动确认计划」开关发起研究
    2. 观察 plan_generated 事件与计划卡出现，研究挂起
    3a. 点「确认执行」→ 检索进度继续 → done
    3b. 输入修改意见点「修订计划」→ 新计划卡（iteration=1）→ 再确认 → done
    3c. 不操作等待 300s → 自动接受继续（日志出现「计划确认超时，自动接受」）
    3d. 等待期间关闭页面 → 详情接口状态为 cancelled
    """
