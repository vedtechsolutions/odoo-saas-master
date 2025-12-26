# -*- coding: utf-8 -*-
"""
Support Access Approval Controller.

Handles public endpoints for customers to approve/deny support access requests.
"""

import logging

from odoo import http, fields, SUPERUSER_ID, api
from odoo.http import request

_logger = logging.getLogger(__name__)


class SupportApprovalController(http.Controller):
    """Controller for support access approval workflow."""

    @http.route('/support/approve/<string:token>', type='http', auth='public', website=True, sitemap=False)
    def approve_support_access(self, token, **kw):
        """
        Public page for customer to approve support access.

        Shows request details and approve/deny buttons.
        """
        # Find the request by token
        access_request = request.env['saas.support.access.request'].sudo().search([
            ('approval_token', '=', token),
        ], limit=1)

        if not access_request:
            return request.render('saas_master.support_approval_invalid', {
                'error': 'Invalid or expired approval link.',
            })

        # Check if already processed
        if access_request.state != 'pending':
            return request.render('saas_master.support_approval_processed', {
                'access_request': access_request,
                'state': access_request.state,
            })

        # Check if expired
        if fields.Datetime.now() > access_request.token_expiry:
            access_request.state = 'expired'
            return request.render('saas_master.support_approval_expired', {
                'access_request': access_request,
            })

        # Show approval page
        return request.render('saas_master.support_approval_page', {
            'access_request': access_request,
            'token': token,
        })

    @http.route('/support/approve/<string:token>/confirm', type='http', auth='public', methods=['POST'], csrf=False, sitemap=False)
    def confirm_approval(self, token, action='approve', **kw):
        """
        Process the approval or denial.
        """
        access_request = request.env['saas.support.access.request'].sudo().search([
            ('approval_token', '=', token),
            ('state', '=', 'pending'),
        ], limit=1)

        if not access_request:
            return request.redirect('/support/approve/' + token)

        # Check expiry
        if fields.Datetime.now() > access_request.token_expiry:
            access_request.state = 'expired'
            return request.redirect('/support/approve/' + token)

        if action == 'approve':
            access_request.action_approve()
            return request.render('saas_master.support_approval_success', {
                'access_request': access_request,
                'action': 'approved',
            })
        else:
            access_request.action_deny()
            return request.render('saas_master.support_approval_success', {
                'access_request': access_request,
                'action': 'denied',
            })
