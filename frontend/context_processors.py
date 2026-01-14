try:
    from notifications.models import Notification
except Exception:
    Notification = None


def notifications_context(request):
    if Notification is None or not request.user.is_authenticated:
        return {"notifications_unread_count": 0, "notifications_recent": []}
    try:
        qs = Notification.objects.filter(user=request.user).order_by("-created_at")
        return {
            "notifications_unread_count": qs.filter(read_at__isnull=True).count(),
            "notifications_recent": list(qs[:5]),
        }
    except Exception:
        return {"notifications_unread_count": 0, "notifications_recent": []}
