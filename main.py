import os
import logging
import re
import asyncio
import aiohttp
import tempfile
import uuid
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
import yt_dlp
import requests
from urllib.parse import urlparse
import json
import time
import shutil
from typing import Dict, List

# Enable detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
SUPPORTED_QUALITIES = ['best', '1080p', '720p', '480p', '360p']

# User sessions to store preferences
user_sessions: Dict[int, Dict] = {}

class KuaishouDownloader:
    def __init__(self):
        self.ydl_opts = {
            'format': 'best[height<=1080]',
            'outtmpl': 'downloads/%(title).100s.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'writethumbnail': True,
            'embedthumbnail': True,
            'consoletitle': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Connection': 'keep-alive',
            }
        }
    
    def get_video_info(self, url: str) -> Dict:
        """Get video information without downloading"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'success': True,
                    'title': info.get('title', 'Kuaishou Video'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'view_count': info.get('view_count', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'formats': info.get('formats', []),
                    'description': info.get('description', '')[:500]
                }
        except Exception as e:
            logger.error(f"Video info error: {e}")
            return {'success': False, 'error': str(e)}
    
    def download_video(self, url: str, quality: str = 'best') -> Dict:
        """Download video with specified quality"""
        download_id = str(uuid.uuid4())[:8]
        download_dir = f"downloads/{download_id}"
        os.makedirs(download_dir, exist_ok=True)
        
        # Update format based on quality preference
        if quality == '1080p':
            format_spec = 'best[height<=1080]'
        elif quality == '720p':
            format_spec = 'best[height<=720]'
        elif quality == '480p':
            format_spec = 'best[height<=480]'
        elif quality == '360p':
            format_spec = 'best[height<=360]'
        else:
            format_spec = 'best'
        
        self.ydl_opts['format'] = format_spec
        self.ydl_opts['outtmpl'] = f'{download_dir}/%(title).100s.%(ext)s'
        
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Check file size
                file_size = os.path.getsize(filename) if os.path.exists(filename) else 0
                
                return {
                    'success': True,
                    'filename': filename,
                    'title': info.get('title', 'Kuaishou Video'),
                    'duration': info.get('duration', 0),
                    'quality': quality,
                    'file_size': file_size,
                    'download_id': download_id
                }
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {'success': False, 'error': str(e)}

# Initialize downloader
downloader = KuaishouDownloader()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when command /start is issued."""
    user = update.message.from_user
    user_id = user.id
    
    # Initialize user session
    user_sessions[user_id] = {
        'quality': 'best',
        'last_activity': datetime.now(),
        'download_count': 0
    }
    
    welcome_text = f"""
🎬 **Namaste {user.first_name}! Welcome to Kuaishou Video Downloader** 🎬

🤖 **Meri Specialities:**
• ✅ Full HD 1080p Quality
• ✅ One-Click Download
• ✅ Fast & Reliable
• ✅ 24/7 Available
• ✅ All Kuaishou Links Supported

📱 **Kaise Use Karein:**
1. Kuaishou app mein koi bhi video kholain
2. Share button dabain
3. "Copy Link" select karein
4. Yahan link paste karein

🔗 **Supported Links:**
• `v.kuaishou.com/...`
• `www.kuaishou.com/...` 
• `ksy://...`
• Aur sabhi Kuaishou links

⚙ **Commands:**
• /start - Bot start karein
• /help - Help dekhein
• /quality - Video quality set karein
• /stats - Apna statistics dekhein

🚀 **Abhi koi bhi Kuaishou link bhej kar try karein!**
"""
    
    await update.message.reply_text(welcome_text)
    logger.info(f"New user started: {user.first_name} (ID: {user_id})")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message when command /help is issued."""
    help_text = """
🆘 **Help & Support Center**

📖 **Basic Usage:**
1. Kuaishou app mein video open karein
2. Share → Copy Link
3. Yahan link paste karein
4. Video automatically download ho jayega!

🎯 **Advanced Features:**
• Multiple quality options (360p to 1080p)
• Fast download speed
• Automatic thumbnail support
• File size optimization

⚡ **Quick Commands:**
• /quality - Video quality change karein
• /stats - Apne downloads dekhein
• /help - Yeh message dikhayein

🔧 **Troubleshooting:**
• Agar video download na ho to different link try karein
• Internet connection strong hona chahiye
• Video publicly available hona chahiye

📞 **Support:**
Agar koi problem ho to directly link bhej kar try karein!
"""
    
    await update.message.reply_text(help_text)

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set video quality preference."""
    user_id = update.message.from_user.id
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {'quality': 'best', 'download_count': 0}
    
    current_quality = user_sessions[user_id].get('quality', 'best')
    
    quality_text = f"""
🎯 **Video Quality Settings**

Current Quality: **{current_quality.upper()}**

Available Options:
• 🥇 /set_quality_best - Best Available (Auto)
• 🖥 /set_quality_1080 - Full HD (1080p)
• 📺 /set_quality_720 - HD Ready (720p) 
• 📱 /set_quality_480 - Standard (480p)
• 💫 /set_quality_360 - Basic (360p)

💡 **Recommendation:** 
• Best - Sabse recommended (Auto adjust)
• 1080p - Highest quality (Data zyada use karega)
• 360p - Fast download (Kam data use karega)
"""
    
    await update.message.reply_text(quality_text)

async def set_quality_best(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quality to best."""
    user_id = update.message.from_user.id
    user_sessions[user_id]['quality'] = 'best'
    await update.message.reply_text("✅ **Quality Set to: BEST**\n\nAb aapko sabse best available quality milegi!")

async def set_quality_1080(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quality to 1080p."""
    user_id = update.message.from_user.id
    user_sessions[user_id]['quality'] = '1080p'
    await update.message.reply_text("✅ **Quality Set to: 1080p FULL HD**\n\nAb aapko highest quality videos milenge!")

async def set_quality_720(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quality to 720p."""
    user_id = update.message.from_user.id
    user_sessions[user_id]['quality'] = '720p'
    await update.message.reply_text("✅ **Quality Set to: 720p HD**\n\nAb aapko HD quality videos milenge!")

async def set_quality_480(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quality to 480p."""
    user_id = update.message.from_user.id
    user_sessions[user_id]['quality'] = '480p'
    await update.message.reply_text("✅ **Quality Set to: 480p STANDARD**\n\nAb aapko standard quality videos milenge!")

async def set_quality_360(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quality to 360p."""
    user_id = update.message.from_user.id
    user_sessions[user_id]['quality'] = '360p'
    await update.message.reply_text("✅ **Quality Set to: 360p BASIC**\n\nAb aapko fast download with basic quality milegi!")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics."""
    user_id = update.message.from_user.id
    user = update.message.from_user
    
    if user_id in user_sessions:
        download_count = user_sessions[user_id].get('download_count', 0)
        quality = user_sessions[user_id].get('quality', 'best')
    else:
        download_count = 0
        quality = 'best'
    
    stats_text = f"""
📊 **User Statistics**

👤 User: {user.first_name}
🆔 ID: {user_id}
📥 Total Downloads: {download_count}
🎯 Current Quality: {quality.upper()}
🕒 Last Active: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🌟 **Thanks for using our service!**
"""
    
    await update.message.reply_text(stats_text)

def is_valid_kuaishou_url(url: str) -> bool:
    """Check if URL is a valid Kuaishou URL."""
    kuaishou_patterns = [
        r'https?://v\.kuaishou\.com/\w+',
        r'https?://www\.kuaishou\.com/\w+',
        r'ksy://\w+',
        r'kuaishou\.com/\w+',
        r'kuaishouapp\.com/\w+'
    ]
    
    url = url.strip()
    for pattern in kuaishou_patterns:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

async def cleanup_downloads():
    """Cleanup old download directories."""
    try:
        if os.path.exists('downloads'):
            for dir_name in os.listdir('downloads'):
                dir_path = os.path.join('downloads', dir_name)
                if os.path.isdir(dir_path):
                    # Remove directories older than 1 hour
                    dir_time = os.path.getctime(dir_path)
                    if time.time() - dir_time > 3600:  # 1 hour
                        shutil.rmtree(dir_path, ignore_errors=True)
                        logger.info(f"Cleaned up old directory: {dir_path}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    user = update.message.from_user
    user_id = user.id
    message_text = update.message.text.strip()
    
    # Initialize user session if not exists
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'quality': 'best',
            'last_activity': datetime.now(),
            'download_count': 0
        }
    
    # Update last activity
    user_sessions[user_id]['last_activity'] = datetime.now()
    
    # Check if message is a Kuaishou URL
    if not is_valid_kuaishou_url(message_text):
        await update.message.reply_text(
            "❌ **Invalid Kuaishou Link!**\n\n"
            "Kripya sahi Kuaishou video link bhejein.\n\n"
            "📝 **Examples of Valid Links:**\n"
            "• `https://v.kuaishou.com/KybGvmoV`\n"
            "• `v.kuaishou.com/ABC123`\n"
            "• `ksy://video123`\n\n"
            "Kuaishou app mein share button se 'Copy Link' karein."
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        "🔄 **Processing Your Request...**\n\n"
        "📡 Checking video availability...\n"
        "⏳ Please wait..."
    )
    
    try:
        # Step 1: Get video information
        await processing_msg.edit_text(
            "🔍 **Video Analysis Started...**\n\n"
            "📹 Extracting video information...\n"
            "⚡ This may take a few seconds..."
        )
        
        video_info = downloader.get_video_info(message_text)
        if not video_info.get('success'):
            await processing_msg.edit_text(
                "❌ **Video Access Failed!**\n\n"
                "Possible Reasons:\n"
                "• Video private ya deleted hai\n"
                "• Link invalid hai\n"
                "• Regional restriction hai\n"
                "• Network issue hai\n\n"
                "Kripya different video ka link try karein."
            )
            return
        
        # Step 2: Start download with user's preferred quality
        user_quality = user_sessions[user_id].get('quality', 'best')
        await processing_msg.edit_text(
            f"📥 **Download Starting...**\n\n"
            f"🎬 Title: {video_info['title'][:50]}...\n"
            f"⏱ Duration: {video_info['duration']} seconds\n"
            f"🎯 Quality: {user_quality.upper()}\n"
            f"👤 Uploader: {video_info['uploader']}\n\n"
            f"⏳ Downloading please wait..."
        )
        
        # Download video
        download_result = downloader.download_video(message_text, user_quality)
        
        if not download_result.get('success'):
            await processing_msg.edit_text(
                "❌ **Download Failed!**\n\n"
                f"Error: {download_result.get('error', 'Unknown error')}\n\n"
                "Kripya:\n"
                "• Different link try karein\n"
                "• Thodi der baad try karein\n"
                "• Internet connection check karein"
            )
            return
        
        # Step 3: Send video to user
        await processing_msg.edit_text(
            "✅ **Download Complete!**\n\n"
            "📤 Sending video to you...\n"
            "⚡ Almost done!"
        )
        
        # Prepare caption
        file_size_mb = download_result['file_size'] / (1024 * 1024)
        caption = (
            f"🎥 **{download_result['title']}**\n\n"
            f"⏱ Duration: {download_result['duration']} seconds\n"
            f"🎯 Quality: {download_result['quality'].upper()}\n"
            f"📊 Size: {file_size_mb:.2f} MB\n"
            f"👤 Uploader: {video_info['uploader']}\n"
            f"🔗 @KuaishouDownloaderBot\n\n"
            f"⭐ Downloaded successfully!"
        )
        
        # Send video file
        with open(download_result['filename'], 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=caption,
                supports_streaming=True,
                width=1920,
                height=1080,
                duration=download_result['duration']
            )
        
        # Update user statistics
        user_sessions[user_id]['download_count'] += 1
        
        # Cleanup downloaded files immediately
        try:
            download_dir = f"downloads/{download_result['download_id']}"
            if os.path.exists(download_dir):
                shutil.rmtree(download_dir, ignore_errors=True)
                logger.info(f"Cleaned up download directory: {download_dir}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        
        await processing_msg.delete()
        
        # Send success message
        await update.message.reply_text(
            "🎉 **Download Successful!**\n\n"
            "✅ Video successfully downloaded and sent!\n\n"
            "🔄 Agar aur videos download karna hai to simply links bhejte rahein!\n\n"
            "🌟 Thank you for using our service!"
        )
        
        logger.info(f"Video downloaded successfully for user {user_id}: {download_result['title']}")
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await processing_msg.edit_text(
            "❌ **Unexpected Error Occurred!**\n\n"
            "System ne unexpected error report kiya hai.\n\n"
            "Kripya:\n"
            "• Thodi der wait karein\n"
            "• Phir se try karein\n"
            "• Agar problem continue ho to different link try karein\n\n"
            "We're working to fix this automatically."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the telegram bot."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    try:
        if update and update.message:
            await update.message.reply_text(
                "❌ **System Error!**\n\n"
                "Kuch technical problem aayi hai. Kripya thodi der baad phir try karein.\n\n"
                "Agar problem continue ho to /help command use karein."
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    # Create necessary directories
    os.makedirs('downloads', exist_ok=True)
    
    # Cleanup old downloads on startup
    asyncio.run(cleanup_downloads())
    
    # Create Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("set_quality_best", set_quality_best))
    application.add_handler(CommandHandler("set_quality_1080", set_quality_1080))
    application.add_handler(CommandHandler("set_quality_720", set_quality_720))
    application.add_handler(CommandHandler("set_quality_480", set_quality_480))
    application.add_handler(CommandHandler("set_quality_360", set_quality_360))
    
    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("🤖 Advanced Kuaishou Video Downloader Bot Starting...")
    print("=" * 50)
    print("🎬 ADVANCED KUAISHOU VIDEO DOWNLOADER BOT")
    print("🤖 Bot Successfully Started!")
    print("📱 Send any Kuaishou link to download videos")
    print("⚡ Features: Multi-quality, Fast, Reliable")
    print("🌐 Ready to receive requests...")
    print("=" * 50)
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
