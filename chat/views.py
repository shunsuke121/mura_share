import requests
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import models

# Create your views here.
from marketplace.models import Product, Purchase, Rental, RentalApplication
from rest_framework import viewsets, permissions, decorators, response
from .models import ChatRoom, ChatMessage
from .serializers import ChatRoomSerializer, ChatMessageSerializer


def _ensure_room_member(user, room):
    if user.id not in (room.user1_id, room.user2_id):
        raise PermissionDenied


class ChatRoomViewSet(viewsets.ModelViewSet):
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(
            models.Q(user1=user) | models.Q(user2=user)
        )

class ChatMessageViewSet(viewsets.ModelViewSet):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = ChatMessage.objects.select_related("room","user")
        room_id = self.kwargs.get("room_pk")
        if room_id:
            qs = qs.filter(room_id=room_id)
        return qs.filter(models.Q(room__user1=user) | models.Q(room__user2=user))

    def perform_create(self, serializer):
        room_id = self.kwargs.get("room_pk") or self.request.data.get("room")
        room = get_object_or_404(ChatRoom, id=room_id)
        _ensure_room_member(self.request.user, room)
        serializer.save(room=room, user=self.request.user)

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
        seller = product.owner  # owner

        if user == seller:
            return redirect("frontend:product_detail", pk=product.id)

        if getattr(product, "is_sold_out", False):
            messages.warning(request, "売り切れとなっています。")
            return redirect("frontend:product_detail", pk=product.id)

        purchase = (
            Purchase.objects
            .filter(product=product)
            .filter(models.Q(buyer=user) | models.Q(product__owner=user))
            .order_by("-created_at")
            .first()
        )
        if purchase:
            return redirect("chat:start_purchase_chat", purchase_id=purchase.id)

        app = (
            RentalApplication.objects
            .filter(product=product)
            .filter(models.Q(renter=user) | models.Q(owner=user))
            .order_by("-created_at")
            .first()
        )
        if app:
            return redirect("chat:start_rental_app_chat", app_id=app.id)

        rental = (
            Rental.objects
            .filter(product=product)
            .filter(models.Q(renter=user) | models.Q(product__owner=user))
            .order_by("-created_at")
            .first()
        )
        if rental:
            return redirect("chat:start_rental_chat", rental_id=rental.id)

        room = (
            ChatRoom.objects.filter(
                product=product,
                user1=seller,
                user2=user,
                rental__isnull=True,
                purchase__isnull=True,
                application__isnull=True,
            ).first()
            or ChatRoom.objects.filter(
                product=product,
                user1=user,
                user2=seller,
                rental__isnull=True,
                purchase__isnull=True,
                application__isnull=True,
            ).first()
        )

        if not room:
            room = ChatRoom.objects.create(product=product, user1=seller, user2=user)

        return redirect("chat:chat_detail", room_id=room.id)

class StartPurchaseChatView(LoginRequiredMixin, View):
    def get(self, request, purchase_id):
        purchase = get_object_or_404(
            Purchase.objects.select_related("product", "buyer", "product__owner"),
            id=purchase_id,
        )
        if request.user.id not in (purchase.buyer_id, purchase.product.owner_id):
            raise PermissionDenied
        room = ChatRoom.objects.filter(purchase=purchase).first()
        if not room:
            room = ChatRoom.objects.create(
                product=purchase.product,
                user1=purchase.product.owner,
                user2=purchase.buyer,
                purchase=purchase,
            )
        return redirect("chat:chat_detail", room_id=room.id)


class StartRentalChatView(LoginRequiredMixin, View):
    def get(self, request, rental_id):
        rental = get_object_or_404(
            Rental.objects.select_related("product", "renter", "product__owner"),
            id=rental_id,
        )
        if request.user.id not in (rental.renter_id, rental.product.owner_id):
            raise PermissionDenied
        room = ChatRoom.objects.filter(rental=rental).first()
        if not room:
            room = ChatRoom.objects.create(
                product=rental.product,
                user1=rental.product.owner,
                user2=rental.renter,
                rental=rental,
            )
        return redirect("chat:chat_detail", room_id=room.id)


class StartRentalAppChatView(LoginRequiredMixin, View):
    def get(self, request, app_id):
        app = get_object_or_404(
            RentalApplication.objects.select_related("product", "owner", "renter"),
            id=app_id,
        )
        if request.user.id not in (app.owner_id, app.renter_id):
            raise PermissionDenied
        room = ChatRoom.objects.filter(application=app).first()
        if not room:
            room = ChatRoom.objects.create(
                product=app.product,
                user1=app.owner,
                user2=app.renter,
                application=app,
            )
        return redirect("chat:chat_detail", room_id=room.id)


class ChatDetailView(LoginRequiredMixin, View):
    def get(self, request, room_id):
        room = get_object_or_404(
            ChatRoom.objects.select_related(
                "product",
                "user1",
                "user2",
                "purchase",
                "rental",
                "application",
                "user1__profile",
                "user2__profile",
            ),
            id=room_id,
        )
        _ensure_room_member(request.user, room)

        messages = room.messages.order_by("created_at")
        room.messages.filter(is_read=False).exclude(user=request.user).update(is_read=True)

        other = room.user1 if room.user1_id != request.user.id else room.user2
        other_name = getattr(getattr(other, "profile", None), "display_name", "") or other.username

        transaction_info = None
        if room.purchase_id and room.purchase:
            transaction_info = {
                "label": "購入",
                "id": room.purchase_id,
                "status": room.purchase.get_status_display() if hasattr(room.purchase, "get_status_display") else room.purchase.status,
                "tracking": [
                    ("追跡番号", room.purchase.tracking_number),
                    ("返品追跡番号", room.purchase.return_tracking_number),
                ],
            }
        elif room.rental_id and room.rental:
            transaction_info = {
                "label": "レンタル",
                "id": room.rental_id,
                "status": room.rental.get_status_display() if hasattr(room.rental, "get_status_display") else room.rental.status,
                "tracking": [
                    ("追跡番号", room.rental.tracking_number_to_renter),
                    ("返却追跡番号", room.rental.tracking_number_return),
                ],
            }
        elif room.application_id and room.application:
            order_label = "レンタル" if room.application.order_type == RentalApplication.OrderType.RENTAL else "購入"
            transaction_info = {
                "label": order_label,
                "id": room.application_id,
                "status": room.application.get_status_display() if hasattr(room.application, "get_status_display") else room.application.status,
                "tracking": [
                    ("追跡番号", room.application.tracking_number),
                    ("返却追跡番号", room.application.return_tracking_number),
                ],
            }

        return render(request, "frontend/messages/messages_detail.html", {
            "room": room,
            "messages": messages,
            "counterparty_name": other_name,
            "transaction_info": transaction_info,
        })

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id)
        _ensure_room_member(request.user, room)
        body = request.POST.get("body")

        if body:
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                body=body
            )

        return redirect("chat:chat_detail", room_id=room_id)

@login_required
def send_message(request, room_id):
    room = get_object_or_404(ChatRoom, id=room_id)
    _ensure_room_member(request.user, room)

    if request.method == "POST":
        body = request.POST.get("body")
        if body:
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                body=body
            )

    return redirect("chat:chat_detail", room_id=room.id)
