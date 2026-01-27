# AWS Tool 🚀

CLI interativa para automação de tarefas AWS com suporte a SSO.

## Features

- 🔐 **Seletor de profiles SSO** - Menu interativo para escolher entre seus profiles
- 📦 **ECS Manager** - Ver logs, tasks, forçar deploys
- 🖥️ **EC2 Manager** - Listar, iniciar, parar, reiniciar instâncias
- 🌐 **API Gateway** - Listar e criar rotas
- 🎨 **Interface rica** - Tabelas coloridas, JSON highlighting

## Requisitos

- Python 3.10+
- AWS CLI configurado com SSO (`aws configure sso`)

## Instalação

### Opção 1: Clone do repositório

```bash
git clone https://github.com/Lucasliuzao/aws-cli-tool.git
cd aws-cli-tool

# Criar virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Instalar
pip install -e .
```

### Opção 2: Instalar via pipx (recomendado)

```bash
# Instalar pipx se não tiver
sudo apt install pipx
pipx ensurepath

# Instalar direto do GitHub
pipx install git+https://github.com/Lucasliuzao/aws-cli-tool.git
```

## Uso

### Modo Interativo (recomendado)

```bash
aws-tool
```

Isso abre um wizard que guia você:
1. Seleciona profile SSO
2. Escolhe o serviço (ECS, API Gateway)
3. Navega pelos recursos interativamente

### Comandos Diretos

```bash
# Listar profiles configurados
aws-tool profiles

# ECS - modo interativo
aws-tool ecs

# ECS - comandos diretos
aws-tool ecs logs --cluster meu-cluster --service meu-service
aws-tool ecs force-task -c meu-cluster -s meu-service -y

# EC2
aws-tool ec2                         # Modo interativo
aws-tool ec2 list                    # Listar instâncias
aws-tool ec2 list -s running         # Listar só as rodando
aws-tool ec2 start -i i-0123456789   # Iniciar instância
aws-tool ec2 stop -i i-0123456789    # Parar instância
aws-tool ec2 reboot -i i-0123456789  # Reiniciar instância

# API Gateway
aws-tool apigw apis
aws-tool apigw list --api-id abc123
aws-tool apigw create-route --api-id abc123 --path /users --method GET
```

## Estrutura do Projeto

```
aws-cli-tool/
├── pyproject.toml
├── README.md
└── src/awscli_tool/
    ├── main.py           # Entry point e wizard principal
    ├── config.py         # Gerenciamento de profiles SSO
    ├── commands/
    │   ├── ecs.py        # Comandos ECS
    │   ├── ec2.py        # Comandos EC2
    │   └── apigateway.py # Comandos API Gateway
    └── utils/
        ├── aws_client.py    # Factory boto3
        └── log_formatter.py # Formatação de logs
```

## Desenvolvimento

```bash
# Clonar e instalar em modo dev
git clone https://github.com/Lucasliuzao/aws-cli-tool.git
cd aws-cli-tool
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Testar
aws-tool --help
```

## Licença

MIT
