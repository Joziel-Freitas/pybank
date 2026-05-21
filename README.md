# 🏦 PyBank System 3.0 - Enterprise-Grade CLI Banking Application

Uma aplicação bancária via linha de comando desenvolvida com foco extremo em **Arquitetura de Software (Clean Architecture / DDD)**, **Segurança (Zero Trust / AppSec)** e **Concorrência de Dados (ACID)**.

## 📖 Sobre o Projeto

Este projeto é o marco principal do meu portfólio para Desenvolvimento Backend. O objetivo não foi criar apenas um script funcional, mas provar que é possível aplicar engenharia de software de nível corporativo utilizando Python puro, sem depender de frameworks de alto nível (como Django ou FastAPI) para abstrair a complexidade.

Em um intervalo de 82 dias, o sistema evoluiu de uma persistência simples em JSON (v2.0) para uma arquitetura robusta, baseada em um banco de dados relacional isolado em contêineres, aplicando padrões rigorosos de design para garantir segurança, desacoplamento e resiliência a falhas.

## 🚀 O que mudou na v3.0? (Destaques de Engenharia)

Nesta versão, a aplicação deixou de ser um projeto de estudos e passou a adotar práticas de mercado focadas em alta disponibilidade e segurança:

* **Domain-Driven Design (DDD) e DTOs:** Fronteiras arquiteturais estritas. A interface de usuário (View/Controllers) nunca interage diretamente com as entidades de Domínio (`Account`, `AccountHolder`). Todo o tráfego de dados é feito através de Data Transfer Objects (DTOs) imutáveis.
* **Concorrência e Transações ACID (Unit of Work):** Transição para MySQL. Implementação manual do padrão *Unit of Work* com gerenciamento de contexto (`contextmanager`) e **Bloqueio Pessimista (FOR UPDATE)**, mitigando completamente vulnerabilidades de Race Conditions e TOCTOU (Time-of-Check to Time-of-Use) durante saques e transferências simultâneas.
* **Segurança Zero Trust e Sessões Stateless:** Fim do armazenamento de sessão em memória. Implementação de um sistema de tokens criptográficos baseados em HMAC-SHA256.
  * **AuthToken (Lobby):** Comprova a identidade sem expor dados financeiros.
  * **AccessToken (Vault):** Garante acesso ao cofre. O hash da senha via Bcrypt é embutido na assinatura do token, garantindo que uma troca de senha invalide sessões ativas instantaneamente.
* **Anti-Corruption Layer (ACL) e Padrão Repository:** O banco de dados é apenas um detalhe de infraestrutura. O Domínio desconhece o SQL. O `MySQLRepository` atua como tradutor, hidratando os objetos de domínio.
* **Roteamento Centralizado de Exceções:** Padrão *Intercept-and-Rethrow*. Exceções de Domínio e Infraestrutura são mapeadas dinamicamente para um dicionário de mensagens da UI, evitando vazamento de Stack Trace ou lógicas de negócio para o cliente.

## 🏗️ Estrutura e Arquitetura (Clean Architecture)

```text
PyBank/
├── app/                  # Camada de Aplicação (Casos de Uso)
│   └── controllers.py    # Orquestração do fluxo, gestão de sessão e injeção de DTOs
├── domain/               # Camada de Domínio (O Coração do Negócio - Zero dependências externas)
│   ├── bank.py           # Aggregate Root, Regras de Segurança e AppSec
│   ├── account.py        # Entidades base, Fábricas (Dispatchers) para Checking/Savings
│   └── person.py         # Entidades de Cliente e credenciais de acesso
├── infra/                # Camada de Infraestrutura (Adaptadores de Interface)
│   ├── mysql_repository  # Repository Pattern, Unit of Work, ACL e queries SQL
│   ├── io_utils.py       # Motor de validação de input dinâmico (Inversão de Controle)
│   ├── config.py         # Mapeamento de regras de I/O
│   ├── views.py          # Renderização de tela (Terminal)
│   └── ui_messages.py    # Catálogo central de feedback ao usuário
├── shared/               # Tipos globais e transporte de dados
│   ├── dtos.py           # Data Transfer Objects
│   ├── credentials.py    # Value Objects de Tokens HMAC
│   └── exceptions.py     # Hierarquia customizada de erros do sistema
├── main.py               # Composition Root (Dependency Injection Bottom-Up)
├── init.sql              # Script de inicialização do schema relacional
├── docker-compose.yaml   # Orquestração do banco de dados
└── .env.example          # Variáveis de ambiente (12-Factor App)
```

## 🛠️ Tecnologias Utilizadas
* **Linguagem:** Python 3.12+ (Com tipagem estrita via typing / Mypy)

* **Persistência:** MySQL 8.0 (PyMySQL)

* **Infraestrutura:** Docker & Docker Compose

* **Segurança:** Bcrypt, HMAC (Hash-based Message Authentication Code), Hashlib

* **Configuração:** python-dotenv (Seguindo princípios do 12-Factor App)

## 💻 Funcionalidades Principais
* **Identidade First:** Autenticação em duas camadas (Cartão/CPF -> Senha).

* **Operações Financeiras ACID:** Saques (com cálculo dinâmico de Cheque Especial), Depósitos e Extrato Cronológico com saldo retroativo.

* **Sistema Kiosk Mode:** O Terminal nunca "crasha". Falhas de infraestrutura são capturadas pelo Global Exception Handler e o sistema retorna à tela inicial de forma segura.

* **Recuperação e Bloqueio:** Congelamento automático de conta após 3 tentativas falhas de login. Recuperação de conta validada por KBA (Knowledge Based Authentication - Data de Nascimento).

* **Alteração e Encerramento:** Troca de senhas com invalidação de token e fechamento de conta mediante regra de saldo zero.

## ⚙️ Como Executar o Projeto
**Pré-requisitos:** Python 3.12+ e Docker (com Docker Compose) instalados.

**1. Clone o repositório e acesse a pasta:**
```Bash
git clone https://github.com/Joziel-Freitas/bank-system-python.git
cd bank-system-python
```

**2. Configure o Ambiente:**
Crie uma cópia do arquivo de configuração e edite as credenciais caso necessário:
```Bash
cp .env.example .env
```

**3. Suba o Banco de Dados (Docker):**
Isso irá iniciar o MySQL e executar automaticamente o init.sql.
```Bash
docker-compose up -d
```

**4. Instale as dependências e rode a aplicação:**
```Bash
pip install -r requirements.txt
python main.py
```

---
**Autor:** Joziel Freitas da Silva<br>
*Projeto desenvolvido do zero, guiado pela paixão por resolver problemas complexos através de Backend Engineering, Design Patterns e Clean Code.*
