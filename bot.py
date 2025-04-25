import os
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    CallbackQueryHandler,
    filters
)
from pdf2image import convert_from_bytes
from PIL import Image
import cv2
import numpy as np
from io import BytesIO
import tempfile

# Настройки
TOKEN = "8013070807:AAFwDMOWX1qI11rPAbADZvaxx_5YahIGr_U"
DB_NAME = "pdf_bot.db"
OUTPUT_FOLDER = "processed_pdfs"
PREVIEW_PAGES = 5
PRICE = 100  # Стоимость полной версии в Stars
STARS_ADD_AMOUNT = 100  # Количество Stars за пополнение


# Параметры обработки по умолчанию
DEFAULT_SETTINGS = {
    'thickness': 2,
    'bg_color': (255, 255, 255),
    'ink_color': (0, 0, 0),
    'contrast': 3.0
}

# Инициализация логгера
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def init_db():
    """Инициализация базы данных"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY,
                      username TEXT,
                      balance INTEGER DEFAULT 50)''')


def get_user_balance(user_id: int) -> int:
    """Получение баланса пользователя"""
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]


def update_user_balance(user_id: int, amount: int):
    """Обновление баланса пользователя"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))


def process_image_page(img: Image, settings: dict) -> Image:
    """Обработка одной страницы изображения"""
    img_np = np.array(img)

    # Конвертация в оттенки серого
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

    # Улучшение контраста
    enhanced = cv2.convertScaleAbs(gray, alpha=settings['contrast'], beta=0)

    # Бинаризация
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Утолщение текста
    kernel = np.ones((settings['thickness'], settings['thickness']), np.uint8)
    processed = cv2.dilate(binary, kernel, iterations=1)

    # Создание результата
    result = np.full_like(img_np, settings['bg_color'])
    result[processed == 255] = settings['ink_color']

    return Image.fromarray(result)


async def process_pdf_file(pdf_bytes: BytesIO, settings: dict, pages: int = None) -> BytesIO:
    """Обработка PDF файла"""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_pdf:
        temp_pdf.write(pdf_bytes.getvalue())
        temp_pdf.flush()

        images = convert_from_bytes(
            pdf_bytes.getvalue(),
            first_page=1,
            last_page=pages,
            fmt='jpeg'
        )

    processed_images = [process_image_page(img, settings) for img in images]

    output = BytesIO()
    if len(processed_images) > 1:
        processed_images[0].save(
            output, format="PDF",
            save_all=True,
            append_images=processed_images[1:],
            quality=100
        )
    else:
        processed_images[0].save(output, format="PDF", quality=100)

    output.seek(0)
    return output


# Клавиатуры
def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню"""
    balance = get_user_balance(user_id)
    buttons = [
        [InlineKeyboardButton(f"💰 Баланс: {balance} Stars", callback_data="balance")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("🆘 Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(buttons)


def settings_keyboard() -> InlineKeyboardMarkup:
    """Меню настроек"""
    buttons = [
        [InlineKeyboardButton("🔢 Толщина линий", callback_data="set_thickness")],
        [InlineKeyboardButton("🎨 Цвет фона", callback_data="set_bg_color")],
        [InlineKeyboardButton("✒️ Цвет текста", callback_data="set_text_color")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(buttons)


def thickness_keyboard() -> InlineKeyboardMarkup:
    """Выбор толщины линий"""
    buttons = [
        [InlineKeyboardButton("Тонкие (1)", callback_data="thickness_1")],
        [InlineKeyboardButton("Средние (2)", callback_data="thickness_2")],
        [InlineKeyboardButton("Толстые (3)", callback_data="thickness_3")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_settings")]
    ]
    return InlineKeyboardMarkup(buttons)


def color_keyboard(color_type: str) -> InlineKeyboardMarkup:
    """Выбор цвета"""
    buttons = [
        [InlineKeyboardButton("⚪ Белый", callback_data=f"{color_type}_white")],
        [InlineKeyboardButton("⚫ Черный", callback_data=f"{color_type}_black")],
        [InlineKeyboardButton("🔵 Синий", callback_data=f"{color_type}_blue")],
        [InlineKeyboardButton("🔴 Красный", callback_data=f"{color_type}_red")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_settings")]
    ]
    return InlineKeyboardMarkup(buttons)


def payment_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Меню оплаты"""
    balance = get_user_balance(user_id)
    buttons = [
        [InlineKeyboardButton(f"⭐ Купить полную версию ({PRICE} Stars)", callback_data="buy_full")],
        [InlineKeyboardButton(f"💎 Пополнить баланс (+100 Stars)", callback_data="add_stars")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(buttons)


# Обработчики сообщений
async def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    user = update.effective_user
    update_user_balance(user.id, 0)  # Инициализация пользователя

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу улучшить качество рукописного текста в ваших PDF.\n\n"
        f"• Бесплатно: превью первых {PREVIEW_PAGES} страниц\n"
        f"• Полная версия: {PRICE} Stars\n\n"
        "Просто отправьте мне PDF файл или выберите действие:",
        reply_markup=main_menu_keyboard(user.id)
    )


async def handle_document(update: Update, context: CallbackContext):
    """Обработка полученного PDF"""
    user = update.effective_user
    document = update.message.document

    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            "📁 Файл слишком большой (максимум 50 МБ).\n\n"
            "Вы можете разбить PDF на части с помощью:\n"
            "• Онлайн-сервиса: https://www.ilovepdf.com/split_pdf\n"
            "• Или программы: Adobe Acrobat, PDFsam\n\n"
            "После разбивки отправьте мне файлы по одному.",
            reply_markup=main_menu_keyboard(user.id)
        )
        return

    # Сохраняем файл для обработки
    file = await document.get_file()
    pdf_bytes = BytesIO()
    await file.download_to_memory(out=pdf_bytes)
    context.user_data['pdf'] = pdf_bytes
    context.user_data['filename'] = document.file_name

    await update.message.reply_text(
        "Файл получен! Выберите действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Превью (бесплатно)", callback_data="preview")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
            [InlineKeyboardButton("💰 Баланс", callback_data="balance")]
        ])
    )


async def button_handler(update: Update, context: CallbackContext):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "settings":
        await query.edit_message_text(
            "⚙️ Настройки обработки:",
            reply_markup=settings_keyboard())

    elif query.data == "balance":
        balance = get_user_balance(user_id)
        await query.edit_message_text(
            f"💰 Ваш баланс: {balance} Stars\n\n"
            f"Полная обработка PDF: {PRICE} Stars",
            reply_markup=payment_keyboard(user_id))

    elif query.data == "preview":
        await query.edit_message_text("⏳ Готовлю превью...")

        try:
            preview_pdf = await process_pdf_file(
                context.user_data['pdf'],
                DEFAULT_SETTINGS,
                PREVIEW_PAGES
            )

            await context.bot.send_document(
                chat_id=user_id,
                document=preview_pdf,
                filename=f"preview_{context.user_data['filename']}"
            )

            await query.edit_message_text(
                f"🔍 Превью первых {PREVIEW_PAGES} страниц\n\n"
                f"Для полной версии нужно {PRICE} Stars",
                reply_markup=payment_keyboard(user_id))

        except Exception as e:
            logger.error(f"Ошибка превью: {e}")
            await query.edit_message_text(
                "❌ Ошибка при создании превью. Попробуйте другой файл.",
                reply_markup=main_menu_keyboard(user_id))

    elif query.data == "buy_full":
        balance = get_user_balance(user_id)

        if balance >= PRICE:
            update_user_balance(user_id, -PRICE)
            await query.edit_message_text("⏳ Обрабатываю полную версию...")

            try:
                full_pdf = await process_pdf_file(
                    context.user_data['pdf'],
                    DEFAULT_SETTINGS
                )

                await context.bot.send_document(
                    chat_id=user_id,
                    document=full_pdf,
                    filename=f"enhanced_{context.user_data['filename']}"
                )

                await query.edit_message_text(
                    f"✅ Готово! Списано {PRICE} Stars\n"
                    f"💰 Новый баланс: {balance - PRICE} Stars\n\n"
                    "Напишите /start если понадоблюсь ещё!",
                    reply_markup=main_menu_keyboard(user_id))

            except Exception as e:
                logger.error(f"Ошибка обработки: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при обработке файла. Попробуйте другой файл.",
                    reply_markup=main_menu_keyboard(user_id))

        else:
            await query.edit_message_text(
                f"❌ Недостаточно Stars. Нужно {PRICE}, у вас {balance}",
                reply_markup=payment_keyboard(user_id))

    elif query.data == "add_stars":
        update_user_balance(user_id, 100)
        await query.edit_message_text(
            "✅ Баланс пополнен на 100 Stars!",
            reply_markup=payment_keyboard(user_id))

    elif query.data.startswith("thickness_"):
        thickness = int(query.data.split("_")[1])
        DEFAULT_SETTINGS['thickness'] = thickness
        await query.edit_message_text(
            f"🔢 Толщина линий установлена: {thickness}",
            reply_markup=settings_keyboard())

    elif query.data.startswith(("bg_", "text_")):
        color_type, color = query.data.split("_")
        color_map = {
            'white': (255, 255, 255),
            'black': (0, 0, 0),
            'blue': (0, 0, 255),
            'red': (255, 0, 0)
        }

        if color_type == "bg":
            DEFAULT_SETTINGS['bg_color'] = color_map[color]
            await query.edit_message_text(
                f"🎨 Цвет фона: {color}",
                reply_markup=settings_keyboard())
        else:
            DEFAULT_SETTINGS['ink_color'] = color_map[color]
            await query.edit_message_text(
                f"✒️ Цвет текста: {color}",
                reply_markup=settings_keyboard())

    elif query.data == "back_to_settings":
        await query.edit_message_text(
            "⚙️ Настройки обработки:",
            reply_markup=settings_keyboard())

    elif query.data == "back_to_main":
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=main_menu_keyboard(user_id))

    elif query.data == "help":
        await query.edit_message_text(
            "ℹ️ Помощь:\n\n"
            "1. Отправьте мне PDF файл с рукописным текстом\n"
            "2. Получите бесплатное превью первых 5 страниц\n"
            "3. Для полной версии потребуются Stars\n\n"
            "Советы:\n"
            "• Максимальный размер файла: 50 МБ\n"
            "• Для больших файлов используйте: https://www.ilovepdf.com/split_pdf\n"
            "• Напишите /start чтобы вернуться в главное меню",
            reply_markup=main_menu_keyboard(user_id))


async def text_handler(update: Update, context: CallbackContext):
    """Обработчик текстовых сообщений"""
    text = update.message.text.lower()

    if text in ['привет', 'start', 'начать', 'меню']:
        await start(update, context)
    else:
        await update.message.reply_text(
            "Я понимаю только PDF файлы и команды меню.\n"
            "Напишите /start для отображения меню.",
            reply_markup=main_menu_keyboard(update.effective_user.id))


def main():
    """Запуск бота"""
    init_db()

    app = Application.builder().token(TOKEN).build()

    # Обработчики команд
    app.add_handler(CommandHandler("start", start))

    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Обработчики кнопок
    app.add_handler(CallbackQueryHandler(button_handler))

    # Запуск бота
    app.run_polling()


if __name__ == "__main__":
    main()