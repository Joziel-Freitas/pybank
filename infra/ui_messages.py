TRANSACTION_MESSAGES: dict[str, dict[str, str]] = {
    "transaction": {
        "success": "Transação realizada com sucesso",
        "min_value": "Valor mínimo para transação: {min_atm}",
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
    "menu": {
        "cancel": "Operação cancelada. Voltando ao menu anterior",
        "exit": "Sessão encerrada. Voltando à tela inicial",
        "security": "Sessão encerrada por falha de segurança. Voltando à tela inicial",
        "expired": "Sessão expirada por inatividade. Por favor, autentique-se novamente",
        "unavailable": "O sistema do PyBank está temporariamente indisponível. Tente novamente mais tarde",
    },
    "account_holder": {
        "new_account_holder": "Bem vindo ao PyBank. Faça o seu cadastro de titular",
        "already_account_holder": "Bem-vindo de volta ao PyBank",
    },
    "new_account": {
        "success": "Conta registrada com sucesso",
        "acc_duplicated": "Essa conta já se encontra registrada no sistema. Crie uma nova conta",
        "password": "Falha ao registrar sua senha. Tente novamente",
        "run_time": "Erro ao registrar sua conta. Tente novamente",
    },
    "new_password": {
        "first": "Insira a sua nova senha (6 dígitos)",
        "second": "Confirme a sua nova senha",
        "created": "Senha criada com sucesso",
        "updated": "Senha alterada com sucesso",
        "error": "As senhas não conferem. Tente novamente",
    },
    "authentication": {
        "success": "Autenticado com sucesso",
        "not_account_holder": "Falha na autenticação. Titular não encontrado no sistema",
        "auth": "Falha na autenticação. Conta não pertence a este titular",
    },
    "access": {
        "success": "Acesso Concedido",
        "auth": "Senha incorreta. Acesso Negado",
        "last": "Atenção: Última tentativa. Se errar a senha, a conta será bloqueada",
        "access_denied": "Conta BLOQUEADA por segurança. Desbloqueie a conta para usá-la novamente",
    },
    "unfreeze": {
        "success": "Conta desbloqueada com sucesso. Sessão atual invalidada",
        "auth": "Falha na autenticação. A data de nascimento informada não corresponde ao titular",
        "acc_active": "Essa conta está ativa. Impossível desbloquear",
    },
    "close_account": {
        "success": "Sua conta foi encerrada corretamente e seus dados removidos do sistema",
        "positive": "Você possui saldo de R${balance}. Realize o SAQUE do valor total antes de encerrar a conta",
        "negative": "Você possui dívida de R${balance}. Realize o DEPÓSITO do valor total antes de encerrar a conta.",
        "other_branch": "Operação negada. O encerramento de conta deve ser realizado presencialmente na sua agência de origem",
    },
}
