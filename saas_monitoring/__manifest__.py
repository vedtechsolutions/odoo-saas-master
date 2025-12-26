# -*- coding: utf-8 -*-
{
    'name': 'SaaS Monitoring',
    'version': '19.0.1.0.0',
    'category': 'Services/SaaS',
    'summary': 'Usage monitoring and alerting for SaaS instances',
    'description': """
SaaS Monitoring - Usage Tracking & Alerts
==========================================

Monitor and track resource usage for all SaaS tenant instances:

Features:
---------
* Real-time usage metrics collection
* Historical usage data and trends
* Plan limit enforcement
* Alert system for threshold violations
* Usage reports and dashboards
* Automated metric collection via cron

Tracked Metrics:
----------------
* CPU usage percentage
* Memory (RAM) usage
* Disk space usage
* Database size
* Bandwidth consumption
* Active user count
* API call count
* Background job count

Alert Types:
------------
* Warning: 80% of limit reached
* Critical: 90% of limit reached
* Exceeded: Over plan limit
    """,
    'author': 'VedTech Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'saas_master',
    ],
    'data': [
        # Security
        'security/monitoring_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/metric_type_data.xml',
        'data/cron_data.xml',
        # Views (order matters - actions must be defined before referenced)
        'views/usage_log_views.xml',
        'views/usage_metric_views.xml',
        'views/alert_views.xml',
        'views/monitoring_menu.xml',
    ],
    'assets': {},
    'installable': True,
    'auto_install': False,
    'application': False,
}
