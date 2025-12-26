# -*- coding: utf-8 -*-
{
    'name': 'SaaS E-commerce Integration',
    'version': '19.0.1.0.0',
    'summary': 'E-commerce integration for SaaS platform',
    'description': """
SaaS E-commerce Integration
===========================

Integrates the SaaS platform with Odoo e-commerce:

Features:
- Product templates linked to SaaS plans
- Monthly and yearly subscription products
- Subdomain selection in checkout
- Automatic instance provisioning on order confirmation
- Add-on products (extra storage, users, etc.)

Requirements:
- website_sale module
- saas_master module
- saas_subscription module
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'category': 'Website/Website',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
        'saas_master',
        'saas_subscription',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        # Data
        'data/product_category_data.xml',
        'data/product_attribute_data.xml',
        'data/plan_product_data.xml',
        'data/cron_data.xml',
        # Views
        'views/saas_plan_views.xml',
        'views/product_template_views.xml',
        'views/product_templates.xml',
        'views/shop_templates.xml',
        'views/checkout_templates.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'saas_shop/static/src/js/checkout.js',
            'saas_shop/static/src/js/shop.js',
            'saas_shop/static/src/css/shop.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
