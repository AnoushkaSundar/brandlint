from mocks import gateway as mock_gateway

from app.clients.flags import use_mock


def llm_call(
    purpose: str, data_class: str, rule_ids: list[str], payload: dict
) -> dict:
    """The only way product code reaches a model."""
    if use_mock("GATEWAY"):
        return mock_gateway.llm_call(purpose, data_class, rule_ids, payload)

    from app.gateway import llm

    return llm.call(purpose, data_class, rule_ids, payload)
