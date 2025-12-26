# -*- coding: utf-8 -*-
{
    'name': 'SaaS Backup',
    'version': '19.0.1.0.0',
    'category': 'Services/SaaS',
    'summary': 'Backup management for SaaS instances',
    'description': """
SaaS Backup - Instance Backup & Restore
========================================

Manage backups for all SaaS tenant instances:

Features:
---------
* Automated scheduled backups
* Manual backup on demand
* Database + filestore backup
* Retention policies by plan tier
* S3/cloud storage integration
* Backup verification
* Point-in-time restore
* Backup download for customers

Retention by Plan:
------------------
* Trial: 3 days
* Starter: 7 days
* Professional: 30 days
* Enterprise: 90 days

Backup Types:
-------------
* Full: Complete database + filestore
* Database: Database only
* Filestore: Filestore only
* Incremental: Changes since last backup
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'saas_core',
        'saas_master',
    ],
    'data': [
        # Security (main models)
        'security/backup_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence_data.xml',
        'data/cron_data.xml',
        'data/backup_schedule_data.xml',
        'data/mail_templates.xml',
        # Wizards
        'wizard/backup_restore_wizard_views.xml',
        # Wizard Security (loaded after wizard model is registered)
        'security/wizard_security.xml',
        # Views
        'views/backup_views.xml',
        'views/backup_schedule_views.xml',
        'views/instance_backup_views.xml',
        'views/backup_menu.xml',
    ],
    'assets': {},
    'installable': True,
    'auto_install': False,
    'application': False,
}
