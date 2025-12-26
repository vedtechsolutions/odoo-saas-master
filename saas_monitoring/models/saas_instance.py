# -*- coding: utf-8 -*-
"""
Extends saas.instance with monitoring capabilities.
"""

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaasInstanceMonitoring(models.Model):
    """Extend saas.instance with monitoring fields."""
    _inherit = 'saas.instance'

    # Monitoring relations
    usage_metric_ids = fields.One2many(
        'saas.usage.metric',
        'instance_id',
        string='Usage Metrics',
    )
    usage_log_ids = fields.One2many(
        'saas.usage.log',
        'instance_id',
        string='Usage Logs',
    )
    alert_ids = fields.One2many(
        'saas.alert',
        'instance_id',
        string='Alerts',
    )

    # Computed counts (stored for filtering/search)
    active_alert_count = fields.Integer(
        string='Active Alerts',
        compute='_compute_alert_counts',
        store=True,
    )
    total_alert_count = fields.Integer(
        string='Total Alerts',
        compute='_compute_alert_counts',
        store=True,
    )

    # Health status
    health_status = fields.Selection([
        ('healthy', 'Healthy'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('unknown', 'Unknown'),
    ], string='Health Status', compute='_compute_health_status', store=True)

    # Quick metric access (for dashboard, stored for search/sort)
    cpu_usage = fields.Float(
        string='CPU Usage %',
        compute='_compute_quick_metrics',
        store=True,
    )
    memory_usage = fields.Float(
        string='Memory Usage %',
        compute='_compute_quick_metrics',
        store=True,
    )
    disk_usage = fields.Float(
        string='Disk Usage %',
        compute='_compute_quick_metrics',
        store=True,
    )
    user_count = fields.Integer(
        string='Active Users',
        compute='_compute_quick_metrics',
        store=True,
    )

    @api.depends('alert_ids', 'alert_ids.is_active')
    def _compute_alert_counts(self):
        Alert = self.env['saas.alert']
        for record in self:
            record.active_alert_count = Alert.search_count([
                ('instance_id', '=', record.id),
                ('is_active', '=', True),
            ])
            record.total_alert_count = Alert.search_count([
                ('instance_id', '=', record.id),
            ])

    @api.depends('usage_metric_ids.status')
    def _compute_health_status(self):
        for record in self:
            if not record.usage_metric_ids:
                record.health_status = 'unknown'
                continue

            statuses = record.usage_metric_ids.mapped('status')
            if 'exceeded' in statuses or 'critical' in statuses:
                record.health_status = 'critical'
            elif 'warning' in statuses:
                record.health_status = 'warning'
            else:
                record.health_status = 'healthy'

    @api.depends('usage_metric_ids', 'usage_metric_ids.usage_percent', 'usage_metric_ids.current_value', 'usage_metric_ids.metric_code')
    def _compute_quick_metrics(self):
        for record in self:
            metrics = {m.metric_code: m for m in record.usage_metric_ids}

            record.cpu_usage = metrics.get('cpu', self.env['saas.usage.metric']).usage_percent or 0
            record.memory_usage = metrics.get('memory', self.env['saas.usage.metric']).usage_percent or 0
            record.disk_usage = metrics.get('disk', self.env['saas.usage.metric']).usage_percent or 0
            record.user_count = int(metrics.get('users', self.env['saas.usage.metric']).current_value or 0)

    def action_view_metrics(self):
        """Open metrics view for this instance."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Metrics - {self.name}',
            'res_model': 'saas.usage.metric',
            'view_mode': 'tree,form',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }

    def action_view_alerts(self):
        """Open alerts view for this instance."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Alerts - {self.name}',
            'res_model': 'saas.alert',
            'view_mode': 'tree,form',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }

    def action_view_usage_history(self):
        """Open usage history for this instance."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Usage History - {self.name}',
            'res_model': 'saas.usage.log',
            'view_mode': 'tree,graph,pivot',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }

    def collect_metrics(self):
        """Collect current metrics for this instance via Docker API."""
        self.ensure_one()
        if self.state != 'running':
            _logger.debug(f"Skipping metric collection for non-running instance {self.name}")
            return False

        if not self.container_id or not self.server_id:
            _logger.debug(f"No container or server for instance {self.name}")
            return False

        _logger.info(f"Collecting metrics for instance {self.name}")

        try:
            # Get container stats via Docker API
            stats = self._get_container_stats()
            if stats:
                self._update_metrics_from_docker(stats)
                return True
            return False
        except Exception as e:
            _logger.error(f"Failed to collect metrics for {self.name}: {e}")
            return False

    def _get_container_stats(self):
        """Get container stats from Docker API on tenant server."""
        self.ensure_one()
        try:
            import docker

            server = self.server_id
            if not server.docker_api_url:
                _logger.warning(f"No Docker API URL for server {server.name}")
                return None

            client = docker.DockerClient(base_url=server.docker_api_url, timeout=10)

            # Look up container by name (more resilient than ID)
            container = client.containers.get(self.container_name)

            # Auto-fix container_id if it changed (container was recreated)
            current_id = container.id[:12]
            if self.container_id != current_id:
                _logger.info(
                    f"Container ID changed for {self.container_name}: "
                    f"{self.container_id} -> {current_id}, updating record"
                )
                self.sudo().write({'container_id': current_id})

            stats = container.stats(stream=False)

            # Also get container info for additional data
            info = container.attrs

            return {
                'stats': stats,
                'info': info,
                'server_info': client.info(),
            }
        except ImportError:
            _logger.error("Docker SDK not installed. Run: pip install docker")
            return None
        except Exception as e:
            _logger.error(f"Error getting container stats for {self.container_name}: {e}")
            return None

    def _get_storage_metrics(self):
        """Get storage metrics (database size and filestore size).

        Returns:
            dict: {'db_size_gb': float, 'filestore_size_gb': float}
        """
        self.ensure_one()
        result = {'db_size_gb': 0.0, 'filestore_size_gb': 0.0}

        if not self.database_name or not self.container_name:
            return result

        # Get database size via SSH to tenant server
        try:
            db_cmd = f"PGPASSWORD=odoo psql -h localhost -U odoo -d postgres -t -c \"SELECT pg_database_size('{self.database_name}')\" 2>/dev/null | tr -d ' '"
            success, output = self._run_server_command(db_cmd, max_retries=1, retry_delay=1)
            if success and output.strip():
                db_size_bytes = int(output.strip())
                result['db_size_gb'] = round(db_size_bytes / (1024 ** 3), 3)  # bytes to GB
                _logger.debug(f"Database size for {self.database_name}: {result['db_size_gb']} GB")
        except Exception as e:
            _logger.warning(f"Could not get database size for {self.name}: {e}")

        # Get filestore size via Docker exec
        try:
            import docker
            server = self.server_id
            if server and server.docker_api_url:
                client = docker.DockerClient(base_url=server.docker_api_url, timeout=15)
                container = client.containers.get(self.container_name)

                # Run du command inside container to get filestore size
                # Odoo filestore is typically at /var/lib/odoo/filestore/{database_name}
                filestore_path = f"/var/lib/odoo/filestore/{self.database_name}"
                exec_result = container.exec_run(
                    f"du -sb {filestore_path} 2>/dev/null | cut -f1",
                    demux=True
                )
                if exec_result.exit_code == 0 and exec_result.output[0]:
                    filestore_bytes = int(exec_result.output[0].decode().strip())
                    result['filestore_size_gb'] = round(filestore_bytes / (1024 ** 3), 3)
                    _logger.debug(f"Filestore size for {self.database_name}: {result['filestore_size_gb']} GB")
        except Exception as e:
            _logger.warning(f"Could not get filestore size for {self.name}: {e}")

        return result

    def _update_metrics_from_docker(self, docker_data):
        """Update metrics from Docker stats data."""
        self.ensure_one()

        stats = docker_data.get('stats', {})
        info = docker_data.get('info', {})
        server_info = docker_data.get('server_info', {})

        # Calculate CPU percentage
        cpu_percent = 0.0
        try:
            cpu_stats = stats.get('cpu_stats', {})
            precpu_stats = stats.get('precpu_stats', {})

            cpu_delta = cpu_stats.get('cpu_usage', {}).get('total_usage', 0) - \
                        precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
            system_delta = cpu_stats.get('system_cpu_usage', 0) - \
                           precpu_stats.get('system_cpu_usage', 0)
            ncpu = server_info.get('NCPU', 1)

            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * ncpu * 100.0
                cpu_percent = min(round(cpu_percent, 2), 100.0)
        except Exception as e:
            _logger.warning(f"Could not calculate CPU for {self.name}: {e}")

        # Get memory usage
        mem_usage = 0
        mem_limit = 0
        mem_percent = 0.0
        try:
            mem_stats = stats.get('memory_stats', {})
            mem_usage = mem_stats.get('usage', 0) - mem_stats.get('stats', {}).get('cache', 0)
            mem_limit = mem_stats.get('limit', 0)
            if mem_limit > 0:
                mem_percent = round((mem_usage / mem_limit) * 100, 2)
        except Exception as e:
            _logger.warning(f"Could not calculate memory for {self.name}: {e}")

        # Get network I/O
        net_rx = 0
        net_tx = 0
        try:
            networks = stats.get('networks', {})
            for iface, net_stats in networks.items():
                net_rx += net_stats.get('rx_bytes', 0)
                net_tx += net_stats.get('tx_bytes', 0)
        except Exception as e:
            _logger.warning(f"Could not calculate network for {self.name}: {e}")

        # Get disk I/O
        disk_read = 0
        disk_write = 0
        try:
            blkio_stats = stats.get('blkio_stats', {}).get('io_service_bytes_recursive', [])
            for entry in blkio_stats or []:
                op = entry.get('op', '').lower()
                if op == 'read':
                    disk_read += entry.get('value', 0)
                elif op == 'write':
                    disk_write += entry.get('value', 0)
        except Exception as e:
            _logger.warning(f"Could not calculate disk I/O for {self.name}: {e}")

        # Collect storage metrics (database and filestore sizes)
        storage_metrics = self._get_storage_metrics()
        db_size_gb = storage_metrics.get('db_size_gb', 0.0)
        filestore_size_gb = storage_metrics.get('filestore_size_gb', 0.0)

        # Convert GB to bytes for consistent storage in metrics
        db_size_bytes = db_size_gb * (1024 ** 3)
        filestore_size_bytes = filestore_size_gb * (1024 ** 3)

        # Build metrics dict
        metrics_data = {
            'cpu': cpu_percent,
            'memory': mem_usage,  # bytes
            'memory_percent': mem_percent,
            'disk_read': disk_read,  # bytes
            'disk_write': disk_write,  # bytes
            'network_rx': net_rx,  # bytes
            'network_tx': net_tx,  # bytes
            'database': db_size_bytes,  # bytes - database storage
            'filestore': filestore_size_bytes,  # bytes - filestore storage
        }

        # Update metrics in database (saas.usage.metric)
        self._update_metrics(metrics_data)

        # Also update instance direct fields for form display
        # These fields are defined in saas_master and shown in the Resource Usage tab
        try:
            self.sudo().write({
                'cpu_usage_percent': cpu_percent,
                'ram_usage_mb': round(mem_usage / 1048576, 2),  # bytes to MB
                'storage_db_gb': db_size_gb,
                'storage_file_gb': filestore_size_gb,
            })
            _logger.debug(
                f"Updated instance fields for {self.name}: "
                f"CPU={cpu_percent}%, RAM={round(mem_usage / 1048576, 2)}MB, "
                f"DB={db_size_gb}GB, Files={filestore_size_gb}GB"
            )
        except Exception as e:
            _logger.warning(f"Could not update instance fields for {self.name}: {e}")

    def _update_metrics(self, stats_data):
        """Update metrics from collected stats data."""
        self.ensure_one()
        UsageMetric = self.env['saas.usage.metric']
        UsageLog = self.env['saas.usage.log']
        MetricType = self.env['saas.metric.type']

        for metric_code, value in stats_data.items():
            metric_type = MetricType.search([('code', '=', metric_code)], limit=1)
            if not metric_type:
                # Skip unknown metrics silently
                continue

            # Get or create metric record
            metric = UsageMetric.search([
                ('instance_id', '=', self.id),
                ('metric_type_id', '=', metric_type.id),
            ], limit=1)

            if metric:
                # Update existing metric
                old_value = metric.current_value
                metric.write({
                    'current_value': value,
                    'last_updated': fields.Datetime.now(),
                })
                _logger.debug(f"Updated metric {metric_code} for {self.name}: {old_value} -> {value}")
            else:
                # Get limit from plan
                limit_value = self._get_metric_limit(metric_code)
                metric = UsageMetric.create({
                    'instance_id': self.id,
                    'metric_type_id': metric_type.id,
                    'current_value': value,
                    'limit_value': limit_value,
                    'last_updated': fields.Datetime.now(),
                })
                _logger.info(f"Created metric {metric_code} for {self.name}: {value}")

            # Log usage for history (key metrics including storage)
            if metric_code in ('cpu', 'memory', 'disk', 'database', 'filestore'):
                try:
                    UsageLog.create({
                        'instance_id': self.id,
                        'metric_type_id': metric_type.id,
                        'value': value,
                    })
                except Exception as e:
                    _logger.warning(f"Could not log usage for {metric_code}: {e}")

    def _get_metric_limit(self, metric_code):
        """Get the limit for a metric based on the instance's plan."""
        self.ensure_one()
        if not self.plan_id:
            return 0

        plan = self.plan_id

        # Map metric codes to plan fields (using actual field names)
        # Storage limits are in GB on the plan, convert to bytes for metrics
        limit_map = {
            'disk': (getattr(plan, 'storage_db_limit_gb', 0) or 0) * 1073741824,  # Convert GB to bytes
            'database': (getattr(plan, 'storage_db_limit_gb', 0) or 0) * 1073741824,  # DB storage in bytes
            'filestore': (getattr(plan, 'storage_file_limit_gb', 0) or 0) * 1073741824,  # Filestore in bytes
            'users': getattr(plan, 'user_limit', 0) or 0,
            'memory': (getattr(plan, 'ram_limit_mb', 0) or 0) * 1048576,  # Convert MB to bytes
            'memory_percent': 100.0,  # Percentage limit is always 100%
            'cpu': 100.0,  # CPU percent limit
            'bandwidth': 0,  # No limit by default, can be plan-specific
            'api_calls': 0,  # No limit by default
        }

        return limit_map.get(metric_code, 0)

    @api.model
    def cron_collect_all_metrics(self):
        """Cron job to collect metrics for all running instances."""
        running_instances = self.search([('state', '=', 'running')])
        _logger.info(f"Starting metric collection for {len(running_instances)} instances")

        for instance in running_instances:
            try:
                instance.collect_metrics()
            except Exception as e:
                _logger.error(f"Error collecting metrics for {instance.name}: {e}")

        return True
