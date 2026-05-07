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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
        is_active (bool): Flag indicating if the account is active or frozen.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    is_active: bool


@dataclass(frozen=True)
class AccountInfoDTO:
    """
    Data Transfer Object representing a read-only snapshot of an Account's current state.

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
        is_active (bool): The operational status of the account (True for active, False for frozen/blocked).
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
    is_active: bool
    overdraft_limit: Decimal | None
    available_overdraft: Decimal | None


@dataclass(frozen=True)
class StatementDTO:
    """
    Data Transfer Object representing a mathematically consistent account statement.

    Acts as an immutable payload combining a read-only representation of the account's
    current state with its chronological transaction history.

    Attributes:
        account_info (AccountInfoDTO): The account's details and balance
            at the exact moment of the statement generation.
        transactions (tuple[dict[str, Any], ...]): A chronological sequence of
            transaction records (amount and timestamp) occurring on or after
            a requested start date.
    """

    account_info: AccountInfoDTO
    transactions: tuple[dict[str, Any], ...]
