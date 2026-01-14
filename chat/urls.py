from django.urls import path
from .views import (
    StartChatView,
    StartPurchaseChatView,
    StartRentalChatView,
    StartRentalAppChatView,
    ChatDetailView,
    ChatListView,
    send_message,
)

app_name = "chat"

urlpatterns = [
    path("", ChatListView.as_view(), name="chat_list"),
    path("start/<int:product_id>/", StartChatView.as_view(), name="start_chat"),
    path("start/purchase/<int:purchase_id>/", StartPurchaseChatView.as_view(), name="start_purchase_chat"),
    path("start/rental/<int:rental_id>/", StartRentalChatView.as_view(), name="start_rental_chat"),
    path("start/application/<int:app_id>/", StartRentalAppChatView.as_view(), name="start_rental_app_chat"),
    path("<int:room_id>/", ChatDetailView.as_view(), name="chat_detail"),
    path("<int:room_id>/send/", send_message, name="send_message"),
]
