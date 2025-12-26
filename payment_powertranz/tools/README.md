# PowerTranz Module Development Tools

This directory contains utility scripts to help with the development and maintenance of the PowerTranz payment module.

## Version Upgrade Tool

The `version_upgrade.py` script automates the process of upgrading the module version and creating the necessary migration scripts.

### Usage

```bash
python version_upgrade.py [--major] [--minor] [--patch] [--version VERSION]
```

#### Arguments

- `--major`: Increment the major version number (e.g., 18.0.1.0.0 → 18.0.2.0.0)
- `--minor`: Increment the minor version number (e.g., 18.0.1.0.0 → 18.0.1.1.0)
- `--patch`: Increment the patch version number (e.g., 18.0.1.0.0 → 18.0.1.0.1)
- `--version VERSION`: Set a specific version (e.g., `--version 2.0.0` will set to 18.0.2.0.0)

### Example

To create a new minor version:

```bash
cd /path/to/payment_powertranz
python tools/version_upgrade.py --minor
```

This will:
1. Create a new migration directory with template scripts
2. Update the version in `__manifest__.py`
3. Update the CHANGELOG.md with a new version entry

### After Running the Tool

After running the version upgrade tool, you should:

1. Implement the migration logic in the pre-migration.py and post-migration.py scripts
2. Update the CHANGELOG.md with details of your changes
3. Test the upgrade process from the previous version

## Best Practices for Module Upgrades

1. **Plan your changes**: Before upgrading the version, plan what changes will be included and how they will affect existing data.
2. **Test thoroughly**: Test the upgrade process on a copy of production data to ensure it works correctly.
3. **Document changes**: Always document your changes in the CHANGELOG.md file.
4. **Follow semantic versioning**: Increment the version number according to the nature of your changes:
   - Major: Backward-incompatible changes
   - Minor: New features that are backward-compatible
   - Patch: Bug fixes that are backward-compatible
