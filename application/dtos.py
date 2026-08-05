"""Application Layer Data Transfer Objects (DTOs).

Defines input payload DTOs required to execute Application Use Cases and Services.
These objects carry user input, security tokens, and command criteria from the
Presentation/CLI layer into the Application orchestrators.
"""

from abc import ABC
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from shared.credentials import AccessToken, AuthToken


class ApplicationDTO(ABC):
    """Abstract base marker class for all Application Layer DTOs.

    Establishes a unified base type for command payloads, request criteria,
    and input parameters passed from Presentation controllers to Application
    Services, ensuring consistent static typing across the use case layer.
    """


@dataclass(frozen=True, slots=True)
class AccountDataDTO(ApplicationDTO):
    """Represents the identification data for a bank account.

    Encapsulates the branch code and account number pair used for search,
    lookup, and validation operations within the application layer.

    Attributes:
        branch_code (str): The identifier code for the bank branch.
        account_num (str): The unique bank account number.
    """

    branch_code: str
    account_num: str


@dataclass(frozen=True, slots=True)
class CheckDataDTO(ApplicationDTO):
    """Input DTO for checking data eligibility or prior existence.

    Used by OnboardingService (or related services) to verify the availability
    or prior existence of records before proceeding with registration or
    authentication workflows.

    Attributes:
        cpf (str | None): The holder's CPF to be verified. Optional.
        account (AccountDataDTO | None): The bank account details to be verified.
          Optional.
    """

    cpf: str | None = None
    account: AccountDataDTO | None = None


@dataclass(frozen=True, slots=True)
class NewAccountDTO(ApplicationDTO):
    """Data Transfer Object containing the validated data required to open a new Account.

    Transports user choices and onboarding information into a unified payload.
    Supports both new account holder creation and attaching a new account to an
    existing account holder.

    Attributes:
        account_type (int): Integer flag mapping to the account type (1 for Checking, 2 for Savings).
        branch_code (str): The validated 4-digit branch code.
        account_num (str): The validated 8-digit account number.
        password (str): The plain text password set by the user for vault authentication.
        holder_cpf (str): The validated 11-digit CPF string of the account holder.
        holder_name (str | None): Full name of the account holder. Required for new holders,
            None if attaching to an existing holder.
        holder_birth_date (date | None): Birth date of the account holder. Required for new holders,
            None if attaching to an existing holder.
    """

    account_type: int
    branch_code: str
    account_num: str
    password: str
    holder_cpf: str
    holder_name: str | None = None
    holder_birth_date: date | None = None


@dataclass(frozen=True, slots=True)
class VaultAccessDTO(ApplicationDTO):
    """Data Transfer Object representing credentials required for vault access authentication.

    Encapsulates the raw password and the primary authentication token required
    to request elevated authorization (vault access) for sensitive operations.

    Attributes:
        password: The plain-text password provided by the user for vault authorization.
        auth_token: The active primary authentication token confirming the user's logged-in session.
    """

    password: str
    auth_token: AuthToken


@dataclass(frozen=True, slots=True)
class DepositTargetDTO(ApplicationDTO):
    """A read-only, sanitized snapshot of an account intended exclusively
    for public deposit confirmation screens.

    Contains masked sensitive information (like CPF) to prevent data leaks
    during unauthenticated queries, adhering to Zero Trust principles.

    Attributes:
        holder_name (str): The full name of the account holder.
        holder_cpf (str): The masked 11-digit CPF string.
        branch_code (str): The target account branch code.
        account_num (str): The target account number.
        account_type (str): The semantic name of the account type.
    """

    holder_name: str
    holder_cpf: str
    branch_code: str
    account_num: str
    account_type: str


@dataclass(frozen=True, slots=True)
class DepositDTO(ApplicationDTO):
    """Command Data Transfer Object encapsulating the criteria for a deposit operation.

    Transports target account coordinates and the monetary amount from unauthenticated
    or public presentation controllers into the financial execution service.

    Attributes:
        branch_code (str): The 4-digit target branch code.
        account_num (str): The 8-digit target account number.
        amount (Decimal): The strictly positive monetary value to deposit.
    """

    branch_code: str
    account_num: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class WithdrawalDTO(ApplicationDTO):
    """Command Data Transfer Object encapsulating an authenticated withdrawal request.

    Binds a cryptographically signed AccessToken proving user authorization in the Vault
    context together with the requested monetary withdrawal amount.

    Attributes:
        access_token (AccessToken): The active, verified cryptographic token of the session.
        amount (Decimal): The strictly positive monetary value requested for withdrawal.
    """

    access_token: AccessToken
    amount: Decimal
