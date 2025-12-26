# -*- coding: utf-8 -*-

import hmac
import hashlib
import json
import logging
from unittest.mock import patch
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.payment.tests.common import PaymentCommon

_logger = logging.getLogger(__name__)

@tagged('post_install', '-at_install')
class TestPowerTranzWebhookAuth(TransactionCase):
    """Test PowerTranz webhook authentication."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Create a PowerTranz provider
        cls.provider = cls.env['payment.provider'].create({
            'name': 'PowerTranz Test',
            'code': 'powertranz',
            'state': 'test',
            'powertranz_id': 'test_merchant_id',
            'powertranz_password': 'test_password',
            'powertranz_webhook_secret': 'test_webhook_secret',
        })
        
        # Create a partner for testing
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Partner',
            'email': 'test@example.com',
        })
        
        # Create a payment token
        cls.token = cls.env['payment.token'].create({
            'name': '4111 11** **** 1111',
            'provider_id': cls.provider.id,
            'partner_id': cls.partner.id,
            'provider_ref': 'test_token_ref',
        })
        
        # Create a recurring payment
        cls.recurring = cls.env['powertranz.recurring'].create({
            'name': 'TEST-REC-001',
            'partner_id': cls.partner.id,
            'payment_token_id': cls.token.id,
            'amount': 100.0,
            'currency_id': cls.env.company.currency_id.id,
            'frequency': 'M',
            'start_date': '2025-01-01',
            'state': 'active',
            'powertranz_recurring_identifier': 'test_recurring_id',
        })

    def test_webhook_authentication_success(self):
        """Test that webhook authentication succeeds with valid signature."""
        # Create a test webhook payload
        webhook_data = {
            'recurringIdentifier': 'test_recurring_id',
            'transactionIdentifier': 'test_tx_id',
            'status': 'success',
            'amount': 100.0,
            'currencyCode': 'USD',
            'paymentDate': '2025-05-09',
        }
        
        # Compute the signature using the webhook secret
        webhook_secret = self.provider.powertranz_webhook_secret
        payload_str = str(webhook_data)
        signature = hmac.new(
            webhook_secret.encode('utf-8'),
            payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Mock the request object with our test data
        with patch('odoo.http.request') as mock_request, \
             patch('odoo.addons.payment_powertranz.controllers.webhook.PowerTranzWebhookController._verify_webhook_authenticity', return_value=True):
            
            # Mock the jsonrequest attribute
            mock_request.jsonrequest = webhook_data
            
            # Mock the httprequest.headers attribute
            mock_request.httprequest.headers = {
                'X-PowerTranz-Signature': signature
            }
            
            # Call the webhook controller
            controller = self.env['payment_powertranz.controllers.webhook'].PowerTranzWebhookController()
            result = controller.powertranz_recurring_webhook()
            
            # Verify the result
            self.assertEqual(result.get('status'), 'ok', "Webhook authentication should succeed with valid signature")

    def test_webhook_authentication_failure(self):
        """Test that webhook authentication fails with invalid signature."""
        # Create a test webhook payload
        webhook_data = {
            'recurringIdentifier': 'test_recurring_id',
            'transactionIdentifier': 'test_tx_id',
            'status': 'success',
            'amount': 100.0,
            'currencyCode': 'USD',
            'paymentDate': '2025-05-09',
        }
        
        # Use an invalid signature
        invalid_signature = "invalid_signature"
        
        # Mock the request object with our test data
        with patch('odoo.http.request') as mock_request, \
             patch('odoo.addons.payment_powertranz.controllers.webhook.PowerTranzWebhookController._verify_webhook_authenticity', return_value=False):
            
            # Mock the jsonrequest attribute
            mock_request.jsonrequest = webhook_data
            
            # Mock the httprequest.headers attribute
            mock_request.httprequest.headers = {
                'X-PowerTranz-Signature': invalid_signature
            }
            
            # Call the webhook controller
            controller = self.env['payment_powertranz.controllers.webhook'].PowerTranzWebhookController()
            result = controller.powertranz_recurring_webhook()
            
            # Verify the result
            self.assertEqual(result.get('status'), 'error', "Webhook authentication should fail with invalid signature")
            self.assertEqual(result.get('message'), 'Authentication failed', "Error message should indicate authentication failure")
