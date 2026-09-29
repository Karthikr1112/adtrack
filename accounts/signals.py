from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Profile


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    """Every User automatically gets a Profile the moment they're created."""
    if created:
        Profile.objects.create(user=instance, is_admin_created=bool(instance.is_superuser or instance.is_staff))
    else:
        profile, _ = Profile.objects.get_or_create(user=instance)
        if (instance.is_superuser or instance.is_staff) and not profile.is_admin_created:
            profile.is_admin_created = True
            profile.save(update_fields=['is_admin_created'])