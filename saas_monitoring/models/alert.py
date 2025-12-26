# -*- coding: utf-8 -*-
"""
Alert model - monitoring alerts for instances.
"""

from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames


class MonitoringAlert(models.Model):
    """Monitoring alerts for SaaS instances."""
    _name = 'saas.alert'
    _description = 'Monitoring Alert'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'title'

    # Basic info
    title = fields.Char(string='Title', required=True)
    message = fields.Text(string='Message')

    # Relations
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        ondelete='cascade',
        index=True,
    )
    metric_type_id = fields.Many2one(
        ModelNames.METRIC_TYPE,
        string='Metric Type',
        ondelete='set null',
    )
    server_id = fields.Many2one(
        ModelNames.SERVER,
        string='Server',
        ondelete='cascade',
    )

    # Alert classification
    alert_type = fields.Selection([
        ('threshold', 'Threshold Exceeded'),
        ('health', 'Health Check Failed'),
        ('connectivity', 'Connectivity Issue'),
        ('performance', 'Performance Degradation'),
        ('security', 'Security Alert'),
        ('billing', 'Billing Alert'),
        ('system', 'System Alert'),
    ], string='Alert Type', required=True, default='threshold')

    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ], string='Severity', required=True, default='warning', tracking=True)

    # Status
    state = fields.Selection([
        ('new', 'New'),
        ('acknowledged', 'Acknowledged'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ], string='State', default='new', required=True, tracking=True)

    # Values
    current_value = fields.Float(string='Current Value')
    threshold_value = fields.Float(string='Threshold Value')

    # Assignment
    assigned_to = fields.Many2one(
        'res.users',
        string='Assigned To',
        tracking=True,
    )

    # Timestamps
    acknowledged_at = fields.Datetime(string='Acknowledged At')
    acknowledged_by = fields.Many2one('res.users', string='Acknowledged By')
    resolved_at = fields.Datetime(string='Resolved At')
    resolved_by = fields.Many2one('res.users', string='Resolved By')

    # Resolution
    resolution_notes = fields.Text(string='Resolution Notes')

    # Related fields
    instance_name = fields.Char(
        related='instance_id.name',
        string='Instance Name',
        store=True,
    )
    partner_id = fields.Many2one(
        related='instance_id.partner_id',
        string='Customer',
        store=True,
    )

    # Computed
    is_active = fields.Boolean(
        string='Is Active',
        compute='_compute_is_active',
        store=True,
    )
    age_hours = fields.Float(
        string='Age (hours)',
        compute='_compute_age',
    )

    @api.depends('state')
    def _compute_is_active(self):
        for record in self:
            record.is_active = record.state in ['new', 'acknowledged', 'in_progress']

    def _compute_age(self):
        now = fields.Datetime.now()
        for record in self:
            if record.create_date:
                delta = now - record.create_date
                record.age_hours = delta.total_seconds() / 3600
            else:
                record.age_hours = 0

    def action_acknowledge(self):
        """Acknowledge the alert."""
        self.write({
            'state': 'acknowledged',
            'acknowledged_at': fields.Datetime.now(),
            'acknowledged_by': self.env.user.id,
        })

    def action_start_progress(self):
        """Start working on the alert."""
        self.write({
            'state': 'in_progress',
            'assigned_to': self.env.user.id,
        })

    def action_resolve(self):
        """Mark alert as resolved."""
        self.write({
            'state': 'resolved',
            'resolved_at': fields.Datetime.now(),
            'resolved_by': self.env.user.id,
        })

    def action_dismiss(self):
        """Dismiss the alert."""
        self.write({'state': 'dismissed'})

    def action_reopen(self):
        """Reopen a resolved/dismissed alert."""
        self.write({
            'state': 'new',
            'resolved_at': False,
            'resolved_by': False,
        })

    @api.model
    def create_alert(self, instance_id, alert_type, severity, title, message, **kwargs):
        """Helper method to create alerts programmatically."""
        vals = {
            'instance_id': instance_id,
            'alert_type': alert_type,
            'severity': severity,
            'title': title,
            'message': message,
        }
        vals.update(kwargs)
        return self.create(vals)

    @api.model
    def get_active_alerts_count(self, instance_id=None, server_id=None):
        """Get count of active alerts."""
        domain = [('is_active', '=', True)]
        if instance_id:
            domain.append(('instance_id', '=', instance_id))
        if server_id:
            domain.append(('server_id', '=', server_id))
        return self.search_count(domain)

    @api.model
    def cleanup_old_alerts(self, days=90):
        """Remove old resolved/dismissed alerts. Called by cron."""
        from datetime import timedelta
        cutoff_date = fields.Datetime.now() - timedelta(days=days)

        old_alerts = self.search([
            ('state', 'in', ['resolved', 'dismissed']),
            ('write_date', '<', cutoff_date),
        ])

        if old_alerts:
            count = len(old_alerts)
            old_alerts.unlink()
            return count
        return 0
