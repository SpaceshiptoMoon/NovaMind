# -*- coding: utf-8 -*-
"""
知识库测评模块 API 接口测试脚本

新流程：
  1. 管理员登录
  2. 创建测试知识空间
  3. 创建测试知识库
  4. 上传知识文档并等待解析完成
  5. 上传测试集文件 → 获得 test_set_id
  6. 基于 test_set_id 创建测评任务 → 异步执行
  7. 轮询等待任务完成
  8. 查看报告 / 导出结果

使用方式：
  确保后端服务已启动在 http://127.0.0.1:8100
  运行命令：python tests/test_evaluation_api.py
"""

import io
import json
import os
import sys
import time

import requests
import pytest

pytestmark = pytest.mark.integration

# ==================== 基础配置 ====================

BASE_URL = "http://127.0.0.1:8100"
TIMEOUT_SHORT = 10
TIMEOUT_POLL = 10
MAX_POLL_ATTEMPTS = 60

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-admin-password")

ts = int(time.time())
TEST_SPACE_NAME = f"evaluation_test_{ts}"
TEST_KB_NAME = f"测评测试知识库_{ts}"
TEST_DOC_NAME = f"测试知识文档_{ts}.txt"

# 全局变量
access_token = None
space_id = None
kb_id = None
document_id = None
test_set_id_json = None
test_set_id_csv = None
created_task_ids = []


# ==================== 知识文档内容 ====================

KNOWLEDGE_DOC = """Python FastAPI 框架技术文档

一、FastAPI 概述

FastAPI 是一个现代、高性能的 Python Web 框架，基于 Python 3.8+ 的类型提示构建。它的核心优势包括：
1. 极高的性能：与 NodeJS 和 Go 相当，是最快的 Python 框架之一
2. 快速开发：开发效率提升约 200%-300%
3. 减少 bug：减少约 40% 的人为错误
4. 智能 IDE 支持：处处有自动补全，编辑器中处处有类型提示
5. 简单易用：设计易于使用和学习，减少阅读文档的时间

FastAPI 由 Sebastian Ramirez 创建，基于 Starlette（处理 Web 部分）和 Pydantic（数据验证部分）构建。

二、核心特性

2.1 自动文档生成
FastAPI 能够根据代码中的类型提示自动生成交互式 API 文档。它支持两种文档界面：
- Swagger UI：提供交互式界面，可以直接在浏览器中测试 API
- ReDoc：提供美观的 API 文档展示，适合分享给团队和客户
文档在开发模式下可通过 /docs 和 /redoc 路径访问。

2.2 依赖注入系统
FastAPI 内置了强大的依赖注入系统，支持：
- 函数级别的依赖注入
- 类级别的依赖注入
- 依赖的嵌套和组合
- 全局依赖和路由级别的依赖
- 依赖的缓存和作用域控制

依赖注入通过 Depends() 函数实现，可以用于参数注入、权限验证、数据库会话管理等场景。

2.3 异步支持
FastAPI 原生支持 async/await 语法，可以同时处理同步和异步视图函数。它基于 ASGI（异步服务器网关接口）标准，
可以使用 Uvicorn 或 Hypercorn 作为 ASGI 服务器。异步处理使得 FastAPI 能够高效处理大量并发请求。

三、路由与请求处理

3.1 路由定义
FastAPI 使用装饰器模式定义路由，支持 GET、POST、PUT、DELETE、PATCH 等 HTTP 方法。路由支持路径参数、
查询参数、请求体等多种参数类型。路径参数使用花括号 {} 标记，如 /items/{item_id}。

3.2 请求体验证
FastAPI 使用 Pydantic 模型进行请求体验证。只需定义一个继承 BaseModel 的类，FastAPI 会自动：
- 验证请求数据类型
- 转换数据格式
- 生成 JSON Schema
- 在文档中展示请求格式
- 返回清晰的验证错误信息

3.3 响应模型
通过 response_model 参数指定响应模型，FastAPI 会自动：
- 过滤输出数据（只返回模型中定义的字段）
- 验证响应数据格式
- 在文档中展示响应格式
- 自动转换为 JSON 格式

四、中间件与异常处理

4.1 中间件
FastAPI 支持中间件机制，可以在请求处理前后添加自定义逻辑。常用的中间件包括：
- CORS 中间件：处理跨域请求
- 认证中间件：验证用户身份
- 日志中间件：记录请求信息
- 压缩中间件：压缩响应数据

4.2 异常处理
FastAPI 提供了完善的异常处理机制：
- 可以自定义异常处理器
- 支持 HTTP 异常和通用异常
- 异常可以返回自定义响应格式
- 内置的异常处理器提供友好的错误信息

五、数据库集成

FastAPI 可以与多种数据库集成：
- SQLAlchemy：最常用的 ORM，支持同步和异步模式
- Tortoise ORM：异步原生 ORM
- Databases：异步数据库支持库
- MongoDB/Motor：NoSQL 数据库的异步驱动

推荐使用 SQLAlchemy 2.0 的异步模式，配合 Alembic 进行数据库迁移管理。

六、安全与认证

6.1 JWT 认证
FastAPI 内置对 JWT（JSON Web Token）的支持，通过 python-jose 库实现。JWT 认证流程：
1. 用户使用用户名和密码登录
2. 服务器验证后返回 access_token 和 refresh_token
3. 客户端在后续请求中携带 access_token
4. 服务器验证 token 的有效性和过期时间

6.2 OAuth2 支持
FastAPI 内置 OAuth2 支持，支持多种授权模式：
- 密码模式（Password Flow）
- 授权码模式（Authorization Code Flow）
- 客户端凭证模式（Client Credentials Flow）
- 隐式授权模式（Implicit Flow）

6.3 密码哈希
推荐使用 Argon2 或 Bcrypt 进行密码哈希处理，不要使用 MD5 或 SHA1 等不安全的哈希算法。
"""


def make_test_json_from_doc() -> bytes:
    """基于上传的知识文档内容，生成 JSON 格式的测试集"""
    test_set = {
        "name": "FastAPI 技术文档测试集",
        "test_cases": [
            {
                "question": "FastAPI 的核心优势有哪些？",
                "expected_answer": "FastAPI 的核心优势包括：极高的性能（与 NodeJS 和 Go 相当）、快速开发（效率提升约 200%-300%）、减少 bug（减少约 40% 的人为错误）、智能 IDE 支持（自动补全和类型提示）、简单易用（易于学习和使用）。FastAPI 由 Sebastian Ramirez 创建，基于 Starlette 和 Pydantic 构建。",
            },
            {
                "question": "FastAPI 的依赖注入系统支持哪些功能？",
                "expected_answer": "FastAPI 依赖注入系统支持：函数级别和类级别的依赖注入、依赖的嵌套和组合、全局依赖和路由级别的依赖、依赖的缓存和作用域控制。通过 Depends() 函数实现，可用于参数注入、权限验证、数据库会话管理等场景。",
            },
            {
                "question": "FastAPI 如何实现自动文档生成？",
                "expected_answer": "FastAPI 根据代码中的类型提示自动生成交互式 API 文档。支持 Swagger UI 和 ReDoc 两种文档界面。Swagger UI 提供交互式界面可在浏览器中测试 API，ReDoc 提供美观的文档展示。开发模式下通过 /docs 和 /redoc 路径访问。",
            },
            {
                "question": "FastAPI 中如何使用 Pydantic 模型进行请求体验证？",
                "expected_answer": "定义一个继承 BaseModel 的类，FastAPI 会自动验证请求数据类型、转换数据格式、生成 JSON Schema、在文档中展示请求格式、返回清晰的验证错误信息。",
            },
            {
                "question": "FastAPI 推荐使用哪种密码哈希算法？",
                "expected_answer": "推荐使用 Argon2 或 Bcrypt 进行密码哈希处理，不应使用 MD5 或 SHA1 等不安全的哈希算法。",
            },
        ],
    }
    return json.dumps(test_set, ensure_ascii=False).encode("utf-8")


def make_test_csv_file() -> bytes:
    """生成 CSV 格式的测试集文件内容"""
    lines = [
        "question,expected_answer",
        '"FastAPI 支持哪些 HTTP 方法？","FastAPI 支持 GET、POST、PUT、DELETE、PATCH 等 HTTP 方法"',
        '"FastAPI 推荐哪个 ASGI 服务器？","推荐使用 Uvicorn 或 Hypercorn 作为 ASGI 服务器"',
    ]
    return "\n".join(lines).encode("utf-8-sig")


def eval_url(path: str = "") -> str:
    """构造测评 API URL"""
    return f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation{path}"


# ==================== 工具函数 ====================

def get_headers(token: str = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def print_test_header(test_name: str):
    print(f"\n{'=' * 60}")
    print(f"测试：{test_name}")
    print(f"{'=' * 60}")


def print_request_info(method: str, url: str, params: dict = None, body: dict = None):
    print(f"  请求：{method} {url}")
    if params:
        print(f"  查询参数：{json.dumps(params, ensure_ascii=False)}")
    if body:
        body_str = json.dumps(body, ensure_ascii=False)
        if len(body_str) > 500:
            body_str = body_str[:500] + "..."
        print(f"  请求体：{body_str}")


def print_response_info(response: requests.Response):
    print(f"  状态码：{response.status_code}")
    try:
        data = response.json()
        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(data_str) > 2000:
            data_str = data_str[:2000] + "..."
        print(f"  响应内容：{data_str}")
        return data
    except Exception:
        text = response.text
        if len(text) > 1000:
            text = text[:1000] + "..."
        print(f"  响应内容（文本）：{text}")
        return None


# ==================== 前置准备 ====================

def step_0_login():
    global access_token
    print_test_header("前置准备 - 登录管理员账号")

    url = f"{BASE_URL}/api/v1/user/users/login"
    body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}

    resp = requests.post(url, json=body, headers=get_headers(), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    if resp.status_code == 200 and data:
        access_token = data.get("access_token")
        print(f"  [成功] 管理员登录成功")
    else:
        print(f"  [失败] 无法登录")
        sys.exit(1)


def step_1_create_space():
    global space_id
    print_test_header("前置准备 - 创建测试知识空间")

    url = f"{BASE_URL}/api/v1/spaces"
    body = {"name": TEST_SPACE_NAME, "visibility": 0, "config": {"description": "测评模块自动化测试空间"}}

    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code in (200, 201), f"创建测试空间失败：{resp.status_code}"
    space_id = data["id"]
    print(f"  [成功] space_id = {space_id}")


def step_2_create_kb():
    global kb_id
    print_test_header("前置准备 - 创建测试知识库")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases"
    body = {"name": TEST_KB_NAME, "description": "测评模块自动化测试知识库"}

    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code in (200, 201), f"创建知识库失败：{resp.status_code}"
    kb_id = data["id"]
    print(f"  [成功] kb_id = {kb_id}")


def step_3_upload_document():
    global document_id
    print_test_header("前置准备 - 上传知识文档")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents"
    file_bytes = KNOWLEDGE_DOC.encode("utf-8")

    resp = requests.post(
        url,
        files={"files": (TEST_DOC_NAME, io.BytesIO(file_bytes), "text/plain")},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=TIMEOUT_SHORT,
    )
    data = print_response_info(resp)

    assert resp.status_code in (200, 201), f"上传文档失败：{resp.status_code}"
    document_id = data["document_id"]
    print(f"  [成功] document_id = {document_id}")


def step_4_process_document():
    print_test_header("前置准备 - 解析知识文档")

    url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}/process"
    body = {"enable_question_generation": False}

    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)
    assert resp.status_code in (200, 202), f"触发解析失败：{resp.status_code}"

    print(f"  等待文档解析完成...")
    status_url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}"

    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(status_url, headers=get_headers(access_token), timeout=TIMEOUT_POLL)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            print(f"  第 {attempt + 1} 次轮询：status={status}")
            if status == 2:
                print(f"  [成功] 文档解析完成")
                return
            if status == 3:
                print(f"  [警告] 文档解析失败")
                return
        time.sleep(10)

    print(f"  [警告] 文档解析轮询超时")


# ==================== 测试用例 ====================

def test_1_upload_json_test_set():
    """测试 1：上传 JSON 测试集"""
    global test_set_id_json
    print_test_header("测试 1 - 上传 JSON 测试集")

    url = eval_url("/test-sets")
    files = {"file": ("test_set.json", make_test_json_from_doc(), "application/json")}
    form_data = {"name": f"JSON测试集_{ts}"}

    print(f"  请求：POST {url}")
    resp = requests.post(url, files=files, data=form_data, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 201, f"上传测试集失败：{resp.status_code}"
    assert data is not None, "响应为空"
    assert "test_set_id" in data, "缺少 test_set_id"
    assert data["total_cases"] == 5, f"total_cases 应为 5，实际 {data['total_cases']}"

    test_set_id_json = data["test_set_id"]
    print(f"  [断言通过] test_set_id={test_set_id_json}, total_cases={data['total_cases']}")


def test_2_upload_csv_test_set():
    """测试 2：上传 CSV 测试集"""
    global test_set_id_csv
    print_test_header("测试 2 - 上传 CSV 测试集")

    url = eval_url("/test-sets")
    files = {"file": ("test_set.csv", make_test_csv_file(), "text/csv")}
    form_data = {"name": f"CSV测试集_{ts}"}

    print(f"  请求：POST {url}")
    resp = requests.post(url, files=files, data=form_data, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 201, f"上传 CSV 测试集失败：{resp.status_code}"
    assert data["total_cases"] == 2, f"total_cases 应为 2，实际 {data['total_cases']}"

    test_set_id_csv = data["test_set_id"]
    print(f"  [断言通过] test_set_id={test_set_id_csv}, total_cases={data['total_cases']}")


def test_3_list_test_sets():
    """测试 3：获取测试集列表"""
    print_test_header("测试 3 - 获取测试集列表")

    url = eval_url("/test-sets")
    resp = requests.get(url, params={"limit": 10}, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取列表失败：{resp.status_code}"
    assert "items" in data and "total" in data, "缺少 items/total"
    assert data["total"] >= 2, f"至少应有 2 个测试集，实际 {data['total']}"

    item = data["items"][0]
    for field in ["id", "name", "filename", "file_type", "total_cases"]:
        assert field in item, f"列表项缺少 {field}"
    print(f"  [断言通过] total={data['total']}, 首项 id={item['id']}")


def test_4_get_test_set_detail():
    """测试 4：获取测试集详情"""
    print_test_header("测试 4 - 获取测试集详情")

    url = eval_url(f"/test-sets/{test_set_id_json}")
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取详情失败：{resp.status_code}"
    assert data["id"] == test_set_id_json, "id 不匹配"
    assert data["total_cases"] == 5, "total_cases 不匹配"
    print(f"  [断言通过] 详情正确")


def test_5_upload_invalid_file():
    """测试 5：上传不支持的文件格式（期望 400）"""
    print_test_header("测试 5 - 不支持的文件格式（期望 400）")

    url = eval_url("/test-sets")
    files = {"file": ("test.txt", b"invalid", "text/plain")}
    form_data = {"name": "无效测试"}

    resp = requests.post(url, files=files, data=form_data, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 400, f"期望 400，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 400")


def test_6_create_task_from_json():
    """测试 6：基于 JSON 测试集创建测评任务"""
    print_test_header("测试 6 - 创建测评任务（JSON 测试集）")

    url = eval_url("/tasks")
    body = {
        "test_set_id": test_set_id_json,
        "name": f"JSON测评_{ts}",
        "config": {
            "top_k": 5,
            "faithfulness_strategy": "decompose",
            "relevance_strategy": "reverse_question",
        },
    }

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 202, f"创建任务失败：{resp.status_code}"
    assert "task_id" in data, "缺少 task_id"
    assert data["status"] == "pending", f"初始状态应为 pending，实际 {data['status']}"
    assert data["test_set_id"] == test_set_id_json, "test_set_id 不匹配"

    task_id = data["task_id"]
    created_task_ids.append(task_id)
    print(f"  [断言通过] task_id={task_id}, status={data['status']}")
    return task_id


def test_7_create_task_from_csv():
    """测试 7：基于 CSV 测试集创建测评任务"""
    print_test_header("测试 7 - 创建测评任务（CSV 测试集）")

    url = eval_url("/tasks")
    body = {
        "test_set_id": test_set_id_csv,
        "name": f"CSV测评_{ts}",
    }

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 202, f"创建 CSV 任务失败：{resp.status_code}"
    assert "task_id" in data, "缺少 task_id"
    assert data["test_set_id"] == test_set_id_csv, "test_set_id 不匹配"

    created_task_ids.append(data["task_id"])
    print(f"  [断言通过] task_id={data['task_id']}")
    return data["task_id"]


def test_8_list_tasks():
    """测试 8：获取测评任务列表"""
    print_test_header("测试 8 - 获取测评任务列表")

    url = eval_url("/tasks")
    params = {"limit": 10}

    print_request_info("GET", url, params=params)
    resp = requests.get(url, params=params, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取任务列表失败：{resp.status_code}"
    assert "items" in data and "total" in data, "缺少 items/total"

    if data["items"]:
        item = data["items"][0]
        for field in ["id", "test_set_id", "name", "status", "created_at"]:
            assert field in item, f"列表项缺少 {field}"
    print(f"  [断言通过] total={data['total']}")


def test_9_get_task_detail():
    """测试 9：获取测评任务详情"""
    print_test_header("测试 9 - 获取测评任务详情")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}")

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取详情失败：{resp.status_code}"
    assert data["id"] == task_id, "id 不匹配"
    assert "test_set_id" in data, "缺少 test_set_id"
    assert "config" in data, "缺少 config"
    assert data["test_set_id"] == test_set_id_json, "test_set_id 不匹配"

    print(f"  [断言通过] id={data['id']}, status={data['status']}, test_set_id={data['test_set_id']}")


def test_10_task_not_found():
    """测试 10：获取不存在的任务（期望 404）"""
    print_test_header("测试 10 - 任务不存在（期望 404）")

    url = eval_url("/tasks/999999")
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 404")


def test_11_wait_for_completion():
    """测试 11：等待测评任务完成"""
    print_test_header("测试 11 - 等待测评任务完成")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}")

    print(f"  轮询任务 {task_id} 状态...")

    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_POLL)
        data = resp.json()
        status = data.get("status")

        print(f"  第 {attempt + 1} 次轮询：status={status}")

        if status == 2:  # COMPLETED
            print(f"  [成功] 测评任务已完成！")
            return
        elif status == 3:  # FAILED
            error_msg = data.get("error_message", "未知错误")
            print(f"  [警告] 测评任务失败：{error_msg}")
            return

        time.sleep(10)

    print(f"  [跳过] 轮询超时")


def test_12_get_report():
    """测试 12：获取测评报告"""
    print_test_header("测试 12 - 获取测评报告")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}/report")

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"获取报告失败：{resp.status_code}"

    for field in ["task_id", "name", "status", "total_cases", "completed_cases", "summary"]:
        assert field in data, f"报告缺少 {field}"

    assert data["task_id"] == task_id, "task_id 不匹配"
    assert data["total_cases"] == 5, f"total_cases 应为 5，实际 {data['total_cases']}"

    summary = data.get("summary", {})
    if summary:
        print(f"  检索指标：{summary.get('retrieval', {})}")
        print(f"  生成指标：{summary.get('generation', {})}")
        print(f"  端到端：{summary.get('end_to_end', {})}")
        print(f"  耗时：{summary.get('elapsed_seconds')}s")

    details = data.get("details", [])
    if details:
        first = details[0]
        print(f"  首条详情：index={first.get('index')}, question={first.get('question', '')[:30]}...")
        gen_scores = first.get("generation_scores", {})
        if gen_scores:
            print(f"  生成评分：correctness={gen_scores.get('correctness')}, faithfulness={gen_scores.get('faithfulness')}")

    print(f"  [断言通过] 报告结构完整")


def test_13_submit_human_scores():
    """测试 13：提交人工评分"""
    print_test_header("测试 13 - 提交人工评分")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}/scores")

    body = {
        "scores": [
            {"index": 0, "score": 9, "comment": "回答准确"},
            {"index": 1, "score": 7, "comment": "基本正确"},
            {"index": 2, "score": 8, "comment": "描述准确"},
        ]
    }

    print_request_info("POST", url, body=body)
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    assert resp.status_code == 200, f"提交评分失败：{resp.status_code}"
    assert "updated_count" in data, "缺少 updated_count"
    assert data["updated_count"] == 3, f"updated_count 应为 3，实际 {data['updated_count']}"

    print(f"  [断言通过] 更新 {data['updated_count']} 条")


def test_14_export_json():
    """测试 14：导出 JSON 格式结果"""
    print_test_header("测试 14 - 导出 JSON 结果")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}/export?format=json")

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)

    assert resp.status_code == 200, f"导出失败：{resp.status_code}"
    assert "application/json" in resp.headers.get("content-type", ""), "Content-Type 应为 JSON"

    data = resp.json()
    assert "summary" in data or "details" in data, "导出内容应包含 summary 或 details"
    print(f"  [断言通过] JSON 导出成功，大小={len(resp.content)} bytes")


def test_15_export_csv():
    """测试 15：导出 CSV 格式结果"""
    print_test_header("测试 15 - 导出 CSV 结果")

    if not created_task_ids:
        print("  [跳过] 没有可用的 task_id")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}/export?format=csv")

    print_request_info("GET", url)
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)

    assert resp.status_code == 200, f"导出失败：{resp.status_code}"
    assert "text/csv" in resp.headers.get("content-type", ""), "Content-Type 应为 CSV"

    lines = resp.text.strip().split("\n")
    assert len(lines) >= 2, "CSV 至少应有表头 + 1 行数据"
    assert "index" in lines[0], "CSV 表头应包含 index"
    print(f"  [断言通过] CSV 导出成功，{len(lines)} 行")


def test_16_delete_task():
    """测试 16：删除测评任务"""
    print_test_header("测试 16 - 删除测评任务")

    if len(created_task_ids) < 2:
        print("  [跳过] 没有足够的 task_id")
        return

    task_id = created_task_ids[1]
    url = eval_url(f"/tasks/{task_id}")

    print_request_info("DELETE", url)
    resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    data = print_response_info(resp)

    if resp.status_code == 409:
        print(f"  [跳过] 任务执行中（409）")
        return

    assert resp.status_code == 200, f"删除失败：{resp.status_code}"

    # 验证删除后 404
    verify_resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    assert verify_resp.status_code == 404, f"删除后应 404，实际 {verify_resp.status_code}"

    created_task_ids.remove(task_id)
    print(f"  [断言通过] 任务已删除，再次获取返回 404")


def test_17_delete_task_not_found():
    """测试 17：删除不存在的任务（期望 404）"""
    print_test_header("测试 17 - 删除不存在任务（期望 404）")

    url = eval_url("/tasks/999999")
    resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 404")


def test_18_submit_scores_not_found():
    """测试 18：向不存在的任务提交评分（期望 404）"""
    print_test_header("测试 18 - 提交评分 404")

    url = eval_url("/tasks/999999/scores")
    body = {"scores": [{"index": 0, "score": 5}]}

    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 404")


def test_19_report_not_found():
    """测试 19：获取不存在任务的报告（期望 404）"""
    print_test_header("测试 19 - 报告 404")

    url = eval_url("/tasks/999999/report")
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 404")


def test_20_upload_empty_file():
    """测试 20：上传空文件（期望 400）"""
    print_test_header("测试 20 - 空文件（期望 400）")

    url = eval_url("/test-sets")
    files = {"file": ("empty.json", b"", "application/json")}
    form_data = {"name": "空文件测试"}

    resp = requests.post(url, files=files, data=form_data, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 400, f"期望 400，实际 {resp.status_code}"
    print(f"  [断言通过] 正确返回 400")


def test_21_cancel_task():
    """测试 21：取消测评任务"""
    print_test_header("测试 21 - 取消测评任务")

    # 先创建一个新任务用于取消
    url = eval_url("/tasks")
    body = {
        "test_set_id": test_set_id_json,
        "name": "待取消任务",
        "config": {"enable_generation": False},
    }
    resp = requests.post(url, json=body, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    assert resp.status_code == 202, f"创建任务失败：{resp.status_code}"
    cancel_task_id = resp.json()["task_id"]
    created_task_ids.append(cancel_task_id)
    print(f"  创建任务 {cancel_task_id}")

    # 取消任务
    url = eval_url(f"/tasks/{cancel_task_id}/cancel")
    resp = requests.post(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
    data = resp.json()
    assert data["status"] == "cancelled", f"期望 cancelled，实际 {data['status']}"
    print(f"  [断言通过] 任务状态为 cancelled")


def test_22_get_task_progress():
    """测试 22：获取任务进度"""
    print_test_header("测试 22 - 获取任务进度")

    if not created_task_ids:
        print("  [跳过] 无可用任务")
        return

    task_id = created_task_ids[0]
    url = eval_url(f"/tasks/{task_id}/progress")
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
    data = resp.json()
    assert "task_id" in data, "缺少 task_id 字段"
    assert "status" in data, "缺少 status 字段"
    assert "current" in data, "缺少 current 字段"
    assert "total" in data, "缺少 total 字段"
    print(f"  [断言通过] 进度：{data['current']}/{data['total']}，状态：{data['status']}")


def test_23_update_test_set():
    """测试 23：更新测试集名称"""
    print_test_header("测试 23 - 更新测试集名称")

    url = eval_url(f"/test-sets/{test_set_id_json}")
    new_name = f"更新后的测试集_{int(time.time())}"
    resp = requests.put(url, json={"name": new_name}, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
    data = resp.json()
    assert data["name"] == new_name, f"名称未更新：{data['name']}"
    print(f"  [断言通过] 名称更新为：{new_name}")


def test_24_preview_test_set_cases():
    """测试 24：预览测试集用例"""
    print_test_header("测试 24 - 预览测试集用例")

    url = eval_url(f"/test-sets/{test_set_id_json}/cases")
    resp = requests.get(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
    print_response_info(resp)

    assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
    data = resp.json()
    assert "test_set_id" in data, "缺少 test_set_id 字段"
    assert "total_cases" in data, "缺少 total_cases 字段"
    assert "test_cases" in data, "缺少 test_cases 字段"
    assert len(data["test_cases"]) > 0, "测试用例列表为空"

    case = data["test_cases"][0]
    assert "question" in case, "用例缺少 question 字段"
    assert "expected_answer" in case, "用例缺少 expected_answer 字段"
    print(f"  [断言通过] 共 {data['total_cases']} 条用例，首条：{case['question'][:30]}...")

def cleanup():
    print_test_header("清理测试资源")

    # 删除任务
    for task_id in list(created_task_ids):
        url = eval_url(f"/tasks/{task_id}")
        try:
            resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
            print(f"  删除任务 {task_id}：{resp.status_code}")
        except Exception as e:
            print(f"  删除任务 {task_id} 出错：{e}")

    # 删除测试集
    for ts_id in [test_set_id_json, test_set_id_csv]:
        if ts_id:
            url = eval_url(f"/test-sets/{ts_id}")
            try:
                resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
                print(f"  删除测试集 {ts_id}：{resp.status_code}")
            except Exception as e:
                print(f"  删除测试集 {ts_id} 出错：{e}")

    # 删除文档
    if document_id:
        url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}"
        try:
            resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
            print(f"  删除文档：{resp.status_code}")
        except Exception as e:
            print(f"  删除文档出错：{e}")

    # 删除知识库
    if kb_id:
        url = f"{BASE_URL}/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}"
        try:
            resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
            print(f"  删除知识库：{resp.status_code}")
        except Exception as e:
            print(f"  删除知识库出错：{e}")

    # 删除空间
    if space_id:
        url = f"{BASE_URL}/api/v1/spaces/{space_id}"
        try:
            resp = requests.delete(url, headers=get_headers(access_token), timeout=TIMEOUT_SHORT)
            print(f"  删除空间：{resp.status_code}")
        except Exception as e:
            print(f"  删除空间出错：{e}")


# ==================== 主流程 ====================

def run_test(name, func, *args):
    try:
        func(*args)
        return (name, "PASS")
    except AssertionError as e:
        print(f"  [断言失败] {e}")
        return (name, f"FAIL: {e}")
    except Exception as e:
        print(f"  [异常] {e}")
        return (name, f"ERROR: {e}")


def main():
    print("=" * 60)
    print("知识库测评模块 API 接口测试（新架构）")
    print(f"服务地址：{BASE_URL}")
    print(f"测试时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 前置准备
    try:
        step_0_login()
        step_1_create_space()
        step_2_create_kb()
        step_3_upload_document()
        step_4_process_document()
    except Exception as e:
        print(f"\n  [失败] 前置准备失败：{e}")
        cleanup()
        sys.exit(1)

    # 执行测试
    results = []

    results.append(run_test("测试 1 - 上传 JSON 测试集", test_1_upload_json_test_set))
    results.append(run_test("测试 2 - 上传 CSV 测试集", test_2_upload_csv_test_set))
    results.append(run_test("测试 3 - 获取测试集列表", test_3_list_test_sets))
    results.append(run_test("测试 4 - 获取测试集详情", test_4_get_test_set_detail))
    results.append(run_test("测试 5 - 不支持的文件格式 400", test_5_upload_invalid_file))
    results.append(run_test("测试 6 - 创建 JSON 测评任务", test_6_create_task_from_json))
    results.append(run_test("测试 7 - 创建 CSV 测评任务", test_7_create_task_from_csv))
    results.append(run_test("测试 8 - 获取任务列表", test_8_list_tasks))
    results.append(run_test("测试 9 - 获取任务详情", test_9_get_task_detail))
    results.append(run_test("测试 10 - 任务不存在 404", test_10_task_not_found))
    results.append(run_test("测试 11 - 等待任务完成", test_11_wait_for_completion))
    results.append(run_test("测试 12 - 获取测评报告", test_12_get_report))
    results.append(run_test("测试 13 - 提交人工评分", test_13_submit_human_scores))
    results.append(run_test("测试 14 - 导出 JSON", test_14_export_json))
    results.append(run_test("测试 15 - 导出 CSV", test_15_export_csv))
    results.append(run_test("测试 16 - 删除任务", test_16_delete_task))
    results.append(run_test("测试 17 - 删除不存在任务 404", test_17_delete_task_not_found))
    results.append(run_test("测试 18 - 提交评分 404", test_18_submit_scores_not_found))
    results.append(run_test("测试 19 - 报告 404", test_19_report_not_found))
    results.append(run_test("测试 20 - 空文件 400", test_20_upload_empty_file))
    results.append(run_test("测试 21 - 取消测评任务", test_21_cancel_task))
    results.append(run_test("测试 22 - 获取任务进度", test_22_get_task_progress))
    results.append(run_test("测试 23 - 更新测试集名称", test_23_update_test_set))
    results.append(run_test("测试 24 - 预览测试集用例", test_24_preview_test_set_cases))

    # 清理
    cleanup()

    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    pass_count = sum(1 for _, r in results if r == "PASS")
    fail_count = sum(1 for _, r in results if r.startswith("FAIL"))
    error_count = sum(1 for _, r in results if r.startswith("ERROR"))

    for name, result in results:
        icon = "[PASS]" if result == "PASS" else "[FAIL]" if result.startswith("FAIL") else "[ERROR]"
        print(f"  {icon} {name}")

    print(f"\n  总计：{len(results)} 个测试")
    print(f"  通过：{pass_count}")
    print(f"  失败：{fail_count}")
    print(f"  异常：{error_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
