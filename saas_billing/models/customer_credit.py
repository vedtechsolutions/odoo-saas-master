# -*- coding: utf-8 -*-
"""
Customer Credit/Wallet model.

Manages prepaid credits, refund credits, and promotional credits.
"""

import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CreditType:
    """Credit type constants."""
    PREPAID = 'prepaid'
    REFUND = 'refund'
    PROMOTIONAL = 'promotional'
    COMPENSATION = 'compensation'

    @classmethod
    def get_selection(cls):
        return [
            (cls.PREPAID, 'Prepaid'),
            (cls.REFUND, 'Refund'),
            (cls.PROMOTIONAL, 'Promotional'),
            (cls.COMPENSATION, 'Compensation'),
        ]


class CustomerCredit(models.Model):
    """Customer credit balance entries."""

    _name = 'saas.customer.credit'
    _description = 'Customer Credit'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    # Basic fields
    name = fields.Char(
        string='Description',
        required=True,
    )
    reference = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New',
        index=True,
    )

    # Relations
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='restrict',
        index=True,
    )
    transaction_id = fields.Many2one(
        'saas.billing.transaction',
        string='Related Transaction',
        ondelete='set null',
    )

    # Credit details
    credit_type = fields.Selection(
        selection=CreditType.get_selection(),
        string='Credit Type',
        required=True,
        default=CreditType.PREPAID,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        help='Positive for credits added, negative for credits used',
    )
    balance_after = fields.Monetary(
        string='Balance After',
        readonly=True,
        help='Customer balance after this transaction',
    )

    # Expiration
    expires_at = fields.Date(
        string='Expires On',
        help='Leave empty for non-expiring credits',
    )
    is_expired = fields.Boolean(
        string='Expired',
        compute='_compute_is_expired',
        store=True,
    )

    # Tracking
    used_amount = fields.Monetary(
        string='Used Amount',
        default=0.0,
        readonly=True,
    )
    remaining_amount = fields.Monetary(
        string='Remaining',
        compute='_compute_remaining_amount',
        store=True,
    )

    # Metadata
    notes = fields.Text(
        string='Notes',
    )
    created_by = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
    )

    @api.depends('expires_at')
    def _compute_is_expired(self):
        """Check if credit has expired."""
        today = fields.Date.context_today(self)
        for credit in self:
            if credit.expires_at:
                credit.is_expired = credit.expires_at < today
            else:
                credit.is_expired = False

    @api.depends('amount', 'used_amount')
    def _compute_remaining_amount(self):
        """Calculate remaining credit amount."""
        for credit in self:
            if credit.amount > 0:
                credit.remaining_amount = credit.amount - credit.used_amount
            else:
                credit.remaining_amount = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate reference, name, and update balance."""
        for vals in vals_list:
            # Auto-generate reference
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'saas.customer.credit'
                ) or 'New'

            # Auto-generate name if not provided
            if not vals.get('name'):
                credit_type = vals.get('credit_type', CreditType.PREPAID)
                type_labels = dict(CreditType.get_selection())
                vals['name'] = f"{type_labels.get(credit_type, 'Credit')} Credit"

            # Calculate balance after
            partner_id = vals.get('partner_id')
            amount = vals.get('amount', 0)
            current_balance = self.get_available_balance(partner_id)
            vals['balance_after'] = current_balance + amount

        return super().create(vals_list)

    @api.model
    def get_available_balance(self, partner_id):
        """Get available credit balance for a customer."""
        today = fields.Date.context_today(self)

        # Sum all non-expired, positive credits minus used amounts
        credits = self.search([
            ('partner_id', '=', partner_id),
            ('amount', '>', 0),
            '|',
            ('expires_at', '=', False),
            ('expires_at', '>=', today),
        ])

        total_available = sum(c.remaining_amount for c in credits)

        # Subtract any pending deductions
        deductions = self.search([
            ('partner_id', '=', partner_id),
            ('amount', '<', 0),
        ])
        total_deductions = sum(abs(d.amount) for d in deductions)

        return max(0, total_available - total_deductions)

    @api.model
    def add_credit(self, partner_id, amount, credit_type='prepaid',
                   description=None, expires_days=None, transaction_id=None):
        """Add credit to customer account."""
        if amount <= 0:
            raise ValidationError("Credit amount must be positive.")

        vals = {
            'partner_id': partner_id,
            'amount': amount,
            'credit_type': credit_type,
            'name': description or f'{credit_type.title()} Credit',
            'transaction_id': transaction_id,
        }

        # Set expiration for promotional credits
        if expires_days:
            vals['expires_at'] = fields.Date.context_today(self) + timedelta(days=expires_days)
        elif credit_type == CreditType.PROMOTIONAL:
            # Default 90 days for promotional
            vals['expires_at'] = fields.Date.context_today(self) + timedelta(days=90)

        credit = self.create(vals)

        # Update partner's cached balance
        partner = self.env['res.partner'].browse(partner_id)
        if hasattr(partner, 'credit_balance'):
            partner._compute_credit_balance()

        _logger.info(f"Added {amount} credit to partner {partner_id}: {credit.reference}")
        return credit

    @api.model
    def use_credit(self, partner_id, amount, description=None, transaction_id=None):
        """Use credit from customer account."""
        if amount <= 0:
            raise ValidationError("Usage amount must be positive.")

        available = self.get_available_balance(partner_id)
        if available < amount:
            raise UserError(
                f"Insufficient credit balance. Available: {available}, Requested: {amount}"
            )

        # Create negative entry
        usage = self.create({
            'partner_id': partner_id,
            'amount': -amount,
            'credit_type': CreditType.PREPAID,
            'name': description or 'Credit Usage',
            'transaction_id': transaction_id,
        })

        # Mark credits as used (FIFO - oldest first)
        self._allocate_usage(partner_id, amount)

        # Update partner's cached balance
        partner = self.env['res.partner'].browse(partner_id)
        if hasattr(partner, 'credit_balance'):
            partner._compute_credit_balance()

        _logger.info(f"Used {amount} credit from partner {partner_id}: {usage.reference}")
        return usage

    def _allocate_usage(self, partner_id, amount):
        """Allocate credit usage to specific credit entries (FIFO)."""
        today = fields.Date.context_today(self)
        remaining = amount

        # Get available credits ordered by expiration (soonest first) then date
        credits = self.search([
            ('partner_id', '=', partner_id),
            ('amount', '>', 0),
            ('remaining_amount', '>', 0),
            '|',
            ('expires_at', '=', False),
            ('expires_at', '>=', today),
        ], order='expires_at asc nulls last, create_date asc')

        for credit in credits:
            if remaining <= 0:
                break

            available = credit.remaining_amount
            use_from_this = min(available, remaining)

            credit.write({
                'used_amount': credit.used_amount + use_from_this,
            })

            remaining -= use_from_this

    @api.model
    def cron_expire_credits(self):
        """Cron job to mark expired credits."""
        today = fields.Date.context_today(self)

        expired = self.search([
            ('expires_at', '<', today),
            ('is_expired', '=', False),
            ('remaining_amount', '>', 0),
        ])

        for credit in expired:
            credit.write({'is_expired': True})
            _logger.info(f"Credit {credit.reference} expired with {credit.remaining_amount} remaining")

        return True


class ResPartnerCredit(models.Model):
    """Extend partner with credit information."""

    _inherit = 'res.partner'

    credit_ids = fields.One2many(
        'saas.customer.credit',
        'partner_id',
        string='Credit History',
    )
    credit_balance = fields.Monetary(
        string='Credit Balance',
        compute='_compute_credit_balance',
        currency_field='currency_id',
    )
    credit_count = fields.Integer(
        string='Credit Entries',
        compute='_compute_credit_count',
    )

    def _compute_credit_balance(self):
        """Compute available credit balance."""
        Credit = self.env['saas.customer.credit']
        for partner in self:
            partner.credit_balance = Credit.get_available_balance(partner.id)

    def _compute_credit_count(self):
        """Count credit entries."""
        for partner in self:
            partner.credit_count = len(partner.credit_ids)

    def action_view_credits(self):
        """Open credit history."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Credit History',
            'res_model': 'saas.customer.credit',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_add_credit(self):
        """Open wizard to add credit."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Credit',
            'res_model': 'saas.add.credit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
        }
