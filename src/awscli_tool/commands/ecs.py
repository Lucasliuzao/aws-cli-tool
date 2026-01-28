"""ECS commands - interactive wizard and direct commands."""

from typing import Optional

import shutil
import subprocess
import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from awscli_tool.config import select_profile, ensure_sso_login
from awscli_tool.utils.aws_client import get_client
from awscli_tool.utils.log_formatter import display_logs

console = Console()
app = typer.Typer(no_args_is_help=False)


def list_clusters(ecs_client) -> list[str]:
    """List all ECS clusters."""
    paginator = ecs_client.get_paginator("list_clusters")
    clusters = []
    for page in paginator.paginate():
        clusters.extend(page["clusterArns"])
    return [c.split("/")[-1] for c in clusters]


def list_services(ecs_client, cluster: str) -> list[str]:
    """List all services in a cluster."""
    paginator = ecs_client.get_paginator("list_services")
    services = []
    for page in paginator.paginate(cluster=cluster):
        services.extend(page["serviceArns"])
    return [s.split("/")[-1] for s in services]


def get_service_details(ecs_client, cluster: str, service: str) -> dict:
    """Get detailed info about a service."""
    response = ecs_client.describe_services(cluster=cluster, services=[service])
    if response["services"]:
        return response["services"][0]
    return {}


def get_tasks(ecs_client, cluster: str, service: str) -> list[dict]:
    """Get running tasks for a service."""
    response = ecs_client.list_tasks(cluster=cluster, serviceName=service)
    task_arns = response.get("taskArns", [])
    
    if not task_arns:
        return []
    
    tasks_response = ecs_client.describe_tasks(cluster=cluster, tasks=task_arns)
    return tasks_response.get("tasks", [])


def get_container_log_groups(ecs_client, cluster: str, service: str) -> dict[str, str]:
    """Get CloudWatch log groups for all containers in the service."""
    log_groups = {}
    try:
        service_response = ecs_client.describe_services(cluster=cluster, services=[service])
        
        if not service_response["services"]:
            return {}
        
        task_def_arn = service_response["services"][0]["taskDefinition"]
        task_def = ecs_client.describe_task_definition(taskDefinition=task_def_arn)
        container_defs = task_def["taskDefinition"]["containerDefinitions"]
        
        for container in container_defs:
            log_config = container.get("logConfiguration", {})
            if log_config.get("logDriver") == "awslogs":
                options = log_config.get("options", {})
                log_group = options.get("awslogs-group")
                if log_group:
                    log_groups[container["name"]] = log_group
        
        return log_groups
    except Exception as e:
        console.print(f"[red]Erro ao obter log groups: {e}[/red]")
        return {}


def display_service_info(service_details: dict, tasks: list[dict]):
    """Display service information panel."""
    running = service_details.get("runningCount", 0)
    desired = service_details.get("desiredCount", 0)
    status = service_details.get("status", "UNKNOWN")
    task_def = service_details.get("taskDefinition", "").split("/")[-1]
    
    status_color = "green" if status == "ACTIVE" else "yellow"
    running_color = "green" if running == desired else "red"
    
    info = f"""[bold]Status:[/bold] [{status_color}]{status}[/]
[bold]Task Definition:[/bold] {task_def}
[bold]Tasks:[/bold] [{running_color}]{running}/{desired}[/] running
"""
    
    if tasks:
        info += "\n[bold]Running Tasks:[/bold]\n"
        for task in tasks:
            task_id = task["taskArn"].split("/")[-1][:8]
            task_status = task.get("lastStatus", "UNKNOWN")
            health = task.get("healthStatus", "UNKNOWN")
            info += f"  • {task_id} - {task_status} (health: {health})\n"
    else:
        info += "\n[yellow]⚠ Nenhuma task rodando![/yellow]\n"
    
    console.print(Panel(info, title="📦 Service Info", border_style="cyan"))


def view_logs_action(ecs_client, logs_client, cluster: str, service: str):
    """View logs for the service."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Buscando configuração de logs...", total=None)
        log_groups = get_container_log_groups(ecs_client, cluster, service)
    
    if not log_groups:
        console.print("[red]❌ Nenhum log group configurado (awslogs) encontrado.[/red]")
        return
    
    # Select container if multiple
    log_group = None
    if len(log_groups) == 1:
        log_group = list(log_groups.values())[0]
        container_name = list(log_groups.keys())[0]
    else:
        # Check if there is a container with the same name as service
        default_container = None
        if service in log_groups:
            default_container = service
            
        choices = [{"name": f"{name} ({group})", "value": group} for name, group in log_groups.items()]
        
        # Sort choices to put service-named container first
        if default_container:
           choices.sort(key=lambda x: 0 if service in x["name"] else 1)
        
        log_group = inquirer.select(
            message="Selecione o container:",
            choices=choices,
        ).execute()
        
        # Find container name back from log_group for display
        container_name = next((name for name, group in log_groups.items() if group == log_group), "unknown")

    # Ask how many lines
    tail = inquirer.number(
        message="Quantas linhas de log?",
        default=50,
        min_allowed=10,
        max_allowed=500,
    ).execute()
    
    # Ask for level filter
    level_filter = inquirer.select(
        message="Filtrar por nível?",
        choices=[
            {"name": "Todos", "value": None},
            {"name": "ERROR", "value": "ERROR"},
            {"name": "WARN", "value": "WARN"},
            {"name": "INFO", "value": "INFO"},
        ],
    ).execute()
    
    console.print(f"[dim]Container: {container_name}[/dim]")
    console.print(f"[dim]Log group: {log_group}[/dim]\n")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Buscando logs...", total=None)
            
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                limit=int(tail),
                interleaved=True,
            )
        
        events = response.get("events", [])
        
        if level_filter:
            events = [
                e for e in events
                if level_filter in e.get("message", "").upper()
            ]
        
        display_logs(events, service, cluster)
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao buscar logs: {e}[/red]")


def view_tasks_action(ecs_client, cluster: str, service: str):
    """View detailed task information."""
    tasks = get_tasks(ecs_client, cluster, service)
    
    if not tasks:
        console.print("[yellow]⚠ Nenhuma task rodando[/yellow]")
        return
    
    table = Table(
        title="📋 Tasks",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Task ID", style="cyan")
    table.add_column("Status")
    table.add_column("Health")
    table.add_column("Started At")
    table.add_column("CPU/Memory")
    
    for task in tasks:
        task_id = task["taskArn"].split("/")[-1][:12]
        status = task.get("lastStatus", "UNKNOWN")
        health = task.get("healthStatus", "UNKNOWN")
        
        status_style = "green" if status == "RUNNING" else "yellow"
        health_style = "green" if health == "HEALTHY" else "red" if health == "UNHEALTHY" else "dim"
        
        started = task.get("startedAt", "")
        if started:
            started = started.strftime("%Y-%m-%d %H:%M")
        
        cpu = task.get("cpu", "N/A")
        memory = task.get("memory", "N/A")
        
        table.add_row(
            task_id,
            f"[{status_style}]{status}[/]",
            f"[{health_style}]{health}[/]",
            str(started),
            f"{cpu}/{memory}",
        )
    
    console.print(table)


def force_task_action(ecs_client, cluster: str, service: str):
    """Force new deployment."""
    console.print(Panel(
        f"[yellow]⚠ Você está prestes a forçar um novo deploy:[/yellow]\n\n"
        f"  Cluster: [cyan]{cluster}[/cyan]\n"
        f"  Service: [cyan]{service}[/cyan]\n\n"
        f"[dim]Isso irá iniciar novas tasks e desligar as atuais.[/dim]",
        title="Confirmação",
        border_style="yellow",
    ))
    
    confirm = inquirer.confirm(
        message="Continuar com o deploy?",
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
            progress.add_task("Forçando novo deploy...", total=None)
            
            response = ecs_client.update_service(
                cluster=cluster,
                service=service,
                forceNewDeployment=True,
            )
        
        deployment = response["service"]["deployments"][0]
        console.print(Panel(
            f"[green]✓ Deploy iniciado com sucesso![/green]\n\n"
            f"  Deployment ID: [cyan]{deployment['id']}[/cyan]\n"
            f"  Status: [cyan]{deployment['status']}[/cyan]",
            title="Deploy Status",
            border_style="green",
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Erro ao forçar deploy: {e}[/red]")



def check_session_manager_plugin() -> bool:
    """Check if session-manager-plugin is installed."""
    return shutil.which("session-manager-plugin") is not None


def execute_command_action(ecs_client, cluster: str, service: str, profile: str):
    """Start interactive shell session in a container."""
    if not check_session_manager_plugin():
        console.print(Panel(
            "[red]❌ Session Manager Plugin não encontrado![/red]\n\n"
            "Para usar o ECS Exec, você precisa instalar o plugin:\n"
            "https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html",
            border_style="red"
        ))
        return

    # Get running tasks
    tasks = get_tasks(ecs_client, cluster, service)
    running_tasks = [t for t in tasks if t["lastStatus"] == "RUNNING"]
    
    if not running_tasks:
        console.print("[yellow]⚠ Nenhuma task rodando para conectar.[/yellow]")
        return
        
    # Select task if multiple
    task_arn = running_tasks[0]["taskArn"]
    if len(running_tasks) > 1:
        choices = [
            {"name": f"{t['taskArn'].split('/')[-1]} ({t.get('healthStatus', 'UNKNOWN')})", "value": t["taskArn"]}
            for t in running_tasks
        ]
        task_arn = inquirer.select(message="Selecione a task:", choices=choices).execute()
        
    # Select container if multiple (in the selected task)
    selected_task = next(t for t in running_tasks if t["taskArn"] == task_arn)
    containers = selected_task.get("containers", [])
    container_name = containers[0]["name"]
    
    if len(containers) > 1:
        choices = [{"name": c["name"], "value": c["name"]} for c in containers]
        container_name = inquirer.select(message="Selecione o container:", choices=choices).execute()

    console.print(f"\n[green]🚀 Conectando em {container_name}...[/green]")
    console.print("[dim]Pressione Ctrl-D ou digite 'exit' para sair.[/dim]\n")
    
    # Build AWS CLI command
    # We use subprocess to call the system's AWS CLI because we need a real interactive TTY
    cmd = [
        "aws", "ecs", "execute-command",
        "--cluster", cluster,
        "--task", task_arn,
        "--container", container_name,
        "--command", "/bin/sh",
        "--interactive"
    ]
    
    if profile:
        cmd.extend(["--profile", profile])
        
    try:
        subprocess.call(cmd)
    except Exception as e:
        console.print(f"[red]Erro ao executar comando: {e}[/red]")


def interactive_menu(ecs_client, logs_client, cluster: str, service: str, profile: str = None):
    """Show interactive action menu for a service."""
    while True:
        # Get fresh service info
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando informações...", total=None)
            service_details = get_service_details(ecs_client, cluster, service)
            tasks = get_tasks(ecs_client, cluster, service)
        
        console.print(f"\n[bold cyan]📦 {service}[/bold cyan] @ [dim]{cluster}[/dim]\n")
        display_service_info(service_details, tasks)
        
        # Build action choices based on current state
        actions = [
            {"name": "💻 Conectar no Container (Shell)", "value": "exec"},
            {"name": "📋 Ver Logs", "value": "logs"},
            {"name": "🔍 Ver Tasks em detalhe", "value": "tasks"},
            {"name": "🚀 Forçar nova Task (deploy)", "value": "force"},
            {"name": "🔄 Atualizar informações", "value": "refresh"},
            {"name": "◀️ Voltar (escolher outro service)", "value": "back"},
            {"name": "❌ Sair", "value": "exit"},
        ]
        
        # If no tasks, highlight force option
        if not tasks:
            actions[2]["name"] = "🚀 Forçar nova Task (deploy) [RECOMENDADO]"
        
        action = inquirer.select(
            message="O que deseja fazer?",
            choices=actions,
        ).execute()
        
        if action == "exec":
            execute_command_action(ecs_client, cluster, service, profile)
        elif action == "logs":
            view_logs_action(ecs_client, logs_client, cluster, service)
        elif action == "tasks":
            view_tasks_action(ecs_client, cluster, service)
        elif action == "force":
            force_task_action(ecs_client, cluster, service)
        elif action == "refresh":
            continue
        elif action == "back":
            return "back"
        elif action == "exit":
            return "exit"
        
        # Pause before showing menu again
        inquirer.confirm(message="Pressione Enter para continuar...", default=True).execute()


@app.callback(invoke_without_command=True)
def ecs_wizard(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    🚀 Wizard interativo para gerenciar ECS.
    
    Se nenhum subcomando for especificado, abre o modo interativo.
    """
    # If a subcommand was invoked, let it handle things
    if ctx.invoked_subcommand is not None:
        return
    
    # Interactive wizard mode
    console.print(Panel(
        "[bold cyan]AWS Tool - ECS Manager[/bold cyan]\n\n"
        "Gerencie seus serviços ECS de forma interativa.",
        border_style="cyan",
    ))
    
    # Select profile
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    # Ensure SSO login
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    # Create clients
    ecs_client = get_client("ecs", selected_profile)
    logs_client = get_client("logs", selected_profile)
    
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
            raise typer.Exit(1)
        
        cluster_choices = clusters + ["❌ Sair"]
        cluster = inquirer.select(
            message="📦 Selecione o cluster:",
            choices=cluster_choices,
        ).execute()
        
        if cluster == "❌ Sair":
            console.print("[dim]Até logo! 👋[/dim]")
            break
        
        # Select service
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(f"Carregando services...", total=None)
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
        
        # Show interactive menu for this service
        result = interactive_menu(ecs_client, logs_client, cluster, service, selected_profile)
        
        if result == "exit":
            console.print("[dim]Até logo! 👋[/dim]")
            break
        # If "back", continue to cluster selection


@app.command("logs")
def view_logs(
    cluster: Optional[str] = typer.Option(None, "--cluster", "-c", help="Nome do cluster ECS"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Nome do service"),
    tail: int = typer.Option(50, "--tail", "-n", help="Número de linhas para exibir"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    filter_level: Optional[str] = typer.Option(None, "--level", "-l", help="Filtrar por nível (ERROR, WARN, INFO)"),
):
    """
    📋 Visualizar logs do ECS (modo direto).
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ecs_client = get_client("ecs", selected_profile)
    logs_client = get_client("logs", selected_profile)
    
    # Select cluster if not provided
    if not cluster:
        clusters = list_clusters(ecs_client)
        cluster = inquirer.select(message="📦 Cluster:", choices=clusters).execute()
    
    # Select service if not provided
    if not service:
        services = list_services(ecs_client, cluster)
        service = inquirer.select(message="🔧 Service:", choices=services).execute()
    
    log_groups = get_container_log_groups(ecs_client, cluster, service)
    if not log_groups:
        console.print("[red]❌ Log groups não encontrados[/red]")
        raise typer.Exit(1)
    
    log_group = None
    if len(log_groups) == 1:
        log_group = list(log_groups.values())[0]
    elif service in log_groups:
         # Try to match service name directly
         log_group = log_groups[service]
    else:
        # Fallback to first one or ask user? In non-interactive mode (direct command), 
        # it's better to pick one or require a flag. For now, let's pick the first one 
        # but warn, or use interactive select if possible?
        # Since this is the direct command, let's just pick the first one matching 'app' or similar if possible,
        # otherwise just interactive select if input is available?
        # Better approach for direct command: interactively ask if multiple and no specific flag (not implemented yet).
        # Reuse the logic of prioritization:
        console.print("[yellow]⚠ Múltiplos containers encontrados. Use o modo interativo para selecionar.[/yellow]")
        # Pick the one that matches service name if exists (already checked above), 
        # else pick the first one.
        log_group = list(log_groups.values())[0]
        console.print(f"[dim]Selecionando automaticamente o primeiro: {list(log_groups.keys())[0]}[/dim]")

    
    response = logs_client.filter_log_events(logGroupName=log_group, limit=tail, interleaved=True)
    events = response.get("events", [])
    
    if filter_level:
        events = [e for e in events if filter_level.upper() in e.get("message", "").upper()]
    
    display_logs(events, service, cluster)


@app.command("force-task")
def force_new_task(
    cluster: Optional[str] = typer.Option(None, "--cluster", "-c", help="Nome do cluster ECS"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Nome do service"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Pular confirmação"),
):
    """
    🚀 Forçar deploy de nova task (modo direto).
    """
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
    
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
    
    ecs_client = get_client("ecs", selected_profile)
    
    if not cluster:
        clusters = list_clusters(ecs_client)
        cluster = inquirer.select(message="📦 Cluster:", choices=clusters).execute()
    
    if not service:
        services = list_services(ecs_client, cluster)
        service = inquirer.select(message="🔧 Service:", choices=services).execute()
    
    if not yes:
        confirm = inquirer.confirm(message=f"Forçar deploy em {service}?", default=False).execute()
        if not confirm:
            console.print("[dim]Cancelado.[/dim]")
            return
    
    response = ecs_client.update_service(cluster=cluster, service=service, forceNewDeployment=True)
    deployment = response["service"]["deployments"][0]
    console.print(f"[green]✓ Deploy iniciado![/green] ID: {deployment['id']}")
