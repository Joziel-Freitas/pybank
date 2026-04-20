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


@dataclass(frozen=True)
class NewClientDTO:
    """
    Data Transfer Object containing the validated data required to register a new Client.

    Acts as a secure, immutable payload traveling from the OnboardingController
    to the Bank aggregate. It relies strictly on primitive types to ensure the
    Presentation layer does not need to import or construct Domain Entities.

    Attributes:
        name (str): The validated full name of the client.
        cpf (str): The validated 11-digit CPF string.
        birth_date (date): The validated birth date of the client.
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
        balance (Decimal): The initial financial deposit (must be >= 0).
    """

    account_type: int
    branch_code: str
    account_num: str
    balance: Decimal
