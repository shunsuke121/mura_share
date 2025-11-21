from django.db import models
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

User = get_user_model()


class Profile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    profile_image = models.ImageField(
        upload_to="profiles/",
        blank=True,
        null=True,
    )

    is_admin = models.BooleanField(default=False)

    def __str__(self):
        return self.display_name or self.user.username


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, is_admin=False)

@receiver(post_save, sender=User)
def sync_profile_is_admin(sender, instance, **kwargs):
    """
    User.is_staff を Profile.is_admin に常時同期する。
    管理画面でスタッフ権限を切り替えたときも即反映。
    """
    profile, _ = Profile.objects.get_or_create(user=instance)
    flag = bool(instance.is_staff)
    if profile.is_admin != flag:
        profile.is_admin = flag
        profile.save(update_fields=["is_admin"])
