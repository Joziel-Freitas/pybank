"""
Presentation Layer Module.

This module acts strictly as the 'View' in the MVC architecture. It is
responsible for formatting text, displaying banners, and rendering
user feedback to the terminal. It is an entirely 'dumb' layer, devoid
of business logic, error mapping, or decision-making, ensuring complete
decoupling from the application's internal states.
"""

import textwrap
from datetime import datetime
from decimal import Decimal
from time import sleep
from typing import Any

from infra import terminal_input
from settings import BANK_NAME, INACTIVITY_TIMEOUT, TOTAL_TIMEOUT
from shared import clock
from shared.exceptions import InactiveUserError

SCREEN_WIDTH = 45

TRANSLATION_MAP = {
    "financial_events": {
        "DEPOSIT": "DEPOSITO",
        "WITHDRAWAL": "SAQUE",
        "CREDIT_WITHDRAWAL": "SAQUE CRÉDITO ESP.",
        "YIELD": "RENDIMENTOS",
        "INTEREST": "JUROS CRÉDITO ESP.",
    },
    "account_type": {
        "CheckingAccount": "CONTA CORRENTE",
        "SavingsAccount": "CONTA POUPANÇA",
    },
}


def welcome() -> None:
    """Displays the application's startup banner and initial instructions."""
    print("\033[H\033[2J", end="", flush=True)
    print("*" * 45)
    print(f"{' PyBank System 3.0 ':*^45}")
    print("*" * 45)
    print(f"{'Escolha uma das opções no menu': ^45}")
    print("-" * 45)


def _format_currency(value_raw: Decimal) -> str:
    """
    Formats a numeric monetary value into the Brazilian currency standard.

    Converts the raw value into a string with exactly two decimal places,
    replacing the standard decimal point with a comma (e.g., '2,00' or '150,50').

    Args:
        value_raw (Decimal): The raw monetary value to be formatted.

    Returns:
        str: The formatted currency string.
    """
    fmt_value = f"{value_raw:_.2f}".replace(".", ",").replace("_", ".")
    return fmt_value


def system_output(
    message: str,
    wait: bool = False,
    clean: bool = False,
    kwargs: dict[str, Any] | None = None,
) -> None:
    """
    Renders a standardized, formatted system message to the terminal.

    Acts as the primary output channel for the application. It applies
    presentation rules (like currency formatting and text wrapping to
    fit the standard ATM screen width), formats the final string, and
    handles terminal screen state and timing.

    Args:
        message (str): The pre-formatted text string template.
        wait (bool): If True, pauses execution for 5 seconds to ensure
            readability of important messages. Defaults to False.
        clean (bool): If True, clears the terminal screen before rendering
            the message. Defaults to False.
        kwargs (dict, optional): Dynamic values for the message template.
            Defaults to None.
    """
    msg = message

    if kwargs:
        for k, v in kwargs.items():
            if isinstance(v, Decimal):
                fmt_v = _format_currency(v)
                kwargs[k] = fmt_v

        msg = msg.format(**kwargs)

    if clean:
        print("\033[2J\033[3J\033[H", end="", flush=True)

    print()

    wrapped_lines = textwrap.wrap(msg, width=SCREEN_WIDTH)
    for line in wrapped_lines:
        print(line)

    if wait:
        for _ in range(5):
            print("." * 9, end="", flush=True)
            sleep(1)


def confirm_deposit(deposit_info: dict[str, Any], amount: Decimal) -> None:
    """
    Renders the deposit confirmation screen for the ATM terminal.

    Displays a formatted, read-only summary of the target account and the
    transaction amount. Applies dynamic abbreviation to the account holder's
    middle names to ensure visual compliance with the 45-character screen limit.
    Relies on the upstream Domain layer to provide pre-sanitized sensitive
    data (e.g., masked CPF).

    Args:
        deposit_info (dict[str, Any]): A dictionary representation of the
            DepositTargetDTO containing the target routing and identity data.
        amount (Decimal): The exact financial value to be deposited.
    """
    raw_name = deposit_info["holder_name"]
    raw_cpf = deposit_info["holder_cpf"]
    branch_code = deposit_info["branch_code"]
    account_num = deposit_info["account_num"]
    account_type = TRANSLATION_MAP["account_type"][deposit_info["account_type"]]

    name = raw_name
    names_list = raw_name.split()
    if len(names_list) > 2:
        first_name = names_list[0]
        last_name = names_list[-1]

        edited_list = [
            n if n in (first_name, last_name) or len(n) <= 3 else n[0] + "."
            for n in names_list
        ]

        name = " ".join(edited_list)

    cpf = f"{raw_cpf[:3]}.{raw_cpf[3:6]}.{raw_cpf[6:9]}-{raw_cpf[9:]}"

    print("-" * 45)
    print(f"{'DEPÓSITO':^45}")
    print("-" * 45)
    print(f"FAVORECIDO: {name[:32]}")
    print(f"CPF DO FAVORECIDO: {cpf}")
    print(f"AGÊNCIA: {branch_code}")
    print(f"CONTA: {account_num} | {account_type}")
    print(f"VALOR: R$ {_format_currency(amount)}")


def _balance_statement_header(account_info: dict[str, Any]) -> None:
    """
    Renders the standardized header for ATM balance and statement screens.

    Clears the terminal to provide a clean UX and displays the bank's layout,
    current timestamp, and the account holder's identifying information.

    Args:
        account_info (dict[str, Any]): A dictionary containing the account's
            metadata (holder_name, branch_code, account_num, account_type).
    """
    print("\033[2J\033[3J\033[H", end="", flush=True)

    now = clock.get_now()
    date = now.strftime("%d/%m/%Y")
    time = now.strftime("%H:%M:%S")

    name = account_info["holder_name"]
    branch_code = account_info["branch_code"]
    account_num = account_info["account_num"]
    account_type = TRANSLATION_MAP["account_type"][account_info["account_type"]]

    print(f"{BANK_NAME.upper():^45}")
    print(f"{date:<10}{' -  AUTO-ATENDIMENTO  - ':^25}{time:>10}")
    print(f"{f'EXTRATO DE {account_type}':^45}")
    print(f"{'PARA SIMPLES CONFERÊNCIA':^45}")
    print()
    print(f"AGÊNCIA: {branch_code:<8} CONTA: {account_num:>20}")
    print(f"CLIENTE: {name.upper()[:36]}")
    print()


def _balance_statement_footer(financial_info: dict[str, Any]) -> None:
    """
    Renders the standardized financial footer for ATM screens.

    Displays the current balance and the calculated available balance. If
    pending accruals exist (yield or interest), they are displayed. If the
    account has an active overdraft limit, it conditionally renders the total
    and available limits.

    Args:
        financial_info (dict[str, Any]): A dictionary containing the account's
            financial data (balance, accrual, available_balance, limits, etc.).
    """
    accrual = financial_info["accrual"]
    ledger_balance = financial_info["ledger_balance"]
    available_balance = financial_info["available_balance"]
    issue_at = financial_info["issue_at"].strftime("%d/%m/%Y")
    raw_accrual_type = financial_info["accrual_type"]
    accrual_type = None
    if raw_accrual_type:
        accrual_type = TRANSLATION_MAP["financial_events"][
            financial_info["accrual_type"]
        ]

    credit_limit = financial_info["credit_limit"]
    available_credit = financial_info["available_credit"]

    print("\n" + "-" * 45)
    if accrual_type:
        print(f"{f'{accrual_type}:':<25} R$ {_format_currency(accrual):>16}")

    print(f"{'SALDO EM CONTA:':<25} R$ {_format_currency(ledger_balance):>16}")

    if credit_limit is not None and available_credit is not None:
        print(
            f"{'LIMITE CRÉDITO ESPECIAL:':<25} R$ {_format_currency(credit_limit):>16}"
        )
        print(f"{'LIMITE DISPONÍVEL:':<25} R$ {_format_currency(available_credit):>16}")

    print(
        f"{'SALDO TOTAL DISPONÍVEL:':<25} R$ {_format_currency(available_balance):>16}"
    )
    print(f"{'VALOR DISPONÍVEL EM:':<25}{issue_at:>20}")

    print("-" * 45 + "\n")

    try:
        terminal_input.custom_input(
            prompt="Pressione ENTER para sair...",
            inactive_timeout=INACTIVITY_TIMEOUT,
            total_timeout=TOTAL_TIMEOUT,
        )
    except TimeoutError as e:
        raise InactiveUserError("Inactivity timeout during statement view") from e


def views_balance_statement(
    base_summary: dict[str, Any],
    financial_info: dict[str, Any],
    financial_events: tuple[dict[str, Any], ...] | None = None,
) -> None:
    """
    Orchestrates the terminal view for both Balance and Statement operations.

    Acts as a dual-purpose render function based on the presence of the
    'financial_events' argument:
    - If None: Renders a simple Balance view (Header + Footer).
    - If empty tuple: Renders the Statement view indicating no recent movements.
    - If populated tuple: Iterates through the ledger history, rendering
      the previous balance and the chronological events before the current totals.

    Args:
        account_summary (dict[str, Any]): A dictionary representation of the AccountSummaryDTO.
        financial_events (tuple[dict[str, Any], ...] | None, optional): A chronological
            sequence of ledger event dictionaries. Defaults to None.
    """
    _balance_statement_header(base_summary)

    if not financial_events:
        if financial_events is not None:
            print(f"{'Nenhuma movimentação registrada no período':^45}")

        _balance_statement_footer(financial_info)
        return

    first_item = financial_events[0]
    previous_balance = first_item["previous_balance"]
    first_date: datetime = first_item["created_at"].strftime("%d/%m")

    print(f"{'DATA':<6}{'HISTÓRICO':<22}{'VALOR':>17}")
    print("\n" + "-" * 45)
    print(
        f"{first_date:<6}{'Saldo anterior':<22}{_format_currency(previous_balance):>17}"
    )
    print("\n" + "-" * 45)

    for event in financial_events:
        t_date = event["created_at"].strftime("%d/%m")
        t_type = TRANSLATION_MAP["financial_events"][event["event_type"]]
        t_amount = event["amount"]

        print(f"{t_date:<6}{t_type:<22} {_format_currency(abs(t_amount)):>17}")

    _balance_statement_footer(financial_info)


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
    print("\033[2J\033[3J\033[H", end="", flush=True)
    print(f"{' Escolha seu cartão ':-^45}")
    for idx, card in enumerate(client_cards):
        print(f"{idx}: {card}")
