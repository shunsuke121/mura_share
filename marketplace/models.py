from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL

class Product(models.Model):
    class Status(models.IntegerChoices):
        DRAFT = 0, "下書き"
        LISTED = 1, "出品中"
        RENTED = 2, "貸出中"
        SOLD = 3, "販売済"
        ARCHIVED = 9, "アーカイブ"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="products")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=60)
    price_per_day = models.PositiveIntegerField(null=True, blank=True)
    price_buy = models.PositiveIntegerField(null=True, blank=True)
    status = models.IntegerField(choices=Status.choices, default=Status.LISTED)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")

class Rental(models.Model):
    class Status(models.IntegerChoices):
        REQUESTED = 0, "申請中"
        APPROVED  = 1, "承認"
        REJECTED  = 2, "却下"
        SHIPPED   = 3, "発送"
        RECEIVED  = 4, "受取"
        RETURNED  = 5, "返却"
        COMPLETED = 6, "完了"
        CANCELED  = 9, "キャンセル"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="rentals")
    renter  = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rentals")
    start_date = models.DateField()
    end_date   = models.DateField()
    total_price = models.PositiveIntegerField(default=0)
    status = models.IntegerField(choices=Status.choices, default=Status.REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True)

class Purchase(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="purchases")
    buyer   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="purchases")
    price   = models.PositiveIntegerField()
    status  = models.CharField(max_length=20, default="paid_flag")  # 11月はフラグ運用
    created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    rating  = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
