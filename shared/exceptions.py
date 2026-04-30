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


class SystemBaseException(Exception):
    """
    Root exception for all custom errors in the PyBank system.

    Extends the native Python Exception class by introducing an optional
    `argument` attribute. This allows the system to attach the specific
    object or data payload that caused the failure directly to the exception.
    By doing so, higher-level layers (like the Domain) can inspect the
    error's origin using object identity (`is`) or type checking (`isinstance`),
    completely eliminating the need to parse raw error strings or use magic strings.
    """

    def __init__(
        self, msg: object | None = None, argument: object | None = None
    ) -> None:
        """
        Initializes the base system exception.

        Args:
            msg (object | None): The descriptive error message for logging and debugging.
                If omitted, the exception is raised silently without a message payload.
            argument (object | None): The specific object, entity, or primitive
                that triggered the exception. Preserves the exact memory identity
                for structural error handling in upper architectural layers.
        """
        if msg is not None:
            super().__init__(msg)
        else:
            super().__init__()

        self.argument = argument


# --- Infrastructure Layer Exceptions ---


class RepositoryError(SystemBaseException):
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


class SecurityError(SystemBaseException):
    """Base exception for all critical security violations in the system."""


class BankSecurityError(SecurityError):
    """
    Raised when a critical violation is detected (e.g., Token tampering).
    Forces immediate session termination.
    """


class ExpiredTokenError(SecurityError):
    """Raised when a token's Time-To-Live (TTL) has passed."""


# --- Application Layer Exceptions ---


class ControllerError(SystemBaseException):
    """
    Base exception for orchestration and navigation failures within Controllers.
    Independent from DomainError to separate business logic from UI flow.
    """


class ControllerCredentialsError(ControllerError):
    """Raised when authentication fails or access is denied during operational flow."""


class ControllerOperationError(ControllerError):
    """Raised when a high-level banking workflow (e.g., Transaction) is interrupted."""


class ControllerRegisterError(ControllerError):
    """Raised when an onboarding or entity creation process fails."""


class UserAbortError(Exception):
    """Control flow exception raised when the user manually cancels an operation."""


# --- Domain Layer Exceptions ---


class DomainError(SystemBaseException):
    """Base exception for all domain-specific business rule violations."""


# --- Bank Domain Exceptions ---


class BankError(DomainError):
    """Base exception for errors related to the Bank service layer."""


class AccountAlreadyActiveError(BankError):
    """Raised when trying to unfreeze an operational account."""


class AccountNotFoundError(BankError):
    """Raised when an account is not found in the Bank's registry."""


class BankAccessError(BankError):
    """Raised when the access process fails."""


class BankAuthenticationError(BankError):
    """Raised when the authentication process fails."""


class BankNameError(BankError):
    """Raised when the Bank's name is invalid."""


class BankPasswordError(BankError):
    """Raised when a Bank password validation fails."""


class BankUnavailableError(BankError):
    """Raised when an operation fails due to internal infrastructure issues."""


class AccountHolderNotFoundError(BankError):
    """Raised when an account holder is not found in the Bank's registry."""


class DuplicatedAccountError(BankError):
    """Raised when an Account is already registered in the Bank."""


class DuplicatedAccountHolderError(BankError):
    """Raised when an AccountHolder is already registered in Bank."""


class HomeBranchRestrictionError(BankError):
    """Raised when an operation is restricted to the account's home branch."""


class NotEmptyAccountError(BankError):
    """Raised when closing an account with a non-zero balance."""


# --- Person Domain Exceptions ---


class PersonError(DomainError):
    """Base exception for errors related to the Person/AccountHolder entity."""


class AccountHolderCardNotFoundError(PersonError):
    """Raised when accessing a card not found in the account holder's collection."""


class AccountHolderDuplicatedCardError(PersonError):
    """Raised when adding a card already associated with the account holder."""


class InvalidBirthDateError(PersonError):
    """Raised when a birth date is in the future or age is out of range."""


class InvalidCpfError(PersonError):
    """Raised when a CPF fails mathematical or length validation."""


class InvalidNameError(PersonError):
    """Raised when a name violates formatting or length rules."""


# --- Account Domain Exceptions ---


class AccountError(DomainError):
    """Base exception for errors related to the Account entity."""


class BlockedAccountError(AccountError):
    """Raised when an operation is attempted on a frozen/blocked account."""


class InvalidAccountError(AccountError):
    """Raised for an invalid account number format."""


class InvalidBalanceError(AccountError):
    """Raised for invalid initial balances."""


class InvalidBranchError(AccountError):
    """Raised for an invalid branch code format."""


class InvalidDepositError(AccountError):
    """Raised when a deposit value is non-positive."""


class InvalidWithdrawError(AccountError):
    """Raised when a withdrawal violates business rules (e.g., funds, negative value)."""


class OverdraftRequiredError(AccountError):
    """Raised when requested amount exceeds account balance"""


# --- Error Metadata Mappers ---

type ErrorMapType = dict[type[DomainError], str]

DOMAIN_ERROR_MAP: ErrorMapType = {
    AccountAlreadyActiveError: "acc_active",
    AccountHolderCardNotFoundError: "card_not_found",
    AccountHolderDuplicatedCardError: "duplicated_card",
    AccountNotFoundError: "acc_not_found",
    BankAccessError: "access",
    BankAuthenticationError: "auth",
    BankNameError: "name",
    BankPasswordError: "password",
    BankUnavailableError: "unavailable",
    BlockedAccountError: "acc_blocked",
    AccountHolderNotFoundError: "not_account_holder",
    DuplicatedAccountError: "acc_duplicated",
    DuplicatedAccountHolderError: "already_account_holder",
    HomeBranchRestrictionError: "other_branch",
    InvalidAccountError: "account_num",
    InvalidBalanceError: "balance",
    InvalidBirthDateError: "birth_date",
    InvalidBranchError: "branch_code",
    InvalidCpfError: "cpf",
    InvalidDepositError: "value",
    InvalidNameError: "name",
    InvalidWithdrawError: "value",
    NotEmptyAccountError: "non_zero_value",
    OverdraftRequiredError: "use_limit",
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
