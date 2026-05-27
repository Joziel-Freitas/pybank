"""
Shared Data Transfer Objects (DTOs) Module.

This module defines immutable payloads used to transport data across architectural
boundaries (e.g., from the Presentation layer to the Domain layer).

By strictly using primitive types and standard library objects, these DTOs prevent
Domain Entity leakage and eliminate circular dependencies between modules.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


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
class AccountSummaryDTO:
    """
    A read-only, non-sensitive snapshot of an account's basic state.

    Used primarily in the 'Lobby' (Identity-First) phase of the presentation layer.
    It deliberately excludes financial data (like balance or overdraft limits)
    to allow safe routing and dynamic menu rendering (e.g., blocking access to
    frozen accounts) without requiring full Vault authorization (AccessToken).

    Attributes:
        holder_name (str): The full name of the account holder.
        branch_code (str): The branch code where the account is registered.
        account_num (str): The unique account identifier.
        account_type (str): The class name representing the account type (e.g., 'CheckingAccount').
        is_frozen (bool): Flag indicating if the account is active or frozen.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool


@dataclass(frozen=True, slots=True)
class AccountFinancialDTO:
    """
    Data Transfer Object representing a read-only snapshot of an Account's financial state.

    Acts as a secure payload to transport account information from the Domain layer
    to the Presentation layer. By encapsulating only primitive data types, it ensures
    the core Account entity does not leak into the UI, preserving strict Domain-Driven
    Design (DDD) boundaries.

    Attributes:
        holder_name (str): The full name of the account holder.
        branch_code (str): The 4-digit branch code where the account is registered.
        account_num (str): The 8-digit unique account number.
        account_type (str): The classification of the account (e.g., Checking, Savings).
        balance (Decimal): The current available financial balance.
        overdraft_limit (Decimal | None): The maximum overdraft limit. None if the account
            does not support overdraft (e.g., SavingsAccount).
        available_overdraft (Decimal | None): The currently available overdraft amount.
            None if the account does not support overdraft.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    balance: Decimal
    overdraft_limit: Decimal | None
    available_overdraft: Decimal | None


@dataclass(frozen=True, slots=True)
class StatementDTO:
    """
    Data Transfer Object representing a mathematically consistent account statement.

    Acts as an immutable payload combining a read-only representation of the account's
    current state with its chronological transaction history.

    Attributes:
        account_info (AccountFinancialDTO): The account's financial details and balance
            at the exact moment of the statement generation.
        transactions (tuple[dict[str, Any], ...]): A chronological sequence of
            transaction records (amount and timestamp) occurring on or after
            a requested start date.
    """

    account_info: AccountFinancialDTO
    transactions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FinancialProjectionDTO:
    """
    Data Transfer Object holding the financial state of an account.

    Acts as a nested projection representing monetary values. It is only
    instantiated and attached to the root projection if financial data
    was explicitly requested from the infrastructure layer.

    Attributes:
        balance (Decimal): The current available balance.
        used_overdraft (Decimal): The utilized amount of the overdraft limit.
    """

    balance: Decimal
    used_overdraft: Decimal


@dataclass(frozen=True, slots=True)
class AccessProjectionDTO:
    """
    Data Transfer Object holding security and access credentials.

    Acts as a nested projection representing the account's vault security state.
    It is securely isolated and only populated when authentication checks
    or security updates are required.

    Attributes:
        password_hash (str): The cryptographic Bcrypt hash of the account's password.
        failed_attempts (int): The number of consecutive failed login attempts.
    """

    password_hash: str
    failed_attempts: int


@dataclass(frozen=True, slots=True)
class HolderProjectionDTO:
    """
    Data Transfer Object holding the account holder's personal information.

    Acts as a nested projection containing Personally Identifiable Information (PII)
    retrieved via a database JOIN. Only hydrated when identity verification or
    presentation display is necessary.

    Attributes:
        name (str): The full name of the account holder.
        cpf (str): The 11-digit CPF string.
        birth_date (date): The birth date of the account holder.
    """

    name: str
    cpf: str
    birth_date: date


@dataclass(frozen=True, slots=True)
class AccountProjectionDTO:
    """
    Root Data Transfer Object representing a dynamic, composed projection of an Account.

    Utilizes Composition over Inheritance to structure raw database results
    into a predictable, type-safe "Russian Doll" architecture. The baseline
    routing and status fields are always guaranteed. The nested context DTOs
    (financial, access, holder) dynamically reflect the flags passed to the
    Repository's query builder.

    Attributes:
        branch_code (str): The baseline 4-digit branch code.
        account_num (str): The baseline 8-digit account number.
        account_type (str): The baseline classification of the account.
        is_frozen (bool): The baseline operational status of the account.
        financial_info (FinancialProjectionDTO | None): The nested financial context, or None.
        access_info (AccessProjectionDTO | None): The nested security context, or None.
        holder_info (HolderProjectionDTO | None): The nested identity context, or None.
    """

    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    financial_info: FinancialProjectionDTO | None
    access_info: AccessProjectionDTO | None
    holder_info: HolderProjectionDTO | None
