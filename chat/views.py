import requests
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView
from django.conf import settings

# Create your views here.
from marketplace.models import Product
from rest_framework import viewsets, permissions, decorators, response
from .models import ChatRoom, ChatMessage
from .serializers import ChatRoomSerializer, ChatMessageSerializer

class ChatRoomViewSet(viewsets.ModelViewSet):
    queryset = ChatRoom.objects.all()
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

class ChatMessageViewSet(viewsets.ModelViewSet):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ChatMessage.objects.select_related("room","user")
        room_id = self.kwargs.get("room_pk")
        return qs.filter(room_id=room_id) if room_id else qs

    def perform_create(self, serializer):
        room_id = self.kwargs.get("room_pk") or self.request.data.get("room")
        serializer.save(room_id=room_id, user=self.request.user)

    @decorators.action(detail=True, methods=["post"])
    def mark_read(self, request, room_pk=None, pk=None):
        msg = self.get_object()
        msg.is_read = True
        msg.save()
        return response.Response(self.get_serializer(msg).data)

class ChatListView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user

        rooms = ChatRoom.objects.filter(
            models.Q(user1=user) | models.Q(user2=user)
        ).order_by('-created_at')

        room_data = []

        for room in rooms:
            other = room.user1 if room.user1 != user else room.user2
            last_msg = room.messages.order_by('-created_at').first()
            unread = room.messages.filter(is_read=False).exclude(user=user).count()

            room_data.append({
                "room": room,
                "other": other,
                "last_msg": last_msg,
                "unread": unread,
            })

        return render(request, "chat/chat_list.html", {"rooms": room_data})


class StartChatView(LoginRequiredMixin, View):
    def get(self, request, product_id):
        product = get_object_or_404(Product, id=product_id)
        user = request.user
        seller = product.owner  # ← owner に統一

        if user == seller:
            return redirect("frontend:product_detail", pk=product.id)

        # 既存ルーム確認
        room = (
            ChatRoom.objects.filter(product=product, user1=user, user2=seller).first()
            or ChatRoom.objects.filter(product=product, user1=seller, user2=user).first()
        )

        if not room:
            room = ChatRoom.objects.create(product=product, user1=user, user2=seller)

        return redirect("chat:chat_detail", room_id=room.id)


class ChatDetailView(LoginRequiredMixin, View):
    def get(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id)

        messages = room.messages.order_by("created_at")
        room.messages.filter(is_read=False).exclude(user=request.user).update(is_read=True)

        return render(request, "messages/messages_detail.html", {
            "room": room,
            "messages": messages
        })

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id)
        body = request.POST.get("body")

        if body:
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                body=body
            )

        return redirect("chat:chat_detail", room_id=room_id)


class ChatDetailView(DetailView):
    model = ChatRoom
    template_name = "frontend/messages/messages_detail.html"   # ← ここ！
    context_object_name = "room"
    pk_url_kwarg = "room_id"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["messages"] = ChatMessage.objects.filter(room=self.object).select_related("user")
        return context
    
class SendMessageView(View):
    def post(self, request, room_id):
        body = request.POST.get("body")

        # ログインセッションでAPI呼び出す
        url = f"{settings.BASE_URL}/api/v1/rooms/{room_id}/messages/"
        cookies = request.COOKIES  # Djangoセッションを渡す

        requests.post(url, data={"body": body}, cookies=cookies)

        return redirect("chat:chat_detail", room_id=room_id)