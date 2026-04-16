"""
Module containing validation methods used across all classes in the project.
Raises exceptions when invalid values are detected.
"""

from decimal import Decimal


def verify_instance(
    param: object, inst_type: type | tuple[type, ...], error_msg: str | None = None
) -> None:
    """
    Validates that a parameter is an instance of the expected type(s).

    Args:
        param (object): The value to validate.
        inst_type (type | tuple[type, ...]): The expected type(s).
            Can be a single type or a tuple of types.
            If a tuple is provided, all elements must be valid Python types.
        error_msg (Optional[str]): Custom error message to raise if validation fails.

    Raises:
        TypeError: If 'inst_type' is not a type or tuple of types,
                   if 'error_msg' is not a string,
                   or if 'param' does not match the required type(s).
    """

    if not isinstance(inst_type, (type, tuple)):
        raise TypeError("inst_type must be a type or a tuple of types")

    if isinstance(inst_type, tuple):
        if not all(isinstance(t, type) for t in inst_type):
            raise TypeError("All elements in inst_type tuple must be types")

    if error_msg is not None:
        if not isinstance(error_msg, str):
            raise TypeError("error_msg must be a string")

    if not isinstance(param, inst_type):
        if isinstance(inst_type, tuple):
            type_names = " or ".join([t.__name__ for t in inst_type])
        else:
            type_names = inst_type.__name__

        if error_msg is None:
            error_msg = (
                f"Invalid type. Expected {type_names}, got {type(param).__name__}"
            )

        raise TypeError(error_msg)


def verify_interval(
    target_value: int | float | Decimal,
    min_val: int | float | Decimal | None = None,
    max_val: int | float | Decimal | None = None,
) -> None:
    """
    Ensures that a numeric value falls within a specified interval and enforces strict type matching.

    At least one of 'min_val' or 'max_val' must be provided. Both bounds are inclusive.
    To prevent precision bugs and runtime errors during comparison, the provided limits
    must exactly match the type of the 'target_value'.

    Args:
        target_value (int | float | Decimal): The numeric value to validate.
        min_val (int | float | Decimal | None): The minimum allowed value (inclusive).
        max_val (int | float | Decimal | None): The maximum allowed value (inclusive).

    Raises:
        TypeError: If 'target_value' is not a valid numeric type, if no bounds are provided,
                   or if the type of the provided limits does not exactly match the type
                   of the 'target_value'.
        ValueError: If 'target_value' is outside the specified interval.
    """
    valid_types = (int, float, Decimal)

    if not isinstance(target_value, valid_types):
        raise TypeError("The method accepts only int, float or Decimal values")

    target_type = type(target_value)

    if min_val is None and max_val is None:
        raise TypeError("At least one limit (min_val or max_val) must be provided")

    if min_val is not None and type(min_val) is not target_type:
        raise TypeError("min_val must be of the exact same type as target_value")

    if max_val is not None and type(max_val) is not target_type:
        raise TypeError("max_val must be of the exact same type as target_value")

    if min_val and target_value < min_val:
        raise ValueError(
            f"Value {target_value} must be greater than or equal to {min_val}"
        )
    if max_val and target_value > max_val:
        raise ValueError(
            f"Value {target_value} must be less than or equal to {max_val}"
        )


def verify_digits(param: str, size: int) -> None:
    """
    Validates that a string contains only digits and has an exact length.

    Args:
        param (str): The string to validate.
        size (int): The required length of the string.

    Raises:
        TypeError: If 'param' is not a string or 'size' is not an integer.
        ValueError: If 'param' contains non-digit characters
                    or its length does not equal 'size'.
    """

    if not isinstance(param, str):
        raise TypeError(f"param expects str, got {type(param).__name__}")

    if not isinstance(size, int):
        raise TypeError(f"size expects int, got {type(size).__name__}")

    if not param.isdigit():
        raise ValueError(f"Value {param} must contain only digits")

    if len(param) != size:
        raise ValueError(f"Value {param} must have exactly {size} digits")
