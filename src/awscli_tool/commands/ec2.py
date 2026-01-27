"""EC2 commands - interactive wizard and direct commands."""

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


def list_instances(ec2_client, state_filter: str = "all") -> list[dict]:
    """List EC2 instances with optional state filter."""
    filters = []
    
    if state_filter == "running":
        filters.append({"Name": "instance-state-name", "Values": ["running"]})
    elif state_filter == "stopped":
        filters.append({"Name": "instance-state-name", "Values": ["stopped"]})
    elif state_filter != "all":
        filters.append({"Name": "instance-state-name", "Values": [state_filter]})
    
    paginator = ec2_client.get_paginator("describe_instances")
    instances = []
    
    kwargs = {}
    if filters:
        kwargs["Filters"] = filters
    
    for page in paginator.paginate(**kwargs):
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                # Get instance name from tags
                name = "N/A"
                for tag in instance.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                        break
                
                instances.append({
                    "id": instance["InstanceId"],
                    "name": name,
                    "type": instance["InstanceType"],
                    "state": instance["State"]["Name"],
                    "public_ip": instance.get("PublicIpAddress", "N/A"),
                    "private_ip": instance.get("PrivateIpAddress", "N/A"),
                    "launch_time": instance.get("LaunchTime"),
                    "az": instance.get("Placement", {}).get("AvailabilityZone", "N/A"),
                })
    
    return instances


def get_instance_details(ec2_client, instance_id: str) -> dict:
    """Get detailed info about an instance."""
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    
    if response["Reservations"] and response["Reservations"][0]["Instances"]:
        instance = response["Reservations"][0]["Instances"][0]
        
        name = "N/A"
        for tag in instance.get("Tags", []):
            if tag["Key"] == "Name":
                name = tag["Value"]
                break
        
        return {
            "id": instance["InstanceId"],
            "name": name,
            "type": instance["InstanceType"],
            "state": instance["State"]["Name"],
            "public_ip": instance.get("PublicIpAddress", "N/A"),
            "private_ip": instance.get("PrivateIpAddress", "N/A"),
            "launch_time": instance.get("LaunchTime"),
            "az": instance.get("Placement", {}).get("AvailabilityZone", "N/A"),
            "vpc_id": instance.get("VpcId", "N/A"),
            "subnet_id": instance.get("SubnetId", "N/A"),
            "security_groups": [sg["GroupName"] for sg in instance.get("SecurityGroups", [])],
            "key_name": instance.get("KeyName", "N/A"),
            "ami_id": instance.get("ImageId", "N/A"),
        }
    
    return {}


def display_instances_table(instances: list[dict]):
    """Display instances in a rich table."""
    table = Table(
        title="🖥️  EC2 Instances",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="cyan")
    table.add_column("Instance ID", style="dim")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Public IP", style="green")
    table.add_column("Private IP")
    
    for inst in instances:
        state = inst["state"]
        if state == "running":
            state_display = f"[green]● {state}[/green]"
        elif state == "stopped":
            state_display = f"[red]○ {state}[/red]"
        elif state in ["pending", "stopping"]:
            state_display = f"[yellow]◐ {state}[/yellow]"
        else:
            state_display = f"[dim]{state}[/dim]"
        
        table.add_row(
            inst["name"],
            inst["id"],
            inst["type"],
            state_display,
            inst["public_ip"],
            inst["private_ip"],
        )
    
    console.print(table)


def display_instance_info(instance: dict):
    """Display detailed instance information panel."""
    state = instance["state"]
    if state == "running":
        state_display = f"[green]● {state}[/green]"
    elif state == "stopped":
        state_display = f"[red]○ {state}[/red]"
    else:
        state_display = f"[yellow]◐ {state}[/yellow]"
    
    launch_time = instance.get("launch_time", "N/A")
    if launch_time and launch_time != "N/A":
        launch_time = launch_time.strftime("%Y-%m-%d %H:%M")
    
    security_groups = ", ".join(instance.get("security_groups", [])) or "N/A"
    
    info = f"""[bold]State:[/bold] {state_display}
[bold]Type:[/bold] {instance['type']}
[bold]Availability Zone:[/bold] {instance['az']}

[bold]Networking:[/bold]
  • Public IP: [green]{instance['public_ip']}[/green]
  • Private IP: {instance['private_ip']}
  • VPC: {instance.get('vpc_id', 'N/A')}
  • Subnet: {instance.get('subnet_id', 'N/A')}

[bold]Security:[/bold]
  • Key: {instance.get('key_name', 'N/A')}
  • Security Groups: {security_groups}

[bold]Image:[/bold] {instance.get('ami_id', 'N/A')}
[bold]Launched:[/bold] {launch_time}
"""
    
    console.print(Panel(info, title=f"🖥️  {instance['name']} ({instance['id']})", border_style="cyan"))


def start_instance_action(ec2_client, instance_id: str, instance_name: str):
    """Start an EC2 instance."""
    console.print(Panel(
        f"[yellow]⚠ Você está prestes a iniciar a instância:[/yellow]\n\n"
        f"  Name: [cyan]{instance_name}[/cyan]\n"
        f"  ID: [dim]{instance_id}[/dim]",
        title="Confirmação",
        border_style="yellow",
    ))
    
    confirm = inquirer.confirm(
        message="Iniciar instância?",
        default=True,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        return
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Iniciando instância...", total=None)
            ec2_client.start_instances(InstanceIds=[instance_id])
        
        console.print(f"[green]✓ Instância {instance_id} está iniciando![/green]")
        console.print("[dim]Use 'Atualizar' para ver o novo estado.[/dim]")
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao iniciar: {e}[/red]")


def stop_instance_action(ec2_client, instance_id: str, instance_name: str):
    """Stop an EC2 instance."""
    console.print(Panel(
        f"[yellow]⚠ Você está prestes a parar a instância:[/yellow]\n\n"
        f"  Name: [cyan]{instance_name}[/cyan]\n"
        f"  ID: [dim]{instance_id}[/dim]\n\n"
        f"[dim]A instância será desligada mas os dados serão preservados.[/dim]",
        title="Confirmação",
        border_style="yellow",
    ))
    
    confirm = inquirer.confirm(
        message="Parar instância?",
        default=False,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        return
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Parando instância...", total=None)
            ec2_client.stop_instances(InstanceIds=[instance_id])
        
        console.print(f"[green]✓ Instância {instance_id} está parando![/green]")
        console.print("[dim]Use 'Atualizar' para ver o novo estado.[/dim]")
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao parar: {e}[/red]")


def reboot_instance_action(ec2_client, instance_id: str, instance_name: str):
    """Reboot an EC2 instance."""
    console.print(Panel(
        f"[yellow]⚠ Você está prestes a reiniciar a instância:[/yellow]\n\n"
        f"  Name: [cyan]{instance_name}[/cyan]\n"
        f"  ID: [dim]{instance_id}[/dim]\n\n"
        f"[dim]A instância será reiniciada. Conexões ativas serão perdidas.[/dim]",
        title="Confirmação",
        border_style="yellow",
    ))
    
    confirm = inquirer.confirm(
        message="Reiniciar instância?",
        default=False,
    ).execute()
    
    if not confirm:
        console.print("[dim]Operação cancelada.[/dim]")
        return
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Reiniciando instância...", total=None)
            ec2_client.reboot_instances(InstanceIds=[instance_id])
        
        console.print(f"[green]✓ Instância {instance_id} está reiniciando![/green]")
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao reiniciar: {e}[/red]")


def interactive_menu(ec2_client, instance: dict):
    """Show interactive action menu for an instance."""
    while True:
        # Get fresh instance info
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando informações...", total=None)
            instance = get_instance_details(ec2_client, instance["id"])
        
        if not instance:
            console.print("[red]❌ Instância não encontrada[/red]")
            return "back"
        
        console.print()
        display_instance_info(instance)
        
        # Build action choices based on current state
        state = instance["state"]
        actions = []
        
        if state == "stopped":
            actions.append({"name": "▶️  Iniciar instância", "value": "start"})
        elif state == "running":
            actions.append({"name": "⏹️  Parar instância", "value": "stop"})
            actions.append({"name": "🔄 Reiniciar instância", "value": "reboot"})
        
        actions.extend([
            {"name": "🔃 Atualizar informações", "value": "refresh"},
            {"name": "◀️  Voltar (escolher outra instância)", "value": "back"},
            {"name": "❌ Sair", "value": "exit"},
        ])
        
        action = inquirer.select(
            message="O que deseja fazer?",
            choices=actions,
        ).execute()
        
        if action == "start":
            start_instance_action(ec2_client, instance["id"], instance["name"])
        elif action == "stop":
            stop_instance_action(ec2_client, instance["id"], instance["name"])
        elif action == "reboot":
            reboot_instance_action(ec2_client, instance["id"], instance["name"])
        elif action == "refresh":
            continue
        elif action == "back":
            return "back"
        elif action == "exit":
            return "exit"
        
        # Pause before showing menu again
        inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()


@app.callback(invoke_without_command=True)
def ec2_wizard(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    🖥️  Wizard interativo para gerenciar EC2.
    
    Se nenhum subcomando for especificado, abre o modo interativo.
    """
    # If a subcommand was invoked, let it handle things
    if ctx.invoked_subcommand is not None:
        return
    
    # Interactive wizard mode
    console.print(Panel(
        "[bold cyan]AWS Tool - EC2 Manager[/bold cyan]\n\n"
        "Gerencie suas instâncias EC2 de forma interativa.",
        border_style="cyan",
    ))
    
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    # Create client
    ec2_client = get_client("ec2", selected_profile)
    
    while True:
        # Filter selection
        filter_choice = inquirer.select(
            message="🔍 Filtrar instâncias por estado:",
            choices=[
                {"name": "Todas", "value": "all"},
                {"name": "🟢 Running", "value": "running"},
                {"name": "🔴 Stopped", "value": "stopped"},
                {"name": "❌ Sair", "value": "exit"},
            ],
        ).execute()
        
        if filter_choice == "exit":
            console.print("[dim]Até logo! 👋[/dim]")
            break
        
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
            console.print("[dim]Até logo! 👋[/dim]")
            break
        # If "back", continue to instance selection


@app.command("list")
def list_cmd(
    state: Optional[str] = typer.Option("all", "--state", "-s", help="Filtrar por estado (all, running, stopped)"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    📋 Listar instâncias EC2.
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ec2_client = get_client("ec2", selected_profile)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Carregando instâncias...", total=None)
        instances = list_instances(ec2_client, state)
    
    if not instances:
        console.print(f"[yellow]⚠ Nenhuma instância encontrada[/yellow]")
        return
    
    display_instances_table(instances)


@app.command("start")
def start_cmd(
    instance_id: str = typer.Option(..., "--instance", "-i", help="Instance ID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
):
    """
    ▶️  Iniciar uma instância EC2.
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ec2_client = get_client("ec2", selected_profile)
    
    if not yes:
        confirm = inquirer.confirm(message=f"Iniciar instância {instance_id}?", default=True).execute()
        if not confirm:
            console.print("[dim]Cancelado.[/dim]")
            return
    
    try:
        ec2_client.start_instances(InstanceIds=[instance_id])
        console.print(f"[green]✓ Instância {instance_id} está iniciando![/green]")
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        raise typer.Exit(1)


@app.command("stop")
def stop_cmd(
    instance_id: str = typer.Option(..., "--instance", "-i", help="Instance ID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
):
    """
    ⏹️  Parar uma instância EC2.
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ec2_client = get_client("ec2", selected_profile)
    
    if not yes:
        confirm = inquirer.confirm(message=f"Parar instância {instance_id}?", default=False).execute()
        if not confirm:
            console.print("[dim]Cancelado.[/dim]")
            return
    
    try:
        ec2_client.stop_instances(InstanceIds=[instance_id])
        console.print(f"[green]✓ Instância {instance_id} está parando![/green]")
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        raise typer.Exit(1)


@app.command("reboot")
def reboot_cmd(
    instance_id: str = typer.Option(..., "--instance", "-i", help="Instance ID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
):
    """
    🔄 Reiniciar uma instância EC2.
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ec2_client = get_client("ec2", selected_profile)
    
    if not yes:
        confirm = inquirer.confirm(message=f"Reiniciar instância {instance_id}?", default=False).execute()
        if not confirm:
            console.print("[dim]Cancelado.[/dim]")
            return
    
    try:
        ec2_client.reboot_instances(InstanceIds=[instance_id])
        console.print(f"[green]✓ Instância {instance_id} está reiniciando![/green]")
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        raise typer.Exit(1)
