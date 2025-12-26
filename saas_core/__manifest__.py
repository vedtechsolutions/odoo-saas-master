# -*- coding: utf-8 -*-
{
    'name': 'SaaS Core',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Core constants, utilities, and mixins for SaaS platform',
    'description': """
SaaS Core Module
================

Foundation module providing shared resources for all SaaS modules:

* **Constants**: Model names, field names, states, configuration
* **Validators**: Subdomain validation, email normalization
* **Mixins**: Audit trails, status management

This module has no dependencies on other SaaS modules and serves as the
single source of truth for all SaaS-related constants and utilities.
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'data/security_config.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
