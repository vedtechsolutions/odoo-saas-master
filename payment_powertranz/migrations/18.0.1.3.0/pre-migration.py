# -*- coding: utf-8 -*-

import logging
from odoo import api, SUPERUSER_ID
from psycopg2 import sql

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Remove sensitive card data fields from the payment transaction table and erase existing data."""
    
    _logger.info("Running pre-migration to remove sensitive card data from database")
    
    # List of fields to check and remove
    card_data_fields = [
        'powertranz_card_number', 
        'powertranz_card_holder', 
        'powertranz_card_expiry_month', 
        'powertranz_card_expiry_year', 
        'powertranz_card_cvc'
    ]
    
    # Check if the fields exist and clean up any data before removing them
    for field in card_data_fields:
        # Check if field exists
        cr.execute(
            sql.SQL("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s"),
            ('payment_transaction', field)
        )
        if cr.fetchone():
            # Field exists, first set all values to NULL for security
            cr.execute(
                sql.SQL("UPDATE payment_transaction SET {} = NULL").format(sql.Identifier(field))
            )
            _logger.info("Cleared data from field %s", field)
            
            # We'll let ORM handle the actual field removal
    
    # Check if we have a duplicate powertranz_recurring_id field
    cr.execute(
        """
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'payment_transaction' 
        AND column_name = 'powertranz_recurring_id'
        """
    )
    recurring_field_count = cr.fetchone()[0]
    
    if recurring_field_count > 1:
        _logger.warning("Detected duplicate powertranz_recurring_id field! Fixing...")
        
        # Fix by dropping the duplicate field
        # First, create a list of all field definitions
        cr.execute(
            """
            SELECT attname, atttypid
            FROM pg_attribute
            WHERE attrelid = 'payment_transaction'::regclass
            AND attname = 'powertranz_recurring_id'
            """
        )
        fields = cr.fetchall()
        
        if len(fields) > 1:
            # Keep the first field, drop others
            _logger.info("Will keep the first field definition and drop duplicates")
            
            # This is a simplified approach - in a real scenario you might want to check the constraints
            # and foreign keys more carefully before deciding which one to keep
            
            # Note: Directly modifying the database schema is generally not recommended
            # This is a special case for fixing a duplicate field issue
            try:
                cr.execute(
                    """
                    ALTER TABLE payment_transaction
                    DROP COLUMN IF EXISTS powertranz_recurring_id_duplicate;
                    """
                )
                _logger.info("Successfully removed duplicate field")
            except Exception as e:
                _logger.error("Error removing duplicate field: %s", e)
    
    # Log that the migration was completed
    _logger.info("Pre-migration completed: Sensitive card data has been removed from the database.")
    
    # Note: The actual column dropping will happen through the ORM when the module is updated,
    # as the fields are no longer defined in the model. 