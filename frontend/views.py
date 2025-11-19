from django.contrib.auth.decorators import login_required
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
import re
 
from accounts.models import Profile
from marketplace.models import Product, ProductImage, RentalApplication, Rental, Purchase
 
# 通知アプリが無い環境でも落ちないように
try:
    from notifications.models import Notification
except Exception:
    Notification = None
 
 
# ========= 一覧・詳細など =========
 
class ProductListView(ListView):
    model = Product
    template_name = "frontend/products/index.html"  # 商品一覧テンプレ
    context_object_name = "products"
    paginate_by = 20
 
    def get_queryset(self):
        # 出品中だけ
        return Product.objects.filter(
            status=Product.Status.LISTED
        ).order_by("-id")   # created_at 依存を避ける
 
 
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
    """通知作成。通知アプリが無い/URL名が存在しない場合でも落ちないようにする。"""
    if Notification is None:
        return
 
    url = ""
    if action_url_name:
        try:
            url = reverse(action_url_name, kwargs=action_url_kwargs or {})
        except Exception:
            # 既にパスが入っているか、URL名が未登録ならそのまま保存
            url = action_url_name
 
    Notification.objects.create(
        recipient_email=recipient_email or "",
        title=(title or "")[:255],
        message=message or "",
        type=kind,
        related_id=related_id,
        action_url=url,
    )
 
 
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
    """
    POST:
      - action: 'ship' | 'complete' | 'cancel'
      - purchase_id: int
      - tracking_number: str（ship のとき必須）
    """
    user = request.user
    action = request.POST.get("action")
    pid = request.POST.get("purchase_id")
    tracking = (request.POST.get("tracking_number") or "").strip()
 
    purchase = get_object_or_404(
        Purchase.objects.select_related("product", "buyer", "product__owner"),
        id=pid,
    )
 
    try:
        if action == "ship":
            # 出品者のみ、申請中のみ
            if purchase.product.owner_id != user.id:
                raise ValueError("発送権限がありません。")
            if purchase.status != Purchase.Status.REQUESTED:
                raise ValueError("申請中のみ発送できます。")
            if not tracking:
                raise ValueError("追跡番号を入力してください。")
 
            purchase.status = Purchase.Status.SHIPPED
            purchase.tracking_number = tracking
            purchase.save(update_fields=["status", "tracking_number"])
 
            # 在庫引き当て
            product = purchase.product
            current_available = product.available_quantity if product.available_quantity is not None else product.stock_quantity
            product.available_quantity = max(0, (current_available or 0) - (purchase.quantity or 1))
            product.save(update_fields=["available_quantity"])
 
            _create_notification(
                purchase.buyer_email,
                "商品発送済み",
                f"「{purchase.product_title}」が発送されました。到着後に受取完了を押してください。",
                purchase.id,
                redirect_name,
                kind="purchase",
            )
            messages.success(request, "発送済みに更新しました。")
 
        elif action == "complete":
            # 購入者のみ、発送済みのみ
            if purchase.buyer_id != user.id:
                raise ValueError("受取完了は購入者のみ可能です。")
            if purchase.status != Purchase.Status.SHIPPED:
                raise ValueError("発送済みのみ受取完了にできます。")
 
            purchase.status = Purchase.Status.COMPLETED
            purchase.completed_date = timezone.now()
            purchase.save(update_fields=["status", "completed_date"])
 
            # 双方に通知
            for email in [purchase.buyer_email, purchase.seller_email]:
                _create_notification(
                    email,
                    "購入完了",
                    f"「{purchase.product_title}」の購入が完了しました。",
                    purchase.id,
                    "frontend:profile",
                    kind="purchase",
                )
 
            messages.success(request, "受取完了として更新しました。")
 
        elif action == "cancel":
            # 出品者か購入者。申請中のみを想定（運用で調整）
            if user.id not in (purchase.buyer_id, purchase.product.owner_id):
                raise ValueError("キャンセル権限がありません。")
            if purchase.status != Purchase.Status.REQUESTED:
                raise ValueError("申請中のみキャンセルできます。")
 
            purchase.status = Purchase.Status.CANCELED
            purchase.save(update_fields=["status"])
 
            # 双方に通知
            for email in [purchase.buyer_email, purchase.seller_email]:
                _create_notification(
                    email,
                    "購入キャンセル",
                    f"「{purchase.product_title}」の購入がキャンセルされました。",
                    purchase.id,
                    redirect_name,
                    kind="purchase",
                )
 
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
    """
    テンプレ: templates/frontend/purchases/my_purchases.html
    POST アクションもここで受ける（受取完了など）
    """
    if request.method == "POST":
        return _handle_purchase_action(request, redirect_name="frontend:my_purchases")
 
    items = (Purchase.objects
             .select_related("product", "buyer", "product__owner")
             .filter(buyer=request.user)
             .order_by("-id"))
 
    return render(request, "frontend/purchases/my_purchases.html", {"my_purchases": items})
 
 
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
    profile, _ = Profile.objects.get_or_create(user=user)
 
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
    """右側フォームからの申請作成"""
    product = get_object_or_404(Product, pk=pk)
 
    # 自分の出品には申請不可
    if getattr(product, "owner_id", None) == request.user.id:
        messages.error(request, "自分が出品した商品には申請できません。")
        return redirect("frontend:product_detail", pk=pk)
 
    order_type = request.POST.get("order_type")           # 'rental' or 'purchase'
    quantity = int(request.POST.get("quantity") or 1)
 
    postal_code = request.POST.get("postal_code", "")
    address = request.POST.get("address", "")
    payment_method = request.POST.get("payment_method")
    message_txt = request.POST.get("message", "")
 
    start_date = request.POST.get("start_date") or None
    end_date   = request.POST.get("end_date") or None
 
    # 提供方法チェック
    t = getattr(product, "availability_type", "レンタル・販売両方")
    allow_rental = t in ("レンタル・販売両方", "レンタルのみ")
    allow_purchase = t in ("レンタル・販売両方", "販売のみ")
    if order_type == "rental" and not allow_rental:
        messages.error(request, "この商品はレンタルできません。")
        return redirect("frontend:product_detail", pk=pk)
    if order_type == "purchase" and not allow_purchase:
        messages.error(request, "この商品は購入できません。")
        return redirect("frontend:product_detail", pk=pk)
 
    # バリデーション
    errors = []
    if quantity < 1:
        errors.append("個数は1以上にしてください。")
    if not payment_method:
        errors.append("決済方法を選択してください。")
 
    from django.utils.dateparse import parse_date
    sd = ed = None
    if order_type == "rental":
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
 
    # 申請レコード作成
    RentalApplication.objects.create(
        product=product,
        owner=product.owner,          # 受け取り側
        renter=request.user,          # 申請者
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
