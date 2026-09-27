"""DeepDoc JSON 解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/json_parser.py
import json
from typing import Any

from novamind.engines.document.integrations.deepdoc.compat import find_codec


class RAGFlowJsonParser:
    """RAGFlow JSON 文档解析器。"""
    def __init__(self, max_chunk_size: int = 2000, min_chunk_size: int | None = None):
        """初始化分块大小上下限。"""
        self.max_chunk_size = max_chunk_size * 2
        self.min_chunk_size = min_chunk_size if min_chunk_size is not None else max(max_chunk_size - 200, 50)

    def __call__(self, binary: bytes):
        """解析 JSON / JSONL 字节流为分块文本列表。"""
        encoding = find_codec(binary)
        text = binary.decode(encoding, errors="ignore")
        if self.is_jsonl_format(text):
            return self._parse_jsonl(text)
        return self._parse_json(text)

    @staticmethod
    def _json_size(data: dict) -> int:
        """JSON 序列化后字符长度（分块大小度量）。"""
        return len(json.dumps(data, ensure_ascii=False))

    @staticmethod
    def _set_nested_dict(data: dict, path: list[str], value: Any) -> None:
        """按 key 路径在嵌套字典中写入值，中间层自动建字典。"""
        for key in path[:-1]:
            data = data.setdefault(key, {})
        data[path[-1]] = value

    def _list_to_dict_preprocessing(self, data: Any) -> Any:
        """递归把列表转成以索引为 key 的字典，便于按路径切分。"""
        if isinstance(data, dict):
            return {key: self._list_to_dict_preprocessing(value) for key, value in data.items()}
        if isinstance(data, list):
            return {str(index): self._list_to_dict_preprocessing(item) for index, item in enumerate(data)}
        return data

    def _json_split(self, data, current_path: list[str] | None, chunks: list[dict] | None) -> list[dict]:
        """深度优先遍历嵌套结构，按 max/min_chunk_size 组装分块。"""
        current_path = current_path or []
        chunks = chunks or [{}]
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = current_path + [key]
                chunk_size = self._json_size(chunks[-1])
                size = self._json_size({key: value})
                remaining = self.max_chunk_size - chunk_size
                if size < remaining:
                    self._set_nested_dict(chunks[-1], new_path, value)
                else:
                    if chunk_size >= self.min_chunk_size:
                        chunks.append({})
                    self._json_split(value, new_path, chunks)
        else:
            self._set_nested_dict(chunks[-1], current_path, data)
        return chunks

    def split_json(self, json_data, convert_lists: bool = False) -> list[dict]:
        """把 JSON 对象切成大小受限的字典分块。
        
        Args:
            json_data: 待切分的 JSON 对象（dict/嵌套结构）。
            convert_lists: 是否先把列表转为索引字典再切分。
        
        Returns:
            字典分块列表，每个分块保留原 JSON 的嵌套路径。
        """
        if convert_lists:
            preprocessed_data = self._list_to_dict_preprocessing(json_data)
            chunks = self._json_split(preprocessed_data, None, None)
        else:
            chunks = self._json_split(json_data, None, None)

        if chunks and not chunks[-1]:
            chunks.pop()
        return chunks

    def _parse_json(self, content: str) -> list[str]:
        """解析单个 JSON 文档为分块文本列表；解析失败返回空列表。"""
        sections = []
        try:
            json_data = json.loads(content)
            chunks = self.split_json(json_data, True)
            sections = [json.dumps(line, ensure_ascii=False) for line in chunks if line]
        except json.JSONDecodeError:
            pass
        return sections

    def _parse_jsonl(self, content: str) -> list[str]:
        """逐行解析 JSONL，每行独立切分；坏行跳过不报错。"""
        lines = content.strip().splitlines()
        all_chunks = []
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                chunks = self.split_json(data, convert_lists=True)
                all_chunks.extend(json.dumps(chunk, ensure_ascii=False) for chunk in chunks if chunk)
            except json.JSONDecodeError:
                continue
        return all_chunks

    def is_jsonl_format(self, text: str, sample_limit: int = 10, threshold: float = 0.8) -> bool:
        """判定文本是否为 JSONL 格式。
        
        Args:
            text: 待判定文本。
            sample_limit: 采样前 N 个非空行判定。
            threshold: 有效 JSON 行占比阈值。
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return False

        try:
            json.loads(text)
            return False
        except json.JSONDecodeError:
            pass

        sample_limit = min(len(lines), sample_limit)
        sample_lines = lines[:sample_limit]
        valid_lines = sum(1 for line in sample_lines if self._is_valid_json(line))
        if not valid_lines:
            return False
        return (valid_lines / len(sample_lines)) >= threshold

    @staticmethod
    def _is_valid_json(line: str) -> bool:
        """单行能否完整解析为 JSON。"""
        try:
            json.loads(line)
            return True
        except json.JSONDecodeError:
            return False
