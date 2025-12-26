# -*- coding: utf-8 -*-
"""
Metric Type model - defines the types of metrics that can be tracked.
"""

from odoo import models, fields, api


class MetricType(models.Model):
    """Definition of metric types for monitoring."""
    _name = 'saas.metric.type'
    _description = 'Metric Type'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True, index=True)
    description = fields.Text(string='Description', translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    # Unit and formatting
    unit = fields.Char(string='Unit', help='e.g., %, MB, GB, count')
    unit_type = fields.Selection([
        ('percentage', 'Percentage'),
        ('bytes', 'Bytes'),
        ('count', 'Count'),
        ('time', 'Time (seconds)'),
        ('currency', 'Currency'),
    ], string='Unit Type', default='count')

    # Thresholds
    warning_threshold = fields.Float(
        string='Warning Threshold',
        default=80.0,
        help='Percentage of limit at which to trigger warning'
    )
    critical_threshold = fields.Float(
        string='Critical Threshold',
        default=90.0,
        help='Percentage of limit at which to trigger critical alert'
    )

    # Collection settings
    collection_method = fields.Selection([
        ('api', 'API Call'),
        ('docker', 'Docker Stats'),
        ('database', 'Database Query'),
        ('manual', 'Manual Entry'),
    ], string='Collection Method', default='api')

    collection_interval = fields.Integer(
        string='Collection Interval (minutes)',
        default=60,
        help='How often to collect this metric'
    )

    # Retention
    retention_days = fields.Integer(
        string='Retention Days',
        default=90,
        help='Number of days to keep historical data'
    )

    # SQL Constraint using Odoo 19 syntax
    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Metric type code must be unique!'
    )

    # Computed display name (replaces deprecated name_get in Odoo 19)
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    @api.depends('name', 'unit')
    def _compute_display_name(self):
        """Compute display name with unit suffix."""
        for record in self:
            if record.unit:
                record.display_name = f"{record.name} ({record.unit})"
            else:
                record.display_name = record.name
