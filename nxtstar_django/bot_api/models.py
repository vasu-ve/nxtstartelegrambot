"""
Database models for the NxtStar bot.
"""
import uuid
from datetime import timedelta
from django.db import models
from django.utils import timezone
import httpx

class Leader(models.Model):
    """Represents a group leader."""
    id = models.BigAutoField(primary_key=True)
    telegram_username = models.CharField(max_length=255, unique=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    display_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leaders'
        verbose_name = 'Leader'
        verbose_name_plural = 'Leaders'

    def __str__(self):
        return f"{self.display_name} (@{self.telegram_username})"


class Group(models.Model):
    """Represents a Telegram group."""
    id = models.BigAutoField(primary_key=True)
    chat_id = models.BigIntegerField(unique=True)  # REAL telegram group id
    chat_username = models.CharField(max_length=255, null=True, blank=True)  # optional
    chat_title = models.CharField(max_length=255)
    language = models.CharField(
        max_length=10,
        choices=[
            ('pt-br', 'Portuguese (Brazil)'),
            ('fr', 'French'),
            ('en', 'English'),
            ('es', 'Spanish'),
            ('ar', 'Arabic'),
        ]
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'groups'
        verbose_name = 'Group'
        verbose_name_plural = 'Groups'

    def __str__(self):
        return f"{self.chat_title} ({self.language})"


class User(models.Model):
    """Represents a user who interacted with the bot."""
    id = models.BigAutoField(primary_key=True)
    telegram_user_id = models.BigIntegerField(unique=True)
    telegram_username = models.CharField(max_length=255, null=True, blank=True)
    nxtstar_uid = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    language = models.CharField(
        max_length=10,
        choices=[
            ('pt-br', 'Portuguese (Brazil)'),
            ('fr', 'French'),
            ('en', 'English'),
            ('es', 'Spanish'),
            ('ar', 'Arabic'),
        ],
        default='en'
    )
    # ✅ Changed from ForeignKey to ManyToManyField to support joining multiple groups
    joined_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name='members'
    )
    is_verified = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"User {self.telegram_user_id} ({self.nxtstar_uid})"
    
    def has_joined_group(self, group):
        """Check if user has already joined a specific group."""
        return self.joined_groups.filter(id=group.id).exists()


class InviteLink(models.Model):
    """Represents a personal invite link for a user to join a group."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('used', 'Used'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invite_links')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='invite_links')
    invite_link = models.CharField(max_length=500, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'invite_links'
        verbose_name = 'Invite Link'
        verbose_name_plural = 'Invite Links'
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['group', 'status']),
        ]

    def __str__(self):
        uid = self.user.nxtstar_uid or "NoUID"
        return f"Invite {str(self.id)[:8]} - {uid} to {self.group.chat_title}"

    def is_valid(self):
        """Check if the invite link is still valid."""
        return (
            self.status == 'pending' and
            timezone.now() < self.expires_at
        )

    @classmethod
    def create_invite(cls, user, group, ttl_minutes=15):
        from django.conf import settings
        import logging        
        logger = logging.getLogger(__name__)

        # Calculate expiration time with proper timezone handling
        now_utc = timezone.now()
        expires_at = now_utc + timedelta(minutes=ttl_minutes)
        expire_timestamp = int(expires_at.timestamp())
        current_timestamp = int(now_utc.timestamp())
        
        # Validate that expire_date is in the future
        time_until_expiry = expire_timestamp - current_timestamp
        if time_until_expiry <= 0:
            logger.error(f"[INVITE_ERROR] Expire timestamp is in the past! Delta: {time_until_expiry}s")
            raise Exception("Calculated expiration time is in the past")

        BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"

        # Prepare payload for Telegram API
        payload = {
            "chat_id": group.chat_id,
            "expire_date": expire_timestamp,
            # "member_limit": 1,
        }

        # Log the invite creation attempt with detailed info
        logger.info("="*80)
        logger.info("[INVITE_CREATE_START] Creating new invite link")
        logger.info(f"  User ID: {user.id} (Telegram ID: {user.telegram_user_id})")
        logger.info(f"  Group ID: {group.id} (Chat ID: {group.chat_id})")
        logger.info(f"  TTL: {ttl_minutes} minutes")
        logger.info("")
        logger.info("[TIMESTAMP_INFO]")
        logger.info(f"  Current time (UTC): {now_utc.isoformat()}")
        logger.info(f"  Current timestamp: {current_timestamp}")
        logger.info(f"  Expires at (UTC): {expires_at.isoformat()}")
        logger.info(f"  Expire timestamp: {expire_timestamp}")
        logger.info(f"  Seconds until expiry: {time_until_expiry}")
        logger.info("")
        logger.info(f"[TELEGRAM_PAYLOAD] {payload}")

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response_data = response.json()

            logger.info(f"[TELEGRAM_RESPONSE] HTTP Status: {response.status_code}")
            logger.info(f"[TELEGRAM_RESPONSE] OK: {response_data.get('ok')}")
            logger.info(f"[TELEGRAM_RESPONSE] Full response: {response_data}")

            if not response_data.get("ok"):
                error_msg = response_data.get('description', 'Unknown error')
                error_code = response_data.get('error_code', 'N/A')
                logger.error(f"[TELEGRAM_ERROR] Code: {error_code}, Message: {error_msg}")
                raise Exception(f"Telegram API error ({error_code}): {error_msg}")

            invite_url = response_data["result"]["invite_link"]
            logger.info(f"[INVITE_LINK_CREATED] {invite_url}")

            # Create database record
            invite_link_obj = cls.objects.create(
                user=user,
                group=group,
                invite_link=invite_url,
                expires_at=expires_at
            )
            
            logger.info(f"[INVITE_DB_SAVED] Invite ID: {invite_link_obj.id}")
            logger.info(f"  DB expires_at: {invite_link_obj.expires_at.isoformat()}")
            logger.info("="*80)

            return invite_link_obj
            
        except Exception as e:
            logger.error("="*80)
            logger.error(f"[INVITE_EXCEPTION] {type(e).__name__}: {str(e)}", exc_info=True)
            logger.error("="*80)
            raise

    def revoke(self):
        """Revoke this invite link on Telegram and mark it as expired in the DB.

        After revocation, the link URL can no longer be used to join the chat,
        even by users who previously joined through it and then left.
        """
        from django.conf import settings
        import logging
        logger = logging.getLogger(__name__)

        BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/revokeChatInviteLink"
        payload = {"chat_id": self.group.chat_id, "invite_link": self.invite_link}

        logger.info(f"[INVITE_REVOKE] Revoking invite {self.id} for chat {self.group.chat_id}")

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response_data = response.json()

            if not response_data.get("ok"):
                # INVITE_LINK_ALREADY_REVOKED / link not found is benign — still flip DB state.
                logger.warning(
                    f"[INVITE_REVOKE] Telegram refused revoke for {self.id}: {response_data}"
                )
            else:
                logger.info(f"[INVITE_REVOKE] ✅ Telegram revoked {self.id}")
        except Exception as e:
            logger.error(f"[INVITE_REVOKE] Exception revoking {self.id}: {e}", exc_info=True)

        self.status = 'expired'
        self.save(update_fields=['status'])


class AuditLog(models.Model):
    """Audit log for tracking user actions and system events."""
    EVENT_CHOICES = [
        ('start', 'Start'),
        ('language_selected', 'Language Selected'),
        ('uid_check', 'UID Check'),
        ('user_verified', 'User Verified'),
        ('invite_created', 'Invite Created'),
        ('invite_used', 'Invite Used'),
        ('invite_declined', 'Invite Declined'),
        ('join_approved', 'Join Approved'),
        ('join_declined', 'Join Declined'),
        ('user_banned', 'User Banned'),
        ('group_left', 'Group Left'),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_log'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.user} - {self.created_at}"
