ONBOARDING_MESSAGES: dict[str, dict[str, str]] = {
    "info": {
        "already_account_holder": "Bem-vindo de volta ao PyBank",
        "new_account_holder": "Bem vindo ao PyBank. Faça o seu cadastro de titular",
        "pwd_confirm": "Confirme a sua nova senha",
        "pwd_error": "As senhas não conferem. Tente novamente",
        "pwd_input": "Insira a sua nova senha (6 dígitos)",
        "pwd_ok": "Senha criada com sucesso",
        "register_ok": "Conta registrada com sucesso",
    },
    "errors": {
        "acc_duplicated": "Essa conta já se encontra registrada no sistema. Crie uma nova conta",
        "ctrl_register": "Erro ao registrar sua conta. Tente novamente",
        "password": "Falha ao registrar sua senha. Tente novamente",
    },
}
SYSTEM_MESSAGES: dict[str, dict[str, str]] = {
    "info": {
        "auth_ok": "Autenticado com sucesso",
        "access_ok": "Acesso Concedido",
        "close_acc_negative": "Você possui dívida de R${balance}. Realize o DEPÓSITO do valor total antes de encerrar a conta.",
        "close_acc_positive": "Você possui saldo de R${balance}. Realize o SAQUE do valor total antes de encerrar a conta",
        "close_acc_ok": "Sua conta foi encerrada corretamente e seus dados removidos do sistema",
        "lobby_hello": "Olá, {user_name}! Seja bem-vindo ao PyBank",
        "lobby_restrict": "Sua conta {acc_type} está bloqueada. Seu acesso ao menu está restringido}",
        "pwd_confirm": "Confirme a sua nova senha",
        "pwd_error": "As senhas não conferem. Tente novamente",
        "pwd_input": "Insira a sua nova senha (6 dígitos)",
        "pwd_last_try": "Atenção: Última tentativa. Se errar a senha, a conta será bloqueada",
        "pwd_ok": "Senha criada com sucesso",
        "pwd_update_ok": "Senha alterada com sucesso",
        "unfreeze_acc_ok": "Conta desbloqueada com sucesso. Sessão atual invalidada",
        "user_cancel": "Operação cancelada pelo usuário",
    },
    "errors": {
        "acc_active": "Essa conta está ativa. Impossível desbloquear",
        "access_denied": "Conta BLOQUEADA por segurança. Desbloqueie a conta para usá-la novamente",
        "auth_failed": "Falha na autenticação. Retornando à tela inicial",
        "bank_security": "Sessão encerrada por falha de segurança. Voltando à tela inicial",
        "ctrl_credentials": "Sessão encerrada. Voltando à tela inicial",
        "ctrl_operations": "Operação cancelada",
        "exp_token": "Sessão expirada. Por favor, autentique-se novamente",
        "other_branch": "Operação negada. O encerramento de conta deve ser realizado presencialmente na sua agência de origem",
        "unavailable": "O sistema do PyBank está temporariamente indisponível. Tente novamente mais tarde",
    },
}


TRANSACTION_MESSAGES: dict[str, dict[str, str]] = {
    "info": {
        "deposit_ok": "Depósito realizado com sucesso",
        "min_value": "Valor mínimo para transação: {min_atm}",
        "withdraw_ok": "Saque realizado com sucesso",
    },
    "deposit_error": {
        "acc_blocked": "Transação não permitida para esta conta no momento. Entre em contato com o titular",
        "acc_not_found": "Conta inexistente no sistema do PyBank",
    },
    "withdraw_error": {
        "acc_blocked": "Sua conta foi BLOQUEADA por segurança. Desbloqueie a conta pra usá-la novamente",
        "value": "Valor indisponível para saque. Transação não autorizada",
        "use_limit": "Valor insuficiente em conta. Para sacar essa quantia autorize o uso do limite especial",
    },
}
