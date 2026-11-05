"""AI gateway. Every model call goes through `llm.call`:

    from app.gateway import llm
    llm.call(purpose="classify", data_class="public", rule_ids=["R1"], payload=...)
"""

from __future__ import annotations

from app.gateway import llm

__all__ = ["llm"]
