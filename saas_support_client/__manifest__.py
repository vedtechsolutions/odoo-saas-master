# -*- coding: utf-8 -*-
{
    'name': 'SaaS Support Client',
    'version': '19.0.1.1.0',
    'category': 'Technical',
    'summary': 'Enables secure support access to tenant instances',
    'description': """
SaaS Support Client Module
==========================

This lightweight module enables secure one-time token-based authentication
for SaaS platform support staff to access tenant instances.

Features:
- Token-based auto-login for support access
- Tokens expire after 5 minutes
- One-time use tokens (deleted after use)
- 1-hour session time limit
- Session expiry notifications to customer
- Audit logging of support access
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir.rule.xml',
    ],
    'installable': True,
    'auto_install': False,
}
