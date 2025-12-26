# -*- coding: utf-8 -*-
"""
Models for the SaaS Core module.

This module imports mixins as models to ensure proper Odoo registration.
AbstractModels must be imported in this context to be registered in ir.model.
"""

# Import mixins here to ensure they're registered as Odoo models
from odoo.addons.saas_core.mixins.audit_mixin import SaasAuditMixin
from odoo.addons.saas_core.mixins.encryption_mixin import SaasEncryptionMixin
