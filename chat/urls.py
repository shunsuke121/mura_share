from django.urls import path
from .views import StartChatView, ChatDetailView, ChatListView

app_name = "chat"

urlpatterns = [
    path("", ChatListView.as_view(), name="chat_list"),
    path("start-chat/<int:product_id>/", StartChatView.as_view(), name="start_chat"),
    path("<int:room_id>/", ChatDetailView.as_view(), name="chat_detail"),
]
