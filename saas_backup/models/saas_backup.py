# -*- coding: utf-8 -*-
"""
SaaS Backup model.

Manages individual backup records for tenant instances.
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.config import BackupConfig

_logger = logging.getLogger(__name__)


class BackupType:
    """Backup type constants."""
    FULL = 'full'
    DATABASE = 'database'
    FILESTORE = 'filestore'

    @classmethod
    def get_selection(cls):
        return [
            (cls.FULL, 'Full (Database + Filestore)'),
            (cls.DATABASE, 'Database Only'),
            (cls.FILESTORE, 'Filestore Only'),
        ]


class BackupState:
    """Backup state constants."""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    EXPIRED = 'expired'
    DELETED = 'deleted'

    @classmethod
    def get_selection(cls):
        return [
            (cls.PENDING, 'Pending'),
            (cls.IN_PROGRESS, 'In Progress'),
            (cls.COMPLETED, 'Completed'),
            (cls.FAILED, 'Failed'),
            (cls.EXPIRED, 'Expired'),
            (cls.DELETED, 'Deleted'),
        ]


class BackupTrigger:
    """Backup trigger type constants."""
    SCHEDULED = 'scheduled'
    MANUAL = 'manual'
    PRE_UPDATE = 'pre_update'
    PRE_DELETE = 'pre_delete'

    @classmethod
    def get_selection(cls):
        return [
            (cls.SCHEDULED, 'Scheduled'),
            (cls.MANUAL, 'Manual'),
            (cls.PRE_UPDATE, 'Pre-Update'),
            (cls.PRE_DELETE, 'Pre-Delete'),
        ]


class SaasBackup(models.Model):
    """Individual backup record for a SaaS instance."""

    _name = 'saas.backup'
    _description = 'SaaS Backup'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    # SQL Constraints (Odoo 19 syntax)
    _reference_unique = models.Constraint(
        'UNIQUE(reference)',
        'Backup reference must be unique!'
    )

    # Basic fields
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    reference = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New',
        index=True,
    )

    # State
    state = fields.Selection(
        selection=BackupState.get_selection(),
        string='Status',
        default=BackupState.PENDING,
        required=True,
        tracking=True,
        index=True,
    )

    # Type and trigger
    backup_type = fields.Selection(
        selection=BackupType.get_selection(),
        string='Backup Type',
        default=BackupType.FULL,
        required=True,
    )
    trigger = fields.Selection(
        selection=BackupTrigger.get_selection(),
        string='Trigger',
        default=BackupTrigger.MANUAL,
        required=True,
    )

    # Relations
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    schedule_id = fields.Many2one(
        'saas.backup.schedule',
        string='Schedule',
        ondelete='set null',
    )

    # Instance info (denormalized for history)
    instance_subdomain = fields.Char(
        string='Subdomain',
        readonly=True,
    )
    instance_database = fields.Char(
        string='Database Name',
        readonly=True,
    )

    # Storage info
    storage_path = fields.Char(
        string='Storage Path',
        readonly=True,
    )
    storage_type = fields.Selection(
        selection=[
            ('local', 'Local Filesystem'),
            ('s3', 'S3 Compatible'),
        ],
        string='Storage Type',
        default=lambda self: self._get_default_storage_type(),
        required=True,
        help='Where to store the backup. S3 requires configuration in System Parameters.',
    )
    s3_bucket = fields.Char(
        string='S3 Bucket',
    )
    s3_key = fields.Char(
        string='S3 Key',
    )

    @api.model
    def _get_default_storage_type(self):
        """Get default storage type from system config."""
        ICP = self.env['ir.config_parameter'].sudo()
        default = ICP.get_param('saas.backup_default_storage', 's3')
        # Validate S3 is configured if it's the default
        if default == 's3':
            s3_endpoint = ICP.get_param('saas.s3_endpoint')
            s3_bucket = ICP.get_param('saas.s3_bucket')
            if not s3_endpoint or not s3_bucket:
                return 'local'
        return default

    def _is_s3_configured(self):
        """Check if S3 storage is properly configured."""
        ICP = self.env['ir.config_parameter'].sudo()
        return all([
            ICP.get_param('saas.s3_endpoint'),
            ICP.get_param('saas.s3_bucket'),
            ICP.get_param('saas.s3_access_key'),
            ICP.get_param('saas.s3_secret_key'),
        ])

    @api.constrains('storage_type')
    def _check_storage_type_config(self):
        """Validate that S3 is configured when S3 storage is selected."""
        for backup in self:
            if backup.storage_type == 's3' and not backup._is_s3_configured():
                raise ValidationError(
                    "S3 storage is not configured. Please configure S3 settings in:\n"
                    "Settings > Technical > System Parameters:\n"
                    "- saas.s3_endpoint\n"
                    "- saas.s3_bucket\n"
                    "- saas.s3_access_key\n"
                    "- saas.s3_secret_key"
                )

    # Size tracking
    database_size = fields.Float(
        string='Database Size (MB)',
        readonly=True,
    )
    filestore_size = fields.Float(
        string='Filestore Size (MB)',
        readonly=True,
    )
    total_size = fields.Float(
        string='Total Size (MB)',
        compute='_compute_total_size',
        store=True,
    )
    size_display = fields.Char(
        string='Size',
        compute='_compute_size_display',
    )

    # Timing
    started_at = fields.Datetime(
        string='Started At',
    )
    completed_at = fields.Datetime(
        string='Completed At',
    )
    duration = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True,
    )
    expires_at = fields.Date(
        string='Expires At',
        index=True,
    )

    # Verification
    is_verified = fields.Boolean(
        string='Verified',
        default=False,
    )
    verified_at = fields.Datetime(
        string='Verified At',
    )
    checksum = fields.Char(
        string='Checksum (MD5)',
    )

    # Encryption (T-094)
    is_encrypted = fields.Boolean(
        string='Encrypted',
        default=False,
        help='Indicates if the backup is encrypted with AES-256',
    )

    # Error tracking
    error_message = fields.Text(
        string='Error Message',
    )

    # Restore tracking
    restore_count = fields.Integer(
        string='Restore Count',
        default=0,
    )
    last_restored_at = fields.Datetime(
        string='Last Restored At',
    )

    # Notes
    notes = fields.Text(
        string='Notes',
    )

    @api.depends('instance_id', 'create_date')
    def _compute_name(self):
        """Generate backup name."""
        for backup in self:
            if backup.instance_id and backup.create_date:
                date_str = backup.create_date.strftime('%Y-%m-%d %H:%M')
                backup.name = f"{backup.instance_id.subdomain} - {date_str}"
            else:
                backup.name = backup.reference or 'New Backup'

    @api.depends('database_size', 'filestore_size')
    def _compute_total_size(self):
        """Calculate total backup size."""
        for backup in self:
            backup.total_size = (backup.database_size or 0) + (backup.filestore_size or 0)

    def _compute_size_display(self):
        """Format size for display."""
        for backup in self:
            size_mb = backup.total_size or 0
            if size_mb >= 1024:
                backup.size_display = f"{size_mb / 1024:.2f} GB"
            else:
                backup.size_display = f"{size_mb:.2f} MB"

    @api.depends('started_at', 'completed_at')
    def _compute_duration(self):
        """Calculate backup duration."""
        for backup in self:
            if backup.started_at and backup.completed_at:
                delta = backup.completed_at - backup.started_at
                backup.duration = delta.total_seconds()
            else:
                backup.duration = 0

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference and set instance info."""
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'saas.backup'
                ) or 'New'

            # Denormalize instance info
            if vals.get('instance_id'):
                instance = self.env[ModelNames.INSTANCE].browse(vals['instance_id'])
                vals['instance_subdomain'] = instance.subdomain
                vals['instance_database'] = instance.database_name

        return super().create(vals_list)

    def action_start_backup(self):
        """Start the backup process."""
        self.ensure_one()
        if self.state != BackupState.PENDING:
            raise UserError(_("Can only start pending backups."))

        self.write({
            'state': BackupState.IN_PROGRESS,
            'started_at': fields.Datetime.now(),
        })

        try:
            self._execute_backup()
        except Exception as e:
            self._handle_backup_failure(str(e))
            raise

        return True

    def _execute_backup(self):
        """
        Execute the actual backup with selected storage type.

        Supports:
        - Full backup (database + filestore)
        - Database-only backup
        - Filestore-only backup
        - AES-256 encryption for S3 uploads (T-094)
        - Filestore archiving from Docker containers (T-093)
        """
        instance = self.instance_id
        if not instance:
            raise UserError(_("No instance associated with this backup."))

        backup_type = self.backup_type or BackupType.DATABASE
        _logger.info(f"Starting {backup_type} backup for instance {instance.subdomain} (storage: {self.storage_type})")

        # Determine if we should use S3 based on user selection
        use_s3 = self.storage_type == 's3'

        # Get S3 configuration if needed
        ICP = self.env['ir.config_parameter'].sudo()
        s3_endpoint = None
        s3_bucket = None
        s3_access_key = None
        s3_secret_key = None

        if use_s3:
            s3_endpoint = ICP.get_param('saas.s3_endpoint')
            s3_bucket = ICP.get_param('saas.s3_bucket')
            s3_access_key = ICP.get_param('saas.s3_access_key')
            s3_secret_key = ICP.get_param('saas.s3_secret_key')

            if not all([s3_endpoint, s3_bucket, s3_access_key, s3_secret_key]):
                raise UserError(_("S3 storage selected but not configured. Please configure S3 in System Parameters."))

        # Get encryption key (optional - if set, backups will be encrypted)
        encryption_key = ICP.get_param('saas.backup_encryption_key')
        use_encryption = bool(encryption_key) and use_s3  # Only encrypt S3 backups

        # Build backup path
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{instance.subdomain}_{timestamp}.tar.gz"
        if use_encryption:
            backup_filename += ".enc"  # Mark encrypted backups

        # Get tenant server SSH credentials
        ssh_password = ICP.get_param('saas.tenant_ssh_password')
        server = instance.server_id

        if not server:
            raise UserError(_("Instance has no server assigned."))

        try:
            # Create backup on tenant server via SSH
            db_name = instance.database_name
            container_name = instance.container_name
            remote_backup_dir = f"/tmp/backup_{instance.subdomain}_{timestamp}"
            remote_backup_path = f"/tmp/{backup_filename}"

            # SSH command to create backup
            ssh_cmd = f"sshpass -p '{ssh_password}' ssh -o StrictHostKeyChecking=no root@{server.ip_address}"

            # Create temp backup directory
            mkdir_cmd = f"{ssh_cmd} \"mkdir -p {remote_backup_dir}\""
            result = subprocess.run(mkdir_cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                _logger.warning(f"Failed to create temp backup directory: {result.stderr}")

            db_size_mb = 0
            filestore_size_mb = 0

            # Step 1: Dump database if needed (full or database-only backup)
            if backup_type in [BackupType.FULL, BackupType.DATABASE]:
                _logger.info(f"Dumping database {db_name}...")
                dump_cmd = f"{ssh_cmd} \"PGPASSWORD=odoo pg_dump -h localhost -U odoo {db_name} | gzip > {remote_backup_dir}/database.sql.gz\""
                result = subprocess.run(dump_cmd, shell=True, capture_output=True, text=True, timeout=600)

                if result.returncode != 0:
                    raise Exception(f"Database dump failed: {result.stderr}")

                # Get database dump size
                size_cmd = f"{ssh_cmd} \"stat -c%s {remote_backup_dir}/database.sql.gz 2>/dev/null || echo 0\""
                size_result = subprocess.run(size_cmd, shell=True, capture_output=True, text=True, timeout=30)
                db_size_mb = int(size_result.stdout.strip() or 0) / (1024 * 1024)

            # Step 2: Archive filestore if needed (full or filestore-only backup) - T-093
            if backup_type in [BackupType.FULL, BackupType.FILESTORE]:
                if container_name:
                    _logger.info(f"Archiving filestore from container {container_name}...")
                    # Docker container: filestore is at /opt/odoo/data/filestore/{db_name}
                    # We need to copy it out of the container first
                    filestore_archive = f"{remote_backup_dir}/filestore.tar.gz"

                    # Create filestore archive from inside container
                    archive_cmd = f"{ssh_cmd} \"docker exec {container_name} tar -czf /tmp/filestore.tar.gz -C /opt/odoo/data/filestore . 2>/dev/null || echo 'no_filestore'\""
                    result = subprocess.run(archive_cmd, shell=True, capture_output=True, text=True, timeout=600)

                    if 'no_filestore' not in result.stdout:
                        # Copy filestore archive from container
                        copy_cmd = f"{ssh_cmd} \"docker cp {container_name}:/tmp/filestore.tar.gz {filestore_archive}\""
                        copy_result = subprocess.run(copy_cmd, shell=True, capture_output=True, text=True, timeout=120)
                        if copy_result.returncode != 0:
                            _logger.warning(f"Failed to copy filestore archive from container: {copy_result.stderr}")

                        # Cleanup inside container
                        cleanup_container_cmd = f"{ssh_cmd} \"docker exec {container_name} rm -f /tmp/filestore.tar.gz\""
                        cleanup_result = subprocess.run(cleanup_container_cmd, shell=True, capture_output=True, text=True, timeout=30)
                        if cleanup_result.returncode != 0:
                            _logger.debug(f"Cleanup in container failed: {cleanup_result.stderr}")

                        # Get filestore size
                        size_cmd = f"{ssh_cmd} \"stat -c%s {filestore_archive} 2>/dev/null || echo 0\""
                        size_result = subprocess.run(size_cmd, shell=True, capture_output=True, text=True, timeout=30)
                        filestore_size_mb = int(size_result.stdout.strip() or 0) / (1024 * 1024)
                        _logger.info(f"Filestore archived: {filestore_size_mb:.2f} MB")
                    else:
                        _logger.warning(f"No filestore found in container {container_name}")
                else:
                    _logger.warning("Filestore backup requires Docker container")

            # Step 3: Create final backup archive (tar all components together)
            _logger.info("Creating final backup archive...")
            tar_cmd = f"{ssh_cmd} \"cd {remote_backup_dir} && tar -czf {remote_backup_path.replace('.enc', '')} .\""
            result = subprocess.run(tar_cmd, shell=True, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                raise Exception(f"Archive creation failed: {result.stderr}")

            # Step 4: Encrypt if enabled (T-094)
            if use_encryption:
                _logger.info("Encrypting backup with AES-256...")
                encrypted_path = remote_backup_path
                unencrypted_path = remote_backup_path.replace('.enc', '')

                # Use openssl for AES-256-CBC encryption
                encrypt_cmd = f"{ssh_cmd} \"openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 -in {unencrypted_path} -out {encrypted_path} -pass pass:{encryption_key}\""
                result = subprocess.run(encrypt_cmd, shell=True, capture_output=True, text=True, timeout=300)

                if result.returncode != 0:
                    raise Exception(f"Encryption failed: {result.stderr}")

                # Remove unencrypted file
                rm_cmd = f"{ssh_cmd} \"rm -f {unencrypted_path}\""
                rm_result = subprocess.run(rm_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if rm_result.returncode != 0:
                    _logger.warning(f"Failed to remove unencrypted file: {rm_result.stderr}")
                _logger.info("Backup encrypted successfully")

            # Step 5: Get final backup file size
            size_cmd = f"{ssh_cmd} \"stat -c%s {remote_backup_path} 2>/dev/null || echo 0\""
            size_result = subprocess.run(size_cmd, shell=True, capture_output=True, text=True, timeout=30)
            total_size = int(size_result.stdout.strip() or 0)

            # Step 6: Calculate checksum
            checksum_cmd = f"{ssh_cmd} \"md5sum {remote_backup_path} | cut -d' ' -f1\""
            checksum_result = subprocess.run(checksum_cmd, shell=True, capture_output=True, text=True, timeout=60)
            checksum = checksum_result.stdout.strip()

            # Step 7: Store backup based on selected storage type
            if use_s3:
                s3_key = f"backups/{instance.subdomain}/{backup_filename}"
                self._upload_to_s3(
                    server, ssh_password, remote_backup_path,
                    s3_endpoint, s3_bucket, s3_access_key, s3_secret_key, s3_key
                )
                storage_path = f"s3://{s3_bucket}/{s3_key}"

                # Cleanup remote temp files
                cleanup_cmd = f"{ssh_cmd} \"rm -rf {remote_backup_dir} {remote_backup_path}\""
                cleanup_result = subprocess.run(cleanup_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if cleanup_result.returncode != 0:
                    _logger.debug(f"Remote cleanup warning: {cleanup_result.stderr}")
            else:
                # Local storage - move to permanent backup directory on tenant server
                local_backup_dir = f"{BackupConfig.BACKUP_PATH}/{instance.subdomain}"
                mkdir_cmd = f"{ssh_cmd} \"mkdir -p {local_backup_dir}\""
                mkdir_result = subprocess.run(mkdir_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if mkdir_result.returncode != 0:
                    _logger.warning(f"Failed to create local backup dir: {mkdir_result.stderr}")

                final_path = f"{local_backup_dir}/{backup_filename}"
                mv_cmd = f"{ssh_cmd} \"mv {remote_backup_path} {final_path}\""
                mv_result = subprocess.run(mv_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if mv_result.returncode != 0:
                    raise Exception(f"Failed to move backup to final location: {mv_result.stderr}")

                # Cleanup temp directory
                cleanup_cmd = f"{ssh_cmd} \"rm -rf {remote_backup_dir}\""
                cleanup_result = subprocess.run(cleanup_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if cleanup_result.returncode != 0:
                    _logger.debug(f"Temp cleanup warning: {cleanup_result.stderr}")

                storage_path = final_path

            # Update backup record
            self.write({
                'state': BackupState.COMPLETED,
                'completed_at': fields.Datetime.now(),
                'storage_path': storage_path,
                's3_bucket': s3_bucket if use_s3 else False,
                's3_key': s3_key if use_s3 else False,
                'database_size': db_size_mb,
                'filestore_size': filestore_size_mb,
                'checksum': checksum,
                'is_encrypted': use_encryption,
            })

            # Calculate expiration based on plan
            retention_days = self._get_retention_days()
            expires_at = fields.Date.context_today(self) + timedelta(days=retention_days)
            self.write({'expires_at': expires_at})

            # Build completion message
            size_display = self.size_display
            msg_parts = [f"Backup completed. Type: {backup_type}, Size: {size_display}"]
            if use_encryption:
                msg_parts.append("Encrypted: Yes (AES-256)")
            if filestore_size_mb > 0:
                msg_parts.append(f"Filestore: {filestore_size_mb:.2f} MB")
            msg_parts.append(f"Checksum: {checksum[:8]}...")

            self.message_post(body=", ".join(msg_parts))
            _logger.info(f"Backup completed for instance {instance.subdomain}: {storage_path}")

            # Send backup completion email notification
            self._send_backup_notification('completed')

        except subprocess.TimeoutExpired:
            raise UserError(_("Backup timed out"))
        except Exception as e:
            _logger.error(f"Backup failed for {instance.subdomain}: {e}")
            raise

    def _upload_to_s3(self, server, ssh_password, local_path, endpoint, bucket, access_key, secret_key, s3_key):
        """Upload backup file to S3 from tenant server."""
        import boto3
        from botocore.config import Config

        # Create S3 client
        s3 = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4')
        )

        # Download file from tenant server to master, then upload to S3
        ssh_cmd = f"sshpass -p '{ssh_password}' scp -o StrictHostKeyChecking=no root@{server.ip_address}:{local_path} /tmp/"
        result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            raise Exception(f"SCP download failed: {result.stderr}")

        local_file = f"/tmp/{os.path.basename(local_path)}"

        try:
            # Upload to S3
            s3.upload_file(local_file, bucket, s3_key)
            _logger.info(f"Uploaded backup to s3://{bucket}/{s3_key}")
        finally:
            # Cleanup local temp file
            if os.path.exists(local_file):
                os.remove(local_file)

    def _get_retention_days(self):
        """Get retention days based on instance plan."""
        instance = self.instance_id
        if not instance or not instance.plan_id:
            return BackupConfig.RETENTION_TRIAL

        plan_code = instance.plan_id.code if hasattr(instance.plan_id, 'code') else ''

        retention_map = {
            'trial': BackupConfig.RETENTION_TRIAL,
            'starter': BackupConfig.RETENTION_BASIC,
            'professional': BackupConfig.RETENTION_PROFESSIONAL,
            'enterprise': BackupConfig.RETENTION_ENTERPRISE,
        }

        return retention_map.get(plan_code, BackupConfig.RETENTION_BASIC)

    def _handle_backup_failure(self, error_msg):
        """Handle backup failure."""
        self.write({
            'state': BackupState.FAILED,
            'completed_at': fields.Datetime.now(),
            'error_message': error_msg,
        })
        self.message_post(body=f"Backup failed: {error_msg}")
        _logger.error(f"Backup {self.reference} failed: {error_msg}")

        # Send backup failure email notification
        self._send_backup_notification('failed')

    def _send_backup_notification(self, notification_type='completed'):
        """
        Send email notification for backup events.

        Args:
            notification_type: 'completed' or 'failed'
        """
        self.ensure_one()

        try:
            # Get the appropriate template by name
            template_names = {
                'completed': 'SaaS: Backup Completed',
                'failed': 'SaaS: Backup Failed',
            }

            template_name = template_names.get(notification_type)
            if not template_name:
                _logger.warning(f"Unknown notification type: {notification_type}")
                return

            # Try XML ID first, then search by name
            xml_ids = {
                'completed': 'saas_backup.mail_template_backup_completed',
                'failed': 'saas_backup.mail_template_backup_failed',
            }
            template = self.env.ref(xml_ids.get(notification_type, ''), raise_if_not_found=False)

            if not template:
                # Search by name as fallback
                template = self.env['mail.template'].search([('name', '=', template_name)], limit=1)

            if not template:
                _logger.warning(f"Backup {notification_type} email template not found")
                return

            # Check if instance has a valid email recipient
            instance = self.instance_id
            if not instance:
                _logger.warning(f"No instance for backup {self.reference}")
                return

            recipient_email = instance.admin_email or (instance.partner_id and instance.partner_id.email)
            if not recipient_email:
                _logger.warning(f"No email recipient for backup {self.reference}")
                return

            # Send the email
            template.send_mail(self.id, force_send=True)
            _logger.info(f"Backup {notification_type} email sent for {self.reference} to {recipient_email}")

        except Exception as e:
            # Don't fail the backup if email fails
            _logger.error(f"Failed to send backup {notification_type} email for {self.reference}: {e}")

    def action_verify(self):
        """Verify backup integrity."""
        self.ensure_one()
        if self.state != BackupState.COMPLETED:
            raise UserError(_("Can only verify completed backups."))

        # In production, would verify checksums, test restore, etc.
        self.write({
            'is_verified': True,
            'verified_at': fields.Datetime.now(),
        })
        self.message_post(body="Backup verified successfully")
        return True

    def action_restore(self):
        """Open restore confirmation wizard."""
        self.ensure_one()
        if self.state != BackupState.COMPLETED:
            raise UserError(_("Can only restore from completed backups."))

        return {
            'name': 'Confirm Backup Restore',
            'type': 'ir.actions.act_window',
            'res_model': 'saas.backup.restore.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_backup_id': self.id,
                'default_instance_id': self.instance_id.id,
            },
        }

    def action_restore_confirmed(self):
        """
        Execute the restore process after confirmation.

        This is called by the wizard after user confirms.
        """
        self.ensure_one()
        if self.state != BackupState.COMPLETED:
            raise UserError(_("Can only restore from completed backups."))

        instance = self.instance_id
        if not instance:
            raise UserError(_("Instance not found for this backup."))

        _logger.info(f"Starting restore of backup {self.reference} to instance {instance.subdomain}")

        # For Docker containers, we need the container running to execute DB commands
        # The _restore_database method handles stopping/starting Odoo service inside container
        is_docker = bool(instance.container_name)
        was_running = instance.state == 'running'

        try:
            if is_docker:
                # Docker mode: container must stay running, only stop Odoo service inside
                self.message_post(body="Starting restore: Preparing Docker container...")
                # Ensure container is running
                if not was_running:
                    instance.action_start()
                    import time
                    time.sleep(5)
            else:
                # Non-Docker mode: stop the instance
                self.message_post(body="Starting restore: Stopping instance...")
                if was_running:
                    instance.action_stop()
                    import time
                    time.sleep(5)

            # Step 2: Download backup file
            self.message_post(body="Downloading backup file...")
            local_backup_path = self._download_backup_for_restore()

            if not local_backup_path:
                raise UserError(_("Failed to download backup file."))

            # Step 3: Restore database
            self.message_post(body="Restoring database...")
            self._restore_database(local_backup_path)

            # Step 4: Ensure instance is running
            if not is_docker and was_running:
                self.message_post(body="Starting instance...")
                instance.action_start()

            # Step 5: Update tracking
            self.write({
                'restore_count': self.restore_count + 1,
                'last_restored_at': fields.Datetime.now(),
            })

            self.message_post(body=f"✅ Backup restored successfully. Restore #{self.restore_count}")
            _logger.info(f"Backup {self.reference} restored to instance {instance.subdomain}")

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Restore Complete',
                    'message': f'Backup {self.reference} has been restored to {instance.subdomain}.',
                    'type': 'success',
                    'sticky': True,
                }
            }

        except Exception as e:
            error_msg = str(e)
            self.message_post(body=f"❌ Restore failed: {error_msg}")
            _logger.error(f"Restore failed for {self.reference}: {error_msg}")

            # Try to restart instance if it was stopped (non-Docker) or restart Odoo service (Docker)
            try:
                if is_docker:
                    # Try to restart Odoo inside container
                    ICP = self.env['ir.config_parameter'].sudo()
                    ssh_password = ICP.get_param('saas.tenant_ssh_password')
                    server = instance.server_id
                    ssh_cmd = f"sshpass -p '{ssh_password}' ssh -o StrictHostKeyChecking=no root@{server.ip_address}"
                    start_cmd = f"{ssh_cmd} \"docker exec {instance.container_name} supervisorctl start odoo 2>/dev/null || true\""
                    start_result = subprocess.run(start_cmd, shell=True, capture_output=True, text=True, timeout=30)
                    if start_result.returncode != 0:
                        _logger.warning(f"Failed to restart Odoo in container after restore failure: {start_result.stderr}")
                elif instance.state != 'running' and was_running:
                    instance.action_start()
            except Exception as recovery_error:
                _logger.error(f"Failed to recover instance after restore failure: {recovery_error}")

            raise UserError(f"Restore failed: {error_msg}")

    def _download_backup_for_restore(self):
        """
        Download backup file for restore operation.

        Returns:
            str: Local path to the downloaded backup file
        """
        import tempfile

        if self.storage_type == 's3':
            return self._download_from_s3()
        elif self.storage_type == 'local':
            return self._download_from_local_storage()
        else:
            raise UserError(f"Unsupported storage type: {self.storage_type}")

    def _download_from_s3(self):
        """Download backup from S3 to local temp file."""
        try:
            import boto3
            from botocore.config import Config
            import tempfile

            ICP = self.env['ir.config_parameter'].sudo()
            s3_endpoint = ICP.get_param('saas.s3_endpoint')
            s3_access_key = ICP.get_param('saas.s3_access_key')
            s3_secret_key = ICP.get_param('saas.s3_secret_key')

            s3 = boto3.client(
                's3',
                endpoint_url=s3_endpoint,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
                config=Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'}  # Required for Contabo S3
                )
            )

            # Download to temp file
            fd, temp_path = tempfile.mkstemp(suffix='.tar.gz')
            os.close(fd)

            _logger.info(f"Downloading s3://{self.s3_bucket}/{self.s3_key} to {temp_path}")
            s3.download_file(self.s3_bucket, self.s3_key, temp_path)

            return temp_path

        except Exception as e:
            _logger.error(f"S3 download failed: {e}")
            raise UserError(f"Failed to download backup from S3: {e}")

    def _download_from_local_storage(self):
        """Download backup from tenant server local storage."""
        try:
            import tempfile

            instance = self.instance_id
            server = instance.server_id
            if not server:
                raise UserError(_("Instance has no server assigned."))

            ICP = self.env['ir.config_parameter'].sudo()
            ssh_password = ICP.get_param('saas.tenant_ssh_password')

            # SCP file from tenant server
            fd, temp_path = tempfile.mkstemp(suffix='.tar.gz')
            os.close(fd)

            ssh_cmd = f"sshpass -p '{ssh_password}' scp -o StrictHostKeyChecking=no root@{server.ip_address}:{self.storage_path} {temp_path}"
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                raise Exception(f"SCP failed: {result.stderr}")

            return temp_path

        except subprocess.TimeoutExpired:
            raise UserError(_("Download timed out."))
        except Exception as e:
            _logger.error(f"Local download failed: {e}")
            raise UserError(f"Failed to download backup: {e}")

    def _restore_database(self, backup_path):
        """
        Restore database and optionally filestore from backup file.

        Handles:
        - Encrypted backups (AES-256 decryption)
        - Full backups (database + filestore)
        - Database-only backups
        - Filestore-only backups

        Args:
            backup_path: Path to the backup archive (may be encrypted)
        """
        instance = self.instance_id
        server = instance.server_id
        db_name = instance.database_name
        container_name = instance.container_name
        backup_type = self.backup_type or BackupType.DATABASE

        if not server:
            raise UserError(_("Instance has no server assigned."))

        ICP = self.env['ir.config_parameter'].sudo()
        ssh_password = ICP.get_param('saas.tenant_ssh_password')
        encryption_key = ICP.get_param('saas.backup_encryption_key')

        try:
            # Copy backup to tenant server
            remote_backup = f"/tmp/restore_{instance.subdomain}.tar.gz"
            if self.is_encrypted:
                remote_backup += ".enc"

            scp_cmd = f"sshpass -p '{ssh_password}' scp -o StrictHostKeyChecking=no {backup_path} root@{server.ip_address}:{remote_backup}"
            result = subprocess.run(scp_cmd, shell=True, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                raise Exception(f"SCP upload failed: {result.stderr}")

            ssh_cmd = f"sshpass -p '{ssh_password}' ssh -o StrictHostKeyChecking=no root@{server.ip_address}"

            # Decrypt if encrypted
            if self.is_encrypted:
                if not encryption_key:
                    raise UserError(_("Backup is encrypted but no encryption key is configured."))

                _logger.info("Decrypting backup...")
                decrypted_path = remote_backup.replace('.enc', '')
                decrypt_cmd = f"{ssh_cmd} \"openssl enc -aes-256-cbc -d -pbkdf2 -iter 100000 -in {remote_backup} -out {decrypted_path} -pass pass:{encryption_key}\""
                result = subprocess.run(decrypt_cmd, shell=True, capture_output=True, text=True, timeout=300)

                if result.returncode != 0:
                    raise Exception(f"Decryption failed: {result.stderr}")

                # Remove encrypted file, use decrypted
                rm_cmd = f"{ssh_cmd} \"rm -f {remote_backup}\""
                rm_result = subprocess.run(rm_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if rm_result.returncode != 0:
                    _logger.debug(f"Failed to remove encrypted backup file: {rm_result.stderr}")
                remote_backup = decrypted_path

            # Extract backup archive to temp directory
            restore_dir = f"/tmp/restore_{instance.subdomain}_extracted"
            extract_cmd = f"{ssh_cmd} \"mkdir -p {restore_dir} && tar -xzf {remote_backup} -C {restore_dir}\""
            result = subprocess.run(extract_cmd, shell=True, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                raise Exception(f"Extract failed: {result.stderr}")

            # Check if using Docker container or host PostgreSQL
            if container_name:
                _logger.info(f"Restoring to Docker container: {container_name}")
                db_host = "host.docker.internal"
                db_user = "odoo"
                db_password_pg = "odoo"

                # Stop Odoo service
                stop_odoo_cmd = f"{ssh_cmd} \"docker exec {container_name} supervisorctl stop odoo 2>/dev/null || true\""
                stop_result = subprocess.run(stop_odoo_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if stop_result.returncode != 0:
                    _logger.debug(f"Stop Odoo service warning: {stop_result.stderr}")

                # Restore database if present
                if backup_type in [BackupType.FULL, BackupType.DATABASE]:
                    db_dump = f"{restore_dir}/database.sql.gz"
                    check_db_cmd = f"{ssh_cmd} \"test -f {db_dump} && echo 'exists'\""
                    result = subprocess.run(check_db_cmd, shell=True, capture_output=True, text=True, timeout=30)

                    if 'exists' in result.stdout:
                        _logger.info("Restoring database...")

                        # Terminate connections
                        terminate_cmd = f"{ssh_cmd} \"docker exec {container_name} bash -c \\\"PGPASSWORD={db_password_pg} psql -h {db_host} -U {db_user} -d postgres -c \\\\\\\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();\\\\\\\"\\\" 2>/dev/null || true\""
                        subprocess.run(terminate_cmd, shell=True, capture_output=True, timeout=60)

                        import time
                        time.sleep(2)

                        # Drop and recreate database
                        drop_cmd = f"{ssh_cmd} \"docker exec {container_name} bash -c 'PGPASSWORD={db_password_pg} dropdb -h {db_host} -U {db_user} --force --if-exists {db_name}'\""
                        result = subprocess.run(drop_cmd, shell=True, capture_output=True, text=True, timeout=60)
                        if result.returncode != 0:
                            drop_cmd_old = f"{ssh_cmd} \"docker exec {container_name} bash -c 'PGPASSWORD={db_password_pg} dropdb -h {db_host} -U {db_user} --if-exists {db_name}'\""
                            result = subprocess.run(drop_cmd_old, shell=True, capture_output=True, text=True, timeout=60)
                            if result.returncode != 0:
                                raise Exception(f"Drop DB failed: {result.stderr}")

                        create_cmd = f"{ssh_cmd} \"docker exec {container_name} bash -c 'PGPASSWORD={db_password_pg} createdb -h {db_host} -U {db_user} {db_name}'\""
                        result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True, timeout=60)
                        if result.returncode != 0:
                            raise Exception(f"Create DB failed: {result.stderr}")

                        # Copy and restore database
                        copy_cmd = f"{ssh_cmd} \"docker cp {db_dump} {container_name}:/tmp/database.sql.gz\""
                        subprocess.run(copy_cmd, shell=True, capture_output=True, timeout=120)

                        restore_cmd = f"{ssh_cmd} \"docker exec {container_name} bash -c 'gunzip -c /tmp/database.sql.gz | PGPASSWORD={db_password_pg} psql -h {db_host} -U {db_user} -d {db_name}'\""
                        result = subprocess.run(restore_cmd, shell=True, capture_output=True, text=True, timeout=1800)
                        if result.returncode != 0:
                            _logger.warning(f"DB restore warnings: {result.stderr[:500] if result.stderr else 'None'}")

                        cleanup_cmd = f"{ssh_cmd} \"docker exec {container_name} rm -f /tmp/database.sql.gz\""
                        cleanup_result = subprocess.run(cleanup_cmd, shell=True, capture_output=True, text=True, timeout=30)
                        if cleanup_result.returncode != 0:
                            _logger.debug(f"DB cleanup warning: {cleanup_result.stderr}")
                        _logger.info("Database restored successfully")

                # Restore filestore if present (T-093 / T-101)
                if backup_type in [BackupType.FULL, BackupType.FILESTORE]:
                    fs_archive = f"{restore_dir}/filestore.tar.gz"
                    check_fs_cmd = f"{ssh_cmd} \"test -f {fs_archive} && echo 'exists'\""
                    result = subprocess.run(check_fs_cmd, shell=True, capture_output=True, text=True, timeout=30)

                    if 'exists' in result.stdout:
                        _logger.info("Restoring filestore...")

                        # Copy filestore archive to container
                        copy_cmd = f"{ssh_cmd} \"docker cp {fs_archive} {container_name}:/tmp/filestore.tar.gz\""
                        subprocess.run(copy_cmd, shell=True, capture_output=True, timeout=120)

                        # Clear existing filestore and extract new one
                        restore_fs_cmd = f"{ssh_cmd} \"docker exec {container_name} bash -c 'rm -rf /opt/odoo/data/filestore/* && tar -xzf /tmp/filestore.tar.gz -C /opt/odoo/data/filestore && chown -R odoo:odoo /opt/odoo/data/filestore'\""
                        result = subprocess.run(restore_fs_cmd, shell=True, capture_output=True, text=True, timeout=600)
                        if result.returncode != 0:
                            _logger.warning(f"Filestore restore warnings: {result.stderr[:500] if result.stderr else 'None'}")

                        cleanup_cmd = f"{ssh_cmd} \"docker exec {container_name} rm -f /tmp/filestore.tar.gz\""
                        cleanup_result = subprocess.run(cleanup_cmd, shell=True, capture_output=True, text=True, timeout=30)
                        if cleanup_result.returncode != 0:
                            _logger.debug(f"Filestore cleanup warning: {cleanup_result.stderr}")
                        _logger.info("Filestore restored successfully")

                # Start Odoo service
                start_odoo_cmd = f"{ssh_cmd} \"docker exec {container_name} supervisorctl start odoo 2>/dev/null || true\""
                start_result = subprocess.run(start_odoo_cmd, shell=True, capture_output=True, text=True, timeout=30)
                if start_result.returncode != 0:
                    _logger.warning(f"Failed to start Odoo service after restore: {start_result.stderr}")

            else:
                # Host-based PostgreSQL (legacy - no filestore support)
                _logger.info("Restoring database on host PostgreSQL")

                db_dump = f"{restore_dir}/database.sql.gz"

                # Terminate connections
                terminate_cmd = f"{ssh_cmd} \"PGPASSWORD=odoo psql -h localhost -U odoo -d postgres -c \\\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();\\\"\""
                term_result = subprocess.run(terminate_cmd, shell=True, capture_output=True, text=True, timeout=60)
                if term_result.returncode != 0:
                    _logger.debug(f"Terminate connections warning: {term_result.stderr}")

                # Drop and create database
                drop_cmd = f"{ssh_cmd} \"PGPASSWORD=odoo dropdb -h localhost -U odoo --if-exists {db_name}\""
                drop_result = subprocess.run(drop_cmd, shell=True, capture_output=True, text=True, timeout=60)
                if drop_result.returncode != 0:
                    _logger.warning(f"Drop database warning: {drop_result.stderr}")

                create_cmd = f"{ssh_cmd} \"PGPASSWORD=odoo createdb -h localhost -U odoo {db_name}\""
                result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    raise Exception(f"Create DB failed: {result.stderr}")

                # Restore database
                restore_cmd = f"{ssh_cmd} \"gunzip -c {db_dump} | PGPASSWORD=odoo psql -h localhost -U odoo -d {db_name}\""
                result = subprocess.run(restore_cmd, shell=True, capture_output=True, text=True, timeout=1800)
                if result.returncode != 0:
                    _logger.warning(f"Restore warnings: {result.stderr[:500] if result.stderr else 'None'}")

            # Cleanup remote temp files
            cleanup_cmd = f"{ssh_cmd} \"rm -rf {remote_backup} {restore_dir}\""
            cleanup_result = subprocess.run(cleanup_cmd, shell=True, capture_output=True, text=True, timeout=30)
            if cleanup_result.returncode != 0:
                _logger.debug(f"Remote restore cleanup warning: {cleanup_result.stderr}")

            # Cleanup local temp file
            if os.path.exists(backup_path):
                os.remove(backup_path)

            _logger.info(f"Backup restored successfully to {instance.subdomain}")

        except subprocess.TimeoutExpired:
            raise UserError(_("Database restore timed out."))
        except Exception as e:
            _logger.error(f"Database restore failed: {e}")
            raise

    def action_download(self):
        """Generate download link for backup."""
        self.ensure_one()
        if self.state != BackupState.COMPLETED:
            raise UserError(_("Can only download completed backups."))

        if self.storage_type == 's3' and self.s3_bucket and self.s3_key:
            # Generate S3 presigned URL
            download_url = self._generate_s3_presigned_url()
            if download_url:
                return {
                    'type': 'ir.actions.act_url',
                    'url': download_url,
                    'target': 'new',
                }
            else:
                raise UserError(_("Failed to generate download URL."))
        elif self.storage_type == 'local' and self.storage_path:
            # For local storage, we need to download from tenant server
            raise UserError(
                "Local backup download not supported from web interface. "
                f"File location: {self.storage_path}"
            )
        else:
            raise UserError(_("Backup file location not found."))

    def _generate_s3_presigned_url(self, expiration=3600):
        """
        Generate a presigned URL for S3 backup download.

        Args:
            expiration: URL expiration in seconds (default 1 hour)

        Returns:
            str: Presigned URL or None on failure
        """
        try:
            import boto3
            from botocore.config import Config

            ICP = self.env['ir.config_parameter'].sudo()
            s3_endpoint = ICP.get_param('saas.s3_endpoint')
            s3_access_key = ICP.get_param('saas.s3_access_key')
            s3_secret_key = ICP.get_param('saas.s3_secret_key')

            if not all([s3_endpoint, s3_access_key, s3_secret_key]):
                _logger.error("S3 credentials not configured")
                return None

            s3 = boto3.client(
                's3',
                endpoint_url=s3_endpoint,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
                config=Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'}  # Required for Contabo S3
                )
            )

            # Generate presigned URL
            url = s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.s3_bucket,
                    'Key': self.s3_key,
                },
                ExpiresIn=expiration
            )

            _logger.info(f"Generated presigned URL for backup {self.reference}")
            return url

        except Exception as e:
            _logger.error(f"Failed to generate presigned URL: {e}")
            return None

    def action_delete_backup(self):
        """Delete the backup files."""
        self.ensure_one()
        if self.state == BackupState.DELETED:
            raise UserError(_("Backup already deleted."))

        # In production, would delete files from storage
        self.write({'state': BackupState.DELETED})
        self.message_post(body="Backup files deleted")
        return True

    @api.model
    def cron_cleanup_expired(self):
        """Cron job to cleanup expired backups."""
        today = fields.Date.context_today(self)

        expired = self.search([
            ('state', '=', BackupState.COMPLETED),
            ('expires_at', '<', today),
        ])

        for backup in expired:
            try:
                backup.write({'state': BackupState.EXPIRED})
                # In production, would delete actual files
                _logger.info(f"Backup {backup.reference} marked as expired")
            except Exception as e:
                _logger.error(f"Error expiring backup {backup.reference}: {e}")

        return True

    @api.model
    def cron_run_scheduled_backups(self):
        """Cron job to run scheduled backups."""
        Schedule = self.env['saas.backup.schedule']
        schedules = Schedule.search([
            ('is_active', '=', True),
            ('next_run', '<=', fields.Datetime.now()),
        ])

        for schedule in schedules:
            try:
                schedule.action_run_backup()
            except Exception as e:
                _logger.error(f"Error running scheduled backup {schedule.name}: {e}")

        return True
