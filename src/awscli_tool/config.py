"""AWS SSO profile configuration and selection."""

import configparser
import subprocess
from pathlib import Path
from typing import Optional

from InquirerPy import inquirer
from rich.console import Console

console = Console()


def get_aws_config_path() -> Path:
    """Get the path to AWS config file."""
    return Path.home() / ".aws" / "config"


def get_sso_profiles() -> list[dict]:
    """
    Read SSO profiles from AWS config file.
    
    Returns a list of dicts with profile info.
    """
    config_path = get_aws_config_path()
    if not config_path.exists():
        console.print("[red]❌ Arquivo ~/.aws/config não encontrado![/red]")
        console.print("Execute 'aws configure sso' para configurar seus profiles.")
        return []
    
    config = configparser.ConfigParser()
    config.read(config_path)
    
    profiles = []
    for section in config.sections():
        if section.startswith("profile "):
            profile_name = section.replace("profile ", "")
            profile_data = dict(config[section])
            
            # Check if it's an SSO profile
            if "sso_start_url" in profile_data or "sso_session" in profile_data:
                profiles.append({
                    "name": profile_name,
                    "region": profile_data.get("region", "N/A"),
                    "account_id": profile_data.get("sso_account_id", "N/A"),
                    "role": profile_data.get("sso_role_name", "N/A"),
                })
    
    return profiles


def select_profile(profile_name: Optional[str] = None) -> Optional[str]:
    """
    Interactive profile selector.
    
    If profile_name is provided, validates it exists.
    Otherwise, shows an interactive menu.
    """
    profiles = get_sso_profiles()
    
    if not profiles:
        return None
    
    # If profile specified, validate it
    if profile_name:
        profile_names = [p["name"] for p in profiles]
        if profile_name in profile_names:
            return profile_name
        else:
            console.print(f"[red]❌ Profile '{profile_name}' não encontrado![/red]")
            console.print(f"Profiles disponíveis: {', '.join(profile_names)}")
            return None
    
    # Build choices with profile info
    choices = []
    for p in profiles:
        label = f"{p['name']} ({p['region']} - {p['account_id']})"
        choices.append({"name": label, "value": p["name"]})
    
    # Interactive selection
    selected = inquirer.select(
        message="🔐 Selecione o profile AWS:",
        choices=choices,
        default=choices[0]["value"] if choices else None,
    ).execute()
    
    return selected


def ensure_sso_login(profile: str) -> bool:
    """
    Ensure SSO session is active for the profile.
    
    Returns True if login successful or already logged in.
    """
    console.print(f"[dim]Verificando sessão SSO para profile '{profile}'...[/dim]")
    
    # Try to get caller identity to check if session is valid
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--profile", profile],
        capture_output=True,
        text=True,
    )
    
    if result.returncode == 0:
        console.print(f"[green]✓ Sessão SSO válida para '{profile}'[/green]")
        return True
    
    # Need to login
    console.print(f"[yellow]⚠ Sessão expirada. Iniciando login SSO...[/yellow]")
    
    login_result = subprocess.run(
        ["aws", "sso", "login", "--profile", profile],
        capture_output=False,
    )
    
    if login_result.returncode == 0:
        console.print(f"[green]✓ Login SSO realizado com sucesso![/green]")
        return True
    else:
        console.print(f"[red]❌ Falha no login SSO[/red]")
        return False
