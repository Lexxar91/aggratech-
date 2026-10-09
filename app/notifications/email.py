import smtplib
from email.message import EmailMessage
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.notifications.models import AuditEvent
from app.notifications.queue import ClaimedJob, owned_job, utc_now


def send_auth_email(settings: Settings, job: ClaimedJob) -> None:
    """Посылает настоящее SMTP-письмо; токен находится во fragment, не в access log."""
    email = job.payload.get("email")
    token = job.payload.get("token")
    purpose = job.payload.get("purpose")
    if (
        not isinstance(email, str)
        or not isinstance(token, str)
        or purpose not in ("verify_email", "password_reset")
    ):
        raise ValueError("invalid_email_job")
    action = "verify" if purpose == "verify_email" else "reset"
    url = f"{settings.public_origin}/#{action}/{quote(token, safe='')}"
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = (
        "Подтверждение email" if action == "verify" else "Восстановление пароля"
    )
    message.set_content(
        f"Откройте ссылку:\n{url}\n\nСсылка одноразовая. "
        "Если вы не запрашивали действие, проигнорируйте письмо."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


async def finish_email(session: AsyncSession, job: ClaimedJob) -> bool:
    """Фиксирует доставку с fencing и удаляет секретный payload из очереди."""
    now = utc_now()
    row = await owned_job(session, job, now)
    if row is None:
        return False
    await session.execute(
        insert(AuditEvent)
        .values(
            id=uuid4(),
            action=f"{job.kind}_sent",
            entity_type="background_job",
            entity_id=job.id,
            safe_metadata={},
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["action", "entity_id"])
    )
    row.status = "succeeded"
    row.claim_token = None
    row.lease_until = None
    row.payload = {}
    return True


def send_invitation_email(settings: Settings, job: ClaimedJob) -> None:
    """Доставляет уведомление без имени и контактных значений кандидата."""
    email = job.payload.get("email")
    identifier = job.payload.get("invitation_id")
    status = job.payload.get("status")
    if (
        not isinstance(email, str)
        or not isinstance(identifier, str)
        or status not in ("sent", "accepted", "rejected", "withdrawn", "expired")
    ):
        raise ValueError("invalid_invitation_email")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = "Обновление приглашения"
    message.set_content(
        f"Статус приглашения: {status}.\n"
        f"{settings.public_origin}/#invitations/{quote(identifier, safe='')}\n\n"
        "Контакты доступны только по актуальному разрешению при открытии в кабинете."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)
