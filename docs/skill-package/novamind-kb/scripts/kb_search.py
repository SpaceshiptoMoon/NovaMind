"""kb_search 脚本：NovaMind 知识库检索（经 /mcp 端点裸 JSON-RPC）。

配置一次即可直接使用——优先级：命令行参数 > 环境变量 > config.json > 默认值。
把本脚本旁的 config.example.json 复制为 config.json 并填三项即完成配置：

    {
      "api_key": "nvm_xxx",
      "space_id": 6,
      "kb_id": 11
    }

之后用法：python kb_search.py "查询文本"

环境变量等价物：NOVAMIND_API_KEY / NOVAMIND_MCP_URL / NOVAMIND_SPACE_ID / NOVAMIND_KB_ID
依赖：仅 Python 标准库（urllib），无需安装任何包。
输出：stdout 打印检索结果 JSON（total/results）；错误输出到 stderr 并以非零退出
（0 成功 / 2 缺凭证 / 3 多空间候选待指定 / 1 其他错误）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Windows 控制台默认 GBK，重定向/管道场景统一 UTF-8（通用，不降级内容）
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_MCP_URL = "http://127.0.0.1:8100/mcp"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
SEARCH_MODES = (
    "content_bm25", "content_vector", "content_hybrid",
    "question_bm25", "question_vector", "question_hybrid",
    "all_bm25", "all_vector", "all_hybrid",
)


def load_file_config() -> dict:
    """读 config.json（与 SKILL.md 同目录）；不存在或损坏时返回空 dict。"""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"警告：config.json 读取失败（{e}），忽略该配置文件。", file=sys.stderr)
        return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NovaMind 知识库检索（配置见 config.example.json）",
    )
    parser.add_argument("query", help="查询文本")
    parser.add_argument("--space-id", type=int, default=None, help="覆盖配置的 space_id")
    parser.add_argument("--kb-id", type=int, default=None, help="覆盖配置的 kb_id")
    parser.add_argument("--top-k", type=int, default=None, help="返回片段数（默认 5）")
    parser.add_argument("--search-mode", default=None, choices=SEARCH_MODES,
                        help=f"检索方式（默认 content_hybrid），可选：{', '.join(SEARCH_MODES)}")
    parser.add_argument("--score-threshold", type=float, default=None, help="0~1 相关度下限")
    parser.add_argument("--vector-weight", type=float, default=None, help="hybrid 向量权重（默认 0.7）")
    parser.add_argument("--bm25-weight", type=float, default=None, help="hybrid BM25 权重（默认 0.3）")
    parser.add_argument("--no-cache", action="store_true", help="跳过检索缓存")
    return parser


def resolve_settings(args: argparse.Namespace) -> dict:
    """按 命令行 > 环境变量 > config.json > 默认 解析出最终配置。"""
    cfg = load_file_config()
    api_key = os.environ.get("NOVAMIND_API_KEY") or cfg.get("api_key")
    base_url = (
        os.environ.get("NOVAMIND_MCP_URL")
        or cfg.get("base_url")
        or DEFAULT_MCP_URL
    ).rstrip("/")
    space_id = first_not_none(
        args.space_id,
        env_int("NOVAMIND_SPACE_ID"),
        cfg.get("space_id"),
    )
    kb_id = first_not_none(
        args.kb_id,
        env_int("NOVAMIND_KB_ID"),
        cfg.get("kb_id"),
    )
    return {
        "api_key": api_key,
        "base_url": base_url,
        "space_id": space_id,
        "kb_id": kb_id,
    }


def first_not_none(*values):
    """返回第一个非 None 的值（全 None 则 None）。"""
    return next((v for v in values if v is not None), None)


def env_int(name: str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"警告：环境变量 {name}={raw!r} 不是整数，忽略。", file=sys.stderr)
        return None


def call_kb_search(args: argparse.Namespace, settings: dict) -> dict:
    """裸 JSON-RPC 调 /mcp 的 kb_search tool，返回解析后的结果 dict。"""
    api_key = settings["api_key"]
    if not api_key:
        print(
            "错误：未配置 API key。三选一：\n"
            "  1. config.json 填 api_key（模板见同目录 config.example.json）；\n"
            "  2. 环境变量 NOVAMIND_API_KEY；\n"
            "  3. 命令行不直接支持——前两者任选。\n"
            "key 创建方式见 docs/agent/ 下接入指南。",
            file=sys.stderr,
        )
        sys.exit(2)

    mcp_arguments: dict = {
        "query": args.query,
        "top_k": args.top_k if args.top_k is not None else 5,
        "search_mode": args.search_mode or "content_hybrid",
        "vector_weight": args.vector_weight if args.vector_weight is not None else 0.7,
        "bm25_weight": args.bm25_weight if args.bm25_weight is not None else 0.3,
        "use_cache": not args.no_cache,
    }
    if settings["space_id"] is not None:
        mcp_arguments["space_id"] = settings["space_id"]
    if settings["kb_id"] is not None:
        mcp_arguments["kb_id"] = settings["kb_id"]
    if args.score_threshold is not None:
        mcp_arguments["score_threshold"] = args.score_threshold

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "kb_search", "arguments": mcp_arguments},
    }).encode("utf-8")

    request = urllib.request.Request(
        settings["base_url"],
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        print(f"错误：HTTP {e.code}——{detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"错误：无法连接 {settings['base_url']}——{e.reason}", file=sys.stderr)
        sys.exit(1)

    if "error" in body:
        # MCP 协议层错误（鉴权/未知 tool 等）：error.message 即给调用方的说明
        print(f"错误：{body['error'].get('message', body['error'])}", file=sys.stderr)
        sys.exit(1)

    content = body.get("result", {}).get("content", [])
    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")

    # tool 执行错误（目标解析失败/非法参数等）：isError=true，text 是给调用方的说明
    if body.get("result", {}).get("isError"):
        message = text.removeprefix("Error executing tool kb_search: ")
        print(f"错误：{message}", file=sys.stderr)
        # 多空间候选属可自愈错误：按候选清单在配置或 --space-id 中固定后重试
        sys.exit(3)

    return json.loads(text)


def main() -> None:
    args = build_parser().parse_args()
    settings = resolve_settings(args)
    result = call_kb_search(args, settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("total", 0) == 0:
        print(
            "提示：无检索结果。可换措辞重试，或放宽 --score-threshold / 换 --search-mode all_hybrid。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
