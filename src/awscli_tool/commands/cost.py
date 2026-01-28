"""Cost Explorer and FinOps commands."""

from datetime import datetime, timedelta
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


def get_date_range() -> dict:
    """Get start and end dates for current month."""
    today = datetime.today()
    start_date = today.replace(day=1).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    # CE API requires end date to be exclusive (tomorrow) for full inclusion, 
    # but for "current state" usually today is fine or tomorrow.
    # Safe to use tomorrow to include today's partial data if available.
    end_date_api = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    return {"Start": start_date, "End": end_date_api}


def get_cost_and_usage(ce_client, granularity="MONTHLY", group_by=None) -> dict:
    """Get cost data from AWS Cost Explorer."""
    date_range = get_date_range()
    
    kwargs = {
        "TimePeriod": date_range,
        "Granularity": granularity,
        "Metrics": ["UnblendedCost"],
    }
    
    if group_by:
        kwargs["GroupBy"] = group_by
        
    return ce_client.get_cost_and_usage(**kwargs)


def get_forecast(ce_client) -> float:
    """Get cost forecast for the end of the month."""
    today = datetime.today()
    start_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # End of month
    next_month = today.replace(day=28) + timedelta(days=4)
    end_month = (next_month - timedelta(days=next_month.day)).strftime("%Y-%m-%d")
    
    try:
        response = ce_client.get_cost_forecast(
            TimePeriod={"Start": start_date, "End": end_month},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY"
        )
        return float(response["Total"]["Amount"])
    except Exception:
        return 0.0


def check_ebs_unused(ec2_client) -> list[dict]:
    """Find available (unused) EBS volumes."""
    response = ec2_client.describe_volumes(
        Filters=[{"Name": "status", "Values": ["available"]}]
    )
    return response.get("Volumes", [])


def check_eip_unused(ec2_client) -> list[dict]:
    """Find unassociated Elastic IPs."""
    response = ec2_client.describe_addresses()
    # EIPs without AssociationId are unused
    return [addr for addr in response.get("Addresses", []) if "AssociationId" not in addr]


def check_instances_stopped(ec2_client) -> list[dict]:
    """Find stopped EC2 instances (still incurring storage costs)."""
    response = ec2_client.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    )
    instances = []
    for r in response.get("Reservations", []):
        instances.extend(r.get("Instances", []))
    return instances


def interactive_cost_menu(ce_client, ec2_client):
    """Show interactive cost menu."""
    while True:
        action = inquirer.select(
            message="O que deseja ver?",
            choices=[
                {"name": "📊 Resumo de Custos (Mês Atual)", "value": "summary"},
                {"name": "🔝 Top Serviços (Gastos)", "value": "top_services"},
                {"name": "💡 Recomendações FinOps (Recursos Ociosos)", "value": "recommendations"},
                {"name": "◀️  Voltar", "value": "back"},
            ],
        ).execute()
        
        if action == "back":
            return
            
        elif action == "summary":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Buscando dados de custo...", total=None)
                
                # Get current usage
                response = get_cost_and_usage(ce_client)
                results = response.get("ResultsByTime", [])
                total_cost = 0.0
                if results:
                    total_cost = float(results[0]["Total"]["UnblendedCost"]["Amount"])
                
                # Get forecast (if possible)
                forecast = get_forecast(ce_client)
                
            console.print(Panel(
                f"[bold]Custo Acumulado (MTD):[/bold] [green]${total_cost:.2f}[/green]\n"
                f"[bold]Previsão Fim do Mês:[/bold] [yellow]${(total_cost + forecast):.2f}[/yellow]\n"
                f"[dim]Data: {datetime.today().strftime('%Y-%m-%d')}[/dim]",
                title="💵 Resumo Financeiro",
                border_style="green"
            ))
            inquirer.confirm(message="Continuar...", default=True).execute()

        elif action == "top_services":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Analisando serviços...", total=None)
                response = get_cost_and_usage(
                    ce_client, 
                    group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}]
                )
                
            results = response.get("ResultsByTime", [])
            services = []
            if results:
                groups = results[0].get("Groups", [])
                for group in groups:
                    service_name = group["Keys"][0]
                    amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    if amount > 0:
                        services.append((service_name, amount))
            
            # Sort by cost desc
            services.sort(key=lambda x: x[1], reverse=True)
            
            table = Table(title="🔝 Top Serviços (Mês Atual)", border_style="green")
            table.add_column("Serviço", style="cyan")
            table.add_column("Custo ($)", justify="right", style="green")
            
            for s in services[:10]: # Top 10
                table.add_row(s[0], f"{s[1]:.2f}")
                
            console.print(table)
            inquirer.confirm(message="Continuar...", default=True).execute()

        elif action == "recommendations":
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Varrendo recursos ociosos...", total=None)
                
                unused_ebs = check_ebs_unused(ec2_client)
                unused_eip = check_eip_unused(ec2_client)
                stopped_ec2 = check_instances_stopped(ec2_client)
            
            console.print("\n[bold]💡 Recomendações de Otimização[/bold]\n")
            
            # EBS
            if unused_ebs:
                table = Table(title=f"💿 Volumes EBS Soltos ({len(unused_ebs)})", border_style="red")
                table.add_column("ID")
                table.add_column("Size (GB)")
                table.add_column("Type")
                table.add_column("Created")
                for vol in unused_ebs:
                    table.add_row(
                        vol["VolumeId"], 
                        str(vol["Size"]), 
                        vol["VolumeType"], 
                        vol["CreateTime"].strftime("%Y-%m-%d")
                    )
                console.print(table)
                console.print("[dim]Ação sugerida: Deletar volumes se não precisar dos dados (Snapshot antes se necessário).[/dim]\n")
            else:
                console.print("[green]✓ Nenhum volume EBS solto encontrado.[/green]")

            # EIP
            if unused_eip:
                table = Table(title=f"🌐 Elastic IPs Ociosos ({len(unused_eip)})", border_style="red")
                table.add_column("Public IP")
                table.add_column("Allocation ID")
                for eip in unused_eip:
                    table.add_row(eip["PublicIp"], eip["AllocationId"])
                console.print(table)
                console.print("[dim]Ação sugerida: Liberar (Release) IPs não utilizados.[/dim]\n")
            else:
                console.print("[green]✓ Nenhum Elastic IP ocioso encontrado.[/green]")

            # Stopped Instances
            if stopped_ec2:
                table = Table(title=f"🛑 Instâncias Paradas ({len(stopped_ec2)})", border_style="yellow")
                table.add_column("ID")
                table.add_column("Type")
                table.add_column("Launch Time")
                for inst in stopped_ec2:
                    table.add_row(
                        inst["InstanceId"], 
                        inst["InstanceType"], 
                        inst["LaunchTime"].strftime("%Y-%m-%d")
                    )
                console.print(table)
                console.print("[dim]Ação sugerida: Terminar se não forem mais necessárias ou criar AMI e terminar.[/dim]\n")
            else:
                console.print("[green]✓ Nenhuma instância parada encontrada.[/green]")
                
            inquirer.confirm(message="Continuar...", default=True).execute()


@app.callback(invoke_without_command=True)
def cost_wizard(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    💰 Wizard para análise de custos e FinOps.
    """
    if ctx.invoked_subcommand is not None:
        return

    console.print(Panel(
        "[bold green]AWS Cost & FinOps[/bold green]\n\n"
        "Análise de custos e recomendações de otimização.",
        border_style="green",
    ))
    
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
        
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
        
    ce_client = get_client("ce", selected_profile)
    ec2_client = get_client("ec2", selected_profile)
    
    interactive_cost_menu(ce_client, ec2_client)

