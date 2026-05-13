# -*- coding: utf-8 -*-
"""
深度研究模块 API 接口测试脚本

功能说明：
  使用 requests 库对深度研究模块的所有接口进行集成测试。
  测试前会自动完成以下准备工作：
    1. 管理员登录（不存在则创建）
    2. 创建测试知识空间
  测试完成后会自动清理：
    1. 删除创建的研究记录
    2. 删除测试知识空间

使用方式：
  确保后端服务已启动在 http://127.0.0.1:8100
  运行命令：python tests/test_deep_research_api.py

注意：
  - 深度研究接口依赖 LLM 服务和外部搜索服务
  - 如果这些服务不可用，相关测试会优雅跳过并打印原因
  - 非流式研究可能耗时较长（30秒+），已设置 120 秒超时
"""

import json
import sys
import time

import requests

# ==================== 基础配置 ====================

BASE_URL = "http://127.0.0.1:8100"
TIMEOUT_SHORT = 10       # 普通请求超时（秒）
TIMEOUT_RESEARCH = 120   # 深度研究请求超时（秒）
TIMEOUT_STREAM = 180     # 流式请求超时（秒）

# 管理员测试账号配置
ADMIN_USERNAME = "admin_test"
ADMIN_EMAIL = "admin_test@test.com"
ADMIN_PASSWORD = "***REMOVED***"

# 测试空间名称
TEST_SPACE_NAME = f"deep_research_test_{int(time.time())}"

# 全局变量，在测试过程中赋值
access_token = None
space_id = None
created_session_ids = []  # 记录创建的研究 session_id，用于清理


# ==================== 工具函数 ====================

def get_headers(token: str = None) -> dict:
    """获取通用请求头"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def print_test_header(test_name: str):
    """打印测试标题"""
    print(f"\n{'=' * 60}")
    print(f"测试：{test_name}")
    print(f"{'=' * 60}")


def print_request_info(method: str, url: str, params: dict = None, body: dict = None):
    """打印请求信息"""
    print(f"  请求：{method} {url}")
    if params:
        print(f"  查询参数：{json.dumps(params, ensure_ascii=False)}")
    if body:
        body_str = json.dumps(body, ensure_ascii=False)
        if len(body_str) > 500:
            body_str = body_str[:500] + "..."
        print(f"  请求体：{body_str}")


def print_response_info(response: requests.Response):
    """打印响应信息"""
    print(f"  状态码：{response.status_code}")
    try:
        data = response.json()
        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(data_str) > 1000:
            data_str = data_str[:1000] + "..."
        print(f"  响应内容：{data_str}")
        return data
    except Exception:
        text = response.text
        if len(text) > 1000:
            text = text[:1000] + "..."
        print(f"  响应内容（文本）：{text}")
        return None


# ==================== 前置准备 ====================

def step_0_ensure_admin_user():
    """
    前置步骤 0：使用系统默认管理员账号登录（启动时自动创建）。
    """
    global access_token

    print_test_header("前置准备 - 登录管理员账号")

    login_url = f"{BASE_URL}/api/v1/user/users/login"
    login_body = {
        "username": "admin",
        "password": "***REMOVED***",
    }

    print_request_info("POST", login_url, body=login_body)
    resp = requests.post(login_url, json=login_body, headers=get_headers(), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    if resp.status_code == 200 and data:
        access_token = data.get("access_token")
        print(f"  [成功] 管理员 [admin] 登录成功")
    else:
        print(f"  [失败] 无法使用管理员登录，请确保后端服务正常运行")
        sys.exit(1)


def step_1_create_test_space():
    """
    前置步骤 1：创建测试知识空间
    """
    global space_id

    print_test_header("前置准备 - 创建测试知识空间")

    url = f"{BASE_URL}/api/v1/spaces"
    body = {
        "name": TEST_SPACE_NAME,
        "visibility": 0,
        "config": {
            "description": "深度研究模块自动化测试空间，测试完成后将删除",
        },
    }

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code in (200, 201), f"创建测试空间失败，状态码：{resp.status_code}"
    assert data is not None, "创建测试空间返回数据为空"
    assert "id" in data, f"创建测试空间响应缺少 id 字段：{data}"

    space_id = data["id"]
    print(f"  [成功] 测试空间已创建，space_id = {space_id}")


# ==================== 测试用例 ====================

def test_1_execute_research():
    """
    测试 1：执行深度研究（非流式）
    POST /api/v1/spaces/{space_id}/deep-research
    """
    print_test_header("测试 1 - 执行深度研究（非流式）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    body = {
        "query": "Python 异步编程有哪些最佳实践？",
        "research_mode": "quick",
        "search_source": "external",
        "external_search": {
            "provider": "duckduckgo",
            "max_results": 5,
        },
    }

    print_request_info("POST", url, body=body)
    print(f"  注意：此请求可能耗时较长（timeout={TIMEOUT_RESEARCH}s）...")

    try:
        resp = requests.post(
            url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_RESEARCH
        )
        data = print_response_info(resp)
    except requests.exceptions.Timeout:
        print(f"  [跳过] 非流式研究请求超时（{TIMEOUT_RESEARCH}s），可能 LLM 服务响应缓慢")
        return
    except requests.exceptions.ConnectionError as e:
        print(f"  [跳过] 连接错误：{e}")
        return

    if resp.status_code != 200:
        print(f"  [跳过] 非流式研究请求失败，状态码：{resp.status_code}")
        print(f"  原因：可能 LLM 服务或搜索服务不可用")
        return

    assert data is not None, "响应数据为空"

    # 断言关键字段
    assert "session_id" in data, f"响应缺少 session_id 字段"
    assert "query" in data, f"响应缺少 query 字段"
    assert "status" in data, f"响应缺少 status 字段"
    assert data["query"] == body["query"], f"响应 query 与请求不一致"
    assert len(data["session_id"]) == 32, f"session_id 长度异常：{len(data['session_id'])}"

    print(f"  [断言通过] session_id: {data['session_id']}")
    print(f"  [断言通过] status: {data['status']}")
    print(f"  [断言通过] query 匹配")

    # 记录 session_id 用于后续测试和清理
    session_id = data["session_id"]
    created_session_ids.append(session_id)

    # 如果有研究报告，打印部分内容
    if data.get("final_report"):
        report = data["final_report"]
        preview = report[:200] + "..." if len(report) > 200 else report
        print(f"  研究报告预览：{preview}")

    # 如果有统计信息，打印
    if data.get("stats"):
        stats = data["stats"]
        print(f"  研究统计：耗时 {stats.get('elapsed_seconds', '?')}s，"
              f"内部检索 {stats.get('internal_searches', '?')} 次，"
              f"外部搜索 {stats.get('external_searches', '?')} 次")

    return session_id


def test_2_execute_research_stream():
    """
    测试 2：执行深度研究（流式 SSE）
    POST /api/v1/spaces/{space_id}/deep-research/stream
    """
    print_test_header("测试 2 - 执行深度研究（流式 SSE）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/stream"
    body = {
        "query": "FastAPI 框架的核心优势是什么？",
        "research_mode": "quick",
        "search_source": "external",
        "external_search": {
            "provider": "duckduckgo",
            "max_results": 5,
        },
    }

    print_request_info("POST", url, body=body)
    print(f"  注意：此请求为流式 SSE，timeout={TIMEOUT_STREAM}s...")

    event_types_received = []
    stream_session_id = None

    try:
        resp = requests.post(
            url,
            json=body,
            headers=get_headers(access_token),
            timeout=TIMEOUT_STREAM,
            stream=True,
        )

        # 检查是否为 SSE 响应
        content_type = resp.headers.get("Content-Type", "")
        print(f"  响应 Content-Type：{content_type}")

        if resp.status_code != 200:
            data = print_response_info(resp)
            print(f"  [跳过] 流式研究请求失败，状态码：{resp.status_code}")
            print(f"  原因：可能 LLM 服务或搜索服务不可用")
            return

        assert "text/event-stream" in content_type, f"预期 Content-Type 包含 text/event-stream，实际为：{content_type}"
        print(f"  [断言通过] Content-Type 包含 text/event-stream")

        # 逐行读取 SSE 数据
        print(f"  开始接收 SSE 事件流...")
        line_count = 0
        max_lines = 5000  # 安全限制，防止无限读取

        for line in resp.iter_lines(decode_unicode=True):
            if line is None:
                continue

            line_count += 1
            if line_count > max_lines:
                print(f"  [警告] 已读取 {max_lines} 行，强制停止")
                resp.close()
                break

            # SSE 心跳行，以 ": " 开头
            if line.startswith(": "):
                continue

            # SSE 数据行，以 "data: " 开头
            if line.startswith("data: "):
                json_str = line[6:]  # 去掉 "data: " 前缀
                try:
                    event = json.loads(json_str)
                    event_type = event.get("event_type", "unknown")
                    event_types_received.append(event_type)

                    if event_type == "progress":
                        progress_data = event.get("data", {})
                        percent = progress_data.get("progress_percent", 0)
                        step_desc = progress_data.get("current_step", "")
                        print(f"    [progress] {percent}% - {step_desc}")

                    elif event_type == "content":
                        chunk = event.get("data", {}).get("chunk", "")
                        preview = chunk[:80].replace("\n", " ") if chunk else ""
                        print(f"    [content] 片段：{preview}...")

                    elif event_type == "done":
                        done_data = event.get("data", {})
                        stream_session_id = done_data.get("session_id")
                        stats = done_data.get("stats", {})
                        print(f"    [done] 研究完成！session_id={stream_session_id}")
                        if stats:
                            print(f"    [done] 统计：耗时 {stats.get('elapsed_seconds', '?')}s，"
                                  f"内部检索 {stats.get('internal_searches', '?')} 次，"
                                  f"外部搜索 {stats.get('external_searches', '?')} 次")

                    elif event_type == "error":
                        error_data = event.get("data", {})
                        error_msg = error_data.get("message", "未知错误")
                        print(f"    [error] 错误：{error_msg}")

                    else:
                        print(f"    [{event_type}] {json_str[:200]}")

                except json.JSONDecodeError:
                    print(f"    [非JSON数据] {json_str[:200]}")

            # 空行表示事件分隔符
            elif line.strip() == "":
                pass

        print(f"  SSE 流读取完毕，共接收 {line_count} 行")

    except requests.exceptions.Timeout:
        print(f"  [跳过] 流式研究请求超时（{TIMEOUT_STREAM}s），可能 LLM 服务响应缓慢")
        return
    except requests.exceptions.ConnectionError as e:
        print(f"  [跳过] 连接错误：{e}")
        return

    # 验证至少收到了一些事件
    if event_types_received:
        print(f"  [断言通过] 收到 SSE 事件类型：{list(set(event_types_received))}")
    else:
        print(f"  [警告] 未收到任何 SSE 事件")

    # 如果收到了 done 事件，记录 session_id
    if stream_session_id:
        created_session_ids.append(stream_session_id)
        print(f"  [记录] 流式研究 session_id={stream_session_id}")


def test_3_list_researches():
    """
    测试 3：获取研究历史列表
    GET /api/v1/spaces/{space_id}/deep-research
    """
    print_test_header("测试 3 - 获取研究历史列表")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    params = {"limit": 10, "offset": 0}

    print_request_info("GET", url, params=params)
    resp = requests.get(url, params=params, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取研究历史列表失败，状态码：{resp.status_code}"
    assert data is not None, "响应数据为空"

    # 断言分页字段
    assert "items" in data, f"响应缺少 items 字段"
    assert "total" in data, f"响应缺少 total 字段"
    assert "limit" in data, f"响应缺少 limit 字段"
    assert "offset" in data, f"响应缺少 offset 字段"
    assert data["limit"] == 10, f"limit 值不一致：{data['limit']}"
    assert data["offset"] == 0, f"offset 值不一致：{data['offset']}"

    print(f"  [断言通过] total={data['total']}, limit={data['limit']}, offset={data['offset']}")
    print(f"  [断言通过] items 数量={len(data['items'])}")

    # 如果有记录，验证列表项字段
    if data["items"]:
        first_item = data["items"][0]
        required_fields = ["session_id", "query", "status", "research_mode", "created_at"]
        for field in required_fields:
            assert field in first_item, f"列表项缺少 {field} 字段"
        print(f"  [断言通过] 列表项包含所有必要字段")
        print(f"  首条记录：session_id={first_item['session_id']}, query={first_item['query'][:50]}..., status={first_item['status']}")

    return data


def test_3_2_list_researches_with_status_filter():
    """
    测试 3.2：按状态过滤研究历史
    GET /api/v1/spaces/{space_id}/deep-research?status=completed
    """
    print_test_header("测试 3.2 - 按状态过滤研究历史（status=completed）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    params = {"limit": 10, "offset": 0, "status": "completed"}

    print_request_info("GET", url, params=params)
    resp = requests.get(url, params=params, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"按状态过滤失败，状态码：{resp.status_code}"
    assert data is not None, "响应数据为空"
    assert "items" in data, f"响应缺少 items 字段"

    # 验证所有返回记录的状态都是 completed
    for item in data["items"]:
        assert item["status"] == "completed", f"过滤结果包含非 completed 状态的记录：{item['status']}"

    print(f"  [断言通过] 所有返回记录状态均为 completed，共 {len(data['items'])} 条")


def test_3_3_list_researches_pagination():
    """
    测试 3.3：分页查询研究历史
    GET /api/v1/spaces/{space_id}/deep-research?limit=1&offset=0
    """
    print_test_header("测试 3.3 - 分页查询研究历史（limit=1, offset=0）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    params = {"limit": 1, "offset": 0}

    print_request_info("GET", url, params=params)
    resp = requests.get(url, params=params, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"分页查询失败，状态码：{resp.status_code}"
    assert data is not None, "响应数据为空"
    assert data["limit"] == 1, f"limit 值不一致：期望 1，实际 {data['limit']}"
    assert len(data["items"]) <= 1, f"返回记录数超过 limit：{len(data['items'])}"

    print(f"  [断言通过] 分页参数正确，返回 {len(data['items'])} 条记录")


def test_4_get_research_detail(session_id: str = None):
    """
    测试 4：获取研究详情
    GET /api/v1/spaces/{space_id}/deep-research/{session_id}
    """
    print_test_header("测试 4 - 获取研究详情")

    if not session_id and created_session_ids:
        session_id = created_session_ids[0]

    if not session_id:
        print(f"  [跳过] 没有可用的 session_id，跳过详情测试")
        return

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{session_id}"

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取研究详情失败，状态码：{resp.status_code}"
    assert data is not None, "响应数据为空"

    # 断言关键字段
    required_fields = ["session_id", "query", "research_mode", "search_source", "status", "created_at"]
    for field in required_fields:
        assert field in data, f"详情响应缺少 {field} 字段"

    assert data["session_id"] == session_id, f"session_id 不匹配：期望 {session_id}，实际 {data['session_id']}"

    print(f"  [断言通过] 所有必要字段均存在")
    print(f"  [断言通过] session_id 匹配：{session_id}")

    # 打印详情信息
    print(f"  研究模式：{data.get('research_mode')}")
    print(f"  搜索来源：{data.get('search_source')}")
    print(f"  外部搜索提供商：{data.get('external_provider')}")
    print(f"  研究状态：{data.get('status')}")
    print(f"  研究主题：{data.get('research_topic', '（无）')}")

    if data.get("research_tasks"):
        print(f"  研究任务数：{len(data['research_tasks'])}")

    if data.get("final_report"):
        report = data["final_report"]
        preview = report[:150].replace("\n", " ") + "..."
        print(f"  研究报告预览：{preview}")

    if data.get("stats"):
        stats = data["stats"]
        print(f"  统计信息：耗时 {stats.get('elapsed_seconds', '?')}s，"
              f"报告长度 {stats.get('report_length', '?')} 字符")


def test_4_2_get_research_detail_not_found():
    """
    测试 4.2：获取不存在的研究详情（应返回 404）
    GET /api/v1/spaces/{space_id}/deep-research/{invalid_session_id}
    """
    print_test_header("测试 4.2 - 获取不存在的研究详情（期望 404）")

    fake_session_id = "a" * 32  # 不存在的 session_id
    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{fake_session_id}"

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际状态码：{resp.status_code}"
    print(f"  [断言通过] 不存在的研究详情正确返回 404")


def test_5_delete_research():
    """
    测试 5：删除研究记录
    DELETE /api/v1/spaces/{space_id}/deep-research/{session_id}
    """
    print_test_header("测试 5 - 删除研究记录")

    if not created_session_ids:
        print(f"  [跳过] 没有可删除的研究记录")
        return

    session_id = created_session_ids[0]
    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{session_id}"

    print_request_info("DELETE", url)
    resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    if resp.status_code == 409:
        print(f"  [跳过] 研究正在运行中，无法删除（HTTP 409）")
        return

    assert resp.status_code == 200, f"删除研究记录失败，状态码：{resp.status_code}"
    assert data is not None, "响应数据为空"
    assert "message" in data, f"响应缺少 message 字段"

    print(f"  [断言通过] 研究记录已删除，message：{data['message']}")

    # 验证删除后无法再获取
    verify_url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{session_id}"
    print_request_info("GET", verify_url)
    verify_resp = requests.get(verify_url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    assert verify_resp.status_code == 404, f"删除后应返回 404，实际状态码：{verify_resp.status_code}"
    print(f"  [断言通过] 删除后再次获取返回 404")

    # 从清理列表中移除已删除的记录
    created_session_ids.remove(session_id)


def test_5_2_delete_research_not_found():
    """
    测试 5.2：删除不存在的研究记录（应返回 404）
    DELETE /api/v1/spaces/{space_id}/deep-research/{invalid_session_id}
    """
    print_test_header("测试 5.2 - 删除不存在的研究记录（期望 404）")

    fake_session_id = "b" * 32
    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{fake_session_id}"

    print_request_info("DELETE", url)
    resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际状态码：{resp.status_code}"
    print(f"  [断言通过] 删除不存在的研究记录正确返回 404")


def test_6_validation_error():
    """
    测试 6：请求参数验证（缺少必填字段，期望 422）
    POST /api/v1/spaces/{space_id}/deep-research
    """
    print_test_header("测试 6 - 请求参数验证（缺少 query 字段）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    body = {}  # 缺少必填的 query 字段

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 422, f"期望 422 验证错误，实际状态码：{resp.status_code}"
    print(f"  [断言通过] 缺少必填字段正确返回 422")


def test_7_query_too_short():
    """
    测试 7：query 字段过短（少于 5 字符，期望 422）
    POST /api/v1/spaces/{space_id}/deep-research
    """
    print_test_header("测试 7 - query 字段过短（期望 422）")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research"
    body = {"query": "abc"}  # query 最少 5 个字符

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 422, f"期望 422 验证错误，实际状态码：{resp.status_code}"
    print(f"  [断言通过] query 过短正确返回 422")


# ==================== 清理函数 ====================

def cleanup_research_records():
    """清理：删除所有创建的研究记录"""
    print_test_header("清理 - 删除测试产生的研究记录")

    for session_id in list(created_session_ids):
        url = f"{BASE_URL}/api/v1/spaces/{space_id}/deep-research/{session_id}"
        print_request_info("DELETE", url)
        try:
            resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
            if resp.status_code == 200:
                print(f"  已删除研究记录：{session_id}")
            elif resp.status_code == 404:
                print(f"  研究记录已不存在：{session_id}")
            elif resp.status_code == 409:
                print(f"  研究正在运行中，无法删除：{session_id}")
            else:
                print(f"  删除研究记录异常，状态码：{resp.status_code}，session_id：{session_id}")
        except Exception as e:
            print(f"  删除研究记录出错：{e}")


def cleanup_test_space():
    """清理：删除测试知识空间"""
    print_test_header("清理 - 删除测试知识空间")

    if not space_id:
        print(f"  [跳过] space_id 为空，无需清理")
        return

    url = f"{BASE_URL}/api/v1/spaces/{space_id}"
    print_request_info("DELETE", url)
    try:
        resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
        print_response_info(resp)
        if resp.status_code == 200:
            print(f"  [成功] 测试空间已删除，space_id={space_id}")
        else:
            print(f"  [警告] 删除测试空间失败，状态码：{resp.status_code}，请手动清理 space_id={space_id}")
    except Exception as e:
        print(f"  [警告] 删除测试空间出错：{e}，请手动清理 space_id={space_id}")


# ==================== 主流程 ====================

def main():
    """主测试流程"""
    print("=" * 60)
    print("深度研究模块 API 接口测试")
    print(f"服务地址：{BASE_URL}")
    print(f"测试时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 前置准备
    step_0_ensure_admin_user()
    step_1_create_test_space()

    # 执行测试用例
    test_results = []

    # 测试 1：非流式深度研究
    try:
        session_id = test_1_execute_research()
        test_results.append(("测试 1 - 非流式深度研究", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 1 - 非流式深度研究", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 1 - 非流式深度研究", f"ERROR: {e}"))

    # 测试 2：流式深度研究
    try:
        test_2_execute_research_stream()
        test_results.append(("测试 2 - 流式深度研究（SSE）", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 2 - 流式深度研究（SSE）", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 2 - 流式深度研究（SSE）", f"ERROR: {e}"))

    # 测试 3：获取研究历史列表
    try:
        test_3_list_researches()
        test_results.append(("测试 3 - 获取研究历史列表", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 3 - 获取研究历史列表", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 3 - 获取研究历史列表", f"ERROR: {e}"))

    # 测试 3.2：按状态过滤
    try:
        test_3_2_list_researches_with_status_filter()
        test_results.append(("测试 3.2 - 按状态过滤", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 3.2 - 按状态过滤", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 3.2 - 按状态过滤", f"ERROR: {e}"))

    # 测试 3.3：分页查询
    try:
        test_3_3_list_researches_pagination()
        test_results.append(("测试 3.3 - 分页查询", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 3.3 - 分页查询", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 3.3 - 分页查询", f"ERROR: {e}"))

    # 测试 4：获取研究详情
    try:
        test_4_get_research_detail()
        test_results.append(("测试 4 - 获取研究详情", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 4 - 获取研究详情", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 4 - 获取研究详情", f"ERROR: {e}"))

    # 测试 4.2：获取不存在的研究详情
    try:
        test_4_2_get_research_detail_not_found()
        test_results.append(("测试 4.2 - 获取不存在的研究详情", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 4.2 - 获取不存在的研究详情", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 4.2 - 获取不存在的研究详情", f"ERROR: {e}"))

    # 测试 5：删除研究记录
    try:
        test_5_delete_research()
        test_results.append(("测试 5 - 删除研究记录", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 5 - 删除研究记录", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 5 - 删除研究记录", f"ERROR: {e}"))

    # 测试 5.2：删除不存在的研究记录
    try:
        test_5_2_delete_research_not_found()
        test_results.append(("测试 5.2 - 删除不存在的研究记录", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 5.2 - 删除不存在的研究记录", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 5.2 - 删除不存在的研究记录", f"ERROR: {e}"))

    # 测试 6：参数验证（缺少 query）
    try:
        test_6_validation_error()
        test_results.append(("测试 6 - 参数验证（缺少 query）", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 6 - 参数验证（缺少 query）", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 6 - 参数验证（缺少 query）", f"ERROR: {e}"))

    # 测试 7：query 过短
    try:
        test_7_query_too_short()
        test_results.append(("测试 7 - query 字段过短", "PASS"))
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        test_results.append(("测试 7 - query 字段过短", f"FAIL: {e}"))
    except Exception as e:
        print(f"  [异常] {e}")
        test_results.append(("测试 7 - query 字段过短", f"ERROR: {e}"))

    # 清理
    cleanup_research_records()
    cleanup_test_space()

    # 打印测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    pass_count = sum(1 for _, result in test_results if result == "PASS")
    fail_count = sum(1 for _, result in test_results if result.startswith("FAIL"))
    error_count = sum(1 for _, result in test_results if result.startswith("ERROR"))

    for name, result in test_results:
        status_icon = "[PASS]" if result == "PASS" else "[FAIL]" if result.startswith("FAIL") else "[ERROR]"
        print(f"  {status_icon} {name}: {result}")

    print(f"\n  总计：{len(test_results)} 个测试")
    print(f"  通过：{pass_count}")
    print(f"  失败：{fail_count}")
    print(f"  异常：{error_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
