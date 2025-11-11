from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return {
        "status": "online",
        "service": "Kuaishou Video Downloader Bot",
        "version": "2.0.0"
    }

@app.route('/health')
def health():
    return {"status": "healthy"}

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False)

if __name__ == '__main__':
    run_flask()
