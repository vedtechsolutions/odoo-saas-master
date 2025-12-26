# -*- coding: utf-8 -*-
"""
SaaS Shop Controllers.

Handles checkout customization and AJAX endpoints.
"""

import logging
import re
from odoo import http
from odoo.http import request

from odoo.addons.saas_core.constants.fields import ModelNames
from odoo.addons.saas_core.constants.reserved import RESERVED_SUBDOMAINS
from odoo.addons.saas_core.constants.config import DomainConfig, OdooVersions
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class SaasWebsiteSale(WebsiteSale):
    """Extend website sale to ensure cart clearing works properly for SaaS orders."""

    @http.route()
    def shop_payment_validate(self, sale_order_id=None, **post):
        """Override to ensure cart is properly cleared for SaaS orders."""
        # Call parent first
        result = super().shop_payment_validate(sale_order_id=sale_order_id, **post)

        # Double-check cart is cleared - safety measure for edge cases
        try:
            if hasattr(request, 'website') and request.website:
                request.website.sale_reset()
                _logger.debug("SaaS shop: Ensured cart reset after payment validation")
        except Exception as e:
            _logger.warning(f"Could not reset cart in payment validation: {e}")

        return result

    @http.route()
    def shop_payment_confirmation(self, **post):
        """Override to ensure cart is cleared on confirmation page."""
        # Ensure cart is cleared before showing confirmation
        try:
            if hasattr(request, 'website') and request.website:
                request.website.sale_reset()
                _logger.debug("SaaS shop: Ensured cart reset on confirmation page")
        except Exception as e:
            _logger.warning(f"Could not reset cart on confirmation: {e}")

        return super().shop_payment_confirmation(**post)


class SaasShopController(http.Controller):
    """Controller for SaaS shop functionality."""

    @http.route('/saas/check_subdomain', type='jsonrpc', auth='public', website=True)
    def check_subdomain(self, subdomain):
        """
        Check if a subdomain is available.

        Args:
            subdomain: The subdomain to check

        Returns:
            dict: {available: bool, message: str}
        """
        if not subdomain:
            return {'available': False, 'message': 'Subdomain is required'}

        subdomain = subdomain.lower().strip()

        # Check length
        if len(subdomain) < DomainConfig.SUBDOMAIN_MIN_LENGTH:
            return {
                'available': False,
                'message': f'Subdomain must be at least {DomainConfig.SUBDOMAIN_MIN_LENGTH} characters'
            }

        if len(subdomain) > DomainConfig.SUBDOMAIN_MAX_LENGTH:
            return {
                'available': False,
                'message': f'Subdomain must be at most {DomainConfig.SUBDOMAIN_MAX_LENGTH} characters'
            }

        # Check format (alphanumeric and hyphens only, no leading/trailing hyphens)
        pattern = DomainConfig.SUBDOMAIN_PATTERN
        if not re.match(pattern, subdomain):
            return {
                'available': False,
                'message': 'Subdomain can only contain lowercase letters, numbers, and hyphens'
            }

        # Check reserved words
        if subdomain in RESERVED_SUBDOMAINS:
            return {
                'available': False,
                'message': 'This subdomain is reserved'
            }

        # Check if already taken
        Instance = request.env[ModelNames.INSTANCE].sudo()
        existing = Instance.search_count([('subdomain', '=', subdomain)])
        if existing:
            return {
                'available': False,
                'message': 'This subdomain is already in use'
            }

        # Available!
        full_domain = f"{subdomain}.{DomainConfig.TENANT_SUBDOMAIN_SUFFIX}"
        return {
            'available': True,
            'message': f'Great! Your instance will be at {full_domain}',
            'full_domain': full_domain,
        }

    @http.route('/saas/get_odoo_versions', type='jsonrpc', auth='public', website=True)
    def get_odoo_versions(self):
        """Get available Odoo versions."""
        return {
            'versions': OdooVersions.get_selection(),
            'default': OdooVersions.DEFAULT,
        }

    @http.route('/saas/get_product_ids', type='jsonrpc', auth='public', website=True)
    def get_saas_product_ids(self):
        """
        Get list of SaaS product template IDs.
        Used by JavaScript to identify which products need custom checkout.
        """
        products = request.env['product.template'].sudo().search([
            ('is_saas_plan', '=', True),
            ('sale_ok', '=', True),
        ])
        return {
            'product_ids': products.ids,
            'product_map': {p.id: '/shop/saas/configure?product_id=%s' % p.id for p in products}
        }

    @http.route('/shop/saas/configure', type='http', auth='public', website=True)
    def saas_configure(self, product_id=None, **post):
        """
        Custom page for configuring SaaS instance before adding to cart.

        This is shown when adding a SaaS plan product to cart.
        """
        product = None
        if product_id:
            product = request.env['product.template'].sudo().browse(int(product_id))
            if not product.exists() or not product.is_saas_plan:
                return request.redirect('/shop')

        values = {
            'product': product,
            'plan': product.saas_plan_id if product else None,
            'odoo_versions': OdooVersions.get_selection(),
            'default_version': OdooVersions.DEFAULT,
            'tenant_suffix': DomainConfig.TENANT_SUBDOMAIN_SUFFIX,
        }

        return request.render('saas_shop.saas_configure_page', values)

    @http.route('/shop/saas/add_to_cart', type='jsonrpc', auth='public', website=True)
    def saas_add_to_cart(self, product_id, subdomain, odoo_version, billing_cycle='monthly'):
        """
        Add SaaS product to cart with configuration.

        Args:
            product_id: Product template ID
            subdomain: Chosen subdomain
            odoo_version: Selected Odoo version
            billing_cycle: 'monthly' or 'yearly'

        Returns:
            dict: {success: bool, message: str, redirect: str}
        """
        import psycopg2
        import time

        # Validate subdomain first
        check_result = self.check_subdomain(subdomain)
        if not check_result.get('available'):
            return {
                'success': False,
                'message': check_result.get('message', 'Invalid subdomain'),
            }

        product_tmpl = request.env['product.template'].sudo().browse(int(product_id))
        if not product_tmpl.exists() or not product_tmpl.is_saas_plan:
            return {
                'success': False,
                'message': 'Invalid product',
            }

        # Find the correct variant based on billing cycle
        product = None
        for variant in product_tmpl.product_variant_ids:
            variant_cycle = product_tmpl._get_billing_cycle(variant)
            if variant_cycle == billing_cycle:
                product = variant
                break

        if not product:
            # Fallback to first variant
            product = product_tmpl.product_variant_ids[:1]

        if not product:
            return {
                'success': False,
                'message': 'No product variant available',
            }

        # Retry logic for serialization and lock errors
        max_retries = 3
        retry_delay = 0.2  # 200ms

        for attempt in range(max_retries):
            try:
                return self._do_add_to_cart(product, subdomain, odoo_version)
            except (psycopg2.errors.SerializationFailure, psycopg2.errors.LockNotAvailable) as e:
                request.env.cr.rollback()
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    _logger.info(f"Cart add retry {attempt + 1} due to: {type(e).__name__}")
                else:
                    _logger.warning("Cart add failed after retries, returning busy message")
                    return {
                        'success': False,
                        'message': 'Cart is busy, please try again',
                    }
            except psycopg2.Error as e:
                request.env.cr.rollback()
                _logger.error(f"Cart add database error: {e}")
                return {
                    'success': False,
                    'message': 'Database error, please try again',
                }
            except Exception as e:
                _logger.error(f"Cart add error: {e}")
                return {
                    'success': False,
                    'message': str(e),
                }

    def _do_add_to_cart(self, product, subdomain, odoo_version):
        """Actually perform the add to cart operation.

        Note: This method should NOT catch exceptions - let them propagate
        to the caller for retry logic to work.
        """
        # Get or create sale order (Odoo 19 uses request.cart)
        order = request.cart or request.website._create_cart()

        # Lock the order to prevent concurrent updates (SELECT FOR UPDATE)
        if order:
            request.env.cr.execute(
                "SELECT id FROM sale_order WHERE id = %s FOR UPDATE NOWAIT",
                [order.id]
            )

        # Add to cart with SaaS configuration (Odoo 19 uses _cart_add)
        result = order._cart_add(
            product_id=product.id,
            quantity=1,
        )

        # Update line with SaaS configuration
        if result.get('line_id'):
            order_line = request.env['sale.order.line'].sudo().browse(result['line_id'])
            order_line.write({
                'saas_subdomain': subdomain,
                'saas_odoo_version': odoo_version,
            })

        return {
            'success': True,
            'message': 'Added to cart',
            'redirect': '/shop/cart',
        }


class WebsiteSaleInherit(http.Controller):
    """Extend website sale for SaaS products."""

    @http.route(['/shop/cart/update_saas'], type='jsonrpc', auth='public', website=True)
    def cart_update_saas(self, line_id, subdomain=None, odoo_version=None):
        """
        Update SaaS configuration on cart line.

        Args:
            line_id: Sale order line ID
            subdomain: New subdomain
            odoo_version: New Odoo version

        Returns:
            dict: {success: bool, message: str}
        """
        order = request.cart
        if not order:
            return {'success': False, 'message': 'No cart found'}

        line = request.env['sale.order.line'].sudo().browse(int(line_id))
        if not line.exists() or line.order_id != order:
            return {'success': False, 'message': 'Invalid line'}

        if not line.is_saas_line:
            return {'success': False, 'message': 'Not a SaaS product'}

        vals = {}

        if subdomain:
            # Validate subdomain
            check_result = SaasShopController().check_subdomain(subdomain)
            if not check_result.get('available'):
                return {
                    'success': False,
                    'message': check_result.get('message', 'Invalid subdomain'),
                }
            vals['saas_subdomain'] = subdomain

        if odoo_version:
            if odoo_version not in [v[0] for v in OdooVersions.get_selection()]:
                return {'success': False, 'message': 'Invalid Odoo version'}
            vals['saas_odoo_version'] = odoo_version

        if vals:
            line.write(vals)

        return {'success': True, 'message': 'Configuration updated'}
