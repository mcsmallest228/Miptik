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
from PyPDF2 import PdfReader, PdfWriter


TOKEN = "8013070807:AAFwDMOWX1qI11rPAbADZvaxx_5YahIGr_U"
DB_NAME = "pdf_bot.db"
OUTPUT_FOLDER = "processed_pdfs"
PREVIEW_PAGES = 5
PRICE = 100  # Стоимость полной версии в Stars
STARS_ADD_AMOUNT = 100  # Количество Stars за пополнение

# Параметры по умолчанию
DEFAULT_SETTINGS = {
    'thickness': 3,
    'bg_color': (255, 255, 255),
    'ink_color': (0, 0, 0),
    'remove_bg': True,
    'contrast': 3.0
}

# Инициализация
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT,
                      balance INTEGER DEFAULT 50)''')
    conn.commit()
    conn.close()


init_db()


# Функции обработки изображений
def parse_color(color_str):
    color_map = {
        'white': (255, 255, 255),
        'black': (0, 0, 0),
        'blue': (0, 0, 255),
        'red': (255, 0, 0),
        'green': (0, 128, 0),
        'beige': (245, 245, 220),
        'light_pink': (255, 230, 230),
        'purple': (128, 0, 128)
    }

    if color_str.startswith('#'):
        return tuple(int(color_str[i:i + 2], 16) for i in (1, 3, 5))
    return color_map.get(color_str.lower(), (0, 0, 0))


def enhance_image(image, settings):
    img = np.array(image)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img

    enhanced = cv2.convertScaleAbs(gray, alpha=settings['contrast'], beta=0)
    _, binary = cv2.threshold(enhanced, 220, 255, cv2.THRESH_BINARY_INV)

    kernel = np.ones((settings['thickness'], settings['thickness']), np.uint8)
    thickened = cv2.dilate(binary, kernel, iterations=1)

    smoothed = cv2.GaussianBlur(thickened, (3, 3), 0)
    _, smoothed = cv2.threshold(smoothed, 100, 255, cv2.THRESH_BINARY)

    h, w = smoothed.shape
    if settings['remove_bg']:
        background = np.full((h, w, 3), settings['bg_color'], dtype=np.uint8)
    else:
        background = cv2.cvtColor(255 - binary, cv2.COLOR_GRAY2BGR)

    result = np.where(smoothed[..., None] == 255, settings['ink_color'], background)
    return Image.fromarray(result.astype('uint8'))


async def process_pdf(pdf_bytes, settings, preview=False):
    images = convert_from_bytes(
        pdf_bytes.getvalue(),
        first_page=1,
        last_page=PREVIEW_PAGES if preview else None,
        dpi=300
    )

    processed_images = []
    for img in images:
        processed_images.append(enhance_image(img, settings))

    output = BytesIO()
    if len(processed_images) > 1:
        processed_images[0].save(
            output, format="PDF",
            save_all=True,
            append_images=processed_images[1:]
        )
    else:
        processed_images[0].save(output, format="PDF")

    output.seek(0)
    return output


# Клавиатуры
def get_main_menu_keyboard(user_id=None):
    buttons = []

    if user_id:
        conn = sqlite3.connect(DB_NAME)
        balance = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
        conn.close()
        buttons.append([InlineKeyboardButton(f"💰 Баланс: {balance} Stars", callback_data="show_balance")])

    buttons.append([InlineKeyboardButton("⚙️ Настроить обработку", callback_data="open_settings")])
    return InlineKeyboardMarkup(buttons)


def get_settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Толщина линий", callback_data="set_thickness")],
        [InlineKeyboardButton("🎨 Цвет фона", callback_data="set_bg_color")],
        [InlineKeyboardButton("✒️ Цвет чернил", callback_data="set_ink_color")],
        [InlineKeyboardButton("🧹 Удалить фон: Да", callback_data="toggle_bg")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"),
            InlineKeyboardButton("👀 Превью", callback_data="send_preview")
        ]
    ])


def get_thickness_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Тонкие (1)", callback_data="thickness_1")],
        [InlineKeyboardButton("Средние (3)", callback_data="thickness_3")],
        [InlineKeyboardButton("Толстые (5)", callback_data="thickness_5")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_settings")]
    ])


def get_color_keyboard(color_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ Белый", callback_data=f"{color_type}_white")],
        [InlineKeyboardButton("⚫ Черный", callback_data=f"{color_type}_black")],
        [InlineKeyboardButton("🔵 Синий", callback_data=f"{color_type}_blue")],
        [InlineKeyboardButton("🔴 Красный", callback_data=f"{color_type}_red")],
        [InlineKeyboardButton("🟢 Зеленый", callback_data=f"{color_type}_green")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_settings")]
    ])


def get_payment_keyboard(user_id):
    conn = sqlite3.connect(DB_NAME)
    balance = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()

    buttons = [
        [InlineKeyboardButton(f"⭐ Купить полную версию ( {PRICE} Stars = {PRICE} РУБ)", callback_data="buy_full")],
        [InlineKeyboardButton(f"💎 Пополнить (+{STARS_ADD_AMOUNT} Stars = +{STARS_ADD_AMOUNT} РУБ)", callback_data="add_stars")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="open_settings")],
        [InlineKeyboardButton(f"💰 Баланс: {balance} Stars(РУБ)", callback_data="show_balance")]
    ]

    return InlineKeyboardMarkup(buttons)


# Обработчики
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                 (user.id, user.username))
    conn.commit()
    conn.close()

    context.user_data['settings'] = DEFAULT_SETTINGS.copy()

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "📄 Отправьте мне PDF для переката и я пришлю тебе твою версию для планшета \n\n"
        f"• Бесплатно: превью {PREVIEW_PAGES} страниц\n"
        f"• Полная версия: {PRICE} Stars",
        reply_markup=get_main_menu_keyboard(user.id)
    )




async def handle_settings(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "open_settings":
        await query.edit_message_text(
            "⚙️ Настройки обработки:",
            reply_markup=get_settings_keyboard()
        )
    elif query.data == "set_thickness":
        await query.edit_message_text(
            "Выберите толщину линий:",
            reply_markup=get_thickness_keyboard()
        )
    elif query.data == "set_bg_color":
        await query.edit_message_text(
            "Выберите цвет фона:",
            reply_markup=get_color_keyboard("bg")
        )
    elif query.data == "set_ink_color":
        await query.edit_message_text(
            "Выберите цвет чернил:",
            reply_markup=get_color_keyboard("ink")
        )
    elif query.data == "toggle_bg":
        context.user_data['settings']['remove_bg'] = not context.user_data['settings']['remove_bg']
        status = "Да" if context.user_data['settings']['remove_bg'] else "Нет"
        await query.edit_message_text(
            text=f"🧹 Удалить фон: {status}",
            reply_markup=get_settings_keyboard()
        )
    elif query.data.startswith("thickness_"):
        thickness = int(query.data.split("_")[1])
        context.user_data['settings']['thickness'] = thickness
        await query.edit_message_text(
            text=f"🔢 Толщина линий: {thickness}",
            reply_markup=get_settings_keyboard()
        )
    elif query.data.startswith(("bg_", "ink_")):
        color_type, color = query.data.split("_")
        color_rgb = parse_color(color)

        if color_type == "bg":
            context.user_data['settings']['bg_color'] = color_rgb
            await query.edit_message_text(
                text=f"🎨 Цвет фона: {color}",
                reply_markup=get_settings_keyboard()
            )
        else:
            context.user_data['settings']['ink_color'] = color_rgb
            await query.edit_message_text(
                text=f"✒️ Цвет чернил: {color}",
                reply_markup=get_settings_keyboard()
            )
    elif query.data == "back_to_settings":
        await query.edit_message_text(
            "⚙️ Настройки обработки:",
            reply_markup=get_settings_keyboard()
        )
    elif query.data == "back_to_main":
        await query.edit_message_text(
            "✅ Настройки сохранены! Нажмите превью чтобы посмотреть",
            reply_markup=get_payment_keyboard(query.from_user.id)
        )
    elif query.data == "send_preview":
        await query.edit_message_text("⏳ Готовлю превью...")

        try:
            preview = await process_pdf(
                context.user_data['pdf_bytes'],
                context.user_data['settings'],
                preview=True
            )

            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=preview,
                filename=f"preview_{context.user_data['filename']}"
            )

            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"🔍 Превью первых {PREVIEW_PAGES} страниц\n",
                reply_markup=get_payment_keyboard(query.from_user.id)
            )
        except Exception as e:
            logger.error(f"Ошибка генерации превью: {e}")
            await query.edit_message_text("❌ Ошибка при создании превью.")


async def handle_payment(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "buy_full":
        user_id = query.from_user.id
        conn = sqlite3.connect(DB_NAME)
        balance = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

        if balance >= PRICE:
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                         (PRICE, user_id))
            conn.commit()
            conn.close()

            await query.edit_message_text("⏳ Обрабатываю полную версию...")

            try:
                full_pdf = await process_pdf(
                    context.user_data['pdf_bytes'],
                    context.user_data['settings']
                )

                await context.bot.send_document(
                    chat_id=user_id,
                    document=full_pdf,
                    filename=f"enhanced_{context.user_data['filename']}"
                )

                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Готово! Списано {PRICE} Stars\n"
                         f"⭐ Новый баланс: {balance - PRICE} Stars"
                         f"напиши мне '/start' когда снова понадоблюсь!",
                    reply_markup=get_main_menu_keyboard(user_id)
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Напиши мне '/start', если еще раз понадоблюсь!"
                )

            except Exception as e:
                logger.error(f"Ошибка обработки: {e}")
                await query.edit_message_text("❌ Ошибка при обработке файла.")
        else:
            conn.close()
            await query.edit_message_text(
                f"❌ Недостаточно Stars. Нужно {PRICE}, у вас {balance}, пополните баланс (1 рубль=1 STAR)",
                reply_markup=get_payment_keyboard(user_id)
            )

    elif query.data == "add_stars":
        user_id = query.from_user.id
        conn = sqlite3.connect(DB_NAME)
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                     (STARS_ADD_AMOUNT, user_id))
        conn.commit()
        new_balance = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]
        conn.close()

        await query.edit_message_text(
            f"✅ Баланс пополнен на {STARS_ADD_AMOUNT} Stars!\n"
            f"⭐ Новый баланс: {new_balance} Stars",
            reply_markup=get_payment_keyboard(user_id)
        )
    elif query.data == "show_balance":
        conn = sqlite3.connect(DB_NAME)
        balance = conn.execute("SELECT balance FROM users WHERE user_id = ?", (query.from_user.id,)).fetchone()[0]
        conn.close()
        await query.answer(f"Ваш баланс: {balance} Stars (РУБ)", show_alert=True)
    elif query.data == "open_settings":
        await query.edit_message_text(
            "⚙️ Настройки обработки:",
            reply_markup=get_settings_keyboard()
        )

# Обработчик слишком большого PDF
async def handle_pdf(update: Update, context: CallbackContext):
    user = update.effective_user
    file = await update.message.document.get_file()

    if file.file_size > 45 * 1024 * 1024:
        await update.message.reply_text(
            "❌ Файл слишком большой (максимум 45 МБ). Попробуйте разбить его на части с помощью сайта "
            "iLovePDF: https://www.ilovepdf.com/split_pdf "
            "Чтобы попробовать снова напиши мне '/start' "
        )
        return

    pdf_bytes = BytesIO()
    await file.download_to_memory(out=pdf_bytes)
    pdf_bytes.seek(0)

    context.user_data['pdf_bytes'] = pdf_bytes
    context.user_data['filename'] = update.message.document.file_name

    await update.message.reply_text(
        "⚙️ Настройте параметры обработки:",
        reply_markup=get_settings_keyboard()
    )


# Клавиатура с кнопками "Назад" и "Сейчас пришлю"
def get_file_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")],
        [InlineKeyboardButton("📤 Сейчас пришлю", callback_data="send_pdf")]
    ])

# Обработчик кнопки "Сейчас пришлю"
async def send_pdf(update: Update, context: CallbackContext):
    user_id = update.callback_query.from_user.id
    pdf_bytes = context.user_data.get('pdf_bytes')

    if pdf_bytes:
        await update.callback_query.edit_message_text("⏳ Готовлю PDF...")

        try:
            pdf = await process_pdf(
                pdf_bytes,
                context.user_data['settings']
            )

            await context.bot.send_document(
                chat_id=user_id,
                document=pdf,
                filename=f"processed_{context.user_data['filename']}"
            )

            await context.bot.send_message(
                chat_id=user_id,
                text="✅ PDF обработан! Напиши мне '/start', если понадоблюсь снова.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            await update.callback_query.edit_message_text("❌ Ошибка при обработке PDF.")

# Запуск бота
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(
        CallbackQueryHandler(handle_settings, pattern="^(set_|toggle_|thickness_|bg_|ink_|open_|back_|send_)"))
    app.add_handler(CallbackQueryHandler(handle_payment, pattern="^(buy_|show_|add_)"))

    app.run_polling()


if __name__ == "__main__":
    main()
