from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_nested import routers
from django.views.generic import RedirectView  # ← 追加
from marketplace.views import ProductViewSet, ProductImageViewSet, RentalViewSet, PurchaseViewSet
from chat.views import ChatRoomViewSet, ChatMessageViewSet
from notifications.views import NotificationViewSet
from accounts.views import RegisterView, MeView
from django.urls import path, include
router = routers.DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")
router.register(r"rentals", RentalViewSet, basename="rentals")
router.register(r"purchases", PurchaseViewSet, basename="purchases")
router.register(r"notifications", NotificationViewSet, basename="notifications")
router.register(r"rooms", ChatRoomViewSet, basename="rooms")

# ネスト: /products/{product_id}/images/
products_router = routers.NestedDefaultRouter(router, r"products", lookup="product")
products_router.register(r"images", ProductImageViewSet, basename="product-images")

# ネスト: /rooms/{room_id}/messages/
rooms_router = routers.NestedDefaultRouter(router, r"rooms", lookup="room")
rooms_router.register(r"messages", ChatMessageViewSet, basename="room-messages")

urlpatterns = [
    path("", include(("frontend.urls", "frontend"), namespace="frontend")), # ← ユーザー向け画面
    path("admin/", admin.site.urls),
    path("chat/", include("chat.urls")), 

    # API
    path("api/v1/", include(router.urls)),
    path("api/v1/", include(products_router.urls)),
    path("api/v1/", include(rooms_router.urls)),

    # Auth API & Docs（そのまま）
    path("api/v1/auth/register/", RegisterView.as_view(), name="register"),
    path("api/v1/auth/jwt/create/", TokenObtainPairView.as_view(), name="jwt-create"),
    path("api/v1/auth/jwt/refresh/", TokenRefreshView.as_view(), name="jwt-refresh"),
    path("api/v1/auth/me/", MeView.as_view(), name="me"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 既存の urlpatterns の下など、モジュール直下にこれを追加
handler403 = "frontend.views.error_403"
handler404 = "frontend.views.error_404"
handler500 = "frontend.views.error_500"


