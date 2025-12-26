# -*- coding: utf-8 -*-
"""
Extend SaaS Instance with sale order integration.
"""

from odoo import models, fields

from odoo.addons.saas_core.constants.fields import ModelNames


class SaasInstance(models.Model):
    """Extend SaaS Instance with sale order reference."""

    _inherit = ModelNames.INSTANCE

    # Sale order integration
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        readonly=True,
        ondelete='set null',
        help='The sale order that created this instance',
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        readonly=True,
        ondelete='set null',
        help='The specific order line for this instance',
    )
