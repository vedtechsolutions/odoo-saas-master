# -*- coding: utf-8 -*-
"""
Extend saas.instance with subscription relationship.

This module adds the reverse relationship from instance to subscriptions.
"""

from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames


class SaasInstanceSubscription(models.Model):
    """Extend SaaS Instance with subscription relationship."""

    _inherit = ModelNames.INSTANCE

    # Subscription relationships
    subscription_ids = fields.One2many(
        ModelNames.SUBSCRIPTION,
        'instance_id',
        string='Subscriptions',
    )
    subscription_id = fields.Many2one(
        ModelNames.SUBSCRIPTION,
        string='Active Subscription',
        compute='_compute_subscription_id',
        store=True,
    )
    subscription_state = fields.Selection(
        related='subscription_id.state',
        string='Subscription State',
        store=True,
    )
    subscription_reference = fields.Char(
        related='subscription_id.reference',
        string='Subscription Ref',
    )

    @api.depends('subscription_ids', 'subscription_ids.state')
    def _compute_subscription_id(self):
        """Get the active subscription for this instance."""
        active_states = ['trial', 'active', 'past_due']
        for instance in self:
            active_sub = instance.subscription_ids.filtered(
                lambda s: s.state in active_states
            )[:1]
            instance.subscription_id = active_sub.id if active_sub else False
