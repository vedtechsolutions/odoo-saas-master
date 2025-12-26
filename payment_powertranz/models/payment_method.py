# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)

class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    def _compute_image_payment_form(self):
        """Override to return card brand-specific images for PowerTranz tokens."""
        super()._compute_image_payment_form()

        for method in self:
            # Only modify card payment methods
            if method.code != 'card':
                continue

            # Check if we're in a token context with a card brand
            token_id = self.env.context.get('token_id')
            if token_id:
                token = self.env['payment.token'].browse(token_id)
                if token.exists() and token.provider_code == 'powertranz' and token.powertranz_card_brand:
                    card_brand = token.powertranz_card_brand.lower()
                    if card_brand == 'visa':
                        method.image_payment_form = self.env.ref('payment_powertranz.payment_icon_visa').image_128
                    elif card_brand == 'mastercard':
                        method.image_payment_form = self.env.ref('payment_powertranz.payment_icon_mastercard').image_128
