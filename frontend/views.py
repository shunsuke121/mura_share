# frontend/views.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

from marketplace.models import Product
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login


class ProductListView(ListView):
    model = Product
    template_name = "frontend/products/index.html"  # 一覧テンプレ
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        # 出品中だけ出したいならこう
        return Product.objects.filter(status=Product.Status.LISTED).order_by("-created_at")


class ProductDetailView(DetailView):
    model = Product
    template_name = "frontend/products/detail.html"  # 詳細テンプレ
    context_object_name = "product"

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


@login_required
def product_create(request):
    user = request.user

    # 住所必須チェック
    if not getattr(user, "address", None):
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

        # レンタル・販売の必須チェック（React版と同じロジック）
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

        # 数値変換
        try:
            daily_price_val = float(daily_price) if daily_price else None
            sale_price_val = float(sale_price) if sale_price else None
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

        # Product作成（フィールド名は自分のモデルに合わせて調整）
        product = Product(
            owner=user,
            title=title,
            description=description,
            category=category,
            availability_type=availability_type,  # モデルにこのカラムがある前提
            daily_price=daily_price_val,
            sale_price=sale_price_val,
            min_rental_days=min_rental_days_val,
            max_rental_days=max_rental_days_val,
            stock_quantity=stock_quantity_val,
            available_quantity=stock_quantity_val,
            condition=condition,
            owner_notes=owner_notes,
            status="利用可能",
            views=0,
            average_rating=0,
            review_count=0,
        )

        # 画像
        product.image_main = image_main
        if image_sub1:
            product.image_sub1 = image_sub1
        if image_sub2:
            product.image_sub2 = image_sub2
        if image_sub3:
            product.image_sub3 = image_sub3

        product.save()

        messages.success(request, "商品を投稿しました。")
        return redirect("frontend:products")

    # GET のとき：初期値を渡す
    form_data = {
        "availability_type": "レンタル・販売両方",
        "min_rental_days": 1,
        "max_rental_days": 30,
        "stock_quantity": 1,
    }
    return render(request, "frontend/products/form.html", {"form_data": form_data})

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
