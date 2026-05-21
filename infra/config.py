"""Initial configurations for bank, client, account, login, and transactions."""

from decimal import Decimal

from infra import io_utils

menu_config: io_utils.ConfigMap = {
    "main_menu": {
        "info": "Menu principal",
        "prompt": "1 - Depósito\n2 - Abertura de conta\n3 - Outras operações\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1, 2 ou 3",
    },
    "operations_menu": {
        "info": "Operações",
        "prompt": "1 - Depósito\n2 - Saque\n3 - Saldo/Extrato\n4 - Mudança de senha\n5 - Encerrar conta\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções de 1 a 5",
    },
    "restricted_menu": {
        "info": "Acesso restrito",
        "prompt": "1 - Desbloquear conta",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha 1 para desbloquear a conta ou 'S' para sair",
    },
    "use_card_menu": {
        "info": "Formas de acesso",
        "prompt": "1 - Operações com cartão\n2 - Operações sem cartão\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
}

identification_config: io_utils.ConfigMap = {
    "name": {
        "info": "Identificação - Nome",
        "prompt": "Informe o nome (apenas letras): ",
        "input_type": str,
        "error_msg": "O nome deve conter apenas letras (no mínimo três), "
        "não pode conter caracteres especiais e nem começar e/ou terminar com espaços.",
    },
    "cpf": {
        "info": "Identificação - CPF",
        "prompt": "Informe o CPF (somente números): ",
        "input_type": str,
        "error_msg": "CPF inválido. O CPF deve conter somente números e ter exatamente 11 dígitos",
    },
    "birth_date": {
        "info": "Identificação - Data de nascimento",
        "prompt": "Informe sua data de nascimento (dd/mm/aaaa): ",
        "input_type": io_utils.parse_input_date,
        "error_msg": "Data de nascimento ou idade inválida(s). A data deve ser no formato dd/mm/aaaa e a idade estar entre 18 e 120 anos.",
    },
}

new_account_config: io_utils.ConfigMap = {
    "account_type": {
        "info": "Conta - Escolha o tipo da conta",
        "prompt": "1 - Conta Corrente\n2 - Conta Poupança\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida para tipo de conta. Escolha entre 1 ou 2",
    },
    "account_num": {
        "info": "Conta - Número da conta",
        "prompt": "Informe o número da conta: ",
        "input_type": str,
        "error_msg": "Formato de conta inválido. O número da conta deve ser um inteiro positivo de 8 dígitos",
    },
}

auth_config: io_utils.ConfigMap = {
    "branch_code": {
        "info": "Autenticação - Agência ",
        "prompt": "Insira o número da agência: ",
        "input_type": str,
        "error_msg": "Formato de agência inválido. Agência é um número inteiro positivo de 4 dígitos",
    },
    "account_num": {
        "info": "Autenticação - Conta",
        "prompt": "Insira o número da conta: ",
        "input_type": str,
        "error_msg": "Formato de conta inválido. A conta é um número inteiro positivo de 8 dígitos",
    },
    "password": {
        "info": "Autenticação - Senha",
        "prompt": "Insira a senha: ",
        "input_type": str,
        "error_msg": "Formato de senha inválido. A senha é um número inteiro positivo de 6 dígitos",
    },
    "card": {
        "info": "Autenticação - Cartões",
        "prompt": "Escolha seu cartão: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções oferecidas no menu acima",
    },
}

transaction_config: io_utils.ConfigMap = {
    "deposit": {
        "info": "Transação - Depósito",
        "prompt": "Valor a depositar: ",
        "input_type": Decimal,
        "error_msg": "Valor inválido para depósito. Tente novamente",
    },
    "withdraw": {
        "info": "Transação - Saque",
        "prompt": "Valor a sacar: ",
        "input_type": Decimal,
        "error_msg": "Valor inválido para saque. Tente novamente",
    },
    "limit": {
        "info": "Transação - Cheque Especial",
        "prompt": "Deseja usar o cheque especial?\n1 - Sim\n2 - Não\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções 1 ou 2",
    },
    "statement": {
        "info": "Transação - Extrato",
        "prompt": "1 - 30 dias\n2 - 90 dias\n3 - 180 dias\nSua opção: ",
        "input_type": int,
        "error_msg": "Opção inválida. Escolha entre as opções disponíveis no menu",
    },
}
