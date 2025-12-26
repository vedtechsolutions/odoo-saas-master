# -*- coding: utf-8 -*-
"""
Extend SaaS Plan with e-commerce product integration.
"""

from odoo import models, fields, api

from odoo.addons.saas_core.constants.fields import ModelNames


class SaasPlan(models.Model):
    """Extend SaaS Plan with product template link."""

    _inherit = ModelNames.PLAN

    # Link to product template
    product_template_id = fields.Many2one(
        'product.template',
        string='Product Template',
        ondelete='set null',
        help='Product template for this plan in the shop',
    )

    # Product variants
    product_monthly_id = fields.Many2one(
        'product.product',
        string='Monthly Product',
        compute='_compute_product_variants',
        store=True,
    )
    product_yearly_id = fields.Many2one(
        'product.product',
        string='Yearly Product',
        compute='_compute_product_variants',
        store=True,
    )

    # Shop display
    shop_visible = fields.Boolean(
        string='Visible in Shop',
        default=True,
        help='Show this plan in the website shop',
    )
    shop_featured = fields.Boolean(
        string='Featured Plan',
        default=False,
        help='Highlight this plan in the shop',
    )
    features_html = fields.Html(
        string='Features HTML',
        help='Rich text description of plan features for website display',
    )

    @api.depends('product_template_id', 'product_template_id.product_variant_ids')
    def _compute_product_variants(self):
        """Find monthly and yearly variants of the product template."""
        BillingAttr = self.env['product.attribute.value'].sudo()

        for plan in self:
            plan.product_monthly_id = False
            plan.product_yearly_id = False

            if not plan.product_template_id:
                continue

            # Find billing cycle attribute values
            monthly_val = BillingAttr.search([
                ('name', '=', 'Monthly'),
                ('attribute_id.name', '=', 'Billing Cycle'),
            ], limit=1)
            yearly_val = BillingAttr.search([
                ('name', '=', 'Yearly'),
                ('attribute_id.name', '=', 'Billing Cycle'),
            ], limit=1)

            for variant in plan.product_template_id.product_variant_ids:
                variant_attrs = variant.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id'
                )
                if monthly_val in variant_attrs:
                    plan.product_monthly_id = variant
                elif yearly_val in variant_attrs:
                    plan.product_yearly_id = variant

    def action_create_product(self):
        """Create a product template for this plan."""
        self.ensure_one()

        if self.product_template_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'product.template',
                'res_id': self.product_template_id.id,
                'view_mode': 'form',
            }

        # Get or create SaaS product category
        category = self.env.ref(
            'saas_shop.product_category_saas_plans',
            raise_if_not_found=False
        )
        if not category:
            category = self.env['product.category'].create({
                'name': 'SaaS Plans',
            })

        # Get billing cycle attribute
        billing_attr = self.env.ref(
            'saas_shop.product_attribute_billing_cycle',
            raise_if_not_found=False
        )

        # Create product template
        product_vals = {
            'name': f"{self.name} Plan",
            'type': 'service',
            'list_price': self.monthly_price,
            'categ_id': category.id,
            'sale_ok': True,
            'purchase_ok': False,
            'is_saas_plan': True,
            'saas_plan_id': self.id,
            'website_published': self.is_active and not self.is_trial,
            'description_sale': self.description or f"Subscribe to {self.name} plan",
        }

        product = self.env['product.template'].create(product_vals)
        self.product_template_id = product

        # Add billing cycle variants if attribute exists
        if billing_attr:
            monthly_val = self.env.ref(
                'saas_shop.product_attribute_value_monthly',
                raise_if_not_found=False
            )
            yearly_val = self.env.ref(
                'saas_shop.product_attribute_value_yearly',
                raise_if_not_found=False
            )

            if monthly_val and yearly_val:
                # Add attribute line with both values
                self.env['product.template.attribute.line'].create({
                    'product_tmpl_id': product.id,
                    'attribute_id': billing_attr.id,
                    'value_ids': [(6, 0, [monthly_val.id, yearly_val.id])],
                })

                # Set price extra for yearly (discount)
                yearly_ptav = product.attribute_line_ids.product_template_value_ids.filtered(
                    lambda v: v.product_attribute_value_id == yearly_val
                )
                if yearly_ptav:
                    # Yearly price = (yearly - monthly*12) to show as price difference
                    yearly_savings = (self.monthly_price * 12) - self.yearly_price
                    yearly_ptav.price_extra = -yearly_savings

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': product.id,
            'view_mode': 'form',
        }

    def action_sync_product_prices(self):
        """Sync plan prices to product template."""
        for plan in self:
            if not plan.product_template_id:
                continue

            # Update base price (monthly)
            plan.product_template_id.list_price = plan.monthly_price

            # Update yearly variant price extra
            if plan.product_yearly_id:
                yearly_savings = (plan.monthly_price * 12) - plan.yearly_price
                ptav = plan.product_template_id.attribute_line_ids.product_template_value_ids.filtered(
                    lambda v: v.product_attribute_value_id.name == 'Yearly'
                )
                if ptav:
                    ptav.price_extra = -yearly_savings
