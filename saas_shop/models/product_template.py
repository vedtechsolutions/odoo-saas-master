# -*- coding: utf-8 -*-
"""
Extend Product Template for SaaS integration.
"""

from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames


class ProductTemplate(models.Model):
    """Extend Product Template with SaaS plan fields."""

    _inherit = 'product.template'

    is_saas_plan = fields.Boolean(
        string='Is SaaS Plan',
        default=False,
        help='This product represents a SaaS subscription plan',
    )
    is_saas_addon = fields.Boolean(
        string='Is SaaS Add-on',
        default=False,
        help='This product is a SaaS add-on (extra storage, users, etc.)',
    )
    saas_plan_id = fields.Many2one(
        ModelNames.PLAN,
        string='SaaS Plan',
        ondelete='set null',
        help='Linked SaaS plan for this product',
    )

    # Add-on configuration
    addon_type = fields.Selection(
        selection=[
            ('storage_db', 'Extra Database Storage'),
            ('storage_file', 'Extra File Storage'),
            ('users', 'Extra Users'),
            ('instances', 'Extra Instances'),
            ('backup', 'Premium Backup'),
            ('domain', 'Custom Domain'),
            ('support', 'Priority Support'),
        ],
        string='Add-on Type',
        help='Type of add-on for SaaS instances',
    )
    addon_quantity = fields.Float(
        string='Add-on Quantity',
        default=1.0,
        help='Quantity provided by this add-on (e.g., 5 GB, 1 user)',
    )
    addon_unit = fields.Char(
        string='Add-on Unit',
        help='Unit of measurement (e.g., GB, users)',
    )

    # Display fields for shop
    plan_cpu = fields.Float(
        related='saas_plan_id.cpu_limit',
        string='CPU Cores',
    )
    plan_ram = fields.Integer(
        related='saas_plan_id.ram_limit_mb',
        string='RAM (MB)',
    )
    plan_storage_db = fields.Float(
        related='saas_plan_id.storage_db_limit_gb',
        string='DB Storage (GB)',
    )
    plan_storage_file = fields.Float(
        related='saas_plan_id.storage_file_limit_gb',
        string='File Storage (GB)',
    )
    plan_users = fields.Integer(
        related='saas_plan_id.user_limit',
        string='Max Users',
    )
    plan_instances = fields.Integer(
        related='saas_plan_id.instance_limit',
        string='Max Instances',
    )
    plan_support_level = fields.Selection(
        related='saas_plan_id.support_level',
        string='Support Level',
    )

    @api.onchange('saas_plan_id')
    def _onchange_saas_plan_id(self):
        """Update product details when plan changes."""
        if self.saas_plan_id:
            self.is_saas_plan = True
            if not self.name:
                self.name = f"{self.saas_plan_id.name} Plan"
            if not self.list_price:
                self.list_price = self.saas_plan_id.monthly_price

    def _get_billing_cycle(self, product_variant):
        """Get billing cycle for a product variant."""
        for ptav in product_variant.product_template_attribute_value_ids:
            if ptav.attribute_id.name == 'Billing Cycle':
                return ptav.product_attribute_value_id.name.lower()
        return 'monthly'  # default


class ProductProduct(models.Model):
    """Extend Product with SaaS fields."""

    _inherit = 'product.product'

    def _get_saas_plan(self):
        """Get the SaaS plan for this product variant."""
        self.ensure_one()
        return self.product_tmpl_id.saas_plan_id

    def _get_billing_cycle(self):
        """Get billing cycle for this variant."""
        self.ensure_one()
        return self.product_tmpl_id._get_billing_cycle(self)

    def _is_saas_product(self):
        """Check if this is a SaaS plan or add-on product."""
        self.ensure_one()
        return self.product_tmpl_id.is_saas_plan or self.product_tmpl_id.is_saas_addon
