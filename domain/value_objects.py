"""Domain Value Objects Module.

Defines immutable Value Objects that encapsulate monetary calculations, projected outputs,
and atomic ledger event definitions within the core PyBank domain.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from domain.types import AccrualType, FinancialType


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """Value Object representing a discrete event bound for the accounting ledger.

    Designed to decompose complex account operations (such as a withdrawal
    that crosses into overdraft limits, or a deposit that triggers pending
    yield materialization) into immutable, atomic segments. This ensures
    accurate ledger tracking and precise auditing without exposing internal
    entity mechanics.

    Attributes:
        previous_balance (Decimal): The exact account balance immediately
            prior to the execution of this specific event segment.
        amount (Decimal): The specific monetary amount associated with this
            discrete segment of the operation. Negative values represent
            debits, while positive values represent credits.
        event_type (FinancialType): The semantic label categorizing the exact
            business nature of the event.
    """

    previous_balance: Decimal
    amount: Decimal
    event_type: FinancialType


@dataclass(frozen=True, slots=True)
class WithdrawalSimulation:
    """Value Object representing the projected outcome of a withdrawal evaluation.

    Utilized by domain aggregates and application use cases to safely evaluate
    the financial and operational impact of a withdrawal before committing to state
    mutation. It provides the necessary data to evaluate whether credit limits are required.

    Attributes:
        authorized (bool): Indicates if the operation is mathematically and operationally
            possible (e.g., account is active and the requested amount does not exceed
            the total available funds).
        use_credit (bool | None): True if the requested amount exceeds the standard positive
            balance, requiring the use of the account's credit limit. False if the limit
            exists but won't be used. None if the account type does not support credit.
        credit_required (Decimal | None): The exact monetary value that will be drawn from
            the credit limit if the transaction proceeds. Expected to be Decimal("0.00")
            if `use_credit` is False, or None if credit is unsupported.
    """

    authorized: bool
    use_credit: bool | None
    credit_required: Decimal | None


@dataclass(frozen=True, slots=True)
class AccountFinancial:
    """Value Object representing the absolute financial state of an Account.

    Acts as a highly cohesive, composable payload containing all calculated monetary
    metrics. By separating the historical ledger state ('ledger_balance') from the
    temporally accurate current state ('balance') and the total purchasing power
    ('available_balance'), it captures a precise and unambiguous financial snapshot
    at a specific timestamp ('issue_at').

    Attributes:
        ledger_balance (Decimal): The historical, unadjusted balance retrieved directly
            from the accounting records.
        accrual (Decimal): The specific monetary value of any pending time-based adjustment.
            Evaluates to Decimal("0.00") if no adjustment is pending.
        balance (Decimal): The true, real-time adjusted current balance, fully evaluated
            by the account's specific business rules.
        accrual_type (AccrualType | None): The semantic label of the adjustment
            (e.g., YIELD or INTEREST). Strictly None if the accrual is exactly zero.
        credit_limit (Decimal | None): The maximum credit limit, or None if not supported.
        available_credit (Decimal | None): The currently available credit amount, or None.
        available_balance (Decimal): The true total purchasing power, factoring in the
            adjusted balance and any available credit lines.
        issue_at (date): The exact temporal anchor validating the accuracy of this snapshot.
    """

    ledger_balance: Decimal
    accrual: Decimal
    balance: Decimal
    accrual_type: AccrualType | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    available_balance: Decimal
    issue_at: date
