# marketplace/models.py

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Product(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    @property
    def image_url(self):
        """一覧・詳細で使うメイン画像URL"""
        first = self.images.first()
        if first and first.image:
            try:
                return first.image.url
            except Exception:
                return ""
        return ""
    class Status(models.IntegerChoices):
        DRAFT    = 0, "下書き"
        LISTED   = 1, "出品中"
        RENTED   = 2, "貸出中"
        SOLD     = 3, "販売済"
        ARCHIVED = 9, "アーカイブ"

    class Availability(models.TextChoices):
        RENTAL_ONLY   = "レンタルのみ", "レンタルのみ"
        SALE_ONLY     = "販売のみ", "販売のみ"
        BOTH          = "レンタル・販売両方", "レンタル・販売両方"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="products")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=60)

    # ここがゴリゴリ強化ゾーン
    availability_type = models.CharField(
        max_length=20,
        choices=Availability.choices,
        default=Availability.BOTH,
    )

    # 料金
    price_per_day = models.PositiveIntegerField(null=True, blank=True)  # レンタル1日あたり
    price_buy = models.PositiveIntegerField(null=True, blank=True)      # 販売価格

    # レンタル設定
    min_rental_days = models.PositiveIntegerField(default=1)
    max_rental_days = models.PositiveIntegerField(default=30)

    # 在庫
    stock_quantity = models.PositiveIntegerField(default=1)
    available_quantity = models.PositiveIntegerField(default=1)

    # 商品状態 / オーナーメモ
    condition = models.CharField(max_length=30, blank=True)
    owner_notes = models.TextField(blank=True)

    status = models.IntegerField(choices=Status.choices, default=Status.LISTED)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")


class Rental(models.Model):
    class Status(models.TextChoices):
        REQUESTED        = "申請中", "申請中"
        APPROVED         = "承認済み", "承認済み"
        SHIPPED          = "発送済み", "発送済み"
        RENTING          = "レンタル中", "レンタル中"
        RETURN_SHIPPED   = "返却発送済み", "返却発送済み"
        RETURNED         = "返却済み", "返却済み"
        COMPLETED        = "完了", "完了"
        CANCELED         = "キャンセル", "キャンセル"

    # どの商品か
    product = models.ForeignKey(
        "marketplace.Product",
        on_delete=models.CASCADE,
        related_name="rentals",
    )

    # 借り手（ユーザーFK）
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rentals",
    )

    renter_email = models.EmailField(null=True, blank=True)
    owner_email  = models.EmailField(null=True, blank=True)
    product_title = models.CharField(max_length=255, null=True, blank=True)


    # 個数・料金・日数
    quantity    = models.PositiveIntegerField(default=1)
    total_price = models.PositiveIntegerField(default=0)
    total_days  = models.PositiveIntegerField(default=1)

    # 配送情報・メッセージ
    shipping_address = models.TextField(blank=True)
    message          = models.TextField(blank=True)

    # レンタル期間
    start_date = models.DateField()
    end_date   = models.DateField()

    # ステータス（文字列で管理）
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
    )

    # 作成日時
    created_at = models.DateTimeField(auto_now_add=True)


    # 往路の発送
    shipped_date_to_renter    = models.DateTimeField(null=True, blank=True)
    tracking_number_to_renter = models.CharField(max_length=100, blank=True)

    # 受取〜レンタル開始
    received_date_by_renter = models.DateTimeField(null=True, blank=True)
    rental_start_date       = models.DateTimeField(null=True, blank=True)

    # 返送
    shipped_date_return  = models.DateTimeField(null=True, blank=True)
    tracking_number_return = models.CharField(max_length=100, blank=True)

    # 返却完了・レンタル完了
    returned_date  = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)

    # 支払い方法（クレカ / 現地払い とか）
    payment_method = models.CharField(max_length=50, blank=True)

    # 便利プロパティ（今後も "rental.xxx" で触りやすくする用）

    @property
    def product_owner(self):
        # Product 側に owner がいる前提
        return getattr(self.product, "owner", None)

    def __str__(self):
        return f"{self.product_title} - {self.renter_email}"

class Purchase(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="purchases")
    buyer   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="purchases")
    price   = models.PositiveIntegerField()
    status  = models.CharField(max_length=20, default="paid_flag")
    created_at = models.DateTimeField(auto_now_add=True)


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    rating  = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

# --- RentalApplication（申請）モデル ここから追記 -------------------------
from django.conf import settings
from django.db import models

class RentalApplication(models.Model):
    class OrderType(models.TextChoices):
        RENTAL = 'rental', 'レンタル'
        PURCHASE = 'purchase', '購入'

    class Status(models.TextChoices):
        PENDING   = 'pending',   '申請中'
        APPROVED  = 'approved',  '承認'
        REJECTED  = 'rejected',  '却下'
        CANCELLED = 'cancelled', 'キャンセル'

    product = models.ForeignKey('marketplace.Product',
                                on_delete=models.CASCADE,
                                related_name='applications')
    owner   = models.ForeignKey(settings.AUTH_USER_MODEL,
                                on_delete=models.CASCADE,
                                related_name='received_applications')
    renter  = models.ForeignKey(settings.AUTH_USER_MODEL,
                                on_delete=models.CASCADE,
                                related_name='sent_applications')

    order_type = models.CharField(max_length=10, choices=OrderType.choices)
    quantity   = models.PositiveIntegerField(default=1)

    # レンタル時のみ使用
    start_date = models.DateField(blank=True, null=True)
    end_date   = models.DateField(blank=True, null=True)

    postal_code = models.CharField(max_length=20, blank=True)
    address     = models.CharField(max_length=255, blank=True)

    PAYMENT_CHOICES = [
        ('card',        'クレジットカード'),
        ('convenience', 'コンビニ'),
        ('paypay',      'PayPay'),
        ('bank',        '銀行振込'),
    ]
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    message        = models.TextField(blank=True)

    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_order_type_display()}申請: product={self.product_id}, by={self.renter_id}'
# --- 追記ここまで ----------------------------------------------------------

