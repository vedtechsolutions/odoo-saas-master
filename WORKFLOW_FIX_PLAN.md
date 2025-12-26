# SaaS Platform Workflow Fix Plan

**Created:** 2025-12-26
**Status:** Ready for Implementation
**Risk Level:** Medium (all fixes are additive, no breaking changes)

---

## Executive Summary

Deep analysis validated **4 critical workflow gaps** that break core business functionality:

| Gap | Issue | Impact | Complexity |
|-----|-------|--------|------------|
| #1 | Trial instances not auto-provisioned | Trial users can't access instances | LOW |
| #3 | No invoice on renewal | Revenue not collected | MEDIUM |
| #5 | Cancellation doesn't cleanup | Resources wasted, promises broken | MEDIUM |
| #14 | No instance-subscription link validation | Orphaned records possible | LOW |

---

## Implementation Order (Dependency-Safe)

```
Phase 1: Foundation Fixes (No dependencies)
├── Fix #14: Add validation constraints
└── Fix #1: Add auto-provision call

Phase 2: Billing Flow (Depends on Phase 1)
└── Fix #3: Add invoice generation to renewal cron

Phase 3: Lifecycle Management (Depends on Phase 1-2)
└── Fix #5: Add cancellation cleanup cron with grace period
```

---

## Detailed Fix Specifications

### FIX #1: Trial Auto-Provisioning

**File:** `/opt/odoo/custom-addons/saas_subscription/models/saas_subscription.py`
**Location:** Line 316, inside `action_start_trial()`
**Risk:** LOW - Identical pattern to paid flow in sale_order.py:280

**Current Code (Lines 314-319):**
```python
# Provision instance if not exists
if not self.instance_id:
    self._create_trial_instance()

self.message_post(body="Trial started")
return True
```

**Fixed Code:**
```python
# Provision instance if not exists
if not self.instance_id:
    self._create_trial_instance()

# Auto-provision the trial instance (matches paid flow)
if self.instance_id and self.instance_id.state == InstanceState.DRAFT:
    self.instance_id.action_provision()

self.message_post(body="Trial started - instance provisioning queued")
return True
```

**Side Effects:**
- Trial instances will now consume server resources (intended)
- Queue system handles trial instances identically to paid (already supported)
- Welcome email will be sent after provisioning completes (existing behavior)

**Test Procedure:**
1. Create new customer
2. Start trial subscription
3. Verify instance state transitions: DRAFT → PENDING → PROVISIONING → RUNNING
4. Verify customer can access instance URL

---

### FIX #3: Renewal Invoice Generation

**File:** `/opt/odoo/custom-addons/saas_subscription/models/saas_subscription.py`
**Location:** Line 567-568, inside `cron_check_billing_due()`
**Risk:** MEDIUM - Connects to billing/accounting modules

**Current Code (Lines 554-571):**
```python
@api.model
def cron_check_billing_due(self):
    """Cron job to check billing due dates."""
    today = fields.Date.context_today(self)

    due_subscriptions = self.search([
        ('state', '=', SubscriptionState.ACTIVE),
        ('next_billing_date', '<=', today),
        ('payment_status', '!=', 'overdue'),
    ])

    for sub in due_subscriptions:
        sub.write({'payment_status': 'pending'})
        # Here you would trigger invoice generation or payment processing

    _logger.info(f"Found {len(due_subscriptions)} subscriptions due for billing")
    return True
```

**Fixed Code:**
```python
@api.model
def cron_check_billing_due(self):
    """Cron job to check billing due dates and generate renewal invoices."""
    today = fields.Date.context_today(self)

    due_subscriptions = self.search([
        ('state', '=', SubscriptionState.ACTIVE),
        ('next_billing_date', '<=', today),
        ('payment_status', '!=', 'overdue'),
    ])

    invoices_created = 0
    for sub in due_subscriptions:
        try:
            # Generate renewal invoice
            invoice = self._create_renewal_invoice(sub)
            if invoice:
                invoices_created += 1
                sub.write({'payment_status': 'pending'})

                # Create billing transaction for payment processing
                self._create_billing_transaction(sub, invoice)

                _logger.info(f"Created renewal invoice {invoice.name} for {sub.name}")
            else:
                _logger.warning(f"Could not create invoice for subscription {sub.name}")
        except Exception as e:
            _logger.error(f"Error processing renewal for {sub.name}: {e}")
            continue

    _logger.info(f"Processed {len(due_subscriptions)} due subscriptions, created {invoices_created} invoices")
    return True

def _create_renewal_invoice(self, subscription):
    """Create invoice for subscription renewal."""
    self.ensure_one()

    # Use existing infrastructure from saas_billing
    AccountMove = self.env['account.move']
    if hasattr(AccountMove, 'create_subscription_invoice'):
        return AccountMove.create_subscription_invoice(
            subscription=subscription,
            period_start=subscription.next_billing_date,
            period_end=subscription.next_billing_date + timedelta(
                days=365 if subscription.billing_cycle == 'yearly' else 30
            )
        )

    # Fallback: Create basic invoice if method not available
    return AccountMove.create({
        'move_type': 'out_invoice',
        'partner_id': subscription.partner_id.id,
        'subscription_id': subscription.id,
        'invoice_date': fields.Date.today(),
        'invoice_line_ids': [(0, 0, {
            'name': f"Subscription renewal: {subscription.plan_id.name}",
            'quantity': 1,
            'price_unit': subscription.recurring_price,
        })],
    })

def _create_billing_transaction(self, subscription, invoice):
    """Create billing transaction for payment processing."""
    BillingTransaction = self.env.get('saas.billing.transaction')
    if BillingTransaction:
        BillingTransaction.create({
            'name': f"Renewal payment for {subscription.name}",
            'transaction_type': 'renewal',
            'partner_id': subscription.partner_id.id,
            'subscription_id': subscription.id,
            'invoice_id': invoice.id,
            'amount': invoice.amount_total,
            'state': 'pending',
        })
```

**Dependencies:**
- `saas_billing` module must be installed (provides `create_subscription_invoice`)
- `account` module (standard Odoo)
- Existing cron `cron_process_pending_transactions` handles payment processing

**Test Procedure:**
1. Create subscription with next_billing_date = today
2. Run cron manually: `subscription.cron_check_billing_due()`
3. Verify invoice created in Accounting > Invoices
4. Verify billing transaction created
5. Verify cron_process_pending_transactions processes payment

---

### FIX #5: Cancellation Cleanup with Grace Period

**File:** `/opt/odoo/custom-addons/saas_subscription/models/saas_subscription.py`
**New Code:** Add field + modify action_cancel() + add cleanup cron

**Risk:** MEDIUM - Affects instance lifecycle, uses existing termination logic

**Step 1: Add grace period tracking field**
```python
# Add to field definitions (around line 70)
cancellation_cleanup_date = fields.Date(
    string='Cleanup Date',
    help='Date when instance will be terminated after cancellation',
    readonly=True,
)
```

**Step 2: Modify action_cancel() (Lines 418-431)**

**Current:**
```python
def action_cancel(self):
    """Cancel the subscription."""
    self.ensure_one()
    if self.state in [SubscriptionState.CANCELLED, SubscriptionState.EXPIRED]:
        raise UserError(_("Subscription is already cancelled or expired."))

    today = fields.Date.context_today(self)
    self.write({
        'state': SubscriptionState.CANCELLED,
        'cancellation_date': today,
    })

    self.message_post(body="Subscription cancelled")
    return True
```

**Fixed:**
```python
def action_cancel(self):
    """Cancel the subscription with grace period for instance cleanup."""
    self.ensure_one()
    if self.state in [SubscriptionState.CANCELLED, SubscriptionState.EXPIRED]:
        raise UserError(_("Subscription is already cancelled or expired."))

    today = fields.Date.context_today(self)
    grace_period_days = int(self.env['ir.config_parameter'].sudo().get_param(
        'saas.cancellation_grace_period_days', '7'
    ))
    cleanup_date = today + timedelta(days=grace_period_days)

    self.write({
        'state': SubscriptionState.CANCELLED,
        'cancellation_date': today,
        'cancellation_cleanup_date': cleanup_date,
    })

    # Suspend instance immediately (data preserved during grace period)
    if self.instance_id and self.instance_id.state == InstanceState.RUNNING:
        self.instance_id.action_suspend()

    # Send cancellation email with cleanup notice
    self._send_cancellation_email(grace_period_days)

    self.message_post(
        body=f"Subscription cancelled. Instance will be terminated on {cleanup_date} "
             f"({grace_period_days} day grace period)."
    )
    return True

def _send_cancellation_email(self, grace_period_days):
    """Send cancellation confirmation with cleanup notice."""
    template = self.env.ref(
        'saas_subscription.mail_template_subscription_cancelled',
        raise_if_not_found=False
    )
    if template:
        template.with_context(grace_period_days=grace_period_days).send_mail(self.id)
```

**Step 3: Add cleanup cron job**

**File:** `/opt/odoo/custom-addons/saas_subscription/data/cron_jobs.xml`
```xml
<!-- Add new cron job -->
<record id="cron_cleanup_cancelled_subscriptions" model="ir.cron">
    <field name="name">SaaS: Cleanup Cancelled Subscriptions</field>
    <field name="model_id" ref="model_saas_subscription"/>
    <field name="state">code</field>
    <field name="code">model.cron_cleanup_cancelled_subscriptions()</field>
    <field name="interval_number">1</field>
    <field name="interval_type">days</field>
    <field name="nextcall" eval="(DateTime.now() + timedelta(days=1)).replace(hour=3, minute=0)"/>
    <field name="numbercall">-1</field>
    <field name="active">True</field>
</record>
```

**Step 4: Add cleanup cron method**
```python
@api.model
def cron_cleanup_cancelled_subscriptions(self):
    """Terminate instances for cancelled subscriptions after grace period."""
    today = fields.Date.context_today(self)

    # Find cancelled subscriptions past grace period
    expired_cancellations = self.search([
        ('state', '=', SubscriptionState.CANCELLED),
        ('cancellation_cleanup_date', '<=', today),
        ('instance_id', '!=', False),
        ('instance_id.state', '!=', InstanceState.TERMINATED),
    ])

    terminated_count = 0
    for sub in expired_cancellations:
        try:
            if sub.instance_id:
                _logger.info(f"Terminating instance {sub.instance_id.name} for cancelled subscription {sub.name}")
                sub.instance_id.action_terminate()
                terminated_count += 1
                sub.message_post(body="Instance terminated after grace period")
        except Exception as e:
            _logger.error(f"Failed to terminate instance for {sub.name}: {e}")
            continue

    _logger.info(f"Cancelled subscription cleanup: terminated {terminated_count} instances")
    return True
```

**Test Procedure:**
1. Create active subscription with running instance
2. Cancel subscription
3. Verify instance state changes to SUSPENDED (immediate)
4. Verify cancellation_cleanup_date = today + 7 days
5. Manually set cleanup_date to past
6. Run cron: `subscription.cron_cleanup_cancelled_subscriptions()`
7. Verify instance state = TERMINATED

---

### FIX #14: Instance-Subscription Link Validation

**Risk:** LOW - Adds constraints only, doesn't change behavior

**Step 1: Add validation to subscription model**

**File:** `/opt/odoo/custom-addons/saas_subscription/models/saas_subscription.py`

```python
# Add constraint method (after field definitions)
@api.constrains('instance_id', 'state')
def _check_instance_subscription_link(self):
    """Ensure active subscriptions have linked instances."""
    for record in self:
        # Active subscriptions must have an instance
        if record.state in [SubscriptionState.ACTIVE, SubscriptionState.TRIAL]:
            if not record.instance_id:
                raise ValidationError(_(
                    "Active or trial subscriptions must have a linked instance. "
                    "Subscription: %s" % record.name
                ))

        # Check for duplicate active subscriptions on same instance
        if record.instance_id and record.state in [SubscriptionState.ACTIVE, SubscriptionState.TRIAL]:
            duplicate = self.search([
                ('id', '!=', record.id),
                ('instance_id', '=', record.instance_id.id),
                ('state', 'in', [SubscriptionState.ACTIVE, SubscriptionState.TRIAL]),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Instance %s already has an active subscription: %s"
                ) % (record.instance_id.name, duplicate.name))
```

**Step 2: Add validation to instance deletion**

**File:** `/opt/odoo/custom-addons/saas_master/models/saas_instance.py`

```python
# Modify unlink method (around line 341)
def unlink(self):
    """Prevent deletion of instances with active subscriptions."""
    for instance in self:
        active_subs = self.env['saas.subscription'].search([
            ('instance_id', '=', instance.id),
            ('state', 'in', ['active', 'trial', 'past_due']),
        ])
        if active_subs:
            raise UserError(_(
                "Cannot delete instance '%s' - it has %d active subscription(s). "
                "Cancel the subscription(s) first: %s"
            ) % (instance.name, len(active_subs), ', '.join(active_subs.mapped('name'))))

    return super().unlink()
```

**Step 3: Fix shop provisioning race condition**

**File:** `/opt/odoo/custom-addons/saas_shop/models/sale_order.py`

The current flow has commits between subscription and instance creation. Fix by ensuring atomic linking:

```python
# In _provision_saas_instances_safe(), around line 238-271
# Change from separate commits to single transaction block:

# Create subscription WITH instance in single transaction
with self.env.cr.savepoint():
    # Create instance first
    instance = Instance.create(instance_vals)

    # Create subscription with instance already linked
    subscription = Subscription.create({
        **subscription_vals,
        'instance_id': instance.id,  # Link immediately
    })

    # Activate subscription
    subscription.action_activate()
    subscription.action_mark_paid()

    # Queue provisioning (instance already linked)
    instance.action_provision()

# Single commit after all operations
self.env.cr.commit()
```

**Test Procedure:**
1. Try to delete instance with active subscription → Should fail with clear error
2. Try to create subscription without instance_id in ACTIVE state → Should fail
3. Try to create duplicate active subscription for same instance → Should fail
4. Create order via shop → Verify subscription+instance created atomically

---

## Implementation Checklist

### Pre-Implementation
- [ ] Backup database before changes
- [ ] Review all files to be modified
- [ ] Ensure test environment available

### Phase 1: Foundation (30 min)
- [ ] Fix #14: Add `_check_instance_subscription_link()` constraint
- [ ] Fix #14: Add instance unlink() validation
- [ ] Fix #1: Add `action_provision()` call in `action_start_trial()`
- [ ] Test: Create trial subscription → verify auto-provision
- [ ] Test: Try delete instance with active sub → verify blocked

### Phase 2: Billing (45 min)
- [ ] Fix #3: Add `_create_renewal_invoice()` method
- [ ] Fix #3: Add `_create_billing_transaction()` method
- [ ] Fix #3: Modify `cron_check_billing_due()` to generate invoices
- [ ] Test: Set subscription.next_billing_date = today
- [ ] Test: Run cron → verify invoice created
- [ ] Test: Verify billing transaction created

### Phase 3: Lifecycle (45 min)
- [ ] Fix #5: Add `cancellation_cleanup_date` field
- [ ] Fix #5: Modify `action_cancel()` for grace period
- [ ] Fix #5: Add `_send_cancellation_email()` method
- [ ] Fix #5: Add cleanup cron job XML
- [ ] Fix #5: Add `cron_cleanup_cancelled_subscriptions()` method
- [ ] Test: Cancel subscription → verify instance suspended
- [ ] Test: Verify cleanup_date set correctly
- [ ] Test: Run cleanup cron → verify instance terminated

### Post-Implementation
- [ ] Run full module upgrade: `-u saas_subscription,saas_master,saas_shop`
- [ ] Verify all cron jobs active
- [ ] Test complete customer journey: signup → trial → paid → cancel
- [ ] Commit changes with descriptive message

---

## Rollback Plan

If issues arise:

1. **Immediate:** Disable new cron jobs via UI
2. **Quick fix:** Revert specific file changes
3. **Full rollback:** Restore database from backup

Each fix is independent - can be rolled back individually without affecting others.

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `saas_subscription/models/saas_subscription.py` | +4 methods, +1 field, modify 2 methods |
| `saas_subscription/data/cron_jobs.xml` | +1 cron job |
| `saas_master/models/saas_instance.py` | Modify unlink() |
| `saas_shop/models/sale_order.py` | Refactor provisioning for atomicity |

**Total Lines Changed:** ~150 lines added/modified
**Risk Assessment:** LOW-MEDIUM (all changes are additive or improve safety)
