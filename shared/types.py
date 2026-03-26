"""
Shared Types and Enumerations Module.

This module defines common type aliases, enumerations, and constants used across
the banking system architecture. It serves as a single source of truth for
domain-specific values (like transaction types) and error context categories,
promoting type safety and reducing the usage of magic strings and numbers.
"""

from enum import IntEnum, StrEnum


class MainMenuType(IntEnum):
    """
    Enumeration representing the root navigation menu of the banking system.

    Acts as the primary router for the ATM interface (the "External Lobby"),
    separating existing clients seeking services from new users creating accounts.

    Attributes:
        OPERATIONS (1): Routes to the internal operations hub for active clients.
        ONBOARDING (2): Routes to the registration workflow for new clients or accounts.
    """

    OPERATIONS = 1
    ONBOARDING = 2


class OperationMenuType(IntEnum):
    """
    Enumeration representing the internal operations hub (Layer 2 navigation).

    Acts as the central dashboard for users entering the system, segregating
    day-to-day financial transactions from administrative and security tasks.

    Attributes:
        TRANSACTIONS (1): Routes to financial operations (Deposit, Withdraw, Statement).
        MANAGEMENT (2): Routes to account administration and security settings.
    """

    TRANSACTIONS = 1
    MANAGEMENT = 2


class TransactionType(IntEnum):
    """
    Enumeration representing the supported types of financial transactions.

    Attributes:
        DEPOSIT (1): Represents a money deposit operation.
        WITHDRAW (2): Represents a money withdrawal operation.
        STATEMENT (3): Represents a bank statement inquiry.
    """

    DEPOSIT = 1
    WITHDRAW = 2
    STATEMENT = 3


class ManagementType(IntEnum):
    """
    Enumeration representing the account administration and security operations.

    Unlike 'TransactionType', which handles monetary flow, this enum controls
    the lifecycle and access parameters of an existing account.

    Attributes:
        PASSWORD (1): Triggers the secure workflow to change the account password.
        UNFREEZE (2): Triggers the administrative process to reactivate a frozen account.
        CLOSE (3): Triggers the irreversible process of closing the user's bank account
                   and removing their data (subject to business rules like zero balance).
    """

    PASSWORD = 1
    UNFREEZE = 2
    CLOSE = 3


class ErrorContext(StrEnum):
    """
    Base enumeration for error mapping contexts.

    Inherits from StrEnum to ensure all members are treated as native strings,
    allowing direct comparison and usage in string-based logic (e.g., dictionary lookups)
    while maintaining the benefits of strict enumeration.
    """

    pass


class ControllerErrorContext(ErrorContext):
    """
    Defines high-level error contexts for the Bank System Controller workflow.

    Used to categorize errors during the main application lifecycle, allowing
    the orchestrator to distinguish between failures in entity creation (onboarding),
    session establishment (login), and service execution (operations).

    Attributes:
        REGISTER: Context for failures during client or account creation/registration.
        LOGIN: Context for authentication failures or session initialization issues.
        OPERATION: Context for failures during the execution of banking services (Transaction, Unfreeze, Close).
    """

    REGISTER = "register"
    LOGIN = "login"
    OPERATION = "operation"


class PersonContext(ErrorContext):
    """
    Defines error contexts for method-level failures in the Person/Client entity.

    Attributes:
        ACCOUNT: Context for errors involving account associations or validation within a Person.
    """

    ACCOUNT = "account"


class AccountContext(ErrorContext):
    """
    Defines error contexts for method-level failures in the Account entity.

    Attributes:
        VALUE: Context for invalid monetary values (e.g., negative deposit, insufficient funds).
        BLOCKED: Context for operations rejected due to the account being frozen or inactive.
    """

    VALUE = "value"
    BLOCKED = "blocked"


class BankContext(ErrorContext):
    """
    Defines error contexts for method-level failures in the Bank service layer.

    Attributes:
        PASSWORD: Context for password validation or authentication errors.
        CLIENT: Context for errors related to Client entity management (e.g., duplication).
        ACCOUNT: Context for errors related to Account entity management (e.g., aggregation).
        TOKEN: Context for security token validation failures or session integrity issues.
    """

    PASSWORD = "password"
    CLIENT = "client"
    ACCOUNT = "account"
    TOKEN = "token"
