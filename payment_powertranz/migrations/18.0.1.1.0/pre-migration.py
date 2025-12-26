# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Add powertranz_webhook_secret column to payment_provider table.
    
    This migration script is needed because we added a new field to the payment_provider
    model but the column doesn't exist in the database yet.
    """
    if version is None:
        # Skip migration for new installations
        return
    
    _logger.info("Adding powertranz_webhook_secret column to payment_provider table")
    
    # Check if the column already exists
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'payment_provider' 
        AND column_name = 'powertranz_webhook_secret'
    """)
    
    if not cr.fetchone():
        # Add the column if it doesn't exist
        cr.execute("""
            ALTER TABLE payment_provider
            ADD COLUMN powertranz_webhook_secret VARCHAR
        """)
        _logger.info("Column powertranz_webhook_secret added successfully")
    else:
        _logger.info("Column powertranz_webhook_secret already exists, skipping")
