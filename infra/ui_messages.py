TRANSACTION_MESSAGES: dict[str, dict[str, str]] = {
    "transaction": {
        "success": "Transação realizada com sucesso",
        "min_value": "Valor mínimo para transação: {min_atm}}",
    },
    "deposit": {
        "acc_not_found": "Conta inexistente no sistema do PyBank",
        "acc_blocked": "Transação não permitida para esta conta no momento. Entre em contato com o titular",
    },
    "withdraw": {
        "value": "Valor indisponível para saque. Transação não autorizada",
        "use_limit": "Valor insuficiente em conta. Para sacar essa quantia autorize o uso do limite especial",
        "acc_blocked": "Sua conta foi BLOQUEADA por segurança. Desbloqueie a conta pra usá-la novamente",
    },
}

SYSTEM_MESSAGES: dict[str, dict[str, str]] = {
    "menus": {
        "cancel": "Operação cancelada. Voltando ao menu anterior",
        "exit": "Sessão encerrada. Voltando à tela inicial",
        "security": "Sessão encerrada por questão de segurança. Voltando à tela inicial",
        "unavailable": "O sistema do PyBank está temporariamente indisponível. Tente novamente mais tarde",
    },
    "client": {
        "new": "Bem vindo ao PyBank. Faça o seu cadastro",
        "not_new": "Bem vindo de volta ao PyBank",
    },
    "new_account": {
        "success": "Conta registrada com sucesso",
        "duplicated": "Essa conta já se encontra registrada no sistema. Crie uma nova conta",
        "password": "Falha ao registrar sua senha. Tente novamente",
        "run_time": "Erro ao registrar sua conta. Tente novamente",
    },
    "new_password": {
        "first": "Insira sua senha",
        "second": "Insira novamente sua senha",
        "created": "Senha criada com sucesso",
        "updated": "Senha alterada com sucesso",
        "error": "As senhas não conferem. Tente novamente",
    },
    "authentication": {
        "success": "Autenticado com sucesso",
        "not_client": "Falha na autenticação. Cliente não encontrado",
        "auth": "Falha na autenticação. Conta não ligada ao cliente",
    },
    "access": {
        "success": "Acesso Concedido",
        "auth": "Senha incorreta. Acesso Negado",
        "last": "Atenção: Última tentativa. Se errar a senha, a conta será bloqueada",
        "blocked": "Conta BLOQUEADA por segurança. Desbloqueie a conta para usá-la novamente",
    },
    "unfreeze": {
        "success": "Conta desbloqueada com sucesso",
        "auth": "Falha na autenticação. A data de nascimento informada não corresponde",
        "already_active": "Essa conta está ativa. Impossível desbloquear",
    },
    "close_account": {
        "success": "Sua conta foi encerrada corretamente e seus dados removidos do sistema",
        "positive": "Você possui saldo de R${balance}. Realize o SAQUE do valor total antes de encerrar a conta",
        "negative": "Você possui dívida de R${balance}. Realize o DEPÓSITO do valor total antes de encerrar a conta.",
        "other_branch": "Operação negada. O encerramento de conta deve ser realizado presencialmente na sua agência de origem",
    },
}
