from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from accounts.decorators import role_required
from .forms import UserCreateForm, UserEditForm


import requests


def _refresh_pending_badge():   
    """Drops the cached navbar pending-approvals count so approvals,
    rejections, and deactivations show up immediately."""
    from django.core.cache import cache
    from banners.templatetags.banner_extras import PENDING_COUNT_CACHE_KEY
    cache.delete(PENDING_COUNT_CACHE_KEY)


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

                if not user.is_active:
                    # Make the new/returning request visible to the admin
                    # immediately — don't wait out the badge cache.
                    _refresh_pending_badge()
                    messages.info(request, 'Welcome! Your account is pending for Admin approval.')
                    return render(request, 'accounts/login.html')

                login(request, user)
                user_authenticated = True
                
            else:
                # API auth failed, will fallback to local auth below
                pass

        except requests.exceptions.RequestException:
            # API connection error, fallback to local auth
            pass

        if not user_authenticated:
            # Fallback to standard Django authentication
            user = authenticate(request, username=email, password=password)
            if user is not None:
                if not user.is_active:
                    messages.info(request, 'Welcome! Your account is pending for Admin approval.')
                    return render(request, 'accounts/login.html')
                login(request, user)
                user_authenticated = True
            else:
                messages.error(request, 'Invalid username or password.')

        if user_authenticated:
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            
            # Smart redirect based on permissions (single cached query)
            from .permissions import get_role_permissions
            perms = get_role_permissions(request.user)
            if 'can_view_dashboard' in perms:
                return redirect('dashboard')
            elif 'can_view_banners' in perms:
                return redirect('banner_list')
            elif 'can_add_banner' in perms:
                return redirect('banner_add')
                    
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
    return render(request, 'accounts/user_management.html', {
        'users': users,
    })


@role_required('can_approve_requests')
def pending_requests(request):
    users = User.objects.select_related('profile__role').filter(
        is_active=False
    ).order_by('-date_joined')
    return render(request, 'accounts/pending_requests.html', {
        'users': users,
    })


@role_required('can_manage_roles')
def role_matrix(request):
    from .models import Role, Feature

    roles = Role.objects.all().order_by('id')
    features = Feature.objects.all().order_by('id')

    if request.method == 'POST':
        for role in roles:
            # We expect checkboxes named "role_{role.id}_features" with values matching feature.id
            checked_feature_ids = request.POST.getlist(f"role_{role.id}_features")
            role.permissions.set(checked_feature_ids)
            
        messages.success(request, 'Role permissions updated successfully.')
        return redirect('role_matrix')

    return render(request, 'accounts/role_matrix.html', {'roles': roles, 'features': features})


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