# -*- coding: utf-8 -*-
{
    'name': 'VEDTECH Website Assets',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'summary': 'SVG mockups and visual assets for VEDTECH website',
    'description': """
VEDTECH Website Assets
======================

Professional SVG mockups and visual elements for the VEDTECH website:

**Included Assets:**
- Dashboard mockup (browser window with SaaS dashboard)
- Hero section background pattern
- Success/checkmark animation
- Wave divider
- Feature icons sprite sheet

**Design Principles Applied:**
- Figma-style modern SaaS design
- Responsive SVG graphics
- Subtle animations and micro-interactions
- Professional color scheme
- Trust-building visual elements
    """,
    'author': 'VEDTECH Solutions',
    'website': 'https://vedtechsolutions.com',
    'license': 'LGPL-3',
    'depends': ['website'],
    'data': [],
    'assets': {
        'web.assets_frontend': [
            'website_assets/static/src/img/dashboard-mockup.svg',
            'website_assets/static/src/img/hero-pattern.svg',
            'website_assets/static/src/img/success-check.svg',
            'website_assets/static/src/img/wave-divider.svg',
            'website_assets/static/src/img/feature-icons.svg',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
