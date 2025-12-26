# -*- coding: utf-8 -*-
"""
Secure backup execution utilities.

Provides secure command execution for backup/restore operations
without shell injection vulnerabilities.
"""

import logging
import subprocess
import shlex
import os
from typing import Optional, Tuple, List

from odoo.addons.saas_core.utils.secure_ssh import (
    validate_database_name,
    validate_container_name,
    validate_path,
    validate_ip_address,
    ValidationError,
)

_logger = logging.getLogger(__name__)


class BackupCommandBuilder:
    """
    Builds secure backup/restore commands with validated parameters.

    All parameters are validated before being used in commands.
    """

    def __init__(self, env, server_ip: str, ssh_key_path: Optional[str] = None):
        """
        Initialize the command builder.

        Args:
            env: Odoo environment
            server_ip: Remote server IP
            ssh_key_path: Path to SSH private key
        """
        self.env = env
        self.server_ip = validate_ip_address(server_ip)

        # Get SSH configuration from system parameters
        ICP = env['ir.config_parameter'].sudo()
        self.ssh_key_path = ssh_key_path or ICP.get_param(
            'saas.tenant_ssh_key_path', '/root/.ssh/tenant_key'
        )
        self.ssh_user = ICP.get_param('saas.tenant_ssh_user', 'root')

        # Get database password from secure config (not hardcoded)
        self.db_password = ICP.get_param('saas.tenant_db_password', 'odoo')

    def _get_ssh_base_args(self) -> List[str]:
        """Get base SSH command arguments."""
        args = [
            'ssh',
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ConnectTimeout=30',
            '-o', 'BatchMode=yes',
        ]

        if self.ssh_key_path and os.path.exists(self.ssh_key_path):
            args.extend(['-i', self.ssh_key_path])

        args.append(f'{self.ssh_user}@{self.server_ip}')
        return args

    def _get_scp_base_args(self) -> List[str]:
        """Get base SCP command arguments."""
        args = [
            'scp',
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ConnectTimeout=30',
            '-o', 'BatchMode=yes',
        ]

        if self.ssh_key_path and os.path.exists(self.ssh_key_path):
            args.extend(['-i', self.ssh_key_path])

        return args

    def execute_remote(self, command: List[str], timeout: int = 300) -> Tuple[int, str, str]:
        """
        Execute a command on the remote server securely.

        Args:
            command: Command as list of arguments
            timeout: Command timeout in seconds

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        ssh_args = self._get_ssh_base_args()

        # Join the remote command with proper escaping
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
            _logger.error(f"Remote execution failed: {e}")
            return -1, '', str(e)

    def execute_docker_command(self, container_name: str, command: List[str],
                                timeout: int = 300) -> Tuple[int, str, str]:
        """
        Execute a command inside a Docker container on the remote server.

        Args:
            container_name: Docker container name
            command: Command to run inside container
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        container_name = validate_container_name(container_name)

        # Build docker exec command
        docker_cmd = ['docker', 'exec', container_name] + command

        return self.execute_remote(docker_cmd, timeout)

    def scp_download(self, remote_path: str, local_path: str,
                     timeout: int = 600) -> Tuple[int, str, str]:
        """
        Download a file from the remote server.

        Args:
            remote_path: Path on remote server
            local_path: Local destination path
            timeout: Transfer timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        remote_path = validate_path(remote_path)
        local_path = validate_path(local_path)

        scp_args = self._get_scp_base_args()
        scp_args.append(f'{self.ssh_user}@{self.server_ip}:{remote_path}')
        scp_args.append(local_path)

        try:
            result = subprocess.run(
                scp_args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'SCP transfer timed out'
        except Exception as e:
            return -1, '', str(e)

    def scp_upload(self, local_path: str, remote_path: str,
                   timeout: int = 600) -> Tuple[int, str, str]:
        """
        Upload a file to the remote server.

        Args:
            local_path: Local source path
            remote_path: Remote destination path
            timeout: Transfer timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        local_path = validate_path(local_path)
        remote_path = validate_path(remote_path)

        scp_args = self._get_scp_base_args()
        scp_args.append(local_path)
        scp_args.append(f'{self.ssh_user}@{self.server_ip}:{remote_path}')

        try:
            result = subprocess.run(
                scp_args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'SCP transfer timed out'
        except Exception as e:
            return -1, '', str(e)

    def create_database_dump(self, container_name: str, db_name: str,
                              output_path: str, timeout: int = 600) -> Tuple[int, str, str]:
        """
        Create a database dump inside a container.

        Args:
            container_name: Docker container name
            db_name: Database name
            output_path: Path for the dump file (inside container)
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        db_name = validate_database_name(db_name)
        container_name = validate_container_name(container_name)
        output_path = validate_path(output_path)

        # Build pg_dump command - password is passed via environment
        dump_cmd = [
            'bash', '-c',
            f'PGPASSWORD={shlex.quote(self.db_password)} '
            f'pg_dump -h host.docker.internal -U odoo {shlex.quote(db_name)} | '
            f'gzip > {shlex.quote(output_path)}'
        ]

        return self.execute_docker_command(container_name, dump_cmd, timeout)

    def restore_database(self, container_name: str, db_name: str,
                          dump_path: str, timeout: int = 1800) -> Tuple[int, str, str]:
        """
        Restore a database from a dump file.

        Args:
            container_name: Docker container name
            db_name: Database name
            dump_path: Path to the dump file (inside container)
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        db_name = validate_database_name(db_name)
        container_name = validate_container_name(container_name)
        dump_path = validate_path(dump_path)

        # Restore command
        restore_cmd = [
            'bash', '-c',
            f'gunzip -c {shlex.quote(dump_path)} | '
            f'PGPASSWORD={shlex.quote(self.db_password)} '
            f'psql -h host.docker.internal -U odoo -d {shlex.quote(db_name)}'
        ]

        return self.execute_docker_command(container_name, restore_cmd, timeout)

    def terminate_db_connections(self, container_name: str, db_name: str,
                                  timeout: int = 60) -> Tuple[int, str, str]:
        """
        Terminate all connections to a database.

        Args:
            container_name: Docker container name
            db_name: Database name
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        db_name = validate_database_name(db_name)
        container_name = validate_container_name(container_name)

        terminate_cmd = [
            'bash', '-c',
            f'PGPASSWORD={shlex.quote(self.db_password)} '
            f'psql -h host.docker.internal -U odoo -d postgres -c '
            f'"SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            f'WHERE datname = \'{db_name}\' AND pid <> pg_backend_pid();"'
        ]

        return self.execute_docker_command(container_name, terminate_cmd, timeout)

    def drop_database(self, container_name: str, db_name: str,
                       timeout: int = 60) -> Tuple[int, str, str]:
        """
        Drop a database.

        Args:
            container_name: Docker container name
            db_name: Database name
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        db_name = validate_database_name(db_name)
        container_name = validate_container_name(container_name)

        drop_cmd = [
            'bash', '-c',
            f'PGPASSWORD={shlex.quote(self.db_password)} '
            f'dropdb -h host.docker.internal -U odoo --if-exists {shlex.quote(db_name)}'
        ]

        return self.execute_docker_command(container_name, drop_cmd, timeout)

    def create_database(self, container_name: str, db_name: str,
                         timeout: int = 60) -> Tuple[int, str, str]:
        """
        Create a database.

        Args:
            container_name: Docker container name
            db_name: Database name
            timeout: Command timeout

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        db_name = validate_database_name(db_name)
        container_name = validate_container_name(container_name)

        create_cmd = [
            'bash', '-c',
            f'PGPASSWORD={shlex.quote(self.db_password)} '
            f'createdb -h host.docker.internal -U odoo {shlex.quote(db_name)}'
        ]

        return self.execute_docker_command(container_name, create_cmd, timeout)


class SecureBackupExecutor:
    """
    High-level secure backup executor.

    Provides methods for complete backup/restore operations with
    proper error handling and logging.
    """

    def __init__(self, env, instance):
        """
        Initialize the executor.

        Args:
            env: Odoo environment
            instance: saas.instance record
        """
        self.env = env
        self.instance = instance

        if not instance.server_id:
            raise ValidationError("Instance has no server assigned")

        self.builder = BackupCommandBuilder(
            env,
            instance.server_id.ip_address
        )

    def create_full_backup(self, backup_dir: str) -> dict:
        """
        Create a full backup (database + filestore).

        Args:
            backup_dir: Directory for backup files on remote server

        Returns:
            dict with backup information
        """
        container = validate_container_name(self.instance.container_name)
        db_name = validate_database_name(self.instance.database_name)
        backup_dir = validate_path(backup_dir)

        result = {
            'database_size': 0,
            'filestore_size': 0,
            'success': False,
            'error': None,
        }

        try:
            # Create backup directory
            self.builder.execute_remote(['mkdir', '-p', backup_dir])

            # Dump database
            db_dump_path = f'{backup_dir}/database.sql.gz'
            code, out, err = self.builder.create_database_dump(
                container, db_name, f'/tmp/database.sql.gz'
            )

            if code != 0:
                result['error'] = f"Database dump failed: {err}"
                return result

            # Copy dump out of container
            self.builder.execute_remote([
                'docker', 'cp',
                f'{container}:/tmp/database.sql.gz',
                db_dump_path
            ])

            # Cleanup inside container
            self.builder.execute_docker_command(
                container, ['rm', '-f', '/tmp/database.sql.gz']
            )

            # Get database dump size
            code, out, err = self.builder.execute_remote([
                'stat', '-c%s', db_dump_path
            ])
            if code == 0:
                result['database_size'] = int(out.strip() or 0)

            # Archive filestore
            fs_archive_path = f'{backup_dir}/filestore.tar.gz'
            self.builder.execute_docker_command(container, [
                'tar', '-czf', '/tmp/filestore.tar.gz',
                '-C', '/opt/odoo/data/filestore', '.'
            ], timeout=600)

            # Copy filestore out of container
            self.builder.execute_remote([
                'docker', 'cp',
                f'{container}:/tmp/filestore.tar.gz',
                fs_archive_path
            ])

            # Cleanup inside container
            self.builder.execute_docker_command(
                container, ['rm', '-f', '/tmp/filestore.tar.gz']
            )

            # Get filestore size
            code, out, err = self.builder.execute_remote([
                'stat', '-c%s', fs_archive_path
            ])
            if code == 0:
                result['filestore_size'] = int(out.strip() or 0)

            result['success'] = True
            _logger.info(f"Backup completed for {self.instance.subdomain}")

        except Exception as e:
            result['error'] = str(e)
            _logger.error(f"Backup failed for {self.instance.subdomain}: {e}")

        return result

    def restore_full_backup(self, backup_dir: str) -> dict:
        """
        Restore a full backup (database + filestore).

        Args:
            backup_dir: Directory containing backup files on remote server

        Returns:
            dict with restore information
        """
        container = validate_container_name(self.instance.container_name)
        db_name = validate_database_name(self.instance.database_name)
        backup_dir = validate_path(backup_dir)

        result = {
            'success': False,
            'error': None,
        }

        try:
            # Terminate database connections
            self.builder.terminate_db_connections(container, db_name)

            import time
            time.sleep(2)

            # Drop and recreate database
            self.builder.drop_database(container, db_name)
            code, out, err = self.builder.create_database(container, db_name)

            if code != 0:
                result['error'] = f"Create database failed: {err}"
                return result

            # Copy dump into container
            db_dump_path = f'{backup_dir}/database.sql.gz'
            self.builder.execute_remote([
                'docker', 'cp', db_dump_path,
                f'{container}:/tmp/database.sql.gz'
            ])

            # Restore database
            code, out, err = self.builder.restore_database(
                container, db_name, '/tmp/database.sql.gz'
            )

            if code != 0:
                _logger.warning(f"Database restore warnings: {err[:500]}")

            # Cleanup dump
            self.builder.execute_docker_command(
                container, ['rm', '-f', '/tmp/database.sql.gz']
            )

            # Restore filestore
            fs_archive_path = f'{backup_dir}/filestore.tar.gz'
            self.builder.execute_remote([
                'docker', 'cp', fs_archive_path,
                f'{container}:/tmp/filestore.tar.gz'
            ])

            # Extract filestore
            self.builder.execute_docker_command(container, [
                'bash', '-c',
                'rm -rf /opt/odoo/data/filestore/* && '
                'tar -xzf /tmp/filestore.tar.gz -C /opt/odoo/data/filestore && '
                'chown -R odoo:odoo /opt/odoo/data/filestore'
            ], timeout=600)

            # Cleanup
            self.builder.execute_docker_command(
                container, ['rm', '-f', '/tmp/filestore.tar.gz']
            )

            result['success'] = True
            _logger.info(f"Restore completed for {self.instance.subdomain}")

        except Exception as e:
            result['error'] = str(e)
            _logger.error(f"Restore failed for {self.instance.subdomain}: {e}")

        return result
