from datetime import date, datetime
from typing import Any, Callable

from infra import verify

from .exceptions import DomainError, InvalidCpfError

type ValidatorCallback = Callable[[Any], bool]


def boolean_validator_dec(validation_fn: Callable[[Any], Any]) -> ValidatorCallback:
    """
    Wraps a validation method to return bool instead of raising exceptions.

    This decorator adapts 'Raise-Based' validation logic (used in Domain Entities)
    to 'Boolean-Based' validation logic (used in I/O Loops).

    It catches both Domain Errors (Business Rules) and Standard Errors (Type/Value)
    raised by the infra.verify module.

    Args:
        validation_fn (Callable): The function to be wrapped.

    Returns:
        ValidatorCallback: A function that returns True if valid, False if invalid.
    """

    def wrapper(*args, **kwargs) -> bool:
        try:
            result: bool | None = validation_fn(*args, **kwargs)
            return result is not False
        except (DomainError, TypeError, ValueError):
            return False

    return wrapper


def _calculate_verifier_digit(cpf_sequence: str, factor: int) -> int:
    """
    Calculates a single verifier digit following the official CPF rule checksum.
    This is an internal helper for the full CPF validation.

    Args:
        cpf_sequence (str): The preceding sequence of digits (9 for DV1, 10 for DV2).
        factor (int): The starting multiplier (10 for DV1, 11 for DV2).

    Returns:
        int: The calculated verifier digit (0-9).
    """
    soma = 0
    for digit, multiplier in zip(cpf_sequence, range(factor, 1, -1)):
        soma += int(digit) * multiplier

    remainder = soma % 11
    return 0 if remainder < 2 else 11 - remainder


def validate_cpf(cpf: str) -> str:
    """
    Performs the full mathematical verification of the CPF (11 digits, sequence, DVs).

    Args:
        cpf (str): The 11-digit CPF string.

    Returns:
        str: The validated CPF string.

    Raises:
        InvalidCpfError: If the CPF fails any of the following:
                            - Not a string or not 11 digits long.
                            - All repeated digits (e.g., '11111111111').
                            - Fails the mathematical checksum validation.
    """
    try:
        verify.verify_instance(cpf, str)
        verify.verify_digits(cpf, 11)

        # Check for all repeated digits (e.g., "11111111111")
        if cpf == cpf[0] * 11:
            raise ValueError("CPF cannot have all digits equal.")

        # Calculate the First Verifier Digit (DV1)
        dv1 = _calculate_verifier_digit(cpf[:9], 10)

        # Calculate the Second Verifier Digit (DV2)
        dv2 = _calculate_verifier_digit(cpf[:10], 11)

        # Check if the calculated digits match the actual last two digits
        calculated_dv = f"{dv1}{dv2}"
        actual_dv = cpf[9:]

        if calculated_dv != actual_dv:
            raise ValueError(
                f"CPF is mathematically invalid. Calculated DVs: {calculated_dv}, Actual DVs: {actual_dv}."
            )
        return cpf
    except verify.VERIFY_ERRORS as e:
        raise InvalidCpfError(f"Invalid CPF. Cause: {e}") from e


def validate_date_format(date_str: str) -> date:
    """
    Validates and converts a date string into a native Python date object.

    Ensures that the provided input is a string and strictly follows the
    standard format ('dd/mm/yyyy'). This is a generic infrastructure
    validator, independent of any domain-specific business rules (like age limits).

    Args:
        date_str (str): The date string to be validated and converted.

    Returns:
        date: The parsed native Python date object.

    Raises:
        TypeError: If the provided input is not a string (via verify_instance).
        ValueError: If the string does not match the 'dd/mm/yyyy' format
            or represents an invalid calendar date (e.g., '32/01/2026').
    """
    verify.verify_instance(date_str, str)
    date_obj = datetime.strptime(date_str, "%d/%m/%Y").date()
    return date_obj
