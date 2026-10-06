"""Shared Validators Module.

Provides pure infrastructure data integrity and mathematical validation functions
for baseline data types, such as official CPF checksum verification.
"""

from shared import verify


def _calculate_verifier_digit(cpf_sequence: str, factor: int) -> int:
    """Calculates a single verifier digit following the official CPF rule checksum.

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


def validate_cpf(cpf: str) -> None:
    """Performs the full mathematical verification of the CPF (11 digits, sequence, DVs).

    This is a pure infrastructure validator. It focuses strictly on data integrity
    and checksum rules, leaving domain-specific error wrapping to the caller.

    Args:
        cpf (str): The 11-digit CPF string.

    Raises:
        TypeError: If the input is not a string.
        ValueError: If the CPF has an invalid length, consists of all repeated
            digits, or fails the mathematical checksum validation.
    """
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
