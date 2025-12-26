# -*- coding: utf-8 -*-
"""
Extend Sale Order Line for SaaS configuration.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.config import OdooVersions
from odoo.addons.saas_core.utils.validators import validate_subdomain


class SaleOrderLine(models.Model):
    """Extend Sale Order Line with SaaS configuration fields."""

    _inherit = 'sale.order.line'

    # SaaS configuration fields
    is_saas_line = fields.Boolean(
        string='Is SaaS Line',
        compute='_compute_is_saas_line',
        store=True,
    )
    saas_subdomain = fields.Char(
        string='Subdomain',
        help='Subdomain for the SaaS instance (e.g., "mycompany" for mycompany.tenants.vedtechsolutions.com)',
    )
    saas_subdomain_available = fields.Boolean(
        string='Subdomain Available',
        compute='_compute_subdomain_available',
    )
    saas_odoo_version = fields.Selection(
        selection=OdooVersions.get_selection(),
        string='Odoo Version',
        default=OdooVersions.DEFAULT,
    )

    # Link to provisioned instance
    saas_instance_id = fields.Many2one(
        ModelNames.INSTANCE,
        string='SaaS Instance',
        readonly=True,
        help='Instance provisioned from this order line',
    )

    @api.depends('product_id.is_saas_plan', 'product_id.is_saas_addon')
    def _compute_is_saas_line(self):
        for line in self:
            if line.product_id:
                tmpl = line.product_id.product_tmpl_id
                line.is_saas_line = tmpl.is_saas_plan or tmpl.is_saas_addon
            else:
                line.is_saas_line = False

    @api.depends('saas_subdomain')
    def _compute_subdomain_available(self):
        Instance = self.env[ModelNames.INSTANCE]
        for line in self:
            if not line.saas_subdomain:
                line.saas_subdomain_available = False
                continue

            # Check if subdomain is already taken
            existing = Instance.search_count([
                ('subdomain', '=', line.saas_subdomain.lower())
            ])
            line.saas_subdomain_available = (existing == 0)

    @api.onchange('saas_subdomain')
    def _onchange_saas_subdomain(self):
        """Validate subdomain on change."""
        if self.saas_subdomain:
            self.saas_subdomain = self.saas_subdomain.lower().strip()

            # Check availability
            if not self.saas_subdomain_available:
                return {
                    'warning': {
                        'title': 'Subdomain Taken',
                        'message': f'The subdomain "{self.saas_subdomain}" is already in use. Please choose another.',
                    }
                }

    @api.constrains('saas_subdomain')
    def _check_saas_subdomain(self):
        """Validate subdomain format and availability."""
        Instance = self.env[ModelNames.INSTANCE]

        for line in self:
            if not line.is_saas_line or not line.saas_subdomain:
                continue

            # Validate format using centralized validator
            try:
                validate_subdomain(line.saas_subdomain)
            except ValidationError:
                raise

            # Check availability (excluding any instance already linked to this line)
            domain = [('subdomain', '=', line.saas_subdomain.lower())]
            if line.saas_instance_id:
                domain.append(('id', '!=', line.saas_instance_id.id))

            existing = Instance.search_count(domain)
            if existing:
                raise ValidationError(
                    f'The subdomain "{line.saas_subdomain}" is already in use.'
                )

    @api.onchange('product_id')
    def _onchange_product_id_saas(self):
        """Set default Odoo version when SaaS product is selected."""
        if self.product_id and self.is_saas_line:
            if not self.saas_odoo_version:
                self.saas_odoo_version = OdooVersions.DEFAULT

    def _get_display_price(self):
        """Override to show appropriate price for SaaS products."""
        if self.is_saas_line and self.product_id:
            # Get billing cycle
            billing_cycle = self.product_id._get_billing_cycle()
            plan = self.product_id.product_tmpl_id.saas_plan_id

            if plan:
                if billing_cycle == 'yearly':
                    return plan.yearly_price
                return plan.monthly_price

        return super()._get_display_price()
