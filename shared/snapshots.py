"""
Shared Persistence Snapshots Module.

This module defines strict, immutable data structures used exclusively for
transporting Domain Entity states to the Infrastructure (Repository) layer.
Acting as a Write Model in the Anti-Corruption Layer (ACL), Snapshots guarantee
that the database receives typed, verified data without relying on fragile
generic dictionaries or breaking entity encapsulation.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AccountHolderSnapshot:
    """
    Persistence snapshot for the AccountHolder aggregate.

    Captures the complete state of the AccountHolder entity, including both
    core Personally Identifiable Information (PII) and their associated
    quick-access account cards. This immutable Data Transfer Object serves
    as a strict contract between the Domain and Infrastructure layers,
    ensuring secure database insertion and accurate entity hydration.

    Attributes:
        name (str): The full name of the account holder.
        cpf (str): The 11-digit CPF string.
        birth_date (date): The birth date of the account holder.
        cards (list[dict[str, str]]): A serialized list of the holder's associated
            account cards, representing their quick-access credentials.
    """

    name: str
    cpf: str
    birth_date: date
    cards: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """
    Persistence snapshot for the Account entity hierarchy.
    Reflects the exact financial and configurational state needed for storage.
    """

    branch_code: str
    account_num: str
    account_type: str
    is_frozen: bool
    balance: Decimal
    last_balance_update: date
