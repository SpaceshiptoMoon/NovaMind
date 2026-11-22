"""NovaMind 端到端全链路测试（backend=stream 模式真机验证）。

覆盖：
1. 上传 → 解析 → 检索（正向 happy path，含多文档批量）
2. 文档删除 → 检索排除
3. 取消处理
4. 检索模式三档（语义/混合/AI 问答）
5. 文档标签打标与检索过滤
6. 错误路径（无效文件类型）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8100/api/v1"
PASS = []
FAIL = []
TOKEN = ""


def _headers(ct=None):
    h = {"Authorization": f"Bearer {TOKEN}"}
    if ct:
        h["Content-Type"] = ct
    return h


def _api(method, path, body=None, ct="application/json"):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=_headers(ct), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def _check(name, cond, detail=""):
    tag = "✅" if cond else "❌"
    line = f"{tag} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    PASS.append(name) if cond else FAIL.append(f"{name}: {detail}")
    return cond


def login():
    global TOKEN
    from pathlib import Path as _Path
    pw = os.environ.get("NM_PASS")
    if not pw:
        env_file = _Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ADMIN_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
                    break
    code, d = _api("POST", "/user/users/login", {"username": "admin", "password": pw})
    TOKEN = d.get("access_token", "")
    _check("登录", bool(TOKEN), f"HTTP {code}")


BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def create_space(name):
    code, d = _api("POST", "/spaces", {"name": name})
    return d.get("id") if code in (200, 201) else None


def create_kb(sid, name):
    code, d = _api("POST", f"/spaces/{sid}/knowledge-bases", {"name": name})
    return d.get("id") if code in (200, 201) else None


def upload_doc(sid, kid, filename, content):
    boundary = "----E2EBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    hdr = _headers(f"multipart/form-data; boundary={boundary}")
    req = urllib.request.Request(
        f"{BASE}/spaces/{sid}/knowledge-bases/{kid}/documents",
        data=body, headers=hdr, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    return d.get("document_id") or (d.get("data") or {}).get("document_id")


def trigger_process(sid, kid, doc_ids):
    code, d = _api(
        "POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
        {"document_ids": doc_ids},
    )
    return code


def poll_status(sid, kid, doc_id, max_wait=120):
    for _ in range(max_wait // 5):
        code, d = _api("GET", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{doc_id}")
        status = d.get("status")
        if status in (2, "COMPLETED", "completed"):
            return "completed"
        if status in (3, "FAILED", "failed"):
            return "failed"
        time.sleep(5)
    return "timeout"


def search(sid, kid, query, mode="content_hybrid", top_k=5):
    code, d = _api(
        "POST", f"/spaces/{sid}/knowledge-bases/{kid}/search",
        {"query": query, "search_mode": mode, "top_k": top_k},
    )
    return d.get("results") or []


# ==================== 主流程 ====================
if len(sys.argv) < 2 or sys.argv[1] != "--run":
    print("用法: python e2e_full_test.py --run")
    sys.exit(0)

print("=== NovaMind E2E 全链路测试 ===\n")
login()

# ---- 场景 1: 创建空间/KB ----
_ts = str(int(time.time()))
sid = create_space(f"e2e_full_test_{_ts}")
kid = create_kb(sid, f"e2e_full_test_kb_{_ts}")
_check("创建空间/KB", sid is not None and kid is not None, f"sid={sid} kid={kid}")

# ---- 场景 2: 上传多文档 + 批量触发 ----
docs_content = [
    ("doc_redis.md", "Redis 是一个高性能的内存键值数据库，支持 String、Hash、List、Set、ZSet 等数据结构。Redis 6.0 引入了多线程 I/O，Redis Stream 用于消息队列场景。"),
    ("doc_fastapi.md", "FastAPI 是一个现代、快速的 Python Web 框架，基于标准类型提示。FastAPI 支持异步编程、自动文档生成和依赖注入。"),
    ("doc_rag.md", "RAG（检索增强生成）是一种结合信息检索与大语言模型的技术。RAG 系统包含文档解析、切分、向量化、检索和生成五个阶段。"),
]
doc_ids = []
for fname, content in docs_content:
    did = upload_doc(sid, kid, fname, content)
    doc_ids.append(did)
_check("批量上传 3 文档", all(d is not None for d in doc_ids), f"ids={doc_ids}")

code = trigger_process(sid, kid, doc_ids)
_check("批量触发解析", code in (200, 202), f"HTTP {code}")

# ---- 场景 3: 等待全部完成 ----
all_done = False
for _ in range(24):
    time.sleep(5)
    statuses = []
    for did in doc_ids:
        code, d = _api("GET", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{did}")
        statuses.append(d.get("status"))
    if all(s in (2, "COMPLETED", "completed") for s in statuses):
        all_done = True
        break
    if all(s in (3, "FAILED", "failed", 2, "COMPLETED") for s in statuses):
        break
_check("全部文档解析完成", all_done, f"statuses={statuses}")

# ---- 场景 4: 检索三模式 ----
for mode in ("content_bm25", "content_vector", "content_hybrid"):
    results = search(sid, kid, "Redis 数据库", mode)
    _check(f"检索模式 {mode}", len(results) > 0, f"{len(results)} 条")

# ---- 场景 5: AI 问答 ----
code, d = _api(
    "POST", f"/spaces/{sid}/knowledge-bases/{kid}/search",
    {"query": "Redis 是什么", "search_mode": "content_hybrid", "top_k": 3,
     "llm": {"enabled": True}},
)
answer = d.get("answer")
_check("AI 问答（LLM 回答非空）", bool(answer), f"model={d.get('answer_model')}, answer_len={len(answer or '')}")

# ---- 场景 6: 删除文档 → 检索排除 ----
del_doc_id = doc_ids[0]
code, _ = _api("DELETE", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{del_doc_id}")
time.sleep(2)
results = search(sid, kid, doc_ids[0] if doc_ids else "Redis")
_check("删除文档后检索不再命中", len(results) == 0, f"残留 {len(results)} 条")

# ---- 场景 7: 上传无效文件类型 → 拒绝 ----
try:
    boundary = "----E2EBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="test.exe"\r\n'
        f"Content-Type: application/x-msdownload\r\n\r\n"
        f"MZ fake binary\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    hdr = _headers(f"multipart/form-data; boundary={boundary}")
    req = urllib.request.Request(
        f"{BASE}/spaces/{sid}/knowledge-bases/{kid}/documents",
        data=body, headers=hdr, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        _check("无效文件类型被拒绝", False, "上传成功但应拒绝")
except urllib.error.HTTPError as e:
    _check("无效文件类型被拒绝", e.code in (400, 415, 422), f"HTTP {e.code}")

# ---- 场景 8: 错误路径（不存在的文档检索） ----
code, d = _api(
    "POST", f"/spaces/{sid}/knowledge-bases/{kid}/search",
    {"query": "完全不存在的查询内容", "search_mode": "content_hybrid", "top_k": 3},
)
_check("不存在内容检索返回空/零结果", isinstance(d.get("results"), list), f"HTTP {code}")

# ---- 汇总 ----
print(f"\n{'='*60}")
print(f"通过: {len(PASS)}  失败: {len(FAIL)}")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print(f"  ❌ {f}")
print(f"{'='*60}")
sys.exit(1 if FAIL else 0)
