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
from decimal import Decimal
from time import sleep

from domain.person import AccountCard


def welcome() -> None:
    """Displays the application's startup banner and initial instructions."""
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print(f"{' PyBank System ':*^43}")
    print()
    print(f"{'Escolha uma das opções no menu': ^43}")
    print("-" * 43)


def bye() -> None:
    """Displays the system shutdown message and exit banner."""
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print("*" * 10, "PyBank System", "*" * 10)
    print()
    print("Saindo do sistema", end="")
    for i in range(3):
        print(".", end=" ")
        sleep(0.5)


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
    sleep(3)
    print()


def show_statement(
    transactions: list[Decimal],
    balance: Decimal,
    overdraft_info: dict[str, Decimal] | None = None,
) -> None:
    """
    Renders the account bank statement to the terminal.

    Formats the transaction list with alignment and currency symbols, creating
    a readable report. Calculates appropriate labels (Deposit/Withdraw) based
    on the sign of the value.

    If `overdraft_info` is provided (typically for Checking Accounts), it
    appends the credit limit status to the footer.

    Args:
        transactions (list[Decimal]): List of transaction values.
        balance (Decimal): The final calculated balance.
        overdraft_info (dict[str, Decimal] | None, optional): A dictionary containing
            'total_limit' and 'remaining' keys to display overdraft details.
            Defaults to None.
    """
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print("\n" + "=" * 45)
    print(f"{'EXTRATO BANCÁRIO':^45}")
    print("=" * 45 + "\n")

    if not transactions:
        print("Nenhuma movimentação registrada")

    for i, value in enumerate(transactions, 1):
        label = "Saque" if value < 0 else "Depósito"
        print(f"{i:02d} {label:.<25} R$ {value:>10.2f}")

    print("\n" * 2)
    print(f"{'Saldo Atual':.<28} R$ {balance:>10.2f}")

    if overdraft_info:
        limit = overdraft_info["total_limit"]
        remaining = overdraft_info["remaining"]
        print(f"{'Limite Cheque Especial':.<28} R$ {limit:>10.2f}")

        if remaining < limit:
            print(f"{'Limite Disponível':.<28} R$ {remaining:>10.2f}")

    for i in range(5):
        print(".", end=" ")
        sleep(1)


def show_cards(client_cards: list[AccountCard]) -> None:
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    print(f"{' Seus cartões ':-^50}")
    for idx, card in enumerate(client_cards):
        print(f"{idx}: {card}")
