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
        """Remove logs older than retention period. Called by cron."""
        metric_types = self.env['saas.metric.type'].search([])

        for metric_type in metric_types:
            retention_days = metric_type.retention_days or 90
            cutoff_date = fields.Datetime.now() - timedelta(days=retention_days)

            old_logs = self.search([
                ('metric_type_id', '=', metric_type.id),
                ('timestamp', '<', cutoff_date),
            ])

            if old_logs:
                count = len(old_logs)
                old_logs.unlink()
                # Log cleanup
                self.env['ir.logging'].sudo().create({
                    'name': 'saas.usage.log',
                    'type': 'server',
                    'level': 'INFO',
                    'message': f"Cleaned up {count} old {metric_type.name} logs older than {retention_days} days",
                    'func': 'cleanup_old_logs',
                    'path': 'saas_monitoring',
                    'line': '0',
                })

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
