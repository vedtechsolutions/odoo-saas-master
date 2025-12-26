# -*- coding: utf-8 -*-
"""
Extend saas.ticket for portal access.
"""

from odoo import models, fields, api


class SaasTicketPortal(models.Model):
    """Extend ticket with portal access methods."""

    _inherit = 'saas.ticket'

    def _compute_access_url(self):
        """Compute portal access URL."""
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = f'/my/tickets/{ticket.id}'

    def get_portal_url(self, suffix=None, report_type=None, download=None, query_string=None):
        """Get the portal URL for this ticket."""
        self.ensure_one()
        url = f'/my/tickets/{self.id}'
        if suffix:
            url += suffix
        if query_string:
            url += '?' + query_string
        return url

    def portal_add_message(self, message_body):
        """Add a message from the portal."""
        self.ensure_one()
        return self.env['saas.ticket.message'].sudo().create({
            'ticket_id': self.id,
            'body': message_body,
            'author_id': self.env.user.partner_id.id,
            'is_internal': False,
        })
