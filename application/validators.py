from shared import verify
from shared.exceptions import PasswordValidationError


def validate_password(password: str) -> None:
    """
    Validates the format of a password.

    Args:
        password (str): The password string to validate.

    Raises:
        TypeError: If the password is not a string.
        PasswordValidationError: If the password does not consist of exactly 6 digits.
    """
    verify.verify_instance(password, str)
    try:
        verify.verify_digits(password, 6)
    except ValueError as e:
        raise PasswordValidationError(f"Invalid password. Cause: {e}")
