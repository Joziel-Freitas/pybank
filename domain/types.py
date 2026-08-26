"""Domain Enumerations and Semantic Types Module.

Defines the core business enumerations and classifiers required to label financial
events, transaction movements, and time-based adjustments within the PyBank domain.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

type VOValueTypes = str | Decimal | date


class FinancialType(StrEnum):
    """Base enumeration for all domain-level financial event classifiers.

    Acts as a polymorphic marker class for enumerations that represent
    immutable, historical financial events (such as transactions or accruals).
    Ensures that event labels persisted in the database or processed by entities
    belong to a strictly defined set of business categories.
    """


class TransactionType(FinancialType):
    """Value Object representing the semantic business event of a financial operation.

    Acts as the official ledger entry type, ensuring the core domain records
    the exact nature of the movement (e.g., distinguishing a standard withdrawal
    from an overdraft usage).

    Attributes:
        DEPOSIT: Represents funds added to the account.
        WITHDRAWAL: Represents funds removed using standard positive balance.
        CREDIT_WITHDRAWAL: Represents funds removed utilizing the account's credit limit.
    """

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    CREDIT_WITHDRAWAL = "CREDIT_WITHDRAWAL"


class AccrualType(FinancialType):
    """Value Object representing the semantic classification of a time-based financial adjustment.

    Categorizes automatic mathematical operations applied to an account based on
    the passage of time, distinguishing between positive remuneration and negative
    debt charges.

    Attributes:
        YIELD: Represents positive earnings applied to a positive balance (e.g., Savings interest).
        INTEREST: Represents negative charges applied to a utilized credit limit (e.g., Overdraft fees).
    """

    YIELD = "YIELD"
    INTEREST = "INTEREST"
