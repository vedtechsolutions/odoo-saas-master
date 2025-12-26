# -*- coding: utf-8 -*-
{
    'name': 'SaaS Helpdesk',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Support ticket management for SaaS customers',
    'description': """
SaaS Helpdesk - Support Ticket System
======================================

A complete helpdesk solution for managing SaaS customer support:

Features:
---------
* Support ticket creation and tracking
* Ticket categories and priorities
* Assignment to support agents
* Internal notes vs customer-visible messages
* SLA tracking (response time, resolution time)
* Link tickets to instances and subscriptions
* Email notifications
* Customer portal integration (via saas_portal)

Ticket States:
--------------
* New: Ticket just created
* Open: Acknowledged by support
* In Progress: Being worked on
* Pending: Waiting for customer response
* Resolved: Issue resolved, awaiting confirmation
* Closed: Ticket completed

Priority Levels:
----------------
* Low: General inquiries
* Medium: Standard issues
* High: Important issues affecting work
* Urgent: Critical issues, system down
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'saas_master',
        'saas_subscription',
    ],
    'data': [
        # Security
        'security/helpdesk_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/ticket_category_data.xml',
        'data/ticket_sequence.xml',
        'data/mail_templates.xml',
        # Views
        'views/ticket_views.xml',
        'views/ticket_category_views.xml',
        'views/helpdesk_menu.xml',
    ],
    'assets': {},
    'installable': True,
    'auto_install': False,
    'application': True,
}
