"""
测评引擎宿主适配器

实现引擎库端口（PromptProvider 等），桥接宿主侧 `PromptManager`。批次 5 接缝：
evaluator 不再直接 import `shared.prompts.templates.PromptManager`，改经构造器
接收 `PromptProvider` 端口；本适配器在装配时把 `PromptManager` 包成端口实例注入。

按目标架构「各 features/*/adapters/ 实现引擎库端口」，evaluation 拥有自己的宿主
适配器（与 agent/adapters 同名实现各自独立，因 batch 6 后两者分属不同引擎包）。
"""