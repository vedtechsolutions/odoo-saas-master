# -*- coding: utf-8 -*-
"""
Invoice extensions for SaaS billing.

Adds SaaS-specific fields and functionality to Odoo invoices.
"""

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.saas_core.constants.fields import ModelNames

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """Extend invoices with SaaS fields."""

    _inherit = 'account.move'

    # SaaS Relations
    subscription_id = fields.Many2one(
        ModelNames.SUBSCRIPTION,
        string='SaaS Subscription',
        ondelete='set null',
        index=True,
    )
    instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='SaaS Instance',
        ondelete='set null',
    )
    billing_transaction_id = fields.Many2one(
        'saas.billing.transaction',
        string='Billing Transaction',
        ondelete='set null',
    )

    # SaaS Invoice Type
    saas_invoice_type = fields.Selection(
        selection=[
            ('subscription', 'Subscription'),
            ('addon', 'Add-on'),
            ('overage', 'Overage'),
            ('setup', 'Setup Fee'),
            ('credit', 'Credit Purchase'),
        ],
        string='SaaS Invoice Type',
    )

    # Billing period
    billing_period_start = fields.Date(
        string='Billing Period Start',
    )
    billing_period_end = fields.Date(
        string='Billing Period End',
    )

    # Proration
    is_prorated = fields.Boolean(
        string='Prorated',
        default=False,
    )
    proration_factor = fields.Float(
        string='Proration Factor',
        digits=(5, 4),
        default=1.0,
    )

    # Credit applied
    credit_applied = fields.Monetary(
        string='Credit Applied',
        default=0.0,
    )

    # Computed fields
    subscription_name = fields.Char(
        related='subscription_id.name',
        string='Subscription Name',
    )
    is_saas_invoice = fields.Boolean(
        string='Is SaaS Invoice',
        compute='_compute_is_saas_invoice',
        store=True,
    )

    @api.depends('subscription_id', 'saas_invoice_type')
    def _compute_is_saas_invoice(self):
        """Check if this is a SaaS-related invoice."""
        for move in self:
            move.is_saas_invoice = bool(
                move.subscription_id or move.saas_invoice_type
            )

    def action_apply_credit(self):
        """Apply customer credit to invoice."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("Can only apply credit to posted invoices."))

        if self.payment_state == 'paid':
            raise UserError(_("Invoice is already paid."))

        Credit = self.env['saas.customer.credit']
        available = Credit.get_available_balance(self.partner_id.id)

        if available <= 0:
            raise UserError(_("Customer has no available credit."))

        # Calculate how much credit to apply
        remaining = self.amount_residual
        to_apply = min(available, remaining)

        # Use credit
        Credit.use_credit(
            partner_id=self.partner_id.id,
            amount=to_apply,
            description=f"Applied to invoice {self.name}",
        )

        # Update invoice
        self.credit_applied = (self.credit_applied or 0) + to_apply

        # Create payment if fully covered
        if to_apply >= remaining:
            self._create_credit_payment(to_apply)

        self.message_post(body=f"Applied {to_apply} credit to invoice.")
        return True

    def _create_credit_payment(self, amount):
        """Create a payment record for credit application."""
        # This would create an actual payment journal entry
        # For now, just log
        _logger.info(f"Credit payment of {amount} applied to invoice {self.name}")

    def action_create_billing_transaction(self):
        """Create billing transaction for this invoice."""
        self.ensure_one()
        if self.billing_transaction_id:
            raise UserError(_("Billing transaction already exists for this invoice."))

        if self.move_type != 'out_invoice':
            raise UserError(_("Can only create transactions for customer invoices."))

        Transaction = self.env['saas.billing.transaction']
        txn = Transaction.create({
            'name': f"Payment for {self.name}",
            'transaction_type': self.saas_invoice_type or 'subscription',
            'partner_id': self.partner_id.id,
            'subscription_id': self.subscription_id.id if self.subscription_id else False,
            'invoice_id': self.id,
            'amount': self.amount_total,
            'period_start': self.billing_period_start,
            'period_end': self.billing_period_end,
        })

        self.billing_transaction_id = txn.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'Billing Transaction',
            'res_model': 'saas.billing.transaction',
            'view_mode': 'form',
            'res_id': txn.id,
        }

    @api.model
    def create_subscription_invoice(self, subscription, period_start=None, period_end=None):
        """Create invoice for subscription billing."""
        if not subscription.partner_id:
            raise UserError(_("Subscription has no customer."))

        period_start = period_start or fields.Date.context_today(self)

        # Calculate period end based on billing cycle
        if subscription.billing_cycle == 'yearly':
            from datetime import timedelta
            period_end = period_end or (period_start + timedelta(days=365))
        else:
            from datetime import timedelta
            period_end = period_end or (period_start + timedelta(days=30))

        # Create invoice
        invoice = self.create({
            'move_type': 'out_invoice',
            'partner_id': subscription.partner_id.id,
            'subscription_id': subscription.id,
            'instance_id': subscription.instance_id.id if subscription.instance_id else False,
            'saas_invoice_type': 'subscription',
            'billing_period_start': period_start,
            'billing_period_end': period_end,
            'invoice_line_ids': [(0, 0, {
                'name': f"{subscription.plan_id.name} - {subscription.billing_cycle}",
                'quantity': 1,
                'price_unit': subscription.recurring_price,
            })],
        })

        # Link to subscription
        subscription.message_post(
            body=f"Invoice {invoice.name} created for billing period "
                 f"{period_start} to {period_end}"
        )

        return invoice


class AccountMoveLine(models.Model):
    """Extend invoice lines with SaaS fields."""

    _inherit = 'account.move.line'

    # SaaS Line Type
    saas_line_type = fields.Selection(
        selection=[
            ('base', 'Base Subscription'),
            ('addon', 'Add-on'),
            ('overage', 'Overage Charge'),
            ('discount', 'Discount'),
            ('proration', 'Proration Adjustment'),
        ],
        string='SaaS Line Type',
    )

    # Usage tracking (for overage lines)
    usage_metric = fields.Char(
        string='Usage Metric',
    )
    usage_quantity = fields.Float(
        string='Usage Quantity',
    )
    usage_unit_price = fields.Float(
        string='Usage Unit Price',
    )

    # Period tracking
    line_period_start = fields.Date(
        string='Period Start',
    )
    line_period_end = fields.Date(
        string='Period End',
    )
