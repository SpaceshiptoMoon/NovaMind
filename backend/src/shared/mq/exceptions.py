"""
arq 任务临时拥塞信号 TransientBusyError，worker 捕获后按 defer_seconds 延迟重入队。
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