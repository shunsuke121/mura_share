from django.shortcuts import render

# Create your views here.
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
