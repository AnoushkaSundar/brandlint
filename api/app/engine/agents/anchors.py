"""Anchored pass/fail examples per judgment rule.

These are versioned artifacts: they feed the prompt, so changing one must bump
`ANCHORS_VERSION`. A later block lets admins approve changes as proposals.
"""

from __future__ import annotations

ANCHORS_VERSION = "anchors-v3"

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
            "verdict": "PASS",
            "text": "Companies that switch to Tarnhollow save time every month.",
            "why": "Talks about customers in general, so no competitor is named.",
        },
        {
            "verdict": "VIOLATION",
            "text": "We beat Northwind HR on every measure that matters.",
            "why": "Compares Tarnhollow with a named competitor.",
        },
    ],
}

# Voting. Each variant judges the same rule from another angle, with its own examples.
# Part of the cache key, so bump VOTE_VERSION when any of this changes.
VOTE_VERSION = "vote-v1"
VARIANTS = (1, 2)
RUBRICS: dict[int, str] = {
    1: "Judge the wording: flag it only if the words themselves break the rule.",
    2: "Judge the effect: flag it only if an ordinary reader would take away what the "
    "rule forbids.",
}
VOTE_ANCHORS: dict[str, dict[int, list[dict[str, str]]]] = {
    "R-CLAIM-03": {
        1: [
            {
                "verdict": "PASS",
                "text": "Our checklist can help new hires find their feet.",
                "why": "'Can help' offers a possibility, not a promise.",
            },
            {
                "verdict": "VIOLATION",
                "text": "Every customer always sees results in week one.",
                "why": "'Every' and 'always' make it an absolute claim.",
            },
        ],
        2: [
            {
                "verdict": "PASS",
                "text": "Teams told us the first week felt calmer.",
                "why": "Reports what people said, and promises nothing to the reader.",
            },
            {
                "verdict": "VIOLATION",
                "text": "Sign up and your retention problems are over for good.",
                "why": "A reader would take this as a promised outcome.",
            },
        ],
    },
    "R-CLAIM-04": {
        1: [
            {
                "verdict": "PASS",
                "text": "Spreadsheets make onboarding hard to track.",
                "why": "A spreadsheet is a method, not a named competitor.",
            },
            {
                "verdict": "VIOLATION",
                "text": "Tarnhollow is faster than Fernbrook People.",
                "why": "A direct comparison with a company named in the text.",
            },
        ],
        2: [
            {
                "verdict": "PASS",
                "text": "We built Tarnhollow Landing for growing teams.",
                "why": "Says who it's for, and compares it with nobody.",
            },
            {
                "verdict": "VIOLATION",
                "text": "Tired of Harbourline HR? Teams are moving to Tarnhollow.",
                "why": "A reader would see this as a comparison with a named rival.",
            },
        ],
    },
}
