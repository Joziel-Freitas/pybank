"""
Shared Types and Enumerations Module.

This module defines common enumerations used across the banking system's
presentation and controller layers. It serves as a single source of truth
for UI navigation states and operation routing, promoting type safety and
eliminating the use of magic numbers in the user interface menus.
"""

from enum import Enum, StrEnum

from settings import ADMIN_EXIT_CODE


class AdminCodeType(Enum):
    """
    Enumeration representing hidden administrative commands for the PyBank Terminal.

    This enum does not inherit from MenuType as it is not part of the standard
    user navigation flow. It acts as an out-of-band signaling mechanism for
    system administrators or maintenance routines (e.g., safely shutting down
    the infinite Kiosk Loop).

    Attributes:
        EXIT_CODE: The secure integer code required to gracefully terminate the application.
    """

    EXIT_CODE = ADMIN_EXIT_CODE


class MenuType(Enum):
    """
    Base enumeration for all UI navigation menus.

    Acts as a polymorphic marker class, allowing functions in the Presentation
    and Controller layers to strictly type hint against any valid navigation
    menu (e.g., accepting MainMenuType or OperationMenuType interchangeably)
    while rejecting arbitrary integers or unrelated enums.

    Attributes:
        None: This is an abstract marker class and contains no specific options.
    """


class FinancialType(StrEnum):
    """
    Base enumeration for all domain-level financial event classifiers.

    Acts as a polymorphic marker class for enumerations that represent
    immutable, historical financial events (such as transactions or accruals).
    Ensures that event labels persisted in the database or transported via DTOs
    belong to a strictly defined set of business categories.

    Attributes:
        None: This is an abstract marker class and contains no specific options.
    """


class UserConfirmType(MenuType):
    """
    Enumeration representing a standard boolean-like user confirmation.

    Used across the system to formalize binary decisions (Yes/No) submitted
    by the user, replacing magic numbers with explicit, typed identifiers.
    Commonly applied in critical workflow checkpoints, such as verifying
    target deposit information or accepting overdraft usage.

    Attributes:
        YES (1): Represents an affirmative user confirmation to proceed.
        NO (2): Represents a negative response, typically leading to an abort
            or fallback action.
    """

    YES = 1
    NO = 2


class MainMenuType(MenuType):
    """
    Enumeration representing the root navigation menu of the banking system.

    Acts as the primary router for the ATM interface (the "External Lobby").
    Adhering to the 'Identity-First' paradigm, it exposes only public or
    non-authenticated operations at the root level, requiring explicit identity
    resolution (authentication) for all other account-specific actions.

    Attributes:
        DEPOSIT (1): Routes to the public deposit operation (requires only target account info).
        ONBOARDING (2): Routes to the registration workflow for new clients or accounts.
        OPERATIONS (3): Routes to the internal operations hub, triggering the authentication workflow.
    """

    DEPOSIT = 1
    ONBOARDING = 2
    OPERATIONS = 3


class OperationMenuType(MenuType):
    """
    Enumeration representing the flattened internal operations hub.

    Acts as the main dashboard for users with a valid identity token, displaying
    all permitted financial and administrative actions in a single view.

    Attributes:
        DEPOSIT (1): Routes to a logged-in money deposit operation.
        WITHDRAWAL (2): Routes to a money withdrawal operation.
        STATEMENT (3): Routes to a bank statement inquiry.
        CHANGE_PASSWORD (4): Triggers the secure workflow to change the account password.
        CLOSE_ACCOUNT (5): Triggers the irreversible process of closing the bank account.
    """

    DEPOSIT = 1
    WITHDRAWAL = 2
    STATEMENT = 3
    CHANGE_PASSWORD = 4
    CLOSE_ACCOUNT = 5


class RestrictedMenuType(MenuType):
    """
    Enumeration representing the limited operation hub for blocked accounts.

    Triggered dynamically when the system detects a disabled 'is_active' flag
    in the user's AccountSummaryDTO, overriding the standard OperationMenuType.

    Attributes:
        UNFREEZE_ACCOUNT (1): The only permitted administrative action for a frozen account.
    """

    UNFREEZE_ACCOUNT = 1


class TransactionMenuType(MenuType):
    """
    Enumeration representing the internal mapping for transaction-specific controllers.

    Used by the MainController to bridge the flattened UI selection (OperationMenuType)
    into the localized TransactionController context.

    Attributes:
        DEPOSIT (1): Flags the controller to execute the deposit workflow.
        WITHDRAWAL (2): Flags the controller to execute the withdrawal workflow.
        STATEMENT (3): Flags the controller to execute the statement retrieval workflow.
    """

    DEPOSIT = 1
    WITHDRAWAL = 2
    STATEMENT = 3


class TransactionType(FinancialType):
    """
    Value Object representing the semantic business event of a financial operation.

    Unlike 'TransactionMenuType' (which routes UI logic), this enumeration acts
    as the official ledger entry type, ensuring the database records the exact
    nature of the movement (e.g., distinguishing a standard withdrawal from
    an overdraft usage).

    Attributes:
        DEPOSIT: Represents funds added to the account.
        WITHDRAWAL: Represents funds removed using standard positive balance.
        CREDIT_WITHDRAWAL: Represents funds removed utilizing the account's credit limit.
    """

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    CREDIT_WITHDRAWAL = "CREDIT_WITHDRAWAL"


class AccrualType(FinancialType):
    """
    Value Object representing the semantic classification of a time-based financial adjustment.

    Categorizes the automatic mathematical operations applied to an account
    based on the passage of time, distinguishing between positive remuneration
    and negative debt charges.

    Attributes:
        YIELD: Represents positive earnings applied to a positive balance (e.g., Savings interest).
        INTEREST: Represents negative charges applied to a utilized credit limit (e.g., Overdraft fees).
    """

    YIELD = "YIELD"
    INTEREST = "INTEREST"
