from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from accounts.views import profile_view
from django.views.generic import RedirectView

app_name = "frontend"

urlpatterns = [
    # 一覧・詳細
    path("", views.ProductListView.as_view(), name="products"),
    path("products/", views.ProductListView.as_view(), name="products"),
    path("products/new/", views.product_create, name="product_new"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product_detail"),
    # frontend/urls.py
    path('products/<int:pk>/favorite/toggle/', views.product_favorite_toggle, name='product_favorite_toggle'),

    path("profile/history/", views.profile_history, name="profile_history"),
    path("rentals/<int:rental_id>/finish/", views.rental_finish, name="rental_finish"),
    path("purchases/<int:purchase_id>/receive_done/", views.purchase_receive_done, name="purchase_receive_done"),

    # 追加: 編集 / 削除API
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete_api, name="product_delete_api"),


    # ルートを一覧へ
    path("", RedirectView.as_view(pattern_name="frontend:products", permanent=False)),

    # サイドバー系
    path("purchases/", views.purchases_index, name="purchases"),
    path("purchases/my/", views.my_purchases, name="my_purchases"),
    path("purchases/received/", views.received_purchases, name="received_purchases"),
    path("rentals/received/", views.received_rentals, name="received_rentals"),
    path("rentals/", views.rentals_index, name="rentals"),


    path("returns/", views.returns_index, name="returns"),
    path("returns/action/", views.return_action, name="return_action"),


    path("messages/",  views.MessagesPage.as_view(),     name="messages"),
    path("notifications/", views.my_notifications, name="notifications"),
    path("profile/", views.profile, name="profile"),

    path("docs/",      views.DocumentationView.as_view(),name="docs"),
    path("admin/shipping/", views.AdminShippingView.as_view(), name="admin_shipping"),

    # 認証
    path("login/",  auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("error/403/", views.error_403, name="error_403"),

    # 申請
    path("products/<int:pk>/apply/", views.rental_apply, name="rental_apply"),
    path("rentals/manage/", views.rental_manage, name="rental_manage"),
    path("rentals/applications/<int:app_id>/approve/", views.rental_app_approve, name="rental_app_approve"),
    path("rentals/applications/<int:app_id>/reject/", views.rental_app_reject, name="rental_app_reject"),
     path("rentals/applications/<int:app_id>/ship/",    views.rental_app_ship,    name="rental_app_ship"),

    # マイページ（出品一覧）
    path("mypage/products/", views.my_products, name="my_products"),

    # お問い合わせ
    path("contact/", views.contact_page, name="contact"),
    path("api/contact/", views.contact_api, name="contact_api"),
    path("rentals/my/", views.my_applications, name="my_applications"),

    # ▼ 追加（私の申請をキャンセル）
    path("rentals/applications/<int:app_id>/cancel/", views.rental_app_cancel, name="rental_app_cancel"),
    # 借り手側のアクション
    path("rentals/app/<int:app_id>/receive/",      views.rental_app_receive,      name="rental_app_receive"),
    path("rentals/app/<int:app_id>/return_ship/",  views.rental_app_return_ship,  name="rental_app_return_ship"),
    path("rentals/app/<int:app_id>/confirm_return/", views.rental_app_confirm_return, name="rental_app_confirm_return",),
]
