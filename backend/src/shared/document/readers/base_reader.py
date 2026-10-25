"""文档读取器基类。"""
from abc import ABC, abstractmethod


class BaseReader(ABC):
    """文档读取器基类"""

    @abstractmethod
    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """从文件加载数据，返回结构化文档块列表。

        Args:
            file_path: 文档文件在磁盘上的路径。

        Returns:
            文档块列表，每块为 dict（含 text、source、page、doc_id、type 等键）；读取失败返回空列表。
        """
        pass

    @staticmethod
    def decode_text_file(file_path: str) -> str:
        """BOM 感知的文本解码：先探 BOM（UTF-8/UTF-16），再回落链。

        红队 P1-1：原实现直接按 utf-8→gbk→gb2312→latin-1→cp1252 逐个试——
        latin-1 对任意字节恒成功使链后半成为死代码；UTF-16 文件（Windows
        记事本「Unicode」/PowerShell Out-File 输出）被 latin-1 解成带 NUL
        的乱码全文静默入库。UTF-8 BOM 亦以 ﻿ 字符残留正文。

        顺序依据：BOM 显式声明最优先；GBK 对任意字节几乎恒成功，因此
        UTF-16 无 BOM 变体必须在 GBK 之前按 NUL 采样判定。
        """
        from pathlib import Path

        raw = Path(file_path).read_bytes()

        # 1. BOM 显式声明
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig", errors="replace")
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            return raw.decode("utf-16", errors="replace")

        # 2. UTF-8 严格解码（含合法 UTF-8 无 BOM）
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # 3. 中文回落链。已知边界：无 BOM 的 UTF-16LE 纯中文文本（NUL 密度低，
        #    无法与 GBK 可靠区分）会走 GBK 产出乱码——带 BOM 的 UTF-16（Windows
        #    生态绝大多数：记事本「Unicode」/PowerShell Out-File 均带 BOM）已被
        #    第 1 步覆盖；无 BOM 场景做启发式判定有 GBK 误判反噬风险，刻意不做。
        for encoding in ("gbk", "gb2312"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue

        # 5. 最终兜底：忽略错误硬读（不再经过 latin-1/cp1252——恒成功使
        #    之后的一切回落形同虚设）
        return raw.decode("utf-8", errors="replace")
