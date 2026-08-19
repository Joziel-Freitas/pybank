"""Account Management Module.

Defines the abstract base class Account and its concrete implementations:
SavingsAccount and CheckingAccount. This module orchestrates the core domain logic
of the banking system, including account initialization, strict structural validation,
state-safe withdrawal simulations, and time-based financial adjustments (accruals).

It employs Domain-Driven Design (DDD) principles to encapsulate primitive value
validations within Value Objects (BranchCode, AccountNumber, Money) and return immutable
domain events (LedgerEvent) and financial projections (AccountFinancial), ensuring
a robust, append-only audit trail for persistence and clean layer isolation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import ClassVar, cast

from domain.snapshots import AccountSnapshot
from domain.types import AccrualType, TransactionType
from domain.value_objects import (
    AccountFinancial,
    AccountNumber,
    BranchCode,
    LedgerEvent,
    Money,
    WithdrawalSimulation,
)
from shared import clock, verify
from shared.exceptions import (
    AccountStateTransitionError,
    FrozenAccountError,
    InsufficientFundsError,
    NotEmptyAccountError,
)

# =====================================================================
# Account (ABC)
# =====================================================================


class Account(ABC):
    """Abstract Base Class (ABC) for all bank accounts.

    Enforces mandatory attributes, temporal state tracking, and polymorphic
    mathematical behaviors (deposit, withdrawal, accruals) across all concrete
    account types. Acts as the orchestrator for state mutation, ensuring that
    any financial change simultaneously updates the domain clock.

    Attributes:
        _branch_code (BranchCode): The validated bank branch code Value Object.
        _account_num (AccountNumber): The validated unique account number Value Object.
        _is_frozen (bool): The operational status of the account (True if blocked).
        _ledger_balance (Decimal): The historical, unadjusted balance retrieved directly
            from the accounting records.
        _last_balance_update (date): The exact temporal anchor of the last
            balance mutation, used for calculating precise daily accruals.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, branch_code: BranchCode, account_num: AccountNumber) -> None:
        """Initializes a new Account instance with validated Value Objects.

        Sets the initial financial state to zero and initializes the domain
        clock to the current system date. The account is created in an active
        (unfrozen) state by default.

        Args:
            branch_code (BranchCode): The branch code Value Object.
            account_num (AccountNumber): The unique account number Value Object.

        Raises:
            TypeError: If incoming parameters fail type verification.
        """
        verify.verify_instance(branch_code, BranchCode)
        verify.verify_instance(account_num, AccountNumber)

        self._branch_code = branch_code
        self._account_num = account_num
        self._is_frozen = False
        self._ledger_balance = Decimal("0.00")
        self._last_balance_update = clock.get_today()

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns the canonical string representation of the Account instance.

        Returns:
            str: Diagnostic state representation containing internal ledger properties.
        """
        class_name = type(self).__name__

        return (
            f"{class_name}("
            f"branch_code={self._branch_code.value!r}, "
            f"account_num={self._account_num.value!r}, "
            f"balance={self._ledger_balance!r}, "
            f"last_balance_update={self._last_balance_update!r})"
        )

    def __eq__(self, other: object) -> bool:
        """Determines equality between Account instances based on identity coordinates.

        Two Account objects are considered equal if they share the same branch code
        and account number Value Objects, regardless of other state metrics.

        Args:
            other (object): The target object to compare against.

        Returns:
            bool: True if identity Value Objects match perfectly, False otherwise.
        """
        if isinstance(other, Account):
            return (self._branch_code, self._account_num) == (
                other._branch_code,
                other._account_num,
            )
        return False

    def __hash__(self) -> int:
        """Returns a hash value for the Account instance based on its business identity.

        Guarantees safe collection hashing behavior when stored inside sets or
        dictionary key lookups, mirroring the logic found in __eq__.

        Returns:
            int: The generated hash footprint of the routing variables.
        """
        return hash((self._branch_code, self._account_num))

    # --------------------------------------------------------------------------
    # Properties (Public Read Model Interface)
    # --------------------------------------------------------------------------
    @property
    def branch_code(self) -> BranchCode:
        """Returns the branch code Value Object of the account.

        Returns:
            BranchCode: The structural branch location identifier.
        """
        return self._branch_code

    @property
    def account_num(self) -> AccountNumber:
        """Returns the account number Value Object.

        Returns:
            AccountNumber: The unique account numeric index.
        """
        return self._account_num

    @property
    def financial_info(self) -> AccountFinancial:
        """Projects the complete, mathematically accurate financial state of the account.

        Acts as a strict Read-Only facade (Lazy Materialization). By orchestrating
        subclass-specific implementations of credit limits, accruals, and available
        funds through internal properties, this method enforces the Information Expert
        principle. It centralizes the construction of the AccountFinancial value object,
        ensuring outer layers receive a uniform, predictable, and temporally accurate
        snapshot of the account's true state.

        Returns:
            AccountFinancial: An immutable, composed value object detailing the ledger
                balance, pending accruals, true current balance, operational limits,
                and the total purchasing power at the exact moment of invocation.
        """
        accrual = self._pending_accrual
        accrual_type = None

        if accrual:
            accrual_type = AccrualType.YIELD if accrual > 0 else AccrualType.INTEREST

        return AccountFinancial(
            ledger_balance=self._ledger_balance,
            accrual=accrual,
            balance=self._balance,
            accrual_type=accrual_type,
            credit_limit=self._credit_limit,
            available_credit=self._available_credit,
            available_balance=self._available_funds,
            issue_at=clock.get_today(),
        )

    # --------------------------------------------------------------------------
    # Internal Properties (Protected Hook Interface for Subclasses)
    # --------------------------------------------------------------------------
    @property
    def _balance(self) -> Decimal:
        """Returns the true, temporally accurate balance of the account.

        Combines the raw ledger balance with any pending time-based accruals
        (yields or interest) up to the current moment.

        Returns:
            Decimal: The high-precision true balance amount.
        """
        return self._ledger_balance + self._pending_accrual

    @property
    @abstractmethod
    def _credit_limit(self) -> Decimal | None:
        """Defines the maximum credit threshold granted to the account.

        Acts as an explicit contract for subclasses to declare their support
        for credit products. Enforces the Open/Closed Principle by allowing
        the base orchestrator to safely evaluate credit availability without
        type-checking concrete implementations.

        Returns:
            Decimal | None: The absolute monetary value of the credit limit,
                or None if the account type does not support credit operations.
        """

    @property
    @abstractmethod
    def _available_credit(self) -> Decimal | None:
        """Calculates the real-time remaining credit available for transactions.

        Acts as a dynamic projection that accounts for current ledger balances
        and any pending time-based charges (e.g., compound interest) that
        actively consume the credit limit.

        Returns:
            Decimal | None: The precise monetary value still available from the
                credit limit, or None if credit operations are not supported.
        """

    @property
    @abstractmethod
    def _pending_accrual(self) -> Decimal:
        """Represents the raw monetary value of time-based financial adjustments.

        This abstract property enforces the Template Method Pattern, requiring
        concrete account subclasses to define the specific state of their
        pending mathematics (e.g., compound interest for overdrafts or yield
        for savings) based on the elapsed calendar days since the last balance update.

        Returns:
            Decimal: The accumulated accrual amount. Expected to be positive for
                yields, negative for interest charges, and exactly Decimal("0.00")
                if no accruals apply.
        """

    @property
    @abstractmethod
    def _available_funds(self) -> Decimal:
        """Calculates the true, mathematically precise transaction capacity of the account.

        Acts as a dynamic projection of the account's purchasing power at the exact
        moment of invocation. It enforces the Information Expert principle by combining
        the authoritative ledger balance with any pending time-based accruals and
        account-specific credit rules.

        Returns:
            Decimal: The absolute monetary value available for disbursement.
        """

    # --------------------------------------------------------------------------
    # Public API (Orchestrators & Domain Mutators)
    # --------------------------------------------------------------------------
    def to_snapshot(self) -> AccountSnapshot:
        """Generates a persistence snapshot of the current account state.

        Packages the raw ledger state, operational flags, and a polymorphic
        'account_type' identifier (e.g., 'CheckingAccount') into a strictly typed,
        immutable domain snapshot. This isolates the Domain from infrastructure schemas
        while providing the Repository with everything needed for storage and future
        hydration.

        Returns:
            AccountSnapshot: An immutable snapshot containing the account's base
                identifiers, financial ledger balance, temporal anchor, and class type.
        """
        return AccountSnapshot(
            branch_code=self._branch_code.value,
            account_num=self._account_num.value,
            account_type=type(self).__name__,
            is_frozen=self._is_frozen,
            balance=self._ledger_balance,
            last_balance_update=self._last_balance_update,
        )

    def freeze(self) -> None:
        """Transitions the account into a frozen (inactive) state.

        A frozen account operates in a strict Read-Only mode. It preserves
        its current balance and history but outright rejects any state-mutating
        financial operations (like deposits or withdrawals) until explicitly unfrozen.

        Raises:
            AccountStateTransitionError: If the account is already frozen.
        """
        if self._is_frozen:
            raise AccountStateTransitionError("This account is already frozen")

        self._is_frozen = True

    def unfreeze(self) -> None:
        """Restores the account to an active, operational state.

        Lifts the Read-Only restriction, allowing standard balance-mutating
        financial operations to resume.

        Raises:
            AccountStateTransitionError: If the account is not frozen (already active).
        """
        if not self._is_frozen:
            raise AccountStateTransitionError("This account is not frozen")

        self._is_frozen = False

    def close(self) -> None:
        """Enforces domain invariants for closing an account.

        Raises:
            FrozenAccountError: If the account is currently frozen/locked.
            NotEmptyAccountError: If the financial balance is not zero.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to close a frozen account. Unfreeze it first."
            )

        if self._balance != 0:
            raise NotEmptyAccountError(
                "The account cannot be closed because it has a non-zero balance"
            )

    def deposit(self, amount: Money) -> tuple[LedgerEvent, ...]:
        """Performs a standard deposit operation.

        Enforces the strict domain rule that an account must be active to receive funds.
        Validates the input Money Value Object, processes any pending time-based accruals,
        and increments the account balance. This implementation serves as the default
        behavior for all concrete account types.

        Args:
            amount (Money): The monetary Value Object representing the deposit amount.

        Returns:
            tuple[LedgerEvent, ...]: A tuple containing the domain events that represent
                the financial operations generated by this transaction (e.g., the deposit
                itself, potentially preceded by a yield or interest materialization).
                Each event accurately captures its preceding balance point.

        Raises:
            FrozenAccountError: If the account is currently frozen.
            TypeError: If the amount is not an instance of Money Value Object.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform deposit operation on a frozen account"
            )

        verify.verify_instance(amount, Money)

        inner_amount = amount.value
        accruals_event = self._apply_accrual()
        start_balance = self._ledger_balance
        self._update_balance(inner_amount)

        deposit_event = LedgerEvent(
            previous_balance=start_balance,
            amount=inner_amount,
            event_type=TransactionType.DEPOSIT,
        )

        if accruals_event:
            return (accruals_event, deposit_event)

        return (deposit_event,)

    def simulate_withdrawal(self, amount: Money) -> WithdrawalSimulation:
        """Simulates the financial projection of a withdrawal without mutating state.

        Acts as a universal financial oracle for all account types. It evaluates
        transaction viability strictly based on the polymorphic '_available_funds'
        and explicitly checks the subclass contracts for credit support ('_credit_limit').
        If the transaction exceeds total available capacity (unauthorized), credit projection
        fields strictly evaluate to None to preserve domain semantic integrity.

        Args:
            amount (Money): The intended monetary Value Object to be evaluated.

        Returns:
            WithdrawalSimulation: A detailed projection detailing authorization status,
                the necessity of utilizing an overdraft, and the precise monetary value
                required from the credit line.

        Raises:
            TypeError: If the provided amount is not an instance of Money Value Object.
        """
        verify.verify_instance(amount, Money)
        inner_amount = amount.value
        authorized = inner_amount <= self._available_funds
        balance = self._balance
        use_credit = None
        credit_required = None

        if authorized and self._credit_limit is not None:
            use_credit = inner_amount > balance

            if use_credit:
                credit_required = (
                    inner_amount - balance if balance > 0 else inner_amount
                )
            else:
                credit_required = Decimal("0.00")

        return WithdrawalSimulation(
            authorized=authorized,
            use_credit=use_credit,
            credit_required=credit_required,
        )

    def withdrawal(self, amount: Money) -> tuple[LedgerEvent, ...]:
        """Orchestrates the secure withdrawal workflow.

        This template method enforces mandatory business invariants—specifically checking
        account active status and sufficient liquidity—before performing the state mutation.
        It handles financial calculation and domain clock synchronization, concluding by
        delegating the semantic construction of ledger events to concrete subclasses
        via the `_compose_withdrawal_event` hook.

        Args:
            amount (Money): The monetary Value Object to withdraw.

        Returns:
            tuple[LedgerEvent, ...]: A chronological sequence of ledger events representing
                the transaction, including potential interest materialization.

        Raises:
            FrozenAccountError: If the account is locked and cannot dispense funds.
            InsufficientFundsError: If the requested amount exceeds '_available_funds'.
            TypeError: If the provided amount is not an instance of Money Value Object.
        """
        if self._is_frozen:
            raise FrozenAccountError(
                "Impossible to perform withdraw operation on a frozen account"
            )

        verify.verify_instance(amount, Money)

        inner_amount = amount.value

        if inner_amount > self._available_funds:
            raise InsufficientFundsError(
                "The given amount exceeds the account's available funds"
            )

        accrual_event = self._apply_accrual()
        start_balance = self._ledger_balance
        self._update_balance(-inner_amount)

        events = self._compose_withdrawal_event(
            inner_amount, accrual_event, start_balance
        )

        return events

    # --------------------------------------------------------------------------
    # Abstract Hook Methods (Internal Orchestration)
    # --------------------------------------------------------------------------
    @abstractmethod
    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEvent | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEvent, ...]:
        """Abstract hook for constructing account-specific ledger events.

        Concrete subclasses must implement this to define the semantic sequencing
        of withdrawal events, ensuring that the audit trail accurately reflects
        the nature of the transaction (e.g., standard vs. overdraft usage) relative
        to the account's state before mutation.

        Args:
            amount (Decimal): The primitive numeric amount withdrawn.
            accrual_event (LedgerEvent | None): The materialized interest/yield event, if any.
            start_balance (Decimal): The authoritative balance prior to the withdrawal.

        Returns:
            tuple[LedgerEvent, ...]: The chronological sequence of finalized ledger events.
        """

    # --------------------------------------------------------------------------
    # Protected Methods (Internal Helpers)
    # --------------------------------------------------------------------------
    def _update_balance(self, amount: Decimal) -> None:
        """Mutates the account balance and synchronizes the domain clock.

        This protected method acts as the sole access point for state mutation
        regarding the financial balance. It guarantees that any change to the funds
        (whether through standard transactions or accrual materialization) simultaneously
        updates the internal tracker, ensuring the domain maintains an accurate,
        authoritative record of its own temporal state.

        Args:
            amount (Decimal): The exact monetary value to be added to the balance.
                Negative values are inherently supported for debits/withdrawals.
        """
        self._ledger_balance += amount
        self._last_balance_update = clock.get_today()

    def _apply_accrual(self) -> LedgerEvent | None:
        """Materializes pending accruals into the account balance and ledger.

        Acts as an internal orchestrator that evaluates if any time-based
        financial adjustments (yields or charges) have accrued. If a non-zero
        adjustment exists, it mutates the account state via `_update_balance`
        and generates an immutable ledger event for persistence.

        Returns:
            LedgerEvent | None: A domain event representing the applied accrual event
                ready for persistence, or None if no time has elapsed or the calculated
                amount is zero.
        """
        accrual = self._pending_accrual

        if not accrual:
            return None

        start_balance = self._ledger_balance
        self._update_balance(accrual)

        return LedgerEvent(
            previous_balance=start_balance,
            amount=accrual,
            event_type=AccrualType.YIELD if accrual > 0 else AccrualType.INTEREST,
        )

    # --------------------------------------------------------------------------
    # Class Factory Methods
    # --------------------------------------------------------------------------
    @classmethod
    def from_snapshot(cls, data: AccountSnapshot) -> Account:
        """Factory method to reconstruct an Account instance from a persistence snapshot.

        Implements a Dispatcher Pattern using typed domain snapshots:
        1. If called on the base Account class, it inspects the 'account_type' field
           in the snapshot and delegates instantiation to the correct subclass.
        2. If called on a subclass, it restores the common state attributes
           (balance, frozen status, and temporal state) and returns the fully hydrated instance.

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

        branch_code = BranchCode(data.branch_code)
        account_num = AccountNumber(data.account_num)

        instance = cls(
            branch_code=branch_code,
            account_num=account_num,
        )
        instance._is_frozen = data.is_frozen
        instance._ledger_balance = data.balance
        instance._last_balance_update = data.last_balance_update

        return instance


# =====================================================================
# SavingsAccount
# =====================================================================


class SavingsAccount(Account):
    """Represents a standard Savings Account.

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
    # Internal Properties (Subclass Implementation)
    # --------------------------------------------------------------------------
    @property
    def _credit_limit(self) -> None:
        """Explicitly declares that Savings Accounts do not support credit limits.

        Returns:
            None: Strictly evaluates to None, ensuring the domain orchestration
                safely bypasses credit-dependent business rules.
        """
        return None

    @property
    def _available_credit(self) -> None:
        """Explicitly declares that Savings Accounts do not possess available credit.

        Returns:
            None: Strictly evaluates to None.
        """
        return None

    @property
    def _available_funds(self) -> Decimal:
        """Calculates the true available funds, strictly limited to positive balances.

        Evaluates the current ledger balance combined with any pending yields
        that have accrued up to the current calendar day.

        Returns:
            Decimal: The total positive funds available for withdrawal.
        """
        return self._ledger_balance + self._pending_accrual

    @property
    def _pending_accrual(self) -> Decimal:
        """Represents the positive yield generated by the savings balance.

        Derived dynamically by applying daily compound interest over the
        positive balance for the number of full calendar days elapsed
        since the last update.

        Returns:
            Decimal: The precise yield amount pending materialization,
                strictly formatted to two decimal places.
        """
        time_delta = clock.get_today() - self._last_balance_update
        delta_days = time_delta.days
        new_amount = self._ledger_balance * (1 + self.DAILY_EARNINGS_RATE) ** delta_days
        earnings = new_amount - self._ledger_balance

        return earnings.quantize(Decimal("0.00"))

    # --------------------------------------------------------------------------
    # Protected Hook Implementations
    # --------------------------------------------------------------------------
    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEvent | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEvent, ...]:
        """Constructs the ledger event sequence for a savings account withdrawal.

        Since savings accounts do not support overdraft, this simply chains the
        optional accrual event (if materialized) with a standard withdrawal entry.

        Args:
            amount (Decimal): The primitive numeric amount withdrawn.
            accrual_event (LedgerEvent | None): The materialized yield event, if any.
            start_balance (Decimal): The balance prior to mutation.

        Returns:
            tuple[LedgerEvent, ...]: The sequence of events for the savings audit trail.
        """
        withdrawal_event = LedgerEvent(
            previous_balance=start_balance,
            amount=-amount,
            event_type=TransactionType.WITHDRAWAL,
        )
        if accrual_event:
            return (accrual_event, withdrawal_event)

        return (withdrawal_event,)

    # --------------------------------------------------------------------------
    # Class Factory Methods
    # --------------------------------------------------------------------------
    @classmethod
    def from_snapshot(cls, data: AccountSnapshot) -> SavingsAccount:
        """Reconstructs a SavingsAccount instance from a persistence snapshot.

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


# =====================================================================
# CheckingAccount
# =====================================================================


class CheckingAccount(Account):
    """Represents a Checking Account with an integrated overdraft limit.

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
    # Internal Properties (Subclass Implementation)
    # --------------------------------------------------------------------------
    @property
    def _credit_limit(self) -> Decimal:
        """Exposes the static overdraft limit authorized for the checking account.

        Returns:
            Decimal: The absolute maximum overdraft limit defined by the
                account's operational configuration.
        """
        return self._OVERDRAFT_LIMIT

    @property
    def _available_credit(self) -> Decimal:
        """Calculates the remaining available overdraft limit dynamically.

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
        total_credit = self._credit_limit
        calculated_available = self._OVERDRAFT_LIMIT + self._ledger_balance + accrual
        available_credit = max(min_available, calculated_available)

        return total_credit if self._ledger_balance >= 0 else available_credit

    @property
    def _available_funds(self) -> Decimal:
        """Calculates the true transaction capacity, including the overdraft limit.

        Evaluates the total purchasing power by seamlessly combining the account's
        real-time adjusted balance with its maximum authorized credit limit.
        Delegates the resolution of time-based adjustments (such as interest)
        directly to the '_balance' property to maintain single-responsibility.

        Guarantees that the purchasing power never drops below zero, even if
        unpaid accumulated interest charges exceed the maximum authorized overdraft
        limit, isolating the client's spending capacity from negative arithmetic spikes.

        Returns:
            Decimal: The total absolute monetary value available for disbursement.
        """
        min_available = Decimal("0.00")
        calculated_available = self._credit_limit + self._balance
        return max(min_available, calculated_available)

    @property
    def _pending_accrual(self) -> Decimal:
        """Represents the debt charges applied to utilized overdraft limits.

        If the account balance is positive or exactly zero, this property
        evaluates to zero. If operating in the negative, it reflects the
        daily compound interest applied over the absolute debt for the
        number of full calendar days elapsed.

        Returns:
            Decimal: The exact interest charge as a negative value, rounded
                to two decimal places, or Decimal("0.00") if no debt exists.
        """
        if self._ledger_balance >= 0:
            return Decimal("0.00")

        time_delta = clock.get_today() - self._last_balance_update
        delta_days = time_delta.days

        interest = abs(self._ledger_balance) * (
            (1 + self.DAILY_INTEREST_RATE) ** delta_days - 1
        )

        return -interest.quantize(Decimal("0.00"))

    # --------------------------------------------------------------------------
    # Protected Hook Implementations
    # --------------------------------------------------------------------------
    def _compose_withdrawal_event(
        self,
        amount: Decimal,
        accrual_event: LedgerEvent | None,
        start_balance: Decimal,
    ) -> tuple[LedgerEvent, ...]:
        """Constructs the ledger event sequence for a checking account, handling zero-crossing logic.

        This implementation handles the credit complexity by strategically splitting
        the transaction into 'Standard' and 'Credit' events when the requested
        amount crosses the zero-balance threshold.

        Args:
            amount (Decimal): The primitive numeric amount withdrawn.
            accrual_event (LedgerEvent | None): The materialized interest event, if any.
            start_balance (Decimal): The balance prior to mutation.

        Returns:
            tuple[LedgerEvent, ...]: The chronological audit trail accounting for both
                balance usage and credit limit consumption.
        """
        events_list: list[LedgerEvent] = []

        if accrual_event:
            events_list.append(accrual_event)

        # Case 1: Fully covered by positive balance (including exact withdrawal)
        if start_balance >= amount:
            events_list.append(
                LedgerEvent(
                    previous_balance=start_balance,
                    amount=-amount,
                    event_type=TransactionType.WITHDRAWAL,
                )
            )
        # Case 2: Fully operating within credit limits (including starting exactly at zero)
        elif start_balance <= 0:
            events_list.append(
                LedgerEvent(
                    previous_balance=start_balance,
                    amount=-amount,
                    event_type=TransactionType.CREDIT_WITHDRAWAL,
                )
            )
        # Case 3: Zero-crossing (Partial standard, partial credit)
        else:
            remaining = amount - start_balance
            events_list.append(
                LedgerEvent(
                    previous_balance=start_balance,
                    amount=-start_balance,
                    event_type=TransactionType.WITHDRAWAL,
                )
            )
            events_list.append(
                LedgerEvent(
                    previous_balance=Decimal("0.00"),
                    amount=-remaining,
                    event_type=TransactionType.CREDIT_WITHDRAWAL,
                )
            )
        return tuple(events_list)
