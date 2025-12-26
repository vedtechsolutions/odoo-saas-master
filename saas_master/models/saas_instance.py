# -*- coding: utf-8 -*-
"""
SaaS Customer Instance model.

Manages customer Odoo instances running as Docker containers.
"""

import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from odoo.addons.saas_core.constants.fields import ModelNames, FieldNames, FieldLabels
from odoo.addons.saas_core.constants.states import InstanceState
from odoo.addons.saas_core.constants.config import DomainConfig, ServerConfig, OdooVersions
from odoo.addons.saas_core.constants.messages import ValidationErrors, SuccessMessages
from odoo.addons.saas_core.utils.validators import (
    validate_subdomain,
    normalize_email,
    generate_database_name,
    generate_container_name,
)
from odoo.addons.saas_core.utils.db_utils import validate_savepoint_name

_logger = logging.getLogger(__name__)


class SaasInstance(models.Model):
    """Customer Odoo instance running as a Docker container."""

    _name = ModelNames.INSTANCE
    _description = 'SaaS Customer Instance'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'saas.audit.mixin', 'saas.encryption.mixin']

    # PII fields to encrypt (T-084)
    _encrypted_fields = ['admin_email', 'admin_password']

    # Odoo 19 constraint syntax
    _subdomain_unique = models.Constraint(
        'UNIQUE(subdomain)',
        'Subdomain must be unique!'
    )
    _container_name_unique = models.Constraint(
        'UNIQUE(container_name)',
        'Container name must be unique!'
    )
    _database_name_unique = models.Constraint(
        'UNIQUE(database_name)',
        'Database name must be unique!'
    )
    _server_port_unique = models.Constraint(
        'UNIQUE(server_id, port_http)',
        'Port must be unique per server!'
    )

    # Odoo 19 index syntax for composite indexes
    _server_state_idx = models.Index('(server_id, state)')
    _trial_expiry_idx = models.Index('(is_trial, trial_end_date) WHERE is_trial = true')

    # Basic identification
    name = fields.Char(
        string=FieldLabels.NAME,
        required=True,
        tracking=True,
        help='Display name for the instance',
    )
    subdomain = fields.Char(
        string=FieldLabels.SUBDOMAIN,
        required=True,
        index=True,
        tracking=True,
        help='Unique subdomain (e.g., "acme" for acme.tenants.vedtechsolutions.com)',
    )
    full_domain = fields.Char(
        string=FieldLabels.FULL_DOMAIN,
        compute='_compute_full_domain',
        store=True,
        help='Complete domain name for accessing the instance',
    )

    # State management
    state = fields.Selection(
        selection=InstanceState.get_selection(),
        string=FieldLabels.STATE,
        default=InstanceState.DRAFT,
        required=True,
        tracking=True,
        index=True,
    )

    # Relations
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        ondelete='restrict',
        index=True,
    )
    plan_id = fields.Many2one(
        ModelNames.PLAN,
        string=FieldLabels.PLAN,
        required=True,
        tracking=True,
        ondelete='restrict',
    )
    server_id = fields.Many2one(
        ModelNames.SERVER,
        string=FieldLabels.SERVER,
        tracking=True,
        ondelete='restrict',
        index=True,
    )

    # Docker configuration
    container_id = fields.Char(
        string='Container ID',
        readonly=True,
        copy=False,
        help='Docker container ID',
    )
    container_name = fields.Char(
        string='Container Name',
        compute='_compute_container_name',
        store=True,
    )
    database_name = fields.Char(
        string='Database Name',
        compute='_compute_database_name',
        store=True,
    )

    # Ports
    port_http = fields.Integer(
        string='HTTP Port',
        readonly=True,
        copy=False,
    )
    port_longpolling = fields.Integer(
        string='Longpolling Port',
        compute='_compute_port_longpolling',
        store=True,
    )

    # Odoo configuration
    odoo_version = fields.Selection(
        selection=OdooVersions.get_selection(),
        string='Odoo Version',
        default=OdooVersions.DEFAULT,
        required=True,
    )
    admin_email = fields.Char(
        string='Admin Email',
        required=True,
        tracking=True,
    )
    admin_login = fields.Char(
        string='Admin Username',
        default='admin',
        help='The username for logging into the tenant instance',
    )
    admin_password = fields.Char(
        string='Admin Password',
        copy=False,
        groups='base.group_system',
    )

    # Computed fields for templates (decrypted values)
    # These are used in email templates where direct field access returns encrypted values
    admin_email_plain = fields.Char(
        string='Admin Email (Decrypted)',
        compute='_compute_decrypted_fields',
        help='Decrypted admin email for use in email templates',
    )
    admin_password_plain = fields.Char(
        string='Admin Password (Decrypted)',
        compute='_compute_decrypted_fields',
        groups='base.group_system',
        help='Decrypted admin password for use in email templates',
    )

    # Trial management
    is_trial = fields.Boolean(
        string='Trial Instance',
        default=False,
    )
    trial_end_date = fields.Datetime(
        string='Trial End Date',
    )

    # Resource usage (from monitoring)
    cpu_usage_percent = fields.Float(
        string='CPU Usage (%)',
        readonly=True,
    )
    ram_usage_mb = fields.Float(
        string='RAM Usage (MB)',
        readonly=True,
    )
    storage_db_gb = fields.Float(
        string='Database Size (GB)',
        readonly=True,
    )
    storage_file_gb = fields.Float(
        string='File Storage (GB)',
        readonly=True,
    )

    # Timestamps
    provisioned_date = fields.Datetime(
        string='Provisioned Date',
        readonly=True,
        copy=False,
    )
    last_accessed_date = fields.Datetime(
        string='Last Accessed',
        readonly=True,
    )

    # Status message
    status_message = fields.Text(
        string='Status Message',
        readonly=True,
        help='Last operation status or error message',
    )

    # Computed helper fields
    instance_url = fields.Char(
        string='Instance URL',
        compute='_compute_instance_url',
    )

    @api.depends(FieldNames.SUBDOMAIN)
    def _compute_full_domain(self):
        """Compute full domain from subdomain."""
        for instance in self:
            if instance.subdomain:
                instance.full_domain = f"{instance.subdomain}.{DomainConfig.TENANT_SUBDOMAIN_SUFFIX}"
            else:
                instance.full_domain = False

    @api.depends(FieldNames.SUBDOMAIN)
    def _compute_container_name(self):
        """Compute Docker container name."""
        for instance in self:
            if instance.subdomain:
                instance.container_name = generate_container_name(instance.subdomain)
            else:
                instance.container_name = False

    @api.depends(FieldNames.SUBDOMAIN)
    def _compute_database_name(self):
        """Compute PostgreSQL database name."""
        for instance in self:
            if instance.subdomain:
                instance.database_name = generate_database_name(instance.subdomain)
            else:
                instance.database_name = False

    @api.depends('port_http')
    def _compute_port_longpolling(self):
        """Compute longpolling port (HTTP port + 1000)."""
        for instance in self:
            if instance.port_http:
                instance.port_longpolling = instance.port_http + ServerConfig.LONGPOLLING_PORT_OFFSET
            else:
                instance.port_longpolling = False

    @api.depends('full_domain')
    def _compute_instance_url(self):
        """Compute instance access URL."""
        for instance in self:
            if instance.full_domain:
                instance.instance_url = f"https://{instance.full_domain}"
            else:
                instance.instance_url = False

    def _compute_decrypted_fields(self):
        """Compute decrypted values for encrypted fields.

        These are used in email templates where direct field access
        would return encrypted values (ENC::...).
        """
        for instance in self:
            instance.admin_email_plain = instance._get_decrypted_value('admin_email')
            instance.admin_password_plain = instance._get_decrypted_value('admin_password')

    @api.constrains(FieldNames.SUBDOMAIN)
    def _check_subdomain(self):
        """Validate subdomain format and availability."""
        for instance in self:
            if instance.subdomain:
                validate_subdomain(instance.subdomain)

    @api.constrains('admin_email')
    def _check_admin_email(self):
        """Validate admin email format.

        Note: admin_email is encrypted by the encryption mixin, so we need to
        get the decrypted value for validation.
        """
        from odoo.addons.saas_core.utils.encryption import is_encrypted

        for instance in self:
            if instance.admin_email:
                # Get decrypted value since admin_email is in _encrypted_fields
                email = instance.admin_email
                if is_encrypted(email):
                    email = instance._get_decrypted_value('admin_email')
                if email:
                    normalize_email(email)

    @api.onchange(FieldNames.SUBDOMAIN)
    def _onchange_subdomain(self):
        """Normalize subdomain on change."""
        if self.subdomain:
            self.subdomain = self.subdomain.lower().strip()

    @api.onchange('partner_id')
    def _onchange_partner(self):
        """Set admin email from partner."""
        if self.partner_id and self.partner_id.email:
            self.admin_email = self.partner_id.email

    @api.onchange('plan_id')
    def _onchange_plan(self):
        """Set trial flag based on plan."""
        if self.plan_id:
            self.is_trial = self.plan_id.is_trial

    # -------------------------------------------------------------------------
    # CRUD Overrides - Ensure server counts are updated
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to update server instance counts."""
        records = super().create(vals_list)
        # Update server counts for all affected servers
        servers = records.mapped('server_id')
        if servers:
            servers.refresh_instance_counts()
        return records

    def write(self, vals):
        """Override write to update server instance counts when state or server changes."""
        # Track servers that need updating (before and after change)
        servers_to_update = self.env[ModelNames.SERVER]

        if 'state' in vals or 'server_id' in vals:
            # Collect current servers before the change
            servers_to_update |= self.mapped('server_id')

        result = super().write(vals)

        if 'state' in vals or 'server_id' in vals:
            # Collect servers after the change
            servers_to_update |= self.mapped('server_id')
            # Update all affected servers
            if servers_to_update:
                servers_to_update.refresh_instance_counts()

        return result

    def unlink(self):
        """
        Override unlink to prevent deletion of instances with active subscriptions
        and update server instance counts. (FIX Gap #14)
        """
        # Check for active subscriptions before allowing deletion
        Subscription = self.env.get('saas.subscription')
        if Subscription is not None:
            for instance in self:
                active_subs = Subscription.search([
                    ('instance_id', '=', instance.id),
                    ('state', 'in', ['active', 'trial', 'past_due', 'suspended']),
                ])
                if active_subs:
                    raise UserError(_(
                        "Cannot delete instance '%s' - it has %d active subscription(s): %s. "
                        "Cancel or expire the subscription(s) first."
                    ) % (
                        instance.name,
                        len(active_subs),
                        ', '.join(active_subs.mapped('reference'))
                    ))

        servers = self.mapped('server_id')
        result = super().unlink()
        if servers:
            servers.refresh_instance_counts()
        return result

    # State transition methods
    def action_provision(self):
        """
        Provision a new instance.

        This creates the Docker container, database, and configures DNS.
        """
        self.ensure_one()

        if self.state != InstanceState.DRAFT:
            raise UserError(ValidationErrors.INSTANCE_ALREADY_RUNNING)

        # Get available server
        if not self.server_id:
            server = self.env[ModelNames.SERVER].get_available_server()
            if not server:
                raise UserError(ValidationErrors.SERVER_UNAVAILABLE)
            self.server_id = server

        # Allocate port
        if not self.port_http:
            self.port_http = self.server_id.get_available_port()

        self.write({
            'state': InstanceState.PENDING,
            'status_message': 'Instance queued for provisioning...',
        })

        # Queue for async provisioning
        self._queue_provisioning()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Provisioning Started',
                'message': SuccessMessages.INSTANCE_PROVISIONING,
                'type': 'success',
                'sticky': False,
            }
        }

    def _queue_provisioning(self):
        """Queue instance for asynchronous provisioning via the queue system."""
        self.ensure_one()
        Queue = self.env[ModelNames.QUEUE]

        # Create queue task with high priority for provisioning
        task = Queue.create_task(
            instance=self,
            action='provision',
            priority='2',  # High priority for new instances
        )

        _logger.info(
            f"Instance {self.subdomain} queued for provisioning: {task.name}"
        )

        # For immediate feedback, also try to process via post-commit
        # This allows the queue to process right after the transaction commits
        self.env.cr.postcommit.add(
            lambda: self._trigger_immediate_queue_processing()
        )

    def _trigger_immediate_queue_processing(self):
        """Trigger immediate queue processing after transaction commits."""
        try:
            from odoo import api, SUPERUSER_ID
            with self.env.registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, SUPERUSER_ID, {})
                Queue = new_env[ModelNames.QUEUE]
                Queue.cron_process_queue()
                new_cr.commit()
        except Exception as e:
            _logger.warning(f"Immediate queue processing failed: {e}")
            # Not critical - cron will pick it up

    def _queue_action(self, action, priority='1', payload=None):
        """Queue any instance action via the queue system."""
        self.ensure_one()
        Queue = self.env[ModelNames.QUEUE]

        task = Queue.create_task(
            instance=self,
            action=action,
            priority=priority,
            payload=payload,
        )

        _logger.info(f"Instance {self.subdomain} action '{action}' queued: {task.name}")
        return task

    def _get_docker_client(self):
        """Get Docker client for the tenant server."""
        import docker
        if not self.server_id or not self.server_id.docker_api_url:
            raise UserError(_("No Docker API URL configured for server"))
        return docker.DockerClient(base_url=self.server_id.docker_api_url, timeout=60)

    def _do_provision(self):
        """Execute the actual provisioning steps."""
        self.ensure_one()
        try:
            self.write({
                'state': InstanceState.PROVISIONING,
                'status_message': 'Creating container...',
            })
            self.env.cr.commit()

            _logger.info(f"Provisioning instance {self.subdomain}")

            # Get Docker client
            client = self._get_docker_client()

            # Generate admin password if not set
            if not self.admin_password:
                import secrets
                self.admin_password = secrets.token_urlsafe(16)
                # Commit immediately to ensure password is persisted before use
                self.env.cr.commit()
                _logger.info(f"Generated admin password for {self.subdomain}")

            # Container environment variables
            # Use Docker bridge gateway for DB connection from container
            env_vars = {
                'HOST': '0.0.0.0',
                'PORT': '8069',
                'DB_HOST': 'host.docker.internal',
                'DB_PORT': '5432',
                'DB_USER': 'odoo',
                'DB_PASSWORD': 'odoo',
                'DB_NAME': self.database_name,
                'DB_MAXCONN': '8',  # Limit DB connections to prevent PostgreSQL overload
                'ADMIN_PASSWD': self.admin_password or 'admin',
                'INIT_DATABASE': 'true',  # Initialize database with base module
            }

            # Resource limits from plan
            plan = self.plan_id
            mem_limit = f"{plan.ram_limit_mb}m"
            cpu_quota = int(plan.cpu_limit * 100000)  # Docker CPU quota

            # Port bindings
            ports = {
                '8069/tcp': self.port_http,
                '8072/tcp': self.port_longpolling,
            }

            # Check if container already exists
            try:
                existing = client.containers.get(self.container_name)
                _logger.warning(f"Container {self.container_name} already exists, removing...")
                existing.remove(force=True)
            except Exception as e:
                # Container doesn't exist (expected) or removal failed
                if 'NotFound' not in str(type(e).__name__) and '404' not in str(e):
                    _logger.debug(f"Container check for {self.container_name}: {e}")

            # Create and start container
            self.write({'status_message': 'Starting container...'})
            self.env.cr.commit()

            container = client.containers.run(
                image=ServerConfig.DOCKER_IMAGE,
                name=self.container_name,
                detach=True,
                ports=ports,
                environment=env_vars,
                mem_limit=mem_limit,
                cpu_quota=cpu_quota,
                restart_policy={'Name': 'unless-stopped'},
                extra_hosts={'host.docker.internal': 'host-gateway'},
                labels={
                    'saas.instance': self.subdomain,
                    'saas.plan': plan.code,
                    'saas.customer': self.partner_id.name,
                },
            )

            # Store container ID
            self.write({
                'container_id': container.id[:12],
                'status_message': 'Container started, initializing database...',
            })
            self.env.cr.commit()

            _logger.info(f"Container {self.container_name} created with ID {container.id[:12]}")

            # Wait for container to be ready
            import time
            time.sleep(5)

            # Configure db_maxconn to prevent PostgreSQL connection overload
            try:
                container.exec_run([
                    'bash', '-c',
                    "sed -i 's/db_maxconn = .*/db_maxconn = 8/' /etc/odoo/odoo.conf || "
                    "echo 'db_maxconn = 8' >> /etc/odoo/odoo.conf"
                ])
                _logger.info(f"Set db_maxconn=8 for {self.container_name}")
            except Exception as e:
                _logger.warning(f"Could not set db_maxconn: {e}")

            # Add nginx proxy mapping
            self.write({'status_message': 'Configuring proxy...'})
            self.env.cr.commit()
            self._add_nginx_mapping()

            # Request SSL certificate
            self.write({'status_message': 'Requesting SSL certificate...'})
            self.env.cr.commit()
            self._request_ssl_certificate()

            # Wait for database to be fully initialized
            self.write({'status_message': 'Setting up admin credentials...'})
            self.env.cr.commit()
            import time
            time.sleep(10)  # Give Odoo time to fully initialize the database

            # Set admin password and email in tenant database
            # Must use _get_decrypted_value since self.admin_password may return encrypted value
            decrypted_password = self._get_decrypted_value('admin_password')
            _logger.info(f"Password to sync for {self.subdomain}: {decrypted_password[:20]}... (len={len(decrypted_password) if decrypted_password else 0})")
            if decrypted_password and decrypted_password.startswith('ENC::'):
                _logger.error(f"PASSWORD IS STILL ENCRYPTED! This is a bug.")
            self._set_tenant_admin_password(decrypted_password)

            # Fetch and store the admin username from tenant
            self._fetch_tenant_admin_login()

            # Install support module for one-click support access
            self.write({'status_message': 'Installing support module...'})
            self.env.cr.commit()
            support_installed = self._install_support_module()
            if not support_installed:
                _logger.warning(f"Support module not installed on {self.subdomain} - support access may not work")

            # Mark as running
            self.write({
                'state': InstanceState.RUNNING,
                'status_message': 'Instance is running',
                'provisioned_date': fields.Datetime.now(),
            })

            # Refresh server instance counts
            if self.server_id:
                self.server_id.refresh_instance_counts()

            _logger.info(f"Instance {self.subdomain} provisioned successfully")

        except Exception as e:
            _logger.error(f"Provisioning failed for {self.subdomain}: {e}")
            self.write({
                'state': InstanceState.ERROR,
                'status_message': str(e),
            })
            self.env.cr.commit()  # Ensure error state is persisted
            # Re-raise so queue task is marked as failed
            raise

    def action_start(self):
        """Start a stopped instance."""
        self.ensure_one()
        if self.state not in [InstanceState.STOPPED, InstanceState.ERROR]:
            raise UserError(ValidationErrors.INSTANCE_ALREADY_RUNNING)

        try:
            _logger.info(f"Starting instance {self.subdomain}")
            client = self._get_docker_client()
            container = client.containers.get(self.container_name)
            container.start()

            self.write({
                'state': InstanceState.RUNNING,
                'status_message': 'Instance is running',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Instance Started',
                    'message': SuccessMessages.INSTANCE_STARTED,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.write({
                'state': InstanceState.ERROR,
                'status_message': str(e),
            })
            raise UserError(_("Failed to start instance: %s") % e)

    def action_stop(self):
        """Stop a running instance."""
        self.ensure_one()
        if self.state != InstanceState.RUNNING:
            raise UserError(ValidationErrors.INSTANCE_NOT_RUNNING)

        try:
            _logger.info(f"Stopping instance {self.subdomain}")
            client = self._get_docker_client()
            container = client.containers.get(self.container_name)
            container.stop(timeout=30)

            self.write({
                'state': InstanceState.STOPPED,
                'status_message': 'Instance is stopped',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Instance Stopped',
                    'message': SuccessMessages.INSTANCE_STOPPED,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.write({
                'state': InstanceState.ERROR,
                'status_message': str(e),
            })
            raise UserError(_("Failed to stop instance: %s") % e)

    def action_restart(self):
        """Restart a running instance."""
        self.ensure_one()
        if self.state != InstanceState.RUNNING:
            raise UserError(ValidationErrors.INSTANCE_NOT_RUNNING)

        try:
            _logger.info(f"Restarting instance {self.subdomain}")
            client = self._get_docker_client()
            container = client.containers.get(self.container_name)
            container.restart(timeout=30)

            self.write({
                'status_message': 'Instance restarted',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Instance Restarted',
                    'message': SuccessMessages.INSTANCE_RESTARTED,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.write({
                'state': InstanceState.ERROR,
                'status_message': str(e),
            })
            raise UserError(_("Failed to restart instance: %s") % e)

    def action_suspend(self):
        """Suspend instance (for payment issues or trial expiry)."""
        self.ensure_one()
        if self.state not in InstanceState.get_operational_states():
            raise UserError(ValidationErrors.INSTANCE_NOT_RUNNING)

        try:
            _logger.info(f"Suspending instance {self.subdomain}")

            # Stop the container but keep data
            if self.container_name and self.server_id:
                try:
                    client = self._get_docker_client()
                    container = client.containers.get(self.container_name)
                    container.stop(timeout=30)
                    _logger.info(f"Container {self.container_name} stopped")
                except Exception as docker_err:
                    _logger.warning(f"Could not stop container: {docker_err}")

            self.write({
                'state': InstanceState.SUSPENDED,
                'status_message': 'Instance suspended - trial expired or payment issue',
            })

        except Exception as e:
            _logger.error(f"Failed to suspend {self.subdomain}: {e}")
            raise UserError(_("Failed to suspend instance: %s") % e)

    def action_reactivate(self):
        """Reactivate a suspended instance."""
        self.ensure_one()
        if self.state != InstanceState.SUSPENDED:
            raise UserError(_("Instance is not suspended"))

        try:
            _logger.info(f"Reactivating instance {self.subdomain}")
            client = self._get_docker_client()
            container = client.containers.get(self.container_name)
            container.start()

            self.write({
                'state': InstanceState.RUNNING,
                'status_message': 'Instance reactivated',
            })

        except Exception as e:
            self.write({
                'state': InstanceState.ERROR,
                'status_message': str(e),
            })
            raise UserError(_("Failed to reactivate instance: %s") % e)

    def action_terminate(self):
        """Terminate and delete instance permanently."""
        self.ensure_one()

        try:
            _logger.info(f"Terminating instance {self.subdomain}")

            # Remove nginx mapping first
            self._remove_nginx_mapping()

            # Remove Docker container
            if self.container_id and self.server_id:
                try:
                    client = self._get_docker_client()
                    container = client.containers.get(self.container_name)
                    container.remove(force=True, v=True)  # v=True removes volumes
                    _logger.info(f"Container {self.container_name} removed")
                except Exception as e:
                    _logger.warning(f"Could not remove container: {e}")

            # Store server before clearing
            server = self.server_id

            self.write({
                'state': InstanceState.TERMINATED,
                'status_message': 'Instance terminated',
                'container_id': False,
            })

            # Refresh server instance counts
            if server:
                server.refresh_instance_counts()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Instance Terminated',
                    'message': SuccessMessages.INSTANCE_DELETED,
                    'type': 'warning',
                    'sticky': False,
                }
            }

        except Exception as e:
            _logger.error(f"Failed to terminate {self.subdomain}: {e}")
            raise UserError(_("Failed to terminate instance: %s") % e)

    def action_open_instance(self):
        """Open instance in new browser tab."""
        self.ensure_one()
        if not self.instance_url:
            raise UserError(_("Instance URL not available"))

        return {
            'type': 'ir.actions.act_url',
            'url': self.instance_url,
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # Credential Management
    # -------------------------------------------------------------------------

    def _set_tenant_admin_password(self, new_password, old_password=None):
        """Update the admin user password in the tenant database.

        Uses Docker over VPN to connect to the tenant container and update
        the admin user's password directly in the database using psql.

        Args:
            new_password: The new password to set
            old_password: The current password (if known). Not used in this approach.
        """
        _logger.info(f"_set_tenant_admin_password called with password: {new_password[:20] if new_password else 'None'}...")
        if new_password and new_password.startswith('ENC::'):
            _logger.error(f"ENCRYPTED PASSWORD PASSED TO _set_tenant_admin_password! Decrypting...")
            new_password = self._get_decrypted_value('admin_password')
            _logger.info(f"After decryption: {new_password[:20] if new_password else 'None'}...")

        if not self.database_name or not new_password or not self.container_name:
            _logger.warning(
                f"Missing required data for password update: "
                f"db={self.database_name}, container={self.container_name}"
            )
            return False

        # Get VPN IP from server or use default
        vpn_ip = None
        docker_port = 2375
        if self.server_id:
            vpn_ip = self.server_id.vpn_ip or ServerConfig.TENANT_VPN_IP
            docker_port = self.server_id.docker_api_port or 2375
        else:
            vpn_ip = ServerConfig.TENANT_VPN_IP

        if not vpn_ip:
            _logger.warning(f"No VPN IP configured for tenant {self.subdomain}")
            return False

        try:
            import docker

            # Connect to Docker on tenant server via VPN
            docker_url = f"tcp://{vpn_ip}:{docker_port}"
            client = docker.DockerClient(base_url=docker_url, timeout=30)

            # Get the container
            try:
                container = client.containers.get(self.container_name)
            except docker.errors.NotFound:
                _logger.error(f"Container {self.container_name} not found")
                return False

            if container.status != 'running':
                _logger.warning(f"Container {self.container_name} is not running")
                return False

            # Use Python script to update password with proper hashing
            # Odoo 19 requires 600000 rounds for pbkdf2_sha512
            # Use base64 to safely pass password with special characters
            import base64
            encoded_password = base64.b64encode(new_password.encode()).decode()

            python_script = f'''
import psycopg2
import base64
from passlib.context import CryptContext
ctx = CryptContext(['pbkdf2_sha512'], pbkdf2_sha512__rounds=600000)
password = base64.b64decode("{encoded_password}").decode()
new_hash = ctx.hash(password)
conn = psycopg2.connect(host='host.docker.internal', dbname='{self.database_name}', user='odoo', password='odoo')
cur = conn.cursor()
cur.execute("UPDATE res_users SET password = %s WHERE login = 'admin'", (new_hash,))
conn.commit()
print("PASSWORD_UPDATED" if cur.rowcount > 0 else "PASSWORD_FAILED")
conn.close()
'''
            cmd = [
                '/opt/odoo/venv/bin/python3', '-c', python_script
            ]
            exit_code, output = container.exec_run(cmd, demux=False)

            output_str = output.decode() if output else ''
            if exit_code == 0 and 'PASSWORD_UPDATED' in output_str:
                _logger.info(f"Admin password updated for tenant {self.subdomain}")
                return True
            else:
                _logger.warning(
                    f"Password update failed for {self.subdomain}: "
                    f"exit={exit_code}, output={output_str[:200]}"
                )
                return False

        except Exception as e:
            _logger.error(f"Failed to update admin password in tenant: {e}")
            return False

    def _fetch_tenant_admin_login(self):
        """Fetch the admin username from the tenant database.

        Uses Docker over VPN to query the tenant's res_users table.
        """
        if not self.database_name or not self.container_name:
            return False

        # Get VPN IP from server or use default
        vpn_ip = None
        docker_port = 2375
        if self.server_id:
            vpn_ip = self.server_id.vpn_ip or ServerConfig.TENANT_VPN_IP
            docker_port = self.server_id.docker_api_port or 2375
        else:
            vpn_ip = ServerConfig.TENANT_VPN_IP

        if not vpn_ip:
            return False

        try:
            import docker

            docker_url = f"tcp://{vpn_ip}:{docker_port}"
            client = docker.DockerClient(base_url=docker_url, timeout=30)

            try:
                container = client.containers.get(self.container_name)
            except docker.errors.NotFound:
                return False

            if container.status != 'running':
                return False

            # Query the admin user's login from the tenant database
            cmd = [
                'bash', '-c',
                f"PGPASSWORD=odoo psql -h host.docker.internal -U odoo -d {self.database_name} "
                f"-t -c \"SELECT login FROM res_users WHERE id=2;\""
            ]
            exit_code, output = container.exec_run(cmd, demux=False)

            if exit_code == 0 and output:
                admin_login = output.decode().strip()
                if admin_login:
                    self.write({'admin_login': admin_login})
                    _logger.info(f"Fetched admin login '{admin_login}' for tenant {self.subdomain}")
                    return True

            return False

        except Exception as e:
            _logger.error(f"Failed to fetch admin login from tenant: {e}")
            return False

    def action_refresh_admin_login(self):
        """Refresh the admin username from the tenant database."""
        self.ensure_one()

        if self.state != InstanceState.RUNNING:
            raise UserError(_("Cannot refresh login - instance is not running."))

        if self._fetch_tenant_admin_login():
            # Reload the form to show updated value
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            raise UserError(_("Could not fetch admin login from tenant. Check container status."))

    def _install_support_module(self, max_retries=3, retry_delay=5):
        """Install the saas_support_client module in the tenant instance.

        This module provides the /support/login endpoint for one-click
        support access after customer approval.

        Uses retry logic with exponential backoff to handle transient failures
        like database connection limits.

        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 5)

        Returns:
            bool: True if module was installed successfully, False otherwise
        """
        import time

        if not self.container_name:
            _logger.warning(f"No container name for tenant {self.subdomain}")
            return False

        # Get VPN IP from server or use default
        vpn_ip = None
        docker_port = 2375
        if self.server_id:
            vpn_ip = self.server_id.vpn_ip or ServerConfig.TENANT_VPN_IP
            docker_port = self.server_id.docker_api_port or 2375
        else:
            vpn_ip = ServerConfig.TENANT_VPN_IP

        if not vpn_ip:
            _logger.warning(f"No VPN IP configured for tenant {self.subdomain}")
            return False

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                import docker
                import tarfile
                import io
                import os

                # Connect to Docker on tenant server via VPN
                docker_url = f"tcp://{vpn_ip}:{docker_port}"
                client = docker.DockerClient(base_url=docker_url, timeout=120)

                # Get the container
                try:
                    container = client.containers.get(self.container_name)
                except docker.errors.NotFound:
                    _logger.error(f"Container {self.container_name} not found")
                    return False

                if container.status != 'running':
                    _logger.warning(f"Container {self.container_name} is not running")
                    return False

                # Path to the support client module on master server
                module_source = '/opt/odoo/custom-addons/saas_support_client'
                if not os.path.exists(module_source):
                    _logger.error(f"Support module not found at {module_source}")
                    return False

                # Create tar archive of the module
                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                    tar.add(module_source, arcname='saas_support_client')
                tar_stream.seek(0)

                # Copy to container's addons directory
                addons_path = '/opt/odoo/custom-addons'

                # Create the custom-addons directory if it doesn't exist
                container.exec_run(['mkdir', '-p', addons_path])

                # Put the module in the container
                container.put_archive(addons_path, tar_stream.read())
                _logger.info(f"Copied saas_support_client module to {self.container_name}")

                # Check if module already installed
                check_cmd = [
                    'bash', '-c',
                    f"PGPASSWORD=odoo psql -h host.docker.internal -U odoo -d {self.database_name} "
                    f"-t -c \"SELECT state FROM ir_module_module WHERE name='saas_support_client';\""
                ]
                exit_code, output = container.exec_run(check_cmd, demux=False)
                current_state = output.decode().strip() if output else ''

                # Determine install or upgrade
                if current_state == 'installed':
                    action_flag = '-u'
                    action_name = 'Upgrading'
                else:
                    action_flag = '-i'
                    action_name = 'Installing'

                # Install/upgrade the module using odoo-bin
                install_cmd = [
                    '/opt/odoo/venv/bin/python3',
                    '/opt/odoo/odoo/odoo-bin',
                    '-c', '/etc/odoo/odoo.conf',
                    '-d', self.database_name,
                    action_flag, 'saas_support_client',
                    '--stop-after-init',
                    '--no-http',
                ]

                _logger.info(f"{action_name} saas_support_client module on {self.subdomain}...")
                exit_code, output = container.exec_run(install_cmd, demux=False)
                output_str = output.decode() if output else ''

                if exit_code == 0:
                    _logger.info(f"Successfully installed saas_support_client on {self.subdomain}")
                    return True
                else:
                    # Check for specific error conditions
                    if 'too many clients' in output_str.lower():
                        raise ConnectionError("PostgreSQL: too many clients")
                    if 'already installed' in output_str.lower():
                        _logger.info(f"saas_support_client already installed on {self.subdomain}")
                        return True

                    last_error = f"exit={exit_code}, output={output_str[-300:]}"
                    raise RuntimeError(last_error)

            except (ConnectionError, RuntimeError) as e:
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            # Retry with exponential backoff
            if attempt < max_retries:
                current_delay = retry_delay * (2 ** attempt)  # Exponential backoff
                _logger.warning(
                    f"Module install attempt {attempt + 1}/{max_retries + 1} failed for "
                    f"{self.subdomain}: {last_error}. Retrying in {current_delay}s..."
                )
                time.sleep(current_delay)
            else:
                _logger.error(
                    f"All {max_retries + 1} attempts failed for module install on "
                    f"{self.subdomain}: {last_error}"
                )

        return False

    def _install_support_module_with_lock(self):
        """Install support module with cron lock to prevent concurrent runs."""
        from odoo.addons.saas_core.utils import TryLock

        with TryLock(self.env.cr, f'support_install_{self.id}') as lock:
            if not lock.acquired:
                _logger.info(f"Skipping support module install for {self.subdomain} - already running")
                return False
            return self._install_support_module()

    def action_install_support_module(self):
        """Manual action to install/reinstall the support module on this instance."""
        self.ensure_one()

        if self.state != InstanceState.RUNNING:
            raise UserError(_("Cannot install module - instance is not running."))

        success = self._install_support_module()

        if success:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Support Module Installed',
                    'message': f'The saas_support_client module has been installed on {self.subdomain}.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            raise UserError(_("Failed to install support module. Check the logs for details."))

    def action_regenerate_password(self):
        """Regenerate admin password for the instance and notify customer."""
        self.ensure_one()
        import secrets

        # Save old password before generating new one
        old_password = self.admin_password

        # Generate new password
        new_password = secrets.token_urlsafe(16)

        # Try to update password in tenant database
        tenant_updated = False
        if self.state == InstanceState.RUNNING:
            tenant_updated = self._set_tenant_admin_password(new_password, old_password)
            if not tenant_updated:
                _logger.warning(f"Could not sync password to tenant {self.subdomain} - will need manual update")

        # Save to master DB
        self.write({'admin_password': new_password})

        # Send notification email to customer
        template = self.env.ref(
            'saas_subscription.mail_template_saas_password_reset',
            raise_if_not_found=False
        )
        email_sent = False
        if template and self.admin_email:
            try:
                template.send_mail(self.id, force_send=True)
                email_sent = True
                _logger.info(f"Password reset email sent to {self.admin_email} for instance {self.subdomain}")
            except Exception as e:
                _logger.error(f"Failed to send password reset email: {e}")

        # Build message based on what succeeded
        if tenant_updated and email_sent:
            message = f'Password updated and email sent to {self.admin_email}'
            msg_type = 'success'
        elif tenant_updated:
            message = f'Password updated. Email not sent - notify customer manually.'
            msg_type = 'warning'
        elif email_sent:
            message = f'Password saved locally and email sent. Note: Tenant login still uses old password until manually updated.'
            msg_type = 'warning'
        else:
            message = f'Password saved locally. Tenant sync and email failed - manual intervention needed.'
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Password Regenerated',
                'message': message,
                'type': msg_type,
                'sticky': msg_type == 'warning',
            }
        }

    def action_send_credentials(self):
        """Send credentials email to the customer."""
        self.ensure_one()

        if not self.admin_email:
            raise UserError(_("No admin email configured for this instance."))

        # Find the email template
        template = self.env.ref(
            'saas_subscription.mail_template_saas_instance_ready',
            raise_if_not_found=False
        )

        if not template:
            raise UserError(_(
                "Email template 'saas_subscription.mail_template_saas_instance_ready' not found. "
                "Please install the saas_subscription module."
            ))

        # Send the email
        template.send_mail(self.id, force_send=True)

        _logger.info(f"Credentials email sent to {self.admin_email} for instance {self.subdomain}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Email Sent',
                'message': f'Credentials email sent to {self.admin_email}',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_copy_login_url(self):
        """Return the login URL for copying."""
        self.ensure_one()
        if not self.instance_url:
            raise UserError(_("Instance URL not available"))

        # Return URL with action to copy to clipboard (handled by JS)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Login URL',
                'message': f'{self.instance_url}/web/login',
                'type': 'info',
                'sticky': True,
            }
        }

    # -------------------------------------------------------------------------
    # Nginx Management
    # -------------------------------------------------------------------------

    def _run_local_command(self, command):
        """
        Run a command locally on the master server.

        Args:
            command: Command to execute locally (can be string or list)

        Returns:
            tuple: (success, output)
        """
        import subprocess

        try:
            if isinstance(command, str):
                # Use shell=True for string commands
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
            else:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _run_server_command(self, command, max_retries=3, retry_delay=2):
        """
        Run a command on the tenant server via SSH with VPN fallback.

        Tries public IP first, then falls back to VPN IP if available.
        Includes retry logic with exponential backoff.

        Args:
            command: Command to execute on the server
            max_retries: Maximum number of retry attempts per IP (default 3)
            retry_delay: Base delay between retries in seconds (default 2)

        Returns:
            tuple: (success, output)
        """
        self.ensure_one()
        if not self.server_id:
            return False, "No server assigned"

        import subprocess
        import time

        # Get SSH credentials
        ssh_user = 'root'
        ssh_password = self.env['ir.config_parameter'].sudo().get_param(
            'saas.tenant_ssh_password', 'changeme'
        )

        # Build list of IPs to try: public IP first, then VPN IP as fallback
        server_ips = []
        if self.server_id.ip_address:
            server_ips.append(('public', self.server_id.ip_address))
        if self.server_id.vpn_ip:
            server_ips.append(('vpn', self.server_id.vpn_ip))

        if not server_ips:
            return False, "No IP addresses configured for server"

        last_error = None
        for ip_type, ip_address in server_ips:
            _logger.debug(f"Trying SSH to {ip_type} IP: {ip_address}")

            ssh_cmd = [
                'sshpass', '-p', ssh_password,
                'ssh', '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=10',
                '-o', 'ServerAliveInterval=5',
                '-o', 'ServerAliveCountMax=2',
                f'{ssh_user}@{ip_address}',
                command
            ]

            for attempt in range(max_retries):
                try:
                    result = subprocess.run(
                        ssh_cmd,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if result.returncode == 0:
                        if ip_type == 'vpn':
                            _logger.info(f"SSH succeeded via VPN fallback to {ip_address}")
                        return True, result.stdout
                    else:
                        last_error = result.stderr
                        # Check if it's a transient error worth retrying
                        transient_errors = ['Connection refused', 'Connection timed out',
                                           'Network is unreachable', 'Host is unreachable']
                        if any(err in result.stderr for err in transient_errors):
                            if attempt < max_retries - 1:
                                delay = retry_delay * (2 ** attempt)  # Exponential backoff
                                _logger.warning(f"SSH to {ip_address} attempt {attempt + 1} failed, retrying in {delay}s")
                                time.sleep(delay)
                                continue
                            # All retries failed for this IP, try next IP
                            break
                        # Non-transient error (like permission denied after connection)
                        if 'Permission denied' in result.stderr:
                            return False, f"Authentication failed: {result.stderr}"
                        return False, result.stderr

                except subprocess.TimeoutExpired:
                    last_error = "Command timed out"
                    if attempt < max_retries - 1:
                        delay = retry_delay * (2 ** attempt)
                        _logger.warning(f"SSH to {ip_address} attempt {attempt + 1} timed out, retrying in {delay}s")
                        time.sleep(delay)
                        continue
                    break  # Try next IP

                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        delay = retry_delay * (2 ** attempt)
                        _logger.warning(f"SSH to {ip_address} attempt {attempt + 1} failed: {e}")
                        time.sleep(delay)
                        continue
                    break  # Try next IP

            _logger.warning(f"All SSH attempts to {ip_type} IP {ip_address} failed")

        return False, last_error or "All SSH connection attempts failed (public and VPN)"

    def _add_nginx_mapping(self):
        """Add nginx proxy mapping for this instance (runs on tenant server via SSH)."""
        self.ensure_one()
        if not self.subdomain or not self.port_http or not self.port_longpolling:
            _logger.warning(f"Cannot add nginx mapping: missing subdomain or ports")
            return False

        # Run nginx manager on tenant server via SSH
        command = f"/usr/local/bin/saas-nginx-manager add {self.subdomain} {self.port_http} {self.port_longpolling}"
        success, output = self._run_server_command(command)

        if success:
            _logger.info(f"Nginx mapping added for {self.subdomain}")
        else:
            _logger.error(f"Failed to add nginx mapping for {self.subdomain}: {output}")

        return success

    def _remove_nginx_mapping(self):
        """Remove nginx proxy mapping for this instance (runs on tenant server via SSH)."""
        self.ensure_one()
        if not self.subdomain:
            return False

        # Run nginx manager on tenant server via SSH
        command = f"/usr/local/bin/saas-nginx-manager remove {self.subdomain}"
        success, output = self._run_server_command(command)

        if success:
            _logger.info(f"Nginx mapping removed for {self.subdomain}")
        else:
            _logger.warning(f"Failed to remove nginx mapping for {self.subdomain}: {output}")

        return success

    def _request_ssl_certificate(self):
        """Request SSL certificate for this instance subdomain (runs on tenant server via SSH)."""
        self.ensure_one()
        if not self.subdomain:
            return False

        # Run nginx manager on tenant server via SSH
        command = f"/usr/local/bin/saas-nginx-manager ssl {self.subdomain}"
        success, output = self._run_server_command(command)

        if success:
            _logger.info(f"SSL certificate requested for {self.subdomain}")
        else:
            _logger.warning(f"Failed to request SSL for {self.subdomain}: {output}")

        return success

    # -------------------------------------------------------------------------
    # Sync Methods - Keep data in sync with tenant server
    # -------------------------------------------------------------------------

    def action_sync_state(self):
        """Sync instance state from Docker container."""
        self.ensure_one()
        if not self.server_id or not self.container_name:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Failed',
                    'message': 'No server or container assigned to this instance.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        try:
            client = self._get_docker_client()
            try:
                container = client.containers.get(self.container_name)
                container_status = container.status  # running, exited, paused, etc.

                # Map Docker status to instance state
                state_map = {
                    'running': InstanceState.RUNNING,
                    'exited': InstanceState.STOPPED,
                    'paused': InstanceState.STOPPED,
                    'restarting': InstanceState.RUNNING,
                    'created': InstanceState.PENDING,
                }
                new_state = state_map.get(container_status, self.state)

                if new_state != self.state:
                    old_state = self.state
                    self.write({
                        'state': new_state,
                        'status_message': f'State synced from Docker: {container_status}',
                    })
                    _logger.info(f"Instance {self.subdomain} state synced: {old_state} -> {new_state}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Sync Complete',
                        'message': f'Container status: {container_status}',
                        'type': 'success',
                        'sticky': False,
                    }
                }

            except Exception as e:
                # Container not found
                if self.state not in [InstanceState.DRAFT, InstanceState.TERMINATED]:
                    self.write({
                        'state': InstanceState.ERROR,
                        'status_message': f'Container not found: {e}',
                    })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Container Not Found',
                        'message': str(e),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

        except Exception as e:
            _logger.error(f"Failed to sync instance {self.subdomain}: {e}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Failed',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': False,
                }
            }

    @api.model
    def action_sync_all_instances(self):
        """Sync all instances with their Docker containers."""
        instances = self.search([
            ('state', 'not in', [InstanceState.DRAFT, InstanceState.TERMINATED]),
            ('server_id', '!=', False),
        ])

        synced = 0
        errors = 0

        for instance in instances:
            try:
                instance.action_sync_state()
                synced += 1
            except Exception as e:
                errors += 1
                _logger.error(f"Failed to sync {instance.subdomain}: {e}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Complete',
                'message': f'Synced {synced} instances. Errors: {errors}',
                'type': 'success' if errors == 0 else 'warning',
                'sticky': False,
            }
        }

    @api.model
    def cron_sync_instances(self):
        """Cron job to sync all instance states from Docker."""
        _logger.info("Starting instance sync cron job")
        self.action_sync_all_instances()
        return True

    @api.model
    def discover_containers(self):
        """
        Discover Docker containers on tenant servers that don't have instance records.
        Creates instance records for orphaned containers.
        """
        Server = self.env[ModelNames.SERVER]
        servers = Server.search([('state', '=', 'online')])

        discovered = 0
        for server in servers:
            try:
                import docker
                client = docker.DockerClient(base_url=server.docker_api_url, timeout=30)
                containers = client.containers.list(all=True, filters={'label': 'saas.instance'})

                for container in containers:
                    subdomain = container.labels.get('saas.instance', '')
                    if not subdomain:
                        continue

                    # Check if instance exists
                    existing = self.search([('subdomain', '=', subdomain)], limit=1)
                    if existing:
                        # Update container_id if different
                        if existing.container_id != container.id[:12]:
                            existing.write({'container_id': container.id[:12]})
                        continue

                    # Create new instance record for discovered container
                    _logger.warning(f"Discovered orphan container: {container.name} ({subdomain})")
                    # Note: Would need more info to fully create the record
                    discovered += 1

            except Exception as e:
                _logger.error(f"Error discovering containers on {server.name}: {e}")

        if discovered:
            _logger.info(f"Discovered {discovered} orphan containers")
        return discovered

    # -------------------------------------------------------------------------
    # Support Access / Impersonation
    # -------------------------------------------------------------------------

    def action_impersonate(self):
        """
        Request support access to the tenant instance.

        This creates a support access request that requires customer approval.
        The customer receives an email with approve/deny buttons.

        Returns:
            dict: Action to show the pending request or wizard
        """
        self.ensure_one()

        if self.state != InstanceState.RUNNING:
            raise UserError(_("Cannot access instance - it is not running."))

        if not self.admin_email:
            raise UserError(_("No customer email configured. Cannot send approval request."))

        # Check for existing pending/approved request
        existing = self.env['saas.support.access.request'].search([
            ('instance_id', '=', self.id),
            ('requested_by_id', '=', self.env.uid),
            ('state', 'in', ['pending', 'approved']),
        ], limit=1)

        if existing:
            if existing.state == 'approved':
                # Access already approved - proceed to login
                return existing.action_access_instance()
            else:
                # Request pending - show message
                raise UserError(_(
                    "A support access request is already pending for this instance.\n"
                    "Please wait for the customer to approve your request."
                ))

        # Create new access request
        access_request = self.env['saas.support.access.request'].create({
            'instance_id': self.id,
            'requested_by_id': self.env.uid,
        })

        # Send approval email to customer
        self._send_support_access_approval_email(access_request)

        # Show confirmation
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Access Request Sent',
                'message': f'Approval request sent to {self.admin_email}. You will be notified when approved.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_access_approved_instance(self):
        """
        Access an instance that has an approved request.

        Called from the instance form when there's an approved request.
        """
        self.ensure_one()

        # Find approved request
        approved_request = self.env['saas.support.access.request'].search([
            ('instance_id', '=', self.id),
            ('requested_by_id', '=', self.env.uid),
            ('state', '=', 'approved'),
        ], limit=1)

        if not approved_request:
            raise UserError(_("No approved access request found. Please request access first."))

        return approved_request.action_access_instance()

    def _send_support_access_approval_email(self, access_request):
        """Send email with approval link to customer."""
        self.ensure_one()

        # Get decrypted email (admin_email is an encrypted field)
        customer_email = self._get_decrypted_value('admin_email')
        if not customer_email:
            _logger.warning(f"No admin email for instance {self.subdomain}")
            return

        try:
            approval_url = access_request.get_approval_url()
            support_user = self.env.user.name
            request_time = fields.Datetime.now().strftime('%Y-%m-%d %H:%M UTC')

            subject = f"Support Access Request - {self.name}"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #875A7B; padding: 20px; text-align: center;">
                    <h1 style="color: white; margin: 0;">Support Access Request</h1>
                </div>

                <div style="padding: 30px; background-color: #f8f9fa;">
                    <p>Dear Customer,</p>

                    <p>A VedTech Solutions support representative is requesting access to your Odoo instance for troubleshooting purposes.</p>

                    <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #875A7B;">
                        <p style="margin: 5px 0;"><strong>Instance:</strong> {self.name} ({self.subdomain})</p>
                        <p style="margin: 5px 0;"><strong>Support Agent:</strong> {support_user}</p>
                        <p style="margin: 5px 0;"><strong>Request Time:</strong> {request_time}</p>
                    </div>

                    <p>Please review this request and click one of the buttons below:</p>

                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{approval_url}"
                           style="display: inline-block; padding: 15px 40px; background-color: #28a745; color: white;
                                  text-decoration: none; border-radius: 5px; font-size: 16px; font-weight: bold;
                                  margin: 10px;">
                            Approve Access
                        </a>
                    </div>

                    <p style="color: #6c757d; font-size: 14px;">
                        <strong>Note:</strong> This request will expire in 1 hour. If you did not expect this request
                        or have concerns, you can simply ignore this email or click the link to deny access.
                    </p>

                    <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

                    <p style="color: #6c757d; font-size: 12px;">
                        This email was sent by the VedTech SaaS Platform. All support access is logged for security and audit purposes.
                        If you have questions, contact us at support@vedtechsolutions.com.
                    </p>
                </div>
            </div>
            """

            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': customer_email,
                'email_from': self.env.company.email or 'noreply@vedtechsolutions.com',
                'auto_delete': True,
            }
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()

            _logger.info(f"Support access approval request sent to {customer_email} for {self.subdomain}")

        except Exception as e:
            _logger.error(f"Failed to send approval email: {e}")
            raise UserError(_("Failed to send approval email: %s") % e)

    def _send_support_access_notification(self):
        """Send email notification to customer about support access (after approval)."""
        self.ensure_one()

        # Get decrypted email (admin_email is an encrypted field)
        customer_email = self._get_decrypted_value('admin_email')
        if not customer_email:
            _logger.warning(f"No admin email for instance {self.subdomain}, skipping notification")
            return

        try:
            # Compose email
            subject = f"Support Access Notification - {self.name}"
            support_user = self.env.user.name
            access_time = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #875A7B;">Support Access Notification</h2>
                <p>Dear Customer,</p>
                <p>This is to inform you that a VedTech Solutions support representative has accessed your Odoo instance for support purposes.</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Instance:</strong> {self.name} ({self.subdomain})</p>
                    <p><strong>Support Agent:</strong> {support_user}</p>
                    <p><strong>Access Time:</strong> {access_time}</p>
                </div>

                <p>If you did not request support or have any concerns about this access, please contact us immediately at support@vedtechsolutions.com.</p>

                <p style="color: #6c757d; font-size: 12px; margin-top: 30px;">
                    This notification was sent automatically by the VedTech SaaS Platform for transparency and security purposes.
                </p>
            </div>
            """

            # Send email
            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': customer_email,
                'email_from': self.env.company.email or 'noreply@vedtechsolutions.com',
                'auto_delete': True,
            }
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()

            _logger.info(f"Support access notification sent to {customer_email} for {self.subdomain}")

        except Exception as e:
            _logger.error(f"Failed to send support access notification: {e}")
            # Don't block support access if email fails

    def _log_support_access(self):
        """Log the support access attempt for audit purposes."""
        self.ensure_one()

        # Create audit log entry
        SupportAccessLog = self.env.get('saas.support.access.log')
        if SupportAccessLog is not None:
            SupportAccessLog.create({
                'instance_id': self.id,
                'user_id': self.env.uid,
                'access_type': 'impersonate',
                'ip_address': self._get_client_ip(),
            })

        # Also log to chatter for visibility
        self.message_post(
            body=f"<strong>Support Access:</strong> {self.env.user.name} accessed this instance for support.",
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

        _logger.info(
            f"Support access: User {self.env.user.login} (ID: {self.env.uid}) "
            f"impersonated into instance {self.subdomain}"
        )

    def _get_client_ip(self):
        """Get the client IP address from the request."""
        try:
            from odoo.http import request
            if request and hasattr(request, 'httprequest'):
                # Check for X-Forwarded-For header (behind proxy)
                forwarded_for = request.httprequest.headers.get('X-Forwarded-For')
                if forwarded_for:
                    return forwarded_for.split(',')[0].strip()
                return request.httprequest.remote_addr
        except Exception as e:
            _logger.debug(f"Could not get client IP from request: {e}")
        return 'unknown'

    def _create_support_access_token(self, max_retries=3, retry_delay=2):
        """
        Create a one-time support access token in the tenant database.

        The token allows auto-login to the tenant instance and expires
        after 5 minutes or first use.

        Uses retry logic with savepoints to handle transient failures.

        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 2)

        Returns:
            str: The generated token, or None if failed
        """
        self.ensure_one()

        import secrets
        import requests
        import time
        from datetime import datetime, timedelta

        if not self.database_name or not self.instance_url:
            _logger.error("Missing database or URL info for token creation")
            return None

        # Generate token data
        token = secrets.token_urlsafe(32)
        token_key = f'saas.support_token.{token[:8]}'
        expiry = (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

        # Create callback URL for session end notifications
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        callback_url = f'{base_url}/support/session/callback/{self.id}'

        # Token format: token|expiry|master_uid:::callback_url
        token_value = f'{token}|{expiry}|{self.env.uid}:::{callback_url}'

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Create a savepoint for this attempt (validated to prevent SQL injection)
                raw_savepoint = f"token_create_{attempt}_{int(time.time() * 1000)}"
                savepoint_name = validate_savepoint_name(raw_savepoint)
                self.env.cr.execute(f"SAVEPOINT {savepoint_name}")

                try:
                    # Use JSON-RPC to create token in tenant database
                    session = requests.Session()

                    # Authenticate to tenant with timeout
                    auth_url = f"{self.instance_url}/web/session/authenticate"
                    # Use _get_decrypted_value to ensure we get the plain password
                    # (not the ENC::... encrypted value from the mixin)
                    plain_password = self._get_decrypted_value('admin_password')

                    auth_response = session.post(auth_url, json={
                        "jsonrpc": "2.0",
                        "method": "call",
                        "params": {
                            "db": self.database_name,
                            "login": "admin",
                            "password": plain_password,
                        },
                        "id": 1,
                    }, timeout=30)

                    auth_data = auth_response.json()
                    if not auth_data.get('result', {}).get('uid'):
                        raise ValueError(f"Auth failed: {auth_data.get('error', 'Unknown error')}")

                    # Set the config parameter
                    rpc_url = f"{self.instance_url}/web/dataset/call_kw/ir.config_parameter/set_param"
                    rpc_response = session.post(rpc_url, json={
                        "jsonrpc": "2.0",
                        "method": "call",
                        "params": {
                            "model": "ir.config_parameter",
                            "method": "set_param",
                            "args": [token_key, token_value],
                            "kwargs": {},
                        },
                        "id": 2,
                    }, timeout=30)

                    rpc_data = rpc_response.json()
                    if 'error' in rpc_data:
                        raise ValueError(f"RPC failed: {rpc_data['error']}")

                    # Release savepoint on success
                    self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")

                    _logger.info(f"Support access token created for {self.subdomain}: {token_key}")
                    return token

                except Exception as e:
                    # Rollback to savepoint
                    self.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                    raise

            except requests.exceptions.Timeout:
                last_error = "Connection timeout"
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
            except ValueError as e:
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            # Log retry attempt
            if attempt < max_retries:
                _logger.warning(
                    f"Token creation attempt {attempt + 1}/{max_retries + 1} failed for "
                    f"{self.subdomain}: {last_error}. Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                _logger.error(
                    f"All {max_retries + 1} attempts failed for token creation on "
                    f"{self.subdomain}: {last_error}"
                )

        return None

    def action_view_support_access_logs(self):
        """View support access logs for this instance."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Support Access Logs - {self.subdomain}',
            'res_model': 'saas.support.access.log',
            'view_mode': 'list,form',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }
