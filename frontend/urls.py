# frontend/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from accounts.views import profile_view

app_name = "frontend"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="products"),
    path("products/new/", views.product_create, name="product_new"),  # ←これ
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    
    # サイドバーで参照している名前をすべて定義（中身は後でOK）
    path("purchases/", views.PurchaseListView.as_view(), name="purchases"),
    path("rentals/",   views.RentalListPage.as_view(),   name="rentals"),
    path("returns/",   views.ReturnListPage.as_view(),   name="returns"),
    path("messages/",  views.MessagesPage.as_view(),     name="messages"),
    path("profile/",   profile_view,                     name="profile"),
    path("docs/",      views.DocumentationView.as_view(),name="docs"),
    path("admin/shipping/", views.AdminShippingView.as_view(), name="admin_shipping"),

    # 認証
    path("login/",  auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
]
