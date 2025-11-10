from rest_framework import serializers
from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id","kind","body","read_at","created_at","user"]
        read_only_fields = ["user","created_at"]
