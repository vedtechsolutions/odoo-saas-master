# -*- coding: utf-8 -*-

import logging
import json
from datetime import datetime, timedelta
from odoo.tests.common import TransactionCase
from odoo.addons.payment.tests.common import PaymentCommon
from odoo import fields

_logger = logging.getLogger(__name__)

class TestPowerTranzMerchantRecurring(TransactionCase):
    """Test cases for PowerTranz merchant-managed recurring payments."""
    
    def setUp(self):
        super().setUp()
        
        # Create a test partner
        self.partner = self.env['res.partner'].create({
            'name': 'Test Partner',
            'email': 'test@example.com',
        })
        
        # Create a PowerTranz payment provider
        self.powertranz_provider = self.env['payment.provider'].create({
            'name': 'PowerTranz Test',
            'code': 'powertranz',
            'state': 'test',
            'powertranz_merchant_id': 'test_merchant',
            'powertranz_merchant_password': 'test_password',
            'powertranz_api_key': 'test_api_key',
            'powertranz_api_url': 'https://test.api.powertranz.com',
        })
        
        # Create a payment token
        self.token = self.env['payment.token'].create({
            'name': 'Test Token',
            'partner_id': self.partner.id,
            'provider_id': self.powertranz_provider.id,
            'provider_ref': 'test_token_ref',
            'powertranz_card_brand': 'Visa',
            'powertranz_masked_pan': '411111******1111',
        })
        
    def test_create_recurring_payment(self):
        """Test creating a merchant-managed recurring payment."""
        # Create a transaction with tokenization
        tx = self.env['payment.transaction'].create({
            'reference': 'TEST/TX/01',
            'provider_id': self.powertranz_provider.id,
            'partner_id': self.partner.id,
            'amount': 100.0,
            'currency_id': self.env.ref('base.USD').id,
            'tokenize': True,
            'token_id': self.token.id,
        })
        
        # Simulate recurring payment data from the payment form
        recurring_data = {
            'frequency': 'M',  # Monthly
            'management_type': 'merchant',
            'start_date': fields.Date.today(),
            'description': 'Test Recurring Payment',
        }
        
        # Create the recurring payment
        recurring = tx._create_recurring_payment(self.token, recurring_data)
        
        # Verify the recurring payment was created correctly
        self.assertTrue(recurring, "Recurring payment should be created")
        self.assertEqual(recurring.partner_id, self.partner, "Partner should match")
        self.assertEqual(recurring.payment_token_id, self.token, "Token should match")
        self.assertEqual(recurring.amount, 100.0, "Amount should match")
        self.assertEqual(recurring.frequency, 'M', "Frequency should be monthly")
        self.assertEqual(recurring.management_type, 'merchant', "Management type should be merchant")
        self.assertEqual(recurring.state, 'active', "State should be active")
        
        # Test the cron job for processing recurring payments
        # First, set the next payment date to today to trigger processing
        recurring.write({'next_payment_date': fields.Date.today()})
        
        # Run the cron job
        self.env['powertranz.recurring']._cron_process_recurring_payments()
        
        # Verify a new transaction was created
        transactions = self.env['payment.transaction'].search([
            ('powertranz_recurring_id', '=', recurring.id)
        ])
        
        self.assertTrue(transactions, "At least one transaction should be created")
        
        # Verify the next payment date was updated
        self.assertNotEqual(recurring.next_payment_date, fields.Date.today(), 
                           "Next payment date should be updated after processing")
        
    def test_retry_failed_payment(self):
        """Test the retry mechanism for failed recurring payments."""
        # Create a recurring payment
        recurring = self.env['powertranz.recurring'].create({
            'name': 'TEST/RECURRING/01',
            'partner_id': self.partner.id,
            'payment_token_id': self.token.id,
            'amount': 100.0,
            'currency_id': self.env.ref('base.USD').id,
            'frequency': 'M',
            'management_type': 'merchant',
            'start_date': fields.Date.today(),
            'state': 'active',
            'next_payment_date': fields.Date.today(),
        })
        
        # Simulate a failed payment by setting the retry count and last retry date
        recurring.write({
            'retry_count': 1,
            'last_retry_date': fields.Date.today() - timedelta(days=4),  # More than retry_days (default 3)
            'last_payment_status': 'failed',
        })
        
        # Run the cron job
        self.env['powertranz.recurring']._cron_process_recurring_payments()
        
        # Verify a new transaction was created for the retry
        transactions = self.env['payment.transaction'].search([
            ('powertranz_recurring_id', '=', recurring.id)
        ])
        
        self.assertTrue(transactions, "A retry transaction should be created")
        
        # Verify the retry count was incremented
        self.assertEqual(recurring.retry_count, 2, 
                        "Retry count should be incremented after a failed payment")
