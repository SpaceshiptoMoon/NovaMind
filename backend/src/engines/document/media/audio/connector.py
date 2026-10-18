"""ASR 连接器：本地/远程模型统一转写入口（协议路由 + 凭证解析 + 忙碌锁）。

音频文档与视频音轨共用此类——调用方只给模型名与音频字节，连接器负责：
1. 路由解析：faster-whisper 家族直判 local（不查凭证）；云端模型按名字精确
   匹配凭证（不串用其它配置），缺失抛 AsrCredentialsMissingError；
2. 协议分发：local → faster-whisper（子进程隔离）/ openai → Whisper API /
   dashscope → Paraformer（MinIO 中转）；
3. 本地忙碌锁：单进程转写串行化，忙碌抛 AsrBusyError（拥塞信号，非错误）。

失败语义（文件损坏永久性 / 环境瞬时性）归调用方按场景处理——音频文档致命、
视频音轨告警跳过，连接器不做场景策略。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AsrCredentialsMissingError(RuntimeError):
    """云端 ASR 模型凭证缺失、本地档位非法或协议不支持（配置错误，重试不可能成功）。"""


class AsrBusyError(RuntimeError):
    """本地 ASR 正在转写其它音频（拥塞信号，调用方应延后重试）。"""

    def __init__(self, defer_seconds: int = 30):
        self.defer_seconds = defer_seconds
        super().__init__("本地 ASR 忙碌，需延后重试")


@dataclass(frozen=True)
class AsrRoute:
    """一次 ASR 调用的完整路由（协议 + 模型 + 凭证）。"""

    protocol: str  # local / openai / dashscope
    model: str
    api_key: str | None = None
    base_url: str | None = None


class _CredentialsPort(Protocol):
    """凭证查询端口（duck-typing：ModelConfigService 或测试桩）。"""

    async def get_credentials_by_model(
        self, uploader_id: int, model_type: str, model: str
    ): ...


class _RouteDocument(Protocol):
    """路由解析所需的最小文档面（duck-typing：Document ORM 或测试桩）。"""

    id: int
    uploader_id: int


class AsrConnector:
    """ASR 连接器：按模型名自动路由本地/远程转写，后续 ASR 需求直接调用本类。

    两种使用形态：
    - 一次性（简单场景）：``await connector.transcribe(...)``——路由解析、
      拿锁、转写、释放全部在连接器内完成；
    - 两阶段（锁敏感场景，如视频音轨需先探锁再提取音轨）：调用方先
      ``resolve_route`` 并自行 ``acquire_local_slot``，再调
      ``transcribe_with_route(route, lock_held=True)``——锁的持有期由调用方
      控制（如覆盖 ffmpeg 提取段），释放仍归连接器 finally。
    """

    # wait_local_slot=True 时的轮询间隔（秒）。本地转写分钟级起，1s 轮询
    # 足够灵敏且不空转。
    _WAIT_POLL_INTERVAL_S = 1.0

    def __init__(self, credentials_port: _CredentialsPort | None = None):
        """
        Args:
            credentials_port: 模型配置端口（get_credentials_by_model）；
                None 时云端模型一律判凭证缺失（纯本地部署无需注入）。
        """
        self._credentials_port = credentials_port

    async def resolve_route(
        self, document: _RouteDocument, asr_model: str
    ) -> AsrRoute:
        """解析模型名到路由四元组。

        本地 faster-whisper 家族不查凭证；云端模型凭证按名字精确匹配，
        找不到即抛错（不取「该用户第一个 ASR 配置」串用——用户选了 A 模型
        可能被静默换成 B 模型/他家凭证，不可追踪）。

        Raises:
            AsrCredentialsMissingError: 本地档位非法，或云端凭证缺失。
        """
        from novamind.engines.document.media.audio import split_local_whisper_model_name

        try:
            if split_local_whisper_model_name(asr_model) is not None:
                return AsrRoute(protocol="local", model=asr_model)
        except ValueError as exc:
            raise AsrCredentialsMissingError(str(exc)) from exc

        if self._credentials_port is None:
            raise AsrCredentialsMissingError(
                f"未找到 ASR 模型「{asr_model}」的凭证：未注入模型配置端口，"
                f"云端模型不可用（asr_model 填 faster-whisper-<档位> 可走本地）"
            )
        creds = await self._credentials_port.get_credentials_by_model(
            document.uploader_id, "asr", asr_model
        )
        if not creds:
            raise AsrCredentialsMissingError(
                f"未找到 ASR 模型「{asr_model}」的凭证，请在模型管理中添加该模型的 "
                f"API 配置，或将知识库音频解析配置切回本地"
                f"（asr_model 填 faster-whisper-<档位>，留空 = 部署默认档）"
            )
        return AsrRoute(
            protocol=creds.protocol or "openai",
            model=creds.model or asr_model,
            api_key=creds.api_key,
            base_url=creds.base_url,
        )

    async def acquire_local_slot(self) -> bool:
        """非阻塞获取本地 ASR 忙碌锁（原子操作，无竞态窗口）。

        Returns:
            True 已获取（转写完成后须 release_local_slot 释放）；False 忙碌。
        """
        from novamind.engines.document.media.audio import acquire_asr_or_busy

        return await acquire_asr_or_busy()

    def release_local_slot(self) -> None:
        """释放本地 ASR 忙碌锁（幂等，未持锁时无操作）。"""
        from novamind.engines.document.media.audio import force_release_asr_slot

        force_release_asr_slot()

    async def transcribe(
        self,
        *,
        file_content: bytes,
        file_type: str,
        asr_model: str,
        document: _RouteDocument,
        language: str | None = None,
        engine_audio_config: Any = None,
        hotwords: list[str] | None = None,
        diarization_enabled: bool | None = None,
        speaker_count: int | None = None,
        minio_client: Any = None,
        wait_local_slot: bool = False,
        wait_timeout: float | None = None,
    ) -> tuple[list[dict[str, Any]], AsrRoute]:
        """统一转写入口：路由解析 + 协议分发 + 本地忙碌锁。

        Args:
            file_content: 音频二进制（视频音轨先 extract_audio_track 再传入）。
            file_type: 类型提示（真实格式按 Magic Bytes 检测）。
            asr_model: 模型名（faster-whisper-<档位> / whisper-1 / paraformer-v2…）。
            document: 文档（uploader_id 用于凭证查询，id 用于日志与 MinIO 桶）。
            language: 语言提示，None 自动检测。
            engine_audio_config: 引擎 AudioConfig（宿主从 YAML 构造；仅本地协议消费）。
            hotwords: 热词列表（仅本地协议生效，云端告警忽略）。
            diarization_enabled: 说话人分离（仅 DashScope 生效）。
            speaker_count: 说话人数量参考（仅 DashScope 生效）。
            minio_client: MinIO 客户端（仅 DashScope 中转需要；None 时经
                ClientFactory 惰性获取）。
            wait_local_slot: True 时本地忙碌在连接器内等待重试获取（视频旁白等
                可等待场景）；False（默认）忙碌即抛 AsrBusyError（音频文档
                场景由调用方转译为延后重入队）。
            wait_timeout: 等待锁的超时上限（秒）；None 不限时。超时抛
                AsrBusyError——防 wait 模式在锁泄漏时永久自旋。

        Returns:
            (segments, route)：segments 为统一段落字典列表；route 为实际生效
            路由（调用方记录日志/指纹用）。

        Raises:
            AsrCredentialsMissingError: 本地档位非法或云端凭证缺失。
            AsrBusyError: 本地忙碌且 wait_local_slot=False，或等待超时。
            AudioFileInvalidError: 文件损坏/过小/格式不支持（永久性）。
            RuntimeError: 模型缺失/云端调用失败（瞬时性，可重试）。
        """
        route = await self.resolve_route(document, asr_model)
        segments = await self.transcribe_with_route(
            route,
            file_content=file_content,
            file_type=file_type,
            document=document,
            language=language,
            engine_audio_config=engine_audio_config,
            hotwords=hotwords,
            diarization_enabled=diarization_enabled,
            speaker_count=speaker_count,
            minio_client=minio_client,
            wait_local_slot=wait_local_slot,
            wait_timeout=wait_timeout,
        )
        return segments, route

    async def transcribe_with_route(
        self,
        route: AsrRoute,
        *,
        file_content: bytes,
        file_type: str,
        document: _RouteDocument,
        language: str | None = None,
        engine_audio_config: Any = None,
        hotwords: list[str] | None = None,
        diarization_enabled: bool | None = None,
        speaker_count: int | None = None,
        minio_client: Any = None,
        lock_held: bool = False,
        wait_local_slot: bool = False,
        wait_timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """按已解析路由分发转写（两阶段入口，供调用方自管锁的持有期）。

        典型用法：视频音轨先 resolve_route + acquire_local_slot（锁内含
        ffmpeg 提取），成功后调用本方法并传 ``lock_held=True``——连接器只在
        finally 释放、不再重复拿锁；音频文档等一次性场景直接用 transcribe()。

        Args:
            route: resolve_route 返回的路由（协议/模型/凭证）。
            lock_held: True = 调用方已持本地锁（仅 local 协议有意义），连接器
                不再拿锁、仍在 finally 释放；False = 由本方法按
                wait_local_slot/wait_timeout 语义拿锁（云端协议忽略此参）。

        其余参数同 transcribe()。

        Raises:
            同 transcribe()。
        """
        if route.protocol != "local":
            return await self._transcribe_remote(
                file_content=file_content,
                file_type=file_type,
                route=route,
                document=document,
                language=language,
                hotwords=hotwords,
                diarization_enabled=diarization_enabled,
                speaker_count=speaker_count,
                minio_client=minio_client,
            )

        from novamind.engines.document.media.audio import (
            transcribe_audio_local,
        )

        if not lock_held:
            await self._acquire_local_slot_or_wait(
                wait_local_slot=wait_local_slot, wait_timeout=wait_timeout
            )
        try:
            if diarization_enabled:
                logger.warning(
                    "本地 ASR 暂不支持说话人分离（需 pyannote 额外模型），"
                    "忽略 diarization 配置, document_id=%s",
                    document.id,
                )
            return await transcribe_audio_local(
                file_content=file_content,
                file_type=file_type,
                language=language,
                audio_config=engine_audio_config,
                hotwords=hotwords,
            )
        finally:
            self.release_local_slot()

    async def _acquire_local_slot_or_wait(
        self, *, wait_local_slot: bool, wait_timeout: float | None
    ) -> None:
        """获取本地锁：非等待模式忙碌即抛；等待模式轮询直至拿到或超时。"""
        import asyncio

        acquired = await self.acquire_local_slot()
        if wait_local_slot:
            waited = 0.0
            while not acquired:
                if wait_timeout is not None and waited >= wait_timeout:
                    raise AsrBusyError(defer_seconds=int(wait_timeout))
                await asyncio.sleep(self._WAIT_POLL_INTERVAL_S)
                waited += self._WAIT_POLL_INTERVAL_S
                acquired = await self.acquire_local_slot()
            return
        if not acquired:
            raise AsrBusyError()

    async def _transcribe_remote(
        self,
        *,
        file_content: bytes,
        file_type: str,
        route: AsrRoute,
        document: _RouteDocument,
        language: str | None,
        hotwords: list[str] | None,
        diarization_enabled: bool | None,
        speaker_count: int | None,
        minio_client: Any,
    ) -> list[dict[str, Any]]:
        """云端协议分发：dashscope → Paraformer（MinIO 中转）/ openai → Whisper。

        Raises:
            AsrCredentialsMissingError: 凭证记录的协议不在 ASR 支持面
                （openai/dashscope）内——不静默当 openai 兜底，那会把
                anthropic/ollama 等配置以错误协议烧请求。
        """
        from novamind.engines.document.media.audio import (
            transcribe_audio_with_dashscope,
            transcribe_audio_with_timestamps,
        )

        if route.protocol not in ("openai", "dashscope"):
            raise AsrCredentialsMissingError(
                f"ASR 模型「{route.model}」配置的协议「{route.protocol}」不受支持："
                f"音频转写仅支持 openai / dashscope 协议，请在模型管理中修正该 "
                f"ASR 配置的协议，或改用本地 faster-whisper 档位"
            )
        if route.protocol == "dashscope":
            if hotwords:
                logger.warning(
                    "DashScope ASR 暂不支持自由热词（仅控制台预注册 phrase_id），"
                    "忽略 %d 个热词, document_id=%s",
                    len(hotwords), document.id,
                )
            if minio_client is None:
                from novamind.shared.storage.client_factory import ClientFactory

                minio_client = await ClientFactory.get_minio_client()
            storage_info = (
                document.get_storage_info() if hasattr(document, "get_storage_info") else {}
            )
            return await transcribe_audio_with_dashscope(
                file_content=file_content,
                file_type=file_type,
                model=route.model,
                api_key=route.api_key,
                base_url=route.base_url,
                minio_bucket=storage_info.get("minio_bucket"),
                language_hints=[language] if language else None,
                diarization_enabled=diarization_enabled,
                speaker_count=speaker_count,
                minio_client=minio_client,
            )
        if hotwords:
            logger.warning(
                "OpenAI 协议 ASR 暂不支持热词，忽略 %d 个热词, document_id=%s",
                len(hotwords), document.id,
            )
        return await transcribe_audio_with_timestamps(
            file_content=file_content,
            file_type=file_type,
            model=route.model,
            api_key=route.api_key,
            base_url=route.base_url,
            language=language,
        )
