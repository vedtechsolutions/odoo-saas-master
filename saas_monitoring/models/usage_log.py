# -*- coding: utf-8 -*-
"""
Usage Log model - stores historical metric values.
"""

from odoo import models, fields, api
from datetime import timedelta


class UsageLog(models.Model):
    """Historical log of metric values."""
    _name = 'saas.usage.log'
    _description = 'Usage Log Entry'
    _order = 'timestamp desc'
    _rec_name = 'display_name'

    # Odoo 19 index syntax for efficient time-series queries
    _instance_timestamp_idx = models.Index('(instance_id, timestamp)')
    _metric_timestamp_idx = models.Index('(metric_type_id, timestamp)')

    instance_id = fields.Many2one(
        'saas.instance',
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    metric_type_id = fields.Many2one(
        'saas.metric.type',
        string='Metric Type',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # Values
    value = fields.Float(string='Value', required=True)
    limit_value = fields.Float(string='Limit at Time')
    usage_percent = fields.Float(
        string='Usage %',
        compute='_compute_usage_percent',
        store=True,
    )

    # Timestamp
    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    date = fields.Date(
        string='Date',
        compute='_compute_date',
        store=True,
        index=True,
    )

    # Display
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    # Related fields
    instance_name = fields.Char(
        related='instance_id.name',
        string='Instance Name',
        store=True,
    )
    metric_code = fields.Char(
        related='metric_type_id.code',
        string='Metric Code',
        store=True,
    )
    metric_name = fields.Char(
        related='metric_type_id.name',
        string='Metric Name',
    )
    unit = fields.Char(related='metric_type_id.unit', string='Unit')

    @api.depends('value', 'limit_value')
    def _compute_usage_percent(self):
        for record in self:
            if record.limit_value > 0:
                record.usage_percent = (record.value / record.limit_value) * 100
            else:
                record.usage_percent = 0.0

    @api.depends('timestamp')
    def _compute_date(self):
        for record in self:
            record.date = record.timestamp.date() if record.timestamp else False

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.instance_name} - {record.metric_name} @ {record.timestamp}"

    @api.model
    def cleanup_old_logs(self):
        """
        Remove logs older than retention period. Called by cron.

        Optimized to use batch SQL DELETE instead of individual ORM deletes
        for better performance on large datasets.
        """
        import logging
        _logger = logging.getLogger(__name__)

        # Get all metric types with retention settings
        metric_types = self.env['saas.metric.type'].search_read(
            [], ['id', 'name', 'retention_days']
        )

        total_deleted = 0
        for mt in metric_types:
            retention_days = mt['retention_days'] or 90
            cutoff_date = fields.Datetime.now() - timedelta(days=retention_days)

            # Use SQL for efficient bulk delete
            self.env.cr.execute("""
                DELETE FROM saas_usage_log
                WHERE metric_type_id = %s AND timestamp < %s
            """, (mt['id'], cutoff_date))

            deleted_count = self.env.cr.rowcount
            if deleted_count > 0:
                total_deleted += deleted_count
                _logger.info(
                    f"Cleaned up {deleted_count} old {mt['name']} logs "
                    f"older than {retention_days} days"
                )

        # Invalidate cache after bulk delete
        self.invalidate_model()

        if total_deleted > 0:
            _logger.info(f"Total logs cleaned up: {total_deleted}")

        return True

    @api.model
    def get_usage_stats(self, instance_id, metric_code, days=30):
        """Get usage statistics for an instance metric over a period."""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)

        logs = self.search([
            ('instance_id', '=', instance_id),
            ('metric_code', '=', metric_code),
            ('timestamp', '>=', cutoff_date),
        ], order='timestamp asc')

        if not logs:
            return {}

        values = logs.mapped('value')

        return {
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'current': values[-1] if values else 0,
            'count': len(values),
            'trend': 'up' if len(values) > 1 and values[-1] > values[0] else 'down',
        }
