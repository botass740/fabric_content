import asyncio
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.database.db import Database, STATUS_APPROVED, STATUS_GENERATED, STATUS_REJECTED, STATUS_PUBLISHED
from app.publishers.dzen_publisher import DzenPublisher
from app.generators.article_plan import generate_article_plan
from app.generators.articles import generate_article
from app.generators.images import generate_cover
from app.generators.titles import generate_titles
from app.generators.topics import generate_topics
from app.generators.topic_matrix import pick_combination
from app.context.refresh import refresh_via_llm, apply_weekly_hot, parse_raw_input
from app.context.trends import load_trend_context

logger = logging.getLogger(__name__)


def is_admin(settings, user_id: int | None) -> bool:
    if settings.telegram_admin_id is None:
        return True
    return user_id == settings.telegram_admin_id


def chunk_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


def build_actions_keyboard(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"pub:{article_id}"),
            InlineKeyboardButton("🔄 Перегенерировать", callback_data=f"regen:{article_id}"),
        ],
        [
            InlineKeyboardButton("❌ Удалить", callback_data=f"del:{article_id}"),
        ],
    ])


async def send_article_preview(bot, chat_id: int, article: dict) -> None:
    title = article.get("title", "")
    content = article.get("content", "")
    image_path = article.get("image_path")
    status = article.get("status", "")
    article_id = article.get("id")

    # Отправка фото
    if image_path and Path(image_path).exists():
        try:
            with open(image_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=title[:1000],
                )
        except Exception as e:
            logger.warning(f"Failed to send photo: {e}")
            await bot.send_message(chat_id=chat_id, text=f"Заголовок: {title}")
    else:
        await bot.send_message(chat_id=chat_id, text=f"Заголовок: {title}")

    # Отправка текста статьи кусками
    chunks = chunk_text(content)
    for chunk in chunks:
        await bot.send_message(chat_id=chat_id, text=chunk)

    # Финальное сообщение с кнопками
    status_text = f"Статус: {status}\nID: {article_id}"
    await bot.send_message(
        chat_id=chat_id,
        text=status_text,
        reply_markup=build_actions_keyboard(article_id),
    )


def generate_full_article_payload(settings, db: Database) -> tuple[str, str, str, str | None]:
    # 0. Один срез актуального фона на всю генерацию —
    # чтобы тема, план и статья видели один и тот же контекст
    live_triggers = load_trend_context(settings, logger=logger)

    # 1. Выбираем комбинацию осей (архетип героя, эмоция, формат, триггер, тип хука)
    combination = pick_combination(db, logger=logger)

    # 2. Темы в этой комбинации
    recent = db.recent_topics(limit=30)
    topics = generate_topics(
        settings,
        combination=combination,
        live_triggers=live_triggers,
        recent_topics=recent,
        n=3,
    )
    topic = topics[0] if topics else "финансовые ошибки в быту"

    # 3. Заголовки под hook_type
    titles = generate_titles(
        settings,
        topic=topic,
        hook_type=combination["hook_type"],
        hero=combination["hero"],
        n=6,
    )
    title = titles[0] if titles else topic

    # 4. План статьи с голосом рассказчика
    plan = generate_article_plan(
        settings,
        topic=topic,
        title=title,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        live_triggers=live_triggers,
    )

    # 5. Статья
    content = generate_article(
        settings,
        topic=topic,
        title=title,
        plan=plan,
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        live_triggers=live_triggers,
    )

    # 6. Обложка
    image_path = generate_cover(settings, topic=topic, title=title, content=content)

    # 7. Регистрируем использованную комбинацию (article_id проставится позже — после create_article)
    db.register_combination(
        hero=combination["hero"],
        emotion=combination["emotion"],
        format=combination["format"],
        trigger=combination["trigger"],
        hook_type=combination["hook_type"],
        topic=topic,
    )

    return topic, title, content, image_path


# ========================= Handlers =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    if not is_admin(settings, update.effective_user.id):
        return

    text = """
🤖 Бот генерации и публикации статей в Дзен

📋 Команды:

/generate — создать новую статью
/queue — очередь на публикацию
/list — последние статьи
/stats — статистика
/publish_last — опубликовать последнюю одобренную

🌡 Актуальный фон:
/refresh_trends — сгенерировать черновик горячих тем недели (LLM)
/set_weekly <текст> — вручную задать горячие темы недели
/show_trends — показать текущие триггеры

После генерации нажми:
✅ Опубликовать — одобрить и опубликовать в Дзен
🔄 Перегенерировать — создать новый вариант
❌ Удалить — отклонить статью
""".strip()
    await update.message.reply_text(text)


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    await update.message.reply_text("Генерирую статью... это может занять 1-2 минуты.")

    try:
        topic, title, content, image_path = await asyncio.to_thread(
            generate_full_article_payload, settings, db
        )

        article_id = db.create_article(
            title=title,
            content=content,
            image_path=image_path,
            status=STATUS_GENERATED,
        )
        article = db.get_article(article_id)

        await send_article_preview(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            article=article,
        )

    except Exception:
        logger.exception("Error in /generate handler")
        await update.message.reply_text("Ошибка генерации, см. логи.")


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    articles = db.list_queue(limit=10)

    if not articles:
        await update.message.reply_text("Очередь пуста.")
        return

    lines = []
    for a in articles:
        title_short = a["title"][:50] + "..." if len(a["title"]) > 50 else a["title"]
        lines.append(f"#{a['id']} [{a['status']}] {title_short}")

    await update.message.reply_text("\n".join(lines))


async def publish_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    publisher: DzenPublisher = context.application.bot_data.get("publisher")

    if not is_admin(settings, update.effective_user.id):
        return

    last = db.get_last(status=STATUS_APPROVED)

    if not last:
        await update.message.reply_text(
            "Нет одобренных статей. Нажмите 'Опубликовать' под превью."
        )
        return

    # Проверка статуса
    if last["status"] == STATUS_PUBLISHED:
        await update.message.reply_text(f"Статья #{last['id']} уже опубликована")
        return

    # Проверка на дубли заголовка
    all_published = db.list_articles(status=STATUS_PUBLISHED, limit=100)
    for pub in all_published:
        if pub["title"].strip().lower() == last["title"].strip().lower():
            await update.message.reply_text(
                f"⚠️ Дубль!\nСтатья #{pub['id']} с таким же заголовком уже опубликована {pub['published_at']}"
            )
            return

    await update.message.reply_text(
        f"Публикую статью #{last['id']}...\n{last['title'][:60]}"
    )

    try:
        result = await asyncio.to_thread(
            publisher.publish_article,
            title=last["title"],
            content=last["content"],
            image_path=last["image_path"],
        )
        if result.ok:
            db.set_status(last["id"], STATUS_PUBLISHED)
            msg = f"Статья #{last['id']} опубликована!"
            if result.url:
                msg += f"\nURL: {result.url}"
            await update.message.reply_text(msg)
        else:
            msg = f"Ошибка публикации: {result.error}"
            if result.screenshot_path:
                msg += f"\nСкриншот: {result.screenshot_path}"
            await update.message.reply_text(msg)
    except Exception:
        logger.exception("Error in publish_last")
        await update.message.reply_text("Критическая ошибка публикации, см. логи.")


# ========================= Статистика =========================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    # Получаем статистику
    from app.database.db import STATUS_GENERATED, STATUS_APPROVED, STATUS_PUBLISHED, STATUS_REJECTED

    generated = db.list_articles(status=STATUS_GENERATED, limit=1000)
    approved = db.list_articles(status=STATUS_APPROVED, limit=1000)
    published = db.list_articles(status=STATUS_PUBLISHED, limit=1000)
    rejected = db.list_articles(status=STATUS_REJECTED, limit=1000)

    # Последняя публикация
    last_pub = db.get_last(status=STATUS_PUBLISHED)
    last_pub_text = ""
    if last_pub:
        last_pub_text = f"\n📅 Последняя публикация:\n{last_pub['published_at']}"

    msg = f"""
📊 Статистика канала

✏️ Сгенерировано: {len(generated)}
✅ Одобрено: {len(approved)}
📰 Опубликовано: {len(published)}
❌ Отклонено: {len(rejected)}
{last_pub_text}

💡 Используй:
/list - посмотреть последние статьи
/queue - очередь на публикацию
/generate - создать новую статью
""".strip()

    await update.message.reply_text(msg)


async def list_articles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    # Получаем последние 10 статей всех статусов
    all_recent = db.list_articles(status=None, limit=10, offset=0)

    if not all_recent:
        await update.message.reply_text("Статей пока нет. Используй /generate")
        return

    lines = ["📝 Последние статьи:\n"]
    for a in all_recent:
        # Форматируем статус эмодзи
        status_emoji = {
            "generated": "✏️",
            "approved": "✅",
            "published": "📰",
            "rejected": "❌"
        }.get(a["status"], "❓")

        # Обрезаем заголовок
        title_short = a["title"][:60] + "..." if len(a["title"]) > 60 else a["title"]

        # Время
        created = a["created_at"].split()[0] if a["created_at"] else "???"

        lines.append(f"{status_emoji} #{a['id']} | {created}\n{title_short}\n")

    await update.message.reply_text("\n".join(lines))


# ========================= Callback Handler =========================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    query = update.callback_query

    if not is_admin(settings, query.from_user.id):
        await query.answer("Нет доступа.")
        return

    data = query.data

    # Trend Layer callbacks (без article_id)
    if data == "trends_apply":
        blocks = context.application.bot_data.get("pending_trends") or []
        if not blocks:
            await query.answer("Нет черновика для применения.")
            return
        try:
            await asyncio.to_thread(apply_weekly_hot, settings, blocks, logger=logger)
        except Exception:
            logger.exception("apply_weekly_hot failed")
            await query.answer("Ошибка записи, см. логи.")
            return
        context.application.bot_data["pending_trends"] = None
        await query.answer("Применено ✅")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"weekly_hot.txt обновлён: {len(blocks)} пунктов. Следующая /generate уже увидит новый фон.",
        )
        return

    if data == "trends_cancel":
        context.application.bot_data["pending_trends"] = None
        await query.answer("Отменено ❌")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    try:
        action, article_id_str = data.split(":", 1)
        article_id = int(article_id_str)
    except Exception:
        await query.answer("Неверный формат.")
        return

    # Кнопка: Опубликовать
    if action == "pub":
        article = db.get_article(article_id)
        if not article:
            await query.answer("Статья не найдена.")
            return

        # Проверяем что статья ещё не опубликована
        if article["status"] == STATUS_PUBLISHED:
            await query.answer("Эта статья уже опубликована")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except:
                pass
            return

        # Проверяем нет ли дублей заголовка среди опубликованных
        all_published = db.list_articles(status=STATUS_PUBLISHED, limit=100)
        for pub in all_published:
            if pub["title"].strip().lower() == article["title"].strip().lower():
                await query.answer("Статья с таким заголовком уже опубликована")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"⚠️ Найден дубль!\n\nСтатья #{pub['id']} имеет такой же заголовок:\n{pub['title']}\n\nОпубликована: {pub['published_at']}"
                )
                return

        publisher: DzenPublisher = context.application.bot_data.get("publisher")

        db.set_status(article_id, STATUS_APPROVED)
        try:
            await query.answer("Публикую...")
        except Exception:
            pass  # Telegram timeout — не критично, публикуем дальше
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            result = await asyncio.to_thread(
                publisher.publish_article,
                title=article["title"],
                content=article["content"],
                image_path=article["image_path"],
            )

            if result.ok:
                db.set_status(article_id, STATUS_PUBLISHED)
                msg = f"Статья #{article_id} опубликована!"
                if result.url:
                    msg += f"\nURL: {result.url}"
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=msg,
                )
            else:
                msg = f"Ошибка публикации: {result.error}"
                if result.screenshot_path:
                    msg += f"\nСкриншот: {result.screenshot_path}"
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=msg,
                )
        except Exception:
            logger.exception(f"Error publishing article #{article_id}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Критическая ошибка публикации, см. логи.",
            )

    # Кнопка: Удалить
    elif action == "del":
        db.set_status(article_id, STATUS_REJECTED)
        await query.answer("Удалено ❌")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Кнопка: Перегенерировать
    elif action == "regen":
        await query.answer("Перегенерирую... подождите.")
        old = db.get_article(article_id)
        if not old:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Статья #{article_id} не найдена.",
            )
            return
        try:
            seed_topic = old["title"]
            def _regen(settings, db, seed_topic):
                # Для перегенерации выбираем НОВУЮ комбинацию —
                # это даёт разнообразный второй вариант вместо копии первого.
                combination = pick_combination(db, logger=logger)
                # Свежий срез фона на перегенерацию
                live_triggers = load_trend_context(settings, logger=logger)
                new_titles = generate_titles(
                    settings,
                    topic=seed_topic,
                    hook_type=combination["hook_type"],
                    hero=combination["hero"],
                    n=6,
                )
                new_title = new_titles[0] if new_titles else seed_topic
                new_plan = generate_article_plan(
                    settings,
                    topic=seed_topic,
                    title=new_title,
                    hero=combination["hero"],
                    emotion=combination["emotion"],
                    format=combination["format"],
                    live_triggers=live_triggers,
                )
                new_content = generate_article(
                    settings,
                    topic=seed_topic,
                    title=new_title,
                    plan=new_plan,
                    hero=combination["hero"],
                    emotion=combination["emotion"],
                    format=combination["format"],
                    live_triggers=live_triggers,
                )
                new_image = generate_cover(settings, topic=seed_topic, title=new_title, content=new_content)
                db.register_combination(
                    hero=combination["hero"],
                    emotion=combination["emotion"],
                    format=combination["format"],
                    trigger=combination["trigger"],
                    hook_type=combination["hook_type"],
                    topic=seed_topic,
                    article_id=article_id,
                )
                return new_title, new_content, new_image
            new_title, new_content, new_image = await asyncio.to_thread(
                _regen, settings, db, seed_topic
            )
            db.update_article(
                article_id,
                title=new_title,
                content=new_content,
                image_path=new_image,
            )
            db.set_status(article_id, STATUS_GENERATED)
            article = db.get_article(article_id)
            await send_article_preview(
                bot=context.bot,
                chat_id=query.message.chat_id,
                article=article,
            )
        except Exception:
            logger.exception(f"Error regenerating article #{article_id}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Ошибка перегенерации статьи #{article_id}, см. логи.",
            )


# ========================= Trend Layer =========================

def _build_trends_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Применить", callback_data="trends_apply"),
            InlineKeyboardButton("❌ Отмена", callback_data="trends_cancel"),
        ],
    ])


def _format_blocks_preview(blocks: list[str]) -> str:
    lines = []
    for i, b in enumerate(blocks, 1):
        lines.append(f"{i}. {b}")
    return "\n\n".join(lines)


async def cmd_refresh_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]

    if not is_admin(settings, update.effective_user.id):
        return

    await update.message.reply_text("Собираю черновик горячих тем недели... ~30 секунд.")

    try:
        blocks = await asyncio.to_thread(refresh_via_llm, settings, logger=logger)
    except Exception:
        logger.exception("refresh_via_llm failed")
        await update.message.reply_text("Ошибка при генерации черновика, см. логи.")
        return

    if not blocks:
        await update.message.reply_text("Модель не вернула ни одного пункта. Попробуй ещё раз или используй /set_weekly.")
        return

    context.application.bot_data["pending_trends"] = blocks

    preview = _format_blocks_preview(blocks)
    await update.message.reply_text(
        f"🌡 Черновик горячих тем ({len(blocks)} шт.):\n\n{preview}",
        reply_markup=_build_trends_preview_keyboard(),
    )


async def cmd_set_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]

    if not is_admin(settings, update.effective_user.id):
        return

    raw = update.message.text or ""
    # Убираем саму команду
    if raw.startswith("/set_weekly"):
        raw = raw[len("/set_weekly"):].lstrip()

    if not raw.strip():
        await update.message.reply_text(
            "Использование: /set_weekly <текст>\n\n"
            "Пункты разделяй пустой строкой или нумерацией (1., 2., ...).\n"
            "Пример:\n"
            "/set_weekly 1. Новые квитанции за ЖКХ, рост 10-15%.\n"
            "2. WB и Ozon: подделки Apple и БАДы.\n"
            "3. Отпуск в Сочи дороже Турции."
        )
        return

    blocks = parse_raw_input(raw)
    if not blocks:
        await update.message.reply_text("Не удалось распарсить пункты. Разделяй их пустой строкой или нумерацией.")
        return

    context.application.bot_data["pending_trends"] = blocks

    preview = _format_blocks_preview(blocks)
    await update.message.reply_text(
        f"Распознал {len(blocks)} пунктов:\n\n{preview}",
        reply_markup=_build_trends_preview_keyboard(),
    )


async def cmd_show_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]

    if not is_admin(settings, update.effective_user.id):
        return

    # Показываем полный контекст, как его увидит промт (не сэмпл, а весь)
    from app.context.trends import _load_file, _MONTHLY_FILE, _WEEKLY_FILE

    monthly = _load_file(settings, _MONTHLY_FILE, logger)
    weekly = _load_file(settings, _WEEKLY_FILE, logger)

    parts = []
    parts.append(f"📅 Weekly ({len(weekly)}):")
    if weekly:
        for i, b in enumerate(weekly, 1):
            parts.append(f"  {i}. {b[:200]}")
    else:
        parts.append("  (пусто — используй /refresh_trends или /set_weekly)")

    parts.append("")
    parts.append(f"🗓 Monthly ({len(monthly)}):")
    if monthly:
        for i, b in enumerate(monthly, 1):
            parts.append(f"  {i}. {b[:200]}")
    else:
        parts.append("  (пусто — обнови вручную app/context/monthly_triggers.txt)")

    msg = "\n".join(parts)
    for chunk in chunk_text(msg):
        await update.message.reply_text(chunk)


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открывает браузер для входа в Дзен и ждёт завершения авторизации."""
    settings = context.application.bot_data["settings"]

    if not is_admin(settings, update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    await update.message.reply_text("🟡 Открываю браузер для входа в Дзен...")

    def _login_sync():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            user_data_dir = str(settings.playwright_user_data_path)
            context = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                slow_mo=50,
            )
            page = context.new_page() if not context.pages else context.pages[0]
            try:
                page.goto(settings.dzen_editor_url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                if "passport" in page.url.lower() or "auth" in page.url.lower():
                    page.wait_for_function(
                        "!window.location.href.includes('passport') && !window.location.href.includes('auth')",
                        timeout=120000,
                    )
                    page.wait_for_load_state("networkidle", timeout=15000)
                    return True, page.url
                return True, page.url
            except Exception:
                return False, page.url
            finally:
                context.close()

    try:
        ok, url = await asyncio.to_thread(_login_sync)
        if ok:
            await update.message.reply_text(f"✅ Успешный вход в Дзен!\nURL: {url}")
        else:
            await update.message.reply_text("❌ Время входа истекло. Попробуйте ещё раз командой /login.")
    except Exception as e:
        logger.exception("Login error")
        await update.message.reply_text(f"❌ Ошибка при входе: {e}")


def run_bot(settings, db: Database, publisher: DzenPublisher = None) -> None:
    # Отключаем системный прокси (SOCKS4) для httpx
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["publisher"] = publisher
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("generate", generate))
    application.add_handler(CommandHandler("queue", queue))
    application.add_handler(CommandHandler("list", list_articles_cmd))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("publish_last", publish_last))
    application.add_handler(CommandHandler("login", cmd_login))
    application.add_handler(CommandHandler("refresh_trends", cmd_refresh_trends))
    application.add_handler(CommandHandler("set_weekly", cmd_set_weekly))
    application.add_handler(CommandHandler("show_trends", cmd_show_trends))
    application.add_handler(CallbackQueryHandler(on_callback))
    logger.info("Bot started, polling...")
    application.run_polling(drop_pending_updates=True)
