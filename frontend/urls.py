from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from accounts.views import profile_view

app_name = "frontend"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="products"),
    path("products/new/", views.product_create, name="product_new"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),

    # サイドバーで参照している名前をすべて定義
    path("purchases/", views.PurchaseListView.as_view(), name="purchases"),
    path("rentals/my/",       views.my_rentals,       name="my_rentals"),
    path("rentals/received/", views.received_rentals, name="received_rentals"),
    path("rentals/", views.my_rentals, name="rentals"),
    path("returns/",   views.ReturnListPage.as_view(),   name="returns"),
    path("messages/",  views.MessagesPage.as_view(),     name="messages"),
    path("profile/",   profile_view,                     name="profile"),
    path("docs/",      views.DocumentationView.as_view(),name="docs"),
    path("admin/shipping/", views.AdminShippingView.as_view(), name="admin_shipping"),

    # 認証
    path("login/",  auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),

    # 申請関連（★ views. を必ず付ける）
    path("products/<int:pk>/apply/", views.rental_apply, name="rental_apply"),
    path("rentals/manage/", views.rental_manage, name="rental_manage"),

    # オーナーマイページ（投稿商品一覧）
    path("mypage/products/", views.my_products, name="my_products"),
]
