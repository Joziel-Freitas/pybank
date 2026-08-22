"""Presentation Layer Types and Navigation Enumerations Module.

This module defines common enumerations used across the PyBank Terminal CLI
presentation and controller layers. It serves as a single source of truth
for UI navigation states, user decision prompts, and operation routing,
promoting type safety and eliminating magic numbers in user interface menus.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, TypedDict

from settings import ADMIN_EXIT_CODE

type InputType = str | int | float | Decimal | date
type PresentationT = InputType | MenuType

type ConfigMap = dict[str, InnerConfig[Any, Any]]


class InnerConfig[In_Type: InputType, PT: PresentationT](TypedDict):
    """Typed dictionary defining the structural schema of a configuration entry.

    Attributes:
        info (str): Short description or label for the configuration option.
        prompt (str): Text shown to the user when input is required.
        input_type (Callable[[str], In_Type]): A parser that casts raw string input
            to the intermediate primitive input type.
        validation_fn (Callable[[In_Type], PT]): Validator function or Enum parser
            responsible for enforcing domain or presentation invariants and returning
            the final strongly-typed value.
        error_msg (str): Error message displayed when input parsing or validation fails.
    """

    info: str
    prompt: str
    input_type: Callable[[str], In_Type]
    validation_fn: Callable[[In_Type], PT]
    error_msg: str


class AdminCodeType(Enum):
    """Enumeration representing hidden administrative commands for the PyBank Terminal.

    This enum does not inherit from MenuType as it is not part of the standard
    user navigation flow. It acts as an out-of-band signaling mechanism for
    system administrators or maintenance routines (e.g., safely shutting down
    the infinite Kiosk Loop).

    Attributes:
        EXIT_CODE: The secure integer code required to gracefully terminate the application.
    """

    EXIT_CODE = ADMIN_EXIT_CODE


class MenuType(Enum):
    """Base enumeration for all UI navigation menus.

    Acts as a polymorphic marker class, allowing functions in the Presentation
    and Controller layers to strictly type hint against any valid navigation
    menu (e.g., accepting MainMenuType or OperationMenuType interchangeably)
    while rejecting arbitrary integers or unrelated enums.

    Attributes:
        None: This is an abstract marker class and contains no specific options.
    """


class UserConfirmType(MenuType):
    """Enumeration representing a standard boolean-like user confirmation.

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
    """Enumeration representing the root navigation menu of the banking system.

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
    """Enumeration representing the flattened internal operations hub.

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
    """Enumeration representing the limited operation hub for blocked accounts.

    Triggered dynamically when the system detects a disabled 'is_active' flag
    in the user's AccountSummaryDTO, overriding the standard OperationMenuType.

    Attributes:
        UNFREEZE_ACCOUNT (1): The only permitted administrative action for a frozen account.
    """

    UNFREEZE_ACCOUNT = 1


class TransactionMenuType(MenuType):
    """Enumeration representing the internal mapping for transaction-specific controllers.

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


class AccountTypeMenu(MenuType):
    """Enumeration representing UI choices for account variant selection.

    Used during onboarding data collection in the CLI interface to bind
    user numerical options to explicit type identifiers before mapping to
    Application layer DTO classifiers.

    Attributes:
        CHECKING (1): Selects a standard Checking Account setup.
        SAVINGS (2): Selects an interest-bearing Savings Account setup.
    """

    CHECKING = 1
    SAVINGS = 2


class StatementPeriodType(MenuType):
    """Enumeration representing UI options for preset bank statement lookup windows.

    Encapsulates the discrete period options offered to the user in the CLI
    statement menu, allowing controllers to convert user choices into concrete
    lookup start dates.

    Attributes:
        THIRTY_DAYS (1): Requests a statement for the last 30 calendar days.
        NINETY_DAYS (2): Requests a statement for the last 90 calendar days.
        ONE_HUNDRED_EIGHTY_DAYS (3): Requests a statement for the last 180 calendar days.
    """

    THIRTY_DAYS = 1
    NINETY_DAYS = 2
    ONE_HUNDRED_EIGHTY_DAYS = 3
