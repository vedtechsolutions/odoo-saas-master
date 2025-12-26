# -*- coding: utf-8 -*-
"""
Extend saas.instance for portal access.
"""

from odoo import models, fields, api


class SaasInstancePortal(models.Model):
    """Extend instance with portal access methods."""

    _inherit = 'saas.instance'

    def _compute_access_url(self):
        """Compute portal access URL."""
        super()._compute_access_url()
        for instance in self:
            instance.access_url = f'/my/instances/{instance.id}'

    def get_portal_url(self, suffix=None, report_type=None, download=None, query_string=None):
        """Get the portal URL for this instance."""
        self.ensure_one()
        url = f'/my/instances/{self.id}'
        if suffix:
            url += suffix
        if query_string:
            url += '?' + query_string
        return url

    def action_portal_start(self):
        """Start instance from portal (if allowed)."""
        self.ensure_one()
        if self.state == 'stopped':
            self.action_start()
        return True

    def action_portal_stop(self):
        """Stop instance from portal (if allowed)."""
        self.ensure_one()
        if self.state == 'running':
            self.action_stop()
        return True

    def action_portal_restart(self):
        """Restart instance from portal (if allowed)."""
        self.ensure_one()
        if self.state == 'running':
            self.action_restart()
        return True
