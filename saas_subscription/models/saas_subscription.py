# -*- coding: utf-8 -*-
"""
SaaS Subscription model.

Manages subscription lifecycle, billing, and customer relationship.
"""

import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from odoo.addons.saas_core.constants.fields import ModelNames, FieldNames, FieldLabels
from odoo.addons.saas_core.constants.states import SubscriptionState, InstanceState
from odoo.addons.saas_core.constants.config import PlanConfig, PaymentConfig

_logger = logging.getLogger(__name__)


class SaasSubscription(models.Model):
    """SaaS subscription linking customers to instances and plans."""

    _name = ModelNames.SUBSCRIPTION
    _description = 'SaaS Subscription'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'saas.audit.mixin']

    # Odoo 19 constraint syntax
    _subscription_unique = models.Constraint(
        'UNIQUE(partner_id, instance_id)',
        'A customer can only have one subscription per instance!'
    )

    # Basic fields
    name = fields.Char(
        string=FieldLabels.NAME,
        compute='_compute_name',
        store=True,
        readonly=False,
    )
    reference = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New',
        help='Unique subscription reference number',
    )

    # State
    state = fields.Selection(
        selection=SubscriptionState.get_selection(),
        string=FieldLabels.STATE,
        default=SubscriptionState.DRAFT,
        required=True,
        tracking=True,
        index=True,
    )

    # Relations
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        ondelete='restrict',
        domain=[('is_company', '=', True)],
        index=True,
    )
    plan_id = fields.Many2one(
        ModelNames.PLAN,
        string=FieldLabels.PLAN,
        required=True,
        tracking=True,
        ondelete='restrict',
    )
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string=FieldLabels.INSTANCE,
        tracking=True,
        ondelete='set null',
        help='Associated SaaS instance',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        ondelete='set null',
        help='Original sale order that created this subscription',
    )

    # Billing configuration
    billing_cycle = fields.Selection(
        selection=[
            ('monthly', 'Monthly'),
            ('yearly', 'Yearly'),
        ],
        string='Billing Cycle',
        default='monthly',
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    recurring_price = fields.Float(
        string='Recurring Price',
        digits=(10, 2),
        compute='_compute_recurring_price',
        store=True,
        tracking=True,
    )

    # Trial management
    is_trial = fields.Boolean(
        string='Is Trial',
        default=False,
        tracking=True,
    )
    trial_start_date = fields.Date(
        string='Trial Start Date',
    )
    trial_end_date = fields.Date(
        string='Trial End Date',
        compute='_compute_trial_end_date',
        store=True,
    )

    # Subscription dates
    start_date = fields.Date(
        string='Start Date',
        tracking=True,
        help='When the paid subscription started',
    )
    end_date = fields.Date(
        string='End Date',
        tracking=True,
        help='When the subscription ends (for fixed-term)',
    )
    next_billing_date = fields.Date(
        string='Next Billing Date',
        tracking=True,
        index=True,
        help='Date of next invoice generation',
    )
    last_billing_date = fields.Date(
        string='Last Billing Date',
        readonly=True,
    )
    cancellation_date = fields.Date(
        string='Cancellation Date',
        readonly=True,
    )

    # Payment tracking
    payment_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('paid', 'Paid'),
            ('overdue', 'Overdue'),
            ('failed', 'Failed'),
        ],
        string='Payment Status',
        default='pending',
        tracking=True,
    )
    failed_payment_count = fields.Integer(
        string='Failed Payments',
        default=0,
        readonly=True,
    )
    last_payment_date = fields.Datetime(
        string='Last Payment',
        readonly=True,
    )

    # Computed/related fields
    instance_state = fields.Selection(
        related='instance_id.state',
        string='Instance Status',
        readonly=True,
    )
    instance_subdomain = fields.Char(
        related='instance_id.subdomain',
        string='Subdomain',
        readonly=True,
    )

    # Days tracking
    days_until_billing = fields.Integer(
        string='Days Until Billing',
        compute='_compute_days_until_billing',
    )
    days_in_trial = fields.Integer(
        string='Days in Trial',
        compute='_compute_days_in_trial',
    )
    trial_days_remaining = fields.Integer(
        string='Trial Days Remaining',
        compute='_compute_trial_days_remaining',
    )

    # Notes
    notes = fields.Text(
        string='Internal Notes',
    )
    cancellation_reason = fields.Text(
        string='Cancellation Reason',
    )

    @api.depends('partner_id', 'plan_id', 'reference')
    def _compute_name(self):
        """Generate subscription name."""
        for sub in self:
            if sub.partner_id and sub.plan_id:
                sub.name = f"{sub.partner_id.name} - {sub.plan_id.name}"
            elif sub.reference and sub.reference != 'New':
                sub.name = sub.reference
            else:
                sub.name = 'New Subscription'

    @api.depends('plan_id', 'billing_cycle')
    def _compute_recurring_price(self):
        """Calculate recurring price based on plan and billing cycle."""
        for sub in self:
            if sub.plan_id:
                if sub.billing_cycle == 'yearly':
                    sub.recurring_price = sub.plan_id.yearly_price
                else:
                    sub.recurring_price = sub.plan_id.monthly_price
            else:
                sub.recurring_price = 0.0

    @api.depends('is_trial', 'trial_start_date')
    def _compute_trial_end_date(self):
        """Calculate trial end date."""
        for sub in self:
            if sub.is_trial and sub.trial_start_date:
                sub.trial_end_date = sub.trial_start_date + timedelta(
                    days=PlanConfig.TRIAL_DURATION_DAYS
                )
            else:
                sub.trial_end_date = False

    def _compute_days_until_billing(self):
        """Calculate days until next billing."""
        today = fields.Date.context_today(self)
        for sub in self:
            if sub.next_billing_date:
                delta = sub.next_billing_date - today
                sub.days_until_billing = delta.days
            else:
                sub.days_until_billing = 0

    def _compute_days_in_trial(self):
        """Calculate days elapsed in trial."""
        today = fields.Date.context_today(self)
        for sub in self:
            if sub.is_trial and sub.trial_start_date:
                delta = today - sub.trial_start_date
                sub.days_in_trial = max(0, delta.days)
            else:
                sub.days_in_trial = 0

    def _compute_trial_days_remaining(self):
        """Calculate remaining trial days."""
        today = fields.Date.context_today(self)
        for sub in self:
            if sub.is_trial and sub.trial_end_date:
                delta = sub.trial_end_date - today
                sub.trial_days_remaining = max(0, delta.days)
            else:
                sub.trial_days_remaining = 0

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference."""
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'saas.subscription'
                ) or 'New'
        return super().create(vals_list)

    def action_start_trial(self):
        """Start a trial subscription."""
        self.ensure_one()
        if self.state != SubscriptionState.DRAFT:
            raise UserError(_("Can only start trial from draft state."))

        # Check if customer already had a trial
        if self.partner_id.has_used_trial:
            raise UserError(_("This customer has already used their trial."))

        today = fields.Date.context_today(self)
        self.write({
            'state': SubscriptionState.TRIAL,
            'is_trial': True,
            'trial_start_date': today,
        })

        # Mark partner as having used trial
        self.partner_id.write({
            'has_used_trial': True,
            'trial_start_date': today,
        })

        # Provision instance if not exists
        if not self.instance_id:
            self._create_trial_instance()

        self.message_post(body="Trial started")
        return True

    def _create_trial_instance(self):
        """Create a trial instance for this subscription."""
        Instance = self.env[ModelNames.INSTANCE]
        Server = self.env[ModelNames.SERVER]

        # Find available server
        server = Server.get_available_server()
        if not server:
            raise UserError(_("No available servers for provisioning."))

        # Generate subdomain from company name
        subdomain = self.partner_id.name.lower().replace(' ', '')
        subdomain = ''.join(c for c in subdomain if c.isalnum())[:20]

        # Ensure unique
        base_subdomain = subdomain
        counter = 1
        while Instance.search([('subdomain', '=', subdomain)], limit=1):
            subdomain = f"{base_subdomain}{counter}"
            counter += 1

        # Create instance
        instance = Instance.create({
            'name': f"{self.partner_id.name} Instance",
            'subdomain': subdomain,
            'partner_id': self.partner_id.id,
            'plan_id': self.plan_id.id,
            'server_id': server.id,
            'admin_email': self.partner_id.email,
            'is_trial': True,
        })

        self.instance_id = instance.id
        return instance

    def action_activate(self):
        """Activate a paid subscription."""
        self.ensure_one()
        if self.state not in [SubscriptionState.DRAFT, SubscriptionState.TRIAL]:
            raise UserError(_("Can only activate from draft or trial state."))

        today = fields.Date.context_today(self)

        # Calculate next billing date
        if self.billing_cycle == 'yearly':
            next_billing = today + timedelta(days=365)
        else:
            next_billing = today + timedelta(days=30)

        self.write({
            'state': SubscriptionState.ACTIVE,
            'is_trial': False,
            'start_date': today,
            'next_billing_date': next_billing,
            'payment_status': 'pending',
        })

        # Activate instance if exists
        if self.instance_id:
            self.instance_id.write({'is_trial': False})

        self.message_post(body="Subscription activated")
        return True

    def action_suspend(self):
        """Suspend the subscription."""
        self.ensure_one()
        if self.state not in [SubscriptionState.ACTIVE, SubscriptionState.PAST_DUE]:
            raise UserError(_("Can only suspend active or past due subscriptions."))

        self.write({'state': SubscriptionState.SUSPENDED})

        # Suspend instance
        if self.instance_id and self.instance_id.state == InstanceState.RUNNING:
            self.instance_id.action_suspend()

        self.message_post(body="Subscription suspended")
        return True

    def action_reactivate(self):
        """Reactivate a suspended subscription."""
        self.ensure_one()
        if self.state != SubscriptionState.SUSPENDED:
            raise UserError(_("Can only reactivate suspended subscriptions."))

        self.write({
            'state': SubscriptionState.ACTIVE,
            'payment_status': 'pending',
        })

        # Reactivate instance
        if self.instance_id and self.instance_id.state == InstanceState.SUSPENDED:
            self.instance_id.action_resume()

        self.message_post(body="Subscription reactivated")
        return True

    def action_cancel(self):
        """Cancel the subscription."""
        self.ensure_one()
        if self.state in [SubscriptionState.CANCELLED, SubscriptionState.EXPIRED]:
            raise UserError(_("Subscription is already cancelled or expired."))

        today = fields.Date.context_today(self)
        self.write({
            'state': SubscriptionState.CANCELLED,
            'cancellation_date': today,
        })

        self.message_post(body="Subscription cancelled")
        return True

    def action_mark_paid(self):
        """Mark subscription as paid."""
        self.ensure_one()

        today = fields.Date.context_today(self)

        # Calculate next billing date
        if self.billing_cycle == 'yearly':
            next_billing = today + timedelta(days=365)
        else:
            next_billing = today + timedelta(days=30)

        self.write({
            'payment_status': 'paid',
            'last_payment_date': fields.Datetime.now(),
            'last_billing_date': today,
            'next_billing_date': next_billing,
            'failed_payment_count': 0,
        })

        # Ensure active state
        if self.state in [SubscriptionState.PAST_DUE, SubscriptionState.SUSPENDED]:
            self.write({'state': SubscriptionState.ACTIVE})
            if self.instance_id and self.instance_id.state == InstanceState.SUSPENDED:
                self.instance_id.action_resume()

        self.message_post(body="Payment received")
        return True

    def action_mark_overdue(self):
        """Mark subscription as payment overdue."""
        self.ensure_one()

        self.write({
            'payment_status': 'overdue',
            'state': SubscriptionState.PAST_DUE,
        })

        self.message_post(body="Payment overdue")
        return True

    def action_view_instance(self):
        """Open associated instance."""
        self.ensure_one()
        if not self.instance_id:
            raise UserError(_("No instance associated with this subscription."))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Instance',
            'res_model': ModelNames.INSTANCE,
            'view_mode': 'form',
            'res_id': self.instance_id.id,
        }

    @api.model
    def cron_check_trial_expiry(self):
        """Cron job to check and expire trial subscriptions."""
        today = fields.Date.context_today(self)
        expired_trials = self.search([
            ('state', '=', SubscriptionState.TRIAL),
            ('trial_end_date', '<', today),
        ])

        for sub in expired_trials:
            sub.write({'state': SubscriptionState.EXPIRED})
            sub.message_post(body="Trial period expired")

            # Suspend instance
            if sub.instance_id and sub.instance_id.state == InstanceState.RUNNING:
                sub.instance_id.action_suspend()

        _logger.info(f"Expired {len(expired_trials)} trial subscriptions")
        return True

    @api.model
    def cron_send_trial_warnings(self):
        """Cron job to send trial expiration warning emails."""
        today = fields.Date.context_today(self)
        Template = self.env['mail.template'].sudo()

        # Find 7-day warning template
        template_7day = Template.search([('name', 'ilike', 'Trial Ending in 7')], limit=1)
        # Find 1-day warning template
        template_1day = Template.search([('name', 'ilike', 'Trial Ending Tomorrow')], limit=1)

        warnings_sent = 0

        # 7-day warnings
        if template_7day:
            seven_days = today + timedelta(days=7)
            subs_7day = self.search([
                ('state', '=', SubscriptionState.TRIAL),
                ('trial_end_date', '=', seven_days),
            ])
            for sub in subs_7day:
                try:
                    template_7day.send_mail(sub.id, force_send=True)
                    sub.message_post(body="Trial ending in 7 days - warning email sent")
                    warnings_sent += 1
                except Exception as e:
                    _logger.error(f"Failed to send 7-day warning for {sub.reference}: {e}")

        # 1-day warnings
        if template_1day:
            one_day = today + timedelta(days=1)
            subs_1day = self.search([
                ('state', '=', SubscriptionState.TRIAL),
                ('trial_end_date', '=', one_day),
            ])
            for sub in subs_1day:
                try:
                    template_1day.send_mail(sub.id, force_send=True)
                    sub.message_post(body="Trial ending tomorrow - warning email sent")
                    warnings_sent += 1
                except Exception as e:
                    _logger.error(f"Failed to send 1-day warning for {sub.reference}: {e}")

        _logger.info(f"Sent {warnings_sent} trial warning emails")
        return True

    @api.model
    def cron_check_billing_due(self):
        """Cron job to check billing due dates."""
        today = fields.Date.context_today(self)

        # Find subscriptions due for billing
        due_subscriptions = self.search([
            ('state', '=', SubscriptionState.ACTIVE),
            ('next_billing_date', '<=', today),
            ('payment_status', '!=', 'overdue'),
        ])

        for sub in due_subscriptions:
            sub.write({'payment_status': 'pending'})
            # Here you would trigger invoice generation or payment processing

        _logger.info(f"Found {len(due_subscriptions)} subscriptions due for billing")
        return True
