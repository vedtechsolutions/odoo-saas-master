# -*- coding: utf-8 -*-
{
    'name': 'SaaS Subscription Management',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Subscription billing and management for SaaS instances',
    'description': """
SaaS Subscription Management
============================

Manages subscription lifecycle for SaaS customers:

Features:
---------
* Subscription billing cycles (monthly/yearly)
* Trial period management
* Subscription state transitions
* Integration with saas.instance
* Customer subscription history
* Billing date tracking
* Payment integration hooks

Subscription States:
--------------------
* Draft: Subscription created but not activated
* Trial: In trial period
* Active: Paid and active
* Past Due: Payment overdue
* Suspended: Temporarily suspended
* Cancelled: Cancelled by customer
* Expired: Trial or subscription expired
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'saas_master',
        'account',
        'sale',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        'security/ir.rule.xml',
        # Data
        'data/mail_templates.xml',
        'data/mail_template_password_reset.xml',
        'data/cron_jobs.xml',
        # Views
        'views/saas_subscription_views.xml',
    ],
    'assets': {},
    'installable': True,
    'auto_install': False,
    'application': False,
}
