# -*- coding: utf-8 -*-
"""
Encryption mixin for field-level PII encryption.

Implements T-084 (Field-level encryption for PII).

Usage:
    class MyModel(models.Model):
        _name = 'my.model'
        _inherit = ['saas.encryption.mixin']

        # Specify fields to encrypt
        _encrypted_fields = ['admin_email', 'admin_password', 'phone']

        admin_email = fields.Char(string='Admin Email')
        admin_password = fields.Char(string='Password')
"""

import logging
from odoo import models, fields, api
from odoo.addons.saas_core.utils.encryption import (
    encrypt_value,
    decrypt_value,
    is_encrypted,
    hash_for_search,
)

_logger = logging.getLogger(__name__)


class SaasEncryptionMixin(models.AbstractModel):
    """
    Mixin that provides automatic field-level encryption for PII.

    Models using this mixin should define:
        _encrypted_fields = ['field1', 'field2', ...]

    The mixin will automatically:
        - Encrypt values before storing to database
        - Decrypt values when reading from database
        - Maintain hash indexes for searchable encrypted fields
    """
    _name = 'saas.encryption.mixin'
    _description = 'Encryption Mixin for PII Fields'

    # Override in inheriting models
    _encrypted_fields = []

    def _encrypt_vals(self, vals):
        """
        Encrypt field values in a vals dictionary.

        Args:
            vals: Dictionary of field: value pairs

        Returns:
            dict: Vals with encrypted values
        """
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if not encrypted_fields:
            return vals

        encrypted_vals = dict(vals)
        for field_name in encrypted_fields:
            if field_name in encrypted_vals and encrypted_vals[field_name]:
                value = encrypted_vals[field_name]
                # Don't re-encrypt already encrypted values
                if not is_encrypted(value):
                    encrypted_vals[field_name] = encrypt_value(self.env, value)

        return encrypted_vals

    def _decrypt_record_vals(self, record_vals):
        """
        Decrypt field values in a record dictionary.

        Args:
            record_vals: Dictionary from read()

        Returns:
            dict: Record with decrypted values
        """
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if not encrypted_fields:
            return record_vals

        for field_name in encrypted_fields:
            if field_name in record_vals and record_vals[field_name]:
                value = record_vals[field_name]
                if is_encrypted(value):
                    record_vals[field_name] = decrypt_value(self.env, value)

        return record_vals

    @api.model_create_multi
    def create(self, vals_list):
        """Encrypt PII fields before creating records."""
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if encrypted_fields and not self.env.context.get('skip_encryption'):
            vals_list = [self._encrypt_vals(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        """Encrypt PII fields before writing records."""
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if encrypted_fields and not self.env.context.get('skip_encryption'):
            vals = self._encrypt_vals(vals)
        return super().write(vals)

    def read(self, fields=None, load='_classic_read'):
        """Decrypt PII fields when reading records."""
        result = super().read(fields, load)
        encrypted_fields = getattr(self, '_encrypted_fields', [])

        if encrypted_fields:
            # Determine which encrypted fields are being read
            fields_to_decrypt = encrypted_fields
            if fields:
                fields_to_decrypt = [f for f in encrypted_fields if f in fields]

            if fields_to_decrypt:
                for record_vals in result:
                    self._decrypt_record_vals(record_vals)

        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        """Decrypt PII fields in search_read results."""
        result = super().search_read(domain, fields, offset, limit, order)
        encrypted_fields = getattr(self, '_encrypted_fields', [])

        if encrypted_fields and result:
            # Determine which encrypted fields are being read
            fields_to_decrypt = encrypted_fields
            if fields:
                fields_to_decrypt = [f for f in encrypted_fields if f in fields]

            if fields_to_decrypt:
                for record_vals in result:
                    self._decrypt_record_vals(record_vals)

        return result

    def _get_decrypted_value(self, field_name):
        """
        Get decrypted value of a specific field.

        Use this when you need to access the raw decrypted value directly.

        Args:
            field_name: Name of the encrypted field

        Returns:
            str: Decrypted value
        """
        self.ensure_one()
        raw_value = super(SaasEncryptionMixin, self).read([field_name])[0].get(field_name)
        if is_encrypted(raw_value):
            return decrypt_value(self.env, raw_value)
        return raw_value

    def action_encrypt_existing_data(self):
        """
        Encrypt existing unencrypted data in the database.

        Call this method after enabling encryption on existing records.
        """
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if not encrypted_fields:
            return {'status': 'no_fields', 'message': 'No encrypted fields defined'}

        count = 0
        for record in self.search([]):
            vals_to_update = {}
            for field_name in encrypted_fields:
                # Read raw value from database
                raw_vals = super(SaasEncryptionMixin, record).read([field_name])
                if raw_vals:
                    raw_value = raw_vals[0].get(field_name)
                    if raw_value and not is_encrypted(raw_value):
                        vals_to_update[field_name] = encrypt_value(self.env, raw_value)

            if vals_to_update:
                # Write with context to skip re-encryption (already encrypted)
                record.with_context(skip_encryption=True).write(vals_to_update)
                count += 1

        _logger.info(f"Encrypted {count} records in {self._name}")
        return {'status': 'success', 'encrypted_count': count}

    def get_encryption_status(self):
        """
        Get encryption status for this model's data.

        Returns:
            dict: Status information
        """
        encrypted_fields = getattr(self, '_encrypted_fields', [])
        if not encrypted_fields:
            return {
                'model': self._name,
                'encrypted_fields': [],
                'total_records': 0,
                'encrypted_records': 0,
                'unencrypted_records': 0,
            }

        total = self.search_count([])
        encrypted_count = 0
        unencrypted_count = 0

        for record in self.search([]):
            is_record_encrypted = False
            for field_name in encrypted_fields:
                raw_vals = super(SaasEncryptionMixin, record).read([field_name])
                if raw_vals:
                    raw_value = raw_vals[0].get(field_name)
                    if raw_value and is_encrypted(raw_value):
                        is_record_encrypted = True
                        break

            if is_record_encrypted:
                encrypted_count += 1
            else:
                unencrypted_count += 1

        return {
            'model': self._name,
            'encrypted_fields': encrypted_fields,
            'total_records': total,
            'encrypted_records': encrypted_count,
            'unencrypted_records': unencrypted_count,
        }
