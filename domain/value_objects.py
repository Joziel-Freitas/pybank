"""Domain Value Objects Module.

Defines immutable Value Objects that encapsulate monetary calculations, projected outputs,
atomic ledger event definitions, and domain-validated primitive types (CPF, BranchCode,
AccountNumber, Name, BirthDate, Password, Money) within the core PyBank domain.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar

from domain.types import AccrualType, FinancialType
from shared import clock, validators, verify
from shared.exceptions import (
    InvalidAccountError,
    InvalidAmountError,
    InvalidBirthDateError,
    InvalidBranchError,
    InvalidCpfError,
    InvalidNameError,
    InvalidPasswordError,
)

# =====================================================================
# Domain Primitive Value Objects (Auto-validating)
# =====================================================================
type ValueTypes = str | Decimal | date


class DomainVO[ValueT: ValueTypes](ABC):
    """Abstract Base Class for all Domain Value Objects.

    Establishes the mandatory 'value' attribute contract and forces
    concrete subclasses to implement internal invariant verification.
    """

    value: ValueT

    def __init__(self, value: ValueT) -> None:
        self.value = value

    @abstractmethod
    def __post_init__(self) -> None:
        """Abstract hook called immediately after instantiation.

        Subclasses MUST override this method to enforce type verification
        and domain invariants.
        """


@dataclass(frozen=True, slots=True)
class BranchCode(DomainVO[str]):
    """Value Object representing a validated 4-digit bank branch code.

    Attributes:
        value (str): The raw 4-digit string representing the bank branch code.

    Raises:
        InvalidBranchError: If the branch code is not exactly 4 numeric digits.
    """

    value: str

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, str)
        try:
            verify.verify_digits(self.value, 4)
        except ValueError as e:
            raise InvalidBranchError(f"Invalid branch code '{self.value}': {e}") from e

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AccountNumber(DomainVO[str]):
    """Value Object representing a validated 8-digit bank account number.

    Attributes:
        value (str): The raw 8-digit string representing the unique account number.

    Raises:
        InvalidAccountError: If the account number is not exactly 8 numeric digits.
    """

    value: str

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, str)
        try:
            verify.verify_digits(self.value, 8)
        except ValueError as e:
            raise InvalidAccountError(
                f"Invalid account number '{self.value}': {e}"
            ) from e

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CPF(DomainVO[str]):
    """Value Object representing a mathematically verified 11-digit CPF.

    Attributes:
        value (str): The sanitized 11-digit numeric string representing the CPF.

    Raises:
        InvalidCpfError: If the CPF fails formatting rules or mathematical checksum validation.
    """

    value: str

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, str)
        try:
            validators.validate_cpf(self.value)
        except ValueError as e:
            raise InvalidCpfError(f"Invalid CPF format or checksum: {e}") from e

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AccountHolderName(DomainVO[str]):
    """Value Object representing a validated account holder full name.

    Attributes:
        value (str): The string representing the holder's full legal name.

    Raises:
        InvalidNameError: If the name contains less than 3 letters or contains numbers/special characters.
    """

    value: str

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, str)

        if len(self.value) < 3:
            raise InvalidNameError(
                f"Value '{self.value}' must have at least three letters"
            )

        pattern = r"^[A-Za-zÀ-ÿ]+(?: [A-Za-zÀ-ÿ]+)*$"
        if not re.match(pattern, self.value):
            raise InvalidNameError(
                f"Value '{self.value}' is invalid. Use only letters and single spaces."
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BirthDate(DomainVO[date]):
    """Value Object representing a validated birth date enforcing institutional age limits.

    Attributes:
        MIN_AGE (ClassVar[int]): Minimum allowed operational age (18 years).
        MAX_AGE (ClassVar[int]): Maximum allowed operational age (120 years).
        value (date): The native date object representing the account holder's birth date.

    Raises:
        InvalidBirthDateError: If the date is in the future or calculated age falls outside [18, 120].
    """

    MIN_AGE: ClassVar[int] = 18
    MAX_AGE: ClassVar[int] = 120

    value: date

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, date)
        today = clock.get_today()

        if self.value > today:
            raise InvalidBirthDateError("Date of birth cannot be in the future.")

        age = (
            today.year
            - self.value.year
            - ((today.month, today.day) < (self.value.month, self.value.day))
        )

        if not self.MIN_AGE <= age <= self.MAX_AGE:
            raise InvalidBirthDateError(
                f"Invalid age ({age}). Must be between {self.MIN_AGE} and {self.MAX_AGE}."
            )

    def __str__(self) -> str:
        return self.value.strftime("%d/%m/%Y")


@dataclass(frozen=True, slots=True)
class Password(DomainVO[str]):
    """Value Object representing a validated 6-digit numeric account password.

    Attributes:
        value (str): The raw 6-digit string representing the password.

    Raises:
        InvalidPasswordError: If the password is not composed of exactly 6 numeric digits.
    """

    value: str

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, str)

        if not (len(self.value) == 6 and self.value.isdigit()):
            raise InvalidPasswordError(
                "Password must consist of exactly 6 numeric digits."
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Money(DomainVO[Decimal]):
    """Value Object representing an atomic validated monetary entry amount.

    Attributes:
        MIN_ATM_TRANSACTION (ClassVar[Decimal]): The minimum allowed ATM transaction value (R$ 2.00).
        value (Decimal): The monetary amount represented as a precise Decimal.

    Raises:
        InvalidAmountError: If the amount is below the minimum institutional threshold.
    """

    MIN_ATM_TRANSACTION: ClassVar[Decimal] = Decimal("2.00")

    value: Decimal

    def __post_init__(self) -> None:
        verify.verify_instance(self.value, Decimal)

        if self.value < self.MIN_ATM_TRANSACTION:
            raise InvalidAmountError(
                f"Transaction amount '{self.value}' is below minimum required '{self.MIN_ATM_TRANSACTION}'."
            )

    def __str__(self) -> str:
        return f"R$ {self.value:.2f}"


# =====================================================================
# Financial & Ledger Value Objects (Existing Domain Contracts)
# =====================================================================


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """Value Object representing a discrete event bound for the accounting ledger.

    Designed to decompose complex account operations (such as a withdrawal
    that crosses into overdraft limits, or a deposit that triggers pending
    yield materialization) into immutable, atomic segments. This ensures
    accurate ledger tracking and precise auditing without exposing internal
    entity mechanics.

    Attributes:
        previous_balance (Decimal): The exact account balance immediately
            prior to the execution of this specific event segment.
        amount (Decimal): The specific monetary amount associated with this
            discrete segment of the operation. Negative values represent
            debits, while positive values represent credits.
        event_type (FinancialType): The semantic label categorizing the exact
            business nature of the event.
    """

    previous_balance: Decimal
    amount: Decimal
    event_type: FinancialType


@dataclass(frozen=True, slots=True)
class WithdrawalSimulation:
    """Value Object representing the projected outcome of a withdrawal evaluation.

    Utilized by domain aggregates and application use cases to safely evaluate
    the financial and operational impact of a withdrawal before committing to state
    mutation. It provides the necessary data to evaluate whether credit limits are required.

    Attributes:
        authorized (bool): Indicates if the operation is mathematically and operationally
            possible (e.g., account is active and the requested amount does not exceed
            the total available funds).
        use_credit (bool | None): True if the requested amount exceeds the standard positive
            balance, requiring the use of the account's credit limit. False if the limit
            exists but won't be used. None if the account type does not support credit.
        credit_required (Decimal | None): The exact monetary value that will be drawn from
            the credit limit if the transaction proceeds. Expected to be Decimal("0.00")
            if `use_credit` is False, or None if credit is unsupported.
    """

    authorized: bool
    use_credit: bool | None
    credit_required: Decimal | None


@dataclass(frozen=True, slots=True)
class AccountFinancial:
    """Value Object representing the absolute financial state of an Account.

    Acts as a highly cohesive, composable payload containing all calculated monetary
    metrics. By separating the historical ledger state ('ledger_balance') from the
    temporally accurate current state ('balance') and the total purchasing power
    ('available_balance'), it captures a precise and unambiguous financial snapshot
    at a specific timestamp ('issue_at').

    Attributes:
        ledger_balance (Decimal): The historical, unadjusted balance retrieved directly
            from the accounting records.
        accrual (Decimal): The specific monetary value of any pending time-based adjustment.
            Evaluates to Decimal("0.00") if no adjustment is pending.
        balance (Decimal): The true, real-time adjusted current balance, fully evaluated
            by the account's specific business rules.
        accrual_type (AccrualType | None): The semantic label of the adjustment
            (e.g., YIELD or INTEREST). Strictly None if the accrual is exactly zero.
        credit_limit (Decimal | None): The maximum credit limit, or None if not supported.
        available_credit (Decimal | None): The currently available credit amount, or None.
        available_balance (Decimal): The true total purchasing power, factoring in the
            adjusted balance and any available credit lines.
        issue_at (date): The exact temporal anchor validating the accuracy of this snapshot.
    """

    ledger_balance: Decimal
    accrual: Decimal
    balance: Decimal
    accrual_type: AccrualType | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    available_balance: Decimal
    issue_at: date
