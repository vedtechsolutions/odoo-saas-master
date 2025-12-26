# -*- coding: utf-8 -*-
"""
Secure SSH utilities for SaaS platform.

Provides secure remote command execution without shell injection vulnerabilities.
Uses paramiko for SSH connections when available, with secure fallback.
"""

import logging
import re
import shlex
import subprocess
import os
from typing import Optional, Tuple, List

_logger = logging.getLogger(__name__)

# Try to import paramiko for secure SSH
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False
    _logger.warning("paramiko not installed - using fallback SSH method")


# Validation patterns for safe values
SAFE_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_\-]*$')
SAFE_DB_NAME_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
SAFE_CONTAINER_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\.\-]*$')
SAFE_PATH_PATTERN = re.compile(r'^[a-zA-Z0-9_/\.\-]+$')
SAFE_IP_PATTERN = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def validate_identifier(value: str, name: str = "identifier") -> str:
    """
    Validate an identifier (database name, container name, etc.).

    Args:
        value: The value to validate
        name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError(f"{name} cannot be empty")

    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")

    # Remove any null bytes or control characters
    value = value.replace('\x00', '').strip()

    if len(value) > 128:
        raise ValidationError(f"{name} too long (max 128 chars)")

    if not SAFE_IDENTIFIER_PATTERN.match(value):
        raise ValidationError(
            f"Invalid {name}: must start with letter/underscore, "
            f"contain only alphanumeric/underscore/dash"
        )

    return value


def validate_database_name(db_name: str) -> str:
    """Validate a PostgreSQL database name."""
    if not db_name:
        raise ValidationError("Database name cannot be empty")

    db_name = db_name.replace('\x00', '').strip()

    if len(db_name) > 63:
        raise ValidationError("Database name too long (max 63 chars)")

    if not SAFE_DB_NAME_PATTERN.match(db_name):
        raise ValidationError(
            "Invalid database name: must start with letter/underscore, "
            "contain only alphanumeric/underscore"
        )

    return db_name


def validate_container_name(container_name: str) -> str:
    """Validate a Docker container name."""
    if not container_name:
        raise ValidationError("Container name cannot be empty")

    container_name = container_name.replace('\x00', '').strip()

    if len(container_name) > 128:
        raise ValidationError("Container name too long (max 128 chars)")

    if not SAFE_CONTAINER_NAME_PATTERN.match(container_name):
        raise ValidationError(
            "Invalid container name: must start with alphanumeric, "
            "contain only alphanumeric/underscore/dot/dash"
        )

    return container_name


def validate_path(path: str) -> str:
    """Validate a file path."""
    if not path:
        raise ValidationError("Path cannot be empty")

    path = path.replace('\x00', '').strip()

    if len(path) > 4096:
        raise ValidationError("Path too long")

    # Check for path traversal
    if '..' in path:
        raise ValidationError("Path cannot contain '..'")

    if not SAFE_PATH_PATTERN.match(path):
        raise ValidationError("Invalid path: contains unsafe characters")

    return path


def validate_ip_address(ip: str) -> str:
    """Validate an IP address."""
    if not ip:
        raise ValidationError("IP address cannot be empty")

    ip = ip.replace('\x00', '').strip()

    if not SAFE_IP_PATTERN.match(ip):
        raise ValidationError("Invalid IP address format")

    # Validate each octet
    parts = ip.split('.')
    for part in parts:
        if int(part) > 255:
            raise ValidationError("Invalid IP address: octet > 255")

    return ip


class SecureSSHClient:
    """
    Secure SSH client for remote command execution.

    Uses paramiko when available for secure key-based auth,
    falls back to subprocess with proper escaping otherwise.
    """

    def __init__(self, host: str, username: str = 'root',
                 password: Optional[str] = None,
                 key_file: Optional[str] = None,
                 port: int = 22,
                 timeout: int = 30):
        """
        Initialize SSH client.

        Args:
            host: Remote host IP or hostname
            username: SSH username
            password: SSH password (avoid if possible, use keys)
            key_file: Path to SSH private key
            port: SSH port
            timeout: Connection timeout
        """
        self.host = validate_ip_address(host)
        self.username = username
        self.password = password
        self.key_file = key_file
        self.port = port
        self.timeout = timeout
        self._client = None

    def connect(self):
        """Establish SSH connection."""
        if HAS_PARAMIKO:
            self._connect_paramiko()
        else:
            # For fallback, we just validate connection is possible
            pass

    def _connect_paramiko(self):
        """Connect using paramiko."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': self.host,
            'port': self.port,
            'username': self.username,
            'timeout': self.timeout,
        }

        if self.key_file:
            connect_kwargs['key_filename'] = self.key_file
        elif self.password:
            connect_kwargs['password'] = self.password

        self._client.connect(**connect_kwargs)
        _logger.debug(f"SSH connected to {self.host} via paramiko")

    def close(self):
        """Close SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

    def execute(self, command: List[str], timeout: int = 300) -> Tuple[int, str, str]:
        """
        Execute a command on the remote host.

        Args:
            command: Command as a list of arguments (NOT a string)
            timeout: Command timeout in seconds

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if HAS_PARAMIKO and self._client:
            return self._execute_paramiko(command, timeout)
        else:
            return self._execute_fallback(command, timeout)

    def _execute_paramiko(self, command: List[str], timeout: int) -> Tuple[int, str, str]:
        """Execute command using paramiko."""
        # Join command with proper shell escaping
        cmd_str = ' '.join(shlex.quote(arg) for arg in command)

        stdin, stdout, stderr = self._client.exec_command(cmd_str, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        return exit_code, stdout.read().decode(), stderr.read().decode()

    def _execute_fallback(self, command: List[str], timeout: int) -> Tuple[int, str, str]:
        """Execute command using subprocess with secure handling."""
        # Build SSH command without shell=True
        ssh_args = ['ssh', '-o', 'StrictHostKeyChecking=accept-new',
                    '-o', f'ConnectTimeout={self.timeout}']

        if self.key_file:
            ssh_args.extend(['-i', self.key_file])

        ssh_args.append(f'{self.username}@{self.host}')

        # The remote command is passed as a single argument
        remote_cmd = ' '.join(shlex.quote(arg) for arg in command)
        ssh_args.append(remote_cmd)

        try:
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'Command timed out'
        except Exception as e:
            return -1, '', str(e)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def get_db_password_from_config(env, param_name: str = 'saas.tenant_db_password') -> str:
    """
    Get database password from secure config parameter.

    Args:
        env: Odoo environment
        param_name: Config parameter name

    Returns:
        Database password
    """
    ICP = env['ir.config_parameter'].sudo()
    password = ICP.get_param(param_name)

    if not password:
        # Fallback to default (should be set during installation)
        _logger.warning(f"Config param {param_name} not set, using default")
        password = 'odoo'

    return password


def build_pg_command(action: str, db_name: str, db_user: str = 'odoo',
                     db_host: str = 'localhost', extra_args: List[str] = None) -> List[str]:
    """
    Build a PostgreSQL command with validated parameters.

    Args:
        action: 'dump', 'restore', 'drop', 'create', 'psql'
        db_name: Database name
        db_user: Database user
        db_host: Database host
        extra_args: Additional arguments

    Returns:
        Command as list of arguments
    """
    db_name = validate_database_name(db_name)

    base_args = ['-h', db_host, '-U', db_user]

    if action == 'dump':
        cmd = ['pg_dump'] + base_args + [db_name]
    elif action == 'restore':
        cmd = ['psql'] + base_args + ['-d', db_name]
    elif action == 'drop':
        cmd = ['dropdb'] + base_args + ['--if-exists', db_name]
    elif action == 'create':
        cmd = ['createdb'] + base_args + [db_name]
    elif action == 'psql':
        cmd = ['psql'] + base_args + ['-d', db_name]
    else:
        raise ValidationError(f"Unknown action: {action}")

    if extra_args:
        cmd.extend(extra_args)

    return cmd


def build_docker_exec_command(container_name: str, command: List[str],
                               user: Optional[str] = None) -> List[str]:
    """
    Build a docker exec command with validated parameters.

    Args:
        container_name: Docker container name
        command: Command to run inside container
        user: Optional user to run as

    Returns:
        Command as list of arguments
    """
    container_name = validate_container_name(container_name)

    cmd = ['docker', 'exec']

    if user:
        cmd.extend(['-u', user])

    cmd.append(container_name)
    cmd.extend(command)

    return cmd


def safe_remote_execute(env, server_ip: str, command: List[str],
                        timeout: int = 300) -> Tuple[int, str, str]:
    """
    Execute a command on a remote server securely.

    Args:
        env: Odoo environment
        server_ip: Server IP address
        command: Command as list of arguments
        timeout: Command timeout

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    ICP = env['ir.config_parameter'].sudo()

    # Get SSH credentials from config
    ssh_key_path = ICP.get_param('saas.tenant_ssh_key_path', '/root/.ssh/tenant_key')
    ssh_user = ICP.get_param('saas.tenant_ssh_user', 'root')

    try:
        with SecureSSHClient(
            host=server_ip,
            username=ssh_user,
            key_file=ssh_key_path,
            timeout=30
        ) as ssh:
            return ssh.execute(command, timeout=timeout)
    except Exception as e:
        _logger.error(f"SSH execution failed: {e}")
        return -1, '', str(e)
