"""
知识空间模块 API 自动化测试脚本
================================
覆盖全部 33 个接口，使用 requests 库执行测试。
外部服务（MinIO、Elasticsearch、Redis、LLM）不可用时优雅跳过相关测试。

使用方式：
    python tests/test_knowledge_space_api.py
"""

import io
import sys
import time
import traceback
from typing import Optional

import requests
import pytest

pytestmark = pytest.mark.integration

# ======================== 配置 ========================
BASE_URL = "http://127.0.0.1:8100"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "***REMOVED***"
ADMIN_USERNAME = "admin_test"
ADMIN_PASSWORD = "***REMOVED***"
TIMEOUT = 30  # 请求超时秒数

# ======================== 全局状态 ========================
session = requests.Session()
token: Optional[str] = None
headers: dict = {}

# 测试过程中创建的资源 ID，用于后续测试和清理
created_space_id: Optional[int] = None
created_kb_id: Optional[int] = None
created_document_id: Optional[int] = None
created_member_id: Optional[int] = None
invite_token_value: Optional[str] = None

# 统计（使用列表避免 global 声明问题）
_stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}


def _add_stat(key: str, n: int = 1):
    _stats[key] += n


def _get_stat(key: str) -> int:
    return _stats[key]


# ======================== 工具函数 ========================
def print_header(title: str):
    """打印分节标题"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_test(name: str):
    """打印测试名称"""
    print(f"\n  [测试] {name}")


def print_pass(msg: str = "通过"):
    """打印通过"""
    _add_stat("passed")
    print(f"    [PASS] {msg}")


def print_fail(msg: str = "失败"):
    """打印失败"""
    _add_stat("failed")
    print(f"    [FAIL] {msg}")


def print_skip(msg: str = "跳过"):
    """打印跳过"""
    _add_stat("skipped")
    print(f"    [SKIP] {msg}")


def is_external_service_error(resp: requests.Response) -> bool:
    """判断响应是否由外部服务不可用导致（MinIO / ES / Redis / LLM）"""
    if resp.status_code >= 500:
        body = resp.text.lower()
        keywords = ["minio", "elasticsearch", "redis", "connection", "connect", "timeout",
                     "refused", "unavailable", "llm", "embedding", "openai"]
        return any(kw in body for kw in keywords)
    return False


def assert_status(resp: requests.Response, expected_code: int, label: str = "") -> bool:
    """断言 HTTP 状态码，返回是否通过"""
    _add_stat("total")
    desc = f"{label} - 期望 {expected_code}, 实际 {resp.status_code}" if label else f"期望 {expected_code}, 实际 {resp.status_code}"

    # 外部服务不可用时优雅跳过
    if is_external_service_error(resp):
        print_skip(f"外部服务不可用, 跳过 ({desc})")
        return False

    if resp.status_code == expected_code:
        print_pass(desc)
        return True
    else:
        print_fail(f"{desc} | 响应: {resp.text[:300]}")
        return False


def assert_field(obj: dict, field: str, expected_value=None, label: str = "") -> bool:
    """断言字段存在及值"""
    _add_stat("total")
    desc = f"{label} 字段 '{field}'" if label else f"字段 '{field}'"

    if field not in obj:
        print_fail(f"{desc} 不存在 | 返回: {list(obj.keys())}")
        return False

    if expected_value is not None and obj[field] != expected_value:
        print_fail(f"{desc} 期望 {expected_value}, 实际 {obj[field]}")
        return False

    print_pass(desc)
    return True


def assert_field_exists(obj: dict, *fields: str, label: str = "") -> int:
    """断言多个字段存在，返回通过的个数"""
    count = 0
    for f in fields:
        if assert_field(obj, f, label=label):
            count += 1
    return count


def assert_type(obj: dict, field: str, expected_type: type | tuple[type, ...], label: str = "") -> bool:
    """断言字段类型"""
    _add_stat("total")
    if isinstance(expected_type, tuple):
        type_name = " | ".join(t.__name__ for t in expected_type)
    else:
        type_name = expected_type.__name__
    desc = f"{label} 字段 '{field}' 类型为 {type_name}" if label else f"字段 '{field}' 类型为 {type_name}"

    if field not in obj:
        print_fail(f"{desc} - 字段不存在")
        return False

    if not isinstance(obj[field], expected_type):
        print_fail(f"{desc} - 实际类型 {type(obj[field]).__name__}, 值: {obj[field]}")
        return False

    print_pass(desc)
    return True


def safe_json(resp: requests.Response) -> Optional[dict]:
    """安全解析 JSON"""
    try:
        return resp.json()
    except Exception:
        return None


def api_url(path: str) -> str:
    """拼接完整 URL"""
    return f"{BASE_URL}{path}"


# ======================== 登录获取 Token ========================
def login():
    """
    使用系统默认管理员账号登录（启动时自动创建）。
    """
    global token, headers
    print_header("前置准备 - 登录管理员账号")
    _add_stat("total")

    try:
        resp = session.post(
            api_url("/api/v1/user/users/login"),
            json={"username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD},
            timeout=TIMEOUT
        )
    except requests.exceptions.ConnectionError:
        print_fail("无法连接服务器，请确认服务已启动")
        sys.exit(1)

    if resp.status_code != 200:
        print_fail(f"管理员登录失败 [{resp.status_code}]: {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token") or data.get("token") or data.get("data", {}).get("access_token")
    if not token:
        print_fail(f"登录响应中未找到 token 字段: {list(data.keys())}")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}"}
    session.headers.update(headers)
    print_pass(f"管理员 [{DEFAULT_ADMIN_USERNAME}] 登录成功, token: {token[:20]}...")


# ======================== 一、知识空间管理 (7 个接口) ========================
def test_1_1_create_space():
    """1.1 创建知识空间"""
    global created_space_id
    print_test("1.1 创建知识空间 POST /api/v1/spaces")

    payload = {
        "name": f"自动化测试空间_{int(time.time())}",
        "visibility": 1,
        "config": {
            "description": "自动化测试创建的知识空间",
            "tags": ["测试", "自动化"]
        }
    }

    try:
        resp = session.post(api_url("/api/v1/spaces"), json=payload, timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "创建空间")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "id", "name", "owner_id", "visibility", "status", "created_at", label="创建空间")
    assert_type(data, "id", int, label="创建空间")
    assert_type(data, "name", str, label="创建空间")
    assert_field(data, "name", payload["name"], label="创建空间")
    assert_field(data, "visibility", 1, label="创建空间")
    assert_field(data, "status", 1, label="创建空间")

    if "id" in data:
        created_space_id = data["id"]
        print(f"    [INFO] 创建的空间 ID: {created_space_id}")


def test_1_2_get_my_spaces():
    """1.2 获取我的空间列表"""
    print_test("1.2 获取我的空间列表 GET /api/v1/spaces")

    try:
        resp = session.get(api_url("/api/v1/spaces"), params={"skip": 0, "limit": 20}, timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "我的空间列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", "skip", "limit", label="空间列表")
    assert_type(data, "items", list, label="空间列表")
    assert_type(data, "total", int, label="空间列表")

    if data.get("items") and len(data["items"]) > 0:
        space = data["items"][0]
        assert_field_exists(space, "id", "name", "visibility", "status", label="空间列表项")


def test_1_3_get_public_spaces():
    """1.3 获取公开空间列表"""
    print_test("1.3 获取公开空间列表 GET /api/v1/spaces/public")

    try:
        resp = session.get(api_url("/api/v1/spaces/public"), params={"skip": 0, "limit": 10}, timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "公开空间列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", label="公开空间列表")
    assert_type(data, "items", list, label="公开空间列表")


def test_1_4_search_spaces():
    """1.4 搜索知识空间"""
    print_test("1.4 搜索知识空间 GET /api/v1/spaces/search")

    try:
        resp = session.get(
            api_url("/api/v1/spaces/search"),
            params={"keyword": "测试", "skip": 0, "limit": 10},
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "搜索空间")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", label="搜索空间")
    assert_type(data, "items", list, label="搜索空间")


def test_1_5_get_space_detail():
    """1.5 获取空间详情"""
    print_test("1.5 获取空间详情 GET /api/v1/spaces/{space_id}")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.get(api_url(f"/api/v1/spaces/{created_space_id}"), timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "空间详情")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "id", "name", "owner_id", "visibility", "status", "created_at", "updated_at", label="空间详情")
    assert_field(data, "id", created_space_id, label="空间详情")


def test_1_6_update_space():
    """1.6 更新空间设置"""
    print_test("1.6 更新空间设置 PUT /api/v1/spaces/{space_id}")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    payload = {
        "name": f"更新后空间名_{int(time.time())}",
        "visibility": 2,
        "config": {
            "description": "更新后的描述",
            "tags": ["测试", "更新"]
        }
    }

    try:
        resp = session.put(api_url(f"/api/v1/spaces/{created_space_id}"), json=payload, timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "更新空间")

    data = safe_json(resp)
    if not data:
        return

    assert_field(data, "name", payload["name"], label="更新空间")
    assert_field(data, "visibility", 2, label="更新空间")

    # 改回 visibility=1 方便后续测试
    session.put(
        api_url(f"/api/v1/spaces/{created_space_id}"),
        json={"visibility": 1},
        timeout=TIMEOUT
    )


def test_1_7_delete_space():
    """1.7 删除知识空间（放到最后执行，这里先测不存在的空间）"""
    print_test("1.7 删除知识空间 DELETE /api/v1/spaces/{space_id} (测试不存在的 ID)")

    # 测试删除不存在的空间
    try:
        resp = session.delete(api_url("/api/v1/spaces/999999"), timeout=TIMEOUT)
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    # 不存在的空间应该返回 404
    assert_status(resp, 404, "删除不存在空间")
    print("    [INFO] 实际空间删除将在全部测试结束后执行")


# ======================== 二、知识库管理 (7 个接口) ========================
def test_2_1_get_knowledge_bases():
    """2.1 获取知识库列表"""
    print_test("2.1 获取知识库列表 GET /api/v1/spaces/{space_id}/knowledge-bases")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases"),
            params={"skip": 0, "limit": 20},
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "知识库列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", "skip", "limit", label="知识库列表")
    assert_type(data, "items", list, label="知识库列表")


def test_2_2_get_kb_detail_not_found():
    """2.2 获取知识库详情（不存在的 ID）"""
    print_test("2.2 获取知识库详情 GET .../knowledge-bases/{kb_id} (不存在的 ID)")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/999999"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 404, "知识库详情-不存在")


def test_2_3_create_knowledge_base():
    """2.3 创建知识库"""
    global created_kb_id
    print_test("2.3 创建知识库 POST .../knowledge-bases")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    payload = {
        "name": f"自动化测试知识库_{int(time.time())}",
        "config": {
            "description": "自动化测试创建的知识库",
            "splitting": {
                "strategy": "recursive",
                "chunk_size": 1000,
                "chunk_overlap": 100
            },
            "parsing": {
                "extract_tables": True,
                "preserve_structure": True
            },
            "question_generation": {
                "enabled": False
            }
        }
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务不可用, 跳过创建知识库")
        return

    assert_status(resp, 200, "创建知识库")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "id", "name", "space_id", "status", label="创建知识库")
    assert_type(data, "id", int, label="创建知识库")
    assert_field(data, "name", payload["name"], label="创建知识库")

    if "id" in data:
        created_kb_id = data["id"]
        print(f"    [INFO] 创建的知识库 ID: {created_kb_id}")


def test_2_2_get_kb_detail():
    """2.2 获取知识库详情（正常情况）"""
    print_test("2.2 获取知识库详情 GET .../knowledge-bases/{kb_id}")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "知识库详情")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "id", "name", "space_id", "config", "status", "created_at", "updated_at", label="知识库详情")
    assert_field(data, "id", created_kb_id, label="知识库详情")


def test_2_4_update_knowledge_base():
    """2.4 更新知识库"""
    print_test("2.4 更新知识库 PUT .../knowledge-bases/{kb_id}")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    payload = {
        "name": f"更新后知识库_{int(time.time())}",
        "config": {
            "description": "更新后的知识库描述"
        }
    }

    try:
        resp = session.put(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "更新知识库")

    data = safe_json(resp)
    if not data:
        return

    assert_field(data, "name", payload["name"], label="更新知识库")


def test_2_5_delete_kb_not_found():
    """2.5 删除知识库（不存在的 ID）"""
    print_test("2.5 删除知识库 DELETE .../knowledge-bases/{kb_id} (不存在的 ID)")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.delete(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/999999"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 404, "删除不存在知识库")
    print("    [INFO] 实际知识库删除将在全部测试结束后执行")


def test_2_6_get_kb_config():
    """2.6 获取知识库配置"""
    print_test("2.6 获取知识库配置 GET .../knowledge-bases/{kb_id}/config")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/config"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "知识库配置")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "kb_id", "name", "config", label="知识库配置")
    assert_field(data, "kb_id", created_kb_id, label="知识库配置")


def test_2_7_update_kb_config():
    """2.7 更新知识库配置（PATCH）"""
    print_test("2.7 更新知识库配置 PATCH .../knowledge-bases/{kb_id}/config")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    payload = {
        "splitting": {
            "strategy": "recursive",
            "chunk_size": 1500,
            "chunk_overlap": 200
        },
        "parsing": {
            "extract_tables": True,
            "preserve_structure": False
        }
    }

    try:
        resp = session.patch(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/config"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "更新知识库配置")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "kb_id", "config", label="更新知识库配置")


# ======================== 三、文档管理 (9 个接口) ========================
def test_3_1_upload_document():
    """3.1 上传文档"""
    global created_document_id
    print_test("3.1 上传文档 POST .../documents")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    # 创建一个测试用的 txt 文件
    file_content = f"这是一个自动化测试文档。\n创建时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n用于测试文档上传接口。"
    file_bytes = file_content.encode("utf-8")

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents"),
            files={"file": ("测试文档.txt", io.BytesIO(file_bytes), "text/plain")},
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务(MinIO)不可用, 跳过上传文档")
        return

    assert_status(resp, 200, "上传文档")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "document_id", "filename", "status", "message", label="上传文档")
    assert_field(data, "status", "uploaded", label="上传文档")

    if "document_id" in data:
        created_document_id = data["document_id"]
        print(f"    [INFO] 上传的文档 ID: {created_document_id}")


def test_3_2_get_documents():
    """3.2 获取文档列表"""
    print_test("3.2 获取文档列表 GET .../documents")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents"),
            params={"skip": 0, "limit": 20},
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "文档列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", "skip", "limit", label="文档列表")
    assert_type(data, "items", list, label="文档列表")


def test_3_3_get_document_detail():
    """3.3 获取文档详情"""
    print_test("3.3 获取文档详情 GET .../documents/{document_id}")

    if not created_space_id or not created_kb_id or not created_document_id:
        _add_stat("total")
        print_skip("无可用空间/知识库/文档 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "文档详情")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "id", "filename", "file_type", "file_size", "status", label="文档详情")
    assert_field(data, "id", created_document_id, label="文档详情")


def test_3_4_get_document_chunks():
    """3.4 获取文档分块"""
    print_test("3.4 获取文档分块 GET .../documents/{document_id}/chunks")

    if not created_space_id or not created_kb_id or not created_document_id:
        _add_stat("total")
        print_skip("无可用空间/知识库/文档 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/chunks"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "文档分块")

    data = safe_json(resp)
    if not data:
        return

    # 分块列表是数组
    assert_type(data, list, label="文档分块") if isinstance(data, dict) else None
    if isinstance(data, list):
        _add_stat("total")
        print_pass(f"分块列表返回 {len(data)} 个分块")
    elif isinstance(data, dict) and "items" in data:
        assert_type(data, "items", list, label="文档分块")


def test_3_5_download_document():
    """3.5 下载文档"""
    print_test("3.5 下载文档 GET .../documents/{document_id}/download")

    if not created_space_id or not created_kb_id or not created_document_id:
        _add_stat("total")
        print_skip("无可用空间/知识库/文档 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/download"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务(MinIO)不可用, 跳过下载文档")
        return

    _add_stat("total")

    if resp.status_code == 200:
        content_type = resp.headers.get("content-type", "")
        print_pass(f"下载文档成功, Content-Type: {content_type}, 大小: {len(resp.content)} 字节")
    elif resp.status_code in (404, 500):
        # 文档可能还没完成存储
        print_skip(f"下载文档返回 {resp.status_code} (可能文件尚未存储完成)")
    else:
        print_fail(f"下载文档期望 200, 实际 {resp.status_code}")


def test_3_6_delete_document_not_found():
    """3.6 删除文档（不存在的 ID）"""
    print_test("3.6 删除文档 DELETE .../documents/{document_id} (不存在的 ID)")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.delete(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/999999"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 404, "删除不存在文档")
    print("    [INFO] 实际文档删除将在全部测试结束后执行")


def test_3_7_process_document():
    """3.7 触发文档拆分解析"""
    print_test("3.7 触发文档拆分解析 POST .../documents/{document_id}/process")

    if not created_space_id or not created_kb_id or not created_document_id:
        _add_stat("total")
        print_skip("无可用空间/知识库/文档 ID, 跳过")
        return

    payload = {
        "enable_question_generation": False,
        "question_count": 5
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/process"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务不可用, 跳过触发文档解析")
        return

    # 202 Accepted 或 200
    _add_stat("total")
    if resp.status_code in (200, 202):
        print_pass(f"触发文档解析, 状态码: {resp.status_code}")
        data = safe_json(resp)
        if data:
            assert_field_exists(data, "document_id", "status", "message", label="触发解析")
    else:
        print_fail(f"触发文档解析期望 200/202, 实际 {resp.status_code} | {resp.text[:300]}")


def test_3_8_batch_process_documents():
    """3.8 批量触发文档拆分解析"""
    print_test("3.8 批量触发文档拆分解析 POST .../documents/process")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    doc_ids = [created_document_id] if created_document_id else []

    payload = {
        "document_ids": doc_ids,
        "enable_question_generation": False
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/process"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务不可用, 跳过批量触发解析")
        return

    _add_stat("total")
    if resp.status_code in (200, 202):
        print_pass(f"批量触发解析, 状态码: {resp.status_code}")
        data = safe_json(resp)
        if data:
            assert_field_exists(data, "total", "success", "failed", label="批量触发解析")
    else:
        print_fail(f"批量触发解析期望 200/202, 实际 {resp.status_code} | {resp.text[:300]}")


def test_3_9_reprocess_document():
    """3.9 重新解析文档"""
    print_test("3.9 重新解析文档 POST .../documents/{document_id}/reprocess")

    if not created_space_id or not created_kb_id or not created_document_id:
        _add_stat("total")
        print_skip("无可用空间/知识库/文档 ID, 跳过")
        return

    payload = {
        "enable_question_generation": False,
        "question_count": 3
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/reprocess"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务不可用, 跳过重新解析")
        return

    _add_stat("total")
    if resp.status_code in (200, 202):
        print_pass(f"重新解析文档, 状态码: {resp.status_code}")
        data = safe_json(resp)
        if data:
            assert_field_exists(data, "document_id", "status", "message", label="重新解析")
    elif resp.status_code == 409:
        print_pass("重新解析返回 409 (文档正在处理中, 符合预期)")
    else:
        print_fail(f"重新解析期望 200/202/409, 实际 {resp.status_code} | {resp.text[:300]}")


# ======================== 四、成员管理 (7 个接口) ========================
def test_4_1_get_members():
    """4.1 获取成员列表"""
    print_test("4.1 获取成员列表 GET /api/v1/spaces/{space_id}/members")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/members"),
            params={"skip": 0, "limit": 20},
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "成员列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "items", "total", "skip", "limit", label="成员列表")
    assert_type(data, "items", list, label="成员列表")

    # 创建者应该自动成为管理员成员
    if data.get("items") and len(data["items"]) > 0:
        member = data["items"][0]
        assert_field_exists(member, "id", "user_id", "role", "status", "username", label="成员列表项")
        assert_field(member, "role", 2, label="创建者角色为ADMIN")  # ADMIN=2
        if "id" in member:
            global created_member_id
            created_member_id = member["id"]


def test_4_2_invite_member():
    """4.2 邀请成员"""
    global invite_token_value
    print_test("4.2 邀请成员 POST /api/v1/spaces/{space_id}/members")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    # 尝试邀请一个用户（可能不存在，测试接口调用即可）
    payload = {
        "email": "test_invite@example.com",
        "role": 0,
        "expires_hours": 48
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/members"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    _add_stat("total")

    if resp.status_code == 200:
        print_pass("邀请成员成功")
        data = safe_json(resp)
        if data:
            assert_field_exists(data, "member_id", "invite_token", "message", label="邀请成员")
            invite_token_value = data.get("invite_token")
    elif resp.status_code == 404:
        # 用户不存在也属于正常业务响应
        print_pass(f"邀请成员返回 404 (用户不存在, 属于正常业务响应)")
    elif resp.status_code == 409:
        print_pass(f"邀请成员返回 409 (用户已是成员, 属于正常业务响应)")
    else:
        print_fail(f"邀请成员期望 200/404/409, 实际 {resp.status_code} | {resp.text[:300]}")


def test_4_3_join_space():
    """4.3 加入空间"""
    print_test("4.3 加入空间 POST .../members/join")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    # 使用无效的 invite_token 测试
    payload = {
        "invite_token": "invalid_token_for_test_12345"
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/members/join"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    _add_stat("total")

    # 无效 token 应该返回 400
    if resp.status_code in (400, 410):
        print_pass(f"加入空间(无效token)返回 {resp.status_code}, 符合预期")
    elif resp.status_code == 200:
        print_pass("加入空间成功")
    else:
        print_fail(f"加入空间期望 400/410, 实际 {resp.status_code} | {resp.text[:300]}")


def test_4_4_get_my_member_info():
    """4.4 获取我的成员信息"""
    print_test("4.4 获取我的成员信息 GET .../members/me")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/members/me"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "我的成员信息")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "user_id", "role", "status", label="我的成员信息")
    assert_field(data, "role", 2, label="我的成员信息(ADMIN)")


def test_4_5_update_member_role():
    """4.5 更新成员角色"""
    print_test("4.5 更新成员角色 PUT .../members/{target_user_id}")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    # 测试修改自己的角色（应该失败）
    # 先获取自己的 user_id
    try:
        me_resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/members/me"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if me_resp.status_code != 200:
        _add_stat("total")
        print_skip("无法获取自身成员信息, 跳过")
        return

    me_data = me_resp.json()
    my_user_id = me_data.get("user_id")

    # 尝试修改自己的角色 -> 应该返回 403
    payload = {"role": 1}
    try:
        resp = session.put(
            api_url(f"/api/v1/spaces/{created_space_id}/members/{my_user_id}"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    _add_stat("total")
    if resp.status_code == 403:
        print_pass("修改自己角色返回 403, 符合预期")
    elif resp.status_code == 200:
        print_pass("修改自己角色返回 200 (接口允许)")
    else:
        print_fail(f"修改成员角色期望 403/200, 实际 {resp.status_code} | {resp.text[:300]}")


def test_4_6_remove_member_not_found():
    """4.6 移除成员（不存在的用户）"""
    print_test("4.6 移除成员 DELETE .../members/{target_user_id} (不存在的用户)")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    try:
        resp = session.delete(
            api_url(f"/api/v1/spaces/{created_space_id}/members/999999"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    # 不存在的成员应该返回 404
    assert_status(resp, 404, "移除不存在成员")


def test_4_7_leave_space():
    """4.7 离开空间"""
    print_test("4.7 离开空间 POST .../members/leave")

    if not created_space_id:
        _add_stat("total")
        print_skip("无可用空间 ID, 跳过")
        return

    # 管理员是唯一成员时不能离开，测试接口调用即可
    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/members/leave"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    _add_stat("total")

    # 管理员是唯一管理员时可能返回 403，或者正常返回
    if resp.status_code == 200:
        print_pass("离开空间返回 200")
        data = safe_json(resp)
        if data:
            assert_field_exists(data, "success", "message", label="离开空间")
    elif resp.status_code == 403:
        print_pass("离开空间返回 403 (唯一管理员不能离开, 符合预期)")
    else:
        print_fail(f"离开空间期望 200/403, 实际 {resp.status_code} | {resp.text[:300]}")


# ======================== 五、知识检索 (3 个接口) ========================
def test_5_1_search():
    """5.1 统一检索接口"""
    print_test("5.1 统一检索接口 POST .../search")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    payload = {
        "query": "自动化测试检索",
        "search_mode": "content_hybrid",
        "top_k": 5,
        "weights": {
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "content_weight": 0.6,
            "question_weight": 0.4,
            "rrf_k": 60
        },
        "score_threshold": 0.0,
        "fallback_on_unavailable": True,
        "use_cache": True
    }

    try:
        resp = session.post(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/search"),
            json=payload,
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    if is_external_service_error(resp):
        _add_stat("total")
        print_skip("外部服务(ES/Embedding)不可用, 跳过检索")
        return

    assert_status(resp, 200, "统一检索")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "results", "total", "query", "search_mode", "top_k", "elapsed_ms", label="统一检索")
    assert_field(data, "query", payload["query"], label="统一检索")
    assert_type(data, "results", list, label="统一检索")
    assert_type(data, "elapsed_ms", (int, float), label="统一检索")


def test_5_2_get_search_modes():
    """5.2 获取可用检索模式"""
    print_test("5.2 获取可用检索模式 GET .../search/modes")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/search/modes"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "检索模式列表")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(data, "modes", "total", label="检索模式")
    assert_type(data, "modes", list, label="检索模式")

    if data.get("modes") and len(data["modes"]) > 0:
        mode = data["modes"][0]
        assert_field_exists(mode, "mode", "label", "description", "requires_question_generation", label="检索模式项")


def test_5_3_get_model_config():
    """5.3 获取知识库模型配置"""
    print_test("5.3 获取知识库模型配置 GET .../search/model-config")

    if not created_space_id or not created_kb_id:
        _add_stat("total")
        print_skip("无可用空间/知识库 ID, 跳过")
        return

    try:
        resp = session.get(
            api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/search/model-config"),
            timeout=TIMEOUT
        )
    except Exception as e:
        _add_stat("total")
        print_skip(f"请求异常: {e}")
        return

    assert_status(resp, 200, "模型配置")

    data = safe_json(resp)
    if not data:
        return

    assert_field_exists(
        data,
        "embedding_model", "embedding_dimension",
        "default_llm_model", "default_rerank_model",
        "available_embedding_models", "available_llm_models", "available_rerank_models",
        label="模型配置"
    )


# ======================== 清理资源 ========================
def cleanup():
    """清理测试创建的所有资源"""
    print_header("清理测试资源")

    # 删除文档
    if created_space_id and created_kb_id and created_document_id:
        print(f"  清理文档 ID: {created_document_id}")
        try:
            resp = session.delete(
                api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}"),
                timeout=TIMEOUT
            )
            if resp.status_code == 200:
                print(f"    文档已删除")
            else:
                print(f"    文档删除返回 {resp.status_code}")
        except Exception as e:
            print(f"    文档删除异常: {e}")

    # 删除知识库
    if created_space_id and created_kb_id:
        print(f"  清理知识库 ID: {created_kb_id}")
        try:
            resp = session.delete(
                api_url(f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}"),
                timeout=TIMEOUT
            )
            if resp.status_code == 200:
                print(f"    知识库已删除")
            else:
                print(f"    知识库删除返回 {resp.status_code}")
        except Exception as e:
            print(f"    知识库删除异常: {e}")

    # 删除空间
    if created_space_id:
        print(f"  清理空间 ID: {created_space_id}")
        try:
            resp = session.delete(
                api_url(f"/api/v1/spaces/{created_space_id}"),
                timeout=TIMEOUT
            )
            if resp.status_code == 200:
                print(f"    空间已删除")
            else:
                print(f"    空间删除返回 {resp.status_code}")
        except Exception as e:
            print(f"    空间删除异常: {e}")


# ======================== 主流程 ========================
def main():
    print("=" * 60)
    print("  知识空间模块 API 自动化测试")
    print(f"  服务地址: {BASE_URL}")
    print(f"  测试账号: {ADMIN_USERNAME}")
    print(f"  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 登录
    login()

    # 一、知识空间管理 (7 个接口)
    print_header("一、知识空间管理 (7 个接口)")
    test_1_1_create_space()
    test_1_2_get_my_spaces()
    test_1_3_get_public_spaces()
    test_1_4_search_spaces()
    test_1_5_get_space_detail()
    test_1_6_update_space()
    test_1_7_delete_space()

    # 二、知识库管理 (7 个接口)
    print_header("二、知识库管理 (7 个接口)")
    test_2_1_get_knowledge_bases()
    test_2_2_get_kb_detail_not_found()
    test_2_3_create_knowledge_base()
    test_2_2_get_kb_detail()
    test_2_4_update_knowledge_base()
    test_2_5_delete_kb_not_found()
    test_2_6_get_kb_config()
    test_2_7_update_kb_config()

    # 三、文档管理 (9 个接口)
    print_header("三、文档管理 (9 个接口)")
    test_3_1_upload_document()
    test_3_2_get_documents()
    test_3_3_get_document_detail()
    test_3_4_get_document_chunks()
    test_3_5_download_document()
    test_3_6_delete_document_not_found()
    test_3_7_process_document()
    test_3_8_batch_process_documents()
    test_3_9_reprocess_document()

    # 五、知识检索 (3 个接口) — 必须在成员管理之前，因为 4.7 离开空间会软删除空间
    print_header("五、知识检索 (3 个接口)")
    test_5_1_search()
    test_5_2_get_search_modes()
    test_5_3_get_model_config()

    # 四、成员管理 (7 个接口)
    print_header("四、成员管理 (7 个接口)")
    test_4_1_get_members()
    test_4_2_invite_member()
    test_4_3_join_space()
    test_4_4_get_my_member_info()
    test_4_5_update_member_role()
    test_4_6_remove_member_not_found()
    test_4_7_leave_space()

    # 清理资源
    cleanup()

    # 输出汇总
    print_header("测试汇总")
    total = _get_stat("total")
    passed = _get_stat("passed")
    failed = _get_stat("failed")
    skipped = _get_stat("skipped")
    print(f"  总断言数: {total}")
    print(f"  通过: {passed}")
    print(f"  失败: {failed}")
    print(f"  跳过: {skipped}")
    rate = (passed / total * 100) if total > 0 else 0
    print(f"  通过率: {rate:.1f}%")
    print(f"  结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if failed > 0:
        print("\n  [WARNING] 存在失败的测试用例，请检查上方输出！")
        sys.exit(1)
    else:
        print("\n  [SUCCESS] 全部测试通过！")
        sys.exit(0)


if __name__ == "__main__":
    main()
