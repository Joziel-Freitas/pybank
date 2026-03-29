"""Initial configurations for bank, client, account, login, and transactions."""

from decimal import Decimal
from typing import TypedDict


class InnerConfig(TypedDict):
    """
    Typed dictionary that defines the structure of a configuration entry.

    Attributes:
        info (str): Short description or label for the configuration option.
        prompt (str): Text shown to the user when input is required.
        value_type (type): Expected Python type for the input value (e.g., int, str, float).
        error_msg (str): Error message displayed when the input does not match the expected type or format.
    """

    info: str
    prompt: str
    value_type: type
    error_msg: str


ConfigMap = dict[str, InnerConfig]

menu_config: ConfigMap = {
    "main_menu": {
        "info": "Menu principal",
        "prompt": "1 - Operações\n2 - Abertura de conta\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
    "operations": {
        "info": "Operações",
        "prompt": "1 - Transações\n2 - Gerenciamento de conta\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
    "transactions": {
        "info": "Transações",
        "prompt": "1 - Depósito\n2 - Saque\n3 - Extrato\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1, 2 ou 3",
    },
    "management": {
        "info": "Gerenciamento de conta",
        "prompt": "1 - Mudança de senha\n2 - Desbloquear conta\n3 - Encerrar conta\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções disponíveis no menu",
    },
    "is_client": {
        "info": "Abertura de Conta",
        "prompt": "1 - Já sou cliente\n2 - Ainda não sou cliente\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
    "use_card": {
        "info": "Formas de acesso",
        "prompt": "1 - Operações com cartão\n2 - Operações sem cartão\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
}

identification_config: ConfigMap = {
    "name": {
        "info": "Identificação - Nome",
        "prompt": "Informe o nome (apenas letras): ",
        "value_type": str,
        "error_msg": "O nome deve conter apenas letras (no mínimo três), "
        "não pode conter caracteres especiais e nem começar e/ou terminar com espaços.",
    },
    "birth_date": {
        "info": "Identificação - Data de nascimento",
        "prompt": "Informe sua data de nascimento (dd/mm/aaaa): ",
        "value_type": str,
        "error_msg": "Data de nascimento ou idade inválida(s). A data deve ser no formato dd/mm/aaaa e a idade estar entre 18 e 120 anos.",
    },
    "cpf": {
        "info": "Identificação - CPF",
        "prompt": "Informe o CPF (somente números): ",
        "value_type": str,
        "error_msg": "CPF inválido. O CPF deve conter somente números e ter exatamente 11 dígitos",
    },
}

new_account_config: ConfigMap = {
    "acc_type": {
        "info": "Conta - Escolha o tipo da conta",
        "prompt": "1 - Conta Corrente\n2 - Conta Poupança\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida para tipo de conta. Escolha entre 1 ou 2",
    },
    "branch_code": {
        "info": "Conta - Agência",
        "prompt": "Informe o número da agência: ",
        "value_type": str,
        "error_msg": "Número de agência inválido. O número da agência deve ser um inteiro positivo de 4 dígitos",
    },
    "account_num": {
        "info": "Conta - Número da conta",
        "prompt": "Informe o número da conta: ",
        "value_type": str,
        "error_msg": "Formato de conta inválido. O número da conta deve ser um inteiro positivo de 8 dígitos",
    },
    "balance": {
        "info": "Conta - Saldo inicial",
        "prompt": "Informe um valor inicial para o saldo da conta: ",
        "value_type": Decimal,
        "error_msg": "Valor inválido. O saldo deve ser um número real não negativo",
    },
    "password": {
        "info": "Conta - Senha",
        "prompt": "Informe um número de 6 dígitos para senha: ",
        "value_type": str,
        "error_msg": "Formato de senha inválido. A senha deve ser um número inteiro positivo de 6 dígitos",
    },
}

auth_config: ConfigMap = {
    "cpf": {
        "info": "Autenticação - CPF",
        "prompt": "Informe o CPF (somente números): ",
        "value_type": str,
        "error_msg": "CPF inválido. O CPF deve conter somente números e ter 11 dígitos",
    },
    "branch_code": {
        "info": "Autenticação - Agência ",
        "prompt": "Insira o número da agência: ",
        "value_type": str,
        "error_msg": "Formato de agência inválido. Agência é um número inteiro positivo de 4 dígitos",
    },
    "account_num": {
        "info": "Autenticação - Conta",
        "prompt": "Insira o número da conta: ",
        "value_type": str,
        "error_msg": "Formato de conta inválido. A conta é um número inteiro positivo de 8 dígitos",
    },
    "password": {
        "info": "Autenticação - Senha",
        "prompt": "Insira a senha: ",
        "value_type": str,
        "error_msg": "Formato de senha inválido. A senha é um número inteiro positivo de 6 dígitos",
    },
    "card": {
        "info": "Autenticação - Cartões",
        "prompt": "Escolha seu cartão: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções oferecidas no menu acima",
    },
}

transaction_config: ConfigMap = {
    "deposit": {
        "info": "Transação - Depósito",
        "prompt": "Valor a depositar: ",
        "value_type": Decimal,
        "error_msg": "Valor inválido para depósito. Informe um valor maior que 0.5",
    },
    "withdraw": {
        "info": "Transação - Saque",
        "prompt": "Valor a sacar: ",
        "value_type": Decimal,
        "error_msg": "Valor inválido para saque. Informe um valor maior que 0.5",
    },
    "limit": {
        "info": "Transação - Cheque Especial",
        "prompt": "Deseja usar o cheque especial?\n1 - Sim\n2 - Não\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
    "statement": {
        "info": "Transação - Extrato",
        "prompt": "1 - 30 dias\n2 - 90 dias\n3 - 180 dias\nSua opção: ",
        "value_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções disponíveis no menu",
    },
}
