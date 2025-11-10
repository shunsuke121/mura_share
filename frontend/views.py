# frontend/views.py
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from marketplace.models import Product, ProductImage, Rental

# オプション: これらのアプリが無くても落ちないように例外で握る
try:
    from chat.models import ChatRoom
except Exception:
    ChatRoom = None
try:
    from notifications.models import Notification
except Exception:
    Notification = None

# 既存の forms を利用（※ここがポイント）
from .forms import ProductForm, ProductImageForm, RentalForm


# ───────── 商品一覧（検索/並び替え） ─────────
class ProductListView(ListView):
    model = Product
    template_name = "frontend/product_list.html"
    paginate_by = 12
    context_object_name = "products"

    def get_queryset(self):
        qs = Product.objects.order_by("-created_at").prefetch_related("images")
        q = self.request.GET.get("q")
        category = self.request.GET.get("category")
        ordering = self.request.GET.get("ordering", "-created_at")

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
        if category:
            qs = qs.filter(category__icontains=category)

        allowed = {
            "created_at", "-created_at",
            "price_per_day", "-price_per_day",
            "price_buy", "-price_buy",
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["category"] = self.request.GET.get("category", "")
        ctx["ordering"] = self.request.GET.get("ordering", "-created_at")
        return ctx


# ───────── 商品詳細 ─────────
class ProductDetailView(DetailView):
    model = Product
    template_name = "frontend/product_detail.html"
    context_object_name = "product"


# ───────── 出品（新規作成, 複数画像対応） ─────────
@login_required
def product_create(request):
    if request.method == "POST":
        form = ProductForm(request.POST)
        img_form = ProductImageForm(request.POST, request.FILES)
        files = request.FILES.getlist("image")  # <input name="image" multiple>
        if form.is_valid():
            product = form.save(commit=False)
            product.owner = request.user
            product.save()
            for f in files:
                ProductImage.objects.create(product=product, image=f)
            messages.success(request, "商品を登録しました。")
            return redirect("product_detail", pk=product.pk)
    else:
        form = ProductForm()
        img_form = ProductImageForm()
    return render(request, "frontend/product_form.html", {"form": form, "img_form": img_form})


# ───────── レンタル申請 ─────────
@login_required
def rental_request(request, pk: int):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = RentalForm(request.POST)
        if form.is_valid():
            start = form.cleaned_data["start_date"]
            end = form.cleaned_data["end_date"]
            if start > end:
                messages.error(request, "終了日は開始日以降を指定してください。")
            else:
                days = (end - start).days + 1
                total = (product.price_per_day or 0) * days
                Rental.objects.create(
                    product=product,
                    renter=request.user,
                    start_date=start,
                    end_date=end,
                    total_price=total,
                )
                messages.success(request, "レンタル申請を送信しました。")
                return redirect("product_detail", pk=product.pk)
    else:
        form = RentalForm()
    return render(request, "frontend/rental_form.html", {"product": product, "form": form})


# ───────── サインアップ ─────────
def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "アカウントを作成しました。")
            return redirect("frontend:products")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})


# ───────── マイページ系 ─────────
class MyProductsListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "frontend/my_products.html"
    paginate_by = 12
    context_object_name = "products"

    def get_queryset(self):
        return Product.objects.filter(owner=self.request.user).order_by("-created_at").prefetch_related("images")


class MyRentalsListView(LoginRequiredMixin, ListView):
    model = Rental
    template_name = "frontend/my_rentals.html"
    paginate_by = 20
    context_object_name = "rentals"

    def get_queryset(self):
        return Rental.objects.filter(renter=self.request.user).select_related("product").order_by("-id")


class MyRoomsListView(LoginRequiredMixin, TemplateView):
    template_name = "frontend/my_rooms.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rooms = []
        if ChatRoom is not None:
            try:
                rooms = list(ChatRoom.objects.all()[:50])
            except Exception:
                rooms = []
        ctx["rooms"] = rooms
        return ctx


class MyNotificationsListView(LoginRequiredMixin, TemplateView):
    template_name = "frontend/my_notifications.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        notifs = []
        if Notification is not None:
            try:
                notifs = list(Notification.objects.filter(user=self.request.user).order_by("-id")[:100])
            except Exception:
                notifs = []
        ctx["notifications"] = notifs
        return ctx

class PurchaseListView(LoginRequiredMixin, TemplateView):
    template_name = "frontend/purchases/index.html"

class RentalListPage(LoginRequiredMixin, TemplateView):
    template_name = "frontend/rentals/index.html"

class ReturnListPage(LoginRequiredMixin, TemplateView):
    template_name = "frontend/returns/index.html"

class MessagesPage(LoginRequiredMixin, TemplateView):
    template_name = "frontend/messages/index.html"

class ProfilePage(LoginRequiredMixin, TemplateView):
    template_name = "frontend/profile/index.html"

class AdminShippingView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "frontend/admin/shipping.html"
    def test_func(self):  # 管理者のみ
        return self.request.user.is_superuser

class DocumentationView(TemplateView):
    template_name = "frontend/docs/index.html"
