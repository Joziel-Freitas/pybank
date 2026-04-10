"""
Person and Client Domain Entities.

Defines the abstract base class Person, the concrete entity Client, and the
AccountCard value object. This module is responsible for validating core
personal attributes (Name, CPF, Birth Date), managing the client's associated
bank accounts, and storing access credentials (cards) for quick login.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import date
from typing import ClassVar, cast

from shared import validators
from shared.credentials import AccountCard
from shared.exceptions import (
    InvalidBirthDateError,
    InvalidCpfError,
    InvalidNameError,
    PersonCardNotFoundError,
    PersonDuplicatedCardError,
)


class Person(ABC):
    """
    Abstract Base Class for any person entity in the system.

    Handles the validation and management of core human attributes like
    name, birth date, and CPF (Brazilian Individual Taxpayer Registry).
    """

    MIN_AGE: ClassVar[int] = 18
    MAX_AGE: ClassVar[int] = 120

    # Type hints for the instance's variables
    _name: str
    _birth_date: date
    _cpf: str

    def __init__(self, name: str, birth_date: str | date, cpf: str):
        """
        Initializes a Person instance with validated attributes.

        Args:
            name (str): The person's full name.
            birth_date (str | date): The person's date of birth. Can be a 'dd/mm/yyyy'
                string (from user input) or a native date object (from the database).
            cpf (str): The person's CPF string (11 digits).

        Raises:
            InvalidNameError: If the name is invalid.
            InvalidBirthDateError: If the date format is wrong, in the future, or age is invalid.
            InvalidCpfError: If the CPF is mathematically invalid or poorly formatted.
        """
        self.name = name
        self._birth_date: date = Person.validate_birth_date(birth_date)
        self._cpf = Person.validate_cpf(cpf)

    def __repr__(self) -> str:
        """
        Returns the canonical string representation of the Person.

        Converts the internal date object back to the string format required
        by the __init__ method to ensure reproducibility.
        """
        class_name = type(self).__name__
        birth_date_str = self._birth_date.strftime("%d/%m/%Y")

        return f"{class_name}(name={self._name!r}, birth_date={birth_date_str!r}, cpf={self._cpf!r})"

    @property
    def name(self) -> str:
        """Returns the person's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        """
        Sets the person's name after validation.

        Args:
            name (str): The new name string.

        Raises:
            InvalidNameError: If the new name fails validation.
        """
        self._name = Person.validate_name(name)

    @property
    def birth_date(self) -> date:
        """Returns the person's birth date"""
        return self._birth_date

    @property
    def age(self) -> int:
        """Returns the person's current age in years."""
        return self._calculate_age(self._birth_date)

    @abstractmethod
    def has_account(self, card: AccountCard) -> bool:
        """
        Abstract method to check if a specific account belongs to this person.

        Concrete implementations must provide the logic to verify the existence
        of the provided account within the person's registry of associated accounts.

        Args:
            acc (Account): The account instance to verify.

        Returns:
            bool: True if the account is associated with this person, False otherwise.
        """
        raise NotImplementedError()

    @staticmethod
    def validate_name(name: str) -> str:
        """
        Validates the provided name string using Regular Expressions.

        Rules:
        - Must be a string.
        - Must have at least three characters.
        - Must contain only alphabetic characters (including accents).
        - Cannot contain numbers or special symbols.
        - Cannot start or end with a blank space.
        - Cannot contain consecutive blank spaces.

        Args:
            name (str): The name to validate.

        Returns:
            str: The validated name.

        Raises:
            InvalidNameError: If any validation rule is violated.
        """
        if not isinstance(name, str):
            raise InvalidNameError(f"Value {name} must be a string")

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
    def validate_birth_date(birth_date: str | date) -> date:
        """
        Validates a given birth date against domain business rules.

        This method acts as a flexible facade, accepting both formatted strings
        (from user input) and native date objects (from the database adapter).
        It enforces the following strict rules:
        1. If it's a string, it must be convertible from the 'dd/mm/yyyy' format.
        2. Cannot be a future date.
        3. The resulting age must be within the allowed range (`Person.MIN_AGE` to `Person.MAX_AGE`).

        Args:
            birth_date (str | date): The date of birth to validate.

        Returns:
            date: The validated native Python date object.

        Raises:
            InvalidBirthDateError: If the format is incorrect, the date is in the future,
                the calculated age is outside the valid limits, or the type is invalid.
        """
        try:
            match birth_date:
                case str():
                    date_obj = validators.validate_date_format(birth_date)
                case date():
                    date_obj = birth_date
                case _:
                    raise TypeError(
                        f"Expected str or date. Got {type(birth_date).__name__}"
                    )

            today = date.today()
            if date_obj > today:
                raise ValueError("Date of birth cannot be in the future")

            age = Person._calculate_age(date_obj)

            if not Person.MIN_AGE <= age <= Person.MAX_AGE:
                raise ValueError(
                    f"Invalid age. Age must be between {Person.MIN_AGE} and {Person.MAX_AGE} (inclusive)"
                )

            return date_obj
        except (ValueError, TypeError) as e:
            raise InvalidBirthDateError(
                f"Value {birth_date} is invalid for date of birth. Cause: {e}"
            ) from e

    @staticmethod
    def _calculate_age(birth_date: date) -> int:
        """
        Calculates the person's age in years based on the birth date.
        Returns:
            int: The calculated age.
        """
        today = date.today()
        age = today.year - birth_date.year

        # Adjust age if the birth date for the current year has not yet passed
        if (today.day, today.month) < (birth_date.day, birth_date.month):
            age -= 1

        return age

    @staticmethod
    def validate_cpf(cpf: str) -> str:
        """
        Validates the CPF by delegating mathematical verification to infrastructure.

        Acts as a Domain Facade. It catches low-level technical errors (ValueError,
        TypeError) from the shared validator and translates them into a formal
        'InvalidCpfError', providing the necessary context for the Domain layer.

        Args:
            cpf (str): The CPF string to validate.

        Returns:
            str: The validated CPF string.

        Raises:
            InvalidCpfError: If the CPF is technically invalid or poorly formatted,
                encapsulating the original cause.
        """
        try:
            return validators.validate_cpf(cpf)
        except (ValueError, TypeError) as e:
            raise InvalidCpfError(f"Person CPF is invalid: {e}")

    def to_dict(self) -> dict:
        """
        Serializes the person's core data into a dictionary format.

        Retains the native Python `date` object for `birth_date`, delegating
        the SQL format translation to the database driver (e.g., PyMySQL).

        Returns:
            dict: A dictionary containing 'name', 'cpf', and 'birth_date'.
        """
        return {
            "name": self._name,
            "birth_date": self._birth_date,
            "cpf": self._cpf,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Person:
        """
        Factory method that reconstructs a Person (or subclass) instance from a dictionary.

        Expects a native Python `date` object from the database adapter and passes
        it directly to the class constructor, bypassing string formatting gymnastics.
        This ensures all original business validations are executed cleanly.

        Args:
            data (dict): The dictionary containing raw user data.

        Returns:
            Person: A fully initialized instance of the class (or subclass).
        """
        return cls(name=data["name"], birth_date=data["birth_date"], cpf=data["cpf"])


class Client(Person):
    """
    A concrete implementation of Person, representing a bank client.

    Manages a unique set of quick-access cards (AccountCard) for streamlined
    authentication. Acts as a credential holder, completely decoupled from
    direct Account object ownership.
    """

    _account_cards: set[AccountCard]

    def __init__(self, name: str, birth_date: str | date, cpf: str):
        """
        Initializes a Client instance.

        Initializes the client's wallet of account cards as empty.
        """
        super().__init__(name, birth_date, cpf)
        self._account_cards = set()

    def __eq__(self, other: object) -> bool:
        """
        Determines equality between Client instances based on their unique CPF.

        Two Client objects are considered equal if they share the same CPF,
        regardless of other attributes. This definition of equality is consistent
        with the `__hash__` method, ensuring reliable behavior when Client objects
        are stored in hash-based collections such as sets or used as dictionary keys.
        """
        if isinstance(other, Client):
            return self._cpf == other._cpf
        return False

    def __hash__(self):
        """
        Returns a hash value for the Client instance based on its unique CPF.

        This ensures that Client objects can be used reliably as keys in
        dictionaries or stored in sets. The hash is consistent with the
        `__eq__` method, which also defines equality by CPF, guaranteeing
        that two Client instances with the same CPF are treated as identical
        in hash-based collections.
        """
        return hash(self._cpf)

    def __contains__(self, card: AccountCard) -> bool:
        """
        Allows checking if an account is registered to this client using the `in` operator.

        The check leverages the O(1) average time complexity of Python's Set
        membership test (Hash Table look-up).
        """
        if isinstance(card, AccountCard):
            return card in self._account_cards
        return False

    @property
    def cpf(self) -> str:
        """Returns the client's unique identifier (the CPF)."""
        return self._cpf

    @property
    def cards(self) -> list[AccountCard]:
        """
        Returns a sorted list of the client's saved account cards.

        Converts the internal set to a list to facilitate iteration in UI menus.
        """
        return sorted(list(self._account_cards), key=lambda c: c.account_num)

    def to_dict(self) -> dict:
        """
        Serializes the client data, extending the Person serialization.

        Includes a list of serialized AccountCards ('account_cards') to persist
        the client's wallet of saved credentials.

        Returns:
            dict: The complete client state dictionary, including personal info and cards.
        """
        data_dict = super().to_dict()
        data_dict["account_cards"] = [asdict(card) for card in self._account_cards]
        return data_dict

    @classmethod
    def from_dict(cls, data: dict) -> Client:
        """
        Reconstructs a Client instance and their associated account cards.

        Uses the parent class logic to restore personal attributes and then
        iteratively deserializes the list of 'account_cards' to repopulate
        the client's wallet.

        Args:
            data (dict): The dictionary containing client data and the list of cards.

        Returns:
            Client: The restored Client object with all its cards.
        """
        instance = cast(Client, super().from_dict(data))
        cards_list = data.get("account_cards", [])
        instance._account_cards = {AccountCard(**card) for card in cards_list}
        return instance

    def has_account(self, card: AccountCard) -> bool:
        """Checks if a specific card is registered to the client (alias for `__contains__`)."""
        return card in self

    def add_card(self, acc_card: AccountCard):
        """
        Stores a new access card in the client's wallet.

        Args:
            acc_card (AccountCard): The card object containing credentials.

        Raises:
            TypeError: If the input is not an instance of AccountCard.
            PersonDuplicatedCardError: If the card is already present in the wallet.
        """
        if not isinstance(acc_card, AccountCard):
            raise TypeError(
                f"Invalid card type. Expected AccountCard, got {type(acc_card).__name__}"
            )
        if acc_card in self._account_cards:
            raise PersonDuplicatedCardError(
                " Card already present in the Client's card collection"
            )

        self._account_cards.add(acc_card)

    def remove_card(self, acc_card: AccountCard):
        """
        Removes a specific card from the client's wallet.

        Args:
            acc_card (AccountCard): The card to be removed.

        Raises:
            TypeError: If the input is not an instance of AccountCard.
            PersonCardNotFoundError: If the card is not found in the wallet.
        """
        if not isinstance(acc_card, AccountCard):
            raise TypeError(
                f"Invalid card type. Expected AccountCard, got {type(acc_card).__name__}"
            )
        if acc_card not in self._account_cards:
            raise PersonCardNotFoundError(
                "Card not found in the Client's card collection"
            )

        self._account_cards.remove(acc_card)
