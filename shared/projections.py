from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from shared.types import AccrualType, FinancialType


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
    Root Data Transfer Object representing a dynamic, lightweight projection of an Account.

    Utilizes Composition over Inheritance to structure raw database results.
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
        """
        Safely extracts the nested identity projection.

        Acts as a strict type-narrowing mechanism. It guarantees to both the
        static type checker and the runtime caller that the nested DTO exists,
        eliminating the need for repetitive 'is None' checks in the Domain layer.

        Returns:
            HolderProjectionDTO: The hydrated identity context.

        Raises:
            RuntimeError: If the projection was originally queried from the
                database without explicitly requesting holder information.
        """
        if self.holder_info is None:
            raise RuntimeError("holder_info was not hydrated in this projection")
        return self.holder_info

    def unwrap_access(self) -> AccessProjectionDTO:
        """
        Safely extracts the nested security projection.

        Acts as a strict type-narrowing mechanism. It guarantees to both the
        static type checker and the runtime caller that the nested DTO exists,
        eliminating the need for repetitive 'is None' checks in the Domain layer.

        Returns:
            AccessProjectionDTO: The hydrated security context.

        Raises:
            RuntimeError: If the projection was originally queried from the
                database without explicitly requesting access information.
        """
        if self.access_info is None:
            raise RuntimeError("access_info was not hydrated in this projection")
        return self.access_info
