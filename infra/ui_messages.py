from domain.account import Account

TRANSACTION_MESSAGES: dict[str, dict[str, str]] = {
    "general": {
        "success": "Transação realizada com sucesso",
        "min_value": f"Valor mínimo para transação: {Account.MIN_ATM_TRANSACTION}",
    },
    "deposit": {
        "acc_not_found": "Conta inexistente no sistema do PyBank",
        "acc_blocked": "Transação não permitida para esta conta no momento. Entre em contato com o titular",
    },
    "withdraw": {
        "value": "Valor inválido para saque. Transação não autorizada",
        "overdraft": "Valor insuficiente em conta. Para sacar essa quantia autorize o uso do limite especial",
    },
}
