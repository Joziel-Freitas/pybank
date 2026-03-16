"""
Shared Credentials and Access Tokens Module.

This module defines immutable Value Objects used for identification and
authentication across the banking system.

By extracting these structures from the core domain entities (Bank and Person),
we prevent circular dependencies and establish a clear boundary for data that
travels between the Interface layer (Controllers) and the Domain/Infrastructure layers.

Classes:
    AccountCard: Represents a saved physical/virtual card in a client's wallet,
                 used for quick identification.
    AuthToken: Represents a verified session token issued by the Bank, used to
               authorize sensitive financial operations.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountCard:
    """
    Immutable value object representing the credentials for quick account access.
    Acts as a 'saved card' in the client's wallet.
    """

    cpf: str
    branch_code: str
    account_num: str

    def __str__(self) -> str:
        """User-friendly string representation for UI/Menus."""
        return f"CPF: {self.cpf} | Ag: {self.branch_code} Conta: {self.account_num}"


@dataclass(frozen=True)
class AuthToken:
    """
    Represents a secure access token for stateless authentication.

    Acts as an immutable digital badge for client operations. It utilizes a
    cryptographic signature to ensure payload integrity, preventing unauthorized
    tampering or lateral movement between accounts.

    Attributes:
        cpf (str): The client's unique identifier.
        branch_code (str): The branch code associated with the session.
        account_num (str): The account number associated with the session.
        signature (str): A cryptographic hash (e.g., HMAC-SHA256) generated exclusively
            by the Bank's internal secret key, proving the authenticity of the token.
    """

    cpf: str
    branch_code: str
    account_num: str
    signature: str
