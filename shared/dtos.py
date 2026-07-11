"""
Shared Data Transfer Objects (DTOs) Module.

This module defines the immutable payloads that act as the lingua franca
across all architectural boundaries of the PyBank system.

It orchestrates a robust, type-safe data flow in multiple directions:
- Inbound: From the Presentation/Controller layers to the Domain (e.g., input forms).
- Outbound: From the Domain to the Presentation layer (e.g., financial snapshots).
- Persistence: Transporting state changes to the Repository (e.g., Ledger Events)
  and hydrating the Domain from the database via Composition (e.g., Russian Doll Projections).

By strictly relying on primitive types and standard library objects, these DTOs
prevent Domain Entity leakage, guarantee immutability in transit, and eliminate
circular dependencies between the system's core modules.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from shared.types import AccrualType, FinancialType


@dataclass(frozen=True, slots=True)
class NewAccountHolderDTO:
    """
    Data Transfer Object containing the validated data required to register a new account holder.

    Acts as a secure, immutable payload traveling from the OnboardingController
    to the Bank aggregate. It relies strictly on primitive types to ensure the
    Presentation layer does not need to import or construct Domain Entities.

    Attributes:
        name (str): The validated full name of the account holder.
        cpf (str): The validated 11-digit CPF string.
        birth_date (date): The validated birth date of the account holder.
    """

    name: str
    cpf: str
    birth_date: date


@dataclass(frozen=True, slots=True)
class NewAccountDTO:
    """
    Data Transfer Object containing the validated data required to open a new Account.

    Transports the user's choices and initial setup information. It uses an integer
    mapping (`account_type`) to indicate the specific account model (e.g., Checking
    vs. Savings) so the external layers remain completely decoupled from the specific
    Domain Entity implementations.

    Attributes:
        account_type (int): An integer flag mapping to the account type (e.g., 1 or 2).
        branch_code (str): The validated 4-digit branch code.
        account_num (str): The validated 8-digit account number.
    """

    account_type: int
    branch_code: str
    account_num: str


@dataclass(frozen=True, slots=True)
class DepositTargetDTO:
    """
    A read-only, sanitized snapshot of an account intended exclusively
    for public deposit confirmation screens.

    Contains masked sensitive information (like CPF) to prevent data leaks
    during unauthenticated queries, adhering to Zero Trust principles.
    """

    holder_name: str
    holder_cpf: str
    branch_code: str
    account_num: str
    account_type: str


@dataclass(frozen=True, slots=True)
class LedgerEventDTO:
    """
    Data Transfer Object representing a discrete event bound for the ledger.

    Designed to decompose complex account operations (such as a withdrawal
    that crosses into overdraft limits, or a deposit that triggers pending
    yield materialization) into immutable, atomic segments. This ensures
    accurate ledger tracking, precise auditing, and correct statement
    generation for the end user without exposing internal domain logic
    to the outer layers.

    Attributes:
        previous_balance (Decimal): The exact account balance immediately
            prior to the execution of this specific event segment, ensuring
            chronological consistency in the database ledger.
        amount (Decimal): The specific monetary amount associated with this
            discrete segment of the operation. Negative values represent
            debits (e.g., withdrawals, interest charges), while positive
            values represent credits (e.g., deposits, yields).
        event_type (FinancialType): The semantic label (e.g., WITHDRAWAL,
            DEPOSIT, YIELD, INTEREST) categorizing the exact business nature
            of the event.
    """

    previous_balance: Decimal
    amount: Decimal
    event_type: FinancialType


@dataclass(frozen=True, slots=True)
class WithdrawalSimulationDTO:
    """
    Data Transfer Object representing the projected outcome of a withdrawal.

    This DTO is utilized by the application layer (Controllers) to safely evaluate
    the financial and operational impact of a withdrawal before committing to the
    state mutation. It provides the necessary data to prompt the user for explicit
    consent when credit limits are involved.

    Attributes:
        authorized (bool): Indicates if the operation is mathematically and operationally
            possible (e.g., account is active and the requested amount does not exceed
            the total available funds).
        use_credit (bool | None): True if the requested amount exceeds the standard positive
            balance, requiring the use of the account's credit limit. False if the limit
            exists but won't be used. None if the account type does not support credit.
        credit_required (Decimal | None): The exact monetary value that will be drawn from
            the credit limit if the transaction proceeds. Expected to be Decimal("0.00")
            if `use_credit` is False. Expected to be None if the account type does not
            support credit (`use_credit` is None).
    """

    authorized: bool
    use_credit: bool | None
    credit_required: Decimal | None


@dataclass(frozen=True, slots=True)
class AccountFinancialDTO:
    """
    Data Transfer Object representing the absolute financial truth of an Account.

    Acts as a highly cohesive, composable payload containing all calculated monetary
    metrics. By separating the historical ledger state ('ledger_balance') from the
    temporally accurate current state ('balance') and the total purchasing power
    ('available_balance'), it ensures the Presentation layer renders precise and
    unambiguous information to the user at the specific timestamp ('issue_at').

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


@dataclass(frozen=True, slots=True)
class AccountSummaryDTO:
    """
    A comprehensive, multi-stage read-only snapshot of an account's state.

    Functions as a flexible facade for the Presentation layer. In the 'Lobby' phase,
    it contains only basic routing and identity data to render menus safely.
    Upon strict Vault authorization, it acts as an aggregate root, composing purely
    financial and accrual data DTOs into a single transport object without leaking
    the core domain entities.

    Attributes:
        holder_name (str): The full name of the account holder.
        branch_code (str): The branch code where the account is registered.
        account_num (str): The unique account identifier.
        account_type (str): The class name representing the account type (e.g., 'CheckingAccount').
        is_frozen (bool): Flag indicating if the account is active or frozen.
        financial_info (AccountFinancialDTO | None): The account's core financial metrics.
            Hydrated only after explicit Vault authorization; otherwise None.
        accrual_info (AccrualEventDTO | None): Pending time-based financial adjustments
            (yields or interests) ready to be applied or displayed.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    financial_info: AccountFinancialDTO | None


@dataclass(frozen=True, slots=True)
class StatementDTO:
    """
    Data Transfer Object representing a mathematically consistent account statement.

    Acts as an immutable payload combining a read-only representation of the account's
    current state with its chronological ledger event history.

    Attributes:
        account_info (AccountSummaryDTO): The account's full summary, including routing
            details and mathematically precise financial state at the exact moment
            of the statement generation.
        financial_events (tuple[dict[str, Any], ...]): A chronological sequence of
            ledger events (e.g., standard transactions, overdraft usage, or time-based
            accruals) occurring on or after a requested start date.
    """

    account_info: AccountSummaryDTO
    financial_events: tuple[dict[str, Any], ...]
