"""What each data class may do. A table in code, versioned, and never changed by a model.

Each row is data class x provider x purpose. The most specific row wins, and
anything without a row is blocked.

- allow: goes out. The deny-list still applies, because a draft labelled public
  can still name a codename.
- mask: goes out with personal data and protected values replaced by tokens.
- local: stays on this machine, on the local model.
- block: never goes anywhere.
"""

from __future__ import annotations

import os
from enum import StrEnum

from app.contracts import DataClass

# Part of the verdict cache key. Bump it when this table or masking changes.
POLICY_VERSION = "policy-2"

PINNED_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")
LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "local-small")

ANY = "*"
CLOUD = "cloud"
LOCAL = "local"


class Action(StrEnum):
    allow = "allow"
    mask = "mask"
    local = "local"
    block = "block"


TABLE: dict[tuple[DataClass, str, str], Action] = {
    (DataClass.public, CLOUD, ANY): Action.allow,
    (DataClass.internal, CLOUD, ANY): Action.mask,
    (DataClass.confidential, CLOUD, ANY): Action.mask,
    (DataClass.restricted, CLOUD, ANY): Action.block,
    (DataClass.restricted, LOCAL, ANY): Action.local,
}


def decide(data_class: DataClass, purpose: str, provider: str = CLOUD) -> Action:
    for key in ((data_class, provider, purpose), (data_class, provider, ANY)):
        if key in TABLE:
            return TABLE[key]
    return Action.block


def stays_local(data_class: DataClass, purpose: str = ANY) -> bool:
    return decide(data_class, purpose, LOCAL) == Action.local


def model_for(data_class: DataClass | str) -> str:
    """The model a review of this data class uses. Part of the cache key, so an
    identical restricted draft never reuses a verdict from the cloud model."""
    return LOCAL_MODEL if stays_local(DataClass(data_class)) else PINNED_MODEL


def route_label(model: str) -> str:
    return LOCAL if model == LOCAL_MODEL else CLOUD
