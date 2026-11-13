import os
import re
import glob
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import yt_dlp

TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

bot = telebot.TeleBot(TOKEN)

class SimpleHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Telegram Downloader Bot is running!")

    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHealthServer)
    server.serve_forever()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

URL_REGEX = r'(https?://[^\s]+)'

pending_requests = {}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك في بوت التحميل 📥\n\n"
        "أرسل لي أي رابط من (YouTube, TikTok, Instagram, Facebook, X, Pinterest) وسأقوم بتحميله لك مباشرة."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda msg: re.search(URL_REGEX, msg.text or ""))
def handle_url_message(message):
    urls = re.findall(URL_REGEX, message.text)
    if not urls:
        return
    url = urls[0]
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_video = types.InlineKeyboardButton("🎬 فيديو", callback_data=f"vid_{message.message_id}")
    btn_audio = types.InlineKeyboardButton("🎵 صوت", callback_data=f"aud_{message.message_id}")
    markup.add(btn_video, btn_audio)
    
    pending_requests[message.message_id] = url
    bot.reply_to(message, "اختر نوع التحميل المطلوب:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('vid_', 'aud_')))
def callback_download(call):
    mode, msg_id_str = call.data.split('_')
    msg_id = int(msg_id_str)
    
    url = pending_requests.get(msg_id)
    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية الطلب، أرسل الرابط مجدداً.")
        return
    
    bot.answer_callback_query(call.id)
    status_msg = bot.edit_message_text("⏳ جاري التحميل والمعالجة...", chat_id=call.message.chat.id, message_id=call.message.message_id)
    
    prefix = f"{call.from_user.id}_{msg_id}"
    out_template = os.path.join(DOWNLOAD_DIR, f"{prefix}_%(id)s.%(ext)s")
    
    if mode == 'vid':
        ydl_opts = {
            'format': 'best[filesize<48M]/best[ext=mp4]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 49 * 1024 * 1024,
        }
    else:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 49 * 1024 * 1024,
        }
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'تم التحميل')
            
        matched_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{prefix}_*"))
        if not matched_files:
            bot.edit_message_text("❌ لم يتم العثور على ملف بعد التحميل.", chat_id=call.message.chat.id, message_id=status_msg.message_id)
            return
            
        downloaded_file = matched_files[0]
        ext = os.path.splitext(downloaded_file)[1].lower()
        
        bot.edit_message_text("📤 جاري الرفع إلى تيليجرام...", chat_id=call.message.chat.id, message_id=status_msg.message_id)
        
        with open(downloaded_file, 'rb') as f:
            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                bot.send_photo(call.message.chat.id, f, caption=title)
            elif mode == 'aud' or ext in ['.mp3', '.m4a', '.wav', '.ogg', '.opus', '.aac']:
                bot.send_audio(call.message.chat.id, f, caption=title)
            else:
                bot.send_video(call.message.chat.id, f, caption=title, supports_streaming=True)
                
        bot.delete_message(chat_id=call.message.chat.id, message_id=status_msg.message_id)
        
    except Exception as e:
        err_msg = str(e)
        if "File is larger than the maximum allowed" in err_msg:
            bot.edit_message_text("❌ حجم الملف أكبر من الحد المسموح به في تيليجرام (50 MB).", chat_id=call.message.chat.id, message_id=status_msg.message_id)
        else:
            bot.edit_message_text(f"❌ حدث خطأ أثناء التحميل: {err_msg[:120]}", chat_id=call.message.chat.id, message_id=status_msg.message_id)
            
    finally:
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{prefix}_*")):
            try:
                os.remove(f)
            except Exception:
                pass
        pending_requests.pop(msg_id, None)

if __name__ == '__main__':
    print("Bot is running...")
    threading.Thread(target=start_health_server, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
