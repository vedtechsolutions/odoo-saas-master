# -*- coding: utf-8 -*-
"""
Support Access Controller.

Handles one-time support token authentication for SaaS support access.
"""

import logging
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SupportAccessController(http.Controller):
    """Controller for handling support access token authentication."""

    @http.route('/saas/support/login', type='http', auth='none', sitemap=False)
    def support_token_login(self, support_token=None, redirect=None, **kw):
        """
        Handle support token authentication.

        This is a separate route from /web/login to avoid conflicts
        with the original login flow.
        """
        if not support_token:
            return request.redirect('/web/login')

        # Try to validate and use the support token
        login_result = self._validate_support_token(support_token)
        if login_result:
            # Token valid - redirect to home
            _logger.info("Support access token validated successfully")
            return request.redirect(redirect or '/web')

        # Invalid token - redirect to normal login
        return request.redirect('/web/login?error=invalid_token')

    def _validate_support_token(self, token):
        """
        Validate a support access token and auto-login if valid.

        Args:
            token: The support token from URL parameter

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Search for matching token in config parameters
            ICP = request.env['ir.config_parameter'].sudo()

            # Token key pattern: saas.support_token.{first8chars}
            token_key = f'saas.support_token.{token[:8]}'
            stored_value = ICP.get_param(token_key)

            if not stored_value:
                _logger.warning(f"Support token not found: {token_key}")
                return False

            # Parse stored value: token|expiry|master_user_id
            try:
                stored_token, expiry_str, master_uid = stored_value.split('|')
            except ValueError:
                _logger.error("Invalid token format in config parameter")
                ICP.set_param(token_key, False)  # Clean up invalid token
                return False

            # Verify token matches
            if stored_token != token:
                _logger.warning("Token mismatch")
                return False

            # Check expiry
            try:
                expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                if datetime.utcnow() > expiry:
                    _logger.warning(f"Support token expired: {expiry_str}")
                    ICP.set_param(token_key, False)  # Clean up expired token
                    return False
            except ValueError:
                _logger.error("Invalid expiry date format")
                return False

            # Token valid - delete it (one-time use)
            ICP.set_param(token_key, False)

            # Find admin user to login as
            admin_user = request.env['res.users'].sudo().search([
                ('login', '=', 'admin')
            ], limit=1)

            if not admin_user:
                # Fallback: get first internal user with admin rights
                admin_user = request.env['res.users'].sudo().search([
                    ('share', '=', False),
                    ('active', '=', True),
                ], limit=1, order='id')

            if not admin_user:
                _logger.error("No admin user found for support access")
                return False

            # Perform login
            request.session.authenticate(request.db, admin_user.login, {'type': 'support_token'})

            # Log the support access
            _logger.info(
                f"Support access login: user={admin_user.login}, "
                f"master_uid={master_uid}, token={token[:8]}..."
            )

            return True

        except Exception as e:
            _logger.error(f"Error validating support token: {e}")
            return False
