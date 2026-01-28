from datetime import timedelta

from django.utils import timezone

from marketplace.models import Purchase


def _purchase_status_value(purchase):
    return str(getattr(purchase, "status", "") or "")


def is_purchase_canceled(purchase):
    status = _purchase_status_value(purchase)
    return status in {
        getattr(Purchase.Status, "CANCELED", "CANCELED"),
        "CANCELED",
        "キャンセル",
    }


def is_purchase_completed(purchase):
    status = _purchase_status_value(purchase)
    return status in {
        getattr(Purchase.Status, "COMPLETED", "COMPLETED"),
        "COMPLETED",
        "完了",
    }


def purchase_chat_deadline(purchase, last_message_at=None):
    if not is_purchase_completed(purchase):
        return None
    base = (
        last_message_at
        or getattr(purchase, "completed_date", None)
        or getattr(purchase, "shipped_at", None)
        or getattr(purchase, "created_at", None)
    )
    if not base:
        return None
    return base + timedelta(days=14)


def is_purchase_chat_available(purchase, last_message_at=None):
    if is_purchase_canceled(purchase):
        return False
    deadline = purchase_chat_deadline(purchase, last_message_at=last_message_at)
    if deadline is None:
        return True
    return timezone.now() <= deadline
