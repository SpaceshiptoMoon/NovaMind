from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class DeepDocParseResult:
    full_text: str
    chunks: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_documents(self, source: str = "") -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        for index, chunk in enumerate(self.chunks):
            documents.append(
                {
                    "text": chunk,
                    "content": chunk,
                    "chunk_index": index,
                    "source": source,
                    "metadata": dict(self.metadata),
                }
            )
        return documents
