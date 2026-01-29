"""API Gateway commands."""

from typing import Optional

import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from awscli_tool.config import select_profile, ensure_sso_login
from awscli_tool.utils.aws_client import get_client

console = Console()
app = typer.Typer(no_args_is_help=True)


HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "ANY"]


def list_apis(apigw_client) -> list[dict]:
    """List all HTTP APIs (API Gateway v2)."""
    apis = []
    try:
        paginator = apigw_client.get_paginator("get_apis")
        for page in paginator.paginate():
            apis.extend(page.get("Items", []))
    except Exception as e:
        console.print(f"[red]Erro ao listar APIs: {e}[/red]")
    return apis


def list_routes(apigw_client, api_id: str) -> list[dict]:
    """List all routes for an API."""
    routes = []
    try:
        paginator = apigw_client.get_paginator("get_routes")
        for page in paginator.paginate(ApiId=api_id):
            routes.extend(page.get("Items", []))
    except Exception as e:
        console.print(f"[red]Erro ao listar rotas: {e}[/red]")
    return routes


def list_integrations(apigw_client, api_id: str) -> list[dict]:
    """List all integrations for an API."""
    integrations = []
    try:
        response = apigw_client.get_integrations(ApiId=api_id)
        integrations = response.get("Items", [])
    except Exception as e:
        console.print(f"[red]Erro ao listar integrações: {e}[/red]")
    return integrations


def list_authorizers(apigw_client, api_id: str) -> list[dict]:
    """List all authorizers for an API."""
    authorizers = []
    try:
        response = apigw_client.get_authorizers(ApiId=api_id)
        authorizers = response.get("Items", [])
    except Exception as e:
        console.print(f"[red]Erro ao listar authorizers: {e}[/red]")
    return authorizers


def create_integration_interactive(apigw_client, api_id: str) -> Optional[str]:
    """Create a new integration interactively."""
    console.print(Panel("🛠️  Criação de Nova Integração", style="cyan"))
    
    # Select integration type
    type_choices = [
        {"name": "AWS Lambda (AWS_PROXY)", "value": "AWS_PROXY"},
        {"name": "HTTP URL (HTTP_PROXY)", "value": "HTTP_PROXY"},
    ]
    
    integration_type = inquirer.select(
        message="Selecione o tipo de integração:",
        choices=type_choices,
    ).execute()
    
    payload_format_version = "2.0"  # Standard for HTTP APIs
    integration_method = "POST" # Usually POST for Lambda and HTTP Proxy
    integration_uri = None
    
    if integration_type == "AWS_PROXY":
        integration_uri = inquirer.text(
            message="Arn da Lambda:",
            instruction="(ex: arn:aws:lambda:us-east-1:123456789012:function:my-function)",
        ).execute()
        if not integration_uri:
            return None
            
    elif integration_type == "HTTP_PROXY":
        integration_method = inquirer.select(
            message="Método HTTP da integração:",
            choices=HTTP_METHODS,
            default="GET",
        ).execute()
        
        integration_uri = inquirer.text(
            message="URL de destino:",
            instruction="(ex: https://api.example.com/users)",
        ).execute()
        if not integration_uri:
            return None
    
    # Confirm creation
    console.print(f"[dim]Criando integração '{integration_type}' -> '{integration_uri}'...[/dim]")
    
    try:
        response = apigw_client.create_integration(
            ApiId=api_id,
            IntegrationType=integration_type,
            IntegrationUri=integration_uri,
            PayloadFormatVersion=payload_format_version,
            IntegrationMethod=integration_method,
        )
        integration_id = response["IntegrationId"]
        console.print(f"[green]✓ Integração criada: {integration_id}[/green]")
        return integration_id
    except Exception as e:
        console.print(f"[red]Erro ao criar integração: {e}[/red]")
        return None


def select_api(apigw_client, api_id: Optional[str] = None) -> dict:
    """Select API interactively or validate provided ID."""
    apis = list_apis(apigw_client)
    
    if not apis:
        console.print("[red]❌ Nenhuma API encontrada![/red]")
        raise typer.Exit(1)
    
    if api_id:
        for api in apis:
            if api["ApiId"] == api_id:
                return api
        console.print(f"[red]❌ API '{api_id}' não encontrada![/red]")
        raise typer.Exit(1)
    
    # Interactive selection
    choices = [
        {"name": f"{api['Name']} ({api['ApiId']}) - {api.get('ProtocolType', 'HTTP')}", "value": api}
        for api in apis
    ]
    
    return inquirer.select(
        message="🌐 Selecione a API:",
        choices=choices,
    ).execute()


@app.command("list")
def list_api_routes(
    api_id: Optional[str] = typer.Option(None, "--api-id", "-a", help="ID da API"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    📋 Listar rotas de uma API Gateway.
    """
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    # Create client (API Gateway v2 for HTTP APIs)
    apigw_client = get_client("apigatewayv2", selected_profile)
    
    # Select API
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando APIs...", total=None)
        api = select_api(apigw_client, api_id)
    
    # List routes
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando rotas...", total=None)
        routes = list_routes(apigw_client, api["ApiId"])
    
    if not routes:
        console.print(f"[yellow]⚠ Nenhuma rota encontrada na API {api['Name']}[/yellow]")
        return
    
    # Display routes
    table = Table(
        title=f"🛣️ Rotas - {api['Name']}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Método", style="cyan", width=10)
    table.add_column("Path", style="green")
    table.add_column("Target", overflow="fold")
    table.add_column("Route ID", style="dim")
    
    for route in routes:
        method = route.get("RouteKey", "").split(" ")[0] if " " in route.get("RouteKey", "") else "ANY"
        path = route.get("RouteKey", "").replace(f"{method} ", "") if " " in route.get("RouteKey", "") else route.get("RouteKey", "")
        target = route.get("Target", "N/A")
        
        table.add_row(
            method,
            path,
            target,
            route.get("RouteId", ""),
        )
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(routes)} rotas[/dim]")


@app.command("create-route")
def create_route(
    api_id: Optional[str] = typer.Option(None, "--api-id", "-a", help="ID da API"),
    path: str = typer.Option(..., "--path", help="Path da rota (ex: /users/{id})"),
    method: str = typer.Option("GET", "--method", "-m", help="Método HTTP"),
    integration_id: Optional[str] = typer.Option(None, "--integration", "-i", help="ID da integração existente"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    ➕ Criar nova rota no API Gateway.
    
    Cria uma nova rota em uma API HTTP existente.
    """
    # Validate method
    method = method.upper()
    if method not in HTTP_METHODS:
        console.print(f"[red]❌ Método inválido: {method}[/red]")
        console.print(f"[dim]Métodos válidos: {', '.join(HTTP_METHODS)}[/dim]")
        raise typer.Exit(1)
    
    # Ensure path starts with /
    if not path.startswith("/"):
        path = f"/{path}"
    
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    # Create client
    apigw_client = get_client("apigatewayv2", selected_profile)
    
    # Select API
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando APIs...", total=None)
        api = select_api(apigw_client, api_id)
    
    # Authorization Selection
    auth_type = "NONE"
    authorizer_id = None
    
    auth_choices = [
        {"name": "🔓 NONE (Público)", "value": "NONE"},
        {"name": "🛡️  AWS_IAM", "value": "AWS_IAM"},
        {"name": "🔑 CUSTOM / JWT / USER_POOLS (Selecionar Authorizer)", "value": "CUSTOM"},
    ]
    
    selected_auth_mode = inquirer.select(
        message="🔒 Configuração de Autorização:",
        choices=auth_choices,
    ).execute()
    
    if selected_auth_mode == "CUSTOM":
        with Progress(
             SpinnerColumn(),
             TextColumn("[progress.description]{task.description}"),
             console=console,
        ) as progress:
            progress.add_task("Carregando Authorizers...", total=None)
            authorizers = list_authorizers(apigw_client, api["ApiId"])
        
        if not authorizers:
            console.print("[yellow]⚠ Nenhum Authorizer encontrado nesta API. Usando NONE.[/yellow]")
            auth_type = "NONE"
        else:
            auth_choices = [
                {"name": f"{auth['Name']} ({auth['AuthorizerType']})", "value": auth}
                for auth in authorizers
            ]
            selected_authorizer = inquirer.select(
                message="Selecione o Authorizer:",
                choices=auth_choices,
            ).execute()
            
            auth_type = selected_authorizer["AuthorizerType"] # JWT or CUSTOM
            authorizer_id = selected_authorizer["AuthorizerId"]
    else:
        auth_type = selected_auth_mode

    # Select integration if not provided
    if not integration_id:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando integrações...", total=None)
            integrations = list_integrations(apigw_client, api["ApiId"])
        
        choices = []
        if integrations:
            choices = [
                {
                    "name": f"{integ.get('IntegrationType', 'N/A')} - {integ.get('IntegrationUri', integ.get('IntegrationId', 'N/A'))}",
                    "value": integ["IntegrationId"]
                }
                for integ in integrations
            ]
        
        # Add option to create new integration
        choices.insert(0, {"name": "➕ Criar nova integração agora", "value": "CREATE_NEW"})
        choices.append({"name": "❌ Nenhuma (criar rota sem integração)", "value": None})
        
        selection = inquirer.select(
            message="🔗 Selecione a integração:",
            choices=choices,
        ).execute()
        
        if selection == "CREATE_NEW":
            created_id = create_integration_interactive(apigw_client, api["ApiId"])
            if created_id:
                integration_id = created_id
            else:
                console.print("[yellow]⚠ Falha ao criar integração. Prosseguindo sem integração.[/yellow]")
                integration_id = None
        else:
            integration_id = selection
    
    # Confirm
    route_key = f"{method} {path}"
    console.print(Panel(
        f"[cyan]Nova rota:[/cyan]\n\n"
        f"  API: [green]{api['Name']}[/green] ({api['ApiId']})\n"
        f"  Route Key: [green]{route_key}[/green]\n"
        f"  Auth Type: [green]{auth_type}[/green]\n"
        f"  Authorizer ID: [green]{authorizer_id or 'N/A'}[/green]\n"
        f"  Integration: [green]{integration_id or 'Nenhuma'}[/green]",
        title="Confirmação",
        border_style="cyan",
    ))
    
    confirm = inquirer.confirm(
        message="Criar esta rota?",
        default=True,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        raise typer.Exit(0)
    
    # Create route
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Criando rota...", total=None)
            
            kwargs = {
                "ApiId": api["ApiId"],
                "RouteKey": route_key,
            }
            
            if integration_id:
                kwargs["Target"] = f"integrations/{integration_id}"

            if auth_type != "NONE":
                kwargs["AuthorizationType"] = auth_type
                if authorizer_id:
                    kwargs["AuthorizerId"] = authorizer_id
            
            response = apigw_client.create_route(**kwargs)
        
        console.print(Panel(
            f"[green]✓ Rota criada com sucesso![/green]\n\n"
            f"  Route ID: [cyan]{response['RouteId']}[/cyan]\n"
            f"  Route Key: [cyan]{response['RouteKey']}[/cyan]",
            title="Sucesso",
            border_style="green",
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao criar rota: {e}[/red]")
        raise typer.Exit(1)


@app.command("apis")
def list_all_apis(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    📋 Listar todas as APIs Gateway.
    """
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    # Create client
    apigw_client = get_client("apigatewayv2", selected_profile)
    
    # List APIs
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando APIs...", total=None)
        apis = list_apis(apigw_client)
    
    if not apis:
        console.print("[yellow]⚠ Nenhuma API encontrada![/yellow]")
        return
    
    # Display
    table = Table(
        title="🌐 APIs Gateway",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Nome", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Protocol", justify="center")
    table.add_column("Endpoint")
    
    for api in apis:
        table.add_row(
            api.get("Name", "N/A"),
            api.get("ApiId", "N/A"),
            api.get("ProtocolType", "N/A"),
            api.get("ApiEndpoint", "N/A"),
        )
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(apis)} APIs[/dim]")
