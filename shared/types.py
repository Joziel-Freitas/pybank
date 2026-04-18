"""
Shared Types and Enumerations Module.

This module defines common enumerations used across the banking system's
presentation and controller layers. It serves as a single source of truth
for UI navigation states and operation routing, promoting type safety and
eliminating the use of magic numbers in the user interface menus.
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
    Base enumeration for generic error context payloads.

    Inherits from StrEnum to guarantee that all members are natively treated
    as strings. This allows seamless instantiation from exception arguments
    (e.g., `ErrorContext(str(e))`) and ensures type safety while eliminating
    the fragility of magic strings across the system.
    """


class BankContext(ErrorContext):
    """
    Defines standardized context identifiers for Bank-related data collisions or misses.

    Acts as a strict contractual vocabulary to identify which specific entity
    was involved in an error event, replacing arbitrary string matching.

    Attributes:
        CLIENT: Context representing the Client entity (e.g., for duplication or not-found events).
        ACCOUNT: Context representing the Account entity.
    """

    CLIENT = "client"
    ACCOUNT = "account"
