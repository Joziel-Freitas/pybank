"""
Central module for all custom exceptions in the banking system.

This module establishes a clear, hierarchical structure for all custom errors,
distinguishing between different architectural layers:

1. **Infrastructure/Repository Errors**: Abstract database-level failures.
2. **Security Errors**: Critical violations and session-integrity breaches.
3. **Domain Errors (The Royalty)**: Business rule violations within Account,
   Person, and Bank entities.
4. **Application/Controller Errors**: Flow orchestration and session management
   failures (isolated from the Domain).

Includes a mapping utility to translate Domain failures into UI-friendly
configuration keys for contextual messaging.
"""

# --- Infrastructure Layer Exceptions ---


class RepositoryError(Exception):
    """
    Base exception for all errors originating from the Infrastructure/Repository layer.

    Ensures that Domain and Application layers do not depend on third-party
    library exceptions (e.g., PyMySQL).
    """


class DataNotFoundError(RepositoryError):
    """Raised when a requested record is not found in the database."""


class DuplicatedDataError(RepositoryError):
    """Raised when an insertion violates a unique constraint (e.g., duplicate CPF)."""


# --- Security Layer Exceptions ---


class SecurityError(Exception):
    """Base exception for all critical security violations in the system."""


class BankSecurityError(SecurityError):
    """
    Raised when a critical violation is detected (e.g., Token tampering).
    Forces immediate session termination.
    """


# --- Domain Layer Exceptions (The Royalty) ---


class DomainError(Exception):
    """Base exception for all domain-specific business rule violations."""


# --- Application Layer Exceptions (The Orchestra) ---


class ControllerError(Exception):
    """
    Base exception for orchestration and navigation failures within Controllers.
    Independent from DomainError to separate business logic from UI flow.
    """


class ControllerRegisterError(ControllerError):
    """Raised when an onboarding or entity creation process fails."""


class ControllerCredentialsError(ControllerError):
    """Raised when authentication fails or access is denied during operational flow."""


class ControllerOperationError(ControllerError):
    """Raised when a high-level banking workflow (e.g., Transaction) is interrupted."""


class UserAbortError(Exception):
    """Control flow exception raised when the user manually cancels an operation."""


# --- Bank Domain Exceptions ---


class BankError(DomainError):
    """Base exception for errors related to the Bank service layer."""


class BankAttributeError(BankError):
    """Base exception for validation errors on Bank attributes."""


class BankMethodError(BankError):
    """Base exception for errors during Bank business operations."""


class BankNameError(BankAttributeError):
    """Raised when the Bank's name is invalid."""


class DuplicatedClientError(BankMethodError):
    """Raised when a Client is already registered in Bank."""


class DuplicatedAccountError(BankMethodError):
    """Raised when an Account is already registered in the Bank."""


class BankPasswordError(BankMethodError):
    """Raised when a Bank password validation fails."""


class ClientNotFoundError(BankMethodError):
    """Raised when a client is not found in the Bank's registry."""


class AccountNotFoundError(BankMethodError):
    """Raised when an account is not found in the Bank's registry."""


class BankAuthenticationError(BankMethodError):
    """Raised when the authentication process fails."""


class NotEmptyAccountError(BankMethodError):
    """Raised when closing an account with a non-zero balance."""


class AccountAlreadyActiveError(BankMethodError):
    """Raised when trying to unfreeze an operational account."""


class HomeBranchRestrictionError(BankMethodError):
    """Raised when an operation is restricted to the account's home branch."""


# --- Person Domain Exceptions ---


class PersonError(DomainError):
    """Base exception for errors related to the Person/Client entity."""


class PersonAttributeError(PersonError):
    """Validation errors on Person core attributes (Name, CPF, Birth Date)."""


class InvalidNameError(PersonAttributeError):
    """Raised when a name violates formatting or length rules."""


class InvalidBirthDateError(PersonAttributeError):
    """Raised when a birth date is in the future or age is out of range."""


class InvalidCpfError(PersonAttributeError):
    """Raised when a CPF fails mathematical or length validation."""


class PersonMethodError(PersonError):
    """Errors during Client-specific operations."""


class PersonDuplicatedCardError(PersonMethodError):
    """Raised when adding a card already associated with the client."""


class PersonCardNotFoundError(PersonMethodError):
    """Raised when accessing a card not found in the client's collection."""


# --- Account Domain Exceptions ---


class AccountError(DomainError):
    """Base exception for errors related to the Account entity."""


class BlockedAccountError(AccountError):
    """Raised when an operation is attempted on a frozen/blocked account."""


class AccountAttributeError(AccountError):
    """Validation errors on Account attributes (Branch, Number, Balance)."""


class AccountMethodError(AccountError):
    """Errors during financial operations (Deposit, Withdraw)."""


class InvalidBranchError(AccountAttributeError):
    """Raised for an invalid branch code format."""


class InvalidAccountError(AccountAttributeError):
    """Raised for an invalid account number format."""


class InvalidBalanceError(AccountAttributeError):
    """Raised for invalid initial balances."""


class InvalidWithdrawError(AccountMethodError):
    """Raised when a withdrawal violates business rules (e.g., funds, negative value)."""


class InvalidDepositError(AccountMethodError):
    """Raised when a deposit value is non-positive."""


# --- Error Metadata Mappers ---

type ErrorMapType = dict[type[DomainError], dict[type[DomainError], str] | str]

BANK_ERROR_MAP: ErrorMapType = {
    BankAttributeError: {BankNameError: "name"},
    BankMethodError: {
        BankPasswordError: "password",
        BankAuthenticationError: "auth",
        DuplicatedClientError: "already_client",
        ClientNotFoundError: "not_client",
        DuplicatedAccountError: "duplicated_account",
        AccountNotFoundError: "not_account",
        BlockedAccountError: "acc_blocked",
        AccountAlreadyActiveError: "active_account",
        NotEmptyAccountError: "non_zero_value",
        HomeBranchRestrictionError: "other_branch",
    },
}

PERSON_ERROR_MAP: ErrorMapType = {
    PersonAttributeError: {
        InvalidNameError: "name",
        InvalidBirthDateError: "birth_date",
        InvalidCpfError: "cpf",
    },
    PersonMethodError: {
        PersonDuplicatedCardError: "duplicated_card",
        PersonCardNotFoundError: "not_found",
    },
}

ACCOUNT_ERROR_MAP: ErrorMapType = {
    AccountAttributeError: {
        InvalidBranchError: "branch_code",
        InvalidAccountError: "account_num",
        InvalidBalanceError: "balance",
    },
    AccountMethodError: {
        InvalidDepositError: "value",
        InvalidWithdrawError: "value",
    },
}


def map_exceptions(exception_instance: DomainError, error_map: ErrorMapType) -> str:
    """
    Translates a DomainError into a UI-friendly configuration key.

    This utility allows Controllers to identify the specific cause of a
    failure without knowing the inner details of the exception. The returned
    string is used to look up the appropriate message in the View layer.

    Args:
        exception_instance (DomainError): The caught domain exception.
        error_map (ErrorMapType): The mapping dictionary for the specific domain.

    Returns:
        str: A configuration key matching the system's View/Config keys.

    Raises:
        TypeError: If the exception type is not present in the provided map.
    """
    config_key = type(exception_instance)

    # Check for direct flat mapping
    mapped_value = error_map.get(config_key)
    if isinstance(mapped_value, str):
        return mapped_value

    # Check for nested hierarchical mapping
    for error in error_map.values():
        if isinstance(error, dict) and config_key in error:
            return error[config_key]

    raise TypeError(
        f"Critical: Exception type {config_key.__name__} not found in mapper."
    )
