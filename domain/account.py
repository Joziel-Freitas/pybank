"""
Account Management Module.

Defines the abstract base class Account and its concrete implementations:
SavingsAccount and CheckingAccount. This module orchestrates the core domain logic
of the banking system, including account initialization, strict structural validation,
state-safe withdrawal simulations, and time-based financial adjustments (accruals).

It employs Domain-Driven Design (DDD) principles to return immutable ledger events
(LedgerEventDTO) instead of simple primitives, ensuring a robust, append-only
audit trail for the repository layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, cast

from infra import verify
from shared.dtos import AccrualEventDTO, LedgerEventDTO, WithdrawalSimulationDTO
from shared.exceptions import (
    FrozenAccountError,
    InsufficientFundsError,
    InvalidAccountError,
    InvalidBranchError,
)
from shared.types import AccrualType, TransactionType


class Account(ABC):
    """
    Abstract Base Class (ABC) for all bank accounts.

    Enforces mandatory attributes, temporal state tracking, and polymorphic
    mathematical behaviors (deposit, withdrawal, accruals) across all concrete
    account types. Acts as the orchestrator for state mutation, ensuring that
    any financial change simultaneously updates the domain clock.

    Attributes:
        _branch_code (str): The validated bank branch code.
        _account_num (str): The validated unique account number.
        _is_frozen (bool): The operational status of the account (True if blocked).
        _balance (Decimal): The current authoritative account balance.
        _balance_updated_at (datetime): The exact temporal anchor of the last
            balance mutation, used for calculating precise daily accruals.
    """

    MIN_ATM_TRANSACTION: ClassVar[Decimal] = Decimal(2.00)

    # Type hints for the instance's variables
    _branch_code: str
    _account_num: str
    _is_frozen: bool
    _balance: Decimal
    _balance_updated_at: datetime

    def __init__(self, branch_code: str, account_num: str):
        """
        Initializes a new Account instance with validated identifiers.

        Sets the initial financial state to zero and initializes the domain
        clock to the current datetime. The account is created in an active
        (unfrozen) state by default.

        Args:
            branch_code (str): The code of the bank branch (validated for format).
            account_num (str): The unique account number (validated for format).

        Raises:
            InvalidBranchError: If `branch_code` fails validation.
            InvalidAccountError: If `account_num` fails validation.
        """
        self._branch_code = Account.validate_branch_code(branch_code)
        self._account_num = Account.validate_account_number(account_num)
        self._is_frozen = False
        self._balance = Decimal("0.00")
        self._balance_updated_at = datetime.now()

    def __repr__(self) -> str:
        """Returns the canonical string representation of the Account instance."""
        class_name = type(self).__name__

        return (
            f"{class_name}("
            f"branch_code={self._branch_code!r}, "
            f"account_num={self._account_num!r}, "
            f"balance={self._balance!r}, "
            f"balance_updated_at={self._balance_updated_at!r})"
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
    def is_frozen(self) -> bool:
        """Returns the current status of the account"""
        return self._is_frozen

    @property
    def balance(self) -> Decimal:
        """Returns the current balance of the account."""
        return self._balance

    @property
    def balance_updated_at(self) -> datetime:
        """Returns the datetime of the last balance update"""
        return self._balance_updated_at

    @property
    @abstractmethod
    def _pending_accrual(self) -> Decimal:
        """
        Represents the raw monetary value of time-based financial adjustments.

        This abstract property enforces the Template Method Pattern, requiring
        concrete account subclasses to define the specific state of their
        pending mathematics (e.g., compound interest for overdrafts or yield
        for savings) based on the elapsed calendar days since the last balance update.

        Returns:
            Decimal: The accumulated accrual amount. Expected to be positive for
                yields, negative for interest charges, and exactly Decimal("0.00")
                if no accruals apply.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def project_accrual(self) -> AccrualEventDTO:
        """
        Calculates and projects the time-based financial adjustments for the account.

        Acts as a Read-Only projection mechanism (Lazy Materialization). It evaluates
        the elapsed time since the last balance update and computes the pending
        remuneration (yield) or debt charges (interest) without mutating the actual
        account balance.

        Returns:
            AccrualEventDTO: An immutable payload detailing the calculated amount,
                its semantic classification (YIELD or INTEREST), and the temporal
                anchor for the calculation.
        """
        raise NotImplementedError

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
    def withdrawal(self, amount: Decimal) -> tuple[LedgerEventDTO, ...]:
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Account:
        """
        Factory method to reconstruct an Account instance (or subclass) from a dictionary.

        Implements a Dispatcher Pattern:
        1. If called on the base Account class, it inspects the 'type' field in the data
           and delegates instantiation to the correct subclass (Checking or Savings).
        2. If called on (or dispatched to) a subclass, it restores the common state
           attributes (balance, frozen status, and temporal state) and returns
           the fully hydrated instance.

        Args:
            data (dict[str, Any]): The dictionary containing raw account data.
                Expects 'balance_updated_at' to be a valid datetime object.

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
        instance._is_frozen = data["is_frozen"]
        instance._balance = data["balance"]
        instance._balance_updated_at = data["balance_updated_at"]

        return instance

    def _update_balance(self, amount: Decimal) -> None:
        """
        Mutates the account balance and synchronizes the domain clock.

        This protected method acts as the sole access point for state mutation
        regarding the financial balance. It guarantees that any change to the funds
        (whether through standard transactions or accrual materialization) simultaneously
        updates the internal tracker, ensuring the domain maintains an accurate,
        authoritative record of its own temporal state.

        Args:
            amount (Decimal): The exact monetary value to be added to the balance.
                Negative values are inherently supported for debits/withdrawals.
        """
        self._balance += amount
        self._balance_updated_at = datetime.now()

    def _apply_accrual(self) -> LedgerEventDTO | None:
        """
        Materializes pending accruals into the account balance and ledger.

        Acts as an internal orchestrator that evaluates if any time-based
        financial adjustments (yields or charges) have accrued. If a non-zero
        adjustment exists, it mutates the account state via `_update_balance`
        and generates an immutable ledger event for persistence.

        Returns:
            LedgerEventDTO | None: A data transfer object representing the applied
                accrual event ready for database insertion, or None if no
                time has elapsed or the calculated amount is zero.
        """
        accrual = self._pending_accrual

        if not accrual:
            return None

        start_balance = self._balance
        self._update_balance(accrual)

        return LedgerEventDTO(
            previous_balance=start_balance,
            amount=accrual,
            event_type=AccrualType.YIELD if accrual > 0 else AccrualType.INTEREST,
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
            "type": type(self).__name__,
            "is_frozen": self._is_frozen,
            "balance": self._balance,
            "balance_updated_at": self._balance_updated_at,
        }

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

    def deposit(self, amount: Decimal) -> tuple[LedgerEventDTO, ...]:
        """
        Performs a standard deposit operation.

        Enforces the strict domain rule that an account must be active to receive funds.
        Validates the input value, processes any pending time-based accruals, and
        increments the account balance. This implementation serves as the default
        behavior for all concrete account types.

        Args:
            amount (Decimal): The amount to deposit.

        Returns:
            tuple[LedgerEventDTO, ...]: A tuple containing the DTOs that represent
                the financial events generated by this operation (e.g., the deposit
                itself, potentially preceded by a yield or interest materialization).
                Each event accurately captures its preceding balance point.

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
        accruals_event = self._apply_accrual()

        start_balance = self._balance
        self._update_balance(amount)
        deposit_event = LedgerEventDTO(
            previous_balance=start_balance,
            amount=amount,
            event_type=TransactionType.DEPOSIT,
        )

        if accruals_event:
            return (accruals_event, deposit_event)

        return (deposit_event,)


class SavingsAccount(Account):
    """
    Represents a standard Savings Account.

    A Savings Account only allows withdrawals up to the current positive balance.
    It does not support overdraft or credit limits. It implements the domain rule
    for positive remuneration, automatically calculating and applying daily yields
    (compound interest) to the balance based on elapsed calendar days.
    """

    DAILY_EARNINGS_RATE: ClassVar[Decimal] = Decimal("0.00016")

    @property
    def _pending_accrual(self) -> Decimal:
        """
        Represents the positive yield generated by the savings balance.

        Derived dynamically by applying daily compound interest over the
        positive balance for the number of full calendar days elapsed
        since the last update.

        Returns:
            Decimal: The precise yield amount pending materialization,
                strictly formatted to two decimal places.
        """
        time_delta = datetime.now().date() - self._balance_updated_at.date()
        delta_days = time_delta.days
        new_amount = self._balance * (1 + self.DAILY_EARNINGS_RATE) ** delta_days
        earnings = new_amount - self.balance

        return earnings.quantize(Decimal("0.00"))

    @property
    def project_accrual(self) -> AccrualEventDTO:
        """
        Projects the current pending yield for read-only visualization.

        Retrieves the calculated earnings without altering the account's actual
        balance or updating its temporal state. This is strictly intended for
        statement generation and UI feedback (Lazy Materialization).

        Returns:
            AccrualEventDTO: An immutable payload detailing the pending yield
                and the exact date of the projection.
        """
        earnings = self._pending_accrual

        return AccrualEventDTO(
            amount=earnings,
            accrual_type=AccrualType.YIELD,
            event_date=datetime.now().date(),
        )

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

        return cast(SavingsAccount, super().from_dict(data))

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

    def withdrawal(self, amount: Decimal) -> tuple[LedgerEventDTO, ...]:
        """
        Withdraws a given amount from the savings account balance.

        Enforces the strict domain rule that an account must be active to dispense funds.
        For a SavingsAccount, the available value is strictly the current positive balance
        (including newly materialized yields). Overdraft limits are not supported.

        Args:
            amount (Decimal): The amount to withdraw.

        Returns:
            tuple[LedgerEventDTO, ...]: A tuple containing the DTOs that represent
                the financial events generated by this operation, categorized
                sequentially. Each event accurately captures its preceding balance point.
                Withdrawal amounts are represented as negative values.

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
        accrual_event = self._apply_accrual()
        Account._validate_account_withdrawal(val=amount, available_val=self._balance)
        start_balance = self._balance
        self._update_balance(-amount)

        withdrawal_event = LedgerEventDTO(
            previous_balance=start_balance,
            amount=-amount,
            event_type=TransactionType.WITHDRAWAL,
        )

        if accrual_event:
            return (accrual_event, withdrawal_event)

        return (withdrawal_event,)


class CheckingAccount(Account):
    """
    Represents a Checking Account with an integrated overdraft limit.

    Allows withdrawal operations that exceed the standard positive balance,
    up to a statically defined OVERDRAFT_LIMIT. This class derives its
    operational credit state dynamically directly from a negative balance,
    enforcing a single source of truth and eliminating legacy tracking attributes
    (such as isolated credit states).

    It implements the domain rule for debt charges, automatically calculating
    and applying daily interest fees to any utilized overdraft amount based
    on elapsed calendar days.
    """

    OVERDRAFT_LIMIT: ClassVar[Decimal] = Decimal("3000.00")
    DAILY_INTEREST_RATE: ClassVar[Decimal] = Decimal("0.0025")

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

    @property
    def _pending_accrual(self) -> Decimal:
        """
        Represents the debt charges applied to utilized overdraft limits.

        If the account balance is positive or exactly zero, this property
        evaluates to zero. If operating in the negative, it reflects the
        daily compound interest applied over the absolute debt for the
        number of full calendar days elapsed.

        Returns:
            Decimal: The exact interest charge as a negative value, rounded
                to two decimal places, or Decimal("0.00") if no debt exists.
        """
        if self._balance >= 0:
            return Decimal("0.00")

        time_delta = datetime.today().date() - self._balance_updated_at.date()
        delta_days = time_delta.days

        interest = abs(self._balance) * (
            (1 + self.DAILY_INTEREST_RATE) ** delta_days - 1
        )

        return -interest.quantize(Decimal("0.00"))

    @property
    def project_accrual(self) -> AccrualEventDTO:
        """
        Projects the current pending overdraft interest for read-only visualization.

        Retrieves the calculated debt charges without mutating the account's
        balance or temporal state, ensuring safe display on user statements
        (Lazy Materialization).

        Returns:
            AccrualEventDTO: An immutable payload detailing the pending interest
                charges and the exact date of the projection.
        """
        interest = self._pending_accrual

        return AccrualEventDTO(
            amount=interest,
            accrual_type=AccrualType.INTEREST,
            event_date=datetime.now().date(),
        )

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

    def withdrawal(self, amount: Decimal) -> tuple[LedgerEventDTO, ...]:
        """
        Withdraws an amount, automatically utilizing the overdraft limit if necessary.

        Enforces the strict domain rule that an account must be active to dispense funds.
        The total available funds are calculated as `balance + OVERDRAFT_LIMIT`.
        If the withdrawal crosses the zero-balance threshold, the event is split into
        two distinct DTOs to accurately reflect standard withdrawal and credit limit usage.

        Args:
            amount (Decimal): The amount to withdraw.

        Returns:
            tuple[LedgerEventDTO, ...]: A tuple containing the DTOs that represent
                the financial events generated by this operation, categorized
                sequentially. Each event accurately captures its preceding balance point.
                Withdrawal amounts are represented as negative values.

        Raises:
            FrozenAccountError: If the account is currently frozen.
            TypeError: If the value is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
            InsufficientFundsError: If the amount exceeds the total available funds.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform withdraw operation on a frozen account"
            )

        Account.validate_amount_entry(amount)
        accrual_event = self._apply_accrual()
        available = CheckingAccount.OVERDRAFT_LIMIT + self._balance
        Account._validate_account_withdrawal(val=amount, available_val=available)

        start_balance = self._balance
        self._update_balance(-amount)

        events_list: list[LedgerEventDTO] = []

        if accrual_event:
            events_list.append(accrual_event)

        # Case 1: Fully covered by positive balance (including exact withdrawal)
        if start_balance >= amount:
            events_list.append(
                LedgerEventDTO(
                    previous_balance=start_balance,
                    amount=-amount,
                    event_type=TransactionType.WITHDRAWAL,
                )
            )
        # Case 2: Fully operating within overdraft limits (including starting exactly at zero)
        elif start_balance <= 0:
            events_list.append(
                LedgerEventDTO(
                    previous_balance=start_balance,
                    amount=-amount,
                    event_type=TransactionType.OVERDRAFT_WITHDRAWAL,
                )
            )
        # Case 3: Zero-crossing (Partial standard, partial overdraft)
        else:
            events_list.append(
                LedgerEventDTO(
                    previous_balance=start_balance,
                    amount=-start_balance,
                    event_type=TransactionType.WITHDRAWAL,
                )
            )
            events_list.append(
                LedgerEventDTO(
                    previous_balance=Decimal("0.00"),
                    amount=self._balance,
                    event_type=TransactionType.OVERDRAFT_WITHDRAWAL,
                )
            )
        return tuple(events_list)
