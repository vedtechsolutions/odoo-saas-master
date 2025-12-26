# -*- coding: utf-8 -*-

import json
import logging
import hmac
import hashlib
import pprint
import werkzeug

from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError

# Import security, logging, and validation tools
from odoo.addons.payment_powertranz.tools.security import mask_sensitive_data
from odoo.addons.payment_powertranz.tools.logging import log_payment_info, safe_pformat
from odoo.addons.payment_powertranz.tools.validation import (
    validate_webhook_data, sanitize_input, validate_request_parameters
)

_logger = logging.getLogger(__name__)


class PowerTranzWebhookController(http.Controller):
    """PowerTranz webhook controller for handling asynchronous notifications."""
    
    _webhook_url = '/payment/powertranz/webhook'
    
    def _enforce_https(self):
        """Enforce HTTPS for payment endpoints.
        
        This method checks if the current request is using HTTPS.
        If not, it checks if we're in development mode or using a local/development domain.
        In production, it returns a JSON response with an error message.
        
        Returns:
            dict or None: Error response if not HTTPS in production, None otherwise
        """
        # Log detailed connection information for debugging
        _logger.info(
            "Connection details - Scheme: %s, Host: %s, Path: %s, Headers: %s",
            request.httprequest.scheme,
            request.httprequest.host,
            request.httprequest.path,
            {k: v for k, v in request.httprequest.headers.items() if k.lower() in ['x-forwarded-proto', 'x-forwarded-for', 'x-real-ip', 'host']}
        )
        
        # Check for secure connection, considering proxy headers
        is_secure = request.httprequest.scheme == 'https'
        
        # Also check X-Forwarded-Proto header which is set by proxies
        forwarded_proto = request.httprequest.headers.get('X-Forwarded-Proto')
        if forwarded_proto:
            is_secure = is_secure or forwarded_proto.lower() == 'https'
        
        if not is_secure:
            # Get the current domain
            host = request.httprequest.host.split(':')[0]
            
            # Check if we're in a development/test environment
            is_dev_environment = (
                host in ['localhost', '127.0.0.1'] or  # Local development
                '.test' in host or                     # Test domain
                '.dev' in host or                      # Dev domain
                '.local' in host or                    # Local domain
                host == 'ja.klutchjaorganics.com' or   # Add your specific domain
                request.env['ir.config_parameter'].sudo().get_param('web.base.url').startswith('http://') # System configured for HTTP
            )
            
            # Log the attempt but allow it in development environments
            if is_dev_environment:
                _logger.info(
                    "HTTP connection to webhook endpoint %s allowed for domain %s",
                    request.httprequest.path,
                    host
                )
                return None
            
            # In production, enforce HTTPS
            _logger.warning(
                "Insecure connection attempt (HTTP) to webhook endpoint %s from %s",
                request.httprequest.path,
                request.httprequest.remote_addr
            )
            return {
                'error': 'security_error',
                'error_msg': _("HTTPS is required for payment processing. Please use a secure connection.")
            }
            
        # Connection is secure, proceed normally
        return None
    
    def _verify_webhook_signature(self, data, signature_header):
        """Verify the webhook signature from PowerTranz.
        
        Args:
            data: The raw request data
            signature_header: The X-PowerTranz-Signature header value
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        if not signature_header:
            _logger.warning("Missing X-PowerTranz-Signature header in webhook request")
            return False
            
        # Get all active PowerTranz providers
        providers = request.env['payment.provider'].sudo().search([('code', '=', 'powertranz')])
        
        # Try to verify with each provider's webhook secret
        for provider in providers:
            if not provider.powertranz_webhook_secret:
                continue
                
            # Compute expected signature
            secret = provider.powertranz_webhook_secret.encode('utf-8')
            expected_signature = hmac.new(
                key=secret,
                msg=data,
                digestmod=hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            if hmac.compare_digest(expected_signature, signature_header):
                return True
                
        _logger.warning("Invalid webhook signature: %s", signature_header)
        return False
    
    @http.route(_webhook_url, type='jsonrpc', auth='public', csrf=False)
    def powertranz_webhook(self):
        """Process PowerTranz webhook notifications.
        
        This endpoint receives webhook notifications from PowerTranz and processes them.
        It verifies the signature of the webhook to ensure it's from PowerTranz.
        
        Returns:
            dict: Response to PowerTranz
        """
        # Enforce HTTPS for this endpoint
        https_error = self._enforce_https()
        if https_error:
            return https_error
            
        # Get the webhook data and signature
        data = request.jsonrequest
        signature = request.httprequest.headers.get('X-PowerTranz-Signature')
        
        # Log the webhook data (masked for security)
        _logger.info(
            "Received PowerTranz webhook: %s, Headers: %s", 
            pprint.pformat(mask_sensitive_data(data)),
            {k: v for k, v in request.httprequest.headers.items() if k.lower() in ['x-powertranz-signature']}
        )
        
        # Validate webhook data structure
        is_valid, error_message = validate_webhook_data(data, raise_exception=False)
        if not is_valid:
            _logger.warning("Invalid webhook data structure: %s", error_message)
            return {'status': 'error', 'message': error_message}
        
        # Verify the webhook signature
        if not self._verify_webhook_signature(request.httprequest.data, signature):
            error_msg = "Invalid webhook signature"
            _logger.warning(error_msg)
            return {'error': 'security_error', 'error_msg': error_msg}
        
        try:
            # Process the webhook data using Odoo 19 API
            # First search for the transaction, then process
            tx = request.env['payment.transaction'].sudo()._search_by_reference('powertranz', data)
            if tx:
                tx._process('powertranz', data)
            else:
                _logger.warning("PowerTranz webhook: No transaction found for data")
            return {'status': 'ok'}
        except ValidationError as e:
            _logger.warning("Unable to handle webhook notification: %s", e)
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            _logger.exception("Error processing PowerTranz webhook")
            return {'status': 'error', 'message': str(e)}
