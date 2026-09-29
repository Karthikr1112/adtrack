from django.db import models
from django.contrib.auth.models import User


class Role(models.Model):
    """A role is one row; every permission is a BooleanField column below
    (tick = allowed). The Role Matrix page and the admin read these columns
    directly from the model — to add a new permission, just add one
    BooleanField starting with `can_` and run makemigrations + migrate."""

    name = models.CharField(max_length=50, unique=True)

    # Dashboard
    can_view_dashboard = models.BooleanField(default=False)
    # Proposals
    can_view_banners = models.BooleanField(default=False)
    can_add_banner = models.BooleanField(default=False)
    can_edit_banner = models.BooleanField(default=False)
    can_delete_banner = models.BooleanField(default=False)
    can_approve_banners = models.BooleanField(default=False)
    # Payments (submitted against an approved Work Order) — reviewed by
    # whichever roles the Approval Flow (see WorkflowStep below) assigns,
    # so no separate review permissions are needed here, only who may
    # submit/view/edit/delete them.
    can_add_payment = models.BooleanField(default=False)
    can_view_payments = models.BooleanField(default=False)
    can_edit_payment = models.BooleanField(default=False)
    can_delete_payment = models.BooleanField(default=False)
    # Administration
    can_manage_users = models.BooleanField(default=False)
    can_approve_requests = models.BooleanField(default=False)
    can_manage_roles = models.BooleanField(default=False)
    # Separate from can_manage_roles so a role can be given access to ONLY
    # the Approval Flow builder, without also granting full Role Matrix
    # (add/edit/delete roles) access.
    can_manage_approval_flow = models.BooleanField(default=False)

    @classmethod
    def permission_fields(cls):
        """The permission column names, read directly from the model —
        every BooleanField whose name starts with `can_`."""
        return [
            f.name for f in cls._meta.get_fields()
            if isinstance(f, models.BooleanField) and f.name.startswith('can_')
        ]

    # A few permission labels read better than the plain auto-generated
    # title case — the "banner" columns are a holdover from before the
    # Banner -> Proposal rename and should read "Proposal" everywhere else
    # in the app already does.
    LABEL_OVERRIDES = {
        'can_view_banners': 'View Proposals',
        'can_add_banner': 'Add Proposal',
        'can_edit_banner': 'Edit Proposal',
        'can_delete_banner': 'Delete Proposal',
        'can_approve_banners': 'Can Approve',
    }

    @classmethod
    def permission_label(cls, codename):
        """Label for a permission column: can_view_dashboard -> 'View
        Dashboard', with a few overrides (see LABEL_OVERRIDES)."""
        if codename in cls.LABEL_OVERRIDES:
            return cls.LABEL_OVERRIDES[codename]
        return codename.removeprefix('can_').replace('_', ' ').title()

    def permission_codenames(self):
        """Frozenset of granted permission column names — plain attribute
        reads, no extra query."""
        return frozenset(c for c in self.permission_fields() if getattr(self, c, False))

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.ForeignKey('Role', on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True, db_index=True)
    department = models.CharField(max_length=100, blank=True, db_index=True)
    is_admin_created = models.BooleanField(default=False, db_index=True, help_text="True if created manually in Admin / User Management")

    def __str__(self):
        return f"{self.user.username} ({self.role.name if self.role else 'No Role'})"

    @property
    def is_admin(self):
        return bool(self.role and self.role.can_manage_users)

    @property
    def is_manager(self):
        return bool(self.role and (self.role.can_manage_users or self.role.can_view_dashboard))


class WorkflowStep(models.Model):
    """One step in the configurable multi-level approval chain used by
    both Proposals and Payment Claims — the chain itself (how many steps,
    and which Role reviews at each one) lives here as data, managed from
    the Approval Flow page, instead of being hardcoded in Python. Add,
    remove, or reorder steps at any time; nothing about a specific role's
    name is ever hardcoded elsewhere in the approval logic."""

    order = models.PositiveIntegerField(unique=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='workflow_steps')
    allow_rework = models.BooleanField(
        default=True, help_text='Can a reviewer at this step send the document back for rework?',
    )
    allow_reject = models.BooleanField(
        default=True, help_text='Can a reviewer at this step reject the document?',
    )
    require_attachment_on_approve = models.BooleanField(
        default=False, help_text='Must a file be attached when approving at this step?',
    )

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'Step {self.order}: {self.role.name}'

    @property
    def can_reject(self):
        """Step 1 and Step 2 cannot reject — only rework and go to next level."""
        if self.order in (1, 2):
            return False
        return self.allow_reject
