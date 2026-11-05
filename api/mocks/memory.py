"""Stands in for /memory until the real brand memory lands."""

from fastapi import APIRouter

router = APIRouter(prefix="/memory", tags=["mock memory"])

AFFECTED_CONTENT = [
    {
        "content_id": "cnt-demo-agency-blog",
        "state": "resolving",
        "claim_text": "cut onboarding time ... by 80%",
    },
    {
        "content_id": "cnt-demo-case-study",
        "state": "published",
        "claim_text": "Customers cut onboarding time by 38% on average.",
    },
]

PRECEDENTS_BY_FINDING = {
    "fnd-agency-blog-03": [
        {
            "decision_id": "dec-demo-1",
            "rule_id": "R-TERM-03",
            "rule_version": 1,
            "channel": "blog",
            "reason": "Used in a direct quote from a customer.",
            "reviewer": "Lena Fischer",
            "date": "2026-10-12",
        }
    ],
    "fnd-agency-blog-07": [
        {
            "decision_id": "dec-demo-2",
            "rule_id": "R-TONE-02",
            "rule_version": 1,
            "channel": "blog",
            "reason": "Describes a real risk, and doesn't pressure the reader.",
            "reviewer": "Lena Fischer",
            "date": "2026-09-30",
        },
        {
            "decision_id": "dec-demo-3",
            "rule_id": "R-TONE-02",
            "rule_version": 1,
            "channel": "blog",
            "reason": "Statement of fact, backed by the customer study.",
            "reviewer": "Marcus Bell",
            "date": "2026-08-21",
        },
    ],
}


@router.get("/impact")
def impact(fact_id: str) -> list[dict]:
    return AFFECTED_CONTENT


@router.get("/precedents")
def precedents(finding_id: str) -> list[dict]:
    return PRECEDENTS_BY_FINDING.get(finding_id, [])


@router.get("/graph")
def graph(root: str) -> dict:
    return {
        "nodes": [
            {"id": root, "type": "Fact", "label": root},
            {"id": "claim-1", "type": "Claim", "label": "Cut onboarding time"},
            {"id": "cnt-demo-agency-blog", "type": "Content", "label": "Agency blog"},
            {"id": "cnt-demo-case-study", "type": "Content", "label": "Case study"},
        ],
        "edges": [
            {"source": "claim-1", "target": root, "type": "CITES"},
            {"source": "cnt-demo-agency-blog", "target": "claim-1", "type": "CONTAINS"},
            {"source": "cnt-demo-case-study", "target": "claim-1", "type": "CONTAINS"},
        ],
    }
