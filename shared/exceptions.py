"""Central module for all custom exceptions in the PyBank system.

Establishes a clear, hierarchical structure for all custom errors across layers:

1. Infrastructure/Repository Errors: Persistence and lower-level I/O failures.
2. Security Errors: Cryptographic and token-integrity breaches.
3. Domain Errors: Business rule invariant violations within Aggregate Roots
   (e.g., Account, Person).
4. Application Errors: Workflow orchestration, authentication, and service-level failures.
5. Controller Errors: UI navigation and presentation flow issues.
"""


class SystemBaseException(Exception):
    """Root exception for all custom errors in the PyBank system.

    Extends Python's base Exception by attaching an optional `argument` attribute,
    allowing upper layers to inspect the error origin using object identity or
    type checks rather than string parsing.
    """

    def __init__(
        self, msg: object | None = None, argument: object | None = None
    ) -> None:
        if msg is not None:
            super().__init__(msg)
        else:
            super().__init__()

        self.argument = argument


# =====================================================================
# Infrastructure Layer Exceptions
# =====================================================================


class RepositoryError(SystemBaseException):
    """Base exception for all persistence layer errors."""


class DataNotFoundError(RepositoryError):
    """Raised when a requested record is not found in persistence."""


class DuplicatedDataError(RepositoryError):
    """Raised when an insertion violates a unique constraint."""


class SystemIOError(SystemBaseException):
    """Base exception for infrastructure I/O errors."""


class UserAbortError(SystemIOError):
    """Raised when the user manually cancels an operation."""


class InactiveUserError(SystemIOError):
    """Raised when user inactivity reaches the system timeout limit."""


# =====================================================================
# Security Layer Exceptions
# =====================================================================


class SecurityError(SystemBaseException):
    """Base exception for critical security and session breaches."""


class TokenSecurityError(SecurityError):
    """Raised when token tampering or invalid cryptographic signatures are detected."""


class ExpiredTokenError(SecurityError):
    """Raised when a token's Time-To-Live (TTL) has passed."""


# =====================================================================
# Application Layer Exceptions
# =====================================================================


class ApplicationError(SystemBaseException):
    """Base exception for orchestration and service workflow failures."""


class AccessDeniedError(ApplicationError):
    """Raised when vault or feature access is denied (e.g., frozen account)."""


class AuthenticationError(ApplicationError):
    """Raised when primary or vault authentication fails."""


class AccountHolderNotFoundError(ApplicationError):
    """Raised when an account holder record cannot be resolved by the application service."""


class AccountNotFoundError(ApplicationError):
    """Raised when an account record cannot be resolved by the application service."""


class DuplicatedAccountError(ApplicationError):
    """Raised during onboarding if an account already exists."""


class DuplicatedAccountHolderError(ApplicationError):
    """Raised during onboarding if an account holder is already registered."""


class PasswordValidationError(ApplicationError):
    """Raised when password format or policy validation fails at service level."""


class ServiceUnavailableError(ApplicationError):
    """Raised when an application workflow cannot commit state due to internal failure."""


# =====================================================================
# Domain Layer Exceptions (Entities & Aggregates)
# =====================================================================


class DomainError(SystemBaseException):
    """Base exception for domain aggregate business rule violations."""


# --- AccountHolder Domain Exceptions ---


class AccountHolderError(DomainError):
    """Base exception for Person and AccountHolder aggregate errors."""


class AccountHolderCardNotFoundError(AccountHolderError):
    """Raised when accessing a card not found in the holder's collection."""


class AccountHolderDuplicatedCardError(AccountHolderError):
    """Raised when adding a duplicate card to the holder."""


class InvalidBirthDateError(AccountHolderError):
    """Raised when a birth date fails domain validation rules."""


class InvalidCpfError(AccountHolderError):
    """Raised when a CPF fails mathematical or structural validation."""


class InvalidNameError(AccountHolderError):
    """Raised when a name fails domain formatting rules."""


# --- Account Domain Exceptions ---


class AccountError(DomainError):
    """Base exception for Account aggregate errors."""


class AccountAlreadyActiveError(AccountError):
    """Raised when trying to unfreeze an already active account."""


class FrozenAccountError(AccountError):
    """Raised when an operation is attempted on a frozen account entity."""


class InsufficientFundsError(AccountError):
    """Raised when a withdrawal exceeds available funds."""


class InvalidAccountError(AccountError):
    """Raised for invalid account number formatting."""


class InvalidBalanceError(AccountError):
    """Raised for invalid balance values."""


class InvalidBranchError(AccountError):
    """Raised for invalid branch code formatting."""


class NotEmptyAccountError(AccountError):
    """Raised when attempting to close an account with a non-zero balance."""


# =====================================================================
# Presentation / Controller Layer Exceptions
# =====================================================================


class ControllerError(SystemBaseException):
    """Base exception for presentation flow and navigation errors."""


class ControllerCredentialsError(ControllerError):
    """Raised when credentials flow fails at presentation level."""


class ControllerOperationError(ControllerError):
    """Raised when a presentation workflow is interrupted."""


class ControllerRegisterError(ControllerError):
    """Raised when onboarding UI presentation flow fails."""


# =====================================================================
# Error Metadata Mappers
# =====================================================================

APPLICATION_ERROR_MAP = {
    AccessDeniedError: "access_denied",
    AccountHolderNotFoundError: "not_account_holder",
    AccountNotFoundError: "acc_not_found",
    AuthenticationError: "auth_failed",
    DuplicatedAccountError: "acc_duplicated",
    DuplicatedAccountHolderError: "already_account_holder",
    NotEmptyAccountError: "non_zero_value",
    PasswordValidationError: "password",
    ServiceUnavailableError: "unavailable",
}

CONTROLLER_ERROR_MAP = {
    ControllerCredentialsError: "ctrl_credentials",
    ControllerOperationError: "ctrl_operation",
    ControllerRegisterError: "ctrl_register",
}

DOMAIN_ERROR_MAP = {
    AccountAlreadyActiveError: "acc_active",
    AccountHolderCardNotFoundError: "card_not_found",
    AccountHolderDuplicatedCardError: "duplicated_card",
    FrozenAccountError: "acc_frozen",
    InsufficientFundsError: "value",
    InvalidAccountError: "account_num",
    InvalidBalanceError: "balance",
    InvalidBirthDateError: "birth_date",
    InvalidBranchError: "branch_code",
    InvalidCpfError: "cpf",
    InvalidNameError: "name",
}

SECURITY_ERROR_MAP = {
    ExpiredTokenError: "exp_token",
    TokenSecurityError: "bank_security",
}


def map_exceptions(
    error: ApplicationError | ControllerError | DomainError | SecurityError,
) -> str:
    """Maps system exceptions to standardized UI context keys."""
    if not isinstance(
        error, (ApplicationError, ControllerError, DomainError, SecurityError)
    ):
        raise TypeError(
            f"Function expects ApplicationError, DomainError, ControllerError, or SecurityError. "
            f"Got {type(error).__name__}"
        )

    match error:
        case ApplicationError():
            context_map = APPLICATION_ERROR_MAP
        case ControllerError():
            context_map = CONTROLLER_ERROR_MAP
        case DomainError():
            context_map = DOMAIN_ERROR_MAP
        case SecurityError():
            context_map = SECURITY_ERROR_MAP
        case _:
            context_map = {}

    error_context = context_map.get(type(error))

    if error_context is None:
        raise NotImplementedError(
            f"Exception {type(error).__name__} is missing from metadata mappers"
        )

    return error_context
