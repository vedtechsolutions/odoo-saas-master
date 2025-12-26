# -*- coding: utf-8 -*-
"""
Usage Metric model - stores current metric values for instances.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError

from odoo.addons.saas_core.constants.fields import ModelNames


class UsageMetric(models.Model):
    """Current metric values for an instance."""
    _name = 'saas.usage.metric'
    _description = 'Instance Usage Metric'
    _order = 'instance_id, metric_type_id'
    _rec_name = 'display_name'

    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    metric_type_id = fields.Many2one(
        ModelNames.METRIC_TYPE,
        string='Metric Type',
        required=True,
        ondelete='restrict',
        index=True,
    )

    # Current value
    current_value = fields.Float(string='Current Value', default=0.0)
    limit_value = fields.Float(string='Limit', default=0.0)
    usage_percent = fields.Float(
        string='Usage %',
        compute='_compute_usage_percent',
        store=True,
    )

    # Status
    status = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('exceeded', 'Exceeded'),
    ], string='Status', compute='_compute_status', store=True)

    # Timestamps
    last_updated = fields.Datetime(
        string='Last Updated',
        default=fields.Datetime.now,
    )
    last_collected = fields.Datetime(string='Last Collected')

    # Display
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    formatted_value = fields.Char(
        string='Formatted Value',
        compute='_compute_formatted_value',
    )

    # Related fields for easy access
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
    unit = fields.Char(related='metric_type_id.unit', string='Unit')

    # SQL Constraint
    _instance_metric_unique = models.Constraint(
        'UNIQUE(instance_id, metric_type_id)',
        'Each instance can only have one value per metric type!'
    )

    @api.depends('instance_id.name', 'metric_type_id.name')
    def _compute_display_name(self):
        for record in self:
            if record.instance_id and record.metric_type_id:
                record.display_name = f"{record.instance_id.name} - {record.metric_type_id.name}"
            else:
                record.display_name = "New Metric"

    @api.depends('current_value', 'limit_value')
    def _compute_usage_percent(self):
        for record in self:
            if record.limit_value > 0:
                record.usage_percent = (record.current_value / record.limit_value) * 100
            else:
                record.usage_percent = 0.0

    @api.depends('usage_percent', 'metric_type_id.warning_threshold', 'metric_type_id.critical_threshold')
    def _compute_status(self):
        for record in self:
            if not record.metric_type_id or record.limit_value <= 0:
                record.status = 'ok'
                continue

            warning = record.metric_type_id.warning_threshold or 80.0
            critical = record.metric_type_id.critical_threshold or 90.0

            if record.usage_percent >= 100:
                record.status = 'exceeded'
            elif record.usage_percent >= critical:
                record.status = 'critical'
            elif record.usage_percent >= warning:
                record.status = 'warning'
            else:
                record.status = 'ok'

    @api.depends('current_value', 'metric_type_id.unit_type', 'metric_type_id.unit')
    def _compute_formatted_value(self):
        for record in self:
            value = record.current_value
            unit_type = record.metric_type_id.unit_type if record.metric_type_id else 'count'
            unit = record.metric_type_id.unit if record.metric_type_id else ''

            if unit_type == 'bytes':
                # Convert to human-readable
                if value >= 1073741824:  # GB
                    record.formatted_value = f"{value / 1073741824:.2f} GB"
                elif value >= 1048576:  # MB
                    record.formatted_value = f"{value / 1048576:.2f} MB"
                elif value >= 1024:  # KB
                    record.formatted_value = f"{value / 1024:.2f} KB"
                else:
                    record.formatted_value = f"{value:.0f} B"
            elif unit_type == 'percentage':
                record.formatted_value = f"{value:.1f}%"
            elif unit_type == 'time':
                if value >= 3600:
                    record.formatted_value = f"{value / 3600:.1f} hours"
                elif value >= 60:
                    record.formatted_value = f"{value / 60:.1f} min"
                else:
                    record.formatted_value = f"{value:.0f} sec"
            else:
                record.formatted_value = f"{value:.0f} {unit}".strip()

    def update_value(self, new_value):
        """Update metric value and log the change."""
        self.ensure_one()
        old_value = self.current_value
        old_status = self.status

        self.write({
            'current_value': new_value,
            'last_updated': fields.Datetime.now(),
            'last_collected': fields.Datetime.now(),
        })

        # Create log entry
        self.env[ModelNames.USAGE_LOG].create({
            'instance_id': self.instance_id.id,
            'metric_type_id': self.metric_type_id.id,
            'value': new_value,
            'limit_value': self.limit_value,
        })

        # Check if alert needed
        new_status = self.status
        if new_status != old_status and new_status in ['warning', 'critical', 'exceeded']:
            self._create_alert(old_status, new_status)

        return True

    def _create_alert(self, old_status, new_status):
        """Create alert when status changes."""
        self.ensure_one()
        severity_map = {
            'warning': 'warning',
            'critical': 'critical',
            'exceeded': 'critical',
        }

        self.env[ModelNames.ALERT].create({
            'instance_id': self.instance_id.id,
            'metric_type_id': self.metric_type_id.id,
            'alert_type': 'threshold',
            'severity': severity_map.get(new_status, 'info'),
            'title': f"{self.metric_type_id.name} {new_status.upper()}",
            'message': f"Instance {self.instance_id.name}: {self.metric_type_id.name} is at {self.usage_percent:.1f}% ({self.formatted_value} of {self.limit_value} {self.unit})",
            'current_value': self.current_value,
            'threshold_value': self.limit_value,
        })
