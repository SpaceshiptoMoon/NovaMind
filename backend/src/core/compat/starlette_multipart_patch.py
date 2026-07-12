"""
Compatibility patch for corrupted Starlette multipart parser helper.

Some local environments may contain a broken implementation of
`starlette.formparsers._user_safe_decode`, which incorrectly calls
`novamind.decode(...)` instead of decoding the input bytes.

That causes every multipart/form-data request to fail with:
`There was an error parsing the body`.
"""

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


def apply_starlette_multipart_patch() -> None:
    try:
        import starlette.formparsers as formparsers
    except Exception as exc:
        logger.warning(
            "无法导入 starlette.formparsers，跳过 multipart 修复补丁",
            error=str(exc),
        )
        return

    def _safe_decode(src: bytes | bytearray, codec: str) -> str:
        try:
            return src.decode(codec)
        except (UnicodeDecodeError, LookupError):
            return src.decode("latin-1")

    formparsers._user_safe_decode = _safe_decode
    logger.info("已应用 Starlette multipart 解析修复补丁")
