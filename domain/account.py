"""
Account Management Module.

Defines the abstract base class Account and its concrete implementations:
SavingsAccount and CheckingAccount. This module handles account initialization,
attribute validation, and core banking mathematical operations (deposit and withdraw).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, ClassVar, NamedTuple, cast

from infra import verify
from shared.exceptions import (
    InvalidAccountError,
    InvalidBalanceError,
    InvalidBranchError,
    InvalidDepositError,
    InvalidWithdrawError,
)


class WithdrawalInfo(NamedTuple):
    authorized: bool
    uses_limit: bool | None


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

    # Type hints for the instance's variables
    _branch_code: str
    _account_num: str
    _balance: Decimal

    def __init__(
        self, branch_code: str, account_num: str, balance: Decimal = Decimal("0.00")
    ):
        """
        Initializes a new Account instance with validated attributes.

        Args:
            branch_code (str): The code of the bank branch (validated for format).
            account_num (str): The unique account number (validated for format).
            balance (Decimal, optional): The initial balance. Must be non-negative.
                                         Defaults to Decimal("0.00").

        Raises:
            InvalidBranchError: If `branch_code` fails validation.
            InvalidAccountError: If `account_num` fails validation.
            InvalidBalanceError: If `balance` fails validation (e.g., negative).
        """
        self._branch_code = Account.validate_branch_code(branch_code)
        self._account_num = Account.validate_account_number(account_num)
        self._balance = Account.validate_account_initial_balance(balance)

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

    @abstractmethod
    def withdraw(self, value: Decimal) -> None:
        """
        Abstract method for withdrawing an amount from the account.

        Concrete implementations must handle specific withdrawal logic,
        such as checking available limits or minimum balances.

        Args:
            value (Decimal): The amount to withdraw.
        """
        raise NotImplementedError()

    @staticmethod
    def validate_branch_code(code: str) -> str:
        """
        Validates the format and length of the branch code.

        The branch code must be a string of 4 numeric characters.

        Args:
            code (str): The branch code string to validate.

        Returns:
            str: The validated branch code.

        Raises:
            InvalidBranchError: If the branch code is not a string, not numeric, or not of length 4.
        """
        try:
            verify.verify_instance(code, str)
            verify.verify_digits(code, 4)
            return code
        except verify.VERIFY_ERRORS as e:
            raise InvalidBranchError(f"Invalid branch code. Cause: {e}") from e

    @staticmethod
    def validate_account_number(acc_num: str) -> str:
        """
        Validates the format and length of the account number.

        The account number must be a string of 8 numeric characters.

        Args:
            acc_num (str): The account number string to validate.

        Returns:
            str: The validated account number.

        Raises:
            InvalidAccountError: If the account number is not a string, not numeric, or not of length 8.
        """
        try:
            verify.verify_instance(acc_num, str)
            verify.verify_digits(acc_num, 8)
            return acc_num
        except verify.VERIFY_ERRORS as e:
            raise InvalidAccountError(f"Invalid account number. Cause: {e}") from e

    @staticmethod
    def validate_account_initial_balance(bal: Decimal) -> Decimal:
        """
        Validates the initial balance value.

        The balance must be a non-negative Decimal.

        Args:
            bal (Decimal): The initial balance value.

        Returns:
            Decimal: The validated balance.

        Raises:
            InvalidBalanceError: If the value is not a Decimal or is negative.
        """
        try:
            verify.verify_instance(bal, Decimal)
            verify.verify_interval(bal, min_val=Decimal("0"))
            return bal
        except verify.VERIFY_ERRORS as e:
            raise InvalidBalanceError(f"Invalid balance value. Cause: {e}") from e

    @staticmethod
    def validate_account_deposit(val: Decimal) -> None:
        """
        Validates the deposit value.

        The deposit must be a Decimal greater than or equal to 0.5.

        Args:
            val (Decimal): The deposit amount.

        Raises:
            InvalidDepositError: If the value is not a Decimal or is less than 0.5.
        """
        try:
            verify.verify_instance(val, Decimal)
            verify.verify_interval(val, min_val=Decimal("0.5"))
        except verify.VERIFY_ERRORS as e:
            raise InvalidDepositError(f"Invalid deposit value. Cause: {e}") from e

    @staticmethod
    def validate_account_withdraw(val: Decimal, available_val: Decimal) -> None:
        """
        Validates a withdrawal value against availability rules.

        The withdrawal value must be a Decimal greater than or equal to 0.5 and
        must not exceed the `available_val`.

        Args:
            val (Decimal): The amount requested for withdrawal.
            available_val (Decimal): The total funds available for withdrawal (e.g., balance + limit).

        Raises:
            InvalidWithdrawError: If the value is not a Decimal, less than 0.5, or exceeds available funds.
        """
        try:
            verify.verify_instance(val, Decimal)
            verify.verify_interval(val, min_val=Decimal("0.5"), max_val=available_val)
        except verify.VERIFY_ERRORS as e:
            raise InvalidWithdrawError(f"Invalid withdraw value: Cause: {e}") from e

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
            balance=Decimal(data["balance"]),
        )
        return instance

    def deposit(self, value: Decimal) -> None:
        """
        Performs a standard deposit operation.

        Validates the input value and increments the account balance.
        This implementation serves as the default behavior for SavingsAccount
        and is extended by CheckingAccount.

        Args:
            value (Decimal): The amount to deposit.

        Raises:
            InvalidDepositError: If the value is not a Decimal or is less than 0.5.
        """
        Account.validate_account_deposit(value)
        self._balance += value

    def check_withdrawal(self, value: Decimal) -> WithdrawalInfo:
        """
        Standard validation: checks only against the balance.

        This serves as the default behavior for any account type that does not
        have a credit limit (like SavingsAccount).

        Args:
            value (Decimal): The amount requested.

        Returns:
            WithdrawalInfo:
                - authorized: True if balance >= value.
                - uses_limit: Always False (if authorized) or None (if unauthorized).
        """
        is_auth = value <= self.balance

        uses_limit = False if is_auth else None

        return WithdrawalInfo(authorized=is_auth, uses_limit=uses_limit)


class SavingsAccount(Account):
    """
    Represents a standard Savings Account.

    A Savings Account only allows withdrawals up to the current balance.
    It does not support overdraft or credit limits.
    """

    def withdraw(self, value: Decimal) -> None:
        """
        Withdraws a given amount from the account balance.

        For a SavingsAccount, `available_val` is simply the current positive balance.

        Args:
            value (Decimal): The amount to withdraw.

        Raises:
            InvalidWithdrawError: If the withdrawal amount is invalid or exceeds the current balance.
        """
        Account.validate_account_withdraw(val=value, available_val=self._balance)
        self._balance -= value


class CheckingAccount(Account):
    """
    Represents a Checking Account with an optional overdraft limit.

    Allows withdrawals that exceed the balance, up to the defined CREDIT_LIMIT.
    Tracks the amount of credit used (`_used_credit`).
    """

    CREDIT_LIMIT: ClassVar[Decimal] = Decimal("3000.00")
    _used_credit: Decimal

    def __init__(
        self, branch_code: str, account_num: str, balance: Decimal = Decimal("0.00")
    ):
        """
        Initializes a CheckingAccount.

        Sets `_used_credit` to 0.0.
        """
        super().__init__(branch_code, account_num, balance)
        self._used_credit = Decimal("0.00")

    @property
    def remaining_credit(self) -> Decimal:
        """Returns the remaining credit (CREDIT_LIMIT minus used credit)."""
        return CheckingAccount.CREDIT_LIMIT - self._used_credit

    def to_dict(self) -> dict[str, Any]:
        """
        Serializes the CheckingAccount, extending the base serialization.

        Adds specific credit attributes (`CREDIT_LIMIT` and `used_credit`) to the
        dictionary. Note that `CREDIT_LIMIT` is strictly informational, as the
        value is defined as a class constant.

        Returns:
            dict: The complete dictionary with base account data plus credit info.
        """
        obj_data = super().to_dict()
        obj_data["used_credit"] = self._used_credit

        return obj_data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckingAccount:
        """
        Reconstructs a CheckingAccount instance.

        Delegates the core hydration to the parent class and then populates the
        specific `_used_credit` attribute.

        Args:
            data (dict): The dictionary containing account data.

        Returns:
            CheckingAccount: The restored instance with the correct credit usage state.
        """
        instance = cast(CheckingAccount, super().from_dict(data))
        instance._used_credit = data["used_credit"]

        return instance

    def deposit(self, value: Decimal) -> None:
        """
        Deposits an amount and adjusts the used credit line.

        Extends the base Account.deposit logic. After the funds are added to
        the balance, this method recalculates the `_used_credit`. If the
        deposit restores the balance to positive, `_used_credit` is reset to zero.

        Args:
            value (Decimal): The amount to deposit.

        Raises:
            InvalidDepositError: If the deposit amount is invalid (propagated from base).
        """
        super().deposit(value)

        # If balance is still negative, update used credit. Otherwise, reset to 0.
        self._used_credit = abs(self._balance) if self._balance < 0 else Decimal("0.00")

    def check_withdrawal(self, value: Decimal) -> WithdrawalInfo:
        """
        Withdraws an amount using credit if needed.

        The total available funds are calculated as `balance + CREDIT_LIMIT`.
        `_used_credit` is updated if the balance becomes negative.

        Args:
            value (Decimal): The amount to withdraw.

        Raises:
            InvalidWithdrawError: If the withdrawal amount is invalid or exceeds the total available funds.
        """
        total_funds = self.balance + self.remaining_credit

        is_auth = value <= total_funds
        uses_limit = None if not is_auth else value > self.balance

        return WithdrawalInfo(uses_limit=uses_limit, authorized=is_auth)

    def withdraw(self, value: Decimal) -> None:
        """
        Withdraws an amount using credit if needed and records the transaction.

        The total available funds are calculated as `balance + CREDIT_LIMIT`.
        `_used_credit` is updated if the balance becomes negative.

        Args:
            value (Decimal): The amount to withdraw.

        Raises:
            InvalidWithdrawError: If the withdrawal amount is invalid or exceeds the total available funds.
        """
        available = CheckingAccount.CREDIT_LIMIT + self._balance
        Account.validate_account_withdraw(val=value, available_val=available)
        self._balance -= value

        # Update used credit if we enter or remain in overdraft
        if self._balance < 0:
            self._used_credit = abs(self._balance)
