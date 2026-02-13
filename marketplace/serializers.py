from rest_framework import serializers
from .models import Product, ProductImage, Rental, Purchase, Review

class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "product"]

class ProductSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = ["id", "title", "description", "category",
                  "price_per_day", "price_buy", "status",
                  "owner", "images", "created_at"]

class RentalSerializer(serializers.ModelSerializer):
    renter = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Rental
        fields = ["id","product","renter","start_date","end_date","total_price","status","created_at"]

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError("end_date は start_date 以降にしてください。")
        return attrs

class PurchaseSerializer(serializers.ModelSerializer):
    buyer = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "product", "buyer", "purchase_price", "status", "created_at"]

class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Review
        fields = ["id","product","user","rating","comment","created_at"]
