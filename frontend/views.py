from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import EmailMessage
from django.conf import settings
from .models import ContactInquiry
<<<<<<< HEAD
import re
 
=======
from django.db import transaction
import requests

>>>>>>> cb624c1 (変更要約)
from accounts.models import Profile
from marketplace.models import Product, ProductImage, RentalApplication, Rental, Purchase
 
# 通知アプリが無い環境でも落ちないように
try:
    from notifications.models import Notification
except Exception:
    Notification = None
 
 
# ========= 一覧・詳細など =========
 
CATEGORIES = [
    "電子機器","家具","スポーツ用品","楽器","車両",
    "アウトドア用品","ファッション","書籍・メディア","その他",
]


class ProductListView(ListView):
    model = Product
    template_name = "frontend/products/index.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        return Product.objects.filter(status=Product.Status.LISTED).order_by("-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = CATEGORIES
        return ctx
 
 
class ProductDetailView(DetailView):
    model = Product
    template_name = "frontend/products/detail.html"
    context_object_name = "product"
 
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.object
        # 画像
        ctx["images"] = p.images.all() if hasattr(p, "images") else ProductImage.objects.none()
 
        # ▼ オーナー判定
        user = self.request.user
        is_owner = user.is_authenticated and getattr(p, "owner_id", None) == user.id
        ctx["is_owner"] = is_owner
 
        # ▼ 提供方法（availability_type は日本語値）
        t = getattr(p, "availability_type", "レンタル・販売両方")
        allow_rental = t in ("レンタル・販売両方", "レンタルのみ")
        allow_purchase = t in ("レンタル・販売両方", "販売のみ")
        ctx["allow_rental"] = allow_rental
        ctx["allow_purchase"] = allow_purchase
 
        return ctx
 
 
class PurchaseListView(TemplateView):
    template_name = "frontend/purchases/index.html"
 
 
class ReturnListPage(TemplateView):
    template_name = "frontend/returns/index.html"
 
 
class MessagesPage(TemplateView):
    template_name = "frontend/messages/index.html"
 
 
class DocumentationView(TemplateView):
    template_name = "frontend/docs/index.html"
 
 
class AdminShippingView(TemplateView):
    template_name = "frontend/admin/shipping.html"
 
 
# ========= レンタル管理（ページ分割） =========
 
COMPLETED_STATUSES = ("完了", "キャンセル")
 
 
def _create_notification(
    recipient_email,
    title,
    message,
    related_id=None,
    action_url_name=None,   # URL名 or そのままのパス
    kind="rental",          # デフォルトは rental
    action_url_kwargs=None
):
    """Notification の実フィールドに合わせて安全に作成する。失敗しても全体は落とさない。"""
    if Notification is None:
        return

    # URL解決（名前でもパスでもOK）
    url = ""
    if action_url_name:
        try:
            url = reverse(action_url_name, kwargs=action_url_kwargs or {})
        except Exception:
            url = action_url_name

    try:
        # モデルが持つ実フィールド一覧
        try:
            field_names = {
                f.name for f in Notification._meta.get_fields()
                if getattr(f, "concrete", True)
            }
        except Exception:
            field_names = set()

        def pick(*candidates):
            """候補のうちモデルに存在する最初の名前を返す"""
            for c in candidates:
                if c in field_names:
                    return c
            return None

        data = {}

        k = pick("recipient_email", "email", "to_email")
        if k:
            data[k] = recipient_email or ""

        k = pick("title", "subject")
        if k:
            data[k] = (title or "")[:255]

        k = pick("message", "body", "content")
        if k:
            data[k] = message or ""

        k = pick("type", "kind", "category")
        if k:
            data[k] = kind

        k = pick("related_id", "object_id", "target_id")
        if k and related_id is not None:
            data[k] = related_id

        k = pick("action_url", "url", "link_url")
        if k and url:
            data[k] = url

        if data:
            Notification.objects.create(**data)

    except Exception:
        # 通知で例外が出ても画面は壊さない
        return

 
 
def _ensure_owner(user, rental: Rental):
    if rental.product.owner_id != user.id:
        raise ValueError("オーナー以外は実行できません。")
 
 
def _ensure_renter(user, rental: Rental):
    if rental.renter_id != user.id:
        raise ValueError("借り手以外は実行できません。")
 
 
def _handle_rental_action(request, user, redirect_name):
    """
    approve / ship / receive / return_ship / confirm_return / cancel を共通処理。
    処理後は redirect_name にリダイレクト。
    """
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
 
            # 在庫引当
            product = rental.product
            current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
            product.available_quantity = (current_available or 0) - (rental.quantity or 1)
            product.save(update_fields=["available_quantity"])
 
            _create_notification(
                rental.renter_email,
                "レンタル承認",
                f"「{rental.product_title}」のレンタルが承認されました。",
                rental.id,
                redirect_name,
                kind="rental",
            )
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
 
            _create_notification(
                rental.renter_email,
                "商品発送のお知らせ",
                f"「{rental.product_title}」が発送されました。到着したら「受取完了」を押してください。",
                rental.id,
                redirect_name,
                kind="rental",
            )
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
                rental.owner_email,
                "商品受け取り完了",
                f"「{rental.product_title}」が借り手に届き、レンタルが開始されました。",
                rental.id,
                redirect_name,
                kind="rental",
            )
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
 
            _create_notification(
                rental.owner_email,
                "商品返却発送のお知らせ",
                f"「{rental.product_title}」が返却のために発送されました。到着確認をしてください。",
                rental.id,
                redirect_name,
                kind="rental",
            )
            messages.success(request, "返却発送済みに更新しました。")
 
        elif action == "confirm_return":
            _ensure_owner(user, rental)
            if rental.status != "返却発送済み":
                raise ValueError("返却発送済みのみ完了にできます。")
 
            now = timezone.now()
            rental.status = "完了"
            rental.completed_date = now
            rental.save(update_fields=["status", "completed_date"])
 
            # 在庫戻し
            product = rental.product
            current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
            product.available_quantity = (current_available or 0) + (rental.quantity or 1)
            product.save(update_fields=["available_quantity"])
 
            for email in [rental.renter_email, rental.owner_email]:
                _create_notification(
                    email,
                    "レンタル完了",
                    f"「{rental.product_title}」のレンタルが完了しました。",
                    rental.id,
                    "frontend:profile",
                    kind="rental",
                )
 
            # 任意: 完了数を持っているなら +1
            if hasattr(user, "completed_rentals") and user.id in (rental.renter_id, rental.product.owner_id):
                user.completed_rentals = (user.completed_rentals or 0) + 1
                user.save(update_fields=["completed_rentals"])
 
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
 
            for email in [rental.renter_email, rental.owner_email]:
                _create_notification(
                    email,
                    "レンタルキャンセル",
                    f"「{rental.product_title}」のレンタルがキャンセルされました。",
                    rental.id,
                    redirect_name,
                    kind="rental",
                )
 
            messages.success(request, "レンタルをキャンセルしました。")
 
        else:
            raise ValueError("不明なアクションです。")
 
    except Exception as e:
        messages.error(request, f"処理に失敗しました: {e}")
 
    return redirect(redirect_name)
 
 
@login_required
def rentals_index(request):
    """購入管理と同じUIのレンタル管理タブ（?tab=mine / ?tab=received）"""
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
    """自分が借り手のレンタル一覧"""
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
    """自分の商品に届いたレンタル一覧"""
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
 
 

def _handle_purchase_action(request, redirect_name):
    user = request.user
    action = request.POST.get("action")
    pid = request.POST.get("purchase_id")
    tracking = (request.POST.get("tracking_number") or "").strip()

    purchase = get_object_or_404(
        Purchase.objects.select_related("product", "buyer", "product__owner"),
        id=pid,
    )

    # ステータス定数（モデルに未定義でも動くようフォールバック）
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
                # 出品者のみ、承認待ちのみ
                if purchase.product.owner_id != user.id:
                    raise ValueError("承認権限がありません。")
                if not is_pending_like:
                    raise ValueError("承認待ちのみ承認できます。")

                purchase.status = S_APPROVED
                if hasattr(purchase, "approved_at"):
                    purchase.approved_at = timezone.now()
                    purchase.save(update_fields=["status", "approved_at"])
                else:
                    purchase.save(update_fields=["status"])

                messages.success(request, "承認しました。追跡番号入力が有効になりました。")

            elif action == "ship":
                # 出品者のみ、承認済みのみ
                if purchase.product.owner_id != user.id:
                    raise ValueError("発送権限がありません。")
                if purchase.status != S_APPROVED:
                    raise ValueError("承認済みのみ配送できます。")
                if not tracking:
                    raise ValueError("追跡番号を入力してください。")

                # 追跡番号 + 在庫引当
                purchase.tracking_number = tracking
                purchase.status = S_SHIPPED
                update_fields = ["tracking_number", "status"]

                if hasattr(purchase, "shipped_at"):
                    purchase.shipped_at = timezone.now()
                    update_fields.append("shipped_at")

                # 在庫（available_quantity があれば減算）
                product = purchase.product
                if hasattr(product, "available_quantity"):
                    current = product.available_quantity if product.available_quantity is not None else getattr(product, "stock_quantity", 0)
                    product.available_quantity = max(0, (current or 0) - (purchase.quantity or 1))
                    product.save(update_fields=["available_quantity"])

                purchase.save(update_fields=update_fields)
                messages.success(request, "発送済みに更新しました。")

            elif action == "complete":
                # 購入者のみ、承認済み以降（APPROVED/SHIPPED）
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

                messages.success(request, "受取完了として更新しました。")

            elif action == "cancel":
                # 当事者のみ、承認待ちのみ
                if user.id not in (purchase.buyer_id, purchase.product.owner_id):
                    raise ValueError("キャンセル権限がありません。")
                if not is_pending_like:
                    raise ValueError("承認待ちのみキャンセルできます。")

                purchase.status = S_CANCELED
                purchase.save(update_fields=["status"])
                messages.success(request, "キャンセルしました。")

            else:
                raise ValueError("不明なアクションです。")

    except Exception as e:
        messages.error(request, f"処理に失敗しました: {e}")

    return redirect(redirect_name)


 
 
@login_required
def purchases_index(request):
    """
    ?tab=mine / ?tab=received で切り替えるタブ式トップ
    テンプレ: templates/frontend/purchases/index.html
    """
    tab = request.GET.get("tab", "mine")
 
    qs = (Purchase.objects
          .select_related("product", "buyer", "product__owner")
          .order_by("-id"))
 
    mine = qs.filter(buyer=request.user)
    received = qs.filter(product__owner=request.user)
 
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
    items = (Purchase.objects
             .select_related("product", "buyer", "product__owner")
             .filter(buyer=request.user)
             .order_by("-id"))
    return render(request, "frontend/purchases/my_purchases.html",
                  {"my_purchases": items, "items": items, "mode": "mine"})

@login_required
def received_purchases(request):
    if request.method == "POST":
        return _handle_purchase_action(request, redirect_name="frontend:received_purchases")
    items = (Purchase.objects
             .select_related("product", "buyer", "product__owner")
             .filter(product__owner=request.user)
             .order_by("-id"))
    return render(request, "frontend/purchases/received_purchases.html",
                  {"received_purchases": items, "items": items, "mode": "received"})
 
 
@login_required
def received_purchases(request):
    """
    テンプレ: templates/frontend/purchases/received_purchases.html
    POST アクションもここで受ける（発送など）
    """
    if request.method == "POST":
        return _handle_purchase_action(request, redirect_name="frontend:received_purchases")
 
    items = (Purchase.objects
             .select_related("product", "buyer", "product__owner")
             .filter(product__owner=request.user)
             .order_by("-id"))
 
    return render(request, "frontend/purchases/received_purchases.html", {"received_purchases": items})
 
 
# ========= 商品投稿 =========
 
@login_required
def product_create(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(
    user=request.user,
    defaults={"is_admin": False}
)
 
    # 住所必須チェック
    if not profile.address:
        messages.warning(request, "商品を投稿するには、まずプロフィールで住所を登録してください。")
        return redirect("frontend:profile")
 
    if request.method == "POST":
        # --- フォーム値の取得 ---
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
 
        # --- 必須チェック ---
        if not image_main:
            errors.append("メイン画像をアップロードしてください。")
        if not title:
            errors.append("商品名を入力してください。")
        if not description:
            errors.append("商品説明を入力してください。")
        if not category:
            errors.append("カテゴリーを選択してください。")
        if not condition:
            errors.append("商品の状態を選択してください。")
 
        # --- レンタル/販売の必須チェック ---
        if availability_type != "販売のみ" and not daily_price:
            errors.append("レンタルのみ、または両方の場合はレンタル料金を入力してください。")
        if availability_type != "レンタルのみ" and not sale_price:
            errors.append("販売のみ、または両方の場合は販売価格を入力してください。")
 
        if errors:
            for msg in errors:
                messages.error(request, msg)
 
            form_data = {
                "title": title,
                "description": description,
                "category": category,
                "availability_type": availability_type,
                "condition": condition,
                "stock_quantity": stock_quantity,
                "daily_price": daily_price,
                "sale_price": sale_price,
                "min_rental_days": min_rental_days,
                "max_rental_days": max_rental_days,
                "owner_notes": owner_notes,
            }
            return render(request, "frontend/products/form.html", {"form_data": form_data})
 
        # --- 数値変換 ---
        try:
            daily_price_val = int(daily_price) if daily_price else None
            sale_price_val = int(sale_price) if sale_price else None
            min_rental_days_val = int(min_rental_days or 1)
            max_rental_days_val = int(max_rental_days or 30)
            stock_quantity_val = int(stock_quantity or 1)
        except ValueError:
            messages.error(request, "数値項目に不正な値があります。")
            form_data = {
                "title": title,
                "description": description,
                "category": category,
                "availability_type": availability_type,
                "condition": condition,
                "stock_quantity": stock_quantity,
                "daily_price": daily_price,
                "sale_price": sale_price,
                "min_rental_days": min_rental_days,
                "max_rental_days": max_rental_days,
                "owner_notes": owner_notes,
            }
            return render(request, "frontend/products/form.html", {"form_data": form_data})
 
        # --- Product作成 ---
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
 
        # 画像の保存
        if image_main:
            ProductImage.objects.create(product=product, image=image_main)
        for img in [image_sub1, image_sub2, image_sub3]:
            if img:
                ProductImage.objects.create(product=product, image=img)
 
        messages.success(request, "商品を投稿しました。")
 
        # 投稿完了＝詳細へ
        return redirect("frontend:product_detail", pk=product.pk)
 
    # GET
    form_data = {
        "availability_type": "レンタル・販売両方",
        "min_rental_days": 1,
        "max_rental_days": 30,
        "stock_quantity": 1,
    }
    return render(request, "frontend/products/form.html", {"form_data": form_data})
 
@login_required
def product_create_done(request):
    return render(request, "frontend/products/create_done.html")
 
# ========= レンタル/購入 申請 & 管理 =========
 
@login_required
def rental_apply(request, pk):
<<<<<<< HEAD
    """右側フォームからの申請作成（レンタル/購入の分岐込み）"""
=======
    """商品詳細の右カラムから レンタル/購入 を申請する"""
>>>>>>> cb624c1 (変更要約)
    product = get_object_or_404(Product, pk=pk)

    # 自分の出品には申請不可
    if getattr(product, "owner_id", None) == request.user.id:
        messages.error(request, "自分が出品した商品には申請できません。")
        return redirect("frontend:product_detail", pk=pk)

<<<<<<< HEAD
    order_type = request.POST.get("order_type")  # 'rental' or 'purchase'
    quantity = int(request.POST.get("quantity") or 1)

    postal_code = request.POST.get("postal_code", "")
    address = request.POST.get("address", "")
    payment_method = request.POST.get("payment_method")
    message_txt = request.POST.get("message", "")
=======
    # 入力値
    order_type = (request.POST.get("order_type") or "").strip()  # 'rental' | 'purchase'
    quantity = int(request.POST.get("quantity") or 1)

    postal_code = (request.POST.get("postal_code") or "").strip()
    address = (request.POST.get("address") or "").strip()
    payment_method = (request.POST.get("payment_method") or "").strip()
    message_txt = (request.POST.get("message") or "").strip()
>>>>>>> cb624c1 (変更要約)

    start_date = request.POST.get("start_date") or None
    end_date   = request.POST.get("end_date") or None

    # 提供方法チェック
    t = getattr(product, "availability_type", "レンタル・販売両方")
    allow_rental   = t in ("レンタル・販売両方", "レンタルのみ")
    allow_purchase = t in ("レンタル・販売両方", "販売のみ")

    # 共通バリデーション
    errors = []
    if quantity < 1:
        errors.append("個数は1以上にしてください。")
    if not payment_method:
        errors.append("決済方法を選択してください。")

<<<<<<< HEAD
    # --- 購入申請 ---
=======
    # order_type 妥当性
    if order_type not in ("rental", "purchase"):
        errors.append("不正な注文種別です。ページを更新してやり直してください。")

    # ここで購入フロー
>>>>>>> cb624c1 (変更要約)
    if order_type == "purchase":
        if not allow_purchase:
            messages.error(request, "この商品は購入できません。")
            return redirect("frontend:product_detail", pk=pk)

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect("frontend:product_detail", pk=pk)

<<<<<<< HEAD
        # Purchase モデルに実在するフィールドだけ詰める
        fields = {f.name for f in Purchase._meta.get_fields()}
        kwargs = {
            "product": product,
            "buyer": request.user,
            "quantity": quantity,
        }

        Status = getattr(Purchase, "Status", None)
        requested_value = getattr(Status, "REQUESTED", None)
        if "status" in fields:
            kwargs["status"] = requested_value or "申請中"

        # 住所系の差異を吸収
        if "postal_code" in fields:
            kwargs["postal_code"] = postal_code
        elif "shipping_postal_code" in fields:
            kwargs["shipping_postal_code"] = postal_code

        if "address" in fields:
            kwargs["address"] = address
        elif "shipping_address" in fields:
            kwargs["shipping_address"] = address

        if "payment_method" in fields:
            kwargs["payment_method"] = payment_method
        if "message" in fields:
            kwargs["message"] = message_txt

        # 金額系（存在すれば）
        if getattr(product, "price_buy", None) is not None:
            if "unit_price" in fields:
                kwargs["unit_price"] = product.price_buy
            if "total_price" in fields:
                kwargs["total_price"] = (product.price_buy or 0) * quantity

        Purchase.objects.create(**kwargs)
        messages.success(request, "購入申請を送信しました。")
        return redirect("frontend:purchases")

    # --- レンタル申請 ---
=======
        # 初期ステータスはモデルに合わせて決定（PENDINGが無ければREQUESTED）
        try:
            initial_status = Purchase.Status.PENDING
        except Exception:
            initial_status = getattr(Purchase.Status, "REQUESTED", "REQUESTED")

        # 余計なフィールドは渡さない（存在確認してから詰める）
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
            # postal_code 専用カラムが無いなら住所に含める
            create_kwargs["shipping_address"] = address if not postal_code else f"{address}（〒{postal_code}）"
        if hasattr(Purchase, "payment_method"):
            create_kwargs["payment_method"] = payment_method
        if hasattr(Purchase, "message"):
            create_kwargs["message"] = message_txt

        Purchase.objects.create(**create_kwargs)
        messages.success(request, "購入申請を送信しました。")
        return redirect("frontend:purchases")

    # ここからレンタルフロー
>>>>>>> cb624c1 (変更要約)
    if order_type == "rental":
        if not allow_rental:
            messages.error(request, "この商品はレンタルできません。")
            return redirect("frontend:product_detail", pk=pk)

<<<<<<< HEAD
=======
        from django.utils.dateparse import parse_date
>>>>>>> cb624c1 (変更要約)
        sd = parse_date(start_date) if start_date else None
        ed = parse_date(end_date) if end_date else None
        if not sd or not ed:
            errors.append("レンタル開始日・終了日を入力してください。")
        elif sd > ed:
            errors.append("レンタル終了日は開始日以降を選択してください。")

        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect("frontend:product_detail", pk=pk)

        RentalApplication.objects.create(
            product=product,
<<<<<<< HEAD
            owner=product.owner,
            renter=request.user,
=======
            owner=product.owner,      # 受け取り側
            renter=request.user,      # 申請者
>>>>>>> cb624c1 (変更要約)
            order_type=order_type,
            quantity=quantity,
            start_date=sd,
            end_date=ed,
            postal_code=postal_code,
            address=address,
            payment_method=payment_method,
            message=message_txt,
        )
        messages.success(request, "申請を送信しました。オーナーの承認をお待ちください。")
        return redirect("frontend:product_detail", pk=pk)
<<<<<<< HEAD
=======

    # ここまでで return されていない場合の最終退避
    messages.error(request, "不正なリクエストです。")
    return redirect("frontend:product_detail", pk=pk)

>>>>>>> cb624c1 (変更要約)
 
 
@login_required
def rental_manage(request):
    """オーナーが受け取った申請一覧（簡易）"""
    apps = RentalApplication.objects.filter(owner=request.user).order_by("-id")
    return render(request, "frontend/rentals/manage.html", {"applications": apps})
 
 
@login_required
def my_products(request):
    """オーナーの投稿商品一覧"""
    items = Product.objects.filter(owner=request.user).order_by("-id")
    return render(request, "frontend/products/my_products.html", {"products": items})

# ========= 返品管理 =========
@login_required
def returns_index(request):
    tab = request.GET.get("tab", "mine")

    mine_qs = (Purchase.objects
               .select_related("product", "buyer", "product__owner")
               .filter(buyer=request.user))

    # 完了済みは常に返品候補として出す。進行中は当然含む。
    mine = mine_qs.filter(
        Q(status__in=[getattr(Purchase.Status, "COMPLETED", "COMPLETED"), "完了"])
        | Q(return_status__in=["REQUESTED", "APPROVED", "SHIPPED", "RECEIVED", "REJECTED"])
    ).order_by("-id")

    received = (Purchase.objects
                .select_related("product", "buyer", "product__owner")
                .filter(product__owner=request.user,
                        return_status__in=["REQUESTED", "APPROVED", "SHIPPED"])
                ).order_by("-id")

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

    try:
        if action == "request_return":
            # 購入者のみ、取引完了後のみ
            if purchase.buyer_id != request.user.id:
                raise ValueError("返品申請は購入者のみ可。")
            if purchase.status not in [getattr(Purchase.Status, "COMPLETED", "COMPLETED"), "完了"]:
                raise ValueError("取引完了後のみ申請可。")

            purchase.return_status = "REQUESTED"
            purchase.return_reason = reason[:255]
            purchase.return_requested_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_reason", "return_requested_at"])

            _create_notification(getattr(purchase.product.owner, "email", ""),
                "返品申請が届きました",
                f"「{purchase.product_title or purchase.product.title}」の返品が申請されました。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品を申請しました。承諾待ちです。")

        elif action == "approve_return":
            # 出品者のみ、申請中のみ
            if purchase.product.owner_id != request.user.id:
                raise ValueError("承諾は出品者のみ可。")
            if purchase.return_status != "REQUESTED":
                raise ValueError("申請中のみ承諾可。")

            purchase.return_status = "APPROVED"
            purchase.return_approved_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_approved_at"])

            _create_notification(getattr(purchase.buyer, "email", ""),
                "返品が承諾されました",
                "返送の準備ができました。追跡番号を入力してください。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品を承諾しました。")

        elif action == "reject_return":
            # 出品者のみ、申請中のみ
            if purchase.product.owner_id != request.user.id:
                raise ValueError("却下は出品者のみ可。")
            if purchase.return_status != "REQUESTED":
                raise ValueError("申請中のみ却下可。")

            purchase.return_status = "REJECTED"
            purchase.save(update_fields=["return_status"])

            _create_notification(getattr(purchase.buyer, "email", ""),
                "返品申請が却下されました",
                "返品申請は却下されました。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品申請を却下しました。")

        elif action == "ship_back":
            # 購入者のみ、APPROVED のときだけ追跡番号登録を解禁
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

            _create_notification(getattr(purchase.product.owner, "email", ""),
                "返品が返送されました",
                f"追跡番号: {tracking}",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返送情報を登録しました。")

        elif action == "receive_back":
            # 出品者のみ、SHIPPED を受領
            if purchase.product.owner_id != request.user.id:
                raise ValueError("受領登録は出品者のみ可。")
            if purchase.return_status != "SHIPPED":
                raise ValueError("返送済みのみ受領可。")

            purchase.return_status = "RECEIVED"
            purchase.return_received_at = timezone.now()
            purchase.save(update_fields=["return_status", "return_received_at"])

            _create_notification(getattr(purchase.buyer, "email", ""),
                "返品の受領が完了しました",
                "返品の受領が完了しました。",
                purchase.id, "frontend:returns", kind="purchase")

            messages.success(request, "返品を受領済みにしました。")

        else:
            raise ValueError("不明なアクション。")

    except Exception as e:
        messages.error(request, f"処理に失敗しました: {e}")

    return redirect("frontend:returns")
 
 
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
 
MAX_UPLOAD_MB = 5
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif",
    "application/pdf", "application/zip"
}
 
def _is_valid_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))
 
@csrf_exempt
def contact_page(request):
    # contact.html を表示する（GET）
    return render(request, "contact/contact.html")

def contact_api(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    
    # ハニーポット
    if request.POST.get("website"):
        return JsonResponse({"ok": True})

    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    message = (request.POST.get("message") or "").strip()

    # 必須チェック
    errors = []
    if not name:
        errors.append("お名前を入力してください")
    if not _is_valid_email(email):
        errors.append("正しいメールアドレスを入力してください")
    if len(message) < 10:
        errors.append("内容は10文字以上で入力してください")

    # 添付チェック
    f = request.FILES.get("attachment")
    if f:
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            errors.append(f"添付は最大 {MAX_UPLOAD_MB}MB までです")
        if f.content_type not in ALLOWED_CONTENT_TYPES:
            errors.append("許可されていないファイル形式です")

    if errors:
        return HttpResponseBadRequest("\n".join(errors))

    # 保存
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

    # メール送信（省略：あなたのコードそのまま）

    return JsonResponse({"ok": True})

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import render

# 追加: 管理者専用 Mixin
class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "frontend:login"
    raise_exception = True  # 権限なしは 403 にする

    def test_func(self):
        return self.request.user.is_staff  # ここを role に変えるなら差し替え

# 既存の管理ページビューを差し替え
class AdminShippingView(AdminRequiredMixin, TemplateView):
    template_name = "frontend/admin/shipping.html"

# 追加: 403 ハンドラ
def error_403(request, exception=None):
    return render(request, "403.html", status=403)
