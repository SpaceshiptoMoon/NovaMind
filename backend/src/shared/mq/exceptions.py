"""arq 任务临时拥塞信号中立基类。

``shared/mq`` 不得依赖 ``features``，故宿主侧的具体拥塞异常（如
``LocalASRBusyError``）应继承本模块的 ``TransientBusyError``；arq worker 只捕获
中立基类，从 ``defer_seconds`` 属性读取延迟秒数，无需感知 ASR 语义。
"""


class TransientBusyError(Exception):
    """临时拥塞信号——worker 捕获后延迟重入队，释放 Worker 槽位。

    这不是错误，而是拥塞信号。子类可附加领域字段（如 ``document_id``），
    但 worker 只读 ``message`` 与 ``defer_seconds``。
    """

    def __init__(self, message: str = "", defer_seconds: int = 30):
        self.message = message
        self.defer_seconds = defer_seconds
        super().__init__(self.message)