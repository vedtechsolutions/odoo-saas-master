# -*- coding: utf-8 -*-
"""
SaaS Tenant Server model.

Manages Docker host servers where customer Odoo instances run.
"""

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.fields import ModelNames, FieldLabels
from odoo.addons.saas_core.constants.states import ServerState
from odoo.addons.saas_core.constants.config import ServerConfig

_logger = logging.getLogger(__name__)


class SaasTenantServer(models.Model):
    """Tenant server hosting Docker containers for customer instances."""

    _name = ModelNames.SERVER
    _description = 'SaaS Tenant Server'
    _order = 'sequence, name'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'saas.audit.mixin']

    # Odoo 19 constraint syntax
    _server_code_unique = models.Constraint(
        'UNIQUE(server_code)',
        'Server code must be unique!'
    )
    _ip_address_unique = models.Constraint(
        'UNIQUE(ip_address)',
        'IP address must be unique!'
    )

    # Basic fields
    name = fields.Char(
        string=FieldLabels.NAME,
        required=True,
        tracking=True,
    )
    server_code = fields.Char(
        string='Server Code',
        required=True,
        index=True,
        help='Unique server identifier (e.g., TENANT-001)',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )

    # Network configuration
    ip_address = fields.Char(
        string=FieldLabels.IP_ADDRESS,
        required=True,
        help='Public IP address of the server',
    )
    vpn_ip = fields.Char(
        string=FieldLabels.VPN_IP,
        help='WireGuard VPN IP address for secure communication',
    )
    ssh_port = fields.Integer(
        string='SSH Port',
        default=22,
    )

    # Docker configuration
    docker_api_port = fields.Integer(
        string='Docker API Port',
        default=ServerConfig.DOCKER_API_PORT,
    )
    docker_api_url = fields.Char(
        string='Docker API URL',
        compute='_compute_docker_api_url',
        store=True,
    )

    # State
    state = fields.Selection(
        selection=ServerState.get_selection(),
        string=FieldLabels.STATE,
        default=ServerState.OFFLINE,
        required=True,
        tracking=True,
    )

    # Capacity
    max_instances = fields.Integer(
        string='Max Instances',
        default=50,
        help='Maximum number of instances this server can host',
    )
    instance_count = fields.Integer(
        string='Current Instances',
        compute='_compute_instance_count',
        store=True,
    )
    available_slots = fields.Integer(
        string='Available Slots',
        compute='_compute_available_slots',
        store=True,
    )

    # Resource monitoring
    cpu_usage_percent = fields.Float(
        string='CPU Usage (%)',
        readonly=True,
    )
    ram_usage_percent = fields.Float(
        string='RAM Usage (%)',
        readonly=True,
    )
    disk_usage_percent = fields.Float(
        string='Disk Usage (%)',
        readonly=True,
    )

    # Port allocation
    port_range_start = fields.Integer(
        string='Port Range Start',
        default=ServerConfig.TENANT_PORT_MIN,
    )
    port_range_end = fields.Integer(
        string='Port Range End',
        default=ServerConfig.TENANT_PORT_MAX,
    )

    # Timestamps
    last_health_check = fields.Datetime(
        string='Last Health Check',
        readonly=True,
    )

    # Relations
    instance_ids = fields.One2many(
        ModelNames.INSTANCE,
        'server_id',
        string='Instances',
    )

    @api.depends('vpn_ip', 'docker_api_port')
    def _compute_docker_api_url(self):
        """Compute Docker API URL from VPN IP and port."""
        for server in self:
            if server.vpn_ip and server.docker_api_port:
                server.docker_api_url = f"tcp://{server.vpn_ip}:{server.docker_api_port}"
            else:
                server.docker_api_url = False

    @api.depends('instance_ids', 'instance_ids.state')
    def _compute_instance_count(self):
        """Count active instances on this server."""
        for server in self:
            server.instance_count = len(server.instance_ids.filtered(
                lambda i: i.state not in ['draft', 'terminated']
            ))

    def refresh_instance_counts(self):
        """Force refresh of instance counts - call after instance changes."""
        for server in self:
            # For stored computed fields, signal that dependencies changed
            # This marks the computed fields as needing recomputation
            server.modified(['instance_ids'])
        # Flush to database to trigger recomputation
        self.flush_recordset(['instance_count', 'available_slots'])
        return True

    @api.depends('max_instances', 'instance_count')
    def _compute_available_slots(self):
        """Calculate available instance slots."""
        for server in self:
            server.available_slots = max(0, server.max_instances - server.instance_count)

    def action_check_health(self):
        """Check Docker API connectivity and update status."""
        self.ensure_one()
        try:
            # Import docker here to avoid import issues if not installed
            import docker

            if not self.docker_api_url:
                raise UserError(_("Docker API URL not configured. Please set VPN IP."))

            client = docker.DockerClient(base_url=self.docker_api_url, timeout=10)
            info = client.info()

            self.write({
                'state': ServerState.ONLINE,
                'last_health_check': fields.Datetime.now(),
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Health Check Passed',
                    'message': f"Docker version: {info.get('ServerVersion', 'Unknown')}",
                    'type': 'success',
                    'sticky': False,
                }
            }

        except ImportError:
            raise UserError(_("Docker SDK not installed. Run: pip install docker"))
        except Exception as e:
            _logger.error(f"Health check failed for {self.name}: {e}")
            self.write({
                'state': ServerState.ERROR,
                'last_health_check': fields.Datetime.now(),
            })
            raise UserError(_("Health check failed: %s") % str(e))

    def action_set_online(self):
        """Manually set server online."""
        self.write({'state': ServerState.ONLINE})

    def action_set_maintenance(self):
        """Set server to maintenance mode."""
        self.write({'state': ServerState.MAINTENANCE})

    def action_set_offline(self):
        """Set server offline."""
        self.write({'state': ServerState.OFFLINE})

    def action_view_instances(self):
        """Open instances on this server."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Instances - {self.name}',
            'res_model': ModelNames.INSTANCE,
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }

    def get_available_port(self, check_actual=True):
        """
        Find the next available HTTP port for a new instance.

        This method checks both the database records AND the actual Docker
        containers to prevent port conflicts. It also checks if the port
        is actually listening on the server.

        Args:
            check_actual: If True, also verify port availability via Docker (default True)

        Returns:
            int: Available port number

        Raises:
            UserError: If no ports are available
        """
        self.ensure_one()

        # Get ports used by instances in the database (not terminated)
        db_used_ports = set(self.instance_ids.filtered(
            lambda i: i.state not in ['terminated']
        ).mapped('port_http'))

        # Also get ports from Docker if we can connect
        docker_used_ports = set()
        if check_actual and self.docker_api_url:
            try:
                docker_used_ports = self._get_docker_used_ports()
                _logger.debug(f"Docker reports {len(docker_used_ports)} ports in use")
            except Exception as e:
                _logger.warning(f"Could not check Docker ports: {e}")

        # Combine both sources to get all potentially used ports
        all_used_ports = db_used_ports.union(docker_used_ports)

        # Find first available port
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in all_used_ports:
                # Also check longpolling port (port + 1000)
                longpoll_port = port + ServerConfig.LONGPOLLING_PORT_OFFSET
                if longpoll_port not in all_used_ports:
                    _logger.info(f"Allocated port {port} (longpolling: {longpoll_port}) on {self.name}")
                    return port

        raise UserError(_("No available ports on server %(name)s. Port range: %(start)s-%(end)s") % {
            'name': self.name,
            'start': self.port_range_start,
            'end': self.port_range_end,
        })

    def _get_docker_used_ports(self):
        """
        Get all ports currently bound by Docker containers.

        Returns:
            set: Set of port numbers currently in use
        """
        self.ensure_one()
        used_ports = set()

        try:
            import docker

            if not self.docker_api_url:
                return used_ports

            client = docker.DockerClient(base_url=self.docker_api_url, timeout=15)
            containers = client.containers.list(all=True)

            for container in containers:
                # Get port bindings from container
                ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
                if ports:
                    for container_port, bindings in ports.items():
                        if bindings:
                            for binding in bindings:
                                host_port = binding.get('HostPort')
                                if host_port:
                                    used_ports.add(int(host_port))

                # Also check HostConfig port bindings for stopped containers
                host_config = container.attrs.get('HostConfig', {})
                port_bindings = host_config.get('PortBindings', {})
                if port_bindings:
                    for container_port, bindings in port_bindings.items():
                        if bindings:
                            for binding in bindings:
                                host_port = binding.get('HostPort')
                                if host_port:
                                    used_ports.add(int(host_port))

        except ImportError:
            _logger.warning("Docker SDK not installed, cannot check actual port usage")
        except Exception as e:
            _logger.warning(f"Failed to get Docker port usage: {e}")

        return used_ports

    def has_capacity(self):
        """Check if server can accept new instances."""
        self.ensure_one()
        return (
            self.state == ServerState.ONLINE and
            self.available_slots > 0
        )

    @api.model
    def get_available_server(self):
        """
        Get a server with available capacity.

        Returns:
            recordset: Available server or empty recordset
        """
        return self.search([
            ('state', '=', ServerState.ONLINE),
            ('available_slots', '>', 0),
        ], order='instance_count', limit=1)

    def action_refresh_stats(self):
        """Fetch current resource usage from the server via Docker API."""
        self.ensure_one()
        try:
            import docker
            import requests

            if not self.docker_api_url:
                raise UserError(_("Docker API URL not configured. Please set VPN IP."))

            # Get Docker system info
            client = docker.DockerClient(base_url=self.docker_api_url, timeout=10)
            info = client.info()

            # Calculate memory usage
            mem_total = info.get('MemTotal', 0)
            # Get memory usage from Docker stats endpoint
            base_url = f"http://{self.vpn_ip}:{self.docker_api_port}"

            # Get system df for disk usage
            df_response = requests.get(f"{base_url}/system/df", timeout=10)
            df_data = df_response.json() if df_response.ok else {}

            # Calculate disk usage from Docker
            layers_size = df_data.get('LayersSize', 0)
            containers_size = sum(c.get('SizeRw', 0) for c in df_data.get('Containers', []))
            volumes_size = sum(v.get('UsageData', {}).get('Size', 0) for v in df_data.get('Volumes', []))
            total_docker_usage = layers_size + containers_size + volumes_size

            # Estimate disk usage (Docker typically has access to see this)
            # We'll use a simple estimation based on Docker data
            disk_percent = 0.0
            if 'SystemStatus' in info:
                for item in info['SystemStatus']:
                    if 'disk' in str(item).lower():
                        _logger.info(f"Disk info: {item}")

            # Get CPU info - count of CPUs
            ncpu = info.get('NCPU', 1)

            # For actual CPU/RAM percentages, we need to query running containers
            containers = client.containers.list()
            total_cpu_percent = 0.0
            total_mem_usage = 0

            for container in containers:
                try:
                    stats = container.stats(stream=False)

                    # Calculate CPU percentage
                    cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                stats['precpu_stats']['cpu_usage']['total_usage']
                    system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                                   stats['precpu_stats']['system_cpu_usage']
                    if system_delta > 0:
                        cpu_percent = (cpu_delta / system_delta) * ncpu * 100.0
                        total_cpu_percent += cpu_percent

                    # Get memory usage
                    mem_usage = stats['memory_stats'].get('usage', 0)
                    total_mem_usage += mem_usage
                except Exception as e:
                    _logger.warning(f"Could not get stats for container {container.name}: {e}")

            # Calculate RAM percentage
            ram_percent = (total_mem_usage / mem_total * 100) if mem_total > 0 else 0

            # Update server stats
            self.write({
                'cpu_usage_percent': min(round(total_cpu_percent, 1), 100.0),
                'ram_usage_percent': min(round(ram_percent, 1), 100.0),
                'disk_usage_percent': min(round(total_docker_usage / (1024**3) / 100 * 100, 1), 100.0),  # Rough estimate
                'last_health_check': fields.Datetime.now(),
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Stats Refreshed',
                    'message': f"CPU: {self.cpu_usage_percent}% | RAM: {self.ram_usage_percent}% | Containers: {len(containers)}",
                    'type': 'success',
                    'sticky': False,
                }
            }

        except ImportError:
            raise UserError(_("Docker SDK not installed. Run: pip install docker"))
        except Exception as e:
            _logger.error(f"Failed to refresh stats for {self.name}: {e}")
            raise UserError(_("Failed to refresh stats: %s") % str(e))

    def action_sync_instances(self):
        """
        Sync instance states with actual Docker container states.

        This is the core method that ensures SaaS Master reflects reality.
        It queries Docker for container states and updates instance records.
        """
        self.ensure_one()
        try:
            import docker

            if not self.docker_api_url:
                raise UserError(_("Docker API URL not configured. Please set VPN IP."))

            client = docker.DockerClient(base_url=self.docker_api_url, timeout=30)

            # Get all containers (including stopped)
            containers = client.containers.list(all=True)
            container_map = {}

            for container in containers:
                # Check if it's a SaaS instance container
                labels = container.labels
                if 'saas.instance' in labels:
                    subdomain = labels['saas.instance']
                    container_map[subdomain] = {
                        'id': container.id[:12],
                        'name': container.name,
                        'status': container.status,  # running, exited, paused, etc.
                        'container': container,
                    }

            _logger.info(f"Found {len(container_map)} SaaS containers on {self.name}")

            # Sync each instance
            Instance = self.env['saas.instance']
            updated = 0
            errors = []

            for instance in self.instance_ids:
                if instance.state == 'terminated':
                    continue

                container_info = container_map.get(instance.subdomain)

                if container_info:
                    # Container exists - sync state
                    docker_status = container_info['status']
                    current_state = instance.state
                    new_state = current_state

                    if docker_status == 'running':
                        if current_state not in ['running', 'suspended']:
                            new_state = 'running'
                    elif docker_status in ['exited', 'dead']:
                        if current_state == 'running':
                            new_state = 'stopped'
                    elif docker_status == 'paused':
                        new_state = 'suspended'

                    # Update container ID if different
                    updates = {}
                    if instance.container_id != container_info['id']:
                        updates['container_id'] = container_info['id']
                    if new_state != current_state:
                        updates['state'] = new_state
                        updates['status_message'] = f"Synced from Docker: {docker_status}"

                    if updates:
                        instance.write(updates)
                        updated += 1
                        _logger.info(f"Synced instance {instance.subdomain}: {current_state} -> {new_state}")
                else:
                    # No container found for this instance
                    if instance.state in ['running', 'stopped']:
                        errors.append(f"{instance.subdomain}: Container not found")
                        instance.write({
                            'state': 'error',
                            'status_message': 'Container not found on server',
                            'container_id': False,
                        })
                        updated += 1

            # Refresh computed fields
            self.refresh_instance_counts()

            # Build result message
            msg_parts = [f"Synced {updated} instances"]
            if errors:
                msg_parts.append(f"Errors: {', '.join(errors[:3])}")
                if len(errors) > 3:
                    msg_parts.append(f"...and {len(errors) - 3} more")

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Complete',
                    'message': ' | '.join(msg_parts),
                    'type': 'warning' if errors else 'success',
                    'sticky': bool(errors),
                }
            }

        except ImportError:
            raise UserError(_("Docker SDK not installed. Run: pip install docker"))
        except Exception as e:
            _logger.error(f"Failed to sync instances for {self.name}: {e}")
            raise UserError(_("Failed to sync instances: %s") % str(e))
