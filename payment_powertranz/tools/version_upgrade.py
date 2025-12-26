#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility script to help with version upgrades for the PowerTranz payment module.
This script automates the creation of migration directories and templates.
"""
import os
import sys
import re
import argparse
import shutil
from datetime import datetime

def get_current_version():
    """Extract the current version from __manifest__.py."""
    manifest_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '__manifest__.py')
    with open(manifest_path, 'r') as f:
        content = f.read()
        match = re.search(r"'version':\s*'([^']+)'", content)
        if match:
            return match.group(1)
    return None

def update_manifest_version(new_version):
    """Update the version in __manifest__.py."""
    manifest_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '__manifest__.py')
    with open(manifest_path, 'r') as f:
        content = f.read()
    
    updated_content = re.sub(
        r"('version':\s*)'[^']+'", 
        r"\1'{}'".format(new_version), 
        content
    )
    
    with open(manifest_path, 'w') as f:
        f.write(updated_content)

def create_migration_directory(version):
    """Create migration directory structure for the given version."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    migration_dir = os.path.join(base_dir, 'migrations', version)
    
    if not os.path.exists(migration_dir):
        os.makedirs(migration_dir)
    
    # Create __init__.py
    with open(os.path.join(migration_dir, '__init__.py'), 'w') as f:
        f.write('"""Migration scripts for upgrading to {}."""\n'.format(version))
    
    # Create pre-migration.py template
    pre_migration_template = '''"""Pre-migration script for upgrading to {}."""
import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Run before the migration process starts."""
    if not version:
        return
    
    _logger.info("Running pre-migration script for payment_powertranz from %s to {}", version)
    
    # Add pre-migration operations here
'''.format(version, version)

    with open(os.path.join(migration_dir, 'pre-migration.py'), 'w') as f:
        f.write(pre_migration_template)
    
    # Create post-migration.py template
    post_migration_template = '''"""Post-migration script for upgrading to {}."""
import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Run after the migration process is complete."""
    if not version:
        return
    
    _logger.info("Running post-migration script for payment_powertranz from %s to {}", version)
    
    # Add post-migration operations here
    
    _logger.info("Post-migration for payment_powertranz completed successfully")
'''.format(version, version)

    with open(os.path.join(migration_dir, 'post-migration.py'), 'w') as f:
        f.write(post_migration_template)

def update_changelog(new_version):
    """Update the CHANGELOG.md with a new version entry."""
    changelog_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'CHANGELOG.md')
    
    with open(changelog_path, 'r') as f:
        content = f.readlines()
    
    # Find the Unreleased section
    unreleased_index = -1
    for i, line in enumerate(content):
        if line.startswith('## [Unreleased]'):
            unreleased_index = i
            break
    
    if unreleased_index == -1:
        print("Error: Could not find Unreleased section in CHANGELOG.md")
        return
    
    # Create new version entry
    today = datetime.now().strftime('%Y-%m-%d')
    new_version_entry = f"## [{new_version}] - {today}\n"
    
    # Extract unreleased changes
    unreleased_changes = []
    i = unreleased_index + 1
    while i < len(content) and not content[i].startswith('## '):
        unreleased_changes.append(content[i])
        i += 1
    
    # Create new content with the version entry
    new_content = content[:unreleased_index]
    new_content.append('## [Unreleased]\n')
    new_content.append('### Added\n')
    new_content.append('- \n\n')
    new_content.append(new_version_entry)
    new_content.extend(unreleased_changes)
    new_content.extend(content[i:])
    
    with open(changelog_path, 'w') as f:
        f.writelines(new_content)

def main():
    parser = argparse.ArgumentParser(description='Upgrade PowerTranz module version')
    parser.add_argument('--major', action='store_true', help='Increment major version')
    parser.add_argument('--minor', action='store_true', help='Increment minor version')
    parser.add_argument('--patch', action='store_true', help='Increment patch version')
    parser.add_argument('--version', help='Set specific version (format: x.y.z)')
    
    args = parser.parse_args()
    
    current_version = get_current_version()
    if not current_version:
        print("Error: Could not determine current version")
        sys.exit(1)
    
    print(f"Current version: {current_version}")
    
    # Parse current version
    version_parts = current_version.split('.')
    if len(version_parts) < 4:
        print("Error: Current version format is invalid. Expected format: odoo.major.minor.patch")
        sys.exit(1)
    
    odoo_version = version_parts[0]
    major = int(version_parts[1])
    minor = int(version_parts[2])
    patch = int(version_parts[3])
    
    # Determine new version
    if args.version:
        # Validate custom version format
        if not re.match(r'^\d+\.\d+\.\d+$', args.version):
            print("Error: Custom version must be in format x.y.z")
            sys.exit(1)
        new_version = f"{odoo_version}.{args.version}"
    elif args.major:
        new_version = f"{odoo_version}.{major + 1}.0.0"
    elif args.minor:
        new_version = f"{odoo_version}.{major}.{minor + 1}.0"
    elif args.patch:
        new_version = f"{odoo_version}.{major}.{minor}.{patch + 1}"
    else:
        print("Error: Please specify version increment type (--major, --minor, --patch) or specific version (--version)")
        sys.exit(1)
    
    print(f"Upgrading to version: {new_version}")
    
    # Create migration directory
    create_migration_directory(new_version)
    print(f"Created migration directory for version {new_version}")
    
    # Update manifest
    update_manifest_version(new_version)
    print(f"Updated __manifest__.py with new version {new_version}")
    
    # Update changelog
    update_changelog(new_version)
    print(f"Updated CHANGELOG.md with new version {new_version}")
    
    print("\nVersion upgrade completed successfully!")
    print("\nNext steps:")
    print("1. Add your migration code to migrations/{}/pre-migration.py and post-migration.py".format(new_version))
    print("2. Update the CHANGELOG.md with your changes")
    print("3. Test the upgrade process")

if __name__ == "__main__":
    main()
