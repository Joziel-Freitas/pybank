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
from typing import Any

from domain.value_objects import AccountFinancial


@dataclass(frozen=True, slots=True)
class NewAccountDTO:
    """Data Transfer Object containing the validated data required to open a new Account.

    Transports user choices and onboarding information into a unified payload.
    Supports both new account holder creation and attaching a new account to an
    existing account holder.

    Attributes:
        account_type (int): Integer flag mapping to the account type (e.g., 1 for Checking, 2 for Savings).
        branch_code (str): The validated 4-digit branch code.
        account_num (str): The validated 8-digit account number.
        holder_cpf (str): The validated 11-digit CPF string of the account holder.
        holder_name (str | None): Full name of the account holder. Required for new holders,
            None if attaching to an existing holder.
        holder_birth_date (date | None): Birth date of the account holder. Required for new holders,
            None if attaching to an existing holder.
    """

    account_type: int
    branch_code: str
    account_num: str
    holder_cpf: str
    holder_name: str | None = None
    holder_birth_date: date | None = None


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
class AccountSummaryDTO:
    """A comprehensive, multi-stage read-only snapshot of an account's state.

    Functions as a flexible, read-only projection for the Presentation layer.
    It operates in two distinct execution phases:
    1. Lobby Phase: Contains only basic routing and non-sensitive identity
       data to safely render general menus.
    2. Vault Phase: Composes rich, real-time financial and temporal metrics
       (AccountFinancial) after strict cryptographic authorization.

    Attributes:
        holder_name (str): The full name of the account holder.
        branch_code (str): The branch code where the account is registered.
        account_num (str): The unique account identifier.
        account_type (str): The class name representing the account type (e.g., 'CheckingAccount').
        is_frozen (bool): Flag indicating if the account is active or frozen.
        financial_info (AccountFinancial | None): The account's core financial metrics.
            Hydrated only after explicit Vault authorization; otherwise None.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    financial_info: AccountFinancial | None

    def unwrap_financial(self) -> AccountFinancial:
        """Safely extracts the nested financial projection.

        Enforces strict temporal access control by raising an exception if
        the presentation layer attempts to read financial metrics that have
        not been cryptographically unlocked and hydrated.

        Returns:
            AccountFinancial: The live, temporally accurate financial state of the account.

        Raises:
            RuntimeError: If called during an unauthenticated 'Lobby' session
                where financial info was not hydrated.
        """
        if self.financial_info is None:
            raise RuntimeError("financial_info was not hydrated in this projection")

        return self.financial_info


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
