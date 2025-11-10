from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL

class ChatRoom(models.Model):
    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE, related_name="chat_rooms")
    user1   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chatrooms_as_user1")
    user2   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chatrooms_as_user2")
    created_at = models.DateTimeField(auto_now_add=True)

class ChatMessage(models.Model):
    room  = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    user  = models.ForeignKey(User, on_delete=models.CASCADE)
    body  = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
