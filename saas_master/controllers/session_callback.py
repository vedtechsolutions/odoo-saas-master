# -*- coding: utf-8 -*-
"""
Support Session Callback Controller.

Handles callbacks from tenant instances when support sessions end.
"""

import logging
import json

from odoo import http, fields, SUPERUSER_ID, api
from odoo.http import request

_logger = logging.getLogger(__name__)


class SessionCallbackController(http.Controller):
    """Controller for support session end callbacks."""

    @http.route(
        '/support/session/callback/<int:instance_id>',
        type='jsonrpc',
        auth='none',
        csrf=False,
        methods=['POST'],
    )
    def session_end_callback(self, instance_id, **kw):
        """
        Receive callback when support session ends on tenant.

        Updates audit log and sends notification to customer.
        """
        try:
            # For type='jsonrpc' routes, the params are passed as kwargs
            # The JSON-RPC params are already extracted by Odoo
            data = kw

            _logger.info(f"Session callback received for instance {instance_id}: {data}")

            # Process in sudo mode
            db = request.db
            if not db:
                return {'success': False, 'error': 'No database'}

            registry = request.env.registry
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Find the instance
                instance = env['saas.instance'].browse(instance_id)
                if not instance.exists():
                    _logger.warning(f"Instance {instance_id} not found for callback")
                    return {'success': False, 'error': 'Instance not found'}

                # Extract session data
                session_data = {
                    'session_id': data.get('session_id'),
                    'master_uid': data.get('master_uid'),
                    'user_id': data.get('user_id'),
                    'user_login': data.get('user_login'),
                    'start_time': data.get('start_time'),
                    'end_time': data.get('end_time'),
                    'duration_minutes': data.get('duration_minutes', 0),
                    'state': data.get('state', 'ended'),
                }

                # Update audit log
                self._update_audit_log(env, instance, session_data)

                # Send notification to customer
                self._send_session_end_notification(env, instance, session_data)

                _logger.info(f"Session callback processed for instance {instance_id}")
                return {'success': True}

        except Exception as e:
            _logger.error(f"Session callback failed: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    def _update_audit_log(self, env, instance, session_data):
        """Update the support access log with session end info."""
        try:
            # Find the most recent access log for this instance
            AccessLog = env['saas.support.access.log']
            log = AccessLog.search([
                ('instance_id', '=', instance.id),
                ('accessed_by_id', '=', session_data.get('master_uid')),
            ], limit=1, order='access_time desc')

            if log:
                # Update with session end info
                end_time = session_data.get('end_time')
                if end_time:
                    try:
                        from datetime import datetime
                        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                        log.write({
                            'session_end_time': end_dt,
                            'session_duration_minutes': session_data.get('duration_minutes', 0),
                            'session_end_reason': session_data.get('state', 'ended'),
                        })
                        _logger.info(f"Updated access log {log.id} with session end info")
                    except Exception as e:
                        _logger.error(f"Failed to parse end time: {e}")
            else:
                _logger.warning(f"No access log found for instance {instance.id}")

        except Exception as e:
            _logger.error(f"Failed to update audit log: {e}")

    def _send_session_end_notification(self, env, instance, session_data):
        """Send email to customer when support session ends."""
        try:
            # Get decrypted email (admin_email is an encrypted field)
            customer_email = instance._get_decrypted_value('admin_email')
            if not customer_email:
                _logger.warning(f"No admin email for instance {instance.subdomain}")
                return

            # Get support user name
            support_user = env['res.users'].browse(session_data.get('master_uid'))
            support_name = support_user.name if support_user.exists() else 'Support Team'

            duration = session_data.get('duration_minutes', 0)
            end_reason = session_data.get('state', 'ended')

            if end_reason == 'expired':
                reason_text = 'Session timed out after 1 hour'
            else:
                reason_text = 'Support logged out'

            subject = f"Support Session Ended: {instance.name}"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #28a745;">Support Session Ended</h2>
                <p>The support session for your Odoo instance has ended.</p>

                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Instance:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{instance.name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Support Representative:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{support_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Session Duration:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{duration} minutes</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>End Reason:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{reason_text}</td>
                    </tr>
                </table>

                <p style="color: #666; font-size: 12px;">
                    This notification is automatically generated for your security and audit purposes.
                    All support access is logged.
                </p>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #999; font-size: 11px;">
                    VedTech Solutions SaaS Platform
                </p>
            </div>
            """

            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': customer_email,
                'email_from': env.company.email or 'noreply@vedtechsolutions.com',
                'auto_delete': True,
            }
            mail = env['mail.mail'].create(mail_values)
            mail.send()

            _logger.info(f"Session end notification sent to {customer_email}")

        except Exception as e:
            _logger.error(f"Failed to send session end notification: {e}")
