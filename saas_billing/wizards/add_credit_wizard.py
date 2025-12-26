# -*- coding: utf-8 -*-
"""
Add Credit Wizard.

Wizard to add credits to customer accounts.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AddCreditWizard(models.TransientModel):
    """Wizard to add credit to customer."""

    _name = 'saas.add.credit.wizard'
    _description = 'Add Credit Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
    )
    current_balance = fields.Monetary(
        string='Current Balance',
        compute='_compute_current_balance',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
    )
    credit_type = fields.Selection(
        selection=[
            ('prepaid', 'Prepaid'),
            ('promotional', 'Promotional'),
            ('compensation', 'Compensation'),
        ],
        string='Credit Type',
        default='prepaid',
        required=True,
    )
    description = fields.Char(
        string='Description',
    )
    expires_days = fields.Integer(
        string='Expires In (Days)',
        help='Leave empty for non-expiring credits. Promotional credits default to 90 days.',
    )

    @api.depends('partner_id')
    def _compute_current_balance(self):
        """Get current credit balance."""
        Credit = self.env['saas.customer.credit']
        for wizard in self:
            if wizard.partner_id:
                wizard.current_balance = Credit.get_available_balance(wizard.partner_id.id)
            else:
                wizard.current_balance = 0.0

    @api.constrains('amount')
    def _check_amount(self):
        """Validate amount is positive."""
        for wizard in self:
            if wizard.amount <= 0:
                raise ValidationError("Amount must be greater than zero.")

    def action_add_credit(self):
        """Add credit to customer."""
        self.ensure_one()

        Credit = self.env['saas.customer.credit']
        credit = Credit.add_credit(
            partner_id=self.partner_id.id,
            amount=self.amount,
            credit_type=self.credit_type,
            description=self.description or f'{self.credit_type.title()} Credit',
            expires_days=self.expires_days or None,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Credit Added',
            'res_model': 'saas.customer.credit',
            'view_mode': 'form',
            'res_id': credit.id,
        }
