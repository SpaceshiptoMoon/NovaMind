"""
RAG 全链路测试脚本
=================
完整测试离线（上传→切分→向量化→ES索引）和在线（全部 9 种检索策略 + LLM 生成）过程
使用真实 PDF 文档，打印每一步的中间结果

使用方式:
    python tests/test_rag_pipeline.py
"""

import os
import sys
import time
import requests
from typing import Optional

# ======================== 配置 ========================
BASE_URL = "http://127.0.0.1:8100"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "***REMOVED***"
TIMEOUT = 120

# 测试用 PDF 文件
PDF_PATH = r"C:\Users\xl\Desktop\24研究生\实习\简历\***REMOVED***_桂林电子科技大学_27届_简历.pdf"

# 全部 9 种检索模式
ALL_SEARCH_MODES = [
    ("content_bm25",    "内容 BM25 全文检索"),
    ("content_vector",  "内容向量语义检索"),
    ("content_hybrid",  "内容混合检索（向量+BM25）"),
    ("question_bm25",   "问题 BM25 全文检索"),
    ("question_vector", "问题向量语义检索"),
    ("question_hybrid", "问题混合检索（向量+BM25）"),
    ("all_bm25",        "全字段 BM25 检索"),
    ("all_vector",      "全字段向量检索"),
    ("all_hybrid",      "全字段全算法融合检索"),
]

# ======================== 全局状态 ========================
session = requests.Session()
token: Optional[str] = None
headers: dict = {}
created_space_id: Optional[int] = None
created_kb_id: Optional[int] = None
created_document_id: Optional[int] = None


# ======================== 工具函数 ========================

def print_step(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_sub(msg: str):
    print(f"  {msg}")


def print_data(label: str, data):
    """格式化打印数据"""
    if isinstance(data, dict):
        print(f"  [{label}]")
        for k, v in data.items():
            val_str = str(v)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            print(f"    {k}: {val_str}")
    elif isinstance(data, list):
        print(f"  [{label}] 共 {len(data)} 项")
        for i, item in enumerate(data):
            print(f"    --- 第 {i+1} 项 ---")
            if isinstance(item, dict):
                for k, v in item.items():
                    val_str = str(v)
                    if len(val_str) > 150:
                        val_str = val_str[:150] + "..."
                    print(f"      {k}: {val_str}")
            else:
                print(f"      {item}")
    else:
        print(f"  [{label}] {data}")


def api(method: str, path: str, **kwargs) -> requests.Response:
    """统一 API 调用"""
    url = f"{BASE_URL}{path}"
    resp = getattr(session, method)(url, timeout=TIMEOUT, **kwargs)
    return resp


def search_url() -> str:
    """拼接搜索接口 URL"""
    return f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/search"


def do_search(query: str, search_mode: str, top_k: int = 3, **extra) -> dict:
    """执行搜索并返回 JSON"""
    body = {
        "query": query,
        "search_mode": search_mode,
        "top_k": top_k,
    }
    body.update(extra)
    resp = api("post", search_url(), json=body)
    if resp.status_code != 200:
        print_sub(f"  请求失败: status={resp.status_code}")
        try:
            err = resp.json()
            print_sub(f"  错误: {err.get('detail', err)}")
        except Exception:
            print_sub(f"  响应: {resp.text[:300]}")
        return {"results": [], "error": True}
    return resp.json()


def print_results(data: dict, max_content_len: int = 150):
    """统一打印搜索结果"""
    results = data.get("results", [])
    elapsed = data.get("elapsed_ms", "?")
    search_mode = data.get("search_mode", "?")
    mode_fallback = data.get("mode_fallback", False)
    original_mode = data.get("original_mode")

    fallback_info = f" (降级自 {original_mode})" if mode_fallback else ""
    print_sub(f"实际模式: {search_mode}{fallback_info}")
    print_sub(f"命中: {len(results)} 条, 耗时: {elapsed}ms")

    # 打印 LLM 生成回答（如果有）
    answer = data.get("answer")
    if answer:
        print_sub(f"LLM 回答 (模型: {data.get('answer_model', '?')}, "
                   f"耗时: {data.get('answer_elapsed_ms', '?')}ms):")
        for line in answer.split("\n"):
            print(f"    {line}")

    for j, r in enumerate(results):
        score = r.get("score", 0)
        content = r.get("content", "")
        chunk_id = r.get("chunk_id", "?")
        doc_id = r.get("document_id", "?")

        print(f"    [{j+1}] chunk={chunk_id} doc={doc_id} score={score:.4f}")
        if content:
            preview = content[:max_content_len]
            suffix = f"... (剩余 {len(content)-max_content_len} 字符)" if len(content) > max_content_len else ""
            print(f"         {preview}{suffix}")


# ======================== 离线阶段 ========================

def step_0_login():
    """登录"""
    print_step("步骤 0: 登录")
    global token, headers
    resp = api("post", "/api/v1/user/users/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    })
    data = resp.json()
    token = data.get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"}
    session.headers.update(headers)
    print_sub(f"登录成功, token: {token[:30]}...")


def step_1_create_space():
    """创建知识空间"""
    print_step("步骤 1: 创建知识空间")
    global created_space_id
    resp = api("post", "/api/v1/spaces", json={
        "name": f"RAG测试空间_{int(time.time())}",
        "visibility": 0,
    })
    data = resp.json()
    created_space_id = data.get("id")
    print_sub(f"空间 ID: {created_space_id}, 名称: {data.get('name')}")


def step_2_create_kb():
    """创建知识库"""
    print_step("步骤 2: 创建知识库")
    global created_kb_id
    resp = api("post", f"/api/v1/spaces/{created_space_id}/knowledge-bases", json={
        "name": f"RAG测试知识库_{int(time.time())}",
        "config": {
            "splitting": {
                "strategy": "recursive",
                "chunk_size": 500,
                "chunk_overlap": 50,
            },
            "parsing": {
                "extract_tables": True,
                "preserve_structure": True,
            },
            "question_generation": {
                "enabled": True,
            },
        },
    })
    data = resp.json()
    created_kb_id = data.get("id")
    print_sub(f"知识库 ID: {created_kb_id}, 名称: {data.get('name')}")
    print_sub(f"ES 索引: {data.get('storage', {}).get('es_index_name')}")


def step_3_upload_document():
    """上传 PDF 文档"""
    print_step("步骤 3: 上传 PDF 文档")

    if not os.path.exists(PDF_PATH):
        print_sub(f"文件不存在: {PDF_PATH}")
        sys.exit(1)

    file_size = os.path.getsize(PDF_PATH)
    print_sub(f"文件: {PDF_PATH}")
    print_sub(f"大小: {file_size} 字节 ({file_size/1024:.1f} KB)")

    global created_document_id
    with open(PDF_PATH, "rb") as f:
        resp = api("post",
            f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents",
            files={"file": (os.path.basename(PDF_PATH), f, "application/pdf")},
        )

    data = resp.json()
    created_document_id = data.get("document_id")
    print_sub(f"文档 ID: {created_document_id}, 状态: {data.get('status')}")
    print_data("上传响应", data)


def step_4_trigger_process():
    """触发文档拆分解析"""
    print_step("步骤 4: 触发文档拆分解析（切分 + 向量化 + ES 索引）")

    resp = api("post",
        f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/process",
        json={"enable_question_generation": True},
    )
    data = resp.json()
    print_sub(f"触发响应: status_code={resp.status_code}")
    print_data("触发结果", data)


def step_5_wait_for_completion():
    """轮询等待处理完成"""
    print_step("步骤 5: 等待文档处理完成（轮询状态）")

    max_wait = 300
    start = time.time()
    last_status = None

    while time.time() - start < max_wait:
        resp = api("get",
            f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}",
        )
        data = resp.json()
        status = data.get("status", "unknown")
        status_map = {0: "uploaded", 1: "processing", 2: "completed", 3: "failed", 4: "deleted"}
        status_str = status_map.get(status, str(status)) if isinstance(status, int) else status

        if status_str != last_status:
            elapsed = time.time() - start
            print_sub(f"[{elapsed:.1f}s] 文档状态: {status_str} (raw={status})")
            last_status = status_str

        if status_str == "completed" or status == 2:
            print_sub(f"处理完成! 耗时: {time.time()-start:.1f}s")
            print_data("文档详情", data)
            return True

        if status_str == "failed" or status == 3:
            print_sub(f"处理失败! 耗时: {time.time()-start:.1f}s")
            print_data("文档详情", data)
            return False

        time.sleep(2)

    print_sub(f"超时! 等待了 {max_wait}s, 最后状态: {last_status}")
    return False


def step_6_check_chunks():
    """查看 ES 中的分块结果"""
    print_step("步骤 6: 查看文档分块结果")

    resp = api("get",
        f"/api/v1/spaces/{created_space_id}/knowledge-bases/{created_kb_id}/documents/{created_document_id}/chunks",
    )
    data = resp.json()
    chunks = data if isinstance(data, list) else data.get("items", data.get("chunks", []))

    print_sub(f"总分块数: {len(chunks)}")

    for i, chunk in enumerate(chunks):
        if isinstance(chunk, dict):
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", chunk.get("id", ""))
            has_embedding = chunk.get("embedding") is not None
            print(f"  [{i+1}/{len(chunks)}] chunk_id={chunk_id} "
                  f"有向量={has_embedding} 内容长度={len(content)}")

    return len(chunks)


# ======================== 在线阶段：全部 9 种检索策略 ========================

def step_7_all_search_modes():
    """测试全部 9 种检索模式"""
    print_step("步骤 7: 全部 9 种检索模式测试")

    query = "这个人的专业技能和项目经历"

    success_count = 0
    fail_count = 0
    fallback_count = 0

    for mode, desc in ALL_SEARCH_MODES:
        print(f"\n  [{mode}] {desc}")
        print(f"  --- 查询: 「{query}」 ---")

        extra = {}
        if "hybrid" in mode:
            extra["weights"] = {"vector_weight": 0.7, "bm25_weight": 0.3}

        data = do_search(query, mode, top_k=3, **extra)

        if data.get("error"):
            fail_count += 1
            continue

        success_count += 1
        if data.get("mode_fallback"):
            fallback_count += 1

        print_results(data)

    # 汇总
    print(f"\n  {'='*50}")
    print(f"  检索模式测试汇总")
    print(f"  {'='*50}")
    print(f"  总计: {len(ALL_SEARCH_MODES)} 种模式")
    print(f"  成功: {success_count} 种")
    print(f"  失败: {fail_count} 种")
    print(f"  降级: {fallback_count} 种 (question_*/all_* 降级到 content_*)")


def step_8_content_bm25_deep():
    """内容 BM25 深度测试 — 不同查询"""
    print_step("步骤 8: 内容 BM25 深度测试 (content_bm25)")

    queries = ["教育背景", "项目经验", "实习经历", "技能", "Python"]

    for query in queries:
        print(f"\n  --- 查询: 「{query}」 ---")
        data = do_search(query, "content_bm25", top_k=3)
        if not data.get("error"):
            print_results(data)


def step_9_content_vector_deep():
    """内容向量检索深度测试 — 自然语言查询"""
    print_step("步骤 9: 内容向量检索深度测试 (content_vector)")

    queries = [
        "这个人的学历是什么",
        "掌握哪些编程语言",
        "做过什么项目",
        "有哪些实习经历",
    ]

    for query in queries:
        print(f"\n  --- 查询: 「{query}」 ---")
        data = do_search(query, "content_vector", top_k=3)
        if not data.get("error"):
            print_results(data)


def step_10_content_hybrid_deep():
    """内容混合检索深度测试 — 不同权重"""
    print_step("步骤 10: 内容混合检索深度测试 (content_hybrid)")

    query = "这个人的专业技能和项目经历"

    weight_sets = [
        {"vector_weight": 0.5, "bm25_weight": 0.5, "label": "均衡 (0.5/0.5)"},
        {"vector_weight": 0.7, "bm25_weight": 0.3, "label": "偏语义 (0.7/0.3)"},
        {"vector_weight": 0.9, "bm25_weight": 0.1, "label": "强语义 (0.9/0.1)"},
        {"vector_weight": 0.3, "bm25_weight": 0.7, "label": "偏关键词 (0.3/0.7)"},
    ]

    for ws in weight_sets:
        label = ws.pop("label")
        print(f"\n  --- 权重: {label} ---")
        data = do_search(query, "content_hybrid", top_k=5, weights=ws)
        if not data.get("error"):
            print_results(data)


def step_11_search_with_llm():
    """混合检索 + LLM 回答生成"""
    print_step("步骤 11: 混合检索 + LLM 回答生成")

    queries = [
        "请介绍这个人的教育背景和项目经历",
        "这个人掌握哪些技能？有哪些实习经历？",
    ]

    for query in queries:
        print(f"\n  --- 查询: 「{query}」 ---")
        data = do_search(query, "content_hybrid", top_k=5, weights={
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
        }, llm={
            "enabled": True,
            "temperature": 0.7,
            "top_p": 0.9,
        })
        if not data.get("error"):
            print_results(data)


def step_12_search_with_rerank_and_llm():
    """混合检索 + Rerank 重排序 + LLM 回答生成"""
    print_step("步骤 12: 混合检索 + Rerank 重排序 + LLM 回答生成")

    queries = [
        "这个人在顺丰科技负责什么工作，有哪些成果？",
        "请详细介绍一下这个人的所有项目经历和成果",
    ]

    for query in queries:
        print(f"\n  --- 查询: 「{query}」 ---")
        data = do_search(query, "content_hybrid", top_k=10, weights={
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
        }, rerank={
            "enabled": True,
            "top_k": 3,
        }, llm={
            "enabled": True,
            "temperature": 0.7,
            "top_p": 0.9,
        })
        if not data.get("error"):
            print_results(data)


def step_cleanup():
    """保留测试资源（不删除）"""
    print_step("测试资源保留")
    if created_space_id:
        print_sub(f"空间 ID: {created_space_id}")
    if created_kb_id:
        print_sub(f"知识库 ID: {created_kb_id}")
    if created_document_id:
        print_sub(f"文档 ID: {created_document_id}")
    print_sub("所有资源已保留，未删除")


# ======================== 主流程 ========================
def main():
    print("=" * 60)
    print("  RAG 全链路测试（9 种检索策略 + LLM 生成）")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  文档: {PDF_PATH}")
    print(f"  检索模式: {len(ALL_SEARCH_MODES)} 种")
    print("=" * 60)

    try:
        # ===== 离线阶段 =====
        print("\n" + "#" * 60)
        print("  离线阶段: 上传 → 切分 → 向量化 → ES 索引")
        print("#" * 60)

        step_0_login()
        step_1_create_space()
        step_2_create_kb()
        step_3_upload_document()
        step_4_trigger_process()

        completed = step_5_wait_for_completion()
        if not completed:
            print("\n  [ABORT] 文档处理失败或超时，跳过在线测试")
            step_cleanup()
            return

        chunk_count = step_6_check_chunks()
        if chunk_count == 0:
            print("\n  [ABORT] 没有生成任何分块，跳过在线测试")
            step_cleanup()
            return

        # ===== 在线阶段 =====
        print("\n" + "#" * 60)
        print("  在线阶段: 9 种检索策略 + LLM 生成")
        print("#" * 60)

        # 全部 9 种检索模式一览
        step_7_all_search_modes()

        # 三大基础策略深度测试
        step_8_content_bm25_deep()
        step_9_content_vector_deep()
        step_10_content_hybrid_deep()

        # 生成策略
        step_11_search_with_llm()
        step_12_search_with_rerank_and_llm()

    finally:
        step_cleanup()

    print("\n" + "=" * 60)
    print("  RAG 全链路测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
