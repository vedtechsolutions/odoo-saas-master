# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from odoo.tests import tagged

from .common import PowerTranzCommon


@tagged('post_install', '-at_install', 'provider_powertranz')
class Test3DSFlows(PowerTranzCommon):

    # TODO: Test Frictionless Flow
    # TODO: Test Fingerprint Flow -> Authenticate call
    # TODO: Test Challenge Flow -> Merchant Response -> Payment call
    # TODO: Test Failed 3DS flows

    pass 