from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Reports whether the platform is up and can reach the database."""

    @extend_schema(
        responses=inline_serializer(
            name="Health",
            fields={"status": serializers.CharField(), "database": serializers.BooleanField()},
        )
    )
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database_ok = True
        except Exception:
            database_ok = False
        return Response(
            {"status": "ok" if database_ok else "degraded", "database": database_ok},
            status=200 if database_ok else 503,
        )
