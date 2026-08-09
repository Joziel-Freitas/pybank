"""Application Types and Enumerations Module.

This module defines high-level enumerations and classifiers specific to the
application layer workflows. It serves as an explicit, type-safe contract
between the presentation controllers and the application use-case DTOs.
"""

from enum import StrEnum, auto


class NewAccountType(StrEnum):
    """Enumeration representing the supported account types for onboarding workflows.

    Acts as an explicit classifier within `NewAccountDTO` payloads to select
    the target domain entity variant (`CheckingAccount` vs `SavingsAccount`)
    without relying on magic integers or loose strings.

    Attributes:
        CHECKING_ACCOUNT: Identifies a standard checking account.
        SAVINGS_ACCOUNT: Identifies an interest-bearing savings account.
    """

    CHECKING_ACCOUNT = auto()
    SAVINGS_ACCOUNT = auto()
