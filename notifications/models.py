from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models

class Notification(models.Model):
    user  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind  = models.CharField(max_length=30)
    body  = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
