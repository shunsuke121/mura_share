from django import forms
from marketplace.models import Product, ProductImage, Rental

# ★ 複数ファイル対応ウィジェット
class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["title", "description", "category", "price_per_day", "price_buy"]

# ★ 画像は複数選択できるようにする
class ProductImageForm(forms.ModelForm):
    image = forms.ImageField(widget=MultiFileInput(), required=False)

    class Meta:
        model = ProductImage
        fields = ["image"]

class RentalForm(forms.ModelForm):
    class Meta:
        model = Rental
        fields = ["start_date", "end_date"]
