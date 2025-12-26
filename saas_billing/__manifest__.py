# -*- coding: utf-8 -*-
{
    'name': 'SaaS Billing',
    'version': '19.0.1.0.0',
    'category': 'Services/SaaS',
    'summary': 'Billing extensions for SaaS platform',
    'description': """
SaaS Billing - Payment & Invoice Management
============================================

Extends Odoo billing capabilities for SaaS subscriptions:

Features:
---------
* Payment transaction tracking
* Retry logic for failed payments
* Customer credit/wallet system
* Proration for plan changes
* Usage-based overage billing
* Invoice extensions for SaaS
* Revenue analytics (MRR/ARR)
* Dunning management

Payment Flow:
-------------
1. Invoice generated from subscription
2. Payment attempted via gateway
3. Success: Update subscription, send receipt
4. Failure: Retry queue, dunning emails
5. Max retries: Suspend subscription

Credit System:
--------------
* Prepaid credits for usage
* Refund credits for downgrades
* Promotional credits
* Credit expiration tracking
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'account',
        'saas_core',
        'saas_subscription',
    ],
    'data': [
        # Security
        'security/billing_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence_data.xml',
        'data/cron_data.xml',
        # Views
        'views/billing_transaction_views.xml',
        'views/customer_credit_views.xml',
        'views/account_move_views.xml',
        'views/subscription_billing_views.xml',
        'views/billing_menu.xml',
    ],
    'assets': {},
    'installable': True,
    'auto_install': False,
    'application': False,
}
