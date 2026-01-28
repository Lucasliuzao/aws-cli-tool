"""Log formatting utilities for structured log display."""

import json
import re
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()


# Log level colors
LEVEL_COLORS = {
    "ERROR": "red bold",
    "WARN": "yellow",
    "WARNING": "yellow",
    "INFO": "green",
    "DEBUG": "dim",
    "TRACE": "dim italic",
}

# Common patterns for log level extraction
LEVEL_PATTERNS = [
    r'"level"\s*:\s*"(\w+)"',
    r'"severity"\s*:\s*"(\w+)"',
    r'\[(\w+)\]',
    r'\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE)\b',
]


def extract_log_level(message: str) -> str:
    """Extract log level from message."""
    message_upper = message.upper()
    
    for pattern in LEVEL_PATTERNS:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            level = match.group(1).upper()
            if level in LEVEL_COLORS:
                return level
            # Map common variations
            if level == "WARNING":
                return "WARN"
    
    # Default based on content
    if "ERROR" in message_upper or "EXCEPTION" in message_upper or "FAILED" in message_upper:
        return "ERROR"
    elif "WARN" in message_upper:
        return "WARN"
    
    return "INFO"


def parse_json_log(message: str) -> dict[str, Any] | None:
    """Try to parse message as JSON."""
    try:
        # Find JSON in the message
        json_match = re.search(r'\{.*\}', message, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return None


def format_timestamp(timestamp: int | float | str) -> str:
    """Format timestamp to readable string."""
    try:
        if isinstance(timestamp, (int, float)):
            # CloudWatch timestamps are in milliseconds
            if timestamp > 1e12:
                timestamp = timestamp / 1000
            dt = datetime.fromtimestamp(timestamp)
        else:
            dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(timestamp)


def format_log_entry(event: dict, show_json: bool = True) -> dict:
    """
    Format a single log event for display.
    
    Returns dict with: timestamp, level, message, json_data
    """
    timestamp = format_timestamp(event.get("timestamp", 0))
    message = event.get("message", "")
    
    # Try to parse as JSON
    json_data = parse_json_log(message) if show_json else None
    
    # Extract level
    level = extract_log_level(message)
    if json_data and "level" in json_data:
        level = json_data["level"].upper()
    
    # Clean message for display
    # Strip ANSI codes for clean display in Rich
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_message = ansi_escape.sub('', message).strip()
    
    # Do NOT truncate heavily here, let Rich table handle folding.
    # We only truncate if it's absurdly long to prevent memory issues, e.g. 5000 chars.
    if len(clean_message) > 5000 and not json_data:
        clean_message = clean_message[:5000] + "..."
    
    return {
        "timestamp": timestamp,
        "level": level,
        "message": clean_message,
        "json_data": json_data,
    }


def create_log_table(events: list[dict], service_name: str, cluster_name: str) -> Table:
    """Create a Rich table with formatted logs."""
    table = Table(
        title=f"📋 ECS Logs - {service_name} | {cluster_name}",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )
    
    table.add_column("Timestamp", style="dim", width=20, no_wrap=True)
    table.add_column("Level", width=7, justify="center")
    table.add_column("Message", overflow="fold")
    
    for event in events:
        formatted = format_log_entry(event)
        
        level = formatted["level"]
        level_style = LEVEL_COLORS.get(level, "white")
        level_text = Text(level, style=level_style)
        
        # Format message
        message = formatted["message"]
        if formatted["json_data"]:
            # Show formatted JSON
            try:
                pretty_json = json.dumps(formatted["json_data"], indent=2, ensure_ascii=False)
                if len(pretty_json) > 500:
                    pretty_json = pretty_json[:500] + "\n..."
                message = pretty_json
            except (TypeError, ValueError):
                pass
        
        # Color message based on level
        if level == "ERROR":
            message_text = Text(message, style="red")
        elif level == "WARN":
            message_text = Text(message, style="yellow")
        else:
            message_text = Text(message)
        
        table.add_row(
            formatted["timestamp"],
            level_text,
            message_text,
        )
    
    return table


def display_logs(events: list[dict], service_name: str, cluster_name: str):
    """Display formatted logs to console."""
    if not events:
        console.print("[yellow]⚠ Nenhum log encontrado.[/yellow]")
        return
    
    table = create_log_table(events, service_name, cluster_name)
    console.print(table)
    console.print(f"\n[dim]Total: {len(events)} eventos[/dim]")


def display_log_detail(event: dict):
    """Display a single log event in detail with JSON highlighting."""
    formatted = format_log_entry(event, show_json=True)
    
    console.print(f"\n[dim]Timestamp:[/dim] {formatted['timestamp']}")
    console.print(f"[dim]Level:[/dim] [{LEVEL_COLORS.get(formatted['level'], 'white')}]{formatted['level']}[/]")
    
    if formatted["json_data"]:
        console.print("\n[dim]JSON Content:[/dim]")
        json_str = json.dumps(formatted["json_data"], indent=2, ensure_ascii=False)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, border_style="dim"))
    else:
        console.print(f"\n[dim]Message:[/dim]\n{formatted['message']}")
