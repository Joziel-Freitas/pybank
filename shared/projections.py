"""Shared Projections Module.

This module defines read-only projection DTOs and Russian Doll composite views
used across Application Services and the Presentation layer to render account status,
security details, and statements without hydrating full Domain entities.
"""

from abc import ABC
from dataclasses import dataclass
from datetime import date
from typing import Any

from domain.value_objects import AccountFinancial


class ProjectionDTO(ABC):
    """Abstract base marker class for all read-only Projection DTOs.

    Establishes a unified base type for lightweight data transfer objects that
    transport non-mutating state projections across application boundaries,
    ensuring consistent static typing for presentation and query layers.
    """


@dataclass(frozen=True, slots=True)
class AccessProjectionDTO(ProjectionDTO):
    """Data Transfer Object holding security and access credentials.

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
class HolderProjectionDTO(ProjectionDTO):
    """Data Transfer Object holding the account holder's personal information.

    Acts as a nested projection containing Personally Identifiable Information (PII)
    associated with an account holder. Populated only when identity verification or
    presentation display is required.

    Attributes:
        name (str): The full name of the account holder.
        cpf (str): The 11-digit CPF string.
        birth_date (date): The birth date of the account holder.
    """

    name: str
    cpf: str
    birth_date: date


@dataclass(frozen=True, slots=True)
class AccountProjectionDTO(ProjectionDTO):
    """Root Data Transfer Object representing a dynamic, lightweight projection of an Account.

    Utilizes Composition over Inheritance to structure raw persistence results.
    Stripped of all financial balance data to enforce domain-driven constraints;
    retrieving financial truth now strictly requires full Entity hydration.

    Attributes:
        branch_code (str): The baseline 4-digit branch code.
        account_num (str): The baseline 8-digit account number.
        account_type (str): The baseline classification of the account.
        is_frozen (bool): The baseline operational status of the account.
        access_info (AccessProjectionDTO | None): The nested security context, or None.
        holder_info (HolderProjectionDTO | None): The nested identity context, or None.
    """

    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    access_info: AccessProjectionDTO | None
    holder_info: HolderProjectionDTO | None

    def unwrap_holder(self) -> HolderProjectionDTO:
        """Safely extracts the nested identity projection."""
        if self.holder_info is None:
            raise RuntimeError("holder_info was not hydrated in this projection")
        return self.holder_info

    def unwrap_access(self) -> AccessProjectionDTO:
        """Safely extracts the nested security projection."""
        if self.access_info is None:
            raise RuntimeError("access_info was not hydrated in this projection")
        return self.access_info


@dataclass(frozen=True, slots=True)
class SummaryProjectionDTO(ProjectionDTO):
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
        account_type (str): The class name representing the account type.
        is_frozen (bool): Flag indicating if the account is active or frozen.
        financial_info (AccountFinancial | None): The account's core financial metrics.
    """

    holder_name: str
    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    financial_info: AccountFinancial | None

    def unwrap_financial(self) -> AccountFinancial:
        """Safely extracts the nested financial projection."""
        if self.financial_info is None:
            raise RuntimeError("financial_info was not hydrated in this projection")
        return self.financial_info


@dataclass(frozen=True, slots=True)
class StatementProjectionDTO(ProjectionDTO):
    """Data Transfer Object representing a mathematically consistent account statement.

    Acts as an immutable payload combining a read-only representation of the account's
    current state with its chronological ledger event history.

    Attributes:
        account_info (AccountSummaryDTO): The account's full summary.
        financial_events (tuple[dict[str, Any], ...]): Sequence of ledger events.
    """

    account_info: SummaryProjectionDTO
    financial_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DepositTargetProjectionDTO(ProjectionDTO):
    """A read-only, sanitized snapshot of an account intended exclusively
    for public deposit confirmation screens.

    Contains masked sensitive information (like CPF) to prevent data leaks
    during unauthenticated queries, adhering to Zero Trust principles.

    Attributes:
        holder_name (str): The full name of the account holder.
        holder_masked_cpf (str): The masked 11-digit CPF string.
        branch_code (str): The target account branch code.
        account_num (str): The target account number.
        account_type (str): The semantic name of the account type.
    """

    holder_name: str
    holder_masked_cpf: str
    branch_code: str
    account_num: str
    account_type: str
