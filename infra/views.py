"""
Presentation Layer Module.

This module is responsible for all terminal output formatting, user feedback messages,
and visual delimiters. It acts as the 'View' in the MVC architecture, keeping the
business logic (Controllers) decoupled from the specific output mechanism (Print/Console).
"""

import os
import subprocess
from decimal import Decimal
from time import sleep

from domain.account import Account
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
method_mappers = {
    "menu": {
        "security": "Sessão encerrada por questão de segurança. Voltando à tela inicial",
        "exit": "Sessão encerrada. Voltando à tela inicial",
        "cancel": "Operação cancelada. Voltando ao menu anterior",
        "credentials": "Erro na autenticação dos dados. Voltando ao menu anterior",
    },
    "auth": {
        True: "Autenticado com sucesso",
        False: "Falha na autenticação. Insira os dados novamente",
    },
    "access": {
        True: "Acesso Concedido",
        False: "Senha incorreta. Acesso Negado",
        "last": "Atenção: Última tentativa. Se errar a senha, a conta será bloqueada",
        "blocked": "Conta BLOQUEADA por segurança. Desbloqueie a conta para usá-la novamente",
    },
    "transaction": {
        "min_value": f"Valor mínimo para transação: {Account.MIN_ATM_TRANSACTION}",
        True: "Transação realizada com sucesso",
        False: "Valor insuficiente em conta. Para sacar esse valor, autorize o uso do limite especial",
        None: "O valor excede o montante em conta. Transação não autorizada",
    },
    "client": {
        "new": "Bem vindo ao PyBank. Faça o seu cadastro",
        "not_new": "Bem vindo de volta ao PyBank",
    },
    "new_account": {
        True: "Conta registrada com sucesso",
        "duplicated": "Essa conta já se encontra registrada no sistema. Crie uma nova conta",
        "password": "Falha ao registrar sua senha. Tente novamente",
        False: "Erro ao registrar sua conta. Tente novamente",
    },
    "prompt_password": {
        "1": "Insira sua senha",
        "2": "Insira novamente sua senha",
        False: "As senhas não conferem. Tente novamente",
    },
    "update_password": {True: "Senha alterada com sucesso"},
    "unfreeze": {
        True: "Conta desbloqueada com sucesso",
        "authentication": "Falha na autenticação. A data de nascimento informada não corresponde",
        "already_active": "Essa conta está ativa. Impossível desbloquear",
    },
    "close_account": {
        True: "Sua conta foi encerrada corretamente e seus dados removidos do sistema",
        False: "Operação negada. O encerramento de conta deve ser realizado presencialmente na sua agência de origem",
    },
    "card": {
        True: "Cartão válido",
        False: "Falha na leitura do cartão",
        None: "Você não possui nenhum cartão cadastrado",
    },
}


def controller_output(mapper_key: str, inner_key: str | bool | None) -> None:
    """
    Retrieves and displays a standardized status message based on the operation context.

    Uses a predefined dictionary to map internal state keys to user-friendly strings.
    Includes a short delay to ensure the user has time to read the feedback before
    the screen refreshes or the menu reappears.

    Args:
        mapper_key (str): The category of the operation (e.g., 'auth', 'transaction').
        status_key (str | bool | None): The specific result state of the operation.
    """
    msg = method_mappers[mapper_key][inner_key]

    print()
    print(msg)
    for i in range(3):
        print(".", end=" ")
        sleep(0.85)
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


def show_close_account_status(balance: Decimal) -> None:
    """
    Displays specific feedback based on the account balance during a closure attempt.

    Informs the user if they need to withdraw remaining funds or pay off debts
    before the account can be permanently closed.

    Args:
        balance (Decimal): The current balance of the account being closed.
    """
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    if balance > 0:
        print(
            f"ERRO: Você possui saldo de R${balance}. Realize o SAQUE do valor total antes de encerrar a conta."
        )
    if balance < 0:
        print(
            f"ERRO: Você possui dívida de R${balance}. Realize o DEPÓSITO do valor total antes de encerrar a conta."
        )
