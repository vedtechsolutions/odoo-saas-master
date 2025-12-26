# PowerTranz Payment Module Migration Guide

This directory contains migration scripts for the PowerTranz payment module. Each subdirectory corresponds to a version of the module and contains scripts that handle the migration from the previous version.

## Migration Process

Odoo automatically executes migration scripts when a module is upgraded. The scripts are executed in the following order:

1. `pre-migration.py` - Executed before the module's code is updated
2. Module update (new models, fields, etc. are created)
3. `post-migration.py` - Executed after the module's code is updated

## Version Naming Convention

Versions follow semantic versioning: `[Odoo Version].[Major].[Minor].[Patch]`

- **Odoo Version**: The Odoo version this module is compatible with (e.g., 18.0)
- **Major**: Incremented for backward-incompatible changes
- **Minor**: Incremented for backward-compatible new features
- **Patch**: Incremented for backward-compatible bug fixes

## Adding a New Migration

When developing a new version:

1. Create a new directory with the target version number
2. Add `__init__.py` to the directory
3. Create `pre-migration.py` and/or `post-migration.py` as needed
4. Update the module's `__manifest__.py` with the new version number

## Migration Script Guidelines

- Always include proper logging
- Handle the case where `version` is `None` (fresh install)
- Use database-agnostic SQL whenever possible
- Document complex migrations with comments
- Test migrations thoroughly before releasing

## Upgrade Checklist

Before releasing a new version:

- [ ] Update version in `__manifest__.py`
- [ ] Create migration scripts if needed
- [ ] Update changelog in module's main README.md
- [ ] Test upgrade from previous version
- [ ] Test fresh install
