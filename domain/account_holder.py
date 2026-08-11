"""Account Holder Domain Entity Module.

Defines the concrete entity AccountHolder. This module is responsible for managing
the account holder's identity and storing access credentials (cards) for quick login.

Following Domain-Driven Design (DDD), this entity delegates primitive value validations
(Name, CPF, Birth Date) to specialized Value Objects, operating independently of database
schemas or presentation layers.
"""

from __future__ import annotations

from dataclasses import asdict

from domain.snapshots import AccountHolderSnapshot
from domain.value_objects import CPF, AccountHolderName, BirthDate
from shared import verify
from shared.credentials import AccountCard

# =====================================================================
# Account Holder Entity
# =====================================================================


class AccountHolder:
    """Represents a bank customer identity.

    Encapsulates a customer's core identity bound to immutable Value Objects
    (AccountHolderName, CPF, BirthDate) while holding the collection of stored
    quick-access cards associated with that customer.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self, name: AccountHolderName, cpf: CPF, birth_date: BirthDate
    ) -> None:
        """Initializes an AccountHolder instance with validated Value Objects.

        Args:
            name (AccountHolderName): The validated account holder's full name VO.
            cpf (CPF): The mathematically verified CPF Value Object.
            birth_date (BirthDate): The validated birth date Value Object.

        Raises:
            TypeError: If any parameter fails type verification against its respective Value Object.
        """
        verify.verify_instance(name, AccountHolderName)
        verify.verify_instance(cpf, CPF)
        verify.verify_instance(birth_date, BirthDate)

        self._name = name
        self._cpf = cpf
        self._birth_date = birth_date
        self._account_cards: set[AccountCard] = set()

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns the canonical string representation of the AccountHolder.

        Returns:
            str: Diagnostic state representation containing core customer identity variables.
        """
        class_name = type(self).__name__
        birth_date_str = str(self._birth_date)

        return f"{class_name}(name={self._name.value!r}, birth_date={birth_date_str!r}, cpf={self._cpf.value!r})"

    def __eq__(self, other: object) -> bool:
        """Determines equality between AccountHolder instances based on their unique CPF Value Object.

        Args:
            other (object): The target object to compare against.

        Returns:
            bool: True if identity CPF objects match, False otherwise.
        """
        if isinstance(other, AccountHolder):
            return self._cpf == other._cpf
        return False

    def __hash__(self) -> int:
        """Returns a hash value based on the unique CPF entity key.

        Enables the entity object to be stored and managed inside hash-based collections.

        Returns:
            int: The generated hash footprint of the core CPF Value Object.
        """
        return hash(self._cpf)

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------
    @property
    def name(self) -> AccountHolderName:
        """Returns the account holder's name Value Object.

        Returns:
            AccountHolderName: The validated name Value Object.
        """
        return self._name

    @name.setter
    def name(self, name: AccountHolderName) -> None:
        """Sets the account holder's name Value Object after type verification.

        Args:
            name (AccountHolderName): The new validated name Value Object.

        Raises:
            TypeError: If the incoming parameter is not an instance of AccountHolderName.
        """
        verify.verify_instance(name, AccountHolderName)
        self._name = name

    @property
    def birth_date(self) -> BirthDate:
        """Returns the account holder's birth date Value Object.

        Returns:
            BirthDate: The immutable birth date Value Object.
        """
        return self._birth_date

    @property
    def cpf(self) -> CPF:
        """Returns the account holder's unique identifier (the CPF Value Object).

        Returns:
            CPF: The clean, mathematically verified CPF Value Object.
        """
        return self._cpf

    @property
    def cards(self) -> list[AccountCard]:
        """Returns a shallow copy of the stored account cards.

        Converts the internal set into a new list to prevent external callers
        from mutating the entity's internal collection directly.

        Returns:
            list[AccountCard]: A clean list representation containing valid credential cards.
        """
        return list(self._account_cards)

    # --------------------------------------------------------------------------
    # Public API (Orchestrators)
    # --------------------------------------------------------------------------
    def to_snapshot(self) -> AccountHolderSnapshot:
        """Creates a persistence snapshot representing the current entity state.

        Acts as a secure Write Model for the Anti-Corruption Layer (ACL).
        Extracts primitive values from Value Objects to package into an immutable
        domain snapshot for persistence layers.

        Returns:
            AccountHolderSnapshot: An immutable payload containing primitive values.
        """
        cards = [asdict(c) for c in self._account_cards]

        return AccountHolderSnapshot(
            name=self._name.value,
            cpf=self._cpf.value,
            birth_date=self._birth_date.value,
            cards=cards,
        )

    # --------------------------------------------------------------------------
    # Class methods
    # --------------------------------------------------------------------------
    @classmethod
    def from_snapshot(cls, data: AccountHolderSnapshot) -> AccountHolder:
        """Rehydrates an AccountHolder aggregate from a persistence snapshot.

        Restores the core entity state by encapsulating primitive snapshot values
        into Value Objects, and rebuilds the collection of associated cards.

        Args:
            data (AccountHolderSnapshot): The strictly typed, immutable snapshot.

        Returns:
            AccountHolder: The fully restored domain aggregate ready for operations.
        """
        name = AccountHolderName(data.name)
        cpf = CPF(data.cpf)
        birth_date = BirthDate(data.birth_date)
        instance = cls(name=name, cpf=cpf, birth_date=birth_date)

        # Restore the stored account cards
        cards_list = data.cards
        instance._account_cards = {AccountCard(**card) for card in cards_list}

        return instance
