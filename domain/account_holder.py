"""
Account Holder Domain Entity Module.

Defines the concrete entity AccountHolder and its associated value objects.
This module is responsible for validating core personal attributes (Name, CPF,
Birth Date), managing the account holder's identity, and storing access
credentials (cards) for quick login.

Following Domain-Driven Design (DDD), this entity encapsulates all rules
pertinent to the bank's client, operating independently of database schemas
or presentation layers.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date
from typing import ClassVar

from infra import verify
from shared import clock, validators
from shared.credentials import AccountCard
from shared.exceptions import (
    InvalidBirthDateError,
    InvalidCpfError,
    InvalidNameError,
)
from shared.snapshots import AccountHolderSnapshot

# =====================================================================
# Global Helpers (Procedural Level)
# =====================================================================


def _calculate_age(birth_date: date) -> int:
    """
    Module-level helper that calculates the current age represented by a birth date.

    Uses the application's canonical business date clock to evaluate true calendar
    years elapsed, taking into account whether the anniversary day has passed.

    Args:
        birth_date (date): The native date object representing the target birth date.

    Returns:
        int: The computed current chronological age of the account holder.
    """
    today = clock.get_today()
    age = today.year - birth_date.year

    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1

    return age


# =====================================================================
# Account Holder Entity
# =====================================================================


class AccountHolder:
    """
    Represents a bank customer identity.

    Encapsulates the business rules that validate a customer's identity
    (Name, CPF and Birth Date) while holding the collection of stored
    quick-access cards associated with that customer.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    MIN_AGE: ClassVar[int] = 18
    MAX_AGE: ClassVar[int] = 120

    _name: str
    _cpf: str
    _birth_date: date
    _account_cards: set[AccountCard]

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, name: str, cpf: str, birth_date: date):
        """
        Initializes an AccountHolder instance with validated attributes.

        Args:
            name (str): The account holder's full name.
            cpf (str): The account holder's CPF string (11 digits).
            birth_date (date): The native Python date object representing the date of birth.

        Raises:
            InvalidNameError: If the name breaks structural domain rules.
            InvalidBirthDateError: If the date is in the future or age boundaries overflow.
            InvalidCpfError: If the CPF is mathematically invalid or poorly formatted.
        """
        self.name = name
        self._cpf = AccountHolder.validate_cpf(cpf)
        self._birth_date = AccountHolder.validate_birth_date(birth_date)
        self._account_cards = set()

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """
        Returns the canonical string representation of the AccountHolder.

        Returns:
            str: Diagnostic state representation containing core customer identity variables.
        """
        class_name = type(self).__name__
        birth_date_str = self._birth_date.strftime("%d/%m/%Y")

        return f"{class_name}(name={self._name!r}, birth_date={birth_date_str!r}, cpf={self._cpf!r})"

    def __eq__(self, other: object) -> bool:
        """
        Determines equality between AccountHolder instances based on their unique CPF.

        Args:
            other (object): The target object to compare against.

        Returns:
            bool: True if identity coordinates match, False otherwise.
        """
        if isinstance(other, AccountHolder):
            return self._cpf == other._cpf
        return False

    def __hash__(self) -> int:
        """
        Returns a hash value based on the unique CPF entity key.

        Enables the entity object to be stored and managed inside hash-based collections.

        Returns:
            int: The generated hash footprint of the core CPF routing string.
        """
        return hash(self._cpf)

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """
        Returns the account holder's name.

        Returns:
            str: The structural string holding the full name metrics.
        """
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        """
        Sets the account holder's name after passing validation rules.

        Args:
            name (str): The new unverified string payload proposed for mutation.

        Raises:
            InvalidNameError: If the string fails format and length thresholds.
        """
        self._name = AccountHolder.validate_name(name)

    @property
    def birth_date(self) -> date:
        """
        Returns the account holder's birth date.

        Returns:
            date: The immutable native calendar birth date marker.
        """
        return self._birth_date

    @property
    def cpf(self) -> str:
        """
        Returns the account holder's unique identifier (the CPF).

        Returns:
            str: The clean 11-digit mathematical identity key.
        """
        return self._cpf

    @property
    def cards(self) -> list[AccountCard]:
        """
        Returns a shallow copy of the stored account cards.

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
        """
        Creates a persistence snapshot representing the current entity state.

        Acts as a secure Write Model for the Anti-Corruption Layer (ACL).
        Packages the core Personally Identifiable Information (PII) into an
        immutable, strictly typed Data Transfer Object, ensuring the
        infrastructure layer receives exactly what it needs for database
        insertion without exposing the entity's internal mechanisms.

        Returns:
            AccountHolderSnapshot: An immutable payload containing the primitive
                values required to persist this account holder.
        """
        cards = [asdict(c) for c in self._account_cards]

        return AccountHolderSnapshot(
            name=self._name, cpf=self._cpf, birth_date=self.birth_date, cards=cards
        )

    # --------------------------------------------------------------------------
    # Class methods
    # --------------------------------------------------------------------------
    @classmethod
    def from_snapshot(cls, data: AccountHolderSnapshot) -> AccountHolder:
        """
        Rehydrates an AccountHolder aggregate from a persistence snapshot.

        Restores the core entity state by passing the primitive values through
        the standard domain validations (via __init__), and subsequently
        rebuilds the collection of associated AccountCard value objects.

        Args:
            data (AccountHolderSnapshot): The strictly typed, immutable snapshot
                containing the account holder's identity data and saved cards.

        Returns:
            AccountHolder: The fully restored domain aggregate ready for operations.
        """
        instance = cls(name=data.name, cpf=data.cpf, birth_date=data.birth_date)

        # Restore the stored account cards
        cards_list = data.cards
        instance._account_cards = {AccountCard(**card) for card in cards_list}

        return instance

    # --------------------------------------------------------------------------
    # Static methods (Validations)
    # --------------------------------------------------------------------------
    @staticmethod
    def validate_name(name: str) -> str:
        """
        Validates an account holder name against the domain business rules.

        Enforces strict baseline thresholds: minimum length, alphabetical composition
        (including native accented maps), and single space block separation rules.

        Args:
            name (str): The raw string representing the name proposed for validation.

        Returns:
            str: The validated pristine name string matching domain parameters.

        Raises:
            TypeError: If incoming parameter inputs violate explicit string type hints.
            InvalidNameError: If string length drops below 3 or format constraints collapse.
        """
        verify.verify_instance(name, str)

        if len(name) < 3:
            raise InvalidNameError(f"Value '{name}' must have at least three letters")

        # Pattern: Accented letters, separated by a maximum of one space.
        pattern = r"^[A-Za-zÀ-ÿ]+(?: [A-Za-zÀ-ÿ]+)*$"

        if not re.match(pattern, name):
            raise InvalidNameError(
                f"Value '{name}' is invalid. Use only letters and single spaces."
            )

        return name

    @staticmethod
    def validate_cpf(cpf: str) -> str:
        """
        Delegates the mathematical CPF validation to the shared validator engine.

        Translates standard runtime value failures into specialized domain-level exceptions
        to insulate corporate architecture tracking loops.

        Args:
            cpf (str): The raw character string representing the individual's key registry.

        Returns:
            str: The unmasked validated digit identity footprint string.

        Raises:
            InvalidCpfError: If structural or mathematical digit checksum evaluations fail.
        """
        try:
            return validators.validate_cpf(cpf)
        except ValueError as e:
            raise InvalidCpfError(f"Account Holder CPF is invalid: {e}")

    @staticmethod
    def validate_birth_date(birth_date: date) -> date:
        """
        Validates a birth date against the account holder age business rules.

        The validation enforces that the birth date is not in the future and
        that the resulting age falls within the institutional corporate boundaries.

        Args:
            birth_date (date): The raw temporal execution date object proposed for insertion.

        Returns:
            date: The verified immutable date footprint object.

        Raises:
            TypeError: If parameter inputs conflict with runtime date instance definitions.
            InvalidBirthDateError: If chronological boundaries overflow or date inputs point to future markers.
        """
        verify.verify_instance(birth_date, date)

        try:
            today = clock.get_today()
            if birth_date > today:
                raise ValueError("Date of birth cannot be in the future")

            age = _calculate_age(birth_date)

            if not AccountHolder.MIN_AGE <= age <= AccountHolder.MAX_AGE:
                raise ValueError(
                    f"Invalid age. Age must be between {AccountHolder.MIN_AGE} and {AccountHolder.MAX_AGE} (inclusive)"
                )

            return birth_date
        except ValueError as e:
            raise InvalidBirthDateError(
                f"Value {birth_date} is invalid for date of birth. Cause: {e}"
            ) from e
