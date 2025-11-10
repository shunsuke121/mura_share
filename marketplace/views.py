from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, decorators, response, status, parsers
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import Product, ProductImage, Rental, Purchase, Review
from .serializers import ProductSerializer, ProductImageSerializer, RentalSerializer, PurchaseSerializer, ReviewSerializer

class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "owner", None) or getattr(obj, "user", None)
        if owner:
            return owner == request.user
        # Rental/Purchaseなどは作成者/関係者に限定（必要最小限）
        if hasattr(obj, "renter"):
            return obj.renter == request.user or obj.product.owner == request.user
        if hasattr(obj, "buyer"):
            return obj.buyer == request.user or obj.product.owner == request.user
        return False

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("owner").prefetch_related("images")
    serializer_class = ProductSerializer
    permission_classes = [IsOwnerOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category","status","owner"]
    search_fields = ["title","description","category"]
    ordering_fields = ["created_at","price_per_day","price_buy"]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

class ProductImageViewSet(viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get_queryset(self):
        qs = ProductImage.objects.all()
        product_id = self.kwargs.get("product_pk")
        return qs.filter(product_id=product_id) if product_id else qs

    def perform_create(self, serializer):
        product_id = self.kwargs.get("product_pk") or self.request.data.get("product")
        serializer.save(product_id=product_id)

class RentalViewSet(viewsets.ModelViewSet):
    queryset = Rental.objects.select_related("product","renter")
    serializer_class = RentalSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(renter=self.request.user)

    @decorators.action(detail=True, methods=["post"])
    def change_status(self, request, pk=None):
        obj = self.get_object()
        status_val = int(request.data.get("status", obj.status))
        obj.status = status_val
        obj.save()
        return response.Response(self.get_serializer(obj).data)

class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.select_related("product","buyer")
    serializer_class = PurchaseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(buyer=self.request.user)

class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.select_related("product","user")
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
