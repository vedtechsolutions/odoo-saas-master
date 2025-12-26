# -*- coding: utf-8 -*-
"""
Reserved subdomain constants.

Usage:
    from odoo.addons.saas_core.constants.reserved import RESERVED_SUBDOMAINS
    if subdomain in RESERVED_SUBDOMAINS:
        raise ValidationError("Subdomain is reserved")
"""

# Reserved subdomains that cannot be used by customers
RESERVED_SUBDOMAINS = frozenset([
    # System and admin
    'admin',
    'administrator',
    'api',
    'app',
    'apps',
    'auth',
    'billing',
    'cdn',
    'config',
    'console',
    'dashboard',
    'dev',
    'development',
    'docs',
    'documentation',

    # Common services
    'email',
    'ftp',
    'git',
    'help',
    'helpdesk',
    'imap',
    'mail',
    'mx',
    'ns',
    'ns1',
    'ns2',
    'pop',
    'pop3',
    'smtp',
    'ssh',
    'ssl',
    'status',
    'support',
    'vpn',

    # Web and infrastructure
    'blog',
    'demo',
    'download',
    'downloads',
    'forum',
    'home',
    'news',
    'portal',
    'shop',
    'staging',
    'static',
    'store',
    'test',
    'testing',
    'web',
    'webmail',
    'www',

    # VedTech specific
    'master',
    'platform',
    'saas',
    'tenant',
    'tenants',
    'vedtech',

    # Security and abuse prevention
    'abuse',
    'admin',
    'hostmaster',
    'info',
    'mailer-daemon',
    'nobody',
    'noc',
    'postmaster',
    'root',
    'security',
    'usenet',
    'uucp',
    'webmaster',

    # Common business terms
    'account',
    'accounts',
    'login',
    'logout',
    'register',
    'signup',
    'signin',
    'subscribe',
    'unsubscribe',

    # Reserved for future
    'backup',
    'backups',
    'client',
    'clients',
    'customer',
    'customers',
    'instance',
    'instances',
    'server',
    'servers',
])

# Patterns that are blocked (regex patterns)
BLOCKED_SUBDOMAIN_PATTERNS = [
    r'^test\d*$',       # test, test1, test2, etc.
    r'^demo\d*$',       # demo, demo1, demo2, etc.
    r'^temp\d*$',       # temp, temp1, temp2, etc.
    r'^tmp\d*$',        # tmp, tmp1, tmp2, etc.
    r'^admin\d*$',      # admin, admin1, admin2, etc.
    r'^user\d*$',       # user, user1, user2, etc.
    r'^\d+$',           # purely numeric subdomains
    r'^-',              # starting with hyphen
    r'-$',              # ending with hyphen
    r'--',              # double hyphens
]
