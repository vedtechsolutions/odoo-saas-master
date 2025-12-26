# -*- coding: utf-8 -*-
"""
Support Login Controller.

Handles one-time token-based authentication for SaaS support access.
Includes session time limits and expiry notifications.
"""

import logging
from datetime import datetime

from odoo import http, SUPERUSER_ID, api
from odoo.http import request
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class SupportLoginController(http.Controller):
    """Controller for support token-based auto-login."""

    @http.route('/support/login', type='http', auth='none', csrf=False, sitemap=False)
    def support_login(self, token=None, **kw):
        """
        Handle support token login.

        Validates the one-time token and auto-authenticates as admin.
        Creates a time-limited support session.
        """
        if not token:
            _logger.warning("Support login attempt without token")
            return request.redirect('/web/login?support_error=missing_token')

        db = request.db
        if not db:
            return request.redirect('/web/database/selector')

        # Validate token and get user to login as
        result = self._validate_and_consume_token(db, token)

        if not result:
            return request.redirect('/web/login?support_error=invalid_token')

        user_id, user_login, master_uid, master_callback_url = result

        # Perform login
        try:
            self._authenticate_user(db, user_id, user_login)

            # Create support session with time limit
            self._create_support_session(db, user_id, master_uid, master_callback_url)

            _logger.info(f"Support login successful for user_id={user_id} on db={db}")
            return request.redirect('/web')
        except Exception as e:
            _logger.error(f"Support login authentication failed: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            return request.redirect('/web/login?support_error=auth_failed')

    def _validate_and_consume_token(self, db, token):
        """
        Validate support token and return (user_id, user_login, master_uid, callback_url).

        Returns None if token is invalid or expired.
        """
        try:
            registry = Registry(db)

            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Look for token in config parameters
                ICP = env['ir.config_parameter']
                token_key = f'saas.support_token.{token[:8]}'
                stored_value = ICP.get_param(token_key)

                if not stored_value:
                    _logger.warning(f"Token not found: {token_key}")
                    return None

                # Parse: full_token|expiry|master_uid:::callback_url
                # The ::: delimiter separates the callback URL which may contain special chars
                try:
                    # First split by ::: to separate callback URL
                    if ':::' in stored_value:
                        main_part, callback_url = stored_value.split(':::', 1)
                    else:
                        main_part = stored_value
                        callback_url = None

                    # Now split the main part by |
                    parts = main_part.split('|')
                    stored_token = parts[0]
                    expiry_str = parts[1]
                    master_uid = int(parts[2]) if len(parts) > 2 else 0

                except (ValueError, IndexError) as e:
                    _logger.error(f"Malformed token data: {e}, value={stored_value[:50]}...")
                    ICP.set_param(token_key, False)
                    return None

                # Verify full token matches
                if stored_token != token:
                    _logger.warning("Token value mismatch")
                    return None

                # Check expiry
                expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                if datetime.utcnow() > expiry:
                    _logger.warning(f"Token expired at {expiry_str}")
                    ICP.set_param(token_key, False)
                    return None

                # Token is valid - consume it (one-time use)
                ICP.set_param(token_key, False)

                # Find admin user to login as
                User = env['res.users']
                admin = User.search([('login', '=', 'admin'), ('active', '=', True)], limit=1)
                if not admin:
                    admin = User.search([('share', '=', False), ('active', '=', True)], limit=1, order='id')

                if not admin:
                    _logger.error("No admin user found")
                    return None

                _logger.info(f"Token validated. Will login as {admin.login} (master_uid={master_uid})")
                return (admin.id, admin.login, master_uid, callback_url)

        except Exception as e:
            _logger.error(f"Token validation error: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            return None

    def _authenticate_user(self, db, user_id, user_login):
        """
        Authenticate the session for the given user without password.

        Uses Odoo's internal session mechanisms.
        """
        registry = Registry(db)

        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            user = env['res.users'].browse(user_id)

            if not user.exists():
                raise ValueError(f"User {user_id} not found")

            # Get fresh session token
            session_token = user._compute_session_token(request.session.sid)

            # Update session
            request.session.db = db
            request.session.uid = user_id
            request.session.login = user_login
            request.session.session_token = session_token

            # Rotate session for security
            request.session.should_rotate = True

            _logger.info(f"Session established for {user_login}")

    def _create_support_session(self, db, user_id, master_uid, callback_url):
        """Create a time-limited support session."""
        try:
            registry = Registry(db)

            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Check if model exists (module might not be fully installed)
                if 'saas.support.session' not in env:
                    _logger.warning("Support session model not available yet")
                    return None

                SupportSession = env['saas.support.session']
                session = SupportSession.create_session(
                    user_id=user_id,
                    master_uid=master_uid,
                    session_id=request.session.sid,
                    master_callback_url=callback_url,
                )

                # Store session info in HTTP session for validation
                request.session['support_session_id'] = session.id
                request.session['support_session_expiry'] = session.expiry_time.isoformat()

                _logger.info(f"Support session created: {session.id}, expires: {session.expiry_time}")
                return session

        except Exception as e:
            _logger.error(f"Failed to create support session: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            return None

    @http.route('/support/session/status', type='jsonrpc', auth='user', csrf=False)
    def session_status(self):
        """Check current support session status."""
        session_id = request.session.get('support_session_id')
        if not session_id:
            return {'active': False, 'reason': 'no_session'}

        try:
            SupportSession = request.env['saas.support.session'].sudo()
            session = SupportSession.browse(session_id)

            if not session.exists():
                return {'active': False, 'reason': 'session_not_found'}

            if session.state != 'active':
                return {'active': False, 'reason': session.state}

            if session.is_expired:
                session.end_session(reason='expired')
                return {'active': False, 'reason': 'expired'}

            return {
                'active': True,
                'time_remaining_minutes': session.time_remaining_minutes,
                'expiry_time': session.expiry_time.isoformat(),
            }
        except Exception as e:
            _logger.error(f"Session status check failed: {e}")
            return {'active': False, 'reason': 'error'}

    @http.route('/support/session/end', type='jsonrpc', auth='user', csrf=False)
    def end_session(self):
        """End the current support session (logout)."""
        session_id = request.session.get('support_session_id')
        if not session_id:
            return {'success': False, 'reason': 'no_session'}

        try:
            SupportSession = request.env['saas.support.session'].sudo()
            session = SupportSession.browse(session_id)

            if session.exists() and session.state == 'active':
                session.end_session(reason='ended')
                _logger.info(f"Support session {session_id} ended by user")

            # Clear session data
            request.session.pop('support_session_id', None)
            request.session.pop('support_session_expiry', None)

            return {'success': True}
        except Exception as e:
            _logger.error(f"Session end failed: {e}")
            return {'success': False, 'reason': str(e)}

    @http.route('/support/logout', type='http', auth='user', csrf=False)
    def support_logout(self):
        """Logout and end support session, then redirect to login."""
        # End the support session
        session_id = request.session.get('support_session_id')
        if session_id:
            try:
                SupportSession = request.env['saas.support.session'].sudo()
                session = SupportSession.browse(session_id)
                if session.exists() and session.state == 'active':
                    session.end_session(reason='ended')
            except Exception as e:
                _logger.error(f"Error ending support session on logout: {e}")

        # Perform standard logout
        request.session.logout()
        return request.redirect('/web/login?support_logout=1')
