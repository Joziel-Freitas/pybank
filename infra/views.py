"""
Presentation Layer Module.

This module acts strictly as the 'View' in the MVC architecture. It is
responsible for formatting text, displaying banners, and rendering
user feedback to the terminal. It is an entirely 'dumb' layer, devoid
of business logic, error mapping, or decision-making, ensuring complete
decoupling from the application's internal states.
"""

import os
import subprocess
from datetime import datetime
from time import sleep
from typing import Any

from inputimeout import TimeoutOccurred, inputimeout
from settings import BANK_NAME
from shared.exceptions import InactiveUserError


def welcome() -> None:
    """Displays the application's startup banner and initial instructions."""
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print("*" * 45)
    print(f"{' PyBank System 3.0':*^45}")
    print("*" * 45)
    print(f"{'Escolha uma das opções no menu': ^45}")
    print("-" * 45)


# Dictionary mapping internal status keys to user-friendly messages


def controller_output(message: str) -> None:
    """
    Renders a standard system message to the terminal.

    Acts as the primary output channel for Controllers to communicate
    with the user. Includes a brief pause to ensure readability before
    the console is refreshed or the next prompt appears.

    Args:
        message (str): The pre-formatted text string to be displayed.
    """
    print()
    print(message)
    sleep(5)
    print()


def _balance_statement_header(account_info: dict[str, Any]) -> None:
    """
    Renders the standardized header for ATM balance and statement screens.

    Clears the terminal to provide a clean UX and displays the bank's layout,
    current timestamp, and the account holder's identifying information.

    Args:
        account_info (dict[str, Any]): A dictionary containing the account's
            metadata (holder_name, branch_code, account_num, account_type).
    """
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)

    account_type_mapper = {
        "CheckingAccount": "CONTA CORRENTE",
        "SavingsAccount": "CONTA POUPANÇA",
    }
    dt = datetime.now()
    date = dt.today().strftime("%d/%m/%Y")
    time = dt.time().strftime("%H:%M:%S")

    name = account_info["holder_name"]
    branch_code = account_info["branch_code"]
    account_num = account_info["account_num"]
    account_type = account_type_mapper[account_info["account_type"]]

    print(f"{BANK_NAME.upper():^45}")
    print(f"{date:<10} - {'AUTO-ATENDIMENTO':^23} - {time:>10}")
    print(f"{f'EXTRATO DE {account_type}':^45}")
    print(f"{'PARA SIMPLES CONFERÊNCIA':^45}")
    print()
    print(f"AGÊNCIA: {branch_code:<8} CONTA: {account_num:>20}")
    print(f"CLIENTE: {name.upper()[:36]}")
    print()


def _balance_statement_footer(account_info: dict[str, Any]) -> None:
    """
    Renders the standardized financial footer for ATM screens.

    Displays the current balance. If the account is a CheckingAccount with an
    active overdraft limit, it conditionally renders the total and available limits.

    Args:
        account_info (dict[str, Any]): A dictionary containing the account's
            financial data (balance, overdraft_limit, available_overdraft).
    """
    balance = account_info["balance"]
    limit = account_info["overdraft_limit"]
    available = account_info["available_overdraft"]

    print("\n" + "-" * 45)
    print(f"{'SALDO ATUAL:':<25} R$ {balance:>16.2f}")

    if limit is not None and available is not None:
        print(f"{'LIMITE CHEQUE ESPECIAL:':<25} R$ {limit:>16.2f}")
        print(f"{'LIMITE DISPONÍVEL:':<25} R$ {available:>16.2f}")

    print("-" * 45 + "\n")

    try:
        inputimeout(prompt="Pressione ENTER para sair...", timeout=90)
    except TimeoutOccurred as e:
        raise InactiveUserError("Inactivity timeout during statement view") from e


def show_balance_statement(
    account_info: dict[str, Any], transactions: tuple[dict[str, Any], ...] | None = None
) -> None:
    """
    Orchestrates the terminal view for both Balance and Statement operations.

    Acts as a dual-purpose render function based on the presence of the
    'transactions' argument:
    - If None: Renders a simple Balance view (Header + Footer).
    - If empty tuple: Renders the Statement view indicating no recent movements.
    - If populated tuple: Iterates through the transaction history, rendering
      the previous balance and the chronological ledger before the current totals.

    Args:
        account_info (dict[str, Any]): A dictionary representation of the AccountInfoDTO.
        transactions (tuple[dict[str, Any], ...] | None, optional): A chronological
            sequence of transaction dictionaries. Defaults to None.
    """
    _balance_statement_header(account_info)

    if not transactions:
        if transactions is not None:
            print(f"{'Nenhuma movimentação registrada no período':^45}")

        _balance_statement_footer(account_info)
        return

    transaction_type_map = {
        "DEPOSIT": "DEPOSITO",
        "WITHDRAWAL": "SAQUE",
        "OVERDRAFT_WITHDRAWAL": "SAQUE CHEQUE ESP.",
    }

    first_item = transactions[0]
    previous_balance = first_item["previous_balance"]
    first_date: datetime = first_item["created_at"].strftime("%d/%m")

    print(f"{'DATA':<6}{'HISTÓRICO':<22}{'VALOR':17}")
    print("\n" + "-" * 45)
    print(f"{first_date:<6}{'Saldo anterior':<22}{previous_balance:17.2f}")
    print("\n" + "-" * 45)

    for t in transactions:
        t_date = t["created_at"].strftime("%d/%m")
        t_type = transaction_type_map[t["transaction_type"]]
        t_amount = t["amount"]

        print(f"{t_date:<6}{t_type:<22} {t_amount:17.2f}")

    _balance_statement_footer(account_info)


def show_cards(client_cards: list[str]) -> None:
    """
    Renders a numbered list of available account cards to the terminal.

    This function acts purely as a display mechanism. It expects card data
    to be pre-formatted as strings, ensuring the presentation layer remains
    completely decoupled from internal domain objects (like AccountCard).

    Args:
        client_cards (list[str]): A list containing the string representation
                                  of each card available to the client.
    """
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print(f"{' Escolha seu cartão ':-^50}")
    for idx, card in enumerate(client_cards):
        print(f"{idx}: {card}")
