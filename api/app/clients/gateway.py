from mocks import gateway as mock_gateway
from sqlalchemy.orm import Session

from app.clients.flags import use_mock


def llm_call(
    purpose: str,
    data_class: str,
    rule_ids: list[str],
    payload: dict,
    *,
    session: Session,
    review_id: str | None = None,
) -> dict:
    """The only way product code reaches a model.

    The session is required because the gateway only logs a call when it has one.
    """
    if use_mock("GATEWAY"):
        return mock_gateway.llm_call(purpose, data_class, rule_ids, payload)

    from app.gateway import llm

    return llm.call(
        purpose,
        data_class,
        rule_ids,
        payload,
        session=session,
        review_id=review_id,
    )
