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
import instaloader

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
INSTA_REGEX = r'instagram\.com/(?:p|reel|reels|tv)/([^/?#&]+)'

media_links = {}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك في بوت التحميل المباشر 📥\n\n"
        "أرسل لي أي رابط من (Instagram, TikTok, YouTube, Facebook, X, Pinterest) وسأقوم بتحميل الصور أو الفيديوهات فوراً بأعلى دقة دون أي أسئلة أو خطوات إضافية."
    )
    bot.reply_to(message, welcome_text)

def process_instagram(url, chat_id):
    match = re.search(INSTA_REGEX, url)
    if not match:
        return False
    shortcode = match.group(1)
    
    L = instaloader.Instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    caption = (post.caption or "Instagram")[:1000]
    
    if post.typename == 'GraphSidecar':
        nodes = list(post.get_sidecar_nodes())
        media_group = []
        for i, node in enumerate(nodes[:10]):
            item_caption = caption if i == 0 else None
            req = urllib.request.Request(node.video_url if node.is_video else node.display_url, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req).read()
            if node.is_video:
                media_group.append(types.InputMediaVideo(data, caption=item_caption))
            else:
                media_group.append(types.InputMediaPhoto(data, caption=item_caption))
        if media_group:
            bot.send_media_group(chat_id, media_group)
            return True

    if post.is_video:
        req = urllib.request.Request(post.video_url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req).read()
        markup = types.InlineKeyboardMarkup()
        cb_key = f"aud_{chat_id}_{shortcode}"
        media_links[cb_key] = url
        markup.add(types.InlineKeyboardButton("🎵 استخراج الصوت", callback_data=cb_key))
        bot.send_video(chat_id, data, caption=caption, supports_streaming=True, reply_markup=markup)
        return True

    req = urllib.request.Request(post.url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req).read()
    bot.send_photo(chat_id, data, caption=caption)
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
                
        bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        
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
            if process_instagram(url, message.chat.id):
                bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
                return
        except Exception:
            pass
            
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
        if self.path.strip('/') == TOKEN:
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
    render_url = os.environ.get('RENDER_EXTERNAL_URL')
    port = int(os.environ.get("PORT", 8080))

    if render_url:
        webhook_target = f"{render_url.rstrip('/')}/{TOKEN}"
        print(f"Setting webhook to: {webhook_target}")
        try:
            bot.remove_webhook()
            bot.set_webhook(url=webhook_target)
        except Exception as e:
            print(f"Webhook setup error: {e}")
            
        server = HTTPServer(("0.0.0.0", port), WebhookServer)
        print(f"Webhook server running on port {port}...")
        server.serve_forever()
    else:
        print("Running in polling mode locally...")
        server = HTTPServer(("0.0.0.0", port), WebhookServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        bot.infinity_polling(skip_pending=True)
