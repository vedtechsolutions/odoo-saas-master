from . import models
from . import controllers
from . import tools


def post_init_hook(env):
    """Post-init-hook to create payment method line for PowerTranz."""
    _setup_payment_method_line(env)


def uninstall_hook(env):
    """Uninstall hook to clean up payment method lines."""
    # Remove payment method lines linked to PowerTranz
    provider = env['payment.provider'].search([('code', '=', 'powertranz')], limit=1)
    if provider:
        env['account.payment.method.line'].search([
            ('payment_provider_id', '=', provider.id)
        ]).unlink()


def module_upgrade_hook():
    """Hook called when the module is loaded via post_load."""
    pass


def _setup_payment_method_line(env):
    """Create payment method line linking PowerTranz to a bank journal."""
    provider = env['payment.provider'].search([('code', '=', 'powertranz')], limit=1)
    if not provider:
        return

    # Check if payment method line already exists for this provider
    existing_line = env['account.payment.method.line'].search([
        ('payment_provider_id', '=', provider.id)
    ], limit=1)
    if existing_line:
        return

    # Find a bank journal
    bank_journal = env['account.journal'].search([
        ('type', '=', 'bank'),
        ('company_id', '=', provider.company_id.id),
    ], limit=1)
    if not bank_journal:
        return

    # Find the manual inbound payment method
    payment_method = env['account.payment.method'].search([
        ('code', '=', 'manual'),
        ('payment_type', '=', 'inbound'),
    ], limit=1)
    if not payment_method:
        return

    # Create the payment method line
    env['account.payment.method.line'].create({
        'name': 'PowerTranz',
        'journal_id': bank_journal.id,
        'payment_method_id': payment_method.id,
        'payment_provider_id': provider.id,
    }) 