"""Central module for all custom exceptions in the PyBank system.

Establishes a clear, hierarchical structure for all custom errors across layers:

1. Domain Errors: Business rule invariant violations within Aggregate Roots and Value Objects.
2. Application Errors: Workflow orchestration, authentication, and security boundary failures.
3. Infrastructure Errors: Persistence, database, and technical token mechanics failures.
4. Presentation Errors: UI navigation, controller workflows, and terminal I/O interrupts.
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
# Domain Layer Exceptions (Value Objects & Invariants)
# =====================================================================


class DomainError(SystemBaseException):
    """Base exception for domain aggregate and Value Object business rule violations."""


# --- Account Aggregate Exceptions ---


class AccountError(DomainError):
    """Base exception for Account aggregate operational state errors."""


class AccountStateTransitionError(AccountError):
    """Raised when an invalid state transition is attempted on an account entity."""


class FrozenAccountError(AccountError):
    """Raised when an operation is attempted on a frozen account entity."""


class InsufficientFundsError(AccountError):
    """Raised when a withdrawal exceeds available funds."""


class NotEmptyAccountError(AccountError):
    """Raised when attempting to close an account with a non-zero balance."""


# --- AccountHolder Aggregate Exceptions ---


class AccountHolderError(DomainError):
    """Base exception for AccountHolder aggregate state errors."""


class AccountHolderCardNotFoundError(AccountHolderError):
    """Raised when accessing a card not found in the holder's collection."""


class AccountHolderDuplicatedCardError(AccountHolderError):
    """Raised when adding a duplicate card to the holder's collection."""


# --- Value Objects & Primitives Exceptions ---


class DomainVOError(DomainError):
    """Base exception for all Value Object and Primitive invariant violations."""


class InvalidAccountError(DomainVOError):
    """Raised when an account number fails format or length domain validation."""


class InvalidAmountError(DomainVOError):
    """Raised when a monetary transaction amount is below institutional minimum limits."""


class InvalidBirthDateError(DomainVOError):
    """Raised when a birth date fails domain boundary or age validation rules."""


class InvalidBranchError(DomainVOError):
    """Raised when a branch code fails format or length domain validation."""


class InvalidCpfError(DomainVOError):
    """Raised when a CPF fails mathematical checksum or structural validation."""


class InvalidNameError(DomainVOError):
    """Raised when an account holder name fails domain formatting rules."""


class InvalidPasswordError(DomainVOError):
    """Raised when a password fails domain formatting rules (e.g., 6 numeric digits)."""


# =====================================================================
# Application Layer Exceptions (Services & Security)
# =====================================================================


class ApplicationError(SystemBaseException):
    """Base exception for all Application Layer failures."""


# --- Application Service / Workflow Exceptions ---


class ApplicationServiceError(ApplicationError):
    """Base exception for recoverable application service and workflow failures."""


class AccessDeniedError(ApplicationServiceError):
    """Raised when vault or feature access is denied (e.g., frozen account)."""


class AccountAlreadyActiveError(ApplicationServiceError):
    """Raised when trying to unfreeze an already active account."""


class AccountHolderNotFoundError(ApplicationServiceError):
    """Raised when an account holder record cannot be resolved by the application service."""


class AccountNotFoundError(ApplicationServiceError):
    """Raised when an account record cannot be resolved by the application service."""


class AuthenticationError(ApplicationServiceError):
    """Raised when primary or vault authentication credentials fail."""


class DeniedOperationError(ApplicationServiceError):
    """Raised when a business operation requested by presentation is rejected by application policy."""


class DuplicatedAccountError(ApplicationServiceError):
    """Raised during onboarding if an account already exists."""


class DuplicatedAccountHolderError(ApplicationServiceError):
    """Raised during onboarding if an account holder is already registered."""


class InvalidDataError(ApplicationServiceError):
    """Raised when an application payload (DTO) or field input fails contract/domain validation."""


class ServiceUnavailableError(ApplicationServiceError):
    """Raised when an application workflow cannot commit state due to internal failure."""


# --- Application Security Exceptions ---


class ApplicationSecurityError(ApplicationError):
    """Base exception for session security breaches (invalid/expired tokens). Drops user session."""


class ExpiredSessionError(ApplicationSecurityError):
    """Raised when an application session token has expired."""


class SessionIntegrityError(ApplicationSecurityError):
    """Raised when a session token fails cryptographic or integrity verification."""


# =====================================================================
# Infrastructure Layer Exceptions
# =====================================================================


class InfrastructureError(SystemBaseException):
    """Base exception for all lower-level infrastructure and persistence failures."""


# --- Repository / Persistence Exceptions ---


class RepositoryError(InfrastructureError):
    """Base exception for all persistence layer errors."""


class DataNotFoundError(RepositoryError):
    """Raised when a requested record is not found in persistence."""


class DuplicatedDataError(RepositoryError):
    """Raised when an insertion violates a unique constraint."""


# --- Token Service Technical Exceptions ---


class TokenServiceError(InfrastructureError):
    """Base exception for low-level cryptographic token calculation failures."""


class ExpiredTokenError(TokenServiceError):
    """Raised when current timestamp exceeds a token's TTL."""


class TokenSignatureError(TokenServiceError):
    """Raised when HMAC signature comparison fails during token verification."""


# =====================================================================
# Presentation / Controller Layer Exceptions
# =====================================================================


class PresentationError(SystemBaseException):
    """Base exception for presentation flow, navigation, and terminal I/O errors."""


# --- Controller Navigation Exceptions ---


class ControllerError(PresentationError):
    """Base exception for presentation flow and navigation errors."""


class ControllerCredentialsError(ControllerError):
    """Raised when credentials flow fails at presentation level."""


class ControllerOperationError(ControllerError):
    """Raised when a presentation workflow is interrupted."""


class ControllerRegisterError(ControllerError):
    """Raised when onboarding UI presentation flow fails."""


# --- Terminal I/O & Interrupt Exceptions ---


class SystemIOError(PresentationError):
    """Base exception for terminal input/output and session lifecycle interrupts."""


class AdminExitError(SystemIOError):
    """Raised when an administrator exit code is issued in terminal prompts."""


class InactiveUserError(SystemIOError):
    """Raised when user inactivity reaches the system timeout limit."""


class UserAbortError(SystemIOError):
    """Raised when the user manually cancels an operation in terminal prompts."""


# =====================================================================
# Error Metadata Mappers
# =====================================================================

APPLICATION_SERVICE_ERROR_MAP = {
    AccessDeniedError: "access_denied",
    AccountAlreadyActiveError: "acc_not_frozen",
    AccountHolderNotFoundError: "not_account_holder",
    AccountNotFoundError: "acc_not_found",
    AuthenticationError: "auth_failed",
    DeniedOperationError: "denied_operation",
    DuplicatedAccountError: "acc_duplicated",
    DuplicatedAccountHolderError: "already_account_holder",
    InvalidDataError: "invalid_data",
    ServiceUnavailableError: "unavailable",
}

APPLICATION_SECURITY_ERROR_MAP = {
    ExpiredSessionError: "exp_session",
    SessionIntegrityError: "integrity_fail",
}

CONTROLLER_ERROR_MAP = {
    ControllerCredentialsError: "ctrl_credentials",
    ControllerOperationError: "ctrl_operation",
    ControllerRegisterError: "ctrl_register",
}


def map_exceptions(
    error: ApplicationError | ControllerError,
) -> str:
    """Maps system exceptions to standardized UI context keys.

    Args:
        error (ApplicationError | ControllerError): The exception instance raised by
            application services or controller workflows.

    Returns:
        str: The corresponding UI context lookup key.

    Raises:
        TypeError: If error is not an instance of ApplicationError or ControllerError.
        NotImplementedError: If an exception class is not mapped in the metadata dictionaries.
    """
    if not isinstance(error, (ApplicationError, ControllerError)):
        raise TypeError(
            f"Function expects ApplicationError or ControllerError. Got {type(error).__name__}"
        )

    match error:
        case ApplicationServiceError():
            context_map = APPLICATION_SERVICE_ERROR_MAP
        case ApplicationSecurityError():
            context_map = APPLICATION_SECURITY_ERROR_MAP
        case ControllerError():
            context_map = CONTROLLER_ERROR_MAP
        case _:
            context_map = {}

    error_context = context_map.get(type(error))

    if error_context is None:
        raise NotImplementedError(
            f"Exception {type(error).__name__} is missing from metadata mappers"
        )

    return error_context
