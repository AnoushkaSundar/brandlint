"""Anchored pass/fail examples per judgment rule.

These are versioned artifacts: they feed the prompt, so changing one must bump
`ANCHORS_VERSION`. A later block lets admins approve changes as proposals.
"""

from __future__ import annotations

ANCHORS_VERSION = "anchors-v1"

ANCHORS: dict[str, list[dict[str, str]]] = {
    "R-TONE-01": [
        {
            "verdict": "PASS",
            "text": "New hires get everything they need on day one.",
            "why": "Short sentence, everyday words.",
        },
        {
            "verdict": "VIOLATION",
            "text": (
                "Our synergistic enablement paradigm operationalises "
                "cross-functional onboarding verticals."
            ),
            "why": "Unexplained jargon a general reader would not follow.",
        },
    ],
    "R-TONE-02": [
        {
            "verdict": "PASS",
            "text": "A clear first week helps people settle in.",
            "why": "Calm and helpful.",
        },
        {
            "verdict": "VIOLATION",
            "text": "Act now or your best people will walk out the door!",
            "why": "Uses fear and false urgency to persuade.",
        },
    ],
    "R-TONE-03": [
        {
            "verdict": "PASS",
            "text": "I've been thinking about what makes a first week feel welcoming.",
            "why": "Warm, measured, conversational.",
        },
        {
            "verdict": "VIOLATION",
            "text": "STOP losing new hires! BOOK YOUR DEMO TODAY!",
            "why": "Shouting, capital-letter emphasis and a hard sell.",
        },
    ],
    "R-TONE-04": [
        {
            "verdict": "PASS",
            "text": "We're here when you need us, and you'll settle in quickly.",
            "why": "Uses contractions naturally.",
        },
        {
            "verdict": "VIOLATION",
            "text": "We are here when you need us, and you will settle in quickly.",
            "why": "Avoids contractions where they would sound natural.",
        },
    ],
}
