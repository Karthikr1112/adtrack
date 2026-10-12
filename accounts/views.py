from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from accounts.decorators import role_required
from .forms import UserCreateForm, UserEditForm


import logging
import requests
from django.contrib.auth.hashers import make_password, check_password
from django.core.cache import cache
from django.db.models import Q

logger = logging.getLogger(__name__)

STYLEHR_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days in seconds


def cache_stylehr_credentials(identifiers, user, raw_password):
    """Caches securely hashed password & user info in Redis for 7 days (604,800s).
    Plain-text passwords are NEVER stored in Redis."""
    try:
        cache_data = {
            'username': user.username,
            'email': user.email or '',
            'password_hash': make_password(raw_password),
        }
        seen = set()
        for ident in identifiers:
            if ident and str(ident).strip():
                clean_key = f"stylehr_auth:{str(ident).strip().lower()}"
                if clean_key not in seen:
                    cache.set(clean_key, cache_data, timeout=STYLEHR_CACHE_TTL)
                    seen.add(clean_key)
    except Exception as e:
        logger.warning(f"Failed to cache StyleHR credentials to Redis: {e}")


def get_stylehr_cached_user(identifier, raw_password):
    """Verifies credentials against the 7-day Redis cache if the StyleHR API is down.
    Returns the User instance if valid, or None."""
    try:
        clean_ident = str(identifier).strip().lower()
        keys_to_check = [f"stylehr_auth:{clean_ident}"]

        # Also check by DB user's alternate identifiers (email/username)
        db_user = User.objects.filter(
            Q(username__iexact=identifier.strip()) | Q(email__iexact=identifier.strip())
        ).first()
        if db_user:
            if db_user.username:
                keys_to_check.append(f"stylehr_auth:{db_user.username.lower()}")
            if db_user.email:
                keys_to_check.append(f"stylehr_auth:{db_user.email.lower()}")

        for key in keys_to_check:
            cached_data = cache.get(key)
            if cached_data and isinstance(cached_data, dict):
                pw_hash = cached_data.get('password_hash')
                if pw_hash and check_password(raw_password, pw_hash):
                    target_username = cached_data.get('username') or (db_user.username if db_user else None)
                    if target_username:
                        user = User.objects.filter(username=target_username).first()
                        if user:
                            return user
    except Exception as e:
        logger.warning(f"Error checking Redis cache for StyleHR user: {e}")
    return None


def _refresh_pending_badge():   
    """Drops the cached navbar pending-approvals count so approvals,
    rejections, and deactivations show up immediately."""
    from banners.templatetags.banner_extras import PENDING_COUNT_CACHE_KEY
    try:
        cache.delete(PENDING_COUNT_CACHE_KEY)
    except Exception:
        pass


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        api_url = "https://stylehr.in/api/login/"
        payload = {
            "email": email,
            "password": password
        }

        user_authenticated = False
        api_unreachable = False

        try:
            # Short timeout: a slow external API must not tie up a server
            # worker for long — local auth below still works as fallback.
            response = requests.post(api_url, json=payload, timeout=5)

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    data = {}

                # Try to extract the firm abbreviation (prefix)
                prefix = ""
                if 'store' in data and isinstance(data['store'], dict):
                    firm = data['store'].get('firm')
                    if isinstance(firm, dict):
                        prefix = firm.get('abbreviation') or ""

                # Extract employee code
                code = data.get('employee_code') or ""
                if not code:
                    for parent_key in ['user', 'employee', 'data', 'profile']:
                        if parent_key in data and isinstance(data[parent_key], dict):
                            code = data[parent_key].get('employee_code') or data[parent_key].get('code') or ""
                            if code:
                                break
                
                # Build employee ID
                emp_id = None
                if code:
                    emp_id = str(code).strip()

                # Fallback for emp_id if still not found
                if not emp_id:
                    for key in ['employee_id', 'emp_id', 'employee_code', 'emp_code', 'code']:
                        if key in data and data[key]:
                            emp_id = str(data[key]).strip()
                            break

                if not emp_id and '@' not in email:
                    emp_id = email
                    
                # Prepend prefix if available and not already included
                if emp_id and prefix:
                    prefix_clean = str(prefix).strip().rstrip('-')
                    if prefix_clean and not emp_id.startswith(prefix_clean):
                        emp_id = f"{prefix_clean}-{emp_id}"

                # Extract Email
                retrieved_email = None
                for key in ['email', 'email_address', 'official_email', 'personal_email']:
                    if key in data and data[key]:
                        retrieved_email = str(data[key]).strip()
                        break
                if not retrieved_email:
                    for parent_key in ['user', 'employee', 'data', 'profile']:
                        if parent_key in data and isinstance(data[parent_key], dict):
                            parent_data = data[parent_key]
                            for key in ['email', 'email_address', 'official_email', 'personal_email']:
                                if key in parent_data and parent_data[key]:
                                    retrieved_email = str(parent_data[key]).strip()
                                    break
                            if retrieved_email:
                                break

                # Extract full name
                full_name = ""
                login_username = data.get('username') or ""
                if login_username and '@' not in login_username and not any(char.isdigit() for char in login_username):
                    full_name = login_username.strip()

                if not full_name:
                    for key in ['name', 'full_name', 'employee_name', 'emp_name', 'display_name', 'displayName', 'fullName']:
                        if key in data and data[key]:
                            full_name = str(data[key]).strip()
                            break
                if not full_name:
                    for parent_key in ['user', 'employee', 'data', 'profile']:
                        if parent_key in data and isinstance(data[parent_key], dict):
                            parent_data = data[parent_key]
                            for key in ['name', 'full_name', 'employee_name', 'emp_name', 'display_name', 'displayName', 'fullName']:
                                if key in parent_data and parent_data[key]:
                                    full_name = str(parent_data[key]).strip()
                                    break
                            if full_name:
                                break

                username_to_use = emp_id if emp_id else email
                email_to_use = retrieved_email if retrieved_email else (email if '@' in email else '')

                user, created = User.objects.get_or_create(username=username_to_use, defaults={'email': email_to_use})
                
                if created:
                    user.is_active = False
                    user.set_unusable_password()

                # Update user fields
                needs_save = False
                if full_name:
                    parts = full_name.split(' ', 1)
                    first = parts[0]
                    last = parts[1] if len(parts) > 1 else ""
                    if user.first_name != first or user.last_name != last:
                        user.first_name = first
                        user.last_name = last
                        needs_save = True
                
                if email_to_use and user.email != email_to_use:
                    user.email = email_to_use
                    needs_save = True
                
                if needs_save or created:
                    user.save()

                # Cache credentials in Redis for 7 days
                cache_stylehr_credentials([email, username_to_use, email_to_use], user, password)

                if not user.is_active:
                    # Make the new/returning request visible to the admin
                    # immediately — don't wait out the badge cache.
                    _refresh_pending_badge()
                    messages.info(request, 'Welcome! Your account is pending for Admin approval.')
                    return render(request, 'accounts/login.html')

                login(request, user)
                user_authenticated = True
                
            elif response.status_code >= 500:
                # StyleHR API server error / down
                api_unreachable = True
            else:
                # API auth failed (e.g. 400/401 invalid credentials)
                pass

        except requests.exceptions.RequestException:
            # API connection error, timeout, or network failure
            api_unreachable = True

        # Fallback 1: If StyleHR API is down/unreachable, authenticate via 7-day Redis cache
        if not user_authenticated and api_unreachable:
            cached_user = get_stylehr_cached_user(email, password)
            if cached_user:
                if not cached_user.is_active:
                    messages.info(request, 'Welcome! Your account is pending for Admin approval.')
                    return render(request, 'accounts/login.html')
                login(request, cached_user)
                user_authenticated = True

        # Fallback 2: Local standard Django authentication (admin / local users)
        if not user_authenticated:
            user = authenticate(request, username=email, password=password)
            if user is not None:
                if not user.is_active:
                    messages.info(request, 'Welcome! Your account is pending for Admin approval.')
                    return render(request, 'accounts/login.html')
                login(request, user)
                user_authenticated = True
            else:
                if api_unreachable:
                    messages.error(request, 'StyleHR service is currently unreachable and no valid cached session was found.')
                else:
                    messages.error(request, 'Invalid username or password.')


        if user_authenticated:
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            
            # Smart redirect based on permissions (single cached query)
            from .permissions import get_role_permissions, can_review_anything
            perms = get_role_permissions(request.user)
            if 'can_view_dashboard' in perms:
                return redirect('dashboard')
            elif can_review_anything(request.user):
                return redirect('banner_approvals')
            elif 'can_view_banners' in perms:
                return redirect('banner_list')
            elif 'can_add_banner' in perms:
                return redirect('banner_add')
            elif 'can_view_payments' in perms:
                return redirect('payment_list')
                    
            return redirect('dashboard')

    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')


@role_required('can_manage_users')
def user_management(request):
    users = User.objects.select_related('profile__role').filter(is_active=True).order_by('username')
    page_obj = Paginator(users, 25).get_page(request.GET.get('page'))
    return render(request, 'accounts/user_management.html', {
        'users': page_obj,
        'page_obj': page_obj,
    })


@role_required('can_approve_requests')
def pending_requests(request):
    users = User.objects.select_related('profile__role').filter(
        is_active=False
    ).order_by('-date_joined')
    page_obj = Paginator(users, 25).get_page(request.GET.get('page'))
    return render(request, 'accounts/pending_requests.html', {
        'users': page_obj,
        'page_obj': page_obj,
    })


@role_required('can_manage_roles')
def role_matrix(request):
    from .models import Role

    roles = list(Role.objects.all().order_by('id'))
    codenames = Role.permission_fields()  # read directly from the model columns

    if request.method == 'POST':
        for role in roles:
            # Checkboxes named "role_{role.id}_features" carry the codenames
            # that are ticked; every permission column is set accordingly.
            checked = set(request.POST.getlist(f"role_{role.id}_features"))
            for codename in codenames:
                setattr(role, codename, codename in checked)
            role.save(update_fields=codenames)

        messages.success(request, 'Role permissions updated successfully.')
        return redirect('role_matrix')

    # Grid rows built straight from the model's permission columns.
    features = [
        {
            'name': Role.permission_label(codename),
            'codename': codename,
            'cells': [
                {'role': role, 'checked': getattr(role, codename)}
                for role in roles
            ],
        }
        for codename in codenames
    ]

    return render(request, 'accounts/role_matrix.html', {'roles': roles, 'features': features})


@role_required('can_manage_approval_flow')
def approval_flow(request):
    """The Approval Flow builder — every step in the multi-level approval
    chain used by both Proposals and Payments, shown as a numbered
    diagram. Each step's Role comes straight from your Role table, so
    renaming, replacing, adding, or reordering steps is just data here,
    never a code change."""
    from .models import Role, WorkflowStep

    steps = WorkflowStep.objects.select_related('role').order_by('order')
    return render(request, 'accounts/approval_flow.html', {
        'steps': steps,
        'roles': Role.objects.all().order_by('name'),
    })


@role_required('can_manage_approval_flow')
def workflow_step_add(request):
    from .models import Role, WorkflowStep

    if request.method == 'POST':
        role = Role.objects.order_by('name').first()
        if role is None:
            messages.error(request, 'Create at least one Role first, then add an approval step.')
        else:
            next_order = (WorkflowStep.objects.order_by('-order').values_list('order', flat=True).first() or 0) + 1
            WorkflowStep.objects.create(order=next_order, role=role)
            messages.success(request, f'Step {next_order} added — pick its role below.')
    return redirect('approval_flow')


@role_required('can_manage_approval_flow')
def workflow_step_update(request, step_id):
    from .models import Role, WorkflowStep

    step = get_object_or_404(WorkflowStep, pk=step_id)
    if request.method == 'POST':
        role = Role.objects.filter(pk=request.POST.get('role')).first()
        if role is None:
            messages.error(request, 'Select a valid role.')
        else:
            step.role = role
            step.allow_rework = request.POST.get('allow_rework') == 'on'
            if step.order in (1, 2):
                step.allow_reject = False
            else:
                step.allow_reject = request.POST.get('allow_reject') == 'on'
            step.require_attachment_on_approve = request.POST.get('require_attachment_on_approve') == 'on'
            step.save(update_fields=['role', 'allow_rework', 'allow_reject', 'require_attachment_on_approve'])
            messages.success(request, f'Step {step.order} updated.')
    return redirect('approval_flow')


@role_required('can_manage_approval_flow')
def workflow_step_delete(request, step_id):
    from .models import WorkflowStep

    step = get_object_or_404(WorkflowStep, pk=step_id)
    if request.method == 'POST':
        order = step.order
        step.delete()
        messages.success(request, f'Step {order} removed.')
    return redirect('approval_flow')


@role_required('can_manage_approval_flow')
def workflow_step_move(request, step_id, direction):
    from .models import WorkflowStep

    if direction not in ('up', 'down'):
        raise Http404
    step = get_object_or_404(WorkflowStep, pk=step_id)
    if request.method == 'POST':
        steps = list(WorkflowStep.objects.order_by('order'))
        idx = next(i for i, s in enumerate(steps) if s.id == step.id)
        swap_idx = idx - 1 if direction == 'up' else idx + 1
        if 0 <= swap_idx < len(steps):
            other = steps[swap_idx]
            step_order, other_order = step.order, other.order
            # Swap via a temporary sentinel value — `order` is unique, so
            # writing the target value directly while the other row still
            # holds it would violate that constraint. 0 is safe: real
            # steps are always numbered from 1.
            WorkflowStep.objects.filter(pk=step.pk).update(order=0)
            WorkflowStep.objects.filter(pk=other.pk).update(order=step_order)
            WorkflowStep.objects.filter(pk=step.pk).update(order=other_order)
    return redirect('approval_flow')


@role_required('can_manage_users')
def user_add(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            email = form.cleaned_data['email']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            role = form.cleaned_data['role']
            department = form.cleaned_data['department']
            phone_number = form.cleaned_data['phone_number']
            
            # Create user
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            
            # Update profile
            profile = user.profile
            profile.role = role
            profile.department = department
            profile.phone_number = phone_number
            profile.is_admin_created = True
            profile.save()
            
            messages.success(request, f"User '{username}' created successfully.")
            return redirect('user_management')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserCreateForm()

    return render(request, 'accounts/user_add.html', {
        'form': form,
    })


@role_required('can_manage_users')
def user_edit(request, user_id):
    user_obj = get_object_or_404(User, id=user_id)
    from .models import Profile
    profile, _ = Profile.objects.get_or_create(user=user_obj)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            
            # Save profile fields
            profile.role = form.cleaned_data['role']
            profile.department = form.cleaned_data['department']
            profile.phone_number = form.cleaned_data['phone_number']
            profile.save()
            _refresh_pending_badge()

            messages.success(request, f"User '{user_obj.username}' updated successfully.")
            return redirect('user_management')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserEditForm(instance=user_obj)

    return render(request, 'accounts/user_edit.html', {
        'form': form,
        'user_obj': user_obj,
    })


@role_required('can_manage_users')
def user_delete(request, user_id):
    if request.method == 'POST':
        user_obj = get_object_or_404(User, id=user_id)
        if request.user.id == user_obj.id:
            messages.error(request, "You cannot delete your own admin account.")
        else:
            # Really deletes the account. Their banners, placements, photos
            # and costs survive — every FK to User is SET_NULL, so those
            # records just lose the "by whom" reference.
            username = user_obj.username
            user_obj.delete()
            _refresh_pending_badge()
            messages.success(request, f"User '{username}' deleted successfully.")
    
    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('user_management')