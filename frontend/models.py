# frontend/models.py
from django.db import models
from django.conf import settings
 
class ContactInquiry(models.Model):
    TYPE_CHOICES = [
        ("general", "一般"),
        ("support", "サポート"),
        ("sales", "導入・見積もり"),
        ("other", "その他"),
    ]
    # フォームのname属性に合わせて定義
    name = models.CharField(max_length=100)
    company = models.CharField(max_length=200, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="general")
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    # 添付
    attachment = models.FileField(upload_to="contact/%Y/%m/%d", blank=True, null=True)
    # 同意フラグ
    consent = models.BooleanField(default=False)
    # ハニーポット
    website = models.CharField(max_length=100, blank=True)
    # 任意: ログイン中なら紐付け
    user = models.ForeignKey(getattr(settings, "AUTH_USER_MODEL", "auth.User"),
                             on_delete=models.SET_NULL, null=True, blank=True)
    # 運用用
    status = models.CharField(max_length=20, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
 
    def __str__(self):
        return f"[{self.get_type_display()}] {self.subject or self.message[:20]}"