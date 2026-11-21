"""
The assistant's chat tables. Owned by Ola: the platform created this first version,
after that Ola changes them (and creates their migrations). Described in docs/interfaces.md.
"""

from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    """One chat, like a conversation in any chat app."""

    TITLE_LENGTH = 80

    title = models.CharField(max_length=TITLE_LENGTH, blank=True, help_text="The start of the first message.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="[UTC]")
    updated_at = models.DateTimeField(auto_now=True, help_text="[UTC] Moves forward with every new message.")

    class Meta:
        ordering = ["-updated_at"]

    @classmethod
    def title_from(cls, first_message: str) -> str:
        """A title from the first message: its first line, shortened to TITLE_LENGTH characters."""
        first_line = first_message.strip().splitlines()[0] if first_message.strip() else ""
        if len(first_line) <= cls.TITLE_LENGTH:
            return first_line
        return first_line[: cls.TITLE_LENGTH - 1].rstrip() + "…"

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class Message(models.Model):
    """One message in a conversation, from the farmer or the assistant."""

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField(help_text="Markdown for assistant messages, plain text for user messages.")
    citations = models.JSONField(
        default=list, blank=True, help_text="List of citations (format in docs/interfaces.md). Empty for user messages."
    )
    field = models.ForeignKey(
        "core.Field",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The field selected on the map when the message was sent (user messages).",
    )
    focus_field = models.ForeignKey(
        "core.Field",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The field the answer points the map at (assistant messages).",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="[UTC]")

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep the conversation's updated_at current, so the newest conversation is listed first.
        Conversation.objects.filter(pk=self.conversation_id).update(updated_at=timezone.now())

    def __str__(self) -> str:
        return f"{self.role}: {self.text[:60]}"
