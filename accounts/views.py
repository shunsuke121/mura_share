# accounts/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from marketplace.models import ProductFavorite
from django.contrib import messages

from rest_framework import generics, permissions, response, views

from .serializers import RegisterSerializer
from .models import Profile
from marketplace.models import Product

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        profile, _ = Profile.objects.get_or_create(user=u)

        profile_image_url = None
        if profile.profile_image:
            try:
                profile_image_url = profile.profile_image.url
            except Exception:
                profile_image_url = None

        return response.Response({
            "id": u.id,
            "username": u.get_username(),
            "email": u.email,
            "display_name": profile.display_name or u.get_username(),
            "full_name": "",
            "phone": profile.phone,
            "address": profile.address,
            "profile_image_url": profile_image_url,
            "rating": getattr(u, "rating", None),
            "completed_rentals": getattr(u, "completed_rentals", 0),
            "favorite_products": getattr(u, "favorite_products", []),
            "role": getattr(u, "role", "user"),
        })


@login_required
def profile_view(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    active_tab = request.GET.get("tab", "info")
    editing = request.GET.get("edit") == "1"

    # プロフィール更新処理（POST）
    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        profile_image = request.FILES.get("profile_image")

        original_address = profile.address

        if display_name:
            profile.display_name = display_name
        profile.phone = phone
        profile.address = address

        if profile_image is not None:
            profile.profile_image = profile_image

        profile.save()

        if not original_address and address:
            messages.success(
                request,
                "住所を登録しました。これで商品の投稿・レンタル・購入が可能になりました。"
            )
        else:
            messages.success(request, "プロフィールを更新しました。")

        return redirect("frontend:profile")

    # 自分の商品一覧
    my_products = Product.objects.filter(owner=user)

    # お気に入り一覧
    favorites = (
        ProductFavorite.objects
        .filter(user=user)
        .select_related("product", "product__owner")
        .order_by("-created_at")
    )

    # とりあえず空で置いてるならこれでOK
    renting_products = []
    transactions = []

    context = {
        "user_obj": user,
        "profile": profile,          # テンプレ側でプロフィール情報使う用
        "active_tab": active_tab,
        "editing": editing,
        "my_products": my_products,
        "favorites": favorites,      # プロフィールの「お気に入りタブ」で使う
        "renting_products": renting_products,
        "transactions": transactions,
    }

    return render(request, "frontend/profile/index.html", context)
