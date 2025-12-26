# -*- coding: utf-8 -*-
{
    'name': 'SaaS Customer Portal',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'summary': 'Customer Portal for Managing SaaS Instances',
    'description': """
SaaS Customer Portal
====================

Extends the Odoo portal to allow customers to manage their SaaS services:

Features:
---------
* View and monitor SaaS instances
* Access instance URLs directly
* View subscription details and billing history
* Create and track support tickets
* Download invoices
* Manage account settings

Portal Pages:
-------------
* /my/instances - List of customer instances
* /my/instances/<id> - Instance detail view
* /my/subscriptions - List of subscriptions
* /my/subscriptions/<id> - Subscription detail
* /my/tickets - Support ticket list
* /my/tickets/<id> - Ticket detail
* /my/tickets/new - Create new ticket
* /my/instances/<id>/backups - Instance backup list (read-only)
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'portal',
        'website',
        'saas_master',
        'saas_subscription',
        'saas_helpdesk',
        'saas_backup',
    ],
    'data': [
        # Security
        'security/portal_security.xml',
        'security/ir.model.access.csv',
        # Views/Templates
        'views/portal_templates.xml',
        'views/portal_instance_templates.xml',
        'views/portal_subscription_templates.xml',
        'views/portal_ticket_templates.xml',
        'views/portal_backup_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'saas_portal/static/src/css/portal.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
