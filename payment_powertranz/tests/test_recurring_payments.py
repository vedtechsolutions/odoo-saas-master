# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from odoo.tests import tagged

from .common import PowerTranzCommon


@tagged('post_install', '-at_install', 'provider_powertranz')
class TestRecurringPayments(PowerTranzCommon):

    # TODO: Test Merchant Managed recurring setup (initial payment)
    # TODO: Test Merchant Managed subsequent payment (using token)
    # TODO: Test PowerTranz Managed recurring setup (initial payment)
    # TODO: Test PowerTranz Managed webhook notification processing (success, failure, cancel)
    # TODO: Test PowerTranz Managed cancellation via API call

    pass 