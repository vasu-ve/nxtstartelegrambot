"""
Django admin configuration for bot_api app.
"""
from django.contrib import admin
from .models import Leader, Group, User, InviteLink, AuditLog


@admin.register(Leader)
class LeaderAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'telegram_username', 'telegram_user_id', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('display_name', 'telegram_username')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('display_name', 'telegram_username', 'telegram_user_id')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('chat_title', 'leader', 'language', 'is_active', 'created_at')
    list_filter = ('leader', 'language', 'is_active', 'created_at')
    search_fields = ('chat_title', 'chat_id')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Group Information', {
            'fields': ('leader', 'chat_title', 'chat_id', 'language')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('telegram_user_id', 'nxtstar_uid', 'telegram_username', 'language', 'get_joined_groups', 'is_verified', 'is_banned', 'created_at')
    list_filter = ('language', 'is_verified', 'is_banned', 'created_at')
    search_fields = ('telegram_user_id', 'nxtstar_uid', 'telegram_username')
    readonly_fields = ('created_at', 'updated_at')
    filter_horizontal = ('joined_groups',)  # ✅ ADD THIS — gives a nice dual-panel widget
    fieldsets = (
        ('Telegram Information', {
            'fields': ('telegram_user_id', 'telegram_username')
        }),
        ('NxtStar Information', {
            'fields': ('nxtstar_uid', 'language', 'joined_groups')
        }),
        ('Status', {
            'fields': ('is_verified', 'is_banned')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    @admin.display(description='Joined Groups')
    def get_joined_groups(self, obj):
        groups = obj.joined_groups.all()
        if not groups:
            return 'None'
        return ', '.join([f"{g.chat_title} ({g.language})" for g in groups])


@admin.register(InviteLink)
class InviteLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'group', 'status', 'created_at', 'expires_at', 'is_valid')
    list_filter = ('status', 'group', 'created_at')
    search_fields = ('user__nxtstar_uid', 'user__telegram_user_id')
    readonly_fields = ('id', 'created_at', 'used_at', 'declined_at')
    fieldsets = (
        ('Invite Information', {
            'fields': ('id', 'user', 'group', 'invite_link')
        }),
        ('Status', {
            'fields': ('status', 'expires_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'used_at', 'declined_at'),
            'classes': ('collapse',)
        }),
    )

    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True
    is_valid.short_description = 'Valid'


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'user', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('user__nxtstar_uid', 'user__telegram_user_id', 'description')
    readonly_fields = ('id', 'created_at', 'user', 'event_type', 'description', 'metadata')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
