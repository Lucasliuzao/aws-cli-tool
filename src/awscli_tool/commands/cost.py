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


def check_rds_stopped(rds_client) -> list[dict]:
    """Find stopped RDS instances."""
    try:
        response = rds_client.describe_db_instances()
        stopped = []
        for db in response.get("DBInstances", []):
            if db["DBInstanceStatus"] == "stopped":
                stopped.append(db)
        return stopped
    except Exception:
        return []


def check_elb_unused(elbv2_client) -> list[dict]:
    """Find unused Application Load Balancers (no targets)."""
    unused = []
    try:
        # List Load Balancers
        paginator = elbv2_client.get_paginator("describe_load_balancers")
        lbs = []
        for page in paginator.paginate():
            lbs.extend(page["LoadBalancers"])
            
        for lb in lbs:
            lb_arn = lb["LoadBalancerArn"]
            
            # Check Target Groups
            tg_resp = elbv2_client.describe_target_groups(LoadBalancerArn=lb_arn)
            target_groups = tg_resp.get("TargetGroups", [])
            
            if not target_groups:
                unused.append(lb)
                continue
                
            # Check if Target Groups have healthy targets
            has_targets = False
            for tg in target_groups:
                tg_arn = tg["TargetGroupArn"]
                health = elbv2_client.describe_target_health(TargetGroupArn=tg_arn)
                # If any target is registered (healthy or not), we consider it "in use" loosely.
                # Strictly, we might want to check for healthy only, but let's be conservative.
                if health.get("TargetHealthDescriptions"):
                    has_targets = True
                    break
            
            if not has_targets:
                unused.append(lb)
                
        return unused
    except Exception:
        return []


def check_old_snapshots(ec2_client, days=90) -> list[dict]:
    """Find snapshots older than N days."""
    try:
        date_threshold = datetime.now(datetime.timezone.utc) - timedelta(days=days)
        response = ec2_client.describe_snapshots(OwnerIds=["self"])
        old_snapshots = []
        
        for snap in response.get("Snapshots", []):
            start_time = snap["StartTime"]
            if start_time < date_threshold:
                old_snapshots.append(snap)
                
        # Sort by age (oldest first)
        old_snapshots.sort(key=lambda x: x["StartTime"])
        return old_snapshots
    except Exception:
        return []


def interactive_cost_menu(ce_client, ec2_client, rds_client, elbv2_client):
    """Show interactive cost menu."""
    while True:
        action = inquirer.select(
            message="O que deseja ver?",
            choices=[
                {"name": "📊  Resumo de Custos (Mês Atual)", "value": "summary"},
                {"name": "🔝  Top Serviços (Gastos)", "value": "top_services"},
                {"name": "💡  Recomendações FinOps (Recursos Ociosos)", "value": "recommendations"},
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
                stopped_rds = check_rds_stopped(rds_client)
                unused_elb = check_elb_unused(elbv2_client)
                old_snapshots = check_old_snapshots(ec2_client)
            
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

            # EIP
            if unused_eip:
                table = Table(title=f"🌐 Elastic IPs Ociosos ({len(unused_eip)})", border_style="red")
                table.add_column("Public IP")
                table.add_column("Allocation ID")
                for eip in unused_eip:
                    table.add_row(eip["PublicIp"], eip["AllocationId"])
                console.print(table)
                console.print("[dim]Ação sugerida: Liberar (Release) IPs não utilizados.[/dim]\n")

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
            
            # RDS Stopped
            if stopped_rds:
                table = Table(title=f"🛢️ RDS Parados ({len(stopped_rds)})", border_style="yellow")
                table.add_column("ID")
                table.add_column("Engine")
                table.add_column("Type")
                for db in stopped_rds:
                    table.add_row(
                        db["DBInstanceIdentifier"],
                        db["Engine"],
                        db["DBInstanceClass"]
                    )
                console.print(table)
                console.print("[dim]Ação sugerida: Terminar/Snapshot. Storage é cobrado mesmo parado.[/dim]\n")
                
            # Unused ELB
            if unused_elb:
                table = Table(title=f"⚖️ Load Balancers Vazios ({len(unused_elb)})", border_style="red")
                table.add_column("Name")
                table.add_column("DNS Name")
                table.add_column("Created")
                for lb in unused_elb:
                    table.add_row(
                        lb["LoadBalancerName"],
                        lb["DNSName"][:30] + "...",
                        lb["CreatedTime"].strftime("%Y-%m-%d")
                    )
                console.print(table)
                console.print("[dim]Ação sugerida: Deletar LB. Cobra hora de operação mínima.[/dim]\n")
                
            # Old Snapshots
            if old_snapshots:
                limit = 10
                total_snaps = len(old_snapshots)
                shown_snaps = old_snapshots[:limit]
                
                table = Table(title=f"📸 Snapshots Antigos >90d ({total_snaps})", border_style="blue")
                table.add_column("ID")
                table.add_column("Size (GB)")
                table.add_column("Date")
                table.add_column("Description")
                for snap in shown_snaps:
                    desc = snap.get("Description", "")
                    if len(desc) > 30:
                        desc = desc[:30] + "..."
                    table.add_row(
                        snap["SnapshotId"],
                        str(snap["VolumeSize"]),
                        snap["StartTime"].strftime("%Y-%m-%d"),
                        desc
                    )
                console.print(table)
                if total_snaps > limit:
                     console.print(f"[dim]... e mais {total_snaps - limit} snapshots antigos.[/dim]")
                console.print("[dim]Ação sugerida: Revisar e deletar backups obsoletos.[/dim]\n")

            if not any([unused_ebs, unused_eip, stopped_ec2, stopped_rds, unused_elb, old_snapshots]):
                 console.print("[green]✨ Parabéns! Nenhum recurso ocioso óbvio encontrado.[/green]")
                
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
    rds_client = get_client("rds", selected_profile)
    elbv2_client = get_client("elbv2", selected_profile)
    
    interactive_cost_menu(ce_client, ec2_client, rds_client, elbv2_client)

