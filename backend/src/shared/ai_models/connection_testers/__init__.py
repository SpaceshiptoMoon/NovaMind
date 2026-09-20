"""模型连通测试器（批次 2.2 从 user/model_config_service 下沉）。

此前 LLM/embedding/rerank/ASR 的连接测试实现内嵌在
``features/user/services/model_config_service.py``（约 230 行），
与用户配置业务耦合。下沉到 ``shared/ai_models/`` 后 service 只留门面分派，
测试器成为模型域的公共能力（audio_utils 的 env 直读也在批次 4.7 改读配置中心）。
"""
