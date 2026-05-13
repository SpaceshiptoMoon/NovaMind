"""
Docker 沙箱核心实现

使用长驻容器 + docker exec 策略，避免每次执行创建容器的冷启动开销。
"""
import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import uuid4

from src.core.middleware.structured_logging import get_logger
from src.features.agent.sandbox.config import LANGUAGE_EXTENSIONS, SandboxConfig
from src.features.agent.api.exceptions import (
    SandboxExecutionError,
    SandboxNotAvailableError,
    SandboxTimeoutError,
    UnsupportedLanguageError,
)

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    """代码执行结果"""

    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    language: str
    timed_out: bool


class DockerSandbox:
    """
    Docker 沙箱管理器

    使用长驻容器 + docker exec 策略：
    - 启动时为每种语言预创建一个长驻容器
    - 执行代码时用 docker exec 在已有容器内运行，开销 < 100ms
    - 定期重建容器防止状态累积
    """

    def __init__(self, config: SandboxConfig):
        self.config = config
        self._client: Any = None
        self._containers: Dict[str, Any] = {}
        self._exec_counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    def _get_client(self) -> Any:
        """获取 Docker 客户端（延迟初始化）"""
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    def check_available(self) -> bool:
        """
        检查 Docker 是否可用

        Returns:
            True 如果 Docker 可用

        Raises:
            SandboxNotAvailableError: Docker 不可用
        """
        try:
            client = self._get_client()
            client.ping()
            return True
        except Exception as e:
            logger.warning("Docker 不可用", error=str(e))
            raise SandboxNotAvailableError()

    async def start(self) -> None:
        """
        启动沙箱：为每种语言预创建长驻容器

        在应用启动时调用
        """
        try:
            self.check_available()
        except SandboxNotAvailableError:
            logger.warning("Docker 不可用，代码执行沙箱未启用")
            return

        client = self._get_client()

        for language, image in self.config.images.items():
            try:
                container_name = f"{self.config.container_prefix}_{language}"

                # 清理同名旧容器（上次异常退出未清理的情况）
                try:
                    old = client.containers.get(container_name)
                    old.remove(force=True)
                    logger.debug("移除旧容器", container=container_name)
                except Exception as e:
                    logger.debug("清理旧容器失败（可忽略）", error=str(e))

                # 检查镜像是否存在
                try:
                    client.images.get(image)
                except Exception as e:
                    logger.debug("检查镜像存在失败（可忽略）", error=str(e))
                    logger.warning(
                        "Docker 镜像不存在，请手动拉取",
                        image=image,
                        hint=f"docker pull {image}",
                    )
                    continue

                # 创建长驻容器
                container = client.containers.run(
                    image=image,
                    command="sleep infinity",
                    name=container_name,
                    detach=True,
                    network_disabled=self.config.network_disabled,
                    mem_limit=f"{self.config.max_memory_mb}m",
                    labels={"managed_by": "agent_sandbox"},
                )

                self._containers[language] = container
                self._exec_counts[language] = 0

                logger.info(
                    "沙箱容器已启动",
                    language=language,
                    image=image,
                    container_id=container.id[:12],
                )

            except Exception as e:
                logger.error(
                    "启动沙箱容器失败",
                    language=language,
                    image=image,
                    error=str(e),
                )

        if self._containers:
            self._started = True
            logger.info(
                "代码执行沙箱已启用",
                languages=list(self._containers.keys()),
            )
        else:
            logger.warning("没有可用的沙箱容器，代码执行功能不可用")

    async def execute(
        self,
        language: str,
        code: str,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        执行代码

        Args:
            language: 编程语言
            code: 要执行的代码
            timeout: 执行超时（秒），默认使用配置值

        Returns:
            ExecutionResult

        Raises:
            UnsupportedLanguageError: 不支持的语言
            SandboxNotAvailableError: 沙箱不可用
            SandboxTimeoutError: 执行超时
            SandboxExecutionError: 执行异常
        """
        # 语言检查
        if language not in self.config.images:
            raise UnsupportedLanguageError(
                language, self.config.supported_languages
            )

        # 容器检查与重建（整体加锁避免竞态）
        if language not in self._containers:
            raise SandboxNotAvailableError()

        async with self._lock:
            container = self._containers.get(language)
            if container is None:
                raise SandboxNotAvailableError()
            try:
                container.reload()
                if container.status != "running":
                    logger.warning("容器已停止，尝试重建", language=language)
                    await self._rebuild_container(language)
            except Exception as e:
                logger.error("容器状态检查失败，尝试重建", language=language, error=str(e))
                await self._rebuild_container(language)
            container = self._containers[language]

        # 超时参数
        effective_timeout = min(
            timeout or self.config.default_timeout,
            self.config.max_timeout,
        )

        # 生成临时文件名
        ext = LANGUAGE_EXTENSIONS.get(language, "txt")
        tmp_file = f"/tmp/sandbox_{uuid4().hex[:8]}.{ext}"

        start_time = time.monotonic()
        timed_out = False

        try:
            # 1. 将代码写入容器临时文件（base64 编码，防止 shell 注入）
            encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
            write_cmd = f"echo '{encoded}' | base64 -d > {tmp_file}"
            write_result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: container.exec_run(cmd=["sh", "-c", write_cmd]),
                ),
                timeout=10,
            )
            if write_result.exit_code != 0:
                raise SandboxExecutionError(
                    f"写入代码文件失败: {write_result.output.decode('utf-8', errors='replace')}"
                )

            # 2. 执行代码
            exec_commands = {
                "python": ["python3", tmp_file],
                "javascript": ["node", tmp_file],
                "shell": ["bash", tmp_file],
            }

            try:
                exec_result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: container.exec_run(
                            cmd=exec_commands[language],
                            workdir="/tmp",
                            demux=True,
                        ),
                    ),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                raise SandboxTimeoutError(effective_timeout, language)

            # 3. 解析输出
            exit_code = exec_result.exit_code
            stdout_bytes, stderr_bytes = exec_result.output or (b"", b"")

            # 处理 None
            stdout_bytes = stdout_bytes or b""
            stderr_bytes = stderr_bytes or b""

            # 输出截断
            max_bytes = self.config.max_output_bytes
            truncation_suffix = b"\n... (output truncated)"
            if len(stdout_bytes) > max_bytes:
                stdout_bytes = stdout_bytes[:max_bytes] + truncation_suffix
            if len(stderr_bytes) > max_bytes:
                stderr_bytes = stderr_bytes[:max_bytes] + truncation_suffix

            execution_time_ms = int((time.monotonic() - start_time) * 1000)

            result = ExecutionResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=exit_code,
                execution_time_ms=execution_time_ms,
                language=language,
                timed_out=timed_out,
            )

            logger.debug(
                "代码执行完成",
                language=language,
                exit_code=exit_code,
                execution_time_ms=execution_time_ms,
            )

            return result

        except SandboxTimeoutError:
            raise
        except SandboxExecutionError:
            raise
        except Exception as e:
            raise SandboxExecutionError(f"代码执行异常: {str(e)}")

        finally:
            # 4. 清理临时文件（无论成功失败都清理）
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: container.exec_run(cmd=["rm", "-f", tmp_file]),
                    ),
                    timeout=5,
                )
            except Exception as e:
                logger.warning("清理临时文件失败", file=tmp_file, error=str(e))

            # 5. 计数 + 重建检查（递增和阈值判断都在锁保护范围内）
            async with self._lock:
                self._exec_counts[language] = self._exec_counts.get(language, 0) + 1
                if self._exec_counts[language] >= self.config.rebuild_interval:
                    await self._rebuild_container(language)

    async def _rebuild_container(self, language: str) -> None:
        """
        重建指定语言的容器

        停止并移除旧容器，创建新容器
        """
        logger.info("重建沙箱容器", language=language)

        # 停止并移除旧容器
        if language in self._containers:
            try:
                old = self._containers[language]
                old.remove(force=True)
            except Exception as e:
                logger.warning("移除旧容器失败", language=language, error=str(e))

        # 从内部状态移除
        self._containers.pop(language, None)
        self._exec_counts.pop(language, None)

        # 创建新容器
        client = self._get_client()
        image = self.config.images[language]
        container_name = f"{self.config.container_prefix}_{language}"

        try:
            container = client.containers.run(
                image=image,
                command="sleep infinity",
                name=container_name,
                detach=True,
                network_disabled=self.config.network_disabled,
                mem_limit=f"{self.config.max_memory_mb}m",
                labels={"managed_by": "agent_sandbox"},
            )

            self._containers[language] = container
            self._exec_counts[language] = 0

            logger.info(
                "沙箱容器已重建",
                language=language,
                container_id=container.id[:12],
            )
        except Exception as e:
            logger.error(
                "重建沙箱容器失败",
                language=language,
                error=str(e),
            )
            raise SandboxExecutionError(f"重建沙箱容器失败: {str(e)}")

    async def cleanup(self) -> None:
        """
        清理所有容器

        在应用关闭时调用
        """
        if not self._containers:
            return

        logger.info("开始清理沙箱容器", count=len(self._containers))

        for language, container in list(self._containers.items()):
            try:
                container.remove(force=True)
                logger.debug("容器已清理", language=language)
            except Exception as e:
                logger.warning("清理容器失败", language=language, error=str(e))

        self._containers.clear()
        self._exec_counts.clear()
        self._started = False

        logger.info("沙箱容器清理完成")

    def get_status(self) -> Dict[str, Any]:
        """获取沙箱状态信息"""
        status = {
            "started": self._started,
            "containers": {},
        }
        for language, container in self._containers.items():
            try:
                container.reload()
                status["containers"][language] = {
                    "id": container.id[:12],
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "unknown",
                    "exec_count": self._exec_counts.get(language, 0),
                }
            except Exception as e:
                logger.warning("获取容器状态失败", error=str(e))
                status["containers"][language] = {"status": "error"}
        return status
