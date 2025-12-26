# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.addons.payment.tests.common import PaymentCommon

from .common import PowerTranzCommon


@tagged('post_install', '-at_install', 'provider_powertranz')
class TestPaymentFlow(PowerTranzCommon):

    def _create_transaction(self, amount=None, **kwargs):
        """ Helper to create a PowerTranz transaction. """
        tx = self.env['payment.transaction'].create({
            **self.processing_values,
            'amount': amount if amount is not None else self.processing_values['amount'],
            **kwargs,
        })
        return tx

    @patch('odoo.addons.payment_powertranz.models.payment_transaction.PaymentTransaction._make_powertranz_request')
    def test_direct_payment_success(self, mock_request):
        """Test a successful direct payment flow without 3DS."""
        # Assume provider does not have 3DS enabled for this test
        self.powertranz.powertranz_3ds_enabled = False
        self.powertranz.capture_manually = False # Direct Sale/Capture

        mock_request.return_value = self.mock_auth_success_response

        tx = self._create_transaction()
        tx._send_payment_request() # Trigger the payment flow

        # Assertions
        mock_request.assert_called_once()
        # Check called endpoint (should be /Auth or /Sale based on logic)
        # Check payload structure
        self.assertEqual(tx.state, 'done', "Transaction should be done after successful payment.")
        self.assertEqual(tx.provider_reference, self.mock_auth_success_response['TransactionID'])
        self.assertEqual(tx.powertranz_authorization_code, self.mock_auth_success_response['AuthorizationCode'])

    @patch('odoo.addons.payment_powertranz.models.payment_transaction.PaymentTransaction._make_powertranz_request')
    def test_direct_payment_failure(self, mock_request):
        """Test a failed direct payment flow."""
        self.powertranz.powertranz_3ds_enabled = False
        mock_request.return_value = self.mock_auth_failure_response

        tx = self._create_transaction()
        tx._send_payment_request()

        # Assertions
        mock_request.assert_called_once()
        self.assertEqual(tx.state, 'error', "Transaction should be in error state after failed payment.")
        self.assertTrue(self.mock_auth_failure_response['ResponseMessage'] in tx.state_message)

    # Add tests for manual capture flow
    # Add tests for token payment flow
    # Add tests for refund/void flows (mocking the respective requests)
    # Add tests for specific error conditions (e.g., timeout, connection error by raising exceptions in mock) 