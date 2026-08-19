"""Application Layer Input Validation Facade Module.

Provides a unified, lightweight validation interface bridging Presentation inputs with
Domain Value Objects.

This module exposes specialized, type-safe validation functions for primitive inputs
(strings, dates, decimals) collected at the boundaries of the application. Each function
delegates internal format and business invariant checking to the corresponding Domain
Value Object (BranchCode, AccountNumber, AccountHolderName, CPF, BirthDate, Password, Money).

To preserve clean architecture boundaries and isolate the Presentation layer from internal
Domain concepts, any DomainError raised during Value Object instantiation is caught and
re-wrapped inside an Application-level InvalidDataError.
"""

from datetime import date
from decimal import Decimal

from domain.value_objects import (
    CPF,
    AccountHolderName,
    AccountNumber,
    BirthDate,
    BranchCode,
    DomainVO,
    Money,
    Password,
    ValueTypes,
)
from shared.exceptions import DomainVOError, InvalidDataError


def _validate_primitives[PrimitiveT: ValueTypes](
    primitive: PrimitiveT, obj_type: type[DomainVO[PrimitiveT]]
) -> PrimitiveT:
    """Helper function to validate a primitive value by attempting DomainVO instantiation.

    Args:
        primitive (PrimitiveT): The raw primitive input value to be validated.
        obj_type (type[DomainVO[PrimitiveT]]): The concrete Domain Value Object class
            parameterized with the matching primitive type.

    Returns:
        PrimitiveT: The validated primitive value retrieved directly from the instantiated
            Value Object's 'value' attribute.

    Raises:
        InvalidDataError: If the Domain Value Object rejects the input due to invariant
            or format violations, shielding upper layers from DomainError exceptions.
    """
    try:
        return obj_type(primitive).value
    except DomainVOError as e:
        raise InvalidDataError(
            "Primitive not validated by domain invariant rules"
        ) from e


def validate_branch_code(branch_code: str) -> str:
    """Validates a 4-digit bank branch code string.

    Args:
        branch_code (str): The raw branch code string.

    Returns:
        str: The validated 4-digit branch code.

    Raises:
        InvalidDataError: If the branch code fails format or length validation rules.
    """
    return _validate_primitives(primitive=branch_code, obj_type=BranchCode)


def validate_account_num(account_num: str) -> str:
    """Validates an 8-digit account number string.

    Args:
        account_num (str): The raw account number string.

    Returns:
        str: The validated 8-digit account number.

    Raises:
        InvalidDataError: If the account number fails format or length validation rules.
    """
    return _validate_primitives(primitive=account_num, obj_type=AccountNumber)


def validate_holder_name(holder_name: str) -> str:
    """Validates an account holder's full legal name string.

    Args:
        holder_name (str): The raw full name string.

    Returns:
        str: The validated full name.

    Raises:
        InvalidDataError: If the name contains non-alphabetic characters or fewer than 3 letters.
    """
    return _validate_primitives(primitive=holder_name, obj_type=AccountHolderName)


def validate_cpf(cpf: str) -> str:
    """Validates an 11-digit CPF string against mathematical checksum rules.

    Args:
        cpf (str): The raw CPF string.

    Returns:
        str: The mathematically verified 11-digit CPF string.

    Raises:
        InvalidDataError: If the CPF fails format, digit count, or checksum verification.
    """
    return _validate_primitives(primitive=cpf, obj_type=CPF)


def validate_birth_date(birth_date: date) -> date:
    """Validates an account holder's birth date enforcing institutional age limits (18-120).

    Args:
        birth_date (date): The raw birth date object.

    Returns:
        date: The validated birth date.

    Raises:
        InvalidDataError: If the date is in the future or the calculated age falls outside [18, 120].
    """
    return _validate_primitives(primitive=birth_date, obj_type=BirthDate)


def validate_password(password: str) -> str:
    """Validates a 6-digit numeric account password string.

    Args:
        password (str): The raw plain-text password string.

    Returns:
        str: The validated 6-digit numeric password.

    Raises:
        InvalidDataError: If the password is not exactly 6 numeric digits.
    """
    return _validate_primitives(primitive=password, obj_type=Password)


def validate_money(amount: Decimal) -> Decimal:
    """Validates a monetary transaction amount against minimum institutional limits.

    Args:
        amount (Decimal): The monetary amount to be evaluated.

    Returns:
        Decimal: The validated monetary amount.

    Raises:
        InvalidDataError: If the amount is below the minimum allowed ATM threshold (R$ 2.00).
    """
    return _validate_primitives(primitive=amount, obj_type=Money)
