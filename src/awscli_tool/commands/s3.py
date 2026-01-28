"""S3 Browser commands."""

import os
from datetime import datetime
from typing import Optional

import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from rich.table import Table

from awscli_tool.config import select_profile, ensure_sso_login
from awscli_tool.utils.aws_client import get_client

console = Console()
app = typer.Typer(no_args_is_help=False)


def list_buckets(s3_client) -> list[dict]:
    """List all buckets."""
    response = s3_client.list_buckets()
    return response.get("Buckets", [])


def list_objects(s3_client, bucket: str, prefix: str = "") -> dict:
    """List objects and 'folders' (prefixes) in a bucket path."""
    response = s3_client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter="/"
    )
    
    folders = response.get("CommonPrefixes", [])
    files = response.get("Contents", [])
    
    return {"folders": folders, "files": files}


def download_file(s3_client, bucket: str, key: str):
    """Download a file from S3 to current directory."""
    filename = key.split("/")[-1]
    
    if os.path.exists(filename):
        confirm = inquirer.confirm(
            message=f"Arquivo '{filename}' já existe. Sobrescrever?",
            default=False
        ).execute()
        if not confirm:
            console.print("[dim]Download cancelado.[/dim]")
            return

    try:
        # Get file size for progress bar
        head = s3_client.head_object(Bucket=bucket, Key=key)
        total_bytes = head["ContentLength"]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Baixando {filename}...", total=total_bytes)
            
            s3_client.download_file(
                Bucket=bucket, 
                Key=key, 
                Filename=filename,
                Callback=lambda bytes_transferred: progress.update(task, advance=bytes_transferred)
            )
            
        console.print(f"[green]✓ Download concluído:[/green] {filename}")
        
    except Exception as e:
        console.print(f"[red]❌ Erro no download: {e}[/red]")


def upload_file(s3_client, bucket: str, prefix: str):
    """Upload a local file to the current S3 path."""
    # List local files
    local_files = [f for f in os.listdir(".") if os.path.isfile(f)]
    
    if not local_files:
        console.print("[yellow]⚠ Nenhum arquivo encontrado no diretório atual.[/yellow]")
        return
        
    file_to_upload = inquirer.select(
        message="Selecione o arquivo para upload:",
        choices=local_files + ["◀️  Cancelar"],
    ).execute()
    
    if file_to_upload == "◀️  Cancelar":
        return
        
    key = f"{prefix}{file_to_upload}"
    
    try:
        file_size = os.path.getsize(file_to_upload)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Enviando {file_to_upload}...", total=file_size)
            
            s3_client.upload_file(
                Filename=file_to_upload,
                Bucket=bucket,
                Key=key,
                Callback=lambda bytes_transferred: progress.update(task, advance=bytes_transferred)
            )
            
        console.print(f"[green]✓ Upload concluído:[/green] s3://{bucket}/{key}")
        
    except Exception as e:
        console.print(f"[red]❌ Erro no upload: {e}[/red]")


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def interactive_s3_browser(s3_client):
    """Main interactive loop for S3 browser."""
    current_bucket = None
    current_prefix = ""
    
    while True:
        if current_bucket is None:
            # Level 0: List Buckets
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Listando buckets...", total=None)
                buckets = list_buckets(s3_client)
            
            if not buckets:
                console.print("[yellow]⚠ Nenhum bucket encontrado![/yellow]")
                return
            
            choices = [
                {"name": f"🪣 {b['Name']}", "value": b['Name']} 
                for b in buckets
            ]
            choices.append({"name": "◀️  Voltar ao menu principal", "value": "exit"})
            
            bucket = inquirer.select(
                message="Selecione um bucket:",
                choices=choices,
            ).execute()
            
            if bucket == "exit":
                return
                
            current_bucket = bucket
            current_prefix = ""
            continue
            
        # Level 1+: Inside a bucket (browse objects)
        display_path = f"s3://{current_bucket}/{current_prefix}"
        console.print(f"\n[bold cyan]📂 {display_path}[/bold cyan]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Carregando conteúdo...", total=None)
            content = list_objects(s3_client, current_bucket, current_prefix)
            
        folders = content["folders"]
        files = content["files"]
        
        # Build choices
        choices = []
        
        # Navigation options
        if current_prefix:
            choices.append({"name": "📂 .. (Subir nível)", "value": ".."})
        else:
            choices.append({"name": "📂 .. (Voltar aos buckets)", "value": ".."})
            
        # Upload action
        choices.append({"name": "⬆️  Upload Arquivo (Aqui)", "value": "upload_action"})
            
        # Folders
        for f in folders:
            folder_name = f["Prefix"].split("/")[-2] + "/" # Get last part
            choices.append({"name": f"📁 {folder_name}", "value": f"folder:{f['Prefix']}"})
            
        # Files
        for f in files:
            file_name = f["Key"].split("/")[-1]
            if not file_name: continue # Ignore empty keys (folder placeholders)
            
            size = format_size(f["Size"])
            last_mod = f["LastModified"].strftime("%Y-%m-%d %H:%M")
            choices.append({
                "name": f"📄 {file_name} ({size}) - {last_mod}", 
                "value": f"file:{f['Key']}"
            })
            
        selection = inquirer.select(
            message="Navegar:",
            choices=choices,
        ).execute()
        
        # Handle selection
        if selection == "..":
            if not current_prefix:
                current_bucket = None # Back to bucket list
            else:
                # Go up one level
                # Remove trailing slash, split, remove last part, join, add trailing slash
                parts = current_prefix.rstrip("/").split("/")
                if len(parts) <= 1:
                    current_prefix = ""
                else:
                    current_prefix = "/".join(parts[:-1]) + "/"
                    
        elif selection == "upload_action":
            upload_file(s3_client, current_bucket, current_prefix)
            # Refresh list loop will handle display update via 'continue' implicit
            
        elif selection.startswith("folder:"):
            new_prefix = selection.split(":", 1)[1]
            current_prefix = new_prefix
            
        elif selection.startswith("file:"):
            key = selection.split(":", 1)[1]
            
            action = inquirer.select(
                message=f"Arquivo: {key.split('/')[-1]}",
                choices=[
                    {"name": "⬇️  Download", "value": "download"},
                    {"name": "❌ Cancelar", "value": "cancel"},
                ]
            ).execute()
            
            if action == "download":
                download_file(s3_client, current_bucket, key)


@app.callback(invoke_without_command=True)
def s3_wizard(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile (SSO)"),
):
    """
    🪣 S3 Browser - Gerenciador de arquivos.
    """
    if ctx.invoked_subcommand is not None:
        return

    console.print(Panel(
        "[bold green]AWS S3 Browser[/bold green]\n\n"
        "Navegue e gerencie seus buckets e arquivos.",
        border_style="green",
    ))
    
    selected_profile = select_profile(profile)
    if not selected_profile:
        raise typer.Exit(1)
        
    if not ensure_sso_login(selected_profile):
        raise typer.Exit(1)
        
    s3_client = get_client("s3", selected_profile)
    
    interactive_s3_browser(s3_client)
