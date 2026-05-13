"""
API views for the bot backend.
"""
import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.db.models import Count
from .models import User, Group, Leader, InviteLink, AuditLog


@csrf_exempt
@require_http_methods(["POST"])
def create_or_get_user(request):
    """Create or get a user by Telegram ID."""
    try:
        data = json.loads(request.body)
        telegram_user_id = data.get('telegram_user_id')
        telegram_username = data.get('telegram_username')
        language = data.get('language', 'en')

        if not telegram_user_id:
            return JsonResponse({'error': 'telegram_user_id is required'}, status=400)

        user, created = User.objects.update_or_create(
            telegram_user_id=telegram_user_id,
            defaults={
                'telegram_username': telegram_username,
                'language': language,
            }
        )

        # Log event
        AuditLog.objects.create(
            user=user,
            event_type='start' if created else 'language_selected',
            description=f"User {'created' if created else 'updated'} with language {language}"
        )

        return JsonResponse({
            'success': True,
            'user_id': user.id,
            'telegram_user_id': user.telegram_user_id,
            'language': user.language,
            'is_verified': user.is_verified,
            'is_banned': user.is_banned,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def verify_user(request):
    """Verify a user with NxtStar UID."""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        nxtstar_uid = data.get('nxtstar_uid')

        if not user_id or not nxtstar_uid:
            return JsonResponse({'error': 'user_id and nxtstar_uid are required'}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        # Check if user is already banned
        if user.is_banned:
            AuditLog.objects.create(
                user=user,
                event_type='uid_check',
                description=f"User is banned"
            )
            return JsonResponse({
                'success': False,
                'message': 'user_banned',
                'reason': 'Your account is banned',
            })

        # For now, allow all users (no API check)
        # In the future, replace this with actual API call to nxtstar_api
        user.nxtstar_uid = nxtstar_uid
        user.is_verified = True
        user.save()

        AuditLog.objects.create(
            user=user,
            event_type='user_verified',
            description=f"User verified with UID {nxtstar_uid}"
        )

        return JsonResponse({
            'success': True,
            'message': 'user_verified',
            'user_id': user.id,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def generate_invite_link(request):
    """Generate an invite link for a user to join a group."""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        language = data.get('language', 'en')

        if not user_id:
            return JsonResponse({'error': 'user_id is required'}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        if user.is_banned:
            AuditLog.objects.create(
                user=user,
                event_type='invite_created',
                description="Invite creation attempted but user is banned"
            )
            return JsonResponse({
                'success': False,
                'message': 'user_banned',
                'reason': 'Your account is banned',
            })

        # ✅ REMOVED: joined_group single-group check — multi-join is now supported

        # Find available group for this language
        groups = Group.objects.filter(
            language=language,
            is_active=True,
            leader__is_active=True
        )

        if not groups.exists():
            AuditLog.objects.create(
                user=user,
                event_type='invite_created',
                description=f"No available group for language {language}"
            )
            return JsonResponse({
                'success': False,
                'message': 'no_group_available',
                'reason': 'No group available for your language',
            })

        # ✅ Count via joined_groups M2M (was: Count('members') on FK)
        group = groups.annotate(member_count=Count('members')).order_by('member_count').first()

        with transaction.atomic():
            invite_link = InviteLink.create_invite(user, group)

        AuditLog.objects.create(
            user=user,
            event_type='invite_created',
            description=f"Invite created for group {group.chat_title}",
            metadata={'group_id': group.id, 'invite_id': str(invite_link.id)}
        )

        return JsonResponse({
            'success': True,
            'message': 'invite_generated',
            'invite_link': invite_link.invite_link,
            'expires_in_minutes': 15,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def get_invite_link(request):
    """Get invite link details."""
    try:
        invite_id = request.GET.get('invite_id')

        if not invite_id:
            return JsonResponse({'error': 'invite_id is required'}, status=400)

        try:
            invite = InviteLink.objects.get(id=invite_id)
        except InviteLink.DoesNotExist:
            return JsonResponse({'error': 'Invite not found'}, status=404)

        return JsonResponse({
            'success': True,
            'invite_id': str(invite.id),
            'user_id': invite.user.id,
            'group_id': invite.group.id,
            'status': invite.status,
            'is_valid': invite.is_valid(),
            'created_at': invite.created_at.isoformat(),
            'expires_at': invite.expires_at.isoformat(),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def mark_invite_used(request):
    """Mark an invite link as used."""
    try:
        data = json.loads(request.body)
        invite_id = data.get('invite_id')

        if not invite_id:
            return JsonResponse({'error': 'invite_id is required'}, status=400)

        try:
            invite = InviteLink.objects.get(id=invite_id)
        except InviteLink.DoesNotExist:
            return JsonResponse({'error': 'Invite not found'}, status=404)

        if not invite.is_valid():
            return JsonResponse({
                'success': False,
                'message': 'invite_invalid',
                'reason': 'Invite link is no longer valid',
            })

        with transaction.atomic():
            invite.status = 'used'
            invite.used_at = timezone.now()
            invite.save()

            invite.user.joined_groups.add(invite.group)

        AuditLog.objects.create(
            user=invite.user,
            event_type='invite_used',
            description=f"User joined group {invite.group.chat_title}",
            metadata={'group_id': invite.group.id}
        )

        return JsonResponse({
            'success': True,
            'message': 'invite_used',
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def get_available_leaders(request):
    """Get all active leaders for the bot."""
    try:
        leaders = Leader.objects.filter(is_active=True).values(
            'id',
            'telegram_user_id',
            'telegram_username',
            'display_name'
        )

        if not leaders.exists():
            return JsonResponse({
                'success': False,
                'message': 'no_leaders_available',
                'reason': 'No leaders are currently available',
            })

        return JsonResponse({
            'success': True,
            'message': 'leaders_fetched',
            'leaders': list(leaders),
            'count': leaders.count(),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def select_leader_and_generate_link(request):
    """Select a leader and generate an invite link for a user."""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        leader_id = data.get('leader_id')
        language = data.get('language', 'en')

        if not user_id or not leader_id:
            return JsonResponse({'error': 'user_id and leader_id are required'}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        try:
            leader = Leader.objects.get(id=leader_id, is_active=True)
        except Leader.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'leader_not_found',
                'reason': 'Selected leader is not available',
            })

        # Check if user is banned
        if user.is_banned:
            AuditLog.objects.create(
                user=user,
                event_type='leader_selected',
                description=f"Leader selection attempted but user is banned"
            )
            return JsonResponse({
                'success': False,
                'message': 'user_banned',
                'reason': 'Your account is banned',
            })

        # Find group for this leader and language
        group = Group.objects.filter(
            leader=leader,
            language=language,
            is_active=True
        ).first()

        if not group:
            return JsonResponse({
                'success': False,
                'message': 'group_not_configured',
                'reason': 'Group not configured for this leader/language',
            })

        # ✅ Check if user already joined THIS specific group (allow joining other groups)
        already_joined_this_group = InviteLink.objects.filter(
            user=user,
            group=group,
            status='used'
        ).exists()

        if already_joined_this_group:
            AuditLog.objects.create(
                user=user,
                event_type='leader_selected',
                description=f"User already joined group {group.chat_title}"
            )
            return JsonResponse({
                'success': False,
                'message': 'already_joined_this_group',
                'reason': f'You have already joined this group',
            })

        # Create invite link
        with transaction.atomic():
            invite_link = InviteLink.create_invite(user, group)

        AuditLog.objects.create(
            user=user,
            event_type='leader_selected',
            description=f"Leader selected: {leader.display_name}",
            metadata={
                'leader_id': leader.id,
                'group_id': group.id,
                'invite_id': str(invite_link.id)
            }
        )

        return JsonResponse({
            'success': True,
            'message': 'invite_generated',
            'leader_id': leader.id,
            'leader_name': leader.display_name,
            'group_id': group.id,
            'invite_link': invite_link.invite_link,
            'invite_id': str(invite_link.id),
            'expires_in_minutes': 15,
        })
    except Exception as e:
        import traceback
        print("ERROR:::::::::::::::::::::::::::::::::", str(e))
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)
    
@csrf_exempt
@require_http_methods(["POST"])
def validate_join(request):
    """Validate and process user joining a group via invite link."""
    import logging
    from django.utils import timezone as tz
    
    logger = logging.getLogger(__name__)
    
    try:
        data = json.loads(request.body)
        telegram_user_id = data.get("telegram_user_id")
        chat_id = int(data.get("chat_id"))

        logger.info(f"[VALIDATE_JOIN] Request received")
        logger.info(f"  Telegram User ID: {telegram_user_id}")
        logger.info(f"  Chat ID: {chat_id}")

        # Find the user
        user = User.objects.filter(telegram_user_id=telegram_user_id).first()

        if not user:
            logger.warning(f"[VALIDATE_JOIN] User not found: TG ID {telegram_user_id}")
            return JsonResponse({"success": False, "reason": "user_not_found"})

        logger.info(f"[VALIDATE_JOIN] User found: {user.id}")

        # Find the pending invite for this user and chat
        invite = InviteLink.objects.filter(
            user=user,
            status='pending',
            group__chat_id=chat_id
        ).first()

        if not invite:
            logger.warning(f"[VALIDATE_JOIN] No pending invite found for user {user.id} and chat {chat_id}")
            return JsonResponse({"success": False, "reason": "invite_not_found"})

        logger.info(f"[VALIDATE_JOIN] Invite found: {invite.id}")
        logger.info(f"  Invite Link: {invite.invite_link}")
        logger.info(f"  Status: {invite.status}")
        logger.info(f"  Created: {invite.created_at.isoformat()}")
        logger.info(f"  Expires: {invite.expires_at.isoformat()}")

        # Check if invite is still valid
        current_time = tz.now()
        is_expired = current_time >= invite.expires_at
        
        logger.info(f"[VALIDATE_JOIN] Time check:")
        logger.info(f"  Current time: {current_time.isoformat()}")
        logger.info(f"  Expires at: {invite.expires_at.isoformat()}")
        logger.info(f"  Is expired: {is_expired}")
        logger.info(f"  Time remaining: {(invite.expires_at - current_time).total_seconds()} seconds")

        if not invite.is_valid():
            logger.error(f"[VALIDATE_JOIN] Invite is NOT valid!")
            logger.error(f"  Status: {invite.status} (expected 'pending')")
            logger.error(f"  Expired: {is_expired}")
            return JsonResponse({
                "success": False,
                "reason": "invite_expired_or_invalid",
                "details": {
                    "status": invite.status,
                    "is_expired": is_expired,
                    "current_time": current_time.isoformat(),
                    "expires_at": invite.expires_at.isoformat()
                }
            })

        # ✅ Mark invite as used
        logger.info(f"[VALIDATE_JOIN] Marking invite as USED")
        invite.status = 'used'
        invite.used_at = tz.now()
        invite.save()

        # Associate user with group
        user.joined_groups.add(invite.group)

        # Log the successful join
        AuditLog.objects.create(
            user=user,
            event_type='invite_used',
            description=f"User joined group via invite link",
            metadata={'invite_id': str(invite.id), 'chat_id': chat_id}
        )

        logger.info(f"[VALIDATE_JOIN] ✅ SUCCESS! User {user.id} joined group {invite.group.id}")
        
        return JsonResponse({
            "success": True,
            "message": "User joined successfully",
            "user_id": user.id,
            "group_id": invite.group.id
        })
    except Exception as e:
        logger.error(f"[VALIDATE_JOIN] Exception occurred: {str(e)}", exc_info=True)
        return JsonResponse({"success": False, "reason": "internal_error", "error": str(e)}, status=500)

    
@csrf_exempt
@require_http_methods(["GET"])
def debug_invites(request):
    """Debug endpoint - shows all recent invites."""
    import logging
    from django.utils import timezone as tz
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("="*80)
        logger.info("[DEBUG_INVITES] Listing all invites")
        
        invites = InviteLink.objects.all().order_by('-created_at')[:10]
        
        invite_list = []
        for invite in invites:
            current_time = tz.now()
            is_expired = current_time >= invite.expires_at
            time_remaining = (invite.expires_at - current_time).total_seconds()
            
            invite_data = {
                "id": str(invite.id),
                "user_id": invite.user.id,
                "user_telegram_id": invite.user.telegram_user_id,
                "group_id": invite.group.id,
                "group_chat_id": invite.group.chat_id,
                "group_title": invite.group.chat_title,
                "status": invite.status,
                "created_at": invite.created_at.isoformat(),
                "expires_at": invite.expires_at.isoformat(),
                "is_expired": is_expired,
                "time_remaining_seconds": int(time_remaining),
                "invite_link": invite.invite_link,
            }
            invite_list.append(invite_data)
            
            logger.info(f"  Invite {invite.id}:")
            logger.info(f"    User: {invite.user.telegram_user_id}")
            logger.info(f"    Group: {invite.group.chat_title}")
            logger.info(f"    Status: {invite.status}")
            logger.info(f"    Expired: {is_expired} (remaining: {time_remaining}s)")
        
        logger.info("="*80)
        
        return JsonResponse({
            "success": True,
            "current_time_utc": current_time.isoformat(),
            "invites_count": len(invite_list),
            "invites": invite_list,
        })
    except Exception as e:
        logger.error(f"[DEBUG_INVITES] Error: {str(e)}", exc_info=True)
        return JsonResponse({"success": False, "error": str(e)}, status=500)
