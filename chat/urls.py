from django.urls import path
from .views import StartChatView, ChatDetailView, ChatListView, send_message

app_name = "chat"

urlpatterns = [
    path("", ChatListView.as_view(), name="chat_list"),
    path("start/<int:product_id>/", StartChatView.as_view(), name="start_chat"),
    path("<int:room_id>/", ChatDetailView.as_view(), name="chat_detail"),
    path("<int:room_id>/send/", send_message, name="send_message"),
]
