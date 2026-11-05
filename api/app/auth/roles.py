from enum import StrEnum


# Mirrors Role in docs/contracts.md. Replace with the import from app.contracts
# once contracts/v1 lands.
class Role(StrEnum):
    CREATOR = "creator"
    REVIEWER = "reviewer"
    MANAGER = "manager"
    LEGAL = "legal"
    ADMIN = "admin"
