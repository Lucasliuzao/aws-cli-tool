"""AWS client factory with profile support."""

from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from rich.console import Console

console = Console()


@lru_cache(maxsize=10)
def get_session(profile: str) -> boto3.Session:
    """Get or create a boto3 session for the given profile."""
    return boto3.Session(profile_name=profile)


def get_client(service: str, profile: str, region: str | None = None) -> Any:
    """
    Get a boto3 client for the specified service.
    
    Args:
        service: AWS service name (e.g., 'ecs', 'apigateway', 'logs')
        profile: AWS profile name
        region: Optional region override
    
    Returns:
        boto3 client for the service
    """
    session = get_session(profile)
    
    config = Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=30,
    )
    
    kwargs = {"config": config}
    if region:
        kwargs["region_name"] = region
    
    return session.client(service, **kwargs)


def get_resource(service: str, profile: str, region: str | None = None) -> Any:
    """
    Get a boto3 resource for the specified service.
    
    Args:
        service: AWS service name
        profile: AWS profile name
        region: Optional region override
    
    Returns:
        boto3 resource for the service
    """
    session = get_session(profile)
    
    kwargs = {}
    if region:
        kwargs["region_name"] = region
    
    return session.resource(service, **kwargs)
