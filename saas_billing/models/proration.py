# -*- coding: utf-8 -*-
"""
Proration Calculator for plan changes.

Handles upgrade/downgrade proration calculations.
"""

import logging
from datetime import date, timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProrationCalculator(models.TransientModel):
    """Calculate proration for plan changes."""

    _name = 'saas.proration.calculator'
    _description = 'Proration Calculator'

    # Input fields
    subscription_id = fields.Many2one(
        'saas.subscription',
        string='Subscription',
        required=True,
    )
    new_plan_id = fields.Many2one(
        'saas.plan',
        string='New Plan',
        required=True,
    )
    change_date = fields.Date(
        string='Change Date',
        default=fields.Date.context_today,
        required=True,
    )

    # Current subscription info
    current_plan_id = fields.Many2one(
        related='subscription_id.plan_id',
        string='Current Plan',
    )
    billing_cycle = fields.Selection(
        related='subscription_id.billing_cycle',
        string='Billing Cycle',
    )
    next_billing_date = fields.Date(
        related='subscription_id.next_billing_date',
        string='Next Billing Date',
    )
    last_billing_date = fields.Date(
        related='subscription_id.last_billing_date',
        string='Last Billing Date',
    )

    # Calculated fields
    days_in_period = fields.Integer(
        string='Days in Period',
        compute='_compute_proration',
    )
    days_remaining = fields.Integer(
        string='Days Remaining',
        compute='_compute_proration',
    )
    days_used = fields.Integer(
        string='Days Used',
        compute='_compute_proration',
    )

    current_price = fields.Float(
        string='Current Price',
        compute='_compute_proration',
    )
    new_price = fields.Float(
        string='New Price',
        compute='_compute_proration',
    )

    credit_amount = fields.Float(
        string='Credit for Unused Days',
        compute='_compute_proration',
        help='Credit for unused portion of current plan',
    )
    charge_amount = fields.Float(
        string='Charge for New Plan',
        compute='_compute_proration',
        help='Prorated charge for new plan',
    )
    net_amount = fields.Float(
        string='Net Amount',
        compute='_compute_proration',
        help='Net charge (positive) or credit (negative)',
    )

    is_upgrade = fields.Boolean(
        string='Is Upgrade',
        compute='_compute_proration',
    )
    proration_factor = fields.Float(
        string='Proration Factor',
        compute='_compute_proration',
        digits=(5, 4),
    )

    @api.depends('subscription_id', 'new_plan_id', 'change_date')
    def _compute_proration(self):
        """Calculate proration amounts."""
        for calc in self:
            if not calc.subscription_id or not calc.new_plan_id:
                calc.days_in_period = 0
                calc.days_remaining = 0
                calc.days_used = 0
                calc.current_price = 0
                calc.new_price = 0
                calc.credit_amount = 0
                calc.charge_amount = 0
                calc.net_amount = 0
                calc.is_upgrade = False
                calc.proration_factor = 0
                continue

            sub = calc.subscription_id
            today = calc.change_date or fields.Date.context_today(calc)

            # Determine billing period dates
            period_start = sub.last_billing_date or sub.start_date or today
            period_end = sub.next_billing_date

            if not period_end:
                # Calculate based on billing cycle
                if sub.billing_cycle == 'yearly':
                    period_end = period_start + timedelta(days=365)
                else:
                    period_end = period_start + timedelta(days=30)

            # Calculate days
            calc.days_in_period = (period_end - period_start).days
            calc.days_remaining = max(0, (period_end - today).days)
            calc.days_used = calc.days_in_period - calc.days_remaining

            # Get prices based on billing cycle
            if sub.billing_cycle == 'yearly':
                calc.current_price = sub.plan_id.yearly_price if sub.plan_id else 0
                calc.new_price = calc.new_plan_id.yearly_price
            else:
                calc.current_price = sub.plan_id.monthly_price if sub.plan_id else 0
                calc.new_price = calc.new_plan_id.monthly_price

            # Calculate proration factor
            if calc.days_in_period > 0:
                calc.proration_factor = calc.days_remaining / calc.days_in_period
            else:
                calc.proration_factor = 0

            # Calculate credit for unused portion of current plan
            calc.credit_amount = calc.current_price * calc.proration_factor

            # Calculate charge for new plan (prorated)
            calc.charge_amount = calc.new_price * calc.proration_factor

            # Net amount (positive = customer pays, negative = customer gets credit)
            calc.net_amount = calc.charge_amount - calc.credit_amount

            # Determine if upgrade or downgrade
            calc.is_upgrade = calc.new_price > calc.current_price

    def action_apply_change(self):
        """Apply the plan change with proration."""
        self.ensure_one()

        if not self.subscription_id or not self.new_plan_id:
            raise ValidationError("Subscription and new plan are required.")

        sub = self.subscription_id
        Credit = self.env['saas.customer.credit']
        Invoice = self.env['account.move']

        # If downgrade (credit_amount > charge_amount), add credit
        if self.net_amount < 0:
            # Customer gets credit
            Credit.add_credit(
                partner_id=sub.partner_id.id,
                amount=abs(self.net_amount),
                credit_type='refund',
                description=f"Proration credit: {sub.plan_id.name} → {self.new_plan_id.name}",
            )
            sub.message_post(
                body=f"Plan downgraded from {sub.plan_id.name} to {self.new_plan_id.name}. "
                     f"Credit of ${abs(self.net_amount):.2f} added."
            )

        # If upgrade (charge_amount > credit_amount), create invoice
        elif self.net_amount > 0:
            # Create prorated invoice
            invoice = Invoice.create({
                'move_type': 'out_invoice',
                'partner_id': sub.partner_id.id,
                'subscription_id': sub.id,
                'saas_invoice_type': 'subscription',
                'is_prorated': True,
                'proration_factor': self.proration_factor,
                'billing_period_start': self.change_date,
                'billing_period_end': sub.next_billing_date,
                'invoice_line_ids': [
                    # Credit line for unused current plan
                    (0, 0, {
                        'name': f"Credit: {sub.plan_id.name} (unused portion)",
                        'quantity': 1,
                        'price_unit': -self.credit_amount,
                        'saas_line_type': 'proration',
                    }),
                    # Charge line for new plan
                    (0, 0, {
                        'name': f"{self.new_plan_id.name} (prorated)",
                        'quantity': 1,
                        'price_unit': self.charge_amount,
                        'saas_line_type': 'proration',
                    }),
                ],
            })
            sub.message_post(
                body=f"Plan upgraded from {sub.plan_id.name} to {self.new_plan_id.name}. "
                     f"Prorated invoice {invoice.name} created for ${self.net_amount:.2f}"
            )

        # Update subscription plan
        old_plan = sub.plan_id
        sub.write({
            'plan_id': self.new_plan_id.id,
        })

        # Update instance plan if linked
        if sub.instance_id:
            sub.instance_id.write({
                'plan_id': self.new_plan_id.id,
            })

        _logger.info(
            f"Subscription {sub.reference} changed from {old_plan.name} to "
            f"{self.new_plan_id.name}. Net proration: ${self.net_amount:.2f}"
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Subscription',
            'res_model': 'saas.subscription',
            'view_mode': 'form',
            'res_id': sub.id,
        }


class SaasSubscriptionBilling(models.Model):
    """Extend subscription with billing capabilities."""

    _inherit = 'saas.subscription'

    # Billing relations
    invoice_ids = fields.One2many(
        'account.move',
        'subscription_id',
        string='Invoices',
        domain=[('move_type', '=', 'out_invoice')],
    )
    transaction_ids = fields.One2many(
        'saas.billing.transaction',
        'subscription_id',
        string='Transactions',
    )

    # Computed stats
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_billing_stats',
    )
    total_invoiced = fields.Monetary(
        string='Total Invoiced',
        compute='_compute_billing_stats',
    )
    total_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_billing_stats',
    )
    outstanding_amount = fields.Monetary(
        string='Outstanding Amount',
        compute='_compute_billing_stats',
    )

    def _compute_billing_stats(self):
        """Compute billing statistics."""
        for sub in self:
            invoices = sub.invoice_ids.filtered(lambda i: i.state == 'posted')
            sub.invoice_count = len(invoices)
            sub.total_invoiced = sum(invoices.mapped('amount_total'))
            sub.total_paid = sum(invoices.mapped('amount_total')) - sum(invoices.mapped('amount_residual'))
            sub.outstanding_amount = sum(invoices.mapped('amount_residual'))

    def action_view_invoices(self):
        """View subscription invoices."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('subscription_id', '=', self.id), ('move_type', '=', 'out_invoice')],
            'context': {'default_subscription_id': self.id},
        }

    def action_view_transactions(self):
        """View billing transactions."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transactions',
            'res_model': 'saas.billing.transaction',
            'view_mode': 'list,form',
            'domain': [('subscription_id', '=', self.id)],
            'context': {'default_subscription_id': self.id},
        }

    def action_create_invoice(self):
        """Create invoice for current billing period."""
        self.ensure_one()
        Invoice = self.env['account.move']
        return Invoice.create_subscription_invoice(self)

    def action_change_plan(self):
        """Open plan change wizard with proration."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Change Plan',
            'res_model': 'saas.proration.calculator',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_subscription_id': self.id},
        }
