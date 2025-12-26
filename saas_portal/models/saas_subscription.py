# -*- coding: utf-8 -*-
"""
Extend saas.subscription for portal access.
"""

from odoo import models, fields, api


class SaasSubscriptionPortal(models.Model):
    """Extend subscription with portal access methods."""

    _inherit = 'saas.subscription'

    def _compute_access_url(self):
        """Compute portal access URL."""
        super()._compute_access_url()
        for subscription in self:
            subscription.access_url = f'/my/subscriptions/{subscription.id}'

    def get_portal_url(self, suffix=None, report_type=None, download=None, query_string=None):
        """Get the portal URL for this subscription."""
        self.ensure_one()
        url = f'/my/subscriptions/{self.id}'
        if suffix:
            url += suffix
        if query_string:
            url += '?' + query_string
        return url
