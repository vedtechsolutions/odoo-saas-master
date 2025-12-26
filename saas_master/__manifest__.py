# -*- coding: utf-8 -*-
{
    'name': 'SaaS Master',
    'version': '19.0.1.1.0',
    'category': 'Technical',
    'summary': 'Core SaaS Platform for Managing Tenant Instances',
    'description': """
SaaS Master Module
==================

This module provides the core functionality for the VedTech SaaS Platform:

* Subscription Plans - Define pricing tiers and resource limits
* Tenant Servers - Manage Docker host servers for customer instances
* Customer Instances - Orchestrate Odoo container deployments

Features:
---------
* Plan management with CPU, RAM, storage, and user limits
* Server health monitoring and capacity management
* Instance lifecycle management (provision, start, stop, terminate)
* Docker container orchestration via remote API
* Automatic port assignment and DNS configuration
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'website',
        'saas_core',
    ],
    'data': [
        # Security
        'security/saas_master_security.xml',
        'security/ir.model.access.csv',
        # Wizards
        'wizards/support_access_wizard_views.xml',
        # Views
        'views/saas_plan_views.xml',
        'views/saas_instance_views.xml',
        'views/saas_tenant_server_views.xml',
        'views/saas_queue_views.xml',
        'views/saas_support_access_log_views.xml',
        'views/support_approval_templates.xml',
        'views/saas_menu.xml',
        # Data
        'data/saas_plan_data.xml',
        'data/saas_queue_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
