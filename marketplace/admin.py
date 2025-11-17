from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import RentalApplication

@admin.register(RentalApplication)
class RentalApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "renter", "owner", "order_type", "status", "created_at")
    list_filter  = ("order_type", "status")
    search_fields = ("product__title", "renter__username", "owner__username")
