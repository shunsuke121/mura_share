# frontend/views.py  — 整理済み

from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q, Prefetch, Exists, OuterRef, Value, BooleanField, Count, Subquery
from django.db.models.functions import Coalesce
from django.http import (
    JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, Http404
)
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, TemplateView

import re

from accounts.models import Profile
from .models import ContactInquiry
from chat.models import ChatRoom, ChatMessage
from marketplace.models import (
    Product, ProductImage, RentalApplication, Rental, Purchase, ProductFavorite, Shipment
)

# 通知アプリが無い環境でも落ちないように
try:
    from notifications.models import Notification
except Exception:
    Notification = None


# ========= 定数 =========

CATEGORIES = [
    "電子機器", "家具", "スポーツ用品", "楽器", "車両",
    "アウトドア用品", "ファッション", "書籍・メディア", "その他",
]

COMPLETED_STATUSES = ("完了", "キャンセル")

MAX_UPLOAD_MB = 5
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif",
    "application/pdf", "application/zip",
}


# ========= ヘルパ =========

def _is_valid_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))


def _create_notification(
    recipient_email,
    title,
    message,
    related_id=None,
    action_url_name=None,
    kind="rental",
    action_url_kwargs=None
):
    if Notification is None:
        return
    url = ""
    if action_url_name:
        try:
            url = reverse(action_url_name, kwargs=action_url_kwargs or {})
        except Exception:
            url = action_url_name
    try:
        try:
            field_names = {
                f.name for f in Notification._meta.get_fields()
                if getattr(f, "concrete", True)
            }
        except Exception:
            field_names = set()

        def pick(*candidates):
            for c in candidates:
                if c in field_names:
                    return c
            return None

        def resolve_user(value):
            if value is None:
                return None
            if hasattr(value, "id"):
                return value
            email = str(value or "").strip()
            if not email:
                return None
            try:
                return get_user_model().objects.filter(email=email).first()
            except Exception:
                return None

        if "user" in field_names:
            user = resolve_user(recipient_email)
            if not user:
                return
            body = message or title or ""
            if title and message:
                body = f"{title} - {message}"
            data = {"user": user}
            k = pick("message", "body", "content")
            if k:
                data[k] = body
            k = pick("type", "kind", "category")
            if k:
                data[k] = kind
            Notification.objects.create(**data)
            return

        data = {}
        k = pick("recipient_email", "email", "to_email")
        if k: data[k] = recipient_email or ""
        k = pick("title", "subject")
        if k: data[k] = (title or "")[:255]
        k = pick("message", "body", "content")
        if k: data[k] = message or ""
        k = pick("type", "kind", "category")
        if k: data[k] = kind
        k = pick("related_id", "object_id", "target_id")
        if k and related_id is not None: data[k] = related_id
        k = pick("action_url", "url", "link_url")
        if k and url: data[k] = url
        if data:
            Notification.objects.create(**data)
    except Exception:
        return


def _ensure_owner(user, rental: Rental):
    if rental.product.owner_id != user.id:
        raise ValueError("オーナー以外は実行できません。")


def _ensure_renter(user, rental: Rental):
    if rental.renter_id != user.id:
        raise ValueError("借り手以外は実行できません。")


def _available_quantity_for(product):
    current = getattr(product, "available_quantity", None)
    if current is None:
        current = getattr(product, "stock_quantity", 0)
    return current or 0


def _adjust_available_quantity(product, delta):
    if not hasattr(product, "available_quantity"):
        return
    current = _available_quantity_for(product)
    new_value = current + (delta or 0)
    stock_limit = getattr(product, "stock_quantity", None)
    if stock_limit is not None:
        new_value = min(new_value, stock_limit)
    if new_value < 0:
        new_value = 0
    product.available_quantity = new_value
    product.save(update_fields=["available_quantity"])


def _strip_return_tracking_line(message):
    if not message:
        return ""
    lines = [
        line for line in str(message).splitlines()
        if not line.startswith("[返却追跡番号]")
    ]
    return "\n".join(lines).strip()


def _handle_rental_action(request, user, redirect_name):
    action = request.POST.get("action")
    rental_id = request.POST.get("rental_id")
    tracking_number = request.POST.get("tracking_number", "").strip()

    rental = get_object_or_404(
        Rental.objects.select_related("product", "renter", "product__owner"),
        id=rental_id,
    )

    try:
        if action == "approve":
            _ensure_owner(user, rental)
            if rental.status != "申請中":
                raise ValueError("申請中のみ承認できます。")
            rental.status = "承認済み"
            rental.save(update_fields=["status"])

            product = rental.product
            current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
            product.available_quantity = (current_available or 0) - (rental.quantity or 1)
            product.save(update_fields=["available_quantity"])

            _create_shipment_for_rental(
                rental,
                getattr(Shipment.Direction, "OUTBOUND", "outbound"),
            )

            _create_notification(
                rental.renter,
                "レンタル承認",
                f"「{rental.product_title}」のレンタルが承認されました。",
                rental.id,
                redirect_name,
                kind="rental",
            )
            from django.contrib import messages
            messages.success(request, "レンタルを承認しました。")

        elif action == "ship":
            _ensure_owner(user, rental)
            if rental.status != "承認済み":
                raise ValueError("承認済みのみ発送できます。")
            if not tracking_number:
                raise ValueError("追跡番号を入力してください。")

            rental.status = "発送済み"
            rental.shipped_date_to_renter = timezone.now()
            rental.tracking_number_to_renter = tracking_number
            rental.save(update_fields=["status", "shipped_date_to_renter", "tracking_number_to_renter"])

            # ▼ 追加: 配送(往路)レコードを起票
            owner_p  = Profile.objects.filter(user=rental.product.owner).first()
            renter_p = Profile.objects.filter(user=rental.renter).first()
            Shipment.objects.update_or_create(
                rental=rental,
                direction=getattr(Shipment.Direction, "OUTBOUND", "outbound"),
                defaults={
                    "kind": getattr(Shipment.Kind, "RENTAL", "rental"),
                    "product": rental.product,
                    "from_name":  (getattr(owner_p,  "display_name", "") or rental.product.owner.username)[:120],
                    "from_phone": getattr(owner_p,  "phone", "")[:40],
                    "from_address": getattr(owner_p, "address", "")[:255],
                    "to_name":    (getattr(renter_p, "display_name", "") or rental.renter.username)[:120],
                    "to_phone":   getattr(renter_p, "phone", "")[:40],
                    "to_address": (rental.shipping_address or getattr(renter_p, "address", ""))[:255],
                    "tracking_no": tracking_number,
                    "status": getattr(Shipment.Status, "IN_TRANSIT", "in_transit"),
                    "is_platform_intermediated": True,
                }
            )


            _create_notification(
                rental.renter,
                "商品発送のお知らせ",
                f"「{rental.product_title}」が発送されました。到着したら「受取完了」を押してください。",
                rental.id,
                redirect_name,
                kind="rental",
            )
            from django.contrib import messages
            messages.success(request, "商品を発送済みに更新しました。")

        elif action == "receive":
            _ensure_renter(user, rental)
            if rental.status != "発送済み":
                raise ValueError("発送済みのみ受取完了にできます。")

            now = timezone.now()
            rental.status = "レンタル中"
            rental.received_date_by_renter = now
            rental.rental_start_date = now
            rental.save(update_fields=["status", "received_date_by_renter", "rental_start_date"])

            _create_notification(
                rental.product.owner,
                "商品受け取り完了",
                f"「{rental.product_title}」が借り手に届き、レンタルが開始されました。",
                rental.id,
                redirect_name,
                kind="rental",
            )
            from django.contrib import messages
            messages.success(request, "受取完了として更新しました。")

        elif action == "return_ship":
            _ensure_renter(user, rental)
            if rental.status != "レンタル中":
                raise ValueError("レンタル中のみ返却発送にできます。")
            if not tracking_number:
                raise ValueError("返却の追跡番号を入力してください。")

            rental.status = "返却発送済み"
            rental.shipped_date_return = timezone.now()
            rental.tracking_number_return = tracking_number
            rental.save(update_fields=["status", "shipped_date_return", "tracking_number_return"])

            # ▼ 追加: 配送(返却)レコードを起票
            owner_p  = Profile.objects.filter(user=rental.product.owner).first()
            renter_p = Profile.objects.filter(user=rental.renter).first()
            Shipment.objects.update_or_create(
                rental=rental,
                direction=getattr(Shipment.Direction, "RETURN", "return"),
                defaults={
                    "kind": getattr(Shipment.Kind, "RENTAL", "rental"),
                    "product": rental.product,
                    "from_name":  (getattr(renter_p, "display_name", "") or rental.renter.username)[:120],
                    "from_phone": getattr(renter_p, "phone", "")[:40],
                    "from_address": getattr(renter_p, "address", "")[:255],
                    "to_name":    (getattr(owner_p,  "display_name", "") or rental.product.owner.username)[:120],
                    "to_phone":   getattr(owner_p,  "phone", "")[:40],
                    "to_address": getattr(owner_p,  "address", "")[:255],
                    "tracking_no": tracking_number,
                    "status": getattr(Shipment.Status, "IN_TRANSIT", "in_transit"),
                    "is_platform_intermediated": True,
                }
            )


            _create_notification(
                rental.product.owner,
                "商品返却発送のお知らせ",
                f"「{rental.product_title}」が返却のために発送されました。到着確認をしてください。",
                rental.id,
                redirect_name,
                kind="rental",
            )
            from django.contrib import messages
            messages.success(request, "返却発送済みに更新しました。")

        elif action == "confirm_return":
            _ensure_owner(user, rental)
            if rental.status != "返却発送済み":
                raise ValueError("返却発送済みのみ完了にできます。")

            now = timezone.now()
            rental.status = "完了"
            rental.completed_date = now
            rental.save(update_fields=["status", "completed_date"])

            product = rental.product
            current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
            product.available_quantity = (current_available or 0) + (rental.quantity or 1)
            product.save(update_fields=["available_quantity"])

            for notify_user in [rental.renter, rental.product.owner]:
                _create_notification(
                    notify_user,
                    "レンタル完了",
                    f"「{rental.product_title}」のレンタルが完了しました。",
                    rental.id,
                    "frontend:profile",
                    kind="rental",
                )
            if hasattr(user, "completed_rentals") and user.id in (rental.renter_id, rental.product.owner_id):
                user.completed_rentals = (user.completed_rentals or 0) + 1
                user.save(update_fields=["completed_rentals"])

            from django.contrib import messages
            messages.success(request, "返却完了として更新しました。")

        elif action == "cancel":
            if user.id not in (rental.renter_id, rental.product.owner_id):
                raise ValueError("キャンセル権限がありません。")
            if rental.status not in ("申請中", "承認済み"):
                raise ValueError("申請中・承認済みのみキャンセル可能です。")

            prev = rental.status
            rental.status = "キャンセル"
            rental.save(update_fields=["status"])

            if prev in ("承認済み", "発送済み"):
                product = rental.product
                current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
                product.available_quantity = (current_available or 0) + (rental.quantity or 1)
                product.save(update_fields=["available_quantity"])

            for notify_user in [rental.renter, rental.product.owner]:
                _create_notification(
                    notify_user,
                    "レンタルキャンセル",
                    f"「{rental.product_title}」のレンタルがキャンセルされました。",
                    rental.id,
                    redirect_name,
                    kind="rental",
                )
            from django.contrib import messages
            messages.success(request, "レンタルをキャンセルしました。")

        else:
            raise ValueError("不明なアクションです。")

    except Exception as e:
        from django.contrib import messages
        messages.error(request, f"処理に失敗しました: {e}")

    return redirect(redirect_name)


def _handle_purchase_action(request, redirect_name):
    user = request.user
    action = request.POST.get("action")
    pid = request.POST.get("purchase_id")
    tracking = (request.POST.get("tracking_number") or "").strip()

    purchase = get_object_or_404(
        Purchase.objects.select_related("product", "buyer", "product__owner"),
        id=pid,
    )

    P = getattr(Purchase, "Status", None)
    S_PENDING   = (getattr(P, "PENDING",   "PENDING"))
    S_APPROVED  = (getattr(P, "APPROVED",  "APPROVED"))
    S_SHIPPED   = (getattr(P, "SHIPPED",   "SHIPPED"))
    S_COMPLETED = (getattr(P, "COMPLETED", "COMPLETED"))
    S_CANCELED  = (getattr(P, "CANCELED",  "CANCELED"))

    st_now = purchase.status or ""
    is_pending_like = st_now in (S_PENDING, "REQUESTED", "申請中")

    try:
        with transaction.atomic():
            if action == "approve":
                if purchase.product.owner_id != user.id:
                    raise ValueError("承認権限がありません。")
                if not is_pending_like:
                    raise ValueError("承認待ちのみ承認できます。")

                is_from_rental = bool(getattr(purchase, "from_rental", False))
                now = timezone.now()
                if is_from_rental:
                    purchase.status = S_COMPLETED
                    update_fields = ["status"]
                    if hasattr(purchase, "approved_at"):
                        purchase.approved_at = now
                        update_fields.append("approved_at")
                    if hasattr(purchase, "completed_date"):
                        purchase.completed_date = now
                        update_fields.append("completed_date")
                    purchase.save(update_fields=update_fields)
                    _close_active_rental_for_purchase(purchase)
                    from django.contrib import messages
                    messages.success(request, "承認しました。購入手続き完了です。")
                else:
                    purchase.status = S_APPROVED
                    if hasattr(purchase, "approved_at"):
                        purchase.approved_at = now
                        purchase.save(update_fields=["status", "approved_at"])
                    else:
                        purchase.save(update_fields=["status"])
                    _create_shipment_for_purchase(
                        purchase,
                        getattr(Shipment.Direction, "OUTBOUND", "outbound"),
                    )
                    from django.contrib import messages
                    messages.success(request, "承認しました。追跡番号入力が有効になりました。")

            elif action == "ship":
                if purchase.product.owner_id != user.id:
                    raise ValueError("発送権限がありません。")
                if getattr(purchase, "from_rental", False):
                    raise ValueError("レンタル購入は配送不要です。")
                if purchase.status != S_APPROVED:
                    raise ValueError("承認済みのみ配送できます。")
                if not tracking:
                    raise ValueError("追跡番号を入力してください。")

                purchase.tracking_number = tracking
                purchase.status = S_SHIPPED
                update_fields = ["tracking_number", "status"]

                if hasattr(purchase, "shipped_at"):
                    purchase.shipped_at = timezone.now()
                    update_fields.append("shipped_at")

                purchase.save(update_fields=update_fields)

                # ▼ 配送(往路)レコードを作成/更新
                seller_p = Profile.objects.filter(user=purchase.product.owner).first()
                buyer_p  = Profile.objects.filter(user=purchase.buyer).first()

                from_name  = (getattr(seller_p, "display_name", "") or purchase.product.owner.username)[:120]
                from_phone = (getattr(seller_p, "phone", "") or "")[:40]
                from_addr  = (getattr(seller_p, "address", "") or "")[:255]

                ship_addr  = (getattr(purchase, "shipping_address", "") or getattr(buyer_p, "address", "") or "")[:255]
                to_name    = (getattr(buyer_p, "display_name", "") or purchase.buyer.username)[:120]
                to_phone   = (getattr(buyer_p, "phone", "") or "")[:40]

                Shipment.objects.update_or_create(
                    purchase=purchase,
                    direction=getattr(Shipment.Direction, "OUTBOUND", "outbound"),
                    defaults={
                        "kind": getattr(Shipment.Kind, "PURCHASE", "purchase"),
                        "product": purchase.product,
                        "from_name": from_name,
                        "from_phone": from_phone,
                        "from_address": from_addr,
                        "to_name": to_name,
                        "to_phone": to_phone,
                        "to_address": ship_addr,
                        "tracking_no": tracking,
                        "status": getattr(Shipment.Status, "IN_TRANSIT", "in_transit"),
                        "is_platform_intermediated": True,
                    }
                )


                from django.contrib import messages
                messages.success(request, "発送済みに更新しました。")

            elif action == "complete":
                if purchase.buyer_id != user.id:
                    raise ValueError("受取完了は購入者のみ可能です。")
                if purchase.status not in (S_APPROVED, S_SHIPPED):
                    raise ValueError("承認後のみ受取完了にできます。")

                purchase.status = S_COMPLETED
                if hasattr(purchase, "completed_date"):
                    purchase.completed_date = timezone.now()
                    purchase.save(update_fields=["status", "completed_date"])
                else:
                    purchase.save(update_fields=["status"])

                # ▼ 配送ステータスを配達完了系に寄せる
                Shipment.objects.filter(
                    purchase=purchase,
                    direction=getattr(Shipment.Direction, "OUTBOUND", "outbound"),
                ).update(status=getattr(Shipment.Status, "DELIVERED", "delivered"))

                _close_active_rental_for_purchase(purchase)

                from django.contrib import messages
                messages.success(request, "受取完了として更新しました。")

            elif action == "cancel":
                if user.id not in (purchase.buyer_id, purchase.product.owner_id):
                    raise ValueError("キャンセル権限がありません。")
                if not is_pending_like:
                    raise ValueError("承認待ちのみキャンセルできます。")

                purchase.status = S_CANCELED
                purchase.save(update_fields=["status"])
                if not _has_active_rental_for_purchase(purchase):
                    _adjust_available_quantity(purchase.product, purchase.quantity or 1)
                from django.contrib import messages
                messages.success(request, "キャンセルしました。")

            else:
                raise ValueError("不明なアクションです。")

    except Exception as e:
        from django.contrib import messages
        messages.error(request, f"処理に失敗しました: {e}")

    return redirect(redirect_name)


def _purchase_closed_statuses():
    return {
        getattr(Purchase.Status, "CANCELED", "CANCELED"),
        getattr(Purchase.Status, "COMPLETED", "COMPLETED"),
        "CANCELED",
        "COMPLETED",
        "キャンセル",
        "完了",
    }


def _purchase_completed_statuses():
    return {
        getattr(Purchase.Status, "COMPLETED", "COMPLETED"),
        "COMPLETED",
        "completed",
        "完了",
    }


def _purchase_return_in_progress(purchase):
    rs = str(getattr(purchase, "return_status", "") or "").upper()
    return rs in ("REQUESTED", "APPROVED", "SHIPPED")


def _purchase_is_completed(purchase):
    st = str(getattr(purchase, "status", "") or "")
    completed = getattr(Purchase.Status, "COMPLETED", "COMPLETED")
    return st in (completed, "COMPLETED")


def _purchase_can_hide(purchase):
    if _purchase_return_in_progress(purchase):
        return False
    rs = str(getattr(purchase, "return_status", "") or "").upper()
    if rs in ("RECEIVED", "REJECTED"):
        return True
    return _purchase_is_completed(purchase)


def _prepare_purchase_items(qs):
    items = list(qs)
    for p in items:
        p.can_hide = _purchase_can_hide(p)
    return items


def _purchase_completed_for_app(app):
    if not app or not app.product_id or not app.renter_id:
        return False
    qs = Purchase.objects.filter(
        product_id=app.product_id,
        buyer_id=app.renter_id,
        status__in=_purchase_completed_statuses(),
    )
    if hasattr(Purchase, "from_rental"):
        if qs.filter(from_rental=True).exists():
            return True
        if getattr(app, "created_at", None):
            qs = qs.filter(created_at__gte=app.created_at)
    return qs.exists()


def _has_open_purchase(product, buyer):
    if not product or not buyer:
        return False
    return (Purchase.objects
            .filter(product=product, buyer=buyer)
            .exclude(status__in=_purchase_closed_statuses())
            .exists())


def _allow_purchase_for_product(product):
    t = getattr(product, "availability_type", None)
    return t in (
        getattr(Product.Availability, "BOTH", "レンタル・販売両方"),
        getattr(Product.Availability, "SALE_ONLY", "販売のみ"),
        "レンタル・販売両方",
        "販売のみ",
    )


def _has_active_rental_for_purchase(purchase):
    if not purchase or not purchase.product_id or not purchase.buyer_id:
        return False
    rental_active = Rental.objects.filter(
        product_id=purchase.product_id,
        renter_id=purchase.buyer_id,
        status=Rental.Status.RENTING,
    ).exists()
    app_active = RentalApplication.objects.filter(
        product_id=purchase.product_id,
        renter_id=purchase.buyer_id,
        order_type=RentalApplication.OrderType.RENTAL,
        status__in=["renting", "received"],
    ).exists()
    return rental_active or app_active


def _close_active_rental_for_purchase(purchase):
    if not purchase or not purchase.product_id or not purchase.buyer_id:
        return
    now = timezone.now()
    Rental.objects.filter(
        product_id=purchase.product_id,
        renter_id=purchase.buyer_id,
        status=Rental.Status.RENTING,
    ).update(
        status=Rental.Status.COMPLETED,
        completed_date=now,
    )

    app_qs = RentalApplication.objects.filter(
        product_id=purchase.product_id,
        renter_id=purchase.buyer_id,
        order_type=RentalApplication.OrderType.RENTAL,
        status__in=["renting", "received"],
    )
    if app_qs.exists():
        update_fields = {"status": RentalApplication.Status.COMPLETED}
        app_field_names = {f.name for f in RentalApplication._meta.get_fields()}
        if "completed_date" in app_field_names:
            update_fields["completed_date"] = now
        app_qs.update(**update_fields)


def _create_purchase_from_rental(
    product,
    buyer,
    quantity,
    payment_method,
    shipping_address,
    shipping_postal_code="",
    message_txt="",
    purchase_price=None,
):
    try:
        initial_status = Purchase.Status.PENDING
    except Exception:
        initial_status = getattr(Purchase.Status, "REQUESTED", "REQUESTED")

    create_kwargs = {
        "product": product,
        "buyer": buyer,
        "quantity": quantity or 1,
        "status": initial_status,
    }
    if hasattr(Purchase, "product_title"):
        create_kwargs["product_title"] = getattr(product, "title", "")
    if hasattr(Purchase, "buyer_email"):
        create_kwargs["buyer_email"] = getattr(buyer, "email", "")
    if hasattr(Purchase, "seller_email"):
        owner = getattr(product, "owner", None)
        create_kwargs["seller_email"] = getattr(owner, "email", "") if owner else ""
    if hasattr(Purchase, "shipping_address"):
        create_kwargs["shipping_address"] = shipping_address or ""
    if hasattr(Purchase, "shipping_postal_code"):
        create_kwargs["shipping_postal_code"] = shipping_postal_code or ""
    if hasattr(Purchase, "payment_method"):
        create_kwargs["payment_method"] = payment_method or ""
    if hasattr(Purchase, "message"):
        create_kwargs["message"] = message_txt or ""
    if hasattr(Purchase, "from_rental"):
        create_kwargs["from_rental"] = True
    if purchase_price is not None and hasattr(Purchase, "purchase_price"):
        create_kwargs["purchase_price"] = max(int(purchase_price), 0)

    return Purchase.objects.create(**create_kwargs)


def _rental_purchase_pricing(
    product,
    quantity,
    start_date=None,
    end_date=None,
    rental_start_date=None,
    total_price=None,
    total_days=None,
):
    qty = quantity or 1
    purchase_price = (getattr(product, "price_buy", 0) or 0) * qty

    start = None
    if rental_start_date:
        start = rental_start_date.date() if hasattr(rental_start_date, "date") else rental_start_date
    elif start_date:
        start = start_date

    days_total = None
    if start_date and end_date:
        days_total = (end_date - start_date).days + 1
        if days_total < 1:
            days_total = None

    days_used = None
    if start:
        today = timezone.localdate()
        days_used = (today - start).days + 1
        if days_used < 1:
            days_used = 1
        if days_total:
            days_used = min(days_used, days_total)
    elif total_days:
        days_used = total_days

    daily_price = getattr(product, "price_per_day", 0) or 0
    rental_cost = 0
    if daily_price and days_used:
        rental_cost = daily_price * days_used * qty
    elif total_price:
        if total_days and days_used and total_days > 0:
            rental_cost = int(round((total_price * days_used) / total_days))
        else:
            rental_cost = total_price

    rental_cost = max(int(rental_cost or 0), 0)
    payable = purchase_price - rental_cost
    if payable < 0:
        payable = 0

    return {
        "purchase_price": purchase_price,
        "rental_cost": rental_cost,
        "payable": payable,
        "days_used": days_used,
        "days_total": days_total,
        "qty": qty,
    }


@login_required
def rental_purchase(request, rental_id):
    rental = get_object_or_404(
        Rental.objects.select_related("product", "renter", "product__owner"),
        id=rental_id,
    )
    back = request.META.get("HTTP_REFERER") or "frontend:rentals"
    if rental.renter_id != request.user.id:
        messages.error(request, "購入権限がありません。")
        return redirect(back)
    if rental.status != Rental.Status.RENTING:
        messages.error(request, "レンタル中のみ購入できます。")
        return redirect(back)

    product = rental.product
    if not product or not _allow_purchase_for_product(product):
        messages.error(request, "この商品は購入できません。")
        return redirect(back)
    if _has_open_purchase(product, request.user):
        messages.info(request, "既に購入申請済みです。")
        return redirect("frontend:purchases")

    payment_method = (getattr(rental, "payment_method", "") or "").strip()
    if not payment_method:
        messages.error(request, "決済方法が未設定のため購入できません。")
        return redirect(back)

    shipping_address = (getattr(rental, "shipping_address", "") or "").strip()
    if not shipping_address:
        profile = Profile.objects.filter(user=request.user).first()
        shipping_address = (getattr(profile, "address", "") or "").strip()

    pricing = _rental_purchase_pricing(
        product=product,
        quantity=getattr(rental, "quantity", 1) or 1,
        start_date=getattr(rental, "start_date", None),
        end_date=getattr(rental, "end_date", None),
        rental_start_date=getattr(rental, "rental_start_date", None) or getattr(rental, "received_date_by_renter", None),
        total_price=getattr(rental, "total_price", None),
        total_days=getattr(rental, "total_days", None),
    )

    if request.method == "GET":
        return render(request, "frontend/purchases/rental_confirm.html", {
            "product": product,
            "rental": rental,
            "pricing": pricing,
            "confirm_url": reverse("frontend:rental_purchase", args=[rental.id]),
            "back_url": back,
            "mode": "rental",
        })

    purchase = _create_purchase_from_rental(
        product=product,
        buyer=request.user,
        quantity=getattr(rental, "quantity", 1) or 1,
        payment_method=payment_method,
        shipping_address=shipping_address,
        message_txt=_strip_return_tracking_line(getattr(rental, "message", "")),
        purchase_price=pricing["payable"],
    )

    try:
        _create_notification(
            product.owner,
            "購入申請が届きました",
            f"「{getattr(product, 'title', '商品')}」の購入申請が届きました。",
            getattr(purchase, "id", None),
            "frontend:purchases",
            kind="purchase",
        )
    except Exception:
        pass

    messages.success(request, "購入申請を作成しました。")
    return redirect("frontend:purchases")


@login_required
def rental_app_purchase(request, app_id):
    app = get_object_or_404(
        RentalApplication.objects.select_related("product", "owner", "renter"),
        id=app_id,
        renter=request.user,
    )
    back = request.META.get("HTTP_REFERER") or "frontend:my_applications"
    if getattr(app, "order_type", "") != RentalApplication.OrderType.RENTAL:
        messages.error(request, "レンタル申請のみ購入できます。")
        return redirect(back)

    status_now = str(getattr(app, "status", "")).lower()
    if status_now not in ("renting", "received"):
        messages.error(request, "レンタル中のみ購入できます。")
        return redirect(back)

    product = app.product
    if not product or not _allow_purchase_for_product(product):
        messages.error(request, "この商品は購入できません。")
        return redirect(back)
    if _has_open_purchase(product, request.user):
        messages.info(request, "既に購入申請済みです。")
        return redirect("frontend:purchases")

    payment_method = (getattr(app, "payment_method", "") or "").strip()
    if not payment_method:
        messages.error(request, "決済方法が未設定のため購入できません。")
        return redirect(back)

    shipping_address = (getattr(app, "address", "") or "").strip()
    if not shipping_address:
        profile = Profile.objects.filter(user=request.user).first()
        shipping_address = (getattr(profile, "address", "") or "").strip()

    pricing = _rental_purchase_pricing(
        product=product,
        quantity=getattr(app, "quantity", 1) or 1,
        start_date=getattr(app, "start_date", None),
        end_date=getattr(app, "end_date", None),
        rental_start_date=getattr(app, "rental_start_date", None) or getattr(app, "received_date_by_renter", None),
    )

    if request.method == "GET":
        return render(request, "frontend/purchases/rental_confirm.html", {
            "product": product,
            "application": app,
            "pricing": pricing,
            "confirm_url": reverse("frontend:rental_app_purchase", args=[app.id]),
            "back_url": back,
            "mode": "application",
        })

    purchase = _create_purchase_from_rental(
        product=product,
        buyer=request.user,
        quantity=getattr(app, "quantity", 1) or 1,
        payment_method=payment_method,
        shipping_address=shipping_address,
        shipping_postal_code=(getattr(app, "postal_code", "") or "").strip(),
        message_txt=_strip_return_tracking_line(getattr(app, "message", "")),
        purchase_price=pricing["payable"],
    )

    try:
        _create_notification(
            product.owner,
            "購入申請が届きました",
            f"「{getattr(product, 'title', '商品')}」の購入申請が届きました。",
            getattr(purchase, "id", None),
            "frontend:purchases",
            kind="purchase",
        )
    except Exception:
        pass

    messages.success(request, "購入申請を作成しました。")
    return redirect("frontend:purchases")


# ========= 商品一覧・詳細 =========

class ProductListView(ListView):
    model = Product
    template_name = "frontend/products/index.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.filter(status=Product.Status.LISTED)

        r = self.request.GET
        q   = (r.get("q") or "").strip()
        cat = (r.get("category") or "all").strip()
        av  = (r.get("availability") or "all").strip()
        sort= (r.get("sort") or "newest").strip()

        self.selected = {"q": q, "category": cat, "availability": av, "sort": sort}

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        if cat and cat != "all":
            qs = qs.filter(category=cat)

        if av and av != "all":
            qs = qs.filter(availability_type=av)

        if sort == "price_low":
            qs = qs.order_by("price_buy", "-id")
        elif sort == "price_high":
            qs = qs.order_by("-price_buy", "-id")
        else:
            qs = qs.order_by("-id")

        u = self.request.user
        if u.is_authenticated:
            fav_exists = ProductFavorite.objects.filter(user=u, product_id=OuterRef("pk"))
            qs = qs.annotate(is_favorited=Exists(fav_exists))
        else:
            qs = qs.annotate(is_favorited=Value(False, output_field=BooleanField()))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = CATEGORIES
        ctx["selected"] = getattr(self, "selected", {
            "q": "", "category": "all", "availability": "all", "sort": "newest",
        })

        fav_ids = set()
        u = self.request.user
        if u.is_authenticated:
            fav_ids = set(
                ProductFavorite.objects
                .filter(user=u)
                .values_list("product_id", flat=True)
            )

        products = ctx.get("products") or []
        for p in products:
            p.is_favorited = (p.id in fav_ids)

        return ctx


class ProductDetailView(DetailView):
    model = Product
    template_name = "frontend/products/detail.html"
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.object

        ctx["images"] = p.images.all() if hasattr(p, "images") else ProductImage.objects.none()

        user = self.request.user
        is_owner = user.is_authenticated and getattr(p, "owner_id", None) == user.id
        ctx["is_owner"] = is_owner

        t = getattr(p, "availability_type", "レンタル・販売両方")
        allow_rental = t in ("レンタル・販売両方", "レンタルのみ")
        allow_purchase = t in ("レンタル・販売両方", "販売のみ")
        ctx["allow_rental"] = allow_rental
        ctx["allow_purchase"] = allow_purchase

        return ctx


# ========= 単純ページ / テンプレ表示 =========

class PurchaseListView(TemplateView):
    template_name = "frontend/purchases/index.html"


class ReturnListPage(TemplateView):
    template_name = "frontend/returns/index.html"


class MessagesPage(LoginRequiredMixin, TemplateView):
    template_name = "frontend/messages/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        purchases = (
            Purchase.objects
            .select_related("product", "buyer", "product__owner", "buyer__profile", "product__owner__profile")
            .filter(Q(buyer=user) | Q(product__owner=user))
            .order_by("-created_at")
        )
        rentals = (
            Rental.objects
            .select_related("product", "renter", "product__owner", "renter__profile", "product__owner__profile")
            .filter(Q(renter=user) | Q(product__owner=user))
            .order_by("-created_at")
        )
        applications = (
            RentalApplication.objects
            .select_related("product", "owner", "renter", "owner__profile", "renter__profile")
            .filter(Q(owner=user) | Q(renter=user))
            .order_by("-created_at")
        )
        pending_purchase_status = getattr(Purchase.Status, "REQUESTED", None)
        pending_rental_status = getattr(Rental.Status, "REQUESTED", None)
        pending_app_status = getattr(RentalApplication.Status, "PENDING", None)
        if pending_purchase_status:
            purchases = purchases.filter(
                Q(status=pending_purchase_status) | Q(chat_rooms__isnull=False)
            ).distinct()
        if pending_rental_status:
            rentals = rentals.filter(
                Q(status=pending_rental_status) | Q(chat_rooms__isnull=False)
            ).distinct()
        if pending_app_status:
            applications = applications.filter(
                Q(status=pending_app_status) | Q(chat_rooms__isnull=False)
            ).distinct()

        purchase_ids = list(purchases.values_list("id", flat=True))
        rental_ids = list(rentals.values_list("id", flat=True))
        app_ids = list(applications.values_list("id", flat=True))

        last_body_qs = (
            ChatMessage.objects
            .filter(room_id=OuterRef("pk"))
            .order_by("-created_at")
            .values("body")[:1]
        )
        last_at_qs = (
            ChatMessage.objects
            .filter(room_id=OuterRef("pk"))
            .order_by("-created_at")
            .values("created_at")[:1]
        )

        room_qs = ChatRoom.objects.select_related(
            "product",
            "user1",
            "user2",
            "purchase",
            "rental",
            "application",
        )
        if purchase_ids or rental_ids or app_ids:
            room_qs = room_qs.filter(
                Q(purchase_id__in=purchase_ids)
                | Q(rental_id__in=rental_ids)
                | Q(application_id__in=app_ids)
            )
            room_qs = room_qs.annotate(
                last_message_body=Subquery(last_body_qs),
                last_message_at=Subquery(last_at_qs),
                unread_count=Count(
                    "messages",
                    filter=Q(messages__is_read=False) & ~Q(messages__user=user),
                ),
            )
        else:
            room_qs = ChatRoom.objects.none()

        room_by_purchase = {room.purchase_id: room for room in room_qs if room.purchase_id}
        room_by_rental = {room.rental_id: room for room in room_qs if room.rental_id}
        room_by_app = {room.application_id: room for room in room_qs if room.application_id}

        def display_name(target):
            if not target:
                return ""
            prof = getattr(target, "profile", None)
            return (getattr(prof, "display_name", "") or getattr(target, "username", ""))

        transactions = []

        for p in purchases:
            other = p.product.owner if p.buyer_id == user.id else p.buyer
            room = room_by_purchase.get(p.id)
            last_msg_at = getattr(room, "last_message_at", None) if room else None
            transactions.append({
                "kind_label": "購入",
                "created_at": p.created_at,
                "activity_at": last_msg_at or p.created_at,
                "product_title": p.product_title or getattr(p.product, "title", ""),
                "other_name": display_name(other),
                "status_label": p.get_status_display() if hasattr(p, "get_status_display") else p.status,
                "chat_url": reverse("chat:chat_detail", args=[room.id]) if room else reverse("chat:start_purchase_chat", args=[p.id]),
                "last_message": getattr(room, "last_message_body", "") if room else "",
                "unread": getattr(room, "unread_count", 0) if room else 0,
            })

        for r in rentals:
            other = r.product.owner if r.renter_id == user.id else r.renter
            room = room_by_rental.get(r.id)
            last_msg_at = getattr(room, "last_message_at", None) if room else None
            transactions.append({
                "kind_label": "レンタル",
                "created_at": r.created_at,
                "activity_at": last_msg_at or r.created_at,
                "product_title": r.product_title or getattr(r.product, "title", ""),
                "other_name": display_name(other),
                "status_label": r.get_status_display() if hasattr(r, "get_status_display") else r.status,
                "chat_url": reverse("chat:chat_detail", args=[room.id]) if room else reverse("chat:start_rental_chat", args=[r.id]),
                "last_message": getattr(room, "last_message_body", "") if room else "",
                "unread": getattr(room, "unread_count", 0) if room else 0,
            })

        for a in applications:
            other = a.owner if a.renter_id == user.id else a.renter
            order_label = "レンタル" if a.order_type == RentalApplication.OrderType.RENTAL else "購入"
            room = room_by_app.get(a.id)
            last_msg_at = getattr(room, "last_message_at", None) if room else None
            transactions.append({
                "kind_label": order_label,
                "created_at": a.created_at,
                "activity_at": last_msg_at or a.created_at,
                "product_title": getattr(a.product, "title", ""),
                "other_name": display_name(other),
                "status_label": a.get_status_display() if hasattr(a, "get_status_display") else a.status,
                "chat_url": reverse("chat:chat_detail", args=[room.id]) if room else reverse("chat:start_rental_app_chat", args=[a.id]),
                "last_message": getattr(room, "last_message_body", "") if room else "",
                "unread": getattr(room, "unread_count", 0) if room else 0,
            })

        pre_rooms = (
            ChatRoom.objects
            .select_related("product", "user1", "user2")
            .filter(
                Q(user1=user) | Q(user2=user),
                rental__isnull=True,
                purchase__isnull=True,
                application__isnull=True,
            )
            .annotate(
                last_message_body=Subquery(last_body_qs),
                last_message_at=Subquery(last_at_qs),
                unread_count=Count(
                    "messages",
                    filter=Q(messages__is_read=False) & ~Q(messages__user=user),
                ),
            )
        )

        for room in pre_rooms:
            other = room.user1 if room.user1_id != user.id else room.user2
            transactions.append({
                "kind_label": "相談",
                "created_at": room.created_at,
                "activity_at": getattr(room, "last_message_at", None) or room.created_at,
                "product_title": getattr(room.product, "title", ""),
                "other_name": display_name(other),
                "status_label": "取引前",
                "chat_url": reverse("chat:chat_detail", args=[room.id]),
                "last_message": getattr(room, "last_message_body", "") or "",
                "unread": getattr(room, "unread_count", 0) or 0,
            })

        transactions.sort(
            key=lambda item: item.get("activity_at") or item.get("created_at") or timezone.now(),
            reverse=True,
        )
        ctx["transactions"] = transactions
        return ctx


class DocumentationView(TemplateView):
    template_name = "frontend/docs/index.html"


# ========= お気に入り =========

@login_required
@require_POST
def product_favorite_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    fav, created = ProductFavorite.objects.get_or_create(user=request.user, product=product)
    if created:
        return JsonResponse({"ok": True, "favorited": True})
    fav.delete()
    return JsonResponse({"ok": True, "favorited": False})


# ========= レンタル/購入 — 一覧系 =========

@login_required
def rentals_index(request):
    tab = request.GET.get("tab", "mine")
    qs = (
        Rental.objects
        .select_related("product", "renter", "product__owner")
        .order_by("-id")
    )
    mine = qs.filter(renter=request.user)
    received = qs.filter(product__owner=request.user)

    context = {
        "active_tab": "received" if tab == "received" else "mine",
        "mine": mine,
        "received": received,
    }
    return render(request, "frontend/rentals/index.html", context)


@login_required
def my_rentals(request):
    user = request.user
    if request.method == "POST":
        return _handle_rental_action(request, user, "frontend:my_rentals")
    rentals = (
        Rental.objects
        .select_related("product", "renter", "product__owner")
        .filter(renter=user)
        .order_by("-id")
    )
    my_active_rentals = [r for r in rentals if r.status not in COMPLETED_STATUSES]
    return render(request, "frontend/rentals/my_rentals.html", {"my_active_rentals": my_active_rentals})


@login_required
def received_rentals(request):
    user = request.user
    if request.method == "POST":
        return _handle_rental_action(request, user, "frontend:received_rentals")
    rentals = (
        Rental.objects
        .select_related("product", "renter", "product__owner")
        .filter(product__owner=user)
        .order_by("-id")
    )
    received_active_rentals = [r for r in rentals if r.status not in COMPLETED_STATUSES]
    return render(request, "frontend/rentals/received_rentals.html", {"received_active_rentals": received_active_rentals})


@login_required
def purchases_index(request):
    tab = request.GET.get("tab", "mine")
    qs = (Purchase.objects
          .select_related("product", "buyer", "product__owner")
          .order_by("-id"))
    mine = _prepare_purchase_items(qs.filter(buyer=request.user, hidden_by_buyer=False))
    received = _prepare_purchase_items(qs.filter(product__owner=request.user, hidden_by_seller=False))
    context = {
        "active_tab": "received" if tab == "received" else "mine",
        "mine": mine,
        "received": received,
    }
    return render(request, "frontend/purchases/index.html", context)


@login_required
def my_purchases(request):
    if request.method == "POST":
        return _handle_purchase_action(request, redirect_name="frontend:my_purchases")
    items = _prepare_purchase_items(
        Purchase.objects
        .select_related("product", "buyer", "product__owner")
        .filter(buyer=request.user, hidden_by_buyer=False)
        .order_by("-id")
    )
    return render(request, "frontend/purchases/my_purchases.html",
                  {"my_purchases": items, "items": items, "mode": "mine"})


@login_required
def received_purchases(request):
    if request.method == "POST":
        return _handle_purchase_action(request, redirect_name="frontend:received_purchases")
    items = _prepare_purchase_items(
        Purchase.objects
        .select_related("product", "buyer", "product__owner")
        .filter(product__owner=request.user, hidden_by_seller=False)
        .order_by("-id")
    )
    return render(request, "frontend/purchases/received_purchases.html",
                  {"received_purchases": items, "items": items, "mode": "received"})


@login_required
@require_POST
def purchase_hide_mine(request, purchase_id):
    purchase = get_object_or_404(Purchase, id=purchase_id, buyer=request.user)
    if not _purchase_can_hide(purchase):
        messages.warning(request, "完了した取引のみ非表示にできます。")
        return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "frontend:purchases")
    purchase.hidden_by_buyer = True
    purchase.save(update_fields=["hidden_by_buyer"])
    messages.success(request, "非表示にしました。")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "frontend:purchases")


@login_required
@require_POST
def purchase_hide_received(request, purchase_id):
    purchase = get_object_or_404(Purchase, id=purchase_id, product__owner=request.user)
    if not _purchase_can_hide(purchase):
        messages.warning(request, "完了した取引のみ非表示にできます。")
        return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "frontend:purchases")
    purchase.hidden_by_seller = True
    purchase.save(update_fields=["hidden_by_seller"])
    messages.success(request, "非表示にしました。")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "frontend:purchases")


# ========= レンタル/購入 — 申請・管理 =========

@login_required
def rental_manage(request):
    """出品者が受け取った申請一覧（レンタル/購入とも）"""
    apps = list(RentalApplication.objects.filter(
        owner=request.user,
        hidden_by_owner=False,
    ).select_related("product", "renter").order_by("-created_at"))
    STATUS_LABELS = {
        "PENDING": "申請中",
        "APPROVED": "承認済み",
        "SHIPPED": "発送済み",
        "RECEIVED": "受取済み",
        "RENTING": "レンタル中",
        "RETURN_SHIPPED": "返却発送済み",
        "COMPLETED": "完了",
        "REJECTED": "却下",
        "CANCELLED": "キャンセル",
    }
    BADGE_CLASS = {
        "PENDING": "secondary",
        "APPROVED": "primary",
        "SHIPPED": "info",
        "RECEIVED": "success",
        "RENTING": "success",
        "RETURN_SHIPPED": "dark",
        "COMPLETED": "secondary",
        "REJECTED": "danger",
        "CANCELLED": "dark",
    }
    for a in apps:
        a.calc_days = None
        a.calc_price = None
        if a.order_type == RentalApplication.OrderType.RENTAL and a.start_date and a.end_date:
            a.calc_days = (a.end_date - a.start_date).days + 1
            daily = getattr(a.product, "price_per_day", 0) or 0
            a.calc_price = daily * (a.calc_days or 0) * (a.quantity or 1)
        elif a.order_type == RentalApplication.OrderType.PURCHASE:
            price_buy = getattr(a.product, "price_buy", 0) or 0
            a.calc_price = price_buy * (a.quantity or 1)
        s = str(getattr(a, "status", "")).upper()
        a.status_code = s
        a.status_label = STATUS_LABELS.get(s, s)
        a.badge_class = BADGE_CLASS.get(s, "secondary")
        a.purchase_completed = False
        if (
            getattr(a, "order_type", None) == RentalApplication.OrderType.RENTAL
            and _purchase_completed_for_app(a)
        ):
            a.purchase_completed = True
            a.status_label = "購入手続き完了"
            a.badge_class = "secondary"
        a.display_message = _strip_return_tracking_line(getattr(a, "message", ""))
        a.display_message = _strip_return_tracking_line(getattr(a, "message", ""))
    ctx = {
        "applications": apps,
        "active_tab": "received",
        "received_count": len(apps),
        "mine_count": RentalApplication.objects.filter(
            renter=request.user,
            hidden_by_renter=False,
        ).count(),
    }
    return render(request, "frontend/rentals/manage.html", ctx)


@login_required
def purchase_manage(request):
    """出品者が受け取った【購入】申請のみの一覧"""
    apps = list(RentalApplication.objects.filter(
        owner=request.user,
        order_type=RentalApplication.OrderType.PURCHASE
    ).select_related("product", "renter").order_by("-created_at"))

    for a in apps:
        a.calc_days = None
        price_buy = getattr(a.product, "price_buy", 0) or 0
        a.calc_price = price_buy * (a.quantity or 1)

    return render(request, "frontend/purchases/applications.html", {
        "applications": apps,
        "active_tab": "received",
        "received_count": len(apps),
        "mine_count": RentalApplication.objects.filter(
            renter=request.user,
            order_type=RentalApplication.OrderType.PURCHASE,
            hidden_by_renter=False,
        ).count(),
    })


@login_required
def my_applications(request):
    """借り手（自分）が送ったレンタル/購入の申請一覧を表示"""
    apps = (RentalApplication.objects
            .filter(renter=request.user, hidden_by_renter=False)
            .select_related("product", "owner")
            .order_by("-created_at"))

    STATUS_LABELS = {
        "PENDING": "申請中",
        "APPROVED": "承認済み",
        "SHIPPED": "発送済み",
        "RECEIVED": "受取済み",
        "RENTING": "レンタル中",
        "RETURN_SHIPPED": "返却発送済み",
        "COMPLETED": "完了",
        "REJECTED": "却下",
        "CANCELLED": "キャンセル",
    }
    BADGE_CLASS = {
        "PENDING": "secondary",
        "APPROVED": "primary",
        "SHIPPED": "info",
        "RECEIVED": "success",
        "RENTING": "success",
        "RETURN_SHIPPED": "dark",
        "COMPLETED": "secondary",
        "REJECTED": "danger",
        "CANCELLED": "dark",
    }

    for a in apps:
        a.calc_days = None
        a.calc_price = None
        qty = (getattr(a, "quantity", 1) or 1)
        try:
            if a.order_type == RentalApplication.OrderType.RENTAL and a.start_date and a.end_date:
                a.calc_days = (a.end_date - a.start_date).days + 1
                daily = getattr(a.product, "price_per_day", 0) or 0
                a.calc_price = daily * (a.calc_days or 0) * qty
            elif a.order_type == RentalApplication.OrderType.PURCHASE:
                price_buy = getattr(a.product, "price_buy", 0) or 0
                a.calc_price = price_buy * qty
        except Exception:
            pass

        s = str(getattr(a, "status", "")).upper()
        a.status_code = s
        a.status_label = STATUS_LABELS.get(s, s)
        a.badge_class = BADGE_CLASS.get(s, "secondary")
        a.purchase_completed = False
        if (
            getattr(a, "order_type", None) == RentalApplication.OrderType.RENTAL
            and _purchase_completed_for_app(a)
        ):
            a.purchase_completed = True
            a.status_label = "購入手続き完了"
            a.badge_class = "secondary"

    ctx = {
        "applications": apps,
        "active_tab": "mine",
        "mine_count": apps.count(),
        "received_count": RentalApplication.objects.filter(
            owner=request.user,
            hidden_by_owner=False,
        ).count(),
    }
    return render(request, "frontend/rentals/my_applications.html", ctx)


# ---- 申請アクション（承認/却下/発送/受取/返却/完了/キャンセル）

@login_required
def rental_app_approve(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    if request.method == "POST":
        app.status = RentalApplication.Status.APPROVED
        app.save()
        _create_shipment_for_application(
            app,
            getattr(Shipment.Direction, "OUTBOUND", "outbound"),
            status=getattr(Shipment.Status, "CREATED", "created"),
        )
        from django.contrib import messages
        messages.success(request, "申請を承認しました。")
    return redirect("frontend:rental_manage")


@login_required
def rental_app_reject(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    if request.method == "POST":
        status_before = str(getattr(app, "status", "")).upper()
        app.status = RentalApplication.Status.REJECTED
        app.save()
        if status_before in ("PENDING", "APPROVED") and getattr(app, "order_type", "") == RentalApplication.OrderType.RENTAL:
            _adjust_available_quantity(app.product, app.quantity or 1)
        from django.contrib import messages
        messages.info(request, "申請を却下しました。")
    return redirect("frontend:rental_manage")


@login_required
@require_POST
def rental_app_cancel(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, renter=request.user)
    status_now = str(getattr(app, "status", "")).upper()
    from django.contrib import messages
    if status_now in ("PENDING", "APPROVED"):
        try:
            app.status = RentalApplication.Status.CANCELLED
        except Exception:
            app.status = "CANCELLED"
        app.save(update_fields=["status"])
        if getattr(app, "order_type", "") == RentalApplication.OrderType.RENTAL:
            _adjust_available_quantity(app.product, app.quantity or 1)
        messages.info(request, "申請をキャンセルしました。")
    else:
        messages.warning(request, "この申請はキャンセルできません。")
    return redirect("frontend:my_applications")


@login_required
@require_POST
def rental_app_ship(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    from django.contrib import messages

    if app.status != RentalApplication.Status.APPROVED:
        messages.error(request, "承認済みの申請のみ配送できます。")
        return redirect("frontend:rental_manage")

    tracking = (request.POST.get("tracking_number") or "").strip()
    if not tracking:
        messages.error(request, "追跡番号を入力してください。")
        return redirect("frontend:rental_manage")

    app.tracking_number = tracking
    app.status = RentalApplication.Status.SHIPPED
    app.save()

    messages.success(request, "商品を配送しました。相手の受取をお待ちください。")
    return redirect("frontend:rental_manage")


@login_required
@require_POST
def rental_app_receive(request, app_id):
    """借り手側：出品者が発送済みの申請に対して『レンタル開始』"""
    app = get_object_or_404(RentalApplication, id=app_id, renter=request.user)
    from django.contrib import messages

    if (app.status or "").lower() != "shipped":
        messages.warning(request, "出品者が『発送済み』の申請のみレンタル開始できます。")
        return redirect("frontend:my_applications")

    app.status = "renting"
    if hasattr(app, "rental_start_date"):
        app.rental_start_date = timezone.now()
    if hasattr(app, "received_date_by_renter"):
        app.received_date_by_renter = timezone.now()
    app.save()

    try:
        _create_notification(
            app.owner,
            "レンタル開始",
            f"「{getattr(app.product, 'title', '商品')}」のレンタルが開始されました。",
            app.id,
            "frontend:rental_manage",
            kind="rental",
        )
    except Exception:
        pass

    messages.success(request, "レンタルを開始しました。")
    return redirect("frontend:my_applications")


@login_required
@require_POST
def rental_app_return_ship(request, app_id):
    """借り手側：返却発送"""
    app = get_object_or_404(RentalApplication, id=app_id, renter=request.user)
    from django.contrib import messages

    tracking = (request.POST.get("return_tracking_number")
                or request.POST.get("tracking_number") or "").strip()
    if not tracking:
        messages.error(request, "返却の追跡番号を入力してください。")
        return redirect("frontend:my_applications")

    app.return_tracking_number = tracking
    app.message = _strip_return_tracking_line(getattr(app, "message", ""))

    app.status = "return_shipped"
    if hasattr(app, "shipped_date_return"):
        app.shipped_date_return = timezone.now()
    app.save()

    try:
        _create_notification(
            app.owner,
            "返却発送のお知らせ",
            f"「{getattr(app.product, 'title', '商品')}」が返却のため発送されました。",
            app.id,
            "frontend:rental_manage",
            kind="rental",
        )
    except Exception:
        pass

    messages.success(request, "返却を発送しました。出品者の受領をお待ちください。")
    return redirect("frontend:my_applications")


@login_required
@require_POST
def rental_app_confirm_return(request, app_id):
    """出品者側：返却発送済み → 完了"""
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    from django.contrib import messages

    if (app.status or "").lower() != "return_shipped":
        messages.warning(request, "返却発送済みの申請のみレンタル終了できます。")
        return redirect("frontend:rental_manage")

    app.status = "completed"
    if hasattr(app, "completed_date"):
        app.completed_date = timezone.now()
    app.save()
    if getattr(app, "order_type", "") == RentalApplication.OrderType.RENTAL:
        _adjust_available_quantity(app.product, app.quantity or 1)

    try:
        _create_notification(
            app.renter,
            "レンタル完了",
            f"「{getattr(app.product, 'title', '商品')}」のレンタルが完了しました。",
            app.id,
            "frontend:my_applications",
            kind="rental",
        )
        _create_notification(
            app.owner,
            "レンタル完了",
            f"「{getattr(app.product, 'title', '商品')}」のレンタルが完了しました。",
            app.id,
            "frontend:rental_manage",
            kind="rental",
        )
    except Exception:
        pass

    messages.success(request, "返却を受領し、レンタルを終了しました。")
    return redirect("frontend:rental_manage")


@login_required
@require_POST
def rental_app_hide(request, app_id):
    """出品者側：完了済み申請をレンタル管理から非表示にする"""
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    from django.contrib import messages

    if getattr(app, "order_type", "") != RentalApplication.OrderType.RENTAL:
        messages.warning(request, "レンタル申請のみ非表示にできます。")
        return redirect("frontend:rental_manage")

    status_now = str(getattr(app, "status", "")).lower()
    if status_now != "completed" and not _purchase_completed_for_app(app):
        messages.warning(request, "完了した申請のみ非表示にできます。")
        return redirect("frontend:rental_manage")

    app.hidden_by_owner = True
    app.save(update_fields=["hidden_by_owner"])
    messages.success(request, "非表示にしました。")
    return redirect("frontend:rental_manage")


@login_required
@require_POST
def rental_app_hide_mine(request, app_id):
    """借り手側：完了済み申請をマイ申請から非表示にする"""
    app = get_object_or_404(RentalApplication, id=app_id, renter=request.user)
    from django.contrib import messages

    status_now = str(getattr(app, "status", "")).lower()
    if status_now != "completed" and not _purchase_completed_for_app(app):
        messages.warning(request, "完了した申請のみ非表示にできます。")
        return redirect("frontend:my_applications")

    app.hidden_by_renter = True
    app.save(update_fields=["hidden_by_renter"])
    messages.success(request, "非表示にしました。")
    return redirect("frontend:my_applications")


# ========= レンタル/購入 — 完了トリガ =========

@login_required
def rental_finish(request, rental_id):
    r = get_object_or_404(Rental, id=rental_id)
    if r.product.owner != request.user:
        return redirect("frontend:error_403")

    r.status = Rental.Status.COMPLETED.value  # => "完了"
    r.completed_date = timezone.now()
    r.save(update_fields=["status", "completed_date"])
    messages.success(request, "レンタルを完了にしました。取引履歴に表示されます。")
    return redirect("frontend:profile")


@login_required
def purchase_receive_done(request, purchase_id):
    p = get_object_or_404(Purchase, id=purchase_id)
    if p.buyer != request.user:
        return redirect("frontend:error_403")

    p.status = Purchase.Status.COMPLETED.value  # => "完了"
    p.completed_date = timezone.now()
    p.save(update_fields=["status", "completed_date"])
    _close_active_rental_for_purchase(p)
    messages.success(request, "受取完了にしました。取引履歴に表示されます。")
    return redirect("frontend:profile")


# ========= 返品管理 =========

@login_required
def returns_index(request):
    tab = request.GET.get("tab", "mine")

    mine_qs = (Purchase.objects
               .select_related("product", "buyer", "product__owner")
               .filter(buyer=request.user, hidden_by_buyer=False))

    mine = _prepare_purchase_items(
        mine_qs.filter(
        Q(status__in=[getattr(Purchase.Status, "COMPLETED", "COMPLETED"), "完了"])
        | Q(return_status__in=["REQUESTED", "APPROVED", "SHIPPED", "RECEIVED", "REJECTED"])
        ).order_by("-id")
    )

    received = _prepare_purchase_items(
        Purchase.objects
        .select_related("product", "buyer", "product__owner")
        .filter(product__owner=request.user,
                hidden_by_seller=False,
                return_status__in=["REQUESTED", "APPROVED", "SHIPPED"])
        .order_by("-id")
    )

    return render(request, "frontend/returns/index.html", {
        "active_tab": "received" if tab == "received" else "mine",
        "mine": mine, "received": received,
    })


@login_required
def return_action(request):
    if request.method != "POST":
        return redirect("frontend:returns")

    pid = request.POST.get("purchase_id")
    action = request.POST.get("action")
    tracking = (request.POST.get("tracking_number") or "").strip()
    reason = (request.POST.get("reason") or "").strip()

    purchase = get_object_or_404(
        Purchase.objects.select_related("product", "buyer", "product__owner"), id=pid
    )

    from django.contrib import messages
    try:
        if action == "request_return":
            if purchase.buyer_id != request.user.id:
                raise ValueError("返品申請は購入者のみ可。")
            if purchase.status not in [getattr(Purchase.Status, "COMPLETED", "COMPLETED"), "完了"]:
                raise ValueError("取引完了後のみ申請可。")

            purchase.return_status = "REQUESTED"
            purchase.return_reason = reason[:255]
            purchase.return_requested_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_reason", "return_requested_at"])

            _create_notification(purchase.product.owner,
                "返品申請が届きました",
                f"「{purchase.product_title or purchase.product.title}」の返品が申請されました。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品を申請しました。承諾待ちです。")

        elif action == "approve_return":
            if purchase.product.owner_id != request.user.id:
                raise ValueError("承諾は出品者のみ可。")
            if purchase.return_status != "REQUESTED":
                raise ValueError("申請中のみ承諾可。")

            purchase.return_status = "APPROVED"
            purchase.return_approved_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_approved_at"])

            _create_notification(purchase.buyer,
                "返品が承諾されました",
                "返送の準備ができました。追跡番号を入力してください。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品を承諾しました。")

        elif action == "reject_return":
            if purchase.product.owner_id != request.user.id:
                raise ValueError("却下は出品者のみ可。")
            if purchase.return_status != "REQUESTED":
                raise ValueError("申請中のみ却下可。")

            purchase.return_status = "REJECTED"
            purchase.save(update_fields=["return_status"])

            _create_notification(purchase.buyer,
                "返品申請が却下されました",
                "返品申請は却下されました。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品申請を却下しました。")

        elif action == "ship_back":
            if purchase.buyer_id != request.user.id:
                raise ValueError("返送登録は購入者のみ可。")
            if purchase.return_status != "APPROVED":
                raise ValueError("承諾後にのみ返送可。")
            if not tracking:
                raise ValueError("返送の追跡番号を入力してください。")

            purchase.return_status = "SHIPPED"
            purchase.return_tracking_number = tracking
            purchase.return_shipped_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_tracking_number", "return_shipped_at"])

            _create_notification(purchase.product.owner,
                "返品が返送されました",
                f"追跡番号: {tracking}",
                purchase.id, "frontend:returns", kind="purchase")

            # ▼ 返送（購入者→出品者）の配送レコードを作成/更新
            buyer_p  = Profile.objects.filter(user=purchase.buyer).first()
            seller_p = Profile.objects.filter(user=purchase.product.owner).first()

            from_name  = (getattr(buyer_p, "display_name", "") or purchase.buyer.username)[:120]
            from_phone = (getattr(buyer_p, "phone", "") or "")[:40]
            from_addr  = (getattr(buyer_p, "address", "") or getattr(purchase, "shipping_address", "") or "")[:255]

            to_name    = (getattr(seller_p, "display_name", "") or purchase.product.owner.username)[:120]
            to_phone   = (getattr(seller_p, "phone", "") or "")[:40]
            to_addr    = (getattr(seller_p, "address", "") or "")[:255]

            Shipment.objects.update_or_create(
                purchase=purchase,
                direction=getattr(Shipment.Direction, "INBOUND", "inbound"),  # 返品の受領側ルート
                defaults={
                    "kind": getattr(Shipment.Kind, "PURCHASE", "purchase"),
                    "product": purchase.product,
                    "from_name": from_name,
                    "from_phone": from_phone,
                    "from_address": from_addr,
                    "to_name": to_name,
                    "to_phone": to_phone,
                    "to_address": to_addr,
                    "tracking_no": tracking,
                    "status": getattr(Shipment.Status, "IN_TRANSIT", "in_transit"),
                    "is_platform_intermediated": True,
                }
            )


            messages.success(request, "返送情報を登録しました。")

        elif action == "receive_back":
            if purchase.product.owner_id != request.user.id:
                raise ValueError("受領登録は出品者のみ可。")
            if purchase.return_status != "SHIPPED":
                raise ValueError("返送済みのみ受領可。")

            purchase.return_status = "RECEIVED"
            purchase.return_received_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_received_at"])

            _create_notification(purchase.buyer,
                "返品の受領が完了しました",
                "返品の受領が完了しました。",
                purchase.id, "frontend:returns", kind="purchase")

            # ▼ 返送配送を配達完了へ
            Shipment.objects.filter(
                purchase=purchase,
                direction=getattr(Shipment.Direction, "INBOUND", "inbound"),
            ).update(status=getattr(Shipment.Status, "DELIVERED", "delivered"))

            messages.success(request, "返品を受領済みにしました。")

        else:
            raise ValueError("不明なアクション。")

    except Exception as e:
        messages.error(request, f"処理に失敗しました: {e}")

    return redirect("frontend:returns")

def _create_shipment_for_application(app, direction, tracking_no="", status=None):
    if status is None:
        status = Shipment.Status.IN_TRANSIT
    # 往路: 出品者→借り手 / 返送: 借り手→出品者
    if direction == Shipment.Direction.OUTBOUND:
        frm = _contact_snapshot(app.owner)
        to  = _contact_snapshot(app.renter, fallback_address=getattr(app, "address", ""))
    else:
        frm = _contact_snapshot(app.renter, fallback_address=getattr(app, "address", ""))
        to  = _contact_snapshot(app.owner)

    Shipment.objects.update_or_create(
        application=app,
        direction=direction,
        defaults={
            "kind": Shipment.Kind.RENTAL,
            "product": app.product,
            "rental": None,          # 今回はRentalモデルじゃなく申請側で運用
            "purchase": None,
            "from_name": frm["name"],
            "from_phone": frm["phone"],
            "from_postal": frm["postal"],
            "from_address": frm["address"],
            "to_name": to["name"],
            "to_phone": to["phone"],
            "to_postal": to["postal"],
            "to_address": to["address"],
            "tracking_no": tracking_no or "",
            "status": status,
            "is_platform_intermediated": True,
        }
    )

def rental_app_ship(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, owner=request.user)
    from django.contrib import messages

    if app.status != RentalApplication.Status.APPROVED:
        messages.error(request, "承認済みの申請のみ配送できます。")
        return redirect("frontend:rental_manage")

    tracking = (request.POST.get("tracking_number") or "").strip()
    if not tracking:
        messages.error(request, "追跡番号を入力してください。")
        return redirect("frontend:rental_manage")

    app.tracking_number = tracking
    app.status = RentalApplication.Status.SHIPPED
    app.save()

    # ★ ここ追加：配送管理へ出す
    _create_shipment_for_application(app, Shipment.Direction.OUTBOUND, tracking)

    messages.success(request, "商品を配送しました。相手の受取をお待ちください。")
    return redirect("frontend:rental_manage")

def rental_app_return_ship(request, app_id):
    app = get_object_or_404(RentalApplication, id=app_id, renter=request.user)
    from django.contrib import messages

    tracking = (request.POST.get("return_tracking_number")
                or request.POST.get("tracking_number") or "").strip()
    if not tracking:
        messages.error(request, "返却の追跡番号を入力してください。")
        return redirect("frontend:my_applications")

    app.return_tracking_number = tracking
    app.message = _strip_return_tracking_line(getattr(app, "message", ""))

    app.status = RentalApplication.Status.RETURN_SHIPPED
    if hasattr(app, "shipped_date_return"):
        app.shipped_date_return = timezone.now()
    app.save()

    # ★ ここ追加：返送を配送管理へ出す
    _create_shipment_for_application(app, Shipment.Direction.RETURN, tracking)

    messages.success(request, "返却を発送しました。出品者の受領をお待ちください。")
    return redirect("frontend:my_applications")


# ========= 購入/レンタル — 申し込み =========

@login_required
def rental_apply(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if getattr(product, "owner_id", None) == request.user.id:
        from django.contrib import messages
        messages.error(request, "自分が出品した商品には申請できません。")
        return redirect("frontend:product_detail", pk=pk)

    order_type = (request.POST.get("order_type") or "").strip()
    quantity = int(request.POST.get("quantity") or 1)

    postal_code = (request.POST.get("postal_code") or "").strip()
    address = (request.POST.get("address") or "").strip()
    payment_method = (request.POST.get("payment_method") or "").strip()
    message_txt = (request.POST.get("message") or "").strip()

    start_date = request.POST.get("start_date") or None
    end_date   = request.POST.get("end_date") or None

    t = getattr(product, "availability_type", "レンタル・販売両方")
    allow_rental   = t in ("レンタル・販売両方", "レンタルのみ")
    allow_purchase = t in ("レンタル・販売両方", "販売のみ")

    errors = []
    if quantity < 1:
        errors.append("個数は1以上にしてください。")
    if not payment_method:
        errors.append("決済方法を選択してください。")
    if order_type not in ("rental", "purchase"):
        errors.append("不正な注文種別です。ページを更新してやり直してください。")

    from django.contrib import messages
    if order_type == "purchase":
        if not allow_purchase:
            messages.error(request, "この商品は購入できません。")
            return redirect("frontend:product_detail", pk=pk)

        if errors:
            for e in errors: messages.error(request, e)
            return redirect("frontend:product_detail", pk=pk)

        available_qty = _available_quantity_for(product)
        if quantity > available_qty:
            messages.error(request, "在庫が不足しています。")
            return redirect("frontend:product_detail", pk=pk)

        try:
            initial_status = Purchase.Status.PENDING
        except Exception:
            initial_status = getattr(Purchase.Status, "REQUESTED", "REQUESTED")

        create_kwargs = dict(
            product=product,
            buyer=request.user,
            quantity=quantity,
            status=initial_status,
        )
        if hasattr(Purchase, "product_title"):
            create_kwargs["product_title"] = getattr(product, "title", "")
        if hasattr(Purchase, "buyer_email"):
            create_kwargs["buyer_email"] = getattr(request.user, "email", "")
        if hasattr(Purchase, "seller_email"):
            create_kwargs["seller_email"] = getattr(product.owner, "email", "") if getattr(product, "owner", None) else ""
        if hasattr(Purchase, "shipping_address"):
            create_kwargs["shipping_address"] = address if not postal_code else f"{address}（〒{postal_code}）"
        if hasattr(Purchase, "payment_method"):
            create_kwargs["payment_method"] = payment_method
        if hasattr(Purchase, "message"):
            create_kwargs["message"] = message_txt

        with transaction.atomic():
            _adjust_available_quantity(product, -(quantity or 0))
            purchase = Purchase.objects.create(**create_kwargs)
        try:
            _create_notification(
                product.owner,
                "購入申請が届きました",
                f"「{getattr(product, 'title', '商品')}」の購入申請が届きました。",
                getattr(purchase, "id", None),
                "frontend:purchases",
                kind="purchase",
            )
        except Exception:
            pass
        messages.success(request, "購入申請を送信しました。")
        return redirect("frontend:purchases")

    if order_type == "rental":
        if not allow_rental:
            messages.error(request, "この商品はレンタルできません。")
            return redirect("frontend:product_detail", pk=pk)

        sd = parse_date(start_date) if start_date else None
        ed = parse_date(end_date) if end_date else None
        if not sd or not ed:
            errors.append("レンタル開始日・終了日を入力してください。")
        elif sd > ed:
            errors.append("レンタル終了日は開始日以降を選択してください。")

        if errors:
            for e in errors: messages.error(request, e)
            return redirect("frontend:product_detail", pk=pk)

        available_qty = _available_quantity_for(product)
        if quantity > available_qty:
            messages.error(request, "在庫が不足しています。")
            return redirect("frontend:product_detail", pk=pk)

        with transaction.atomic():
            _adjust_available_quantity(product, -(quantity or 0))
            app = RentalApplication.objects.create(
                product=product,
                owner=product.owner,
                renter=request.user,
                order_type=order_type,
                quantity=quantity,
                start_date=sd,
                end_date=ed,
                postal_code=postal_code,
                address=address,
                payment_method=payment_method,
                message=message_txt,
            )
        try:
            _create_notification(
                product.owner,
                "レンタル申請が届きました",
                f"「{getattr(product, 'title', '商品')}」のレンタル申請が届きました。",
                getattr(app, "id", None),
                "frontend:rental_manage",
                kind="rental",
            )
        except Exception:
            pass
        messages.success(request, "申請を送信しました。オーナーの承認をお待ちください。")
        return redirect("frontend:product_detail", pk=pk)

    messages.error(request, "不正なリクエストです。")
    return redirect("frontend:product_detail", pk=pk)


# ========= 商品 CRUD =========

@login_required
def product_create(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"is_admin": False}
    )

    from django.contrib import messages
    if not profile.address:
        messages.warning(request, "商品を投稿するには、まずプロフィールで住所を登録してください。")
        return redirect("frontend:profile")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        category = request.POST.get("category", "").strip()
        availability_type = request.POST.get("availability_type", "レンタル・販売両方")
        condition = request.POST.get("condition", "").strip()
        stock_quantity = request.POST.get("stock_quantity", "1")

        daily_price = request.POST.get("daily_price", "").strip()
        sale_price = request.POST.get("sale_price", "").strip()
        min_rental_days = request.POST.get("min_rental_days", "1")
        max_rental_days = request.POST.get("max_rental_days", "30")
        owner_notes = request.POST.get("owner_notes", "").strip()

        image_main = request.FILES.get("image_main")
        image_sub1 = request.FILES.get("image_sub1")
        image_sub2 = request.FILES.get("image_sub2")
        image_sub3 = request.FILES.get("image_sub3")

        errors = []
        missing_images = []
        if not image_main:
            missing_images.append("メイン画像")
        if not image_sub1:
            missing_images.append("サブ画像1")
        if not image_sub2:
            missing_images.append("サブ画像2")
        if not image_sub3:
            missing_images.append("サブ画像3")
        if missing_images:
            errors.append("画像は4枚すべて必須です。({})をアップロードしてください。".format(" / ".join(missing_images)))
        if not title:
            errors.append("商品名を入力してください。")
        if not description:
            errors.append("商品説明を入力してください。")
        if not category:
            errors.append("カテゴリーを選択してください。")
        if not condition:
            errors.append("商品の状態を選択してください。")

        if availability_type != "販売のみ" and not daily_price:
            errors.append("レンタルのみ、または両方の場合はレンタル料金を入力してください。")
        if availability_type != "レンタルのみ" and not sale_price:
            errors.append("販売のみ、または両方の場合は販売価格を入力してください。")

        if errors:
            for msg in errors:
                messages.error(request, msg)
            form_data = {
                "title": title, "description": description, "category": category,
                "availability_type": availability_type, "condition": condition,
                "stock_quantity": stock_quantity, "daily_price": daily_price,
                "sale_price": sale_price, "min_rental_days": min_rental_days,
                "max_rental_days": max_rental_days, "owner_notes": owner_notes,
            }
            return render(request, "frontend/products/form.html", {"form_data": form_data, "is_edit": False})

        try:
            daily_price_val = int(daily_price) if daily_price else None
            sale_price_val = int(sale_price) if sale_price else None
            min_rental_days_val = int(min_rental_days or 1)
            max_rental_days_val = int(max_rental_days or 30)
            stock_quantity_val = int(stock_quantity or 1)
        except ValueError:
            messages.error(request, "数値項目に不正な値があります。")
            form_data = {
                "title": title, "description": description, "category": category,
                "availability_type": availability_type, "condition": condition,
                "stock_quantity": stock_quantity, "daily_price": daily_price,
                "sale_price": sale_price, "min_rental_days": min_rental_days,
                "max_rental_days": max_rental_days, "owner_notes": owner_notes,
            }
            return render(request, "frontend/products/form.html", {"form_data": form_data, "is_edit": False})

        product = Product(
            owner=user,
            title=title,
            description=description,
            category=category,
            availability_type=availability_type,
            price_per_day=daily_price_val if availability_type != "販売のみ" else None,
            price_buy=sale_price_val if availability_type != "レンタルのみ" else None,
            min_rental_days=min_rental_days_val,
            max_rental_days=max_rental_days_val,
            stock_quantity=stock_quantity_val,
            available_quantity=stock_quantity_val,
            condition=condition,
            owner_notes=owner_notes,
            status=Product.Status.LISTED,
        )
        product.save()

        if image_main:
            ProductImage.objects.create(product=product, image=image_main)
        for img in [image_sub1, image_sub2, image_sub3]:
            if img:
                ProductImage.objects.create(product=product, image=img)

        messages.success(request, "商品を投稿しました。")
        return redirect("frontend:product_detail", pk=product.pk)

    form_data = {
        "availability_type": "レンタル・販売両方",
        "min_rental_days": 1,
        "max_rental_days": 30,
        "stock_quantity": 1,
    }
    return render(request, "frontend/products/form.html", {"form_data": form_data, "is_edit": False})


@login_required
def product_edit(request, pk: int):
    product = get_object_or_404(Product.objects.select_related("owner"), pk=pk)
    if product.owner_id != request.user.id:
        return HttpResponseForbidden("権限がありません。")

    from django.contrib import messages
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        category = request.POST.get("category", "").strip()
        availability_type = request.POST.get("availability_type", "レンタル・販売両方")
        condition = request.POST.get("condition", "").strip()
        stock_quantity = request.POST.get("stock_quantity", "1")

        daily_price = request.POST.get("daily_price", "").strip()
        sale_price = request.POST.get("sale_price", "").strip()
        min_rental_days = request.POST.get("min_rental_days", "1")
        max_rental_days = request.POST.get("max_rental_days", "30")
        owner_notes = request.POST.get("owner_notes", "").strip()

        image_main = request.FILES.get("image_main")
        image_sub1 = request.FILES.get("image_sub1")
        image_sub2 = request.FILES.get("image_sub2")
        image_sub3 = request.FILES.get("image_sub3")

        errors = []
        if not title:
            errors.append("商品名を入力してください。")
        if not description:
            errors.append("商品説明を入力してください。")
        if not category:
            errors.append("カテゴリーを選択してください。")
        if not condition:
            errors.append("商品の状態を選択してください。")
        if availability_type != "販売のみ" and not daily_price and product.price_per_day is None:
            errors.append("レンタル料金を入力してください。")
        if availability_type != "レンタルのみ" and not sale_price and product.price_buy is None:
            errors.append("販売価格を入力してください。")

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            try:
                product.title = title
                product.description = description
                product.category = category
                product.availability_type = availability_type
                product.condition = condition
                product.stock_quantity = int(stock_quantity or 1)
                product.min_rental_days = int(min_rental_days or 1)
                product.max_rental_days = int(max_rental_days or 30)

                if availability_type != "販売のみ":
                    if daily_price:
                        product.price_per_day = int(daily_price)
                else:
                    product.price_per_day = None

                if availability_type != "レンタルのみ":
                    if sale_price:
                        product.price_buy = int(sale_price)
                else:
                    product.price_buy = None

                product.owner_notes = owner_notes

                product.save()

                for img in [image_main, image_sub1, image_sub2, image_sub3]:
                    if img:
                        ProductImage.objects.create(product=product, image=img)

                messages.success(request, "保存しました。")
                return redirect("frontend:profile")
            except ValueError:
                messages.error(request, "数値項目に不正な値があります。")

    form_data = {
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "availability_type": product.availability_type or "レンタル・販売両方",
        "condition": product.condition,
        "stock_quantity": product.stock_quantity,
        "daily_price": product.price_per_day,
        "sale_price": product.price_buy,
        "min_rental_days": product.min_rental_days or 1,
        "max_rental_days": product.max_rental_days or 30,
        "owner_notes": product.owner_notes,
    }
    return render(request, "frontend/products/form.html", {"form_data": form_data, "is_edit": True})


@login_required
def product_delete_api(request, pk: int):
    """出品者自身による削除（AJAX想定, POSTのみ）"""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    product = get_object_or_404(Product, pk=pk)
    if product.owner_id != request.user.id:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    product.delete()
    return JsonResponse({"ok": True})


@login_required
def my_products(request):
    items = Product.objects.filter(owner=request.user).order_by("-id")
    return render(request, "frontend/products/my_products.html", {"products": items})


# ========= プロフィール / 取引履歴 =========

@login_required
def profile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"is_admin": False})

    active_tab = request.GET.get("tab", "info")
    editing = request.GET.get("edit") == "1"

    if request.method == "POST":
        profile.display_name = (request.POST.get("display_name") or "").strip()
        profile.phone        = (request.POST.get("phone") or "").strip()
        profile.address      = (request.POST.get("address") or "").strip()
        if "profile_image" in request.FILES:
            profile.profile_image = request.FILES["profile_image"]
        profile.save()
        from django.contrib import messages
        messages.success(request, "プロフィールを更新しました。")
        return redirect(f"{reverse('frontend:profile')}?tab=info")

    my_products = []
    favorites = []
    renting_products = []
    transactions = []
    if active_tab == "posts":
        my_products = Product.objects.filter(owner=user).order_by("-id")
    elif active_tab == "favorites":
        favorites = (ProductFavorite.objects
                    .filter(user=user)
                    .select_related("product")
                    .order_by("-created_at"))
    
    elif active_tab == "rentals":
        renting_items = []
        app_qs = (
            RentalApplication.objects
            .filter(order_type=RentalApplication.OrderType.RENTAL)
            .filter(status__iexact="renting")
            .filter(renter=user)
            .select_related("product", "product__owner")
            .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        )
        rental_qs = (
            Rental.objects
            .filter(status=Rental.Status.RENTING.value)
            .filter(renter=user)
            .select_related("product", "product__owner")
            .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        )
        for app in app_qs:
            if app.product:
                renting_items.append({
                    "product": app.product,
                    "start_date": app.start_date,
                    "end_date": app.end_date,
                    "quantity": app.quantity or 1,
                    "started_at": app.created_at,
                    "application_id": app.id,
                })
        for r in rental_qs:
            if r.product:
                renting_items.append({
                    "product": r.product,
                    "start_date": r.start_date,
                    "end_date": r.end_date,
                    "quantity": r.quantity or 1,
                    "started_at": r.rental_start_date or r.received_date_by_renter or r.created_at,
                    "rental_id": r.id,
                })
        renting_items.sort(
            key=lambda x: x["started_at"] or timezone.now(),
            reverse=True,
        )
        renting_products = renting_items
    elif active_tab == "history":
        # ▼ ここが肝。完了したレンタル/購入を混在で集約
        rentals = (
            Rental.objects
            .filter(status=Rental.Status.COMPLETED.value)  # "完了"
            .filter(Q(renter=user) | Q(product__owner=user))
            .select_related("product", "product__owner")
            .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        )
        purchases = (
            Purchase.objects
            .filter(status=Purchase.Status.COMPLETED.value)  # "完了"
            .filter(Q(buyer=user) | Q(product__owner=user))
            .select_related("product", "product__owner")
            .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        )
        rental_apps = (
            RentalApplication.objects
            .filter(order_type=RentalApplication.OrderType.RENTAL)
            .filter(status=RentalApplication.Status.COMPLETED)
            .filter(Q(renter=user) | Q(owner=user))
            .select_related("product", "product__owner")
            .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        )

        items = []
        for r in rentals:
            if r.product:
                items.append({
                    "kind": "rental",
                    "completed_at": r.completed_date or r.returned_date or r.created_at,
                    "product": r.product,
                })
        for app in rental_apps:
            if app.product:
                items.append({
                    "kind": "rental",
                    "completed_at": getattr(app, "completed_date", None) or app.created_at,
                    "product": app.product,
                })
        for p in purchases:
            if p.product:
                items.append({
                    "kind": "purchase",
                    "completed_at": p.completed_date or p.shipped_at or p.created_at,
                    "product": p.product,
                })

        items.sort(key=lambda x: x["completed_at"] or timezone.now(), reverse=True)
        transactions = items

    ctx = {
        "user_obj": user,
        "profile": profile,
        "active_tab": active_tab,
        "editing": editing,
        "my_products": my_products,
        "favorites": favorites,
        "renting_products": renting_products,
        "transactions": transactions,
    }
    return render(request, "frontend/profile/index.html", ctx)


@login_required
def profile_history(request):
    user = request.user

    rentals = (
        Rental.objects
        .filter(status=Rental.Status.COMPLETED.value) 
        .filter(Q(renter=user) | Q(product__owner=user))
        .select_related("product", "product__owner")
        .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
        
    )

    purchases = (
        Purchase.objects
        .filter(status=Purchase.Status.COMPLETED.value) 
        .filter(Q(buyer=user) | Q(product__owner=user))
        .select_related("product", "product__owner")
        .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("id")))
    )

    items = []
    for r in rentals:
        if r.product:  
            items.append({
                "kind": "rental",
                "completed_at": r.completed_date or r.returned_date or r.created_at,
                "product": r.product,
            })
    for p in purchases:
        if p.product:
            items.append({
                "kind": "purchase",
                "completed_at": p.completed_date or p.shipped_at or p.created_at,
                "product": p.product,
            })

    items.sort(key=lambda x: x["completed_at"] or timezone.now(), reverse=True)

    return render(request, "frontend/profile/history.html", {
        "transactions": items,
    })


# ========= 会員登録 =========

def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("frontend:products")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})


# ========= お問い合わせ =========

def company_page(request):
    return render(request, "frontend/company.html")


@csrf_exempt
def contact_page(request):
    return render(request, "contact/contact.html")


def contact_api(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if request.POST.get("website"):
        return JsonResponse({"ok": True})

    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    message = (request.POST.get("message") or "").strip()

    errors = []
    if not name: errors.append("お名前を入力してください")
    if not _is_valid_email(email): errors.append("正しいメールアドレスを入力してください")
    if len(message) < 10: errors.append("内容は10文字以上で入力してください")

    f = request.FILES.get("attachment")
    if f:
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            errors.append(f"添付は最大 {MAX_UPLOAD_MB}MB までです")
        if f.content_type not in ALLOWED_CONTENT_TYPES:
            errors.append("許可されていないファイル形式です")

    if errors:
        return HttpResponseBadRequest("\n".join(errors))

    inquiry = ContactInquiry.objects.create(
        name=name,
        company=(request.POST.get("company") or "").strip(),
        email=email,
        phone=(request.POST.get("phone") or "").strip(),
        type=(request.POST.get("type") or "general"),
        subject=(request.POST.get("subject") or "").strip(),
        message=message,
        attachment=f if f else None,
        consent=bool(request.POST.get("consent")),
        website="",
        user=request.user if request.user.is_authenticated else None,
        status="open",
    )

    # ここでメール送信等（省略）
    return JsonResponse({"ok": True})


# ========= 通知 =========

@login_required
def my_notifications(request):
    items = []
    unread_ids = []
    if Notification is None:
        return render(request, "frontend/my_notifications.html", {
            "object_list": items,
            "unread_ids": set(),
        })
    try:
        items = list(
            Notification.objects
            .filter(user=request.user)
            .order_by("-created_at")
        )
        unread_ids = [n.id for n in items if getattr(n, "read_at", None) is None]
        if unread_ids:
            Notification.objects.filter(id__in=unread_ids).update(read_at=timezone.now())
    except Exception:
        items = []
        unread_ids = []
    return render(request, "frontend/my_notifications.html", {
        "object_list": items,
        "unread_ids": set(unread_ids),
    })


# ========= 管理系 =========

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "frontend:login"
    raise_exception = True
    def test_func(self):
        return self.request.user.is_staff


class AdminShippingView(AdminRequiredMixin, TemplateView):
    template_name = "frontend/admin/shipping.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip().lower()
        shipments = (Shipment.objects
            .select_related(
                "product",
                "product__owner",
                "rental",
                "rental__renter",
                "purchase",
                "purchase__buyer",
                "application",
                "application__owner",
                "application__renter",
            )
            .order_by("-created_at"))
        if q:
            shipments = shipments.filter(
                Q(product__title__icontains=q) |
                Q(tracking_no__icontains=q) |
                Q(from_name__icontains=q) | Q(to_name__icontains=q)
            )
        shipments = list(shipments)
        user_ids = set()
        for s in shipments:
            if s.rental_id and s.rental:
                if s.rental.renter_id:
                    user_ids.add(s.rental.renter_id)
                if s.product and s.product.owner_id:
                    user_ids.add(s.product.owner_id)
            if s.purchase_id and s.purchase:
                if s.purchase.buyer_id:
                    user_ids.add(s.purchase.buyer_id)
                if s.product and s.product.owner_id:
                    user_ids.add(s.product.owner_id)
            if s.application_id and s.application:
                if s.application.renter_id:
                    user_ids.add(s.application.renter_id)
                if s.application.owner_id:
                    user_ids.add(s.application.owner_id)
        profiles = {p.user_id: p for p in Profile.objects.filter(user_id__in=user_ids)}

        def _contact_for(user, fallback_address=""):
            if not user:
                return {"name": "", "address": fallback_address or "", "phone": ""}
            prof = profiles.get(user.id)
            name = (getattr(prof, "display_name", "") or getattr(user, "username", ""))[:120]
            phone = (getattr(prof, "phone", "") or "")[:40]
            addr = (fallback_address or getattr(prof, "address", "") or "")[:255]
            return {"name": name, "address": addr, "phone": phone}

        for s in shipments:
            is_purchase = str(getattr(s, "kind", "")) == getattr(Shipment.Kind, "PURCHASE", "purchase")
            s.seller_label = "出品者" if is_purchase else "貸し手"
            s.buyer_label = "購入者" if is_purchase else "借り手"

            seller_user = None
            buyer_user = None
            buyer_addr = ""
            if s.rental_id and s.rental:
                seller_user = getattr(s.product, "owner", None)
                buyer_user = s.rental.renter
                buyer_addr = getattr(s.rental, "shipping_address", "") or ""
            elif s.purchase_id and s.purchase:
                seller_user = getattr(s.product, "owner", None)
                buyer_user = s.purchase.buyer
                buyer_addr = getattr(s.purchase, "shipping_address", "") or ""
            elif s.application_id and s.application:
                seller_user = s.application.owner
                buyer_user = s.application.renter
                buyer_addr = getattr(s.application, "address", "") or ""

            seller = _contact_for(seller_user)
            buyer = _contact_for(buyer_user, fallback_address=buyer_addr)
            is_outbound = s.direction == getattr(Shipment.Direction, "OUTBOUND", "outbound")

            if not seller["name"]:
                seller["name"] = s.from_name if is_outbound else s.to_name
            if not seller["address"]:
                seller["address"] = s.from_address if is_outbound else s.to_address
            if not buyer["name"]:
                buyer["name"] = s.to_name if is_outbound else s.from_name
            if not buyer["address"]:
                buyer["address"] = s.to_address if is_outbound else s.from_address

            s.seller_name = seller["name"]
            s.seller_address = seller["address"]
            s.buyer_name = buyer["name"]
            s.buyer_address = buyer["address"]

        ctx["shipments"] = shipments
        return ctx


from marketplace.models import Shipment
from accounts.models import Profile

def _contact_snapshot(user, fallback_address=""):
    # 表示名/電話/住所を Profile 優先で固定値化
    prof = None
    try:
        prof = Profile.objects.get(user=user)
    except Profile.DoesNotExist:
        pass
    name  = getattr(prof, "display_name", "") or getattr(user, "username", "")
    phone = getattr(prof, "phone", "") or ""
    addr  = getattr(prof, "address", "") or ""
    return {
        "name":  name[:120],
        "phone": phone[:40],
        "postal": "",  # 必要なら住所から分離保存に拡張
        "address": (fallback_address or addr)[:255],
    }

def _create_shipment_for_rental(rental, direction, tracking_no=""):
    kind = Shipment.Kind.RENTAL
    if direction == Shipment.Direction.OUTBOUND:
        # 貸し手 → 借り手
        frm = _contact_snapshot(rental.product.owner)
        to  = _contact_snapshot(rental.renter, fallback_address=rental.shipping_address)
    else:
        # 借り手 → 貸し手（返却）
        frm = _contact_snapshot(rental.renter)
        to  = _contact_snapshot(rental.product.owner)
    Shipment.objects.update_or_create(
        rental=rental,
        direction=direction,
        defaults={
            "kind": kind,
            "product": rental.product,
            "from_name": frm["name"],
            "from_phone": frm["phone"],
            "from_postal": frm["postal"],
            "from_address": frm["address"],
            "to_name": to["name"],
            "to_phone": to["phone"],
            "to_postal": to["postal"],
            "to_address": to["address"],
            "tracking_no": tracking_no or "",
            "status": Shipment.Status.CREATED,
            "is_platform_intermediated": True,
        },
    )

def _create_shipment_for_purchase(purchase, direction, tracking_no=""):
    kind = Shipment.Kind.PURCHASE
    if direction == Shipment.Direction.OUTBOUND:
        # 出品者 → 買い手
        frm = _contact_snapshot(purchase.product.owner)
        # Purchase.shipping_address に郵便含んでるならそれを優先
        to_addr = getattr(purchase, "shipping_address", "") or ""
        to  = _contact_snapshot(purchase.buyer, fallback_address=to_addr)
    else:
        # 返品: 買い手 → 出品者
        frm = _contact_snapshot(purchase.buyer)
        to  = _contact_snapshot(purchase.product.owner)
    Shipment.objects.update_or_create(
        purchase=purchase,
        direction=direction,
        defaults={
            "kind": kind,
            "product": purchase.product,
            "from_name": frm["name"],
            "from_phone": frm["phone"],
            "from_postal": frm["postal"],
            "from_address": frm["address"],
            "to_name": to["name"],
            "to_phone": to["phone"],
            "to_postal": to["postal"],
            "to_address": to["address"],
            "tracking_no": tracking_no or "",
            "status": Shipment.Status.CREATED,
            "is_platform_intermediated": True,
        },
    )

@login_required
@require_POST
def shipping_update(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("forbidden")
    sid = request.POST.get("shipment_id")
    st  = request.POST.get("status")
    s = get_object_or_404(Shipment, id=sid)
    valid = {c[0] for c in Shipment.Status.choices}
    if st not in valid:
        return HttpResponseBadRequest("invalid status")
    s.status = st
    s.save(update_fields=["status", "updated_at"])
    messages.success(request, "配送ステータスを更新しました。")
    return redirect("frontend:admin_shipping")



# ========= エラー =========

def error_403(request, exception=None):
    return render(request, "403.html", status=403)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
