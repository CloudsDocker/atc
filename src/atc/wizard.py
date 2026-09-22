import os
import sys
import subprocess
import json
import time
from pathlib import Path
from typing import Any


import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .config import config_dir, config_path


def run_command(cmd: list[str]) -> str:
    """Run a command and return stdout as string."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return ""


def get_k8s_contexts() -> list[str]:
    stdout = run_command(["kubectl", "config", "view", "-o", "jsonpath={.contexts[*].name}"])
    return stdout.split() if stdout else []


def get_k8s_namespaces(context: str) -> list[str]:
    stdout = run_command(["kubectl", "get", "namespaces", "--context", context, "-o", "jsonpath={.items[*].metadata.name}"])
    return stdout.split() if stdout else []


def get_k8s_services(context: str, namespace: str) -> list[str]:
    stdout = run_command(["kubectl", "get", "svc", "--context", context, "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"])
    return stdout.split() if stdout else []


def verify_aws_session(profile: str) -> bool:
    """Verify AWS session using sts get-caller-identity."""
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("aws-cli not found in PATH.")
        return False


def get_aws_profiles() -> list[str]:
    return boto3.Session().available_profiles


def get_mwaa_environments(profile: str, region: str) -> list[str]:
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        client = session.client('mwaa')
        response = client.list_environments()
        return response.get('Environments', [])
    except Exception as e:
        print(f"Error fetching MWAA environments: {e}")
        return []


def write_to_config(profile_name: str, config_data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    if path.exists():
        lines = path.read_text().splitlines()
    
    # If no default is set, set this as default
    has_default = any(line.startswith("default =") for line in lines)
    if not has_default:
        lines.insert(0, f'default = "{profile_name}"')
        lines.insert(1, "")
    
    lines.append(f"")
    lines.append(f"[profiles.{profile_name}]")
    for key, value in config_data.items():
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f'{key} = {"true" if value else "false"}')
        else:
            lines.append(f'{key} = {value}')
    
    lines.append("")
    path.write_text("\n".join(lines) + "\n")
    print(f"Configuration saved to {path}")


def run_wizard():
    from .tui.wizard_app import WizardApp
    app = WizardApp()
    app.run()
