# -*- coding: utf-8 -*-

import odoo
from odoo.addons.payment.tests.common import PaymentCommon


class PowerTranzCommon(PaymentCommon):
    """ Utility class for PowerTranz specific tests. """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        # Create PowerTranz provider
        cls.powertranz = cls._create_provider(
            'powertranz', 
            code='powertranz',
            # Add necessary credentials for mocked tests, keep state 'test'
            powertranz_id='test_merchant_id',
            powertranz_password='test_password',
            state='test', # Keep in test mode for testing API URLs etc.
        )

        # Common data (can be overridden in specific tests)
        cls.provider = cls.powertranz
        cls.currency = cls.currency_usd
        cls.partner = cls.partner_portal # Use portal user for frontend flows

        # Example processing values mimicking Odoo's payment flow
        cls.processing_values = {
            'provider_id': cls.powertranz.id,
            'reference': 'test-tx-12345',
            'amount': 11.11,
            'currency_id': cls.currency.id,
            'partner_id': cls.partner.id,
            'partner_name': cls.partner.name,
            'partner_email': cls.partner.email,
            'partner_address': cls.partner.address_get(['contact'])['contact'], # Example address
            'partner_city': cls.partner.city,
            'partner_zip': cls.partner.zip,
            'partner_state_id': cls.partner.state_id.id,
            'partner_country_id': cls.partner.country_id.id,
            'partner_phone': cls.partner.phone,
            'tokenize': False,
            'access_token': cls._generate_test_access_token(cls.partner.id, 11.11, cls.currency.id),
            # Add other values that might be passed by Odoo
            'payment_option_id': cls.payment_method_card.id, # Assuming card method exists
        }

        # Mocked PowerTranz responses (examples)
        cls.mock_auth_success_response = {
            'Approved': True,
            'IsoResponseCode': '00',
            'ResponseMessage': 'Approval',
            'TransactionID': 'mock-pt-tx-id-123',
            'AuthorizationCode': 'mock-auth-123',
            'RRN': 'mock-rrn-123',
            'SpiToken': 'mock-spi-token-123',
            'PanToken': 'mock-pan-token-123' # If tokenization occurs
        }
        cls.mock_auth_failure_response = {
            'Approved': False,
            'IsoResponseCode': '51',
            'ResponseMessage': 'Decline - Insufficient Funds',
            'TransactionID': 'mock-pt-tx-id-456',
            'SpiToken': 'mock-spi-token-456',
        }
        cls.mock_auth_3ds_challenge_response = {
            'Approved': False,
            'IsoResponseCode': '3D6',
            'ResponseMessage': '3DS Challenge Required',
            'TransactionID': 'mock-pt-tx-id-789',
            'SpiToken': 'mock-spi-token-789',
            'RiskManagement': {
                'ThreeDSecure': {
                    'RedirectData': '<form action="mock-acs-url"><input type="hidden" name="creq" value="mock-creq"></form>',
                    'MerchantResponseUrl': 'mock-merchant-response-url',
                }
            }
        }
        # Add more mocked responses for fingerprint, payment completion, etc. 