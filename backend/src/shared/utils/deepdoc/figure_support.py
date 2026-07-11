from src.shared.integrations.deepdoc.figure_support import (
    LLMBundle,
    LLMType,
    append_context2table_image4pdf,
    ensure_pil_image,
    get_tenant_default_model_by_type,
    is_image_like,
    open_image_for_processing,
    picture_vision_llm_chunk,
    timeout,
    vision_llm_figure_describe_prompt,
    vision_llm_figure_describe_prompt_with_context,
)
