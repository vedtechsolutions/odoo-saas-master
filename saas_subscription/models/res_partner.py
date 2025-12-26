# -*- coding: utf-8 -*-
"""
Extend res.partner for SaaS subscription tracking.

Adds trial tracking and subscription relationship fields.
"""

from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.states import SubscriptionState


class ResPartner(models.Model):
    """Extend partner with SaaS subscription fields."""

    _inherit = 'res.partner'

    # Trial tracking
    has_used_trial = fields.Boolean(
        string='Has Used Trial',
        default=False,
        help='Whether this customer has already used a trial',
    )
    trial_start_date = fields.Date(
        string='Trial Start Date',
        help='When the customer started their trial',
    )

    # Subscription relationship
    subscription_ids = fields.One2many(
        ModelNames.SUBSCRIPTION,
        'partner_id',
        string='Subscriptions',
    )
    subscription_count = fields.Integer(
        string='Subscription Count',
        compute='_compute_subscription_count',
    )
    active_subscription_count = fields.Integer(
        string='Active Subscriptions',
        compute='_compute_subscription_count',
    )

    # Instance relationship (via subscription)
    saas_instance_ids = fields.One2many(
        ModelNames.INSTANCE,
        'partner_id',
        string='SaaS Instances',
    )
    instance_count = fields.Integer(
        string='Instances',
        compute='_compute_instance_count',
    )

    # Computed status
    is_saas_customer = fields.Boolean(
        string='Is SaaS Customer',
        compute='_compute_is_saas_customer',
        store=True,
    )
    current_plan_id = fields.Many2one(
        ModelNames.PLAN,
        string='Current Plan',
        compute='_compute_current_plan',
    )

    def _compute_subscription_count(self):
        """Count subscriptions for this partner."""
        Subscription = self.env[ModelNames.SUBSCRIPTION]
        for partner in self:
            subs = Subscription.search([('partner_id', '=', partner.id)])
            partner.subscription_count = len(subs)
            partner.active_subscription_count = len(subs.filtered(
                lambda s: s.state in [SubscriptionState.TRIAL, SubscriptionState.ACTIVE]
            ))

    def _compute_instance_count(self):
        """Count instances for this partner."""
        for partner in self:
            partner.instance_count = len(partner.saas_instance_ids)

    @api.depends('subscription_ids', 'subscription_ids.state')
    def _compute_is_saas_customer(self):
        """Check if partner has any SaaS subscription."""
        for partner in self:
            partner.is_saas_customer = bool(partner.subscription_ids)

    def _compute_current_plan(self):
        """Get the current active subscription plan."""
        for partner in self:
            active_sub = partner.subscription_ids.filtered(
                lambda s: s.state in [SubscriptionState.TRIAL, SubscriptionState.ACTIVE]
            )[:1]
            partner.current_plan_id = active_sub.plan_id if active_sub else False

    def action_view_subscriptions(self):
        """Open subscriptions for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Subscriptions - {self.name}',
            'res_model': ModelNames.SUBSCRIPTION,
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_instances(self):
        """Open SaaS instances for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Instances - {self.name}',
            'res_model': ModelNames.INSTANCE,
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_start_trial(self):
        """Open wizard to start a trial for this partner."""
        self.ensure_one()
        # Get trial plan
        Plan = self.env[ModelNames.PLAN]
        trial_plan = Plan.get_trial_plan()

        if not trial_plan:
            from odoo.exceptions import UserError
            raise UserError("No trial plan configured.")

        if self.has_used_trial:
            from odoo.exceptions import UserError
            raise UserError("This customer has already used their trial.")

        # Create subscription in draft
        Subscription = self.env[ModelNames.SUBSCRIPTION]
        subscription = Subscription.create({
            'partner_id': self.id,
            'plan_id': trial_plan.id,
            'is_trial': True,
        })

        # Start the trial
        subscription.action_start_trial()

        return {
            'type': 'ir.actions.act_window',
            'name': 'New Trial Subscription',
            'res_model': ModelNames.SUBSCRIPTION,
            'view_mode': 'form',
            'res_id': subscription.id,
        }
