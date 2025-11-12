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
from urllib.parse import urlparse, parse_qs
import json
import time
import shutil
import random
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
        self.user_agents = [
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
            'KSYVideoSDK/1.0.0 (iPhone; iOS 16.6; Scale/3.00)',
            'Mozilla/5.0 (Linux; Android 10; VOG-L29) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Kuaishou(8.9.10)',
            'Mozilla/5.0 (Linux; U; Android 11; en-US; SM-A205F Build/RP1A.200720.012) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.1.0.1300 Mobile Safari/537.36'
        ]
        
        # Session ko initialize nahi karenge yahan, baad mein banayenge
        self.session = None

    async def get_session(self):
        """Lazy initialization of aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def close_session(self):
        """Close the aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    def extract_photo_id(self, url: str) -> str:
        """Extract photo ID from various Kuaishou URL formats"""
        try:
            # Handle ksy:// links
            if url.startswith('ksy://'):
                return url.replace('ksy://', '').split('?')[0]
            
            # Handle v.kuaishou.com links
            if 'v.kuaishou.com' in url:
                match = re.search(r'v\.kuaishou\.com/([^/?]+)', url)
                if match:
                    return match.group(1)
            
            # Handle www.kuaishou.com short-video links
            if 'short-video' in url:
                # Extract from path like /short-video/3x8wpv5je8jznzy
                match = re.search(r'/short-video/([^/?]+)', url)
                if match:
                    return match.group(1)
            
            # Extract photoId from query parameters
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'photoId' in query_params:
                return query_params['photoId'][0]
            
            # Extract from any Kuaishou URL
            patterns = [
                r'photoId=([^&]+)',
                r'/short-video/([^/?]+)',
                r'v\.kuaishou\.com/([^/?]+)',
                r'/([a-zA-Z0-9]{10,})'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    photo_id = match.group(1)
                    if len(photo_id) >= 6:
                        return photo_id
            
            return url.split('/')[-1].split('?')[0]
            
        except Exception as e:
            logger.error(f"Error extracting photo ID: {e}")
            return url.split('/')[-1].split('?')[0]

    async def get_video_info_api(self, url: str) -> Dict:
        """Get video information using direct API calls"""
        try:
            photo_id = self.extract_photo_id(url)
            logger.info(f"Extracted photo ID: {photo_id}")
            
            session = await self.get_session()
            
            # Method 1: Try mobile API endpoint
            api_url = f"https://v.m.chenzhongtech.com/rest/wd/photo/info?photoId={photo_id}"
            
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.kuaishou.com/',
                'Origin': 'https://www.kuaishou.com',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            async with session.get(api_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data'):
                        video_info = data['data']
                        return {
                            'success': True,
                            'title': video_info.get('caption', 'Kuaishou Video'),
                            'duration': video_info.get('duration', 0) // 1000,
                            'thumbnail': video_info.get('coverUrl', ''),
                            'view_count': video_info.get('viewCount', 0),
                            'uploader': video_info.get('userName', 'Unknown'),
                            'video_url': video_info.get('photoUrl', ''),
                            'photo_id': photo_id
                        }
            
            # Method 2: Try alternative API
            alt_api_url = f"https://api.ksycloud.com/photo/info?photoId={photo_id}"
            async with session.get(alt_api_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data'):
                        video_info = data['data']
                        return {
                            'success': True,
                            'title': video_info.get('caption', 'Kuaishou Video'),
                            'duration': video_info.get('duration', 0) // 1000,
                            'thumbnail': video_info.get('coverUrl', ''),
                            'view_count': video_info.get('viewCount', 0),
                            'uploader': video_info.get('userName', 'Unknown'),
                            'video_url': video_info.get('photoUrl', ''),
                            'photo_id': photo_id
                        }
            
            return {'success': False, 'error': 'API methods failed'}
            
        except Exception as e:
            logger.error(f"API error: {e}")
            return {'success': False, 'error': f'API error: {str(e)}'}

    async def get_video_info_selenium_method(self, url: str) -> Dict:
        """Alternative method using web scraping simulation"""
        try:
            photo_id = self.extract_photo_id(url)
            session = await self.get_session()
            
            # Simulate mobile app request
            mobile_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            }
            
            # Try to get page content
            async with session.get(url, headers=mobile_headers) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # Try to extract video info from JSON-LD or meta tags
                    json_ld_pattern = r'<script type="application/ld\+json">(.*?)</script>'
                    matches = re.findall(json_ld_pattern, html, re.DOTALL)
                    
                    for match in matches:
                        try:
                            data = json.loads(match)
                            if 'contentUrl' in data:
                                return {
                                    'success': True,
                                    'title': data.get('name', 'Kuaishou Video'),
                                    'duration': 0,
                                    'thumbnail': data.get('thumbnailUrl', ''),
                                    'view_count': 0,
                                    'uploader': data.get('author', 'Unknown'),
                                    'video_url': data.get('contentUrl', ''),
                                    'photo_id': photo_id
                                }
                        except:
                            continue
                    
                    # Try to extract from meta tags
                    meta_pattern = r'<meta property="og:video:url" content="(.*?)"'
                    video_match = re.search(meta_pattern, html)
                    if video_match:
                        title_pattern = r'<meta property="og:title" content="(.*?)"'
                        title_match = re.search(title_pattern, html)
                        
                        return {
                            'success': True,
                            'title': title_match.group(1) if title_match else 'Kuaishou Video',
                            'duration': 0,
                            'thumbnail': '',
                            'view_count': 0,
                            'uploader': 'Unknown',
                            'video_url': video_match.group(1),
                            'photo_id': photo_id
                        }
            
            return {'success': False, 'error': 'Web scraping failed'}
            
        except Exception as e:
            logger.error(f"Selenium method error: {e}")
            return {'success': False, 'error': f'Scraping error: {str(e)}'}

    async def download_video_direct(self, video_url: str, download_dir: str, quality: str = 'best') -> Dict:
        """Download video directly from URL"""
        try:
            session = await self.get_session()
            
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'video/mp4,video/webm,video/*;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'identity',
                'Range': 'bytes=0-',
                'Referer': 'https://www.kuaishou.com/',
                'Origin': 'https://www.kuaishou.com'
            }
            
            async with session.get(video_url, headers=headers) as response:
                if response.status == 200:
                    # Generate filename
                    filename = f"{download_dir}/video_{int(time.time())}.mp4"
                    
                    # Download content
                    content = await response.read()
                    
                    with open(filename, 'wb') as f:
                        f.write(content)
                    
                    file_size = os.path.getsize(filename)
                    
                    return {
                        'success': True,
                        'filename': filename,
                        'file_size': file_size,
                        'duration': 0
                    }
                else:
                    return {'success': False, 'error': f'HTTP {response.status}'}
                    
        except Exception as e:
            logger.error(f"Direct download error: {e}")
            return {'success': False, 'error': f'Download error: {str(e)}'}

    async def get_video_info_ytdlp(self, url: str) -> Dict:
        """Fallback method using yt-dlp with enhanced configuration"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': False,
                'extract_flat': False,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'extractor_args': {
                    'generic': {
                        'headers': {
                            'User-Agent': random.choice(self.user_agents),
                            'Accept': '*/*',
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                            'Referer': 'https://www.kuaishou.com/',
                            'Origin': 'https://www.kuaishou.com'
                        }
                    }
                },
                'http_headers': {
                    'User-Agent': random.choice(self.user_agents),
                    'Accept': '*/*',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Referer': 'https://www.kuaishou.com/',
                    'Origin': 'https://www.kuaishou.com'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    return {
                        'success': True,
                        'title': info.get('title', 'Kuaishou Video'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'view_count': info.get('view_count', 0),
                        'uploader': info.get('uploader', 'Unknown'),
                        'video_url': info.get('url', ''),
                        'photo_id': self.extract_photo_id(url)
                    }
                
            return {'success': False, 'error': 'yt-dlp extraction failed'}
            
        except Exception as e:
            logger.error(f"yt-dlp error: {e}")
            return {'success': False, 'error': f'yt-dlp error: {str(e)}'}

    async def get_video_info(self, url: str) -> Dict:
        """Main method to get video information using multiple approaches"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempt {attempt + 1} to get video info")
                
                # Try API method first
                api_result = await self.get_video_info_api(url)
                if api_result.get('success'):
                    return api_result
                
                # Try web scraping method
                scrape_result = await self.get_video_info_selenium_method(url)
                if scrape_result.get('success'):
                    return scrape_result
                
                # Try yt-dlp as last resort with different configurations
                if attempt == 1:
                    ydl_result = await self.get_video_info_ytdlp(url)
                    if ydl_result.get('success'):
                        return ydl_result
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    
            except Exception as e:
                logger.error(f"Error in get_video_info attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
        
        return {'success': False, 'error': 'All methods failed to extract video information'}

    async def download_video(self, url: str, quality: str = 'best') -> Dict:
        """Main download method"""
        download_id = str(uuid.uuid4())[:8]
        download_dir = f"downloads/{download_id}"
        os.makedirs(download_dir, exist_ok=True)
        
        try:
            # Get video information first
            video_info = await self.get_video_info(url)
            if not video_info.get('success'):
                return {'success': False, 'error': video_info.get('error', 'Unknown error')}
            
            # Download the video
            if video_info.get('video_url'):
                download_result = await self.download_video_direct(
                    video_info['video_url'], 
                    download_dir, 
                    quality
                )
                
                if download_result.get('success'):
                    return {
                        'success': True,
                        'filename': download_result['filename'],
                        'title': video_info['title'],
                        'duration': video_info['duration'],
                        'quality': quality,
                        'file_size': download_result['file_size'],
                        'download_id': download_id,
                        'uploader': video_info['uploader']
                    }
            
            return {'success': False, 'error': 'No video URL found for download'}
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            # Cleanup on error
            if os.path.exists(download_dir):
                shutil.rmtree(download_dir, ignore_errors=True)
            return {'success': False, 'error': f'Download failed: {str(e)}'}

# Initialize downloader - ab session ko lazy initialize karenge
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
    kuaishou_domains = [
        'v.kuaishou.com',
        'www.kuaishou.com', 
        'kuaishou.com',
        'kuaishouapp.com',
        'c.kuaishou.com',
        'v.m.chenzhongtech.com',
        'api.kuaishouzt.com'
    ]
    
    url = url.strip().lower()
    
    # Check for ksy:// protocol
    if url.startswith('ksy://'):
        return True
    
    # Check for Kuaishou domains
    for domain in kuaishou_domains:
        if domain in url:
            return True
    
    # Check for short-video pattern
    if 'short-video' in url:
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
            "• `https://v.kuaishou.com/JVpSbig2`\n"
            "• `https://www.kuaishou.com/short-video/3x8wpv5je8jznzy`\n"
            "• `ksy://video123`\n"
            "• `v.kuaishou.com/ABC123`\n\n"
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
        
        video_info = await downloader.get_video_info(message_text)
        if not video_info.get('success'):
            error_msg = video_info.get('error', 'Unknown error')
            
            await processing_msg.edit_text(
                "❌ **Video Access Failed!**\n\n"
                f"Error: {error_msg}\n\n"
                "Kripya:\n"
                "• Different video ka link try karein\n"
                "• Thodi der baad try karein\n"
                "• Internet connection check karein\n"
                "• Koi simple Kuaishou link try karein"
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
        download_result = await downloader.download_video(message_text, user_quality)
        
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
            f"👤 Uploader: {download_result.get('uploader', 'Unknown')}\n"
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
        try:
            await processing_msg.edit_text(
                "❌ **Unexpected Error Occurred!**\n\n"
                "System ne unexpected error report kiya hai.\n\n"
                "Kripya:\n"
                "• Thodi der wait karein\n"
                "• Phir se try karein\n"
                "• Agar problem continue ho to different link try karein\n\n"
                "We're working to fix this automatically."
            )
        except:
            await update.message.reply_text(
                "❌ **Unexpected Error Occurred!**\n\n"
                "Please try again with a different link."
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

async def on_shutdown(app: Application):
    """Cleanup on shutdown"""
    await downloader.close_session()

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
    
    # Run the bot with shutdown handler
    try:
        application.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        # Manual cleanup on shutdown
        asyncio.run(on_shutdown(application))

if __name__ == '__main__':
    main()
