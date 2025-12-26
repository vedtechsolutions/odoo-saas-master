# -*- coding: utf-8 -*-
"""
SaaS Support Access Log model.

Tracks all support/admin access to customer instances for audit purposes.
"""

import logging
from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames

_logger = logging.getLogger(__name__)


class SaasSupportAccessLog(models.Model):
    """Log of support access to customer instances."""

    _name = 'saas.support.access.log'
    _description = 'Support Access Log'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # Relations
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='Instance',
        required=True,
        ondelete='cascade',
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Support User',
        required=True,
        ondelete='restrict',
        default=lambda self: self.env.uid,
        index=True,
    )

    # Access details
    access_type = fields.Selection(
        selection=[
            ('impersonate', 'Impersonate Login'),
            ('view_logs', 'View Logs'),
            ('backup_download', 'Backup Download'),
            ('database_access', 'Database Access'),
            ('file_access', 'File Access'),
            ('terminal', 'Terminal Access'),
            ('other', 'Other'),
        ],
        string='Access Type',
        required=True,
        default='impersonate',
    )
    ip_address = fields.Char(
        string='IP Address',
        help='IP address of the support user',
    )
    user_agent = fields.Char(
        string='User Agent',
        help='Browser/client user agent',
    )

    # Timestamps
    access_date = fields.Datetime(
        string='Access Date',
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    access_time = fields.Datetime(
        string='Access Time',
        default=fields.Datetime.now,
        help='Alias for access_date for compatibility',
    )
    session_end_time = fields.Datetime(
        string='Session End Time',
        help='When the support session ended',
    )
    session_duration_minutes = fields.Integer(
        string='Session Duration (min)',
        help='Actual duration of the support session',
    )
    session_end_reason = fields.Selection([
        ('ended', 'Logged Out'),
        ('expired', 'Timed Out'),
        ('unknown', 'Unknown'),
    ], string='End Reason', default='unknown')
    duration_minutes = fields.Integer(
        string='Duration (min)',
        help='Estimated duration of the support session',
    )

    # Link to access request
    accessed_by_id = fields.Many2one(
        'res.users',
        string='Accessed By',
        help='User who performed the support access (alias for user_id)',
        related='user_id',
        store=True,
    )

    # Notes
    reason = fields.Text(
        string='Reason',
        help='Reason for the support access',
    )
    notes = fields.Text(
        string='Notes',
        help='Additional notes about the support session',
    )

    # Related fields for display
    instance_subdomain = fields.Char(
        related='instance_id.subdomain',
        string='Subdomain',
        store=True,
    )
    customer_id = fields.Many2one(
        related='instance_id.partner_id',
        string='Customer',
        store=True,
    )
    user_name = fields.Char(
        related='user_id.name',
        string='User Name',
        store=True,
    )

    # Computed display name
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('instance_subdomain', 'user_id', 'access_date')
    def _compute_display_name(self):
        for record in self:
            date_str = record.access_date.strftime('%Y-%m-%d %H:%M') if record.access_date else ''
            record.display_name = f"{record.instance_subdomain} - {record.user_id.name} ({date_str})"

    @api.model_create_multi
    def create(self, vals_list):
        """Override to capture user agent on create."""
        for vals in vals_list:
            if not vals.get('user_agent'):
                vals['user_agent'] = self._get_user_agent()
        return super().create(vals_list)

    def _get_user_agent(self):
        """Get the user agent from the request."""
        try:
            from odoo.http import request
            if request and hasattr(request, 'httprequest'):
                return request.httprequest.user_agent.string[:255]
        except Exception as e:
            _logger.debug(f"Could not get user agent from request: {e}")
        return None
