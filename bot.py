import os
import re
import glob
import threading
import json
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import yt_dlp

TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN and os.path.exists('.env'):
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('BOT_TOKEN='):
                    TOKEN = line.strip().split('=', 1)[1]
                    break
    except Exception:
        pass

bot = telebot.TeleBot(TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

URL_REGEX = r'(https?://[^\s]+)'
INSTA_REGEX = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([^/?#&]+)'

media_links = {}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك في بوت التحميل المباشر 📥\n\n"
        "أرسل لي أي رابط من (Instagram, TikTok, YouTube, Facebook, X, Pinterest) وسأقوم بتحميل الصور أو الفيديوهات فوراً بأعلى دقة دون أي أسئلة أو خطوات إضافية."
    )
    bot.reply_to(message, welcome_text)

def process_instagram(url, chat_id, status_msg):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'all': {'impersonate': ['chrome']}},
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ie = ydl.get_info_extractor('Instagram')
        ie.raise_no_formats = lambda *args, **kwargs: None
        
        try:
            res = ie._real_extract(url)
        except Exception:
            res = ie.extract(url)
            
        if not res:
            return False
            
        caption = (res.get('description') or res.get('title') or "")[:1000]
        
        entries = res.get('entries')
        if entries is not None:
            items = list(entries)
        else:
            items = [res]
            
        media_items = []
        for item in items:
            formats = item.get('formats')
            if formats:
                vid_url = formats[-1].get('url')
                media_items.append(('video', vid_url))
            else:
                thumbs = item.get('thumbnails', [])
                if thumbs:
                    img_url = thumbs[-1].get('url')
                    media_items.append(('photo', img_url))
                elif item.get('url'):
                    media_items.append(('photo', item.get('url')))
                    
        if not media_items:
            return False

        if len(media_items) == 1 and media_items[0][0] == 'video':
            process_video_download(url, chat_id, status_msg, mode='vid')
            return True
            
        if len(media_items) == 1 and media_items[0][0] == 'photo':
            req = urllib.request.Request(media_items[0][1], headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=30).read()
            bot.send_photo(chat_id, data, caption=caption or None)
            try:
                bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
            except Exception:
                pass
            return True

        chunk_size = 10
        for i in range(0, len(media_items), chunk_size):
            chunk = media_items[i:i + chunk_size]
            if len(chunk) == 1:
                m_type, m_url = chunk[0]
                req = urllib.request.Request(m_url, headers={'User-Agent': 'Mozilla/5.0'})
                data = urllib.request.urlopen(req, timeout=30).read()
                if m_type == 'video':
                    bot.send_video(chat_id, data, caption=caption if i == 0 else None)
                else:
                    bot.send_photo(chat_id, data, caption=caption if i == 0 else None)
            else:
                group = []
                for j, (m_type, m_url) in enumerate(chunk):
                    item_cap = caption if (i == 0 and j == 0) else None
                    req = urllib.request.Request(m_url, headers={'User-Agent': 'Mozilla/5.0'})
                    data = urllib.request.urlopen(req, timeout=30).read()
                    if m_type == 'video':
                        group.append(types.InputMediaVideo(data, caption=item_cap))
                    else:
                        group.append(types.InputMediaPhoto(data, caption=item_cap))
                if group:
                    bot.send_media_group(chat_id, group)
                    
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass
        return True

def process_video_download(url, chat_id, status_msg, mode='vid'):
    prefix = f"{chat_id}_{int(threading.get_ident())}"
    out_template = os.path.join(DOWNLOAD_DIR, f"{prefix}_%(id)s.%(ext)s")
    
    if mode == 'aud':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 49 * 1024 * 1024,
            'extractor_args': {'all': {'impersonate': ['chrome']}},
        }
    else:
        ydl_opts = {
            'format': 'best[filesize<48M]/best[ext=mp4]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 49 * 1024 * 1024,
            'extractor_args': {'all': {'impersonate': ['chrome']}},
        }
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'تم التحميل')
            
        matched_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{prefix}_*"))
        if not matched_files:
            bot.edit_message_text("❌ تعذر العثور على الملف بعد التحميل.", chat_id=chat_id, message_id=status_msg.message_id)
            return
            
        downloaded_file = matched_files[0]
        ext = os.path.splitext(downloaded_file)[1].lower()
        
        with open(downloaded_file, 'rb') as f:
            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                bot.send_photo(chat_id, f, caption=title)
            elif mode == 'aud' or ext in ['.mp3', '.m4a', '.wav', '.ogg', '.opus', '.aac']:
                bot.send_audio(chat_id, f, caption=title)
            else:
                markup = types.InlineKeyboardMarkup()
                cb_key = f"aud_{chat_id}_{status_msg.message_id}"
                media_links[cb_key] = url
                markup.add(types.InlineKeyboardButton("🎵 استخراج الصوت", callback_data=cb_key))
                bot.send_video(chat_id, f, caption=title, supports_streaming=True, reply_markup=markup)
                
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass
        
    except Exception as e:
        err_msg = str(e)
        if "No video formats found" in err_msg:
            bot.edit_message_text("❌ هذا المنشور عبارة عن ألبوم صور ولا يحتوي على أي مقطع فيديو.", chat_id=chat_id, message_id=status_msg.message_id)
        elif "empty media response" in err_msg or "login" in err_msg.lower():
            bot.edit_message_text("❌ هذا المحتوى مقيد أو الحساب خاص ويتطلب تسجيل دخول.", chat_id=chat_id, message_id=status_msg.message_id)
        elif "File is larger than the maximum allowed" in err_msg:
            bot.edit_message_text("❌ حجم الملف أكبر من الحد المسموح به في تيليجرام (50 MB).", chat_id=chat_id, message_id=status_msg.message_id)
        else:
            bot.edit_message_text(f"❌ حدث خطأ أثناء التحميل: {err_msg[:120]}", chat_id=chat_id, message_id=status_msg.message_id)
    finally:
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{prefix}_*")):
            try:
                os.remove(f)
            except Exception:
                pass

@bot.message_handler(func=lambda msg: re.search(URL_REGEX, msg.text or ""))
def handle_url_message(message):
    urls = re.findall(URL_REGEX, message.text)
    if not urls:
        return
    url = urls[0]
    
    status_msg = bot.reply_to(message, "⏳ جاري الفحص والتحميل المباشر بأعلى دقة...")
    
    if 'instagram.com' in url:
        try:
            if process_instagram(url, message.chat.id, status_msg):
                return
        except Exception as e:
            err_str = str(e)
            if "login" in err_str.lower() or "checkpoint" in err_str.lower():
                bot.edit_message_text("❌ هذا الحساب خاص أو المنشور مقيد ويتطلب تسجيل دخول.", chat_id=message.chat.id, message_id=status_msg.message_id)
                return
            
    process_video_download(url, message.chat.id, status_msg, mode='vid')

@bot.callback_query_handler(func=lambda call: call.data.startswith('aud_'))
def callback_extract_audio(call):
    url = media_links.get(call.data)
    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية الطلب.")
        return
    bot.answer_callback_query(call.id)
    status_msg = bot.send_message(call.message.chat.id, "⏳ جاري استخراج الصوت...")
    process_video_download(url, call.message.chat.id, status_msg, mode='aud')

class WebhookServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Telegram Downloader Bot is running!")

    def do_POST(self):
        clean_path = self.path.split('?')[0].strip('/')
        if clean_path == TOKEN:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            json_string = post_data.decode('utf-8')
            update = types.Update.de_json(json_string)
            if update:
                threading.Thread(target=bot.process_new_updates, args=([update],)).start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    is_render = (
        os.environ.get('RENDER') == 'true' or 
        bool(os.environ.get('RENDER_SERVICE_ID')) or 
        bool(os.environ.get('RENDER_EXTERNAL_HOSTNAME')) or
        bool(os.environ.get('RENDER_EXTERNAL_URL'))
    )

    if is_render:
        host = os.environ.get('RENDER_EXTERNAL_HOSTNAME') or "downloader-bot-7pdx.onrender.com"
        webhook_target = f"https://{host}/{TOKEN}"
        print(f"Configuring Webhook for Render: {webhook_target}")
        try:
            bot.remove_webhook()
            bot.set_webhook(url=webhook_target)
            print("Webhook setup completed successfully.")
        except Exception as e:
            print(f"Webhook setup error: {e}")
            
        server = HTTPServer(("0.0.0.0", port), WebhookServer)
        print(f"Render Webhook server running on port {port}...")
        server.serve_forever()
    else:
        print("Running in polling mode locally...")
        try:
            bot.remove_webhook()
        except Exception:
            pass
        server = HTTPServer(("0.0.0.0", port), WebhookServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        bot.infinity_polling(skip_pending=True)
