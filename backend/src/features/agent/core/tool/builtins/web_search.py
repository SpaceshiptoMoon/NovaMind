"""
内置工具：网页搜索

提供 DuckDuckGo 网页搜索功能。
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class WebSearchTool(BaseTool):
    """网页搜索工具"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "使用 DuckDuckGo 搜索引擎搜索互联网信息"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": (
                        "Search the web using a search engine. Returns page titles, URLs, and snippets.\n\n"
                        "WHEN TO USE:\n"
                        "- User asks about current events, news, or recent information\n"
                        "- You need to verify a fact or find up-to-date data\n"
                        "- User explicitly asks you to search the internet\n\n"
                        "TIPS:\n"
                        "- Use specific, targeted queries for better results\n"
                        "- If the first search doesn't find what you need, try different keywords\n"
                        "- You can search multiple times with different queries for comprehensive coverage"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query text",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return (default 5)",
                                "default": 5,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        if tool_name == "web_search":
            return await self._search(arguments)
        return f"未知工具：{tool_name}"

    async def _search(self, args: Dict[str, Any]) -> str:
        """执行网页搜索"""
        try:
            from src.features.deep_research.services.duckduckgo_service import (
                DuckDuckGoSearchService,
            )

            query = args["query"]
            max_results = args.get("max_results", 5)

            service = DuckDuckGoSearchService()
            results = await service.search(query=query, max_results=max_results)

            if not results:
                return json.dumps(
                    {"message": "未找到相关结果", "query": query},
                    ensure_ascii=False,
                )

            formatted = []
            for r in results:
                formatted.append(
                    {
                        "title": r.title if hasattr(r, "title") else "",
                        "url": r.url if hasattr(r, "url") else "",
                        "snippet": r.content if hasattr(r, "content") else "",
                    }
                )

            return json.dumps(
                {"query": query, "total": len(formatted), "results": formatted},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.error("网页搜索失败", error=str(e))
            return json.dumps({"error": f"搜索失败：{str(e)}"}, ensure_ascii=False)

    def get_system_prompt_fragment(self) -> str:
        return (
            "## Web Search\n"
            "Use web_search when:\n"
            "- User asks about current events, news, or recent information\n"
            "- You need facts that may have changed since your training data\n"
            "- User explicitly asks you to search the internet\n"
            "- You need to verify a claim about current versions, prices, or status\n\n"
            "Do NOT search for things you already know with high confidence.\n\n"
            "Search strategy:\n"
            "- Craft specific, targeted queries for better results\n"
            "- If the first search returns poor results, refine keywords and retry\n"
            "- For complex questions, search multiple times with different queries\n"
            "- Cross-reference results when accuracy matters\n\n"
            "Always cite your sources when presenting search results to the user."
        )
