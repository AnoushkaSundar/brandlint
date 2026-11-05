"""Stands in for /gateway and llm.call until the real AI gateway lands."""

from fastapi import APIRouter

from mocks import data

router = APIRouter(prefix="/gateway", tags=["mock gateway"])

CODENAME = "Bluewren"
CODENAME_TOKEN = "[PRODUCT_1]"


@router.get("/reviews/{review_id}/disclosure")
def disclosure(review_id: str) -> dict:
    return {
        "models": ["claude-haiku-5-5", "gpt-6-luna"],
        "masked": {"PRODUCT": 1},
        "routes": ["cloud"],
    }


@router.get("/reviews/{review_id}/masking-preview")
def masking_preview(review_id: str) -> dict:
    original = data.chunks_for_piece("agency-blog")["blog-p6"]
    return {"original": original, "sent": original.replace(CODENAME, CODENAME_TOKEN)}


def _verdicts(rule_ids: list[str]) -> dict:
    return {
        "verdicts": [
            {
                "rule_id": rule_id,
                "verdict": "PASS",
                "span": None,
                "confidence": 0.9,
                "explanation": "Mock verdict.",
            }
            for rule_id in rule_ids
        ]
    }


def _draft_rules() -> dict:
    fields = ("type", "text", "clause_ref", "severity", "channel_scope")
    return {
        "rules": [{field: rule[field] for field in fields} for rule in data.rules()],
        "conflicts": [{"clause_refs": ["§2.4", "§3.4"]}],
    }


def llm_call(
    purpose: str, data_class: str, rule_ids: list[str], payload: dict
) -> dict:
    """Same signature as llm.call in app.gateway. Unknown purposes fail loudly."""
    if purpose == "ingest":
        return _draft_rules()
    if purpose in ("visual", "classify"):
        return _verdicts(rule_ids)
    raise ValueError(f"The mock llm.call has no response for purpose {purpose!r}")
