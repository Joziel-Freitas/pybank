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
from shared import validators
from shared.credentials import AccountCard
from shared.exceptions import (
    AccountHolderCardNotFoundError,
    AccountHolderDuplicatedCardError,
    InvalidBirthDateError,
    InvalidCpfError,
    InvalidNameError,
)


class AccountHolder:
    """
    The core entity representing a bank customer.

    Manages the identity validations (CPF, Name, Age) and a unique set of
    quick-access cards (AccountCard) for streamlined authentication. Acts as
    a credential holder, decoupled from direct Account object ownership.
    """

    MIN_AGE: ClassVar[int] = 18
    MAX_AGE: ClassVar[int] = 120

    # Type hints for the instance's variables
    _name: str
    _cpf: str
    _birth_date: date
    _account_cards: set[AccountCard]

    def __init__(self, name: str, cpf: str, birth_date: date):
        """
        Initializes an AccountHolder instance with validated attributes.

        Args:
            name (str): The account holder's full name.
            cpf (str): The account holder's CPF string (11 digits).
            birth_date (date): The native Python date object representing the date of birth.

        Raises:
            InvalidNameError: If the name is invalid.
            InvalidBirthDateError: If the date is in the future or age is invalid.
            InvalidCpfError: If the CPF is mathematically invalid or poorly formatted.
        """
        self.name = name
        self._cpf = AccountHolder.validate_cpf(cpf)
        self._birth_date: date = AccountHolder.validate_birth_date(birth_date)
        self._account_cards = set()

    def __repr__(self) -> str:
        """
        Returns the canonical string representation of the AccountHolder.
        """
        class_name = type(self).__name__
        birth_date_str = self._birth_date.strftime("%d/%m/%Y")

        return f"{class_name}(name={self._name!r}, birth_date={birth_date_str!r}, cpf={self._cpf!r})"

    def __eq__(self, other: object) -> bool:
        """
        Determines equality between AccountHolder instances based on their unique CPF.
        """
        if isinstance(other, AccountHolder):
            return self._cpf == other._cpf
        return False

    def __hash__(self) -> int:
        """
        Returns a hash value based on the unique CPF, allowing the object to be
        used reliably in hash-based collections (like sets).
        """
        return hash(self._cpf)

    def __contains__(self, card: AccountCard) -> bool:
        """
        Allows checking if an account card is registered using the `in` operator.
        Leverages the O(1) average time complexity of Python's Set membership test.
        """
        if isinstance(card, AccountCard):
            return card in self._account_cards
        return False

    @property
    def name(self) -> str:
        """Returns the person's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        """Sets the person's name after validation."""
        self._name = AccountHolder.validate_name(name)

    @property
    def birth_date(self) -> date:
        """Returns the person's birth date."""
        return self._birth_date

    @property
    def age(self) -> int:
        """Returns the person's current age in years."""
        return self._calculate_age(self._birth_date)

    @property
    def cpf(self) -> str:
        """Returns the account holder's unique identifier (the CPF)."""
        return self._cpf

    @property
    def cards(self) -> list[AccountCard]:
        """
        Returns a list of the account holder's saved account cards.

        Converts the internal set to a list to prevent direct mutation of
        the internal state from external callers.
        """
        return list(self._account_cards)

    def has_account(self, card: AccountCard) -> bool:
        """Checks if a specific card is registered to the account holder."""
        return card in self

    def add_card(self, acc_card: AccountCard) -> None:
        """
        Stores a new access card in the account holder's wallet.

        Args:
            acc_card (AccountCard): The card object containing credentials.

        Raises:
            TypeError: If the input is not an instance of AccountCard.
            AccountHolderDuplicatedCardError: If the card is already present.
        """
        if not isinstance(acc_card, AccountCard):
            raise TypeError(
                f"Invalid card type. Expected AccountCard, got {type(acc_card).__name__}"
            )
        if acc_card in self._account_cards:
            raise AccountHolderDuplicatedCardError(
                "Card already present in the account holder's card collection"
            )

        self._account_cards.add(acc_card)

    def remove_card(self, acc_card: AccountCard) -> None:
        """
        Removes a specific card from the account holder's wallet.

        Args:
            acc_card (AccountCard): The card to be removed.

        Raises:
            TypeError: If the input is not an instance of AccountCard.
            AccountHolderCardNotFoundError: If the card is not found in the wallet.
        """
        if not isinstance(acc_card, AccountCard):
            raise TypeError(
                f"Invalid card type. Expected AccountCard, got {type(acc_card).__name__}"
            )
        if acc_card not in self._account_cards:
            raise AccountHolderCardNotFoundError(
                "Card not found in the account holder's card collection"
            )

        self._account_cards.remove(acc_card)

    @staticmethod
    def validate_name(name: str) -> str:
        """
        Validates the provided name string using Regular Expressions.
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
        Validates the CPF by delegating mathematical verification to infrastructure.
        Acts as a Domain Facade, catching ValueError and raising InvalidCpfError.
        """
        try:
            return validators.validate_cpf(cpf)
        except ValueError as e:
            raise InvalidCpfError(f"Person CPF is invalid: {e}")

    @staticmethod
    def validate_birth_date(birth_date: date) -> date:
        """
        Validates a given birth date against domain business rules.
        """
        verify.verify_instance(birth_date, date)

        try:
            today = date.today()
            if birth_date > today:
                raise ValueError("Date of birth cannot be in the future")

            age = AccountHolder._calculate_age(birth_date)

            if not AccountHolder.MIN_AGE <= age <= AccountHolder.MAX_AGE:
                raise ValueError(
                    f"Invalid age. Age must be between {AccountHolder.MIN_AGE} and {AccountHolder.MAX_AGE} (inclusive)"
                )

            return birth_date
        except ValueError as e:
            raise InvalidBirthDateError(
                f"Value {birth_date} is invalid for date of birth. Cause: {e}"
            ) from e

    @staticmethod
    def _calculate_age(birth_date: date) -> int:
        """
        Calculates the person's age in years based on the birth date.
        """
        today = date.today()
        age = today.year - birth_date.year

        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age -= 1

        return age

    def to_dict(self) -> dict:
        """
        Serializes the account holder data into a standard dictionary.

        Includes a list of serialized AccountCards ('account_cards') to persist
        the account holder's wallet of saved credentials.

        Returns:
            dict: The complete state dictionary, including personal info and cards.
        """
        return {
            "name": self._name,
            "birth_date": self._birth_date,
            "cpf": self._cpf,
            "account_cards": [asdict(card) for card in self._account_cards],
        }

    @classmethod
    def from_dict(cls, data: dict) -> AccountHolder:
        """
        Reconstructs an AccountHolder instance and their associated account cards.

        Args:
            data (dict): The dictionary containing account holder data and cards.

        Returns:
            AccountHolder: The restored AccountHolder object with all its cards.
        """
        # Reconstruct the base instance running all domain validations via __init__
        instance = cls(
            name=data["name"], cpf=data["cpf"], birth_date=data["birth_date"]
        )

        # Populate the wallet
        cards_list = data.get("account_cards", [])
        instance._account_cards = {AccountCard(**card) for card in cards_list}

        return instance
