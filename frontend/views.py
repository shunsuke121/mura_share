from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login

from accounts.models import Profile
from marketplace.models import Product, ProductImage, RentalApplication  # ★ 申請モデルも使う


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
        ).order_by("-created_at")


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

        # ▼ 提供方法（あなたのモデルは availability_type を日本語で保持）
        #   値: 「レンタル・販売両方」「レンタルのみ」「販売のみ」
        t = getattr(p, "availability_type", "レンタル・販売両方")
        allow_rental = t in ("レンタル・販売両方", "レンタルのみ")
        allow_purchase = t in ("レンタル・販売両方", "販売のみ")
        ctx["allow_rental"] = allow_rental
        ctx["allow_purchase"] = allow_purchase

        return ctx


class PurchaseListView(TemplateView):
    template_name = "frontend/purchases/index.html"


class RentalListPage(TemplateView):
    template_name = "frontend/rentals/index.html"


class ReturnListPage(TemplateView):
    template_name = "frontend/returns/index.html"


class MessagesPage(TemplateView):
    template_name = "frontend/messages/index.html"


class DocumentationView(TemplateView):
    template_name = "frontend/docs/index.html"


class AdminShippingView(TemplateView):
    template_name = "frontend/admin/shipping.html"


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

        # --- Product作成（あなたのモデルのフィールド名に準拠）---
        product = Product(
            owner=user,
            title=title,
            description=description,
            category=category,
            availability_type=availability_type,
            # モデル側は price_per_day / price_buy
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

    # GET のとき：初期値
    form_data = {
        "availability_type": "レンタル・販売両方",
        "min_rental_days": 1,
        "max_rental_days": 30,
        "stock_quantity": 1,
    }
    return render(request, "frontend/products/form.html", {"form_data": form_data})


@login_required
def product_create_done(request):
    # （未使用でもOK）
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
        for e in errors: messages.error(request, e)
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
    apps = RentalApplication.objects.filter(owner=request.user).order_by("-created_at")
    return render(request, "frontend/rentals/manage.html", {"applications": apps})


@login_required
def my_products(request):
    """オーナーの投稿商品一覧"""
    items = Product.objects.filter(owner=request.user).order_by("-created_at")
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
