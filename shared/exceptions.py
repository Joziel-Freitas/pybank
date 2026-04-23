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


class ExpiredTokenError(SecurityError):
    """Raised when a token's Time-To-Live (TTL) has passed."""


# --- Domain Layer Exceptions ---


class DomainError(Exception):
    """Base exception for all domain-specific business rule violations."""


# --- Application Layer Exceptions ---


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


class BankNameError(BankError):
    """Raised when the Bank's name is invalid."""


class DuplicatedClientError(BankError):
    """Raised when a Client is already registered in Bank."""


class DuplicatedAccountError(BankError):
    """Raised when an Account is already registered in the Bank."""


class BankPasswordError(BankError):
    """Raised when a Bank password validation fails."""


class ClientNotFoundError(BankError):
    """Raised when a client is not found in the Bank's registry."""


class AccountNotFoundError(BankError):
    """Raised when an account is not found in the Bank's registry."""


class BankAuthenticationError(BankError):
    """Raised when the authentication process fails."""


class NotEmptyAccountError(BankError):
    """Raised when closing an account with a non-zero balance."""


class AccountAlreadyActiveError(BankError):
    """Raised when trying to unfreeze an operational account."""


class HomeBranchRestrictionError(BankError):
    """Raised when an operation is restricted to the account's home branch."""


class BankUnavailableError(BankError):
    """Raised when an operation fails due to internal infrastructure issues."""


# --- Person Domain Exceptions ---


class PersonError(DomainError):
    """Base exception for errors related to the Person/Client entity."""


class InvalidNameError(PersonError):
    """Raised when a name violates formatting or length rules."""


class InvalidBirthDateError(PersonError):
    """Raised when a birth date is in the future or age is out of range."""


class InvalidCpfError(PersonError):
    """Raised when a CPF fails mathematical or length validation."""


class PersonDuplicatedCardError(PersonError):
    """Raised when adding a card already associated with the client."""


class PersonCardNotFoundError(PersonError):
    """Raised when accessing a card not found in the client's collection."""


# --- Account Domain Exceptions ---


class AccountError(DomainError):
    """Base exception for errors related to the Account entity."""


class BlockedAccountError(AccountError):
    """Raised when an operation is attempted on a frozen/blocked account."""


class InvalidBranchError(AccountError):
    """Raised for an invalid branch code format."""


class InvalidAccountError(AccountError):
    """Raised for an invalid account number format."""


class InvalidBalanceError(AccountError):
    """Raised for invalid initial balances."""


class InvalidDepositError(AccountError):
    """Raised when a deposit value is non-positive."""


class InvalidWithdrawError(AccountError):
    """Raised when a withdrawal violates business rules (e.g., funds, negative value)."""


class OverdraftRequiredError(AccountError):
    """Raised when requested amount exceeds account balance"""


# --- Error Metadata Mappers ---

type ErrorMapType = dict[type[DomainError], str]

DOMAIN_ERROR_MAP: ErrorMapType = {
    BankNameError: "name",
    BankPasswordError: "password",
    BankAuthenticationError: "auth",
    DuplicatedClientError: "already_client",
    ClientNotFoundError: "not_client",
    DuplicatedAccountError: "acc_duplicated",
    AccountNotFoundError: "acc_not_found",
    BlockedAccountError: "acc_blocked",
    AccountAlreadyActiveError: "acc_active",
    NotEmptyAccountError: "non_zero_value",
    HomeBranchRestrictionError: "other_branch",
    InvalidNameError: "name",
    InvalidBirthDateError: "birth_date",
    InvalidCpfError: "cpf",
    PersonDuplicatedCardError: "duplicated_card",
    PersonCardNotFoundError: "card_not_found",
    InvalidBranchError: "branch_code",
    InvalidAccountError: "account_num",
    InvalidBalanceError: "balance",
    InvalidDepositError: "value",
    InvalidWithdrawError: "value",
    OverdraftRequiredError: "use_limit",
    BankUnavailableError: "unavailable",
}


def map_exceptions(error: DomainError) -> str:
    """
    Maps a DomainError to a standardized context code.

    Provides a flat, O(1) lookup to identify the specific reason for a domain
    failure without requiring direct type evaluation of the exception.

    Args:
        error (DomainError): The caught domain exception instance.

    Returns:
        str: A standardized string identifier representing the error's context.

    Raises:
        TypeError: If the provided argument is not a subclass of DomainError.
        NotImplementedError: If the exception type is valid but missing from
            the DOMAIN_ERROR_MAP dictionary.
    """
    if not isinstance(error, DomainError):
        raise TypeError(f"Function expects DomainError, got {type(error).__name__}")

    error_context = DOMAIN_ERROR_MAP.get(type(error))

    if error_context is None:
        raise NotImplementedError(
            f"Exception {type(error).__name__} is missing from DOMAIN_ERROR_MAP"
        )

    return error_context
