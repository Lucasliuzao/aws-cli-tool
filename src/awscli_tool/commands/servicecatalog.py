"""Service Catalog commands - interactive wizard and direct commands."""

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
app = typer.Typer(no_args_is_help=False)


def list_portfolios(sc_client) -> list[dict]:
    """List all portfolios the user has access to."""
    portfolios = []
    paginator = sc_client.get_paginator("list_portfolios")
    
    for page in paginator.paginate():
        for portfolio in page.get("PortfolioDetails", []):
            portfolios.append({
                "id": portfolio["Id"],
                "name": portfolio["DisplayName"],
                "description": portfolio.get("Description", ""),
                "provider": portfolio.get("ProviderName", ""),
            })
    
    return portfolios


def list_products(sc_client) -> list[dict]:
    """List all products available to the user."""
    products = []
    
    try:
        paginator = sc_client.get_paginator("search_products")
        
        for page in paginator.paginate():
            for product_view in page.get("ProductViewSummaries", []):
                products.append({
                    "id": product_view["ProductId"],
                    "name": product_view["Name"],
                    "description": product_view.get("ShortDescription", ""),
                    "type": product_view.get("Type", ""),
                    "owner": product_view.get("Owner", ""),
                    "view_id": product_view.get("Id", ""),
                })
    except Exception as e:
        console.print(f"[red]Erro ao listar produtos: {e}[/red]")
    
    products.sort(key=lambda x: x["name"].lower())
    return products


def get_product_versions(sc_client, product_id: str) -> list[dict]:
    """Get available versions (provisioning artifacts) for a product."""
    versions = []
    
    try:
        response = sc_client.describe_product(Id=product_id)
        
        for artifact in response.get("ProvisioningArtifacts", []):
            if artifact.get("Guidance") != "DEPRECATED":
                versions.append({
                    "id": artifact["Id"],
                    "name": artifact["Name"],
                    "description": artifact.get("Description", ""),
                    "created": artifact.get("CreatedTime"),
                })
    except Exception as e:
        console.print(f"[red]Erro ao obter versões: {e}[/red]")
    
    return versions


def get_launch_paths(sc_client, product_id: str) -> list[dict]:
    """Get launch paths for a product."""
    paths = []
    
    try:
        response = sc_client.list_launch_paths(ProductId=product_id)
        
        for path in response.get("LaunchPathSummaries", []):
            paths.append({
                "id": path["Id"],
                "name": path.get("Name", "Default"),
                "constraint_summaries": path.get("ConstraintSummaries", []),
            })
    except Exception as e:
        console.print(f"[red]Erro ao obter launch paths: {e}[/red]")
    
    return paths


def get_provisioning_parameters(sc_client, product_id: str, artifact_id: str, path_id: str = None) -> list[dict]:
    """Get parameters required to provision a product."""
    params = []
    
    try:
        kwargs = {
            "ProductId": product_id,
            "ProvisioningArtifactId": artifact_id,
        }
        if path_id:
            kwargs["PathId"] = path_id
        
        response = sc_client.describe_provisioning_parameters(**kwargs)
        
        for param in response.get("ProvisioningArtifactParameters", []):
            params.append({
                "key": param["ParameterKey"],
                "type": param.get("ParameterType", "String"),
                "default": param.get("DefaultValue", ""),
                "description": param.get("Description", ""),
                "constraints": param.get("ParameterConstraints", {}),
                "is_no_echo": param.get("IsNoEcho", False),
            })
    except Exception as e:
        console.print(f"[red]Erro ao obter parâmetros: {e}[/red]")
    
    return params


def list_provisioned_products(sc_client) -> list[dict]:
    """List all provisioned products."""
    products = []
    
    try:
        paginator = sc_client.get_paginator("scan_provisioned_products")
        
        for page in paginator.paginate(AccessLevelFilter={"Key": "Account", "Value": "self"}):
            for pp in page.get("ProvisionedProducts", []):
                products.append({
                    "id": pp["Id"],
                    "name": pp["Name"],
                    "status": pp["Status"],
                    "status_message": pp.get("StatusMessage", ""),
                    "product_id": pp.get("ProductId", ""),
                    "product_name": pp.get("ProductName", "N/A"),
                    "created": pp.get("CreatedTime"),
                    "arn": pp.get("Arn", ""),
                })
    except Exception as e:
        console.print(f"[red]Erro ao listar provisionados: {e}[/red]")
    
    products.sort(key=lambda x: x["name"].lower())
    return products


def get_provisioned_product_detail(sc_client, pp_id: str) -> dict:
    """Get details of a provisioned product."""
    try:
        response = sc_client.describe_provisioned_product(Id=pp_id)
        pp = response.get("ProvisionedProductDetail", {})
        
        return {
            "id": pp.get("Id", ""),
            "name": pp.get("Name", ""),
            "status": pp.get("Status", ""),
            "status_message": pp.get("StatusMessage", ""),
            "arn": pp.get("Arn", ""),
            "type": pp.get("Type", ""),
            "product_id": pp.get("ProductId", ""),
            "provisioning_artifact_id": pp.get("ProvisioningArtifactId", ""),
            "launch_role_arn": pp.get("LaunchRoleArn", ""),
            "created": pp.get("CreatedTime"),
            "last_record_id": pp.get("LastRecordId", ""),
        }
    except Exception as e:
        console.print(f"[red]Erro ao obter detalhes: {e}[/red]")
        return {}


def display_products_table(products: list[dict]):
    """Display products in a rich table."""
    table = Table(
        title="📦 Service Catalog Products",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="cyan")
    table.add_column("Product ID", style="dim")
    table.add_column("Type")
    table.add_column("Owner")
    table.add_column("Description", max_width=40)
    
    for prod in products:
        table.add_row(
            prod["name"],
            prod["id"],
            prod["type"],
            prod["owner"],
            prod["description"][:40] + "..." if len(prod["description"]) > 40 else prod["description"],
        )
    
    console.print(table)


def display_provisioned_table(products: list[dict]):
    """Display provisioned products in a rich table."""
    table = Table(
        title="📋 Provisioned Products",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Product")
    table.add_column("Status")
    
    for pp in products:
        status = pp["status"]
        if status == "AVAILABLE":
            status_display = f"[green]● {status}[/green]"
        elif status in ["UNDER_CHANGE", "PLAN_IN_PROGRESS"]:
            status_display = f"[yellow]◐ {status}[/yellow]"
        elif status in ["ERROR", "TAINTED"]:
            status_display = f"[red]● {status}[/red]"
        else:
            status_display = f"[dim]{status}[/dim]"
        
        table.add_row(
            pp["name"],
            pp["id"][:12] + "...",
            pp["product_name"],
            status_display,
        )
    
    console.print(table)


def provision_product_action(sc_client, product: dict):
    """Provision a product with interactive parameter input."""
    console.print(f"\n[bold cyan]🚀 Provisionar: {product['name']}[/bold cyan]\n")
    
    # Get versions
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando versões...", total=None)
        versions = get_product_versions(sc_client, product["id"])
        paths = get_launch_paths(sc_client, product["id"])
    
    if not versions:
        console.print("[red]❌ Nenhuma versão disponível para este produto[/red]")
        return
    
    # Select version
    version_choices = [
        {"name": f"{v['name']} - {v['description']}", "value": v}
        for v in versions
    ]
    version_choices.append({"name": "◀️  Cancelar", "value": None})
    
    selected_version = inquirer.select(
        message="📌 Selecione a versão:",
        choices=version_choices,
    ).execute()
    
    if selected_version is None:
        return
    
    # Select path if multiple
    path_id = None
    if len(paths) > 1:
        path_choices = [
            {"name": p["name"], "value": p["id"]}
            for p in paths
        ]
        path_id = inquirer.select(
            message="🛤️  Selecione o launch path:",
            choices=path_choices,
        ).execute()
    elif paths:
        path_id = paths[0]["id"]
    
    # Get parameters
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando parâmetros...", total=None)
        params = get_provisioning_parameters(
            sc_client,
            product["id"],
            selected_version["id"],
            path_id,
        )
    
    # Collect parameter values
    param_values = []
    
    if params:
        console.print("\n[bold]📝 Preencha os parâmetros:[/bold]\n")
        
        for param in params:
            hint = f" [dim]({param['description']})[/dim]" if param["description"] else ""
            default = param["default"] if param["default"] else None
            
            if param["is_no_echo"]:
                value = inquirer.secret(
                    message=f"{param['key']}{hint}:",
                    default=default,
                ).execute()
            else:
                value = inquirer.text(
                    message=f"{param['key']}{hint}:",
                    default=default or "",
                ).execute()
            
            if value:
                param_values.append({
                    "Key": param["key"],
                    "Value": value,
                })
    
    # Get provisioned product name
    pp_name = inquirer.text(
        message="📛 Nome para o recurso provisionado:",
        default=f"{product['name']}-instance",
    ).execute()
    
    if not pp_name:
        console.print("[dim]Cancelado.[/dim]")
        return
    
    # Confirmation
    console.print(Panel(
        f"[yellow]⚠ Você está prestes a provisionar:[/yellow]\n\n"
        f"  Produto: [cyan]{product['name']}[/cyan]\n"
        f"  Versão: [cyan]{selected_version['name']}[/cyan]\n"
        f"  Nome: [cyan]{pp_name}[/cyan]\n"
        f"  Parâmetros: [dim]{len(param_values)} configurados[/dim]",
        title="Confirmação",
        border_style="yellow",
    ))
    
    confirm = inquirer.confirm(
        message="Provisionar este produto?",
        default=True,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        return
    
    # Provision
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Provisionando...", total=None)
            
            kwargs = {
                "ProductId": product["id"],
                "ProvisioningArtifactId": selected_version["id"],
                "ProvisionedProductName": pp_name,
            }
            
            if path_id:
                kwargs["PathId"] = path_id
            
            if param_values:
                kwargs["ProvisioningParameters"] = param_values
            
            response = sc_client.provision_product(**kwargs)
        
        record = response.get("RecordDetail", {})
        console.print(Panel(
            f"[green]✓ Provisionamento iniciado![/green]\n\n"
            f"  Record ID: [cyan]{record.get('RecordId', 'N/A')}[/cyan]\n"
            f"  Status: [cyan]{record.get('Status', 'IN_PROGRESS')}[/cyan]\n\n"
            f"[dim]Use 'aws-tool sc provisioned' para ver o status.[/dim]",
            title="Sucesso",
            border_style="green",
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao provisionar: {e}[/red]")


def terminate_product_action(sc_client, pp: dict):
    """Terminate a provisioned product."""
    console.print(Panel(
        f"[red]⚠ ATENÇÃO: Você está prestes a TERMINAR:[/red]\n\n"
        f"  Nome: [cyan]{pp['name']}[/cyan]\n"
        f"  ID: [dim]{pp['id']}[/dim]\n"
        f"  Produto: [cyan]{pp['product_name']}[/cyan]\n\n"
        f"[red]Esta ação irá DESTRUIR todos os recursos associados![/red]",
        title="⚠ Confirmação de Terminação",
        border_style="red",
    ))
    
    confirm = inquirer.confirm(
        message="Você TEM CERTEZA que deseja terminar?",
        default=False,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        return
    
    # Double confirmation
    confirm_name = inquirer.text(
        message=f"Digite '{pp['name']}' para confirmar:",
    ).execute()
    
    if confirm_name != pp['name']:
        console.print("[dim]Nome não confere. Operação cancelada.[/dim]")
        return
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Terminando...", total=None)
            
            response = sc_client.terminate_provisioned_product(
                ProvisionedProductId=pp["id"],
            )
        
        record = response.get("RecordDetail", {})
        console.print(f"[green]✓ Terminação iniciada![/green] Record ID: {record.get('RecordId', 'N/A')}")
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao terminar: {e}[/red]")


def interactive_provisioned_menu(sc_client, pp: dict):
    """Interactive menu for a provisioned product."""
    while True:
        # Refresh details
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando detalhes...", total=None)
            details = get_provisioned_product_detail(sc_client, pp["id"])
        
        if not details:
            console.print("[red]❌ Não foi possível carregar detalhes[/red]")
            return "back"
        
        # Display info
        status = details["status"]
        if status == "AVAILABLE":
            status_display = f"[green]● {status}[/green]"
        elif status in ["UNDER_CHANGE", "PLAN_IN_PROGRESS"]:
            status_display = f"[yellow]◐ {status}[/yellow]"
        else:
            status_display = f"[red]● {status}[/red]"
        
        info = f"""[bold]Status:[/bold] {status_display}
[bold]ID:[/bold] {details['id']}
[bold]ARN:[/bold] [dim]{details['arn']}[/dim]
[bold]Tipo:[/bold] {details['type']}
"""
        if details.get("status_message"):
            info += f"\n[bold]Mensagem:[/bold] {details['status_message']}"
        
        console.print(Panel(info, title=f"📦 {details['name']}", border_style="cyan"))
        
        # Actions menu
        actions = [
            {"name": "🔃 Atualizar status", "value": "refresh"},
            {"name": "🗑️  Terminar (destruir)", "value": "terminate"},
            {"name": "◀️  Voltar", "value": "back"},
            {"name": "❌ Sair", "value": "exit"},
        ]
        
        action = inquirer.select(
            message="O que deseja fazer?",
            choices=actions,
        ).execute()
        
        if action == "refresh":
            continue
        elif action == "terminate":
            terminate_product_action(sc_client, pp)
            inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
        elif action == "back":
            return "back"
        elif action == "exit":
            return "exit"


@app.callback(invoke_without_command=True)
def sc_wizard(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    🏗️  Wizard interativo para Service Catalog.
    
    Se nenhum subcomando for especificado, abre o modo interativo.
    """
    if ctx.invoked_subcommand is not None:
        return
    
    console.print(Panel(
        "[bold cyan]AWS Tool - Service Catalog Manager[/bold cyan]\n\n"
        "Gerencie seus produtos do Service Catalog de forma interativa.",
        border_style="cyan",
    ))
    
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    sc_client = get_client("servicecatalog", selected_profile)
    
    while True:
        action = inquirer.select(
            message="🎯 O que deseja fazer?",
            choices=[
                {"name": "📦 Ver produtos disponíveis", "value": "products"},
                {"name": "📋 Ver produtos provisionados", "value": "provisioned"},
                {"name": "🚀 Provisionar novo produto", "value": "launch"},
                {"name": "◀️  Voltar ao menu principal", "value": "back"},
                {"name": "❌ Sair", "value": "exit"},
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
            
            # Select provisioned product
            pp_choices = [
                {"name": f"{pp['name']} ({pp['status']})", "value": pp}
                for pp in provisioned
            ]
            pp_choices.append({"name": "◀️  Voltar", "value": None})
            
            selected_pp = inquirer.fuzzy(
                message="📦 Selecione um produto provisionado:",
                instruction="[Digite para filtrar]",
                choices=pp_choices,
                max_height="70%",
                multiselect=False,
            ).execute()
            
            if selected_pp:
                result = interactive_provisioned_menu(sc_client, selected_pp)
                if result == "exit":
                    console.print("[dim]Até logo! 👋[/dim]")
                    break
            
        elif action == "launch":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Carregando produtos...", total=None)
                products = list_products(sc_client)
            
            if not products:
                console.print("[yellow]⚠ Nenhum produto disponível para provisionar[/yellow]")
                continue
            
            display_products_table(products)
            
            product_choices = [
                {"name": f"{p['name']} - {p['description'][:30]}...", "value": p}
                for p in products
            ]
            product_choices.append({"name": "◀️  Cancelar", "value": None})
            
            selected_product = inquirer.select(
                message="🚀 Selecione o produto para provisionar:",
                choices=product_choices,
            ).execute()
            
            if selected_product:
                provision_product_action(sc_client, selected_product)
                inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()
            
        elif action == "back":
            return
        elif action == "exit":
            console.print("[dim]Até logo! 👋[/dim]")
            break


@app.command("products")
def list_products_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """📦 Listar produtos disponíveis."""
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    sc_client = get_client("servicecatalog", selected_profile)
    
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


@app.command("provisioned")
def list_provisioned_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """📋 Listar produtos provisionados."""
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    sc_client = get_client("servicecatalog", selected_profile)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando provisionados...", total=None)
        provisioned = list_provisioned_products(sc_client)
    
    if provisioned:
        display_provisioned_table(provisioned)
    else:
        console.print("[yellow]⚠ Nenhum produto provisionado[/yellow]")


@app.command("status")
def status_cmd(
    pp_id: str = typer.Option(..., "--pp-id", "-pp", help="Provisioned Product ID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """🔍 Ver status de um produto provisionado."""
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    sc_client = get_client("servicecatalog", selected_profile)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando detalhes...", total=None)
        details = get_provisioned_product_detail(sc_client, pp_id)
    
    if not details:
        console.print("[red]❌ Produto não encontrado[/red]")
        raise typer.Exit(1)
    
    status = details["status"]
    if status == "AVAILABLE":
        status_display = f"[green]● {status}[/green]"
    elif status in ["UNDER_CHANGE", "PLAN_IN_PROGRESS"]:
        status_display = f"[yellow]◐ {status}[/yellow]"
    else:
        status_display = f"[red]● {status}[/red]"
    
    info = f"""[bold]Nome:[/bold] {details['name']}
[bold]Status:[/bold] {status_display}
[bold]ID:[/bold] {details['id']}
[bold]Tipo:[/bold] {details['type']}
[bold]ARN:[/bold] [dim]{details['arn']}[/dim]
"""
    if details.get("status_message"):
        info += f"[bold]Mensagem:[/bold] {details['status_message']}\n"
    
    console.print(Panel(info, title="📦 Provisioned Product", border_style="cyan"))


@app.command("terminate")
def terminate_cmd(
    pp_id: str = typer.Option(..., "--pp-id", "-pp", help="Provisioned Product ID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
):
    """🗑️  Terminar um produto provisionado."""
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    sc_client = get_client("servicecatalog", selected_profile)
    
    details = get_provisioned_product_detail(sc_client, pp_id)
    if not details:
        console.print("[red]❌ Produto não encontrado[/red]")
        raise typer.Exit(1)
    
    if not yes:
        console.print(f"[red]⚠ Você está prestes a TERMINAR: {details['name']}[/red]")
        confirm = inquirer.confirm(
            message="Continuar?",
            default=False,
        ).execute()
        
        if not confirm:
            console.print("[dim]Cancelado.[/dim]")
            return
    
    try:
        response = sc_client.terminate_provisioned_product(
            ProvisionedProductId=pp_id,
        )
        record = response.get("RecordDetail", {})
        console.print(f"[green]✓ Terminação iniciada![/green] Record ID: {record.get('RecordId', 'N/A')}")
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        raise typer.Exit(1)
