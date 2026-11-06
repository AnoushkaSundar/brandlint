"""Anchored pass/fail examples per judgment rule.

These are versioned artifacts: they feed the prompt, so changing one must bump
`ANCHORS_VERSION`. A later block lets admins approve changes as proposals.
"""

from __future__ import annotations

ANCHORS_VERSION = "anchors-v2"

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
    "R-CLAIM-03": [
        {
            "verdict": "PASS",
            "text": "A good start shapes how people feel about a new job.",
            "why": "A general observation that promises no result from the product.",
        },
        {
            "verdict": "PASS",
            "text": "Many teams find their first week easier with a clear plan.",
            "why": "Describes a likely benefit without a guarantee.",
        },
        {
            "verdict": "VIOLATION",
            "text": "You're guaranteed to halve your staff turnover within a month.",
            "why": "Promises a specific outcome as a certainty.",
        },
    ],
    "R-CLAIM-04": [
        {
            "verdict": "PASS",
            "text": "Many HR tools leave new hires waiting for logins.",
            "why": "Names no competitor.",
        },
        {
            "verdict": "VIOLATION",
            "text": "We beat Northwind HR on every measure that matters.",
            "why": "Compares Tarnhollow with a named competitor.",
        },
    ],
}
