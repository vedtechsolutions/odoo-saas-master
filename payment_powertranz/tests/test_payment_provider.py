# -*- coding: utf-8 -*-

from odoo.tests import tagged

from .common import PowerTranzCommon


@tagged('post_install', '-at_install', 'provider_powertranz')
class TestProviderConfig(PowerTranzCommon):

    def test_provider_is_created(self):
        """Test that the PowerTranz provider is created."""
        self.assertTrue(self.powertranz, "PowerTranz provider should be created.")
        self.assertEqual(self.powertranz.code, 'powertranz', "Provider code should be 'powertranz'.")

    def test_test_mode_and_urls_computation(self):
        """Test the computation of test mode and API URLs."""
        # Initially created in test mode
        self.assertTrue(self.powertranz.powertranz_test_mode, "Provider should initially be in test mode.")
        self.assertTrue('staging' in self.powertranz.powertranz_api_url, "API URL should point to staging in test mode.")

        # Switch to enabled (production) mode
        self.powertranz.state = 'enabled'
        self.assertFalse(self.powertranz.powertranz_test_mode, "Provider should not be in test mode when enabled.")
        self.assertTrue('staging' not in self.powertranz.powertranz_api_url, "API URL should not point to staging when enabled.")
        self.assertTrue(self.powertranz.powertranz_api_url.startswith('https://ptranz.com'), "API URL should point to production when enabled.")

    def test_feature_support(self):
        """Test that feature support flags are correctly set."""
        self.assertTrue(self.powertranz.support_tokenization, "PowerTranz should support tokenization.")
        self.assertEqual(self.powertranz.support_refund, 'full_only', "PowerTranz should support full refunds only.")
        self.assertTrue(self.powertranz.support_manual_capture, "PowerTranz should support manual capture.")
        self.assertFalse(self.powertranz.support_express_checkout, "PowerTranz should not support express checkout.")

    # Add tests for webhook URL computation, credential verification (when implemented) etc. 