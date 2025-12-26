# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from odoo.tests import tagged

from .common import PowerTranzCommon


@tagged('post_install', '-at_install', 'provider_powertranz')
class TestTokenization(PowerTranzCommon):

    # TODO: Test token creation during successful payment
    # TODO: Test payment using a saved token
    # TODO: Test token deletion/management (if applicable via UI/portal)

    pass 