import os
import httpx
import logging

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ChatJoinRequestHandler, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "REPLACE_WITH_YOUR_TOKEN"

# Django API configuration
DJANGO_API_BASE_URL = os.getenv("DJANGO_API_BASE_URL", "http://localhost:8000/api")

# NxtStar Payment Status API configuration
NXTSTAR_API_URL = os.getenv("NXTSTAR_API_URL")
NXTSTAR_API_KEY = os.getenv("NXTSTAR_API_KEY")

# HTTP client
client = httpx.AsyncClient(timeout=10.0)


async def create_or_get_user(telegram_user_id, telegram_username, language):
    """Create or get user from Django backend."""
    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/users/create/",
            json={
                "telegram_user_id": telegram_user_id,
                "telegram_username": telegram_username,
                "language": language,
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return None


async def verify_user(user_id, nxtstar_uid):
    """Verify user with NxtStar UID."""
    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/users/verify/",
            json={
                "user_id": user_id,
                "nxtstar_uid": nxtstar_uid,
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error verifying user: {e}")
        return None


async def generate_invite_link(user_id, language):
    """Generate invite link for user."""
    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/invites/generate/",
            json={
                "user_id": user_id,
                "language": language,
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error generating invite link: {e}")
        return None


async def check_payment_status(uid):
    """Check payment status from NxtStar API.
    
    API Endpoint: POST https://api.nxt-star.com/api/bot/user-status
    Payload: {"customer_id": "<uid>"}
    
    Possible responses:
    1. User found with deposit: {"success": true, "user_found": true, "data": [{...}]}
    2. User not found: {"success": true, "user_found": false, "message": "User not found"}
    3. API error: {"success": false, "user_found": false, "message": "..."}
    """
    try:
        headers = {
            "X-API-Key": NXTSTAR_API_KEY,
            "Content-Type": "application/json",
        }
        
        # Use customer_id as the parameter name (not uid)
        payload = {"customer_id": uid}
        
        logger.info(f"[CHECK_PAYMENT_STATUS] Calling API with customer_id: {uid}")
        response = await client.post(
            NXTSTAR_API_URL,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        api_response = response.json()
        
        logger.info(f"[CHECK_PAYMENT_STATUS] API Response: {api_response}")
        
        # Handle the three possible API response scenarios
        if api_response.get("success"):
            if api_response.get("user_found"):
                # User found - extract data from array
                user_data_array = api_response.get("data", [])
                if user_data_array:
                    user_info = user_data_array[0]
                    return {
                        "success": True,
                        "user_found": True,
                        "full_name": user_info.get("full_name"),
                        "date_of_birth": user_info.get("date_of_birth"),
                        "broker_name": user_info.get("broker_name"),
                        "broker_alias": user_info.get("broker_alias"),
                        "nextstar_username": user_info.get("nextstar_username"),
                        "deposit_status": user_info.get("deposit_status")  # "yes" or "no"
                    }
            else:
                # User not found
                return {
                    "success": True,
                    "user_found": False,
                    "message": api_response.get("message", "User not found")
                }
        else:
            # API error
            return {
                "success": False,
                "user_found": False,
                "message": api_response.get("message", "API error")
            }
            
    except Exception as e:
        logger.error(f"[CHECK_PAYMENT_STATUS] Exception: {e}")
        return {
            "success": False,
            "user_found": False,
            "message": f"Exception: {str(e)}"
        }


async def get_available_groups(language):
    """Get available groups for a language from Django backend."""
    try:
        response = await client.get(
            f"{DJANGO_API_BASE_URL}/groups/available/",
            params={"language": language},
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error getting groups: {e}")
        return None


async def select_group_and_generate_link(user_id, group_id):
    """Select a group and generate invite link."""
    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/groups/select-and-generate/",
            json={
                "user_id": user_id,
                "group_id": group_id,
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error selecting group and generating link: {e}")
        return None


def validate_uid_format(uid):
    """Validate UID format: must be 6-8 digits.
    
    Returns: (is_valid, error_message)
    """
    uid = uid.strip()
    
    if not uid.isdigit():
        return False, "UID must contain only digits"
    
    if len(uid) < 6 or len(uid) > 8:
        return False, f"UID must be 6-8 digits (you entered {len(uid)})"
    
    return True, None


LANGUAGE_KEYBOARD = [
    [
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇫🇷 French", callback_data="lang_fr"),
    ],
    [
        InlineKeyboardButton("🇪🇸 Spanish", callback_data="lang_es"),
        InlineKeyboardButton("🇸🇦 Arabic", callback_data="lang_ar"),
    ],
    [
        InlineKeyboardButton("🇵🇹 Portuguese", callback_data="lang_pt-br"),
    ],
]


async def reset_user_in_backend(telegram_user_id):
    """Best-effort call to wipe the user's stored UID / joined groups in the backend.

    Safe to call even if the backend has no such endpoint — failures are logged and ignored.
    """
    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/users/reset/",
            json={"telegram_user_id": telegram_user_id},
        )
        if response.status_code == 200:
            logger.info(f"[RESET] Backend reset OK for telegram_user_id={telegram_user_id}")
        else:
            logger.warning(f"[RESET] Backend reset returned HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"[RESET] Backend reset call failed (endpoint may not exist yet): {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command - wipe all prior state (in-memory + backend) and show language picker.

    This is the user's escape hatch: any stale UID, awaiting_* flags, or saved groups
    must be cleared so the user is treated as brand new and re-prompted from scratch.
    """
    telegram_user_id = update.effective_user.id
    logger.info(f"[START] /start from telegram_user_id={telegram_user_id} — resetting state")

    # 1. Wipe in-memory session state (UID, awaiting_uid, awaiting_redeposit_check, language, etc.)
    context.user_data.clear()

    # 2. Best-effort wipe of the user's backend record so the next UID entry is treated fresh
    await reset_user_in_backend(telegram_user_id)

    # 3. Show language picker (same flow as Hi/Hello)
    await update.message.reply_text(
        "🎉 Welcome to NxtStar Bot!\n\n"
        "I'm your trading bot companion. Let me help you get started.\n\n"
        "First, please choose your preferred language:",
        reply_markup=InlineKeyboardMarkup(LANGUAGE_KEYBOARD),
    )

async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve or decline a join request created by an invite link.

    Invite links are now created with creates_join_request=True, so when a user
    taps a link Telegram fires this update *before* the user is added. We check
    that the requesting telegram_user_id matches the one who generated the
    invite for this chat (via the backend), then approve or decline.

    This is the layer that stops a shared link from letting anyone else in:
    a different telegram_id will not match any pending invite for this chat,
    so the join request is declined and they never enter the group.
    """
    join_request = update.chat_join_request
    if not join_request:
        return

    telegram_id = join_request.from_user.id
    chat_id = join_request.chat.id

    logger.info("="*80)
    logger.info(f"[JOIN_REQUEST] telegram_user_id={telegram_id} chat_id={chat_id}")

    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/invites/validate-join/",
            json={
                "telegram_user_id": telegram_id,
                "chat_id": chat_id,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f"[JOIN_REQUEST] validate-join response: {data}")

        if data.get("success"):
            await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=telegram_id)
            logger.info(f"[JOIN_REQUEST] ✅ APPROVED user {telegram_id} for chat {chat_id}")
            logger.info(f"[AUDIT_TRAIL] Approved join: telegram_id={telegram_id}, chat_id={chat_id}, uid={data.get('uid')}")

            # Post-access welcome + disclaimer, sent in the bot's DM with the user.
            language = context.user_data.get('language', 'en')
            post_access_messages = {
                "pt-br": (
                    "🔓 Você agora pode acessar os canais privados da comunidade e receber seus primeiros sinais.\n\n"
                    "Esses alertas não são fornecidos pela NextStar e resultam exclusivamente do compartilhamento voluntário de membros da comunidade.\n\n"
                    "<i>⚠ O trading envolve riscos significativos de perda de capital. Opere com responsabilidade e nunca invista mais do que pode se permitir perder.</i>\n\n"
                    "💬 Dúvidas? @team_NextStar 👇"
                ),
                "fr": (
                    "🔓 Vous pouvez désormais accéder aux canaux privés de la communauté et recevoir vos premiers signaux.\n\n"
                    "Ces alertes ne sont pas proposées par NextStar et résultent uniquement du partage volontaire de membres de la communauté.\n\n"
                    "<i>⚠ Le trading comporte des risques importants de perte en capital. Tradez de manière responsable et n'investissez jamais plus que ce que vous pouvez vous permettre de perdre.</i>\n\n"
                    "💬 Des questions ? @team_NextStar 👇"
                ),
                "en": (
                    "🔓 You can now access the community's private channels and receive your first signals.\n\n"
                    "These alerts are not provided by NextStar and result solely from the voluntary sharing of community members.\n\n"
                    "<i>⚠ Trading involves significant risks of capital loss. Trade responsibly and never invest more than you can afford to lose.</i>\n\n"
                    "💬 Questions? @team_NextStar 👇"
                ),
                "es": (
                    "🔓 Ya puedes acceder a los canales privados de la comunidad y recibir tus primeras señales.\n\n"
                    "Estas alertas no son proporcionadas por NextStar y son únicamente el resultado del intercambio voluntario entre miembros de la comunidad.\n\n"
                    "<i>⚠ El trading conlleva riesgos significativos de pérdida de capital. Opera de forma responsable y nunca inviertas más de lo que puedas permitirte perder.</i>\n\n"
                    "💬 ¿Preguntas? @team_NextStar 👇"
                ),
                "ar": (
                    "🔓 يمكنك الآن الوصول إلى القنوات الخاصة بالمجتمع وتلقي إشاراتك الأولى.\n\n"
                    "هذه التنبيهات ليست مقدمة من NextStar وتنتج فقط عن المشاركة الطوعية من أعضاء المجتمع.\n\n"
                    "<i>⚠ ينطوي التداول على مخاطر كبيرة لخسارة رأس المال. تداول بمسؤولية ولا تستثمر أبدًا أكثر مما يمكنك تحمل خسارته.</i>\n\n"
                    "💬 أسئلة؟ @team_NextStar 👇"
                ),
            }
            welcome_msg = post_access_messages.get(language, post_access_messages["en"])
            try:
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=welcome_msg,
                    parse_mode="HTML",
                )
                logger.info(f"[JOIN_REQUEST] Sent post-access DM to user {telegram_id} (lang={language})")
            except Exception as dm_error:
                logger.warning(f"[JOIN_REQUEST] Failed to send post-access DM to {telegram_id}: {dm_error}")
        else:
            reason = data.get("reason", "unknown")
            logger.warning(f"[JOIN_REQUEST] ❌ DECLINING user {telegram_id} — reason: {reason}")
            await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=telegram_id)
            logger.info(f"[AUDIT_TRAIL] Declined join attempt: telegram_id={telegram_id}, chat_id={chat_id}, reason={reason}")

    except Exception as e:
        logger.error(f"[JOIN_REQUEST] Exception: {type(e).__name__}: {str(e)}", exc_info=True)
        # On error, decline by default — safer than letting through unverified joins.
        try:
            await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=telegram_id)
            logger.info(f"[JOIN_REQUEST] Declined user {telegram_id} due to validation error")
        except Exception as decline_error:
            logger.error(f"[JOIN_REQUEST] Failed to decline: {decline_error}")
    finally:
        logger.info("="*80)


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group.
    
    Step 8: Join request & auto-approval
    - Telegram ID matches stored ID -> Approve
    - Telegram ID mismatch -> Decline and log in audit
    """
    print("🔥 NEW_CHAT_MEMBER EVENT TRIGGERED")
    if not update.message or not update.message.new_chat_members:
        return

    for member in update.message.new_chat_members:
        telegram_id = member.id
        chat_id = update.effective_chat.id
        
        logger.info("="*80)
        logger.info(f"[NEW_MEMBER] Member joined: {member.first_name} (ID: {telegram_id})")
        logger.info(f"[NEW_MEMBER] Chat ID: {chat_id}")
        logger.info(f"[NEW_MEMBER] Chat title: {update.effective_chat.title}")

        try:
            # Step 8: Call Django API to validate join request and check Telegram ID match
            logger.info(f"[NEW_MEMBER] Calling validate-join API")
            logger.info(f"  Payload: telegram_user_id={telegram_id}, chat_id={chat_id}")
            
            response = await client.post(
                f"{DJANGO_API_BASE_URL}/invites/validate-join/",
                json={
                    "telegram_user_id": telegram_id,
                    "chat_id": chat_id
                },
                timeout=10.0
            )

            response.raise_for_status()
            data = response.json()
            
            logger.info(f"[NEW_MEMBER] API Response status: {response.status_code}")
            logger.info(f"[NEW_MEMBER] API Response data: {data}")

            if not data.get("success"):
                reason = data.get("reason", "unknown")
                logger.error(f"[NEW_MEMBER] ❌ Validation FAILED! Reason: {reason}")
                
                # Get more details if available
                if data.get("details"):
                    logger.error(f"[NEW_MEMBER] Details: {data['details']}")
                
                # Case: Telegram ID mismatch (link shared)
                if reason == "TELEGRAM_ID_MISMATCH":
                    logger.warning(f"[NEW_MEMBER] 🚫 TELEGRAM ID MISMATCH! Invite link was shared. Logging to audit trail.")
                    
                    # Log to audit trail (should be done by Django API)
                    logger.info(f"[AUDIT_TRAIL] Unauthorized join attempt:")
                    logger.info(f"[AUDIT_TRAIL]   - Expected Telegram ID: {data.get('expected_telegram_id')}")
                    logger.info(f"[AUDIT_TRAIL]   - Actual Telegram ID: {telegram_id}")
                    logger.info(f"[AUDIT_TRAIL]   - Chat ID: {chat_id}")
                    logger.info(f"[AUDIT_TRAIL]   - Invite UID: {data.get('invite_uid')}")
                    
                    # Kick the user for security
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        await context.bot.unban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        logger.info(f"[NEW_MEMBER] ✅ User {telegram_id} kicked due to ID mismatch")
                    except Exception as kick_error:
                        logger.error(f"[NEW_MEMBER] Failed to kick user: {str(kick_error)}")
                
                # Case: Already joined a group (each UID can only join one group)
                elif reason == "ALREADY_IN_GROUP":
                    logger.warning(f"[NEW_MEMBER] ⚠️ User already in another group with this UID")
                    
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        await context.bot.unban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        logger.info(f"[NEW_MEMBER] User {telegram_id} kicked - already in another group")
                    except Exception as kick_error:
                        logger.error(f"[NEW_MEMBER] Failed to kick user: {str(kick_error)}")
                
                else:
                    # Other errors - kick the user
                    logger.info(f"[NEW_MEMBER] Kicking user {telegram_id} due to validation failure: {reason}")
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        await context.bot.unban_chat_member(
                            chat_id=chat_id,
                            user_id=telegram_id
                        )
                        logger.info(f"[NEW_MEMBER] ✅ User {telegram_id} kicked successfully")
                    except Exception as kick_error:
                        logger.error(f"[NEW_MEMBER] Failed to kick user: {str(kick_error)}")
            else:
                # Step 8 Success: Telegram ID matches - auto-approve
                logger.info(f"[NEW_MEMBER] ✅ VALIDATION SUCCESSFUL!")
                logger.info(f"[NEW_MEMBER] ✅ Telegram ID matches - User {telegram_id} auto-approved to join")
                
                # Log to audit trail
                logger.info(f"[AUDIT_TRAIL] Successful join:")
                logger.info(f"[AUDIT_TRAIL]   - Telegram ID: {telegram_id}")
                logger.info(f"[AUDIT_TRAIL]   - Chat ID: {chat_id}")
                logger.info(f"[AUDIT_TRAIL]   - UID: {data.get('uid')}")
                logger.info(f"[AUDIT_TRAIL]   - Invite consumed: Yes")

        except Exception as e:
            logger.error(f"[NEW_MEMBER] Exception during validation: {type(e).__name__}: {str(e)}", exc_info=True)
            
            # Default: kick the user on error to be safe
            try:
                await context.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=telegram_id
                )
                await context.bot.unban_chat_member(
                    chat_id=chat_id,
                    user_id=telegram_id
                )
                logger.info(f"[NEW_MEMBER] User {telegram_id} kicked due to validation error")
            except Exception as kick_error:
                logger.error(f"[NEW_MEMBER] Failed to kick user: {str(kick_error)}")
        
        finally:
            logger.info("="*80)
            
async def reply_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages from users."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.lower().strip()
    user_data = context.user_data

    # Greetings always win over awaiting_* state — they are a full reset, identical to /start.
    # Without this, a user stuck in awaiting_redeposit_check can never escape by saying "hi".
    if text in {"hi", "hello", "hola", "ola", "bonjour"}:
        telegram_user_id = update.effective_user.id
        logger.info(f"[GREETING] '{text}' from telegram_user_id={telegram_user_id} — resetting state")
        user_data.clear()
        await reset_user_in_backend(telegram_user_id)
        await update.message.reply_text(
            "Please choose your preferred language to proceed:",
            reply_markup=InlineKeyboardMarkup(LANGUAGE_KEYBOARD),
        )
        return

    if 'awaiting_uid' in user_data and user_data.get('awaiting_uid'):
        # User is entering their UID
        await handle_uid_input(update, context)

    elif 'awaiting_redeposit_check' in user_data and user_data.get('awaiting_redeposit_check'):
        # User claimed they made a deposit, waiting for /checkdeposit or similar
        language = user_data.get('language', 'en')
        redeposit_reminder_messages = {
            "pt-br": "Por favor, toque no botão 'Verificar Depósito' abaixo para verificar, ou envie /start para começar novamente.",
            "fr": "Veuillez cliquer sur le bouton « Vérifier le dépôt » ci-dessous pour vérifier, ou envoyez /start pour recommencer.",
            "en": "Please click the 'Check Deposit' button below to verify, or send /start to begin again.",
            "es": "Por favor, pulsa el botón 'Verificar Depósito' abajo para verificar, o envía /start para empezar de nuevo.",
            "ar": "يرجى الضغط على زر 'تحقق من الإيداع' أدناه للتحقق، أو إرسال /start للبدء من جديد.",
        }
        redeposit_reminder_msg = redeposit_reminder_messages.get(language, redeposit_reminder_messages["en"])
        await update.message.reply_text(
            redeposit_reminder_msg,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Check Deposit", callback_data="recheck_deposit")
            ]])
        )

    else:
        language = user_data.get('language', 'en')
        fallback_messages = {
            "pt-br": "Entre em contato com o suporte se você não encontrou o seu ID.\n\nSe quiser recomeçar, clique ou digite /start.",
            "fr": "Contactez le support si vous n'avez pas trouvé votre ID.\n\nSi vous souhaitez recommencer, cliquez ou tapez /start.",
            "en": "Contact the support team if you didn't find your ID.\n\nIf you want to restart, click or type /start.",
            "es": "Contacta con el soporte si no encontraste tu ID.\n\nSi quieres reiniciar, pulsa o escribe /start.",
            "ar": "تواصل مع فريق الدعم إذا لم تجد معرفك.\n\nإذا أردت إعادة البدء، اضغط أو اكتب /start.",
        }
        fallback_msg = fallback_messages.get(language, fallback_messages["en"])
        await update.message.reply_text(fallback_msg)


async def handle_uid_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle UID input from user with format validation and API verification."""
    user_data = context.user_data
    language = user_data.get('language', 'en')
    user_id = user_data.get('user_id')
    uid = update.message.text.strip()
    
    logger.info(f"[UID_INPUT] User {user_id} entered UID (customer_id): {uid}")
    
    # Step 3: UID Format Check
    is_valid, error_msg = validate_uid_format(uid)
    
    if not is_valid:
        error_messages = {
            "pt-br": f"❌ Formato inválido!\n\n{error_msg}\n\nPor favor, insira um UID válido (6-8 dígitos):",
            "fr": f"❌ Format invalide!\n\n{error_msg}\n\nVeuillez entrer un UID valide (6-8 chiffres):",
            "en": f"❌ Format invalid!\n\n{error_msg}\n\nPlease enter a valid UID (6-8 digits):",
            "es": f"❌ ¡Formato inválido!\n\n{error_msg}\n\nPor favor, ingresa un UID válido (6-8 dígitos):",
            "ar": f"❌ صيغة غير صحيحة!\n\n{error_msg}\n\nيرجى إدخال UID صحيح (6-8 أرقام):",
        }
        
        error_text = error_messages.get(language, f"Invalid UID format: {error_msg}")
        await update.message.reply_text(error_text)
        return
    
    # Step 4: Call the real NxtStar API to verify UID/customer_id
    logger.info(f"[UID_INPUT] Calling NxtStar API to verify customer_id: {uid}")
    payment_result = await check_payment_status(uid)
    
    # Handle API error response: success=False
    if not payment_result or not payment_result.get('success'):
        error_message = payment_result.get('message', 'API error') if payment_result else 'API error'
        logger.error(f"[UID_INPUT] ❌ API Error: {error_message}")
        
        error_messages = {
            "pt-br": f"❌ Erro ao verificar UID: {error_message}\n\nPor favor, tente novamente mais tarde.",
            "fr": f"❌ Erreur lors de la vérification de l'UID: {error_message}\n\nVeuillez réessayer plus tard.",
            "en": f"❌ Error verifying UID: {error_message}\n\nPlease try again later.",
            "es": f"❌ Error verificando UID: {error_message}\n\nPor favor, intenta más tarde.",
            "ar": f"❌ خطأ في التحقق من UID: {error_message}\n\nيرجى المحاولة لاحقاً.",
        }
        
        error_text = error_messages.get(language, f"Error: {error_message}")
        await update.message.reply_text(error_text)
        
        # Reset state but keep language for retry
        user_data.pop('awaiting_uid', None)
        return
    
    # Handle user not found
    if not payment_result.get('user_found'):
        logger.warning(f"[UID_INPUT] User not found for customer_id: {uid}")
        
        error_messages = {
            "pt-br": "❌ Usuário não encontrado!\n\nPor favor, verifique seu ID de cliente e tente novamente. Se continuar tendo problemas, entre em contato com o suporte: @Team_NextStar 💬",
            "fr": "❌ Utilisateur non trouvé !\n\nVeuillez vérifier votre ID de client et réessayer. Si vous rencontrez toujours des difficultés, contactez le support : @Team_NextStar 💬",
            "en": "❌ User not found!\n\nPlease verify your client ID and try again. If you keep having issues, contact support: @Team_NextStar 💬",
            "es": "❌ ¡Usuario no encontrado!\n\nPor favor, verifica tu ID de cliente e intenta de nuevo. Si sigues teniendo problemas, contacta con el soporte: @Team_NextStar 💬",
            "ar": "❌ لم يتم العثور على المستخدم!\n\nيرجى التحقق من معرف العميل والمحاولة مرة أخرى. إذا استمرت المشكلة، تواصل مع الدعم: @Team_NextStar 💬",
        }

        error_text = error_messages.get(language, "User not found. Please try again.")
        await update.message.reply_text(error_text)
        user_data.pop('awaiting_uid', None)
        return
    
    # User found - extract account info
    logger.info(f"[UID_INPUT] ✅ User found for customer_id: {uid}")
    broker_name = payment_result.get('broker_name', 'Unknown')
    broker_alias = payment_result.get('broker_alias', '')
    nextstar_username = payment_result.get('nextstar_username', '')
    deposit_status_str = payment_result.get('deposit_status', 'no')  # "yes" or "no"
    has_deposit = deposit_status_str.lower() == 'yes'
    
    logger.info(f"[UID_INPUT] Broker: {broker_name}, Username: {nextstar_username}, Deposit: {deposit_status_str}")
    
    # Store UID for later use
    user_data['temp_uid'] = uid
    user_data['original_uid'] = uid
    user_data['broker_name'] = broker_name
    user_data['nextstar_username'] = nextstar_username
    
    # Save UID to database
    logger.info(f"[UID_INPUT] Saving nxtstar_uid to database for user {user_id}")
    verify_result = await verify_user(user_id, uid)
    
    if verify_result and verify_result.get('success'):
        logger.info(f"[UID_INPUT] ✅ UID saved to database successfully")
    else:
        error_msg = verify_result.get('message', 'Unknown error') if verify_result else 'Failed to save UID'
        logger.warning(f"[UID_INPUT] ⚠️ Failed to save UID to database: {error_msg}")
    
    # Step 5: Deposit Check
    if has_deposit:
        # Deposit confirmed - proceed to group selection
        logger.info(f"[UID_INPUT] ✅ Deposit confirmed (status: {deposit_status_str})")

        confirm_messages = {
            "pt-br": f"✅ Verificação concluída!\n\n👤 Nome de usuário: {nextstar_username}\n🏦 Corretora: {broker_name}\n✓ Primeiro depósito realizado",
            "fr": f"✅ Vérification terminée !\n\n👤 Nom d'utilisateur: {nextstar_username}\n🏦 Courtier: {broker_name}\n✓ Premier dépôt effectué",
            "en": f"✅ Verification complete!\n\n👤 Username: {nextstar_username}\n🏦 Broker: {broker_name}\n✓ First deposit made",
            "es": f"✅ ¡Verificación completada!\n\n👤 Nombre de usuario: {nextstar_username}\n🏦 Corredor: {broker_name}\n✓ Primer depósito realizado",
            "ar": f"✅ تم التحقق بنجاح!\n\n👤 اسم المستخدم: {nextstar_username}\n🏦 الوسيط: {broker_name}\n✓ تم الإيداع الأول",
        }

        confirm_text = confirm_messages.get(language, f"Deposit confirmed! Broker: {broker_name}")
        await update.message.reply_text(confirm_text)

        # Proceed to group selection
        await proceed_to_group_selection(update, context, user_id, uid)
        user_data.pop('awaiting_uid', None)
    
    else:
        # No deposit detected - show "I've made my deposit" button
        logger.info(f"[UID_INPUT] 💵 No deposit detected (status: {deposit_status_str}), showing deposit check button")
        
        deposit_messages = {
            "pt-br": f"❌ Nenhum depósito realizado!\n\n👤 Nome de usuário: {nextstar_username}\n🏦 Corretora: {broker_name}\n⚠️ Primeiro depósito realizado\n\n💡 Se você já fez seu primeiro depósito, toque no botão abaixo para verificar novamente.\n\nSe você ainda não fez um depósito, por favor faça-o com um dos nossos brokers parceiros e volte.",
            "fr": f"❌ Aucun dépôt effectué !\n\n👤 Nom d'utilisateur: {nextstar_username}\n🏦 Courtier: {broker_name}\n⚠️ 1er dépôt effectué\n\n💡 Si vous avez effectué votre premier dépôt, cliquez sur le bouton ci-dessous afin de relancer la vérification.\n\nSi vous n'avez pas encore effectué de dépôt, veuillez le faire auprès d'un de nos brokers partenaires puis revenez.",
            "en": f"❌ No deposit made!\n\n👤 Username: {nextstar_username}\n🏦 Broker: {broker_name}\n⚠️ First deposit made\n\n💡 If you have already made your first deposit, tap the button below to re-check.\n\nIf you haven't made a deposit yet, please do so with one of our partner brokers and come back.",
            "es": f"❌ ¡Sin depósito realizado!\n\n👤 Nombre de usuario: {nextstar_username}\n🏦 Corredor: {broker_name}\n⚠️ Primer depósito realizado\n\n💡 Si ya has realizado tu primer depósito, pulsa el botón de abajo para volver a verificar.\n\nSi aún no has realizado un depósito, hazlo con uno de nuestros brokers asociados y vuelve.",
            "ar": f"❌ لم يتم إجراء أي إيداع!\n\n👤 اسم المستخدم: {nextstar_username}\n🏦 الوسيط: {broker_name}\n⚠️ تم الإيداع الأول\n\n💡 إذا كنت قد أجريت إيداعك الأول، اضغط على الزر أدناه لإعادة التحقق.\n\nإذا لم تقم بأي إيداع بعد، يرجى إجراؤه لدى أحد وسطائنا الشركاء ثم العودة.",
        }
        
        deposit_text = deposit_messages.get(language, "No deposit detected.")
        
        # Show "I've made my deposit" button
        keyboard = [[
            InlineKeyboardButton(
                "✅ I've Made My Deposit",
                callback_data=f"recheck_deposit_{uid}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(deposit_text, reply_markup=reply_markup)
        
        # Set state to wait for button click
        user_data['awaiting_redeposit_check'] = True
        user_data.pop('awaiting_uid', None)


async def proceed_to_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, uid: str) -> None:
    """Fetch available groups for the user's language and show selection buttons."""
    user_data = context.user_data
    language = user_data.get('language', 'en')

    logger.info(
        f"[GROUP_SELECTION] Fetching groups for user_id={user_id}, "
        f"user_data['language']='{language}', joining_another_group={user_data.get('joining_another_group')}"
    )

    groups_result = await get_available_groups(language)

    if not groups_result or not groups_result.get('success'):
        error_messages = {
            "pt-br": "❌ Não há grupos disponíveis no momento. Tente mais tarde.",
            "fr": "❌ Aucun groupe disponible pour le moment. Réessayez plus tard.",
            "en": "❌ No groups available at the moment. Please try later.",
            "es": "❌ No hay grupos disponibles en este momento. Intenta más tarde.",
            "ar": "❌ لا توجد مجموعات متاحة في الوقت الحالي. حاول لاحقاً.",
        }
        error_msg = error_messages.get(language, "No groups available.")
        if update and update.message:
            await update.message.reply_text(error_msg)
        else:
            await context.bot.send_message(chat_id=user_data.get('chat_id'), text=error_msg)

        user_data.pop('temp_uid', None)
        user_data.pop('joining_another_group', None)
        return

    groups = groups_result.get('groups', [])

    if not groups:
        error_messages = {
            "pt-br": "❌ Nenhum grupo disponível. Tente mais tarde.",
            "fr": "❌ Aucun groupe disponible. Réessayez plus tard.",
            "en": "❌ No groups available. Please try later.",
            "es": "❌ Sin grupos disponibles. Intenta más tarde.",
            "ar": "❌ لا توجد مجموعات متاحة. حاول لاحقاً.",
        }
        error_msg = error_messages.get(language, "No groups available.")
        if update and update.message:
            await update.message.reply_text(error_msg)
        else:
            await context.bot.send_message(chat_id=user_data.get('chat_id'), text=error_msg)

        user_data.pop('temp_uid', None)
        user_data.pop('joining_another_group', None)
        return

    logger.info(f"[GROUP_SELECTION] Found {len(groups)} groups for language '{language}'")
    for g in groups:
        logger.info(
            f"[GROUP_SELECTION]   - id={g.get('id')}, chat_id={g.get('chat_id')}, "
            f"language='{g.get('language')}', chat_title={g.get('chat_title')!r}"
        )

    mismatched = [g for g in groups if g.get('language') and g.get('language') != language]
    if mismatched:
        logger.warning(
            f"[GROUP_SELECTION] ⚠️ Backend returned {len(mismatched)} group(s) whose language "
            f"does not match the requested '{language}'. Check Django /groups/available/ filter "
            f"and Group.language values in DB."
        )

    user_data['available_groups'] = groups
    user_data['awaiting_group_selection'] = True
    user_data['verified_uid'] = uid

    keyboard = []
    for group in groups:
        keyboard.append([
            InlineKeyboardButton(
                group['chat_title'],
                callback_data=f"select_group_{group['id']}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    selection_prompts = {
        "pt-br": "Selecione seu grupo abaixo",
        "fr": "Sélectionnez ci-dessous votre groupe",
        "en": "Select your group below",
        "es": "Selecciona tu grupo a continuación",
        "ar": "اختر مجموعتك أدناه",
    }

    selection_msg = selection_prompts.get(language, "Choose a group:")

    if update and update.message:
        await update.message.reply_text(selection_msg, reply_markup=reply_markup)
    else:
        await context.bot.send_message(
            chat_id=user_data.get('chat_id'),
            text=selection_msg,
            reply_markup=reply_markup
        )


async def handle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int) -> None:
    """Handle group selection callback — generate personal invite link for the chosen group."""
    query = update.callback_query
    await query.answer()

    user_data = context.user_data
    language = user_data.get('language', 'en')
    user_id = user_data.get('user_id')

    logger.info(f"[GROUP_CALLBACK] group_id={group_id}, user_id={user_id}, language={language}")

    # Find selected group
    groups = user_data.get('available_groups', [])
    selected_group = None
    for group in groups:
        if group['id'] == group_id:
            selected_group = group
            break

    if not selected_group:
        error_messages = {
            "pt-br": "❌ Grupo não encontrado. Tente novamente.",
            "fr": "❌ Groupe non trouvé. Réessayez.",
            "en": "❌ Group not found. Please try again.",
            "es": "❌ Grupo no encontrado. Intenta de nuevo.",
            "ar": "❌ لم يتم العثور على المجموعة. حاول مرة أخرى.",
        }
        error_msg = error_messages.get(language, "Group not found.")
        logger.warning(f"[GROUP_CALLBACK] Group {group_id} not found in available groups")
        await query.edit_message_text(text=error_msg)

        user_data.pop('available_groups', None)
        user_data.pop('awaiting_group_selection', None)
        return

    logger.info(f"[GROUP_CALLBACK] Selected group: {selected_group['chat_title']}")

    # Generate invite link for selected group
    logger.info(f"[GROUP_CALLBACK] Calling select_group_and_generate_link API for group {group_id}")
    invite_result = await select_group_and_generate_link(user_id, group_id)

    if not invite_result or not invite_result.get('success'):
        error_reason = invite_result.get('reason', 'Unknown error') if invite_result else 'Backend error'
        error_message_key = invite_result.get('message', '') if invite_result else ''

        if error_message_key == 'already_joined_this_group':
            already_joined_messages = {
                "pt-br": "⚠️ Você já é membro deste grupo!\n\nEscolha outro grupo ou clique em '➕ Entrar em outro grupo' para escolher outro idioma.",
                "fr": "⚠️ Vous êtes déjà membre de ce groupe!\n\nChoisissez un autre groupe ou cliquez sur '➕ Rejoindre un autre groupe' pour choisir une autre langue.",
                "en": "⚠️ You are already a member of this group!\n\nChoose a different group or click '➕ Join Another Group' to pick a different language.",
                "es": "⚠️ ¡Ya eres miembro de este grupo!\n\nElige otro grupo o haz clic en '➕ Unirse a otro grupo' para elegir otro idioma.",
                "ar": "⚠️ أنت بالفعل عضو في هذه المجموعة!\n\nاختر مجموعة أخرى أو انقر على '➕ الانضمام إلى مجموعة أخرى' لاختيار لغة مختلفة.",
            }
            error_msg = already_joined_messages.get(language, "You are already a member of this group.")

            keyboard = [[
                InlineKeyboardButton("🔙 Back to Groups", callback_data="back_to_groups"),
                InlineKeyboardButton("➕ Join Another Group", callback_data="join_another_group"),
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(text=error_msg, reply_markup=reply_markup)
            user_data.pop('available_groups', None)
            user_data.pop('awaiting_group_selection', None)
            return

        error_messages = {
            "pt-br": f"❌ Erro ao gerar link: {error_reason}",
            "fr": f"❌ Erreur lors de la génération du lien: {error_reason}",
            "en": f"❌ Error generating link: {error_reason}",
            "es": f"❌ Error al generar enlace: {error_reason}",
            "ar": f"❌ خطأ في إنشاء الرابط: {error_reason}",
        }
        error_msg = error_messages.get(language, f"Error: {error_reason}")
        logger.error(f"[GROUP_CALLBACK] Failed to generate link: {error_reason}")
        await query.edit_message_text(text=error_msg)
        user_data.pop('available_groups', None)
        user_data.pop('awaiting_group_selection', None)
        return

    invite_link = invite_result.get('invite_link')
    logger.info(f"[GROUP_CALLBACK] ✅ Invite link generated: {invite_link}")

    confirmation_messages = {
        "pt-br": f"✅ Você selecionou: {selected_group['chat_title']}\n\n🔑 Seu link de convite pessoal (válido 15 minutos):\n\n{invite_link}\n\n👆 Toque no link acima para entrar no grupo automaticamente!",
        "fr": f"✅ Vous avez sélectionné: {selected_group['chat_title']}\n\n🔑 Votre lien d'invitation personnel (valable 15 minutes):\n\n{invite_link}\n\n👆 Cliquez sur le lien ci-dessus pour rejoindre le groupe automatiquement !",
        "en": f"✅ You selected: {selected_group['chat_title']}\n\n🔑 Your personal invite link (valid 15 minutes):\n\n{invite_link}\n\n👆 Tap the link above to join the group automatically!",
        "es": f"✅ Has seleccionado: {selected_group['chat_title']}\n\n🔑 Tu enlace de invitación personal (válido 15 minutos):\n\n{invite_link}\n\n👆 Pulsa el enlace de arriba para unirte al grupo automáticamente.",
        "ar": f"✅ لقد اخترت: {selected_group['chat_title']}\n\n🔑 رابط الدعوة الشخصي الخاص بك (صالح لمدة 15 دقيقة):\n\n{invite_link}\n\n👆 اضغط على الرابط أعلاه للانضمام إلى المجموعة تلقائيًا!",
    }

    confirmation_msg = confirmation_messages.get(language, f"Selected group: {selected_group['chat_title']}\n\nInvite link: {invite_link}")

    keyboard = [[
        InlineKeyboardButton("➕ Join Another Group", callback_data="join_another_group"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=confirmation_msg, reply_markup=reply_markup)

    user_data.pop('available_groups', None)
    user_data.pop('awaiting_group_selection', None)
    user_data.pop('verified_uid', None)




async def handle_join_another_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_data = context.user_data
    logger.info(f"[JOIN_ANOTHER] User wants to join another group")
    
    # Mark as multi-join — original_uid is already stored and will be reused
    user_data['joining_another_group'] = True
    
    # Reset only group-selection state, keep user_id, language, original_uid
    user_data.pop('verified_uid', None)
    user_data.pop('available_groups', None)
    user_data.pop('awaiting_group_selection', None)
    
    await query.edit_message_text(
        text="🌐 Which language group do you want to join next?",
        reply_markup=InlineKeyboardMarkup(LANGUAGE_KEYBOARD),
    )
    logger.info(f"[JOIN_ANOTHER] Showing language selection for next group")

async def handle_exit_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Done' button - clean up and exit."""
    query = update.callback_query
    await query.answer()
    
    user_data = context.user_data
    language = user_data.get('language', 'en')
    
    logger.info(f"[EXIT_CHAT] User exited chat")
    
    # Thank you messages
    thank_you_messages = {
        "pt-br": "✅ Obrigado por usar o NxtStar Bot!\n\n🎉 Você agora é membro de todos os grupos que escolheu.\n\nPara começar de novo, digite /start",
        "fr": "✅ Merci d'avoir utilisé le bot NxtStar!\n\n🎉 Vous êtes maintenant membre de tous les groupes que vous avez choisis.\n\nPour recommencer, tapez /start",
        "en": "✅ Thank you for using the NxtStar Bot!\n\n🎉 You are now a member of all the groups you selected.\n\nTo start again, type /start",
        "es": "✅ ¡Gracias por usar el bot de NxtStar!\n\n🎉 Ahora eres miembro de todos los grupos que seleccionaste.\n\nPara comenzar de nuevo, escribe /start",
        "ar": "✅ شكراً لاستخدام بوت NxtStar!\n\n🎉 أنت الآن عضو في جميع المجموعات التي اخترتها.\n\nللبدء من جديد، اكتب /start",
    }
    
    thank_you_msg = thank_you_messages.get(language, "Thank you for using NxtStar Bot! Type /start to begin again.")
    
    await query.edit_message_text(text=thank_you_msg)
    
    # Clean up all user data
    user_data.clear()


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all callback queries from buttons."""
    query = update.callback_query
        
    callback_data = query.data
    user_data = context.user_data
    
    logger.info(f"[CALLBACK] Callback data: {callback_data}")
    
    # Handle language selection (button callback)
    if callback_data.startswith('lang_'):
        language = callback_data.replace('lang_', '')
        await handle_language_selection(update, context, language)
    
    # Handle "I've Made My Deposit" button - re-check deposit status
    elif callback_data.startswith('recheck_deposit_'):
        uid = callback_data.replace('recheck_deposit_', '')
        await handle_deposit_recheck(update, context, uid)
    
    # Handle "Join Another Group" button
    elif callback_data == 'join_another_group':
        await handle_join_another_group(update, context)
    
    # Handle "Done" / "Exit" button
    elif callback_data == 'exit_chat':
        await handle_exit_chat(update, context)
    
    # Handle back to group selection
    elif callback_data == 'back_to_groups':
        user_data['chat_id'] = update.effective_chat.id  # ✅ ensure chat_id is set
        await proceed_to_group_selection(None, context, user_data.get('user_id'), user_data.get('verified_uid'))
    
    # Handle change language
    elif callback_data == 'change_language':
        await query.edit_message_text(
            "Please choose your preferred language:",
            reply_markup=InlineKeyboardMarkup(LANGUAGE_KEYBOARD),
        )
    
    # Handle group selection
    elif callback_data.startswith('select_group_'):
        group_id = int(callback_data.replace('select_group_', ''))
        await handle_group_callback(update, context, group_id)


async def handle_deposit_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: str) -> None:
    """Re-check deposit status after user claims they've made a deposit."""
    query = update.callback_query
    user_data = context.user_data
    language = user_data.get('language', 'en')
    user_id = user_data.get('user_id')
    
    logger.info(f"[DEPOSIT_RECHECK] Re-checking deposit for customer_id: {uid}")
    
    # Call the real API again to check for deposit
    payment_result = await check_payment_status(uid)
    
    # Handle API error
    if not payment_result or not payment_result.get('success'):
        error_message = payment_result.get('message', 'API error') if payment_result else 'API error'
        logger.error(f"[DEPOSIT_RECHECK] ❌ API Error: {error_message}")
        
        error_messages = {
            "pt-br": f"❌ Erro ao conectar com a API: {error_message}\n\nTente novamente.",
            "fr": f"❌ Erreur de connexion à l'API: {error_message}\n\nRéessayez.",
            "en": f"❌ Error connecting to API: {error_message}\n\nPlease try again.",
            "es": f"❌ Error al conectar con la API: {error_message}\n\nIntenta de nuevo.",
            "ar": f"❌ خطأ في الاتصال بـ API: {error_message}\n\nحاول مرة أخرى.",
        }
        error_text = error_messages.get(language, f"Error: {error_message}")
        await query.edit_message_text(text=error_text)
        return
    
    # Handle user not found
    if not payment_result.get('user_found'):
        logger.warning(f"[DEPOSIT_RECHECK] User not found for customer_id: {uid}")
        
        not_found_messages = {
            "pt-br": "❌ Usuário não encontrado!\n\nPor favor, verifique seu ID de cliente e tente novamente. Se continuar tendo problemas, entre em contato com o suporte: @Team_NextStar 💬",
            "fr": "❌ Utilisateur non trouvé !\n\nVeuillez vérifier votre ID de client et réessayer. Si vous rencontrez toujours des difficultés, contactez le support : @Team_NextStar 💬",
            "en": "❌ User not found!\n\nPlease verify your client ID and try again. If you keep having issues, contact support: @Team_NextStar 💬",
            "es": "❌ ¡Usuario no encontrado!\n\nPor favor, verifica tu ID de cliente e intenta de nuevo. Si sigues teniendo problemas, contacta con el soporte: @Team_NextStar 💬",
            "ar": "❌ لم يتم العثور على المستخدم!\n\nيرجى التحقق من معرف العميل والمحاولة مرة أخرى. إذا استمرت المشكلة، تواصل مع الدعم: @Team_NextStar 💬",
        }
        not_found_text = not_found_messages.get(language, "User not found.")
        await query.edit_message_text(text=not_found_text)
        return
    
    # Check deposit status
    deposit_status_str = payment_result.get('deposit_status', 'no')  # "yes" or "no"
    has_deposit = deposit_status_str.lower() == 'yes'
    broker_name = payment_result.get('broker_name', 'Unknown')
    nextstar_username = payment_result.get('nextstar_username', '')
    
    if has_deposit:
        # Deposit confirmed - proceed to group selection
        logger.info(f"[DEPOSIT_RECHECK] ✅ Deposit confirmed (status: {deposit_status_str})")

        # Save UID to database if not already saved
        logger.info(f"[DEPOSIT_RECHECK] Saving nxtstar_uid to database for user {user_id}")
        verify_result = await verify_user(user_id, uid)

        if verify_result and verify_result.get('success'):
            logger.info(f"[DEPOSIT_RECHECK] ✅ UID saved to database successfully")
        else:
            error_msg = verify_result.get('message', 'Unknown error') if verify_result else 'Failed to save UID'
            logger.warning(f"[DEPOSIT_RECHECK] ⚠️ Failed to save UID to database: {error_msg}")

        success_messages = {
            "pt-br": f"✅ Verificação concluída!\n\n👤 Nome de usuário: {nextstar_username}\n🏦 Corretora: {broker_name}\n✓ Primeiro depósito realizado",
            "fr": f"✅ Vérification terminée !\n\n👤 Nom d'utilisateur: {nextstar_username}\n🏦 Courtier: {broker_name}\n✓ Premier dépôt effectué",
            "en": f"✅ Verification complete!\n\n👤 Username: {nextstar_username}\n🏦 Broker: {broker_name}\n✓ First deposit made",
            "es": f"✅ ¡Verificación completada!\n\n👤 Nombre de usuario: {nextstar_username}\n🏦 Corredor: {broker_name}\n✓ Primer depósito realizado",
            "ar": f"✅ تم التحقق بنجاح!\n\n👤 اسم المستخدم: {nextstar_username}\n🏦 الوسيط: {broker_name}\n✓ تم الإيداع الأول",
        }
        success_msg = success_messages.get(language, "Deposit confirmed!")
        await query.edit_message_text(text=success_msg)

        user_data['chat_id'] = update.effective_chat.id
        await proceed_to_group_selection(None, context, user_id, uid)
        user_data.pop('awaiting_redeposit_check', None)
    
    else:
        # Still no deposit
        logger.info(f"[DEPOSIT_RECHECK] 💵 Still no deposit detected (status: {deposit_status_str})")
        
        still_no_deposit_messages = {
            "pt-br": f"💵 Ainda não há depósito detectado.\n\n👤 Username: {nextstar_username}\n🏦 Corretora: {broker_name}\n\nPor favor, faça um depósito em sua conta no broker e tente novamente.",
            "fr": f"💵 Aucun dépôt n'a encore été détecté.\n\n👤 Nom d'utilisateur: {nextstar_username}\n🏦 Courtier: {broker_name}\n\nVeuillez effectuer un dépôt sur votre compte chez le courtier et réessayer.",
            "en": f"💵 Still no deposit detected.\n\n👤 Username: {nextstar_username}\n🏦 Broker: {broker_name}\n\nPlease make a deposit in your broker account and try again.",
            "es": f"💵 Todavía no hay depósito detectado.\n\n👤 Usuario: {nextstar_username}\n🏦 Corredor: {broker_name}\n\nPor favor, realiza un depósito en tu cuenta de broker e intenta de nuevo.",
            "ar": f"💵 لا يزال لم يتم اكتشاف أي إيداع.\n\n👤 اسم المستخدم: {nextstar_username}\n🏦 الوسيط: {broker_name}\n\nيرجى إجراء إيداع في حساب الوسيط الخاص بك والمحاولة مرة أخرى.",
        }
        still_no_deposit_msg = still_no_deposit_messages.get(language, "Still no deposit detected.")
        await query.edit_message_text(text=still_no_deposit_msg)

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chat_member updates — fires reliably in both basic groups AND supergroups.

    Detects transitions from an "in-group" status (member/administrator/restricted/creator)
    to an "out-of-group" status (left/kicked) and removes the group from the user's
    joined_groups in the database.
    """
    chat_member_update = update.chat_member
    if not chat_member_update:
        return

    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status

    in_group = {"member", "administrator", "restricted", "creator"}
    out_of_group = {"left", "kicked"}

    if old_status not in in_group or new_status not in out_of_group:
        return

    member = chat_member_update.new_chat_member.user
    telegram_id = member.id
    chat_id = update.effective_chat.id

    logger.info(
        f"[LEFT_GROUP] User {telegram_id} transitioned {old_status} -> {new_status} in chat {chat_id}"
    )

    try:
        response = await client.post(
            f"{DJANGO_API_BASE_URL}/groups/user-left/",
            json={
                "telegram_user_id": telegram_id,
                "chat_id": chat_id,
            },
        )
        logger.info(f"[LEFT_GROUP] API response: {response.json()}")
    except Exception as e:
        logger.error(f"[LEFT_GROUP] Error: {e}")

async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, language: str) -> None:
    """Handle language selection from buttons."""
    query = update.callback_query
    user_data = context.user_data

    prev_language = user_data.get('language')
    callback_data = query.data if query else None
    logger.info(
        f"[LANGUAGE_SELECT] callback_data='{callback_data}', parsed language='{language}', "
        f"previous user_data['language']='{prev_language}'"
    )

    user_data['language'] = language

    is_multi_join = user_data.get('joining_another_group', False)
    
    if is_multi_join:
        logger.info(f"[LANGUAGE_SELECT] Multi-join mode: skipping UID entry for language {language}")
        
        thanks_responses = {
            "pt-br": "✅ Excelente! Procurando grupos em Português (Brasil)...",
            "fr": "✅ Excellent! Recherche de groupes en Français...",
            "en": "✅ Great! Searching for groups in English...",
            "es": "✅ ¡Excelente! Buscando grupos en Español...",
            "ar": "✅ ممتاز! البحث عن مجموعات باللغة العربية...",
        }

        thanks_message = thanks_responses.get(language, "Loading groups...")
        await query.edit_message_text(text=thanks_message)
        
        uid = user_data.get('original_uid')
        user_id = user_data.get('user_id')
        
        if uid and user_id:
            logger.info(f"[LANGUAGE_SELECT] Proceeding to group selection for user {user_id} with UID {uid}")
            # ✅ Set chat_id so proceed_to_group_selection can send messages via send_message
            user_data['chat_id'] = update.effective_chat.id
            await proceed_to_group_selection(None, context, user_id, uid)
        else:
            uid_error_messages = {
                "pt-br": "❌ Erro: Não foi possível recuperar o UID. Por favor, recomece com /start",
                "fr": "❌ Erreur : Impossible de récupérer l'UID. Veuillez recommencer avec /start",
                "en": "❌ Error: Could not retrieve UID. Please start over with /start",
                "es": "❌ Error: No se pudo recuperar el UID. Por favor, comienza de nuevo con /start",
                "ar": "❌ خطأ: تعذر استرداد UID. يرجى البدء من جديد بـ /start",
            }
            error_msg = uid_error_messages.get(language, uid_error_messages["en"])
            await query.edit_message_text(text=error_msg)
            user_data.clear()
        
        return

    # Original flow
    user_result = await create_or_get_user(
        query.from_user.id,
        query.from_user.username,
        language
    )

    if user_result and user_result.get('success'):
        user_data['user_id'] = user_result['user_id']
        
        thanks_responses = {
            "pt-br": "🇵🇹 Obrigado por escolher o português.",
            "fr": "🇫🇷 Merci d'avoir choisi le français.",
            "en": "🇬🇧 Thanks for choosing English.",
            "es": "🇪🇸 Gracias por elegir español.",
            "ar": "🇸🇦 شكرًا لاختيارك العربية.",
        }

        thanks_message = thanks_responses.get(language, "Thanks for your selection.")
        await query.edit_message_text(text=thanks_message)

        wrong_language_hints = {
            "pt-br": "↩ Idioma errado? Toque em /start para escolher novamente.",
            "fr": "↩ Mauvaise langue ? Appuyez sur /start pour modifier.",
            "en": "↩ Wrong language? Tap /start to choose again.",
            "es": "↩ ¿Idioma equivocado? Pulsa /start para elegir de nuevo.",
            "ar": "↩ لغة خاطئة؟ اضغط على /start للاختيار مرة أخرى.",
        }
        wrong_lang_message = wrong_language_hints.get(language, "Wrong language? Tap /start to choose again.")
        await query.message.reply_text(wrong_lang_message)

        uid_prompt = {
            "pt-br": "🔐 Por favor, insira seu UID (6-8 dígitos) para que possamos verificar o status da sua conta.\n\nExemplo: 123456\n\n💡 Você encontrará este número no e-mail de confirmação do broker parceiro escolhido. Ou diretamente no seu perfil do broker depois de fazer login.",
            "fr": "🔐 Veuillez entrer votre UID (6-8 chiffres) afin que nous puissions vérifier le statut de votre compte.\n\nExemple: 123456\n\n💡 Vous trouverez ce numéro sur l'e-mail de confirmation du broker partenaire choisi. Ou directement sur votre profil broker une fois connecté à celui-ci.",
            "en": "🔐 Please enter your UID (6-8 digits) so we can verify your account status.\n\nExample: 123456\n\n💡 You will find this number in the confirmation email from your chosen partner broker. Or directly on your broker profile once logged in.",
            "es": "🔐 Por favor, ingresa tu UID (6-8 dígitos) para que podamos verificar el estado de tu cuenta.\n\nEjemplo: 123456\n\n💡 Encontrarás este número en el correo de confirmación de tu broker socio elegido. O directamente en tu perfil de broker una vez iniciada la sesión.",
            "ar": "🔐 يرجى إدخال معرف UID الخاص بك (6-8 أرقام) حتى نتمكن من التحقق من حالة حسابك.\n\nمثال: 123456\n\n💡 ستجد هذا الرقم في رسالة التأكيد من الوسيط الشريك الذي اخترته. أو مباشرة في ملفك الشخصي لدى الوسيط بعد تسجيل الدخول.",
        }

        prompt_message = uid_prompt.get(language, "Please enter your UID so we can verify your account status.")
        await query.message.reply_text(prompt_message)
        
        user_data['awaiting_uid'] = True
        logger.info(f"[LANGUAGE_SELECT] User {user_result['user_id']} selected language: {language}")
    else:
        error_messages = {
            "pt-br": "❌ Erro ao conectar com o servidor. Tente novamente.",
            "fr": "❌ Erreur de connexion au serveur. Réessayez.",
            "en": "❌ Server connection error. Please try again.",
            "es": "❌ Error de conexión del servidor. Intenta de nuevo.",
            "ar": "❌ خطأ في الاتصال بالخادم. حاول مرة أخرى.",
        }
        error_msg = error_messages.get(language, "Server error. Please try again.")
        await query.message.reply_text(error_msg)

async def debug_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("CHAT ID:", update.effective_chat.id)
    
def main() -> None:
    """Start the bot."""
    if BOT_TOKEN == "REPLACE_WITH_YOUR_TOKEN":
        raise RuntimeError(
            "Set your Telegram bot token in TELEGRAM_BOT_TOKEN or replace REPLACE_WITH_YOUR_TOKEN."
        )

    logger.info(f"Starting bot with Django backend at {DJANGO_API_BASE_URL}")
    logger.info(f"Payment status API: {NXTSTAR_API_URL}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_greeting))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(CommandHandler("debug", debug_chat))
    # ChatMemberHandler fires for both basic groups AND supergroups (left_chat_member
    # service messages are NOT delivered for supergroup leaves).
    app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    print("🤖 NxtStar Bot is starting...")
    print(f"📡 Django API: {DJANGO_API_BASE_URL}")
    print(f"💳 Payment API: {NXTSTAR_API_URL}")
    print("Press Ctrl+C to stop.")
    # chat_member updates must be explicitly requested in allowed_updates,
    # otherwise Telegram will not deliver them.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
