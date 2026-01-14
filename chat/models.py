from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

User = settings.AUTH_USER_MODEL

try:
    from notifications.models import Notification
except Exception:
    Notification = None

class ChatRoom(models.Model):
    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE, related_name="chat_rooms")
    user1   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chatrooms_as_user1")
    user2   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chatrooms_as_user2")
    rental = models.ForeignKey(
        "marketplace.Rental",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )
    purchase = models.ForeignKey(
        "marketplace.Purchase",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )
    application = models.ForeignKey(
        "marketplace.RentalApplication",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rental"],
                condition=Q(rental__isnull=False),
                name="uniq_chatroom_rental",
            ),
            models.UniqueConstraint(
                fields=["purchase"],
                condition=Q(purchase__isnull=False),
                name="uniq_chatroom_purchase",
            ),
            models.UniqueConstraint(
                fields=["application"],
                condition=Q(application__isnull=False),
                name="uniq_chatroom_application",
            ),
            models.CheckConstraint(
                check=(
                    (Q(rental__isnull=True) & Q(purchase__isnull=True) & Q(application__isnull=True))
                    | (Q(rental__isnull=False) & Q(purchase__isnull=True) & Q(application__isnull=True))
                    | (Q(rental__isnull=True) & Q(purchase__isnull=False) & Q(application__isnull=True))
                    | (Q(rental__isnull=True) & Q(purchase__isnull=True) & Q(application__isnull=False))
                ),
                name="chk_chatroom_single_transaction",
            ),
        ]

class ChatMessage(models.Model):
    room  = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    user  = models.ForeignKey(User, on_delete=models.CASCADE)
    body  = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


@receiver(post_save, sender=ChatMessage)
def notify_chat_message(sender, instance, created, **kwargs):
    if not created or Notification is None:
        return
    room = instance.room
    sender_id = instance.user_id
    if sender_id == room.user1_id:
        recipient_id = room.user2_id
    elif sender_id == room.user2_id:
        recipient_id = room.user1_id
    else:
        return

    sender_name = getattr(instance.user, "username", "User")
    product_title = getattr(getattr(room, "product", None), "title", "") or ""
    snippet = (instance.body or "").strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = f"{snippet[:117]}..."
    if product_title:
        body = f"{product_title} / {sender_name}: {snippet}"
    else:
        body = f"{sender_name}: {snippet}"
    Notification.objects.create(user_id=recipient_id, kind="chat", body=body)
