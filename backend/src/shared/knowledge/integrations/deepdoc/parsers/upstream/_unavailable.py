from __future__ import annotations


class UpstreamParserStub:
    """Placeholder for upstream parser modules that are vendored structurally but not wired yet."""

    parser_name = "unknown"

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        raise RuntimeError(
            f"DeepDoc upstream parser '{self.parser_name}' is mirrored as a stub only. "
            "Its heavy dependency chain has not been wired into this standalone module yet."
        )
