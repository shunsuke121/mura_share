# marketplace/models.py

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

User = settings.AUTH_USER_MODEL


class Product(models.Model):

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

    @property
    def available_count(self):
        if self.available_quantity is None:
            return self.stock_quantity or 0
        return self.available_quantity

    @property
    def is_sold_out(self):
        return self.available_count <= 0
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
    

class ProductFavorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_favorites")
    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
        indexes = [models.Index(fields=["user", "product"])]

    def __str__(self):
        return f"{self.user_id} ♥ {self.product_id}"




class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")


class ProductComment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_comments")
    body = models.TextField()
    image = models.ImageField(upload_to="product_comments/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)


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
    class Status(models.TextChoices):
        REQUESTED  = "申請中",  "申請中"
        APPROVED   = "承認済み", "承認済み"  
        SHIPPED    = "発送済み","発送済み"
        COMPLETED  = "完了",    "完了"
        CANCELED   = "キャンセル","キャンセル"

    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE, related_name="purchases")
    buyer   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="purchases")

    # 参照を減らすための冗長カラム（テンプレの表示用）
    product_title  = models.CharField(max_length=255, blank=True)
    buyer_email    = models.EmailField(blank=True)
    seller_email   = models.EmailField(blank=True)

    shipping_postal_code = models.CharField(max_length=20, blank=True, default="") 
    shipping_address = models.CharField(max_length=255, blank=True)
    payment_method   = models.CharField(max_length=50, blank=True)
    message          = models.TextField(blank=True)
    from_rental      = models.BooleanField(default=False)
    hidden_by_buyer  = models.BooleanField(default=False)
    hidden_by_seller = models.BooleanField(default=False)

    quantity       = models.PositiveIntegerField(default=1)
    purchase_price = models.PositiveIntegerField(default=0)

    status          = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    tracking_number = models.CharField(max_length=100, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    shipped_at  = models.DateTimeField(null=True, blank=True) 

    created_at     = models.DateTimeField(auto_now_add=True)
    completed_date = models.DateTimeField(null=True, blank=True)

    class ReturnStatus(models.TextChoices):
        NONE = "NONE", "なし"
        REQUESTED = "REQUESTED", "申請中"
        APPROVED = "APPROVED", "承諾済"
        SHIPPED = "SHIPPED", "返送済み"
        RECEIVED = "RECEIVED", "受領済み"
        REJECTED = "REJECTED", "却下"

    return_status = models.CharField(
        max_length=20, choices=ReturnStatus.choices, default=ReturnStatus.NONE
    )
    return_reason = models.CharField(max_length=255, blank=True)
    return_tracking_number = models.CharField(max_length=64, blank=True)
    return_requested_at = models.DateTimeField(null=True, blank=True)
    return_approved_at  = models.DateTimeField(null=True, blank=True)
    return_shipped_at   = models.DateTimeField(null=True, blank=True)
    return_received_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["buyer_email"]),
            models.Index(fields=["seller_email"]),
        ]

    def __str__(self):
        return f"{self.product_title or self.product_id} / {self.buyer_email} ({self.status})"

    @property
    def created_date(self):
        # テンプレ側で created_date を参照しても落ちないようにする
        return self.created_at

    def save(self, *args, **kwargs):
        # 表示用の冗長カラムを自動補完
        if self.product_id and not self.product_title:
            self.product_title = getattr(self.product, "title", "") or ""
        if self.product_id and not self.seller_email:
            owner = getattr(self.product, "owner", None)
            self.seller_email = getattr(owner, "email", "") if owner else ""
        if self.buyer_id and not self.buyer_email:
            self.buyer_email = getattr(self.buyer, "email", "") or ""
        if self.purchase_price is None:
            self.purchase_price = 0
        super().save(*args, **kwargs)


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    rating  = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

# --- RentalApplication（申請）モデル ここから追記 -------------------------

class RentalApplication(models.Model):
    tracking_number = models.CharField(max_length=100, blank=True, default="")
    class OrderType(models.TextChoices):
        RENTAL = 'rental', 'レンタル'
        PURCHASE = 'purchase', '購入'

    class Status(models.TextChoices):
        PENDING         = 'pending',        '申請中'
        APPROVED        = 'approved',       '承認済み'      # ← 表示名はお好みで
        SHIPPED         = 'shipped',        '発送済み'      # ← 追加
        RECEIVED        = 'received',       '受取完了'      # ← 将来用（借り手確認）
        RETURN_SHIPPED  = 'return_shipped', '返却発送済み'  # ← 将来用（借り手返送）
        COMPLETED       = 'completed',      '完了'          # ← 将来用（出品者確認）
        REJECTED        = 'rejected',       '却下'
        CANCELLED       = 'cancelled',      'キャンセル'

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

    # 申請時に入力された「メッセージ」
    message        = models.TextField(blank=True)

    # ★ 承認後に入力する「追跡番号」
    tracking_number = models.CharField(max_length=50, blank=True, default="")
    return_tracking_number = models.CharField(max_length=100, blank=True, default="")

    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    hidden_by_owner = models.BooleanField(default=False)
    hidden_by_renter = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_order_type_display()}申請: product={self.product_id}, by={self.renter_id}'


# --- Shipment（配送管理） -----------------------------------------
# 末尾あたりに追加
from django.db.models import Q
class Shipment(models.Model):
    class Kind(models.TextChoices):
        RENTAL   = "rental", "レンタル"
        PURCHASE = "purchase", "購入"

    # 往路=出品者/貸し手→買い手/借り手、返送=買い手/借り手→出品者/貸し手
    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "往路"
        RETURN   = "return",   "返送"
        INBOUND  = "inbound",  "受領側（内部用）"  # 返品の受領側用に残す

    class Status(models.TextChoices):
        CREATED    = "created",     "作成"
        IN_TRANSIT = "in_transit",  "輸送中"
        DELIVERED  = "delivered",   "配達完了"
        CANCELED   = "canceled",    "キャンセル"

    kind      = models.CharField(max_length=10, choices=Kind.choices)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    status    = models.CharField(max_length=12, choices=Status.choices, default=Status.CREATED)

    product  = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE, related_name="shipments")

    # 既存（Rental/Purchase）
    rental   = models.ForeignKey(
        "marketplace.Rental",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="shipments"
    )
    purchase = models.ForeignKey(
        "marketplace.Purchase",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="shipments"
    )

    # ★追加：RentalApplication（申請フロー）でも配送管理に出せるようにする
    application = models.ForeignKey(
        "marketplace.RentalApplication",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="shipments"
    )

    # 住所スナップショット（当事者同士を直接見ない想定）
    from_name    = models.CharField(max_length=120, blank=True, default="")
    from_phone   = models.CharField(max_length=40,  blank=True, default="")
    from_postal  = models.CharField(max_length=20,  blank=True, default="")
    from_address = models.CharField(max_length=255, blank=True, default="")

    to_name    = models.CharField(max_length=120, blank=True, default="")
    to_phone   = models.CharField(max_length=40,  blank=True, default="")
    to_postal  = models.CharField(max_length=20,  blank=True, default="")
    to_address = models.CharField(max_length=255, blank=True, default="")

    tracking_no = models.CharField(max_length=100, blank=True, default="")
    is_platform_intermediated = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["kind"]),
            models.Index(fields=["direction"]),
            models.Index(fields=["status"]),
            models.Index(fields=["tracking_no"]),
            models.Index(fields=["rental"]),
            models.Index(fields=["purchase"]),
            models.Index(fields=["application"]),  # ★追加
        ]
        constraints = [
            # ★同じ取引(= rental/purchase/application) + direction は1件に固定
            models.UniqueConstraint(
                fields=["rental", "direction"],
                condition=Q(rental__isnull=False),
                name="uniq_shipment_rental_direction",
            ),
            models.UniqueConstraint(
                fields=["purchase", "direction"],
                condition=Q(purchase__isnull=False),
                name="uniq_shipment_purchase_direction",
            ),
            models.UniqueConstraint(
                fields=["application", "direction"],
                condition=Q(application__isnull=False),
                name="uniq_shipment_application_direction",
            ),

            # ★kind と紐付け先の整合性（雑に事故らないための最低限）
            models.CheckConstraint(
                check=(
                    # kind=rental のとき：rental か application のどっちか（purchaseは無し）
                    (Q(kind="rental") & (Q(rental__isnull=False) | Q(application__isnull=False)) & Q(purchase__isnull=True))
                    |
                    # kind=purchase のとき：purchase 必須（rental/applicationは無し）
                    (Q(kind="purchase") & Q(purchase__isnull=False) & Q(rental__isnull=True) & Q(application__isnull=True))
                ),
                name="chk_shipment_kind_fk_consistency",
            ),
            # ★rental と application を同時に入れない（混ぜると地獄）
            models.CheckConstraint(
                check=~(Q(rental__isnull=False) & Q(application__isnull=False)),
                name="chk_shipment_rental_xor_application",
            ),
        ]

    def __str__(self):
        pid = getattr(self.product, "id", None)
        rid = getattr(self.rental, "id", None)
        aid = getattr(self.application, "id", None)
        pur = getattr(self.purchase, "id", None)
        ref = f"R#{rid}" if rid else (f"A#{aid}" if aid else (f"PU#{pur}" if pur else "-"))
        return f"{self.get_kind_display()} / {self.get_direction_display()} / P#{pid} / {ref} / {self.tracking_no or '-'}"


def _get_chat_room_model():
    try:
        from chat.models import ChatRoom
    except Exception:
        return None
    return ChatRoom


def _attach_or_create_transaction_chat_room(transaction_field, instance, product, owner, other_user):
    ChatRoom = _get_chat_room_model()
    if ChatRoom is None:
        return
    if not product or not owner or not other_user:
        return

    if ChatRoom.objects.filter(**{transaction_field: instance}).exists():
        return

    pre_room = (
        ChatRoom.objects.filter(
            product=product,
            user1=owner,
            user2=other_user,
            rental__isnull=True,
            purchase__isnull=True,
            application__isnull=True,
        )
        .order_by("created_at")
        .first()
    )
    if not pre_room:
        pre_room = (
            ChatRoom.objects.filter(
                product=product,
                user1=other_user,
                user2=owner,
                rental__isnull=True,
                purchase__isnull=True,
                application__isnull=True,
            )
            .order_by("created_at")
            .first()
        )

    if pre_room:
        setattr(pre_room, transaction_field, instance)
        pre_room.save(update_fields=[transaction_field])
        return

    create_kwargs = {transaction_field: instance}
    ChatRoom.objects.create(product=product, user1=owner, user2=other_user, **create_kwargs)


@receiver(post_save, sender=Purchase)
def _create_chat_for_purchase(sender, instance, created, **kwargs):
    if not created:
        return
    product = getattr(instance, "product", None)
    owner = getattr(product, "owner", None) if product else None
    buyer = getattr(instance, "buyer", None)
    if not product or not owner or not buyer or owner.id == buyer.id:
        return
    _attach_or_create_transaction_chat_room(
        "purchase",
        instance,
        product,
        owner,
        buyer,
    )


@receiver(post_save, sender=Rental)
def _create_chat_for_rental(sender, instance, created, **kwargs):
    if not created:
        return
    product = getattr(instance, "product", None)
    owner = getattr(product, "owner", None) if product else None
    renter = getattr(instance, "renter", None)
    if not product or not owner or not renter or owner.id == renter.id:
        return
    _attach_or_create_transaction_chat_room(
        "rental",
        instance,
        product,
        owner,
        renter,
    )


@receiver(post_save, sender=RentalApplication)
def _create_chat_for_application(sender, instance, created, **kwargs):
    if not created:
        return
    product = getattr(instance, "product", None)
    owner = getattr(instance, "owner", None)
    renter = getattr(instance, "renter", None)
    if not product or not owner or not renter or owner.id == renter.id:
        return
    _attach_or_create_transaction_chat_room(
        "application",
        instance,
        product,
        owner,
        renter,
    )


