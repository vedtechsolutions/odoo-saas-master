# -*- coding: utf-8 -*-
{
    'name': 'PowerTranz Payment Acquirer',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': 'Payment Acquirer: PowerTranz Implementation',
    'description': """
PowerTranz Payment Provider Integration for Odoo 19.
=====================================================

Provides integration with the PowerTranz payment gateway.
Features enhanced security with in-memory card data processing.
    """,
    'author': 'OdooAI (Generated)', # Replace with actual author
    'website': 'https://www.powertranz.com', # Replace with actual website if needed
    'depends': [
        'payment',
        'website_payment', # website_payment depends on website, payment depends on account
        'sale_management', # For proper integration with sales workflow
        'mail',  # Required for mail templates and chatter functionality
        'portal', # Required for customer portal access
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        # Views (must load before data that references them)
        'views/payment_provider_views.xml',
        'views/payment_powertranz_templates.xml',
        'views/payment_powertranz_inline_form.xml',
        'views/payment_transaction_views.xml',
        'views/payment_token_views.xml',
        'views/powertranz_recurring_views.xml',
        'views/portal_templates.xml',
        # Data (references views)
        'data/payment_provider_data.xml',
        'data/payment_method_line.xml',
        'data/cron.xml',
        'data/mail_templates.xml',
        'data/sequence.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_powertranz/static/src/css/payment_form.css',
            'payment_powertranz/static/src/css/card_icons.css',
            # Odoo 19 Interaction-based payment form
            'payment_powertranz/static/src/interactions/payment_form.js',
        ],
    },
    'external_dependencies': {
        'python': ['requests'], # Uncomment later
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'post_load': 'module_upgrade_hook',
} 