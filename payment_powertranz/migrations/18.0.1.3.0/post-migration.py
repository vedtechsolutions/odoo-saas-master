# -*- coding: utf-8 -*-

import logging
from odoo import api, SUPERUSER_ID
from psycopg2 import sql

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Synchronize transaction ID fields and ensure they contain correct data."""
    
    _logger.info("Running post-migration to synchronize transaction ID fields")
    
    # First check if both fields exist
    cr.execute(
        """
        SELECT
            CASE WHEN EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payment_transaction' AND column_name = 'powertranz_transaction_id'
            ) THEN 1 ELSE 0 END as transaction_id_exists,
            CASE WHEN EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payment_transaction' AND column_name = 'powertranz_transaction_uuid'
            ) THEN 1 ELSE 0 END as transaction_uuid_exists
        """
    )
    result = cr.fetchone()
    transaction_id_exists, transaction_uuid_exists = result
    
    # If one of the fields doesn't exist yet, we'll let the ORM create it when the module updates
    if not transaction_id_exists or not transaction_uuid_exists:
        _logger.info("One or both transaction ID fields don't exist yet. They will be created by the ORM update.")
        return
    
    # If both fields exist, synchronize their values
    # First, set transaction_id from uuid where id is null but uuid has a value
    cr.execute(
        """
        UPDATE payment_transaction
        SET powertranz_transaction_id = powertranz_transaction_uuid
        WHERE powertranz_transaction_uuid IS NOT NULL
        AND (powertranz_transaction_id IS NULL OR powertranz_transaction_id = '')
        """
    )
    id_from_uuid_count = cr.rowcount
    
    # Next, set uuid from id where uuid is null but id has a value
    cr.execute(
        """
        UPDATE payment_transaction
        SET powertranz_transaction_uuid = powertranz_transaction_id
        WHERE powertranz_transaction_id IS NOT NULL
        AND (powertranz_transaction_uuid IS NULL OR powertranz_transaction_uuid = '')
        """
    )
    uuid_from_id_count = cr.rowcount
    
    _logger.info(
        "Synchronized transaction ID fields: set %d transaction_id values from uuid and %d uuid values from transaction_id",
        id_from_uuid_count, uuid_from_id_count
    )
    
    # Check for any transactions where the provider is powertranz but both ID fields are null
    # This is for informational purposes only
    cr.execute(
        """
        SELECT COUNT(*)
        FROM payment_transaction pt
        JOIN payment_provider pp ON pt.provider_id = pp.id
        WHERE pp.code = 'powertranz'
        AND pt.powertranz_transaction_id IS NULL
        AND pt.powertranz_transaction_uuid IS NULL
        """
    )
    null_ids_count = cr.fetchone()[0]
    if null_ids_count > 0:
        _logger.warning(
            "Found %d PowerTranz transactions with NULL values in both transaction ID fields",
            null_ids_count
        )
    
    _logger.info("Post-migration completed: Transaction ID fields synchronized.") 