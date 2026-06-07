"""
Account Management Module.

Defines the abstract base class Account and its concrete implementations:
SavingsAccount and CheckingAccount. This module handles account initialization,
attribute validation, and core banking mathematical operations (deposit and withdraw).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, cast

from infra import verify
from shared.dtos import TransactionEventDTO, WithdrawalSimulationDTO
from shared.exceptions import (
    FrozenAccountError,
    InsufficientFundsError,
    InvalidAccountError,
    InvalidBranchError,
)
from shared.types import TransactionType


class Account(ABC):
    """
    Abstract Base Class (ABC) for all bank accounts.

    Enforces mandatory attributes and mathematical behaviors (deposit, withdraw)
    across all concrete account types. Handles initial attribute validation
    via static methods.

    Attributes:
        _branch_code (str): The validated branch code.
        _account_num (str): The validated account number.
        _balance (Decimal): The current account balance.
    """

    MIN_ATM_TRANSACTION: ClassVar[Decimal] = Decimal(2.00)

    # Type hints for the instance's variables
    _branch_code: str
    _account_num: str
    _balance: Decimal
    _is_frozen: bool

    def __init__(self, branch_code: str, account_num: str):
        """
        Initializes a new Account instance with validated attributes.

        Args:
            branch_code (str): The code of the bank branch (validated for format).
            account_num (str): The unique account number (validated for format).

        Raises:
            InvalidBranchError: If `branch_code` fails validation.
            InvalidAccountError: If `account_num` fails validation.
        """
        self._branch_code = Account.validate_branch_code(branch_code)
        self._account_num = Account.validate_account_number(account_num)
        self._balance = Decimal("0.00")
        self._is_frozen = False

    def __repr__(self) -> str:
        """Returns the canonical string representation of the Account instance."""
        class_name = type(self).__name__

        return (
            f"{class_name}("
            f"account_num={self._account_num!r}, balance={self._balance!r})"
        )

    def __eq__(self, other: object) -> bool:
        """
        Determines equality between Account instances based on branch code and account number.

        Two Account objects are considered equal if they share the same branch code
        and account number, regardless of other attributes. This definition of equality
        is consistent with the __hash__ method, ensuring reliable behavior when Account
        objects are stored in hash-based collections such as sets or used as dictionary keys.
        """

        if isinstance(other, Account):
            return (self._branch_code, self._account_num) == (
                other._branch_code,
                other._account_num,
            )
        return False

    def __hash__(self):
        """
        Returns a hash value for the Account instance based on its branch code and account number.

        This ensures that Account objects can be used reliably as keys in dictionaries
        or stored in sets. The hash is consistent with the __eq__ method, which also
        defines equality by branch code and account number, guaranteeing that two Account
        instances with the same identifiers are treated as identical in hash-based collections.
        """

        return hash((self._branch_code, self._account_num))

    @property
    def branch_code(self) -> str:
        """Returns the branch code of the account."""
        return self._branch_code

    @property
    def account_num(self) -> str:
        """Returns the account number."""
        return self._account_num

    @property
    def balance(self) -> Decimal:
        """Returns the current balance of the account."""
        return self._balance

    @property
    def is_frozen(self) -> bool:
        """Returns the current status of the account"""
        return self._is_frozen

    @abstractmethod
    def simulate_withdrawal(self, amount: Decimal) -> WithdrawalSimulationDTO:
        """
        Simulates the financial projection of a withdrawal without mutating state.

        This method acts as a financial oracle, calculating the viability of a
        transaction strictly based on the available funds and specific credit rules
        of the concrete account type. It assumes the orchestrating layer has already
        validated external conditions (e.g., account frozen status) and basic
        input rules (e.g., minimum ATM transaction values).

        Args:
            amount (Decimal): The intended monetary amount to be withdrawn.

        Returns:
            WithdrawalSimulationDTO: A Data Transfer Object detailing the projected
                authorization status based on funds, the necessity of an overdraft,
                and the exact overdraft amount required.
        """
        raise NotImplementedError

    @abstractmethod
    def withdrawal(self, amount: Decimal) -> tuple[TransactionEventDTO, ...]:
        """
        Abstract method for withdrawing an amount from the account.

        Concrete implementations handle specific withdrawal logic, such as
        checking available limits or minimum balances, and returning the
        appropriate business event type.

        Args:
            amount (Decimal): The amount to withdraw.

        Returns:
            TransactionType: A Value Object representing the semantic nature of the withdrawal.
        """
        raise NotImplementedError()

    @staticmethod
    def validate_branch_code(code: str) -> str:
        """
        Validates the format and length of the branch code.

        The branch code must be a string of exactly 4 numeric characters.

        Args:
            code (str): The branch code string to validate.

        Returns:
            str: The validated branch code.

        Raises:
            TypeError: If the branch code is not a string (indicates a system type bug).
            InvalidBranchError: If the branch code contains non-numeric characters or is not of length 4.
        """
        verify.verify_instance(code, str)
        try:
            verify.verify_digits(code, 4)
            return code
        except ValueError as e:
            raise InvalidBranchError(f"Invalid branch code. Cause: {e}") from e

    @staticmethod
    def validate_account_number(acc_num: str) -> str:
        """
        Validates the format and length of the account number.

        The account number must be a string of exactly 8 numeric characters.

        Args:
            acc_num (str): The account number string to validate.

        Returns:
            str: The validated account number.

        Raises:
            TypeError: If the account number is not a string (indicates a system type bug).
            InvalidAccountError: If the account number contains non-numeric characters or is not of length 8.
        """
        verify.verify_instance(acc_num, str)
        try:
            verify.verify_digits(acc_num, 8)
            return acc_num
        except ValueError as e:
            raise InvalidAccountError(f"Invalid account number. Cause: {e}") from e

    @staticmethod
    def validate_amount_entry(amount: Decimal) -> None:
        """
        Validates the basic structural and monetary rules for a financial entry.

        Acts as a strict fail-fast mechanism for incoming transactions (such as
        deposits or withdrawals). It ensures the input is strictly of the correct
        type and meets the institution's minimum operational threshold, preventing
        invalid or zero/negative values from reaching the domain logic.

        Args:
            amount (Decimal): The monetary amount to be evaluated.

        Raises:
            TypeError: If the provided amount is not an instance of Decimal.
            ValueError: If the amount is less than the MIN_ATM_TRANSACTION limit.
        """
        verify.verify_instance(amount, Decimal)
        verify.verify_interval(target_value=amount, min_val=Account.MIN_ATM_TRANSACTION)

    @staticmethod
    def _validate_account_withdrawal(val: Decimal, available_val: Decimal) -> None:
        """
        Validates a withdrawal request strictly against the account's available funds.

        This method enforces the core business rule that an account cannot disburse
        more money than its total available capacity (balance plus any applicable credit
        limits). It assumes that basic structural validation (like type checks and
        minimum withdrawal limits) has already been handled by `validate_amount_entry`.

        Args:
            val (Decimal): The intended monetary amount to be withdrawn.
            available_val (Decimal): The maximum total funds currently available to the account.

        Raises:
            InsufficientFundsError: If the requested amount exceeds the total available funds.
        """
        if val > available_val:
            raise InsufficientFundsError(
                "The given amount exceeds the account's available funds"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Serializes the account state into a dictionary.

        Includes a 'type' field (e.g., 'CheckingAccount') to allow the Factory method
        to reconstruct the correct concrete class implementation upon deserialization.

        Returns:
            dict[str, Any]: The dictionary containing account number, balance,
                            and class type.
        """
        return {
            "branch_code": self._branch_code,
            "account_num": self._account_num,
            "balance": self._balance,
            "is_frozen": self._is_frozen,
            "type": type(self).__name__,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Account:
        """
        Factory method to reconstruct an Account instance (or subclass) from a dictionary.

        Implements a Dispatcher Pattern:
        1. If called on the base Account class, it inspects the 'type' field in the data
           and delegates instantiation to the correct subclass (Checking or Savings).
        2. If called on (or dispatched to) a subclass, it restores the common attributes
           (balance) and returns the hydrated instance.

        Args:
            data (dict[str, Any]): The dictionary containing raw account data.

        Returns:
            Account: A fully initialized instance of the specific Account subclass.

        Raises:
            ValueError: If the 'type' field in the data is unknown or missing.
        """
        if cls is Account:
            obj_type = data.get("type")

            if obj_type:
                account_types = {
                    "CheckingAccount": CheckingAccount,
                    "SavingsAccount": SavingsAccount,
                }

                target_class = account_types.get(obj_type)

                if target_class:
                    return target_class.from_dict(data)

            raise ValueError(f"Unknown account type: {obj_type}")

        instance = cls(
            branch_code=data["branch_code"],
            account_num=data["account_num"],
        )
        instance._balance = data["balance"]
        instance._is_frozen = data["is_frozen"]
        return instance

    def freeze(self) -> None:
        """
        Transitions the account into a frozen (inactive) state.

        A frozen account operates in a strict Read-Only mode. It preserves
        its current balance and history but outright rejects any state-mutating
        financial operations (like deposits or withdrawals) until explicitly unfrozen.

        Raises:
            RuntimeError: If the account is already frozen.
        """
        if self._is_frozen:
            raise RuntimeError("This account is already frozen")

        self._is_frozen = True

    def unfreeze(self) -> None:
        """
        Restores the account to an active, operational state.

        Lifts the Read-Only restriction, allowing standard balance-mutating
        financial operations to resume.

        Raises:
            RuntimeError: If the account is not frozen.
        """
        if not self._is_frozen:
            raise RuntimeError("This account is not frozen")

        self._is_frozen = False

    def deposit(self, amount: Decimal) -> tuple[TransactionEventDTO]:
        """
        Performs a standard deposit operation.

        Enforces the strict domain rule that an account must be active to receive funds.
        Validates the input value and increments the account balance.
        This implementation serves as the default behavior for SavingsAccount
        and is extended by CheckingAccount.

        Args:
            amount (Decimal): The amount to deposit.

        Returns:
            tuple[TransactionEventDTO]: A single-element tuple containing the DTO
                that represents the standard deposit event.

        Raises:
            FrozenAccountError: If the account is currently frozen.
            TypeError: If the value is not a Decimal instance.
            ValueError: If the deposit amount is less than the MIN_ATM_TRANSACTION limit.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform deposit operation on a frozen account"
            )

        Account.validate_amount_entry(amount)
        self._balance += amount

        return (
            TransactionEventDTO(amount=amount, transaction=TransactionType.DEPOSIT),
        )


class SavingsAccount(Account):
    """
    Represents a standard Savings Account.

    A Savings Account only allows withdrawals up to the current balance.
    It does not support overdraft or credit limits.
    """

    DAILY_EARNINGS_RATE: ClassVar[Decimal] = Decimal("0.00016")

    _accrual: Decimal

    def __init__(self, branch_code: str, account_num: str):
        super().__init__(branch_code, account_num)

        self._accrual = Decimal("0.00")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavingsAccount:
        """
        Reconstructs a SavingsAccount instance from a dictionary.

        Extends the base Account hydration process by enforcing a strict
        data integrity check: Savings accounts cannot have negative balances.

        Raises:
            RuntimeError: If the database state reflects a negative balance.
        """
        if data["balance"] < 0:
            raise RuntimeError(
                "SavingsAccount does not allow negative balance. Database state might be corrupted."
            )

        current_balance = data["balance"]
        last_update = data["balance_update_at"]

        instance = cast(SavingsAccount, super().from_dict(data))
        new_balance = instance._calculate_yield(current_balance, last_update)
        instance._balance = new_balance

        return instance

    def _calculate_yield(
        self, current_balance: Decimal, balance_date: datetime
    ) -> Decimal:
        time_delta = datetime.today() - balance_date
        new_balance = (
            current_balance * (1 + self.DAILY_EARNINGS_RATE) ** time_delta.days
        )

        self._accrual = new_balance - current_balance

        return new_balance

    def simulate_withdrawal(self, amount: Decimal) -> WithdrawalSimulationDTO:
        """
        Simulates a withdrawal strictly based on the available positive balance.

        Since a Savings Account does not support credit limits, the simulation
        only evaluates if the requested amount is lesser than or equal to the
        current balance. It enforces structural input validation before evaluation.

        Args:
            amount (Decimal): The intended monetary amount to be withdrawn.

        Returns:
            WithdrawalSimulationDTO: A detailed projection of the transaction,
                indicating authorization status. Overdraft fields will strictly be None,
                as this account type does not support credit limits.

        Raises:
            TypeError: If the value is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
        """

        Account.validate_amount_entry(amount)

        authorized = amount <= self._balance

        return WithdrawalSimulationDTO(
            authorized=authorized, use_overdraft=None, overdraft_required=None
        )

    def withdrawal(self, amount: Decimal) -> tuple[TransactionEventDTO]:
        """
        Withdraws a given amount from the savings account balance.

        Enforces the strict domain rule that an account must be active to dispense funds.
        For a SavingsAccount, the available value is strictly the current positive balance.
        Overdraft limits are not supported.

        Args:
            amount (Decimal): The amount to withdraw.

        Returns:
            tuple[TransactionEventDTO]: A single-element tuple containing the DTO
                that represents the standard withdrawal event, with a negative amount.

        Raises:
            FrozenAccountError: If the account is currently frozen.
            TypeError: If the value is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
            InsufficientFundsError: If the requested amount exceeds the current balance.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform withdraw operation on a frozen account"
            )

        Account.validate_amount_entry(amount)
        Account._validate_account_withdrawal(val=amount, available_val=self._balance)

        self._balance -= amount

        return (
            TransactionEventDTO(amount=-amount, transaction=TransactionType.WITHDRAWAL),
        )


class CheckingAccount(Account):
    """
    Represents a Checking Account with an integration for overdraft limits.

    Allows withdrawal operations that exceed the standard positive balance,
    up to a statically defined OVERDRAFT_LIMIT. Instead of tracking credit
    usage in an isolated attribute, this class derives its operational credit
    state dynamically from a negative balance, enforcing a single source of truth.
    """

    OVERDRAFT_LIMIT: ClassVar[Decimal] = Decimal("3000.00")
    DAILY_INTEREST_RATE: ClassVar[Decimal] = Decimal("0.0025")

    _accrual: Decimal

    def __init__(self, branch_code: str, account_num: str):
        super().__init__(branch_code, account_num)

        self._accrual = Decimal("0.00")

    @property
    def available_overdraft(self) -> Decimal:
        """
        Calculates the remaining available credit limit dynamically.

        If the account operates with a positive balance or is exactly zero,
        the full OVERDRAFT_LIMIT is available. If the account is operating in
        the negative, the current debt is deducted directly from the limit to
        reflect the remaining capacity.

        Returns:
            Decimal: The exact monetary value available for credit operations.
        """
        total_overdraft = self.OVERDRAFT_LIMIT

        return (
            total_overdraft if self._balance >= 0 else total_overdraft + self._balance
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckingAccount:

        current_balance = data["balance"]
        last_update = data["balance_update_at"]

        instance = cast(CheckingAccount, super().from_dict(data))
        new_balance = instance._calculate_overdraft_interest(
            current_balance, last_update
        )
        instance._balance = new_balance

        return instance

    def _calculate_overdraft_interest(
        self, current_balance: Decimal, balance_date: datetime
    ) -> Decimal:

        if current_balance >= 0:
            return self.balance

        time_delta = datetime.today() - balance_date

        interest = abs(current_balance) * (
            (1 + self.DAILY_INTEREST_RATE) ** time_delta.days - 1
        )

        self._accrual = -interest
        new_balance = current_balance - interest

        return new_balance

    def simulate_withdrawal(self, amount: Decimal) -> WithdrawalSimulationDTO:
        """
        Simulates a withdrawal evaluating both positive balance and overdraft limit.

        Calculates whether the transaction is possible and exactly how much of
        the credit limit would be consumed. Since Checking Accounts inherently
        support overdraft, the `use_overdraft` property will strictly be a boolean.

        Args:
            amount (Decimal): The intended monetary amount to be withdrawn.

        Returns:
            WithdrawalSimulationDTO: A detailed projection indicating authorization
                status, overdraft necessity, and the precise required credit amount.

        Raises:
            TypeError: If the value is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
        """

        Account.validate_amount_entry(amount)

        authorized = amount <= (CheckingAccount.OVERDRAFT_LIMIT + self.balance)
        use_overdraft = amount > self._balance

        if use_overdraft:
            required = amount - self._balance if self._balance > 0 else amount
        else:
            required = Decimal("0.00")

        return WithdrawalSimulationDTO(
            authorized=authorized,
            use_overdraft=use_overdraft,
            overdraft_required=required,
        )

    def withdrawal(self, amount: Decimal) -> tuple[TransactionEventDTO, ...]:
        """
        Withdraws an amount, automatically utilizing the overdraft limit if necessary.

        Enforces the strict domain rule that an account must be active to dispense funds.
        The total available funds are calculated as `balance + OVERDRAFT_LIMIT`.
        If the withdrawal crosses the zero-balance threshold, the event is split into
        two distinct DTOs to accurately reflect standard withdrawal and credit limit usage.

        Args:
            amount (Decimal): The amount to withdraw.

        Returns:
            tuple[TransactionEventDTO, ...]: A tuple containing one or two event DTOs,
                categorized as WITHDRAWAL and/or OVERDRAFT_WITHDRAWAL, with negative amounts.

        Raises:
            FrozenAccountError: If the account is currently frozen.
            TypeError: If the value is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
            InsufficientFundsError: If the amount exceeds the total available funds
                                    (balance + overdraft limit).
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform withdraw operation on a frozen account"
            )

        available = CheckingAccount.OVERDRAFT_LIMIT + self._balance
        Account._validate_account_withdrawal(val=amount, available_val=available)

        balance = self._balance
        self._balance -= amount

        # Case 1: Fully covered by positive balance (including exact withdrawal)
        if amount <= balance:
            return (
                TransactionEventDTO(
                    amount=-amount, transaction=TransactionType.WITHDRAWAL
                ),
            )

        # Case 2: Fully operating within overdraft limits (including starting exactly at zero)
        if balance <= 0:
            return (
                TransactionEventDTO(
                    amount=-amount, transaction=TransactionType.OVERDRAFT_WITHDRAWAL
                ),
            )

        # Case 3: Zero-crossing (Partial standard, partial overdraft)
        return (
            TransactionEventDTO(
                amount=-balance, transaction=TransactionType.WITHDRAWAL
            ),
            TransactionEventDTO(
                amount=self._balance,
                transaction=TransactionType.OVERDRAFT_WITHDRAWAL,
            ),
        )
