"""Main CLI entry point."""

from typing import Optional

import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from awscli_tool.config import get_sso_profiles, select_profile, ensure_sso_login

console = Console()

app = typer.Typer(
    name="aws-tool",
    help="🚀 CLI para automação de tarefas AWS com suporte a SSO",
    no_args_is_help=False,  # Changed to allow interactive mode
    invoke_without_command=True,
)


def run_ecs_wizard(profile: str):
    """Run the ECS interactive wizard."""
    from awscli_tool.commands.ecs import list_clusters, list_services, get_service_details, get_tasks, interactive_menu
    from awscli_tool.utils.aws_client import get_client
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    ecs_client = get_client("ecs", profile)
    logs_client = get_client("logs", profile)
    
    while True:
        # Select cluster
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando clusters...", total=None)
            clusters = list_clusters(ecs_client)
        
        if not clusters:
            console.print("[red]❌ Nenhum cluster encontrado![/red]")
            return
        
        cluster_choices = clusters + ["◀️  Voltar ao menu principal"]
        cluster = inquirer.select(
            message="📦 Selecione o cluster:",
            choices=cluster_choices,
        ).execute()
        
        if cluster == "◀️  Voltar ao menu principal":
            return
        
        # Select service
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando services...", total=None)
            services = list_services(ecs_client, cluster)
        
        if not services:
            console.print(f"[yellow]⚠ Nenhum service encontrado no cluster {cluster}[/yellow]")
            continue
        
        service_choices = services + ["◀️  Voltar"]
        service = inquirer.select(
            message="🔧 Selecione o service:",
            choices=service_choices,
        ).execute()
        
        if service == "◀️  Voltar":
            continue
        
        # Show interactive menu
        result = interactive_menu(ecs_client, logs_client, cluster, service)
        
        if result == "exit":
            return "exit"


def run_ec2_wizard(profile: str):
    """Run the EC2 interactive wizard."""
    from awscli_tool.commands.ec2 import list_instances, display_instances_table, get_instance_details, interactive_menu
    from awscli_tool.utils.aws_client import get_client
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    ec2_client = get_client("ec2", profile)
    
    while True:
        # Filter selection
        filter_choice = inquirer.select(
            message="🔍 Filtrar instâncias por estado:",
            choices=[
                {"name": "Todas", "value": "all"},
                {"name": "🟢 Running", "value": "running"},
                {"name": "🔴 Stopped", "value": "stopped"},
                {"name": "◀️  Voltar ao menu principal", "value": "back"},
            ],
        ).execute()
        
        if filter_choice == "back":
            return
        
        # List instances
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando instâncias...", total=None)
            instances = list_instances(ec2_client, filter_choice)
        
        if not instances:
            console.print(f"[yellow]⚠ Nenhuma instância encontrada com filtro '{filter_choice}'[/yellow]")
            continue
        
        # Display table
        display_instances_table(instances)
        
        # Select instance
        instance_choices = [
            {"name": f"{inst['name']} ({inst['id']}) - {inst['state']}", "value": inst}
            for inst in instances
        ]
        instance_choices.append({"name": "◀️  Voltar", "value": None})
        
        selected = inquirer.select(
            message="🖥️  Selecione uma instância:",
            choices=instance_choices,
        ).execute()
        
        if selected is None:
            continue
        
        # Show interactive menu for this instance
        result = interactive_menu(ec2_client, selected)
        
        if result == "exit":
            return "exit"


def run_servicecatalog_wizard(profile: str):
    """Run the Service Catalog interactive wizard."""
    from awscli_tool.commands.servicecatalog import (
        list_products, list_provisioned_products, display_products_table,
        display_provisioned_table, provision_product_action, interactive_provisioned_menu
    )
    from awscli_tool.utils.aws_client import get_client
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    sc_client = get_client("servicecatalog", profile)
    
    while True:
        action = inquirer.select(
            message="🏗️  O que deseja fazer?",
            choices=[
                {"name": "📦 Ver produtos disponíveis", "value": "products"},
                {"name": "📋 Ver produtos provisionados", "value": "provisioned"},
                {"name": "🚀 Provisionar novo produto", "value": "launch"},
                {"name": "◀️  Voltar ao menu principal", "value": "back"},
            ],
        ).execute()
        
        if action == "products":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Carregando produtos...", total=None)
                products = list_products(sc_client)
            
            if products:
                display_products_table(products)
            else:
                console.print("[yellow]⚠ Nenhum produto encontrado[/yellow]")
            
            inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
            
        elif action == "provisioned":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Carregando provisionados...", total=None)
                provisioned = list_provisioned_products(sc_client)
            
            if not provisioned:
                console.print("[yellow]⚠ Nenhum produto provisionado[/yellow]")
                inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
                continue
            
            display_provisioned_table(provisioned)
            
            pp_choices = [
                {"name": f"{pp['name']} ({pp['status']})", "value": pp}
                for pp in provisioned
            ]
            pp_choices.append({"name": "◀️  Voltar", "value": None})
            
            selected_pp = inquirer.select(
                message="📦 Selecione um produto:",
                choices=pp_choices,
            ).execute()
            
            if selected_pp:
                result = interactive_provisioned_menu(sc_client, selected_pp)
                if result == "exit":
                    return "exit"
            
        elif action == "launch":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Carregando produtos...", total=None)
                products = list_products(sc_client)
            
            if not products:
                console.print("[yellow]⚠ Nenhum produto disponível[/yellow]")
                continue
            
            display_products_table(products)
            
            product_choices = [
                {"name": f"{p['name']}", "value": p}
                for p in products
            ]
            product_choices.append({"name": "◀️  Cancelar", "value": None})
            
            selected_product = inquirer.select(
                message="🚀 Selecione o produto:",
                choices=product_choices,
            ).execute()
            
            if selected_product:
                provision_product_action(sc_client, selected_product)
                inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
            
        elif action == "back":
            return


def run_apigw_wizard(profile: str):
    """Run the API Gateway interactive wizard."""
    from awscli_tool.commands.apigateway import list_apis, list_routes, select_api
    from awscli_tool.utils.aws_client import get_client
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    apigw_client = get_client("apigatewayv2", profile)
    
    while True:
        # Load APIs
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
        
        # Select API
        api_choices = [
            {"name": f"{api['Name']} ({api['ApiId']})", "value": api}
            for api in apis
        ]
        api_choices.append({"name": "◀️  Voltar ao menu principal", "value": None})
        
        api = inquirer.select(
            message="🌐 Selecione a API:",
            choices=api_choices,
        ).execute()
        
        if api is None:
            return
        
        # Show API actions menu
        while True:
            console.print(f"\n[bold cyan]🌐 {api['Name']}[/bold cyan]")
            console.print(f"[dim]Endpoint: {api.get('ApiEndpoint', 'N/A')}[/dim]\n")
            
            action = inquirer.select(
                message="O que deseja fazer?",
                choices=[
                    {"name": "📋 Listar rotas", "value": "list"},
                    {"name": "➕ Criar nova rota", "value": "create"},
                    {"name": "◀️  Voltar (escolher outra API)", "value": "back"},
                    {"name": "❌ Sair", "value": "exit"},
                ],
            ).execute()
            
            if action == "list":
                routes = list_routes(apigw_client, api["ApiId"])
                if routes:
                    table = Table(title=f"🛣️ Rotas - {api['Name']}", header_style="bold cyan")
                    table.add_column("Método", style="cyan")
                    table.add_column("Path", style="green")
                    table.add_column("Target")
                    
                    for route in routes:
                        route_key = route.get("RouteKey", "")
                        parts = route_key.split(" ", 1)
                        method = parts[0] if len(parts) > 0 else "ANY"
                        path = parts[1] if len(parts) > 1 else route_key
                        table.add_row(method, path, route.get("Target", "N/A"))
                    
                    console.print(table)
                else:
                    console.print("[yellow]⚠ Nenhuma rota encontrada[/yellow]")
                
                inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
                
            elif action == "create":
                console.print("[dim]Digite 'cancelar' ou deixe vazio para voltar[/dim]")
                path = inquirer.text(message="Path da rota (ex: /users/{id}):").execute()
                
                # Check if user wants to cancel
                if not path or path.lower() == "cancelar":
                    console.print("[dim]Operação cancelada.[/dim]")
                    continue
                
                method_choices = ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "◀️  Cancelar"]
                method = inquirer.select(
                    message="Método HTTP:",
                    choices=method_choices,
                ).execute()
                
                if method == "◀️  Cancelar":
                    console.print("[dim]Operação cancelada.[/dim]")
                    continue
                
                route_key = f"{method} {path}"
                confirm = inquirer.confirm(
                    message=f"Criar rota '{route_key}'?",
                    default=True,
                ).execute()
                
                if confirm:
                    try:
                        response = apigw_client.create_route(
                            ApiId=api["ApiId"],
                            RouteKey=route_key,
                        )
                        console.print(f"[green]✓ Rota criada![/green] ID: {response['RouteId']}")
                    except Exception as e:
                        console.print(f"[red]❌ Erro: {e}[/red]")
                    
                    inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
                else:
                    console.print("[dim]Operação cancelada.[/dim]")
                
            elif action == "back":
                break
            elif action == "exit":
                return "exit"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    🚀 AWS Tool - CLI para automação de tarefas AWS.
    
    Execute sem argumentos para modo interativo.
    """
    # If a subcommand was invoked, let it handle things
    if ctx.invoked_subcommand is not None:
        return
    
    # Interactive wizard mode
    console.print(Panel(
        "[bold cyan]🚀 AWS Tool[/bold cyan]\n\n"
        "Gerencie seus recursos AWS de forma interativa.\n"
        "[dim]Selecione um profile para começar.[/dim]",
        border_style="cyan",
    ))
    
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    console.print(f"\n[green]✓ Conectado como:[/green] [cyan]{selected_profile}[/cyan]\n")
    
    # Main menu loop
    while True:
        action = inquirer.select(
            message="🎯 O que deseja gerenciar?",
            choices=[
                {"name": "📦 ECS (Clusters, Services, Tasks, Logs)", "value": "ecs"},
                {"name": "🖥️  EC2 (Instâncias)", "value": "ec2"},
                {"name": "🏗️  Service Catalog (Products)", "value": "sc"},
                {"name": "🌐 API Gateway (APIs, Rotas)", "value": "apigw"},
                {"name": "📋 Ver profiles configurados", "value": "profiles"},
                {"name": "🔄 Trocar profile", "value": "switch"},
                {"name": "❌ Sair", "value": "exit"},
            ],
        ).execute()
        
        if action == "ecs":
            result = run_ecs_wizard(selected_profile)
            if result == "exit":
                break
        
        elif action == "ec2":
            result = run_ec2_wizard(selected_profile)
            if result == "exit":
                break
        
        elif action == "sc":
            result = run_servicecatalog_wizard(selected_profile)
            if result == "exit":
                break
                
        elif action == "apigw":
            result = run_apigw_wizard(selected_profile)
            if result == "exit":
                break
                
        elif action == "profiles":
            profiles = get_sso_profiles()
            table = Table(title="🔐 AWS SSO Profiles", header_style="bold cyan")
            table.add_column("Profile", style="cyan")
            table.add_column("Region")
            table.add_column("Account ID", style="dim")
            table.add_column("Role", style="green")
            
            for p in profiles:
                table.add_row(p["name"], p["region"], p["account_id"], p["role"])
            
            console.print(table)
            inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
            
        elif action == "switch":
            new_profile = select_profile()
            if new_profile and ensure_sso_login(new_profile):
                selected_profile = new_profile
                console.print(f"\n[green]✓ Trocado para:[/green] [cyan]{selected_profile}[/cyan]\n")
            
        elif action == "exit":
            console.print("[dim]Até logo! 👋[/dim]")
            break


# Register subcommands (for direct command usage)
from awscli_tool.commands import ecs, apigateway, ec2, servicecatalog
app.add_typer(ecs.app, name="ecs", help="Comandos para Amazon ECS")
app.add_typer(ec2.app, name="ec2", help="Comandos para Amazon EC2")
app.add_typer(servicecatalog.app, name="sc", help="Comandos para Service Catalog")
app.add_typer(apigateway.app, name="apigw", help="Comandos para API Gateway")


@app.command("profiles")
def list_profiles():
    """📋 Listar todos os profiles SSO configurados."""
    profiles = get_sso_profiles()
    
    if not profiles:
        console.print("[yellow]⚠ Nenhum profile SSO encontrado![/yellow]")
        return
    
    table = Table(title="🔐 AWS SSO Profiles", header_style="bold cyan")
    table.add_column("Profile", style="cyan")
    table.add_column("Region")
    table.add_column("Account ID", style="dim")
    table.add_column("Role", style="green")
    
    for p in profiles:
        table.add_row(p["name"], p["region"], p["account_id"], p["role"])
    
    console.print(table)


if __name__ == "__main__":
    app()
