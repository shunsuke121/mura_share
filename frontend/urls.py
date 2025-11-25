from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from accounts.views import profile_view
from django.views.generic import RedirectView

app_name = "frontend"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="products"),
    path("products/", views.ProductListView.as_view(), name="products"),
    path("products/new/", views.product_create, name="product_new"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("", RedirectView.as_view(pattern_name="frontend:products", permanent=False)),

    # サイドバーで参照している名前をすべて定義
    path("purchases/", views.purchases_index, name="purchases"),
    path("purchases/my/", views.my_purchases, name="my_purchases"),
    path("purchases/received/", views.received_purchases, name="received_purchases"),

    path("rentals/my/",       views.my_rentals,       name="my_rentals"),
    path("rentals/received/", views.received_rentals, name="received_rentals"),
    path("rentals/", views.rentals_index, name="rentals"),
    
    path("returns/", views.returns_index, name="returns"),
    path("returns/action/", views.return_action, name="return_action"),


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
    
    # お問い合わせ
    path("contact/", views.contact_page, name="contact"),
    path("api/contact/", views.contact_api, name="contact_api"),
]