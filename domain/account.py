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
from datetime import date
from decimal import Decimal
from typing import ClassVar, cast

from infra import verify
from shared import clock
from shared.dtos import AccountFinancialDTO, LedgerEventDTO, WithdrawalSimulationDTO
from shared.exceptions import (
    FrozenAccountError,
    InsufficientFundsError,
    InvalidAccountError,
    InvalidBranchError,
)
from shared.snapshots import AccountSnapshot
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
        _last_balance_update (date): The exact temporal anchor of the last
        balance mutation, used for calculating precise daily accruals.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------

    MIN_ATM_TRANSACTION: ClassVar[Decimal] = Decimal(2.00)

    # Type hints for the instance's variables
    _branch_code: str
    _account_num: str
    _is_frozen: bool
    _balance: Decimal
    _last_balance_update: date

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------

    def __init__(self, branch_code: str, account_num: str):
        """
        Initializes a new Account instance with validated identifiers.

        Sets the initial financial state to zero and initializes the domain
        clock to the current system date. The account is created in an active
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
        self._last_balance_update = clock.get_today()

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------

    def __repr__(self) -> str:
        """Returns the canonical string representation of the Account instance."""
        class_name = type(self).__name__

        return (
            f"{class_name}("
            f"branch_code={self._branch_code!r}, "
            f"account_num={self._account_num!r}, "
            f"balance={self._balance!r}, "
            f"last_balance_update={self._last_balance_update!r})"
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

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

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
        """
        Returns the true, temporally accurate balance of the account.

        Combines the raw ledger balance with any pending time-based accruals
        (yields or interest) up to the current moment.
        """
        return self._balance + self._pending_accrual

    @property
    def last_balance_update(self) -> date:
        """Returns the calendar date of the last balance update."""
        return self._last_balance_update

    @property
    def financial_info(self) -> AccountFinancialDTO:
        """
        Projects the complete, mathematically accurate financial state of the account.

        Acts as a strict Read-Only facade (Lazy Materialization). By orchestrating
        subclass-specific implementations of credit limits, accruals, and available
        funds, this method enforces the Information Expert principle. It centralizes
        the construction of the AccountFinancialDTO, applying the DRY principle and
        ensuring that the Application layer receives a uniform, predictable, and
        temporally accurate snapshot of the account's true state.

        Returns:
            AccountFinancialDTO: An immutable, composed snapshot detailing the ledger
                balance, pending accruals, true current balance, operational limits,
                and the total purchasing power at the exact moment of invocation.
        """
        accrual = self._pending_accrual
        accrual_type = None

        if accrual:
            accrual_type = AccrualType.YIELD if accrual > 0 else AccrualType.INTEREST

        return AccountFinancialDTO(
            ledger_balance=self._balance,
            accrual=accrual,
            balance=self.balance,
            accrual_type=accrual_type,
            credit_limit=self.credit_limit,
            available_credit=self.available_credit,
            available_balance=self.available_funds,
            issue_at=clock.get_today(),
        )

    @property
    @abstractmethod
    def credit_limit(self) -> Decimal | None:
        """
        Defines the maximum credit threshold granted to the account.

        Acts as an explicit contract for subclasses to declare their support
        for credit products. Enforces the Open/Closed Principle by allowing
        the base orchestrator to safely evaluate credit availability without
        type-checking concrete implementations.

        Returns:
            Decimal | None: The absolute monetary value of the credit limit,
                or None if the account type does not support credit operations.
        """
        pass

    @property
    @abstractmethod
    def available_credit(self) -> Decimal | None:
        """
        Calculates the real-time remaining credit available for transactions.

        Acts as a dynamic projection that accounts for current ledger balances
        and any pending time-based charges (e.g., compound interest) that
        actively consume the credit limit.

        Returns:
            Decimal | None: The precise monetary value still available from the
                credit limit, or None if credit operations are not supported.
        """
        pass

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
        pass

    @property
    @abstractmethod
    def available_funds(self) -> Decimal:
        """
        Calculates the true, mathematically precise transaction capacity of the account.

        Acts as a dynamic projection of the account's purchasing power at the exact
        moment of invocation. It enforces the Information Expert principle by combining
        the authoritative ledger balance with any pending time-based accruals and
        account-specific credit rules.

        Returns:
            Decimal: The absolute monetary value available for disbursement.
        """
        pass

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    def to_snapshot(self) -> AccountSnapshot:
        """
        Generates a persistence snapshot of the current account state.

        Packages the raw ledger state, operational flags, and a polymorphic
        'account_type' identifier (e.g., 'CheckingAccount') into a strictly
        typed, immutable Data Transfer Object. This isolates the Domain from
        infrastructure schemas while providing the Repository with everything
        needed for storage and future hydration.

        Returns:
            AccountSnapshot: An immutable snapshot containing the account's base
                identifiers, financial ledger balance, temporal anchor, and class type.
        """
        return AccountSnapshot(
            branch_code=self._branch_code,
            account_num=self._account_num,
            account_type=type(self).__name__,
            is_frozen=self._is_frozen,
            balance=self._balance,
            last_balance_update=self._last_balance_update,
        )

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

    def simulate_withdrawal(self, amount: Decimal) -> WithdrawalSimulationDTO:
        """
        Simulates the financial projection of a withdrawal without mutating state.

        Acts as a universal financial oracle for all account types. It evaluates
        transaction viability strictly based on the polymorphic 'available_funds'
        and explicitly checks the subclass contracts for credit support ('credit_limit').
        It assumes the orchestrating layer has already validated external conditions
        (e.g., frozen status) and applies core input validation.

        Args:
            amount (Decimal): The intended monetary amount to be withdrawn.

        Returns:
            WithdrawalSimulationDTO: A detailed projection detailing authorization
                status, the necessity of utilizing an overdraft, and the precise
                monetary value required from the credit line.

        Raises:
            TypeError: If the provided amount is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
        """

        Account.validate_amount_entry(amount)
        authorized = amount <= self.available_funds
        balance = self.balance
        use_credit = None
        credit_required = None

        if self.credit_limit is not None:
            use_credit = amount > balance

            if use_credit:
                credit_required = amount - balance if balance > 0 else amount
            else:
                credit_required = Decimal("0.00")

        return WithdrawalSimulationDTO(
            authorized=authorized,
            use_credit=use_credit,
            credit_required=credit_required,
        )

    def withdrawal(self, amount: Decimal) -> tuple[LedgerEventDTO, ...]:
        """
        Orchestrates the secure withdrawal workflow.

        This template method enforces mandatory business invariants—specifically
        checking account active status and sufficient liquidity—before performing
        the state mutation. It handles the financial calculation and domain clock
        synchronization, concluding by delegating the semantic construction of
        ledger events to concrete subclasses via the `_compose_withdrawal_event` hook.

        Args:
            amount (Decimal): The strictly positive amount to withdraw.

        Returns:
            tuple[LedgerEventDTO, ...]: A chronological sequence of ledger events
                representing the transaction, including potential interest materialization.

        Raises:
            FrozenAccountError: If the account is locked and cannot dispense funds.
            InsufficientFundsError: If the requested amount exceeds the mathematically
                precise 'available_funds'.
            TypeError: If the provided amount is not a Decimal instance.
            ValueError: If the withdrawal amount is less than the MIN_ATM_TRANSACTION limit.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform withdraw operation on a frozen account"
            )

        if amount > self.available_funds:
            raise InsufficientFundsError(
                "The given amount exceeds the account's available funds"
            )

        Account.validate_amount_entry(amount)
        accrual_event = self._apply_accrual()
        start_balance = self._balance
        self._update_balance(-amount)

        events = self._compose_withdrawal_event(amount, accrual_event, start_balance)

        return events

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------

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
        self._last_balance_update = clock.get_today()

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

    # --------------------------------------------------------------------------
    # Abstract methods
    # --------------------------------------------------------------------------

    @abstractmethod
    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEventDTO | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEventDTO, ...]:
        """
        Abstract hook for constructing account-specific ledger events.

        Concrete subclasses must implement this to define the semantic sequencing
        of withdrawal events, ensuring that the audit trail accurately reflects
        the nature of the transaction (e.g., standard vs. overdraft usage) relative
        to the account's state before mutation.

        Args:
            amount (Decimal): The amount withdrawn.
            accrual_event (LedgerEventDTO | None): The materialized interest/yield event, if any.
            start_balance (Decimal): The authoritative balance prior to the withdrawal.

        Returns:
            tuple[LedgerEventDTO, ...]: The chronological sequence of finalized ledger events.
        """
        pass

    # --------------------------------------------------------------------------
    # Class methods
    # --------------------------------------------------------------------------

    @classmethod
    def from_snapshot(cls, data: AccountSnapshot) -> Account:
        """
        Factory method to reconstruct an Account instance (or subclass) from a persistence snapshot.

        Implements a Dispatcher Pattern using typed Data Transfer Objects:
        1. If called on the base Account class, it inspects the 'account_type' field
           in the snapshot and delegates instantiation to the correct subclass.
        2. If called on (or dispatched to) a subclass, it restores the common state
           attributes (balance, frozen status, and temporal state) and returns
           the fully hydrated instance.

        Args:
            data (AccountSnapshot): The immutable snapshot containing the exact
                account state retrieved from persistence.

        Returns:
            Account: A fully initialized instance of the specific Account subclass.

        Raises:
            ValueError: If the 'account_type' field in the snapshot is unknown.
        """
        if cls is Account:
            obj_type = data.account_type

            if obj_type:
                account_types = {
                    "CheckingAccount": CheckingAccount,
                    "SavingsAccount": SavingsAccount,
                }

                target_class = account_types.get(obj_type)

                if target_class:
                    return target_class.from_snapshot(data)

            raise ValueError(f"Unknown account type: {obj_type}")

        instance = cls(
            branch_code=data.branch_code,
            account_num=data.account_num,
        )
        instance._is_frozen = data.is_frozen
        instance._balance = data.balance
        instance._last_balance_update = data.last_balance_update

        return instance

    # --------------------------------------------------------------------------
    # Static methods
    # --------------------------------------------------------------------------

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


class SavingsAccount(Account):
    """
    Represents a standard Savings Account.

    A Savings Account only allows withdrawals up to the current positive balance.
    It does not support overdraft or credit limits. It implements the domain rule
    for positive remuneration, automatically calculating and applying daily yields
    (compound interest) to the balance based on elapsed calendar days.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------

    DAILY_EARNINGS_RATE: ClassVar[Decimal] = Decimal("0.00016")

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

    @property
    def credit_limit(self) -> None:
        """
        Explicitly declares that Savings Accounts do not support credit limits.

        Returns:
            None: Strictly evaluates to None, ensuring the domain orchestration
                safely bypasses credit-dependent business rules.
        """
        return None

    @property
    def available_credit(self) -> None:
        """
        Explicitly declares that Savings Accounts do not possess available credit.

        Returns:
            None: Strictly evaluates to None.
        """
        return None

    @property
    def available_funds(self) -> Decimal:
        """
        Calculates the true available funds, strictly limited to positive balances.

        Evaluates the current ledger balance combined with any pending yields
        that have accrued up to the current calendar day.

        Returns:
            Decimal: The total positive funds available for withdrawal.
        """
        return self._balance + self._pending_accrual

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
        time_delta = clock.get_today() - self._last_balance_update
        delta_days = time_delta.days
        new_amount = self._balance * (1 + self.DAILY_EARNINGS_RATE) ** delta_days
        earnings = new_amount - self._balance

        return earnings.quantize(Decimal("0.00"))

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------

    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEventDTO | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEventDTO, ...]:
        """
        Constructs the ledger event sequence for a savings account withdrawal.

        Since savings accounts do not support overdraft, this simply chains the
        optional accrual event (if materialized) with a standard withdrawal entry.

        Args:
            amount (Decimal): The amount withdrawn.
            accrual_event (LedgerEventDTO | None): The materialized yield event, if any.
            start_balance (Decimal): The balance prior to mutation.

        Returns:
            tuple[LedgerEventDTO, ...]: The sequence of events for the savings audit trail.
        """
        withdrawal_event = LedgerEventDTO(
            previous_balance=start_balance,
            amount=-amount,
            event_type=TransactionType.WITHDRAWAL,
        )
        if accrual_event:
            return (accrual_event, withdrawal_event)

        return (withdrawal_event,)

    # --------------------------------------------------------------------------
    # Class methods
    # --------------------------------------------------------------------------

    @classmethod
    def from_snapshot(cls, data: AccountSnapshot) -> SavingsAccount:
        """
        Reconstructs a SavingsAccount instance from a persistence snapshot.

        Extends the base Account hydration process by enforcing a strict
        domain integrity check: Savings accounts cannot be hydrated with
        a negative balance.

        Args:
            data (AccountSnapshot): The snapshot containing the account state.

        Returns:
            SavingsAccount: The fully hydrated savings account instance.

        Raises:
            RuntimeError: If the persistent state reflects a negative balance,
                indicating data corruption at the database level.
        """
        if data.balance < 0:
            raise RuntimeError(
                "SavingsAccount does not allow negative balance. Database state might be corrupted."
            )

        return cast(SavingsAccount, super().from_snapshot(data))


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

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------

    _OVERDRAFT_LIMIT: ClassVar[Decimal] = Decimal("3000.00")
    DAILY_INTEREST_RATE: ClassVar[Decimal] = Decimal("0.0025")

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

    @property
    def credit_limit(self) -> Decimal:
        """
        Exposes the static overdraft limit authorized for the checking account.

        Returns:
            Decimal: The absolute maximum overdraft limit defined by the
                account's operational configuration.
        """
        return self._OVERDRAFT_LIMIT

    @property
    def available_credit(self) -> Decimal:
        """
        Calculates the remaining available overdraft limit dynamically.

        If the account operates with a positive or zero balance, the full
        credit limit is preserved. If operating in the negative, the current
        ledger debt and any pending compound interest charges are seamlessly
        deducted from the total limit to reflect the true remaining capacity.

        This calculation enforces a strict non-negative floor policy. If accumulated
        interest charges exceed the remaining buffer of the overdraft limit, the
        returned value is saturated at zero to maintain domain semantic coherence.

        Returns:
            Decimal: The exact, temporally accurate monetary value
                available for credit operations.
        """
        min_available = Decimal("0.00")
        accrual = self._pending_accrual
        total_credit = self.credit_limit
        calculated_available = self._OVERDRAFT_LIMIT + self._balance + accrual
        available_credit = max(min_available, calculated_available)

        return total_credit if self._balance >= 0 else available_credit

    @property
    def available_funds(self) -> Decimal:
        """
        Calculates the true transaction capacity, including the overdraft limit.

        Evaluates the total purchasing power by seamlessly combining the account's
        real-time adjusted balance with its maximum authorized credit limit.
        Delegates the resolution of time-based adjustments (such as interest)
        directly to the 'balance' property to maintain single-responsibility.

        Guarantees that the purchasing power never drops below zero, even if
        unpaid accumulated interest charges exceed the maximum authorized overdraft
        limit, isolating the client's spending capacity from negative arithmetic spikes.

        Returns:
            Decimal: The total absolute monetary value available for disbursement.
        """
        min_available = Decimal("0.00")
        calculated_available = self.credit_limit + self.balance
        return max(min_available, calculated_available)

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

        time_delta = clock.get_today() - self._last_balance_update
        delta_days = time_delta.days

        interest = abs(self._balance) * (
            (1 + self.DAILY_INTEREST_RATE) ** delta_days - 1
        )

        return -interest.quantize(Decimal("0.00"))

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------

    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEventDTO | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEventDTO, ...]:
        """
        Constructs the ledger event sequence for a checking account, handling zero-crossing logic.

        This implementation handles the overdraft complexity by strategically splitting
        the transaction into 'Standard' and 'Overdraft' events when the requested
        amount crosses the zero-balance threshold.

        Args:
            amount (Decimal): The amount withdrawn.
            accrual_event (LedgerEventDTO | None): The materialized interest event, if any.
            start_balance (Decimal): The balance prior to mutation.

        Returns:
            tuple[LedgerEventDTO, ...]: The chronological audit trail accounting for both
                balance usage and credit limit consumption.
        """
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
            remaining = amount - start_balance
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
                    amount=-remaining,
                    event_type=TransactionType.OVERDRAFT_WITHDRAWAL,
                )
            )
        return tuple(events_list)
