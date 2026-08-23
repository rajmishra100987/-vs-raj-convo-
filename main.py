import os
import re
import time
import random
import string
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from threading import Thread, Event, Lock
import json
import logging

# Configure logging to only show minimal information
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['DEBUG'] = False

# Global variables for task management
tasks = {}
tasks_lock = Lock()
stop_events = {}
token_usage = {}
token_locks = {}

# 🔥 BADA STRONG HEADERS - MOZILLA LINUX
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.facebook.com',
    'Referer': 'https://www.facebook.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache'
}

def generate_task_key():
    """Generate 10-character random task key"""
    return ''.join(random.choices(string.ascii_lowercase, k=10))

def check_rate_limit(access_token):
    """Check if token has exceeded rate limit (2 messages per minute)"""
    current_time = time.time()
    
    if access_token not in token_usage:
        token_usage[access_token] = []
    
    # Remove timestamps older than 60 seconds
    token_usage[access_token] = [
        ts for ts in token_usage[access_token] 
        if current_time - ts < 60
    ]
    
    # If 2 or more messages in last 60 seconds, apply 5 minute break
    if len(token_usage[access_token]) >= 2:
        return True  # Needs break
    
    return False  # No break needed

def update_token_usage(access_token):
    """Update token usage timestamp"""
    current_time = time.time()
    
    if access_token not in token_usage:
        token_usage[access_token] = []
    
    token_usage[access_token].append(current_time)

def send_messages_strong(task_key, access_tokens, thread_id, hatersname, lastname, time_interval, messages):
    stop_event = stop_events.get(task_key)
    if not stop_event:
        return
    
    while not stop_event.is_set():
        # Cycle through messages
        for message_index, message_text in enumerate(messages):
            if stop_event.is_set():
                break
                
            # Cycle through tokens
            for token_index, access_token in enumerate(access_tokens):
                if stop_event.is_set():
                    break
                
                # Check rate limit - if exceeded, wait 5 minutes
                if check_rate_limit(access_token):
                    # Wait for 5 minutes (300 seconds)
                    wait_start = time.time()
                    while time.time() - wait_start < 300 and not stop_event.is_set():
                        time.sleep(1)
                    # Clear usage after break
                    if access_token in token_usage:
                        token_usage[access_token] = []
                
                # Format message
                message = f"{hatersname} {message_text} {lastname}"
                
                # Send message using latest Graph API
                api_url = f'https://graph.facebook.com/v17.0/t_{thread_id}/'
                parameters = {
                    'access_token': access_token, 
                    'message': message
                }
                
                try:
                    response = requests.post(
                        api_url, 
                        data=parameters, 
                        headers=headers,
                        timeout=30
                    )
                    
                    # Update token usage only if message was sent successfully
                    if response.status_code == 200:
                        update_token_usage(access_token)
                    
                    # Update task status
                    with tasks_lock:
                        if task_key in tasks:
                            tasks[task_key]['last_message'] = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
                            tasks[task_key]['message_count'] = tasks[task_key].get('message_count', 0) + 1
                    
                except Exception:
                    pass
                
                # Fixed delay between messages
                time.sleep(time_interval)
        
        # 20-second rest between cycles
        if not stop_event.is_set():
            time.sleep(20)

def check_token_validity(token):
    """Check if token is valid - SIMPLIFIED VERSION"""
    try:
        # Get basic user info using latest Graph API
        user_url = f"https://graph.facebook.com/v17.0/me?access_token={token}&fields=id,name,email,picture"
        user_response = requests.get(user_url, timeout=10)
        
        if user_response.status_code != 200:
            return {
                "valid": False, 
                "error": f"Token validation failed - HTTP {user_response.status_code}"
            }
        
        user_data = user_response.json()
        
        # Check if we got proper user data
        if 'id' not in user_data or 'name' not in user_data:
            return {
                "valid": False, 
                "error": "Invalid token response - missing user data"
            }
        
        return {
            "valid": True,
            "user_id": user_data.get('id', 'N/A'),
            "name": user_data.get('name', 'N/A'),
            "email": user_data.get('email', 'Not available'),
            "picture": user_data.get('picture', {}).get('data', {}).get('url', '')
        }
        
    except Exception as e:
        return {
            "valid": False, 
            "error": f"Token check failed: {str(e)}"
        }

def extract_messenger_chat_groups(token):
    """Extract ALL Facebook Messenger chat groups for a valid token"""
    try:
        # Get conversations/threads from Messenger
        threads_url = f"https://graph.facebook.com/v17.0/me/conversations?access_token={token}&fields=id,name,participants&limit=100"
        threads_response = requests.get(threads_url, timeout=15)
        
        chat_groups = []
        
        if threads_response.status_code == 200:
            threads_data = threads_response.json()
            conversations = threads_data.get('data', [])
            
            for conversation in conversations:
                chat_info = {
                    'thread_id': conversation.get('id', 'N/A'),
                    'name': conversation.get('name', 'Unnamed Chat'),
                    'participants_count': len(conversation.get('participants', {}).get('data', [])) if conversation.get('participants') else 0
                }
                chat_groups.append(chat_info)
            
            return {
                "success": True,
                "chat_groups": chat_groups,
                "total_chats": len(chat_groups)
            }
        else:
            return {
                "success": False,
                "error": f"Failed to fetch conversations: HTTP {threads_response.status_code}",
                "chat_groups": [],
                "total_chats": 0
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Error extracting chat groups: {str(e)}",
            "chat_groups": [],
            "total_chats": 0
        }

# HTML Template
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔥 MADHU MISHRA - Facebook Message Sender</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Poppins', sans-serif;
            background: url('https://i.ibb.co/XrTgznxD/1773997616608.jpg') no-repeat center center fixed;
            background-size: cover;
            min-height: 100vh;
            padding: 20px;
            color: white;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(0,0,0,0.7);
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        
        h1 {
            color: #ff4081;
            font-weight: 700;
            font-size: 3rem;
            margin-bottom: 10px;
            text-shadow: 0 0 20px #ff4081;
        }
        
        .subtitle {
            color: #fff;
            font-size: 1.2rem;
            font-weight: 300;
        }
        
        .tab-container {
            margin-bottom: 30px;
        }
        
        .tabs {
            display: flex;
            margin-bottom: 20px;
            background: rgba(0,0,0,0.8);
            border-radius: 12px;
            padding: 5px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.5);
        }
        
        .tab {
            flex: 1;
            padding: 15px 20px;
            background: transparent;
            border: none;
            color: white;
            cursor: pointer;
            border-radius: 10px;
            font-weight: 500;
            font-size: 1rem;
            transition: all 0.3s ease;
            text-align: center;
        }
        
        .tab.active {
            background: #ff4081;
            color: white;
            box-shadow: 0 3px 10px rgba(255,64,129,0.5);
        }
        
        .tab:hover:not(.active) {
            background: rgba(255,64,129,0.3);
        }
        
        .tab-content {
            display: none;
            padding: 25px;
            background: rgba(0,0,0,0.8);
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .tab-content.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #ff4081;
            font-size: 1rem;
        }
        
        input[type="text"],
        input[type="number"],
        textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 8px;
            font-size: 1rem;
            transition: all 0.3s ease;
            background: rgba(0,0,0,0.7);
            color: white;
            font-family: 'Poppins', sans-serif;
        }
        
        input[type="text"]:focus,
        input[type="number"]:focus,
        textarea:focus {
            outline: none;
            border-color: #ff4081;
            background: rgba(0,0,0,0.9);
            box-shadow: 0 0 0 3px rgba(255,64,129,0.3);
        }
        
        .file-input-wrapper {
            position: relative;
            display: inline-block;
            width: 100%;
        }
        
        .file-input {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            cursor: pointer;
            text-align: center;
            transition: all 0.3s ease;
            border: none;
            font-weight: 500;
            display: block;
            width: 100%;
            box-shadow: 0 4px 12px rgba(102,126,234,0.4);
        }
        
        .file-input:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102,126,234,0.6);
        }
        
        .file-input input[type="file"] {
            position: absolute;
            left: 0;
            top: 0;
            opacity: 0;
            width: 100%;
            height: 100%;
            cursor: pointer;
        }
        
        .btn-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 25px;
        }
        
        button {
            background: linear-gradient(135deg, #ff4081 0%, #e91e63 100%);
            color: white;
            padding: 12px 25px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 1rem;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(255,64,129,0.4);
            flex: 1;
            min-width: 120px;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255,64,129,0.6);
        }
        
        button.secondary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            box-shadow: 0 4px 12px rgba(102,126,234,0.4);
        }
        
        button.danger {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            box-shadow: 0 4px 12px rgba(255,107,107,0.4);
        }
        
        button.success {
            background: linear-gradient(135deg, #00b894 0%, #00a085 100%);
            box-shadow: 0 4px 12px rgba(0,184,148,0.4);
        }
        
        .copy-btn {
            background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
            padding: 6px 12px;
            font-size: 0.8rem;
            box-shadow: 0 2px 8px rgba(33,150,243,0.4);
        }
        
        .result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 10px;
            display: none;
            background: rgba(0,0,0,0.7);
            border: 1px solid rgba(255,255,255,0.2);
        }
        
        .success {
            background: rgba(40,167,69,0.2);
            border: 2px solid #28a745;
            color: #d4edda;
        }
        
        .error {
            background: rgba(220,53,69,0.2);
            border: 2px solid #dc3545;
            color: #f8d7da;
        }
        
        .status-info {
            background: rgba(33,150,243,0.2);
            border: 2px solid #2196f3;
            padding: 20px;
            border-radius: 10px;
            margin-top: 15px;
        }
        
        .token-result {
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            background: rgba(0,0,0,0.6);
        }
        
        .valid {
            border-left: 4px solid #28a745;
        }
        
        .invalid {
            border-left: 4px solid #dc3545;
        }
        
        .chat-list {
            margin-top: 15px;
            max-height: 400px;
            overflow-y: auto;
            border: 2px solid rgba(255,255,255,0.2);
            padding: 15px;
            background: rgba(0,0,0,0.6);
            border-radius: 8px;
        }
        
        .chat-item {
            padding: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.3s ease;
        }
        
        .chat-item:hover {
            background: rgba(255,255,255,0.1);
            transform: translateX(5px);
        }
        
        .chat-item:last-child {
            border-bottom: none;
        }
        
        .developer {
            text-align: center;
            margin-top: 40px;
            color: rgba(255,255,255,0.8);
            font-style: italic;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.3);
        }
        
        .small-text {
            font-size: 0.85rem;
            color: rgba(255,255,255,0.7);
            margin-top: 5px;
        }
        
        .token-preview {
            font-family: monospace;
            background: rgba(0,0,0,0.6);
            padding: 5px 10px;
            border-radius: 5px;
            border: 1px solid rgba(255,255,255,0.2);
            margin-top: 5px;
            font-size: 0.85rem;
            word-break: break-all;
            color: white;
        }
        
        .feature-badge {
            display: inline-block;
            background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
            color: #000;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 8px;
        }
        
        @media (max-width: 768px) {
            body {
                padding: 10px;
            }
            
            h1 {
                font-size: 2rem;
            }
            
            .tabs {
                flex-direction: column;
            }
            
            .btn-group {
                flex-direction: column;
            }
            
            button {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 MADHU MISHRA</h1>
        <div class="subtitle">Professional Facebook Message Sender</div>
    </div>
    
    <div class="tab-container">
        <div class="tabs">
            <div class="tab" onclick="switchTab('message-sender')">💬 Message Sender</div>
            <div class="tab" onclick="switchTab('token-checker')">🔑 Token Checker</div>
            <div class="tab active" onclick="switchTab('chat-extractor')">📱 Messenger Chat Extractor</div>
            <div class="tab" onclick="switchTab('status-check')">📊 Status Check</div>
        </div>
        
        <!-- Messenger Chat Extractor Tab -->
        <div id="chat-extractor" class="tab-content active">
            <form id="chatExtractForm">
                <div class="form-group">
                    <label>🔑 Enter Valid Facebook Token <span class="feature-badge">Required</span></label>
                    <input type="text" name="token" placeholder="Enter EAAD token like EAAD6V7osOgcBPxx5TBI..." required>
                    <div class="small-text">Token must be valid to extract Messenger chat groups</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">🚀 Extract Messenger Chats</button>
                </div>
            </form>
            
            <div id="chatExtractResult"></div>
        </div>
        
        <!-- Token Checker Tab -->
        <div id="token-checker" class="tab-content">
            <form id="tokenForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label>🔑 Access Tokens</label>
                    <input type="text" name="single_token" placeholder="Enter single token...">
                    <div class="token-preview" id="tokenPreview">Token preview will appear here</div>

<div class="small-text" style="margin: 10px 0; text-align: center; font-weight: bold;">OR</div>
                    
                    <label>📁 Upload Token File</label>
                    <div class="file-input-wrapper">
                        <div class="file-input">
                            📁 Choose Token File (.txt)
                            <input type="file" name="token_file" accept=".txt" id="tokenFileInput">
                        </div>
                    </div>
                    <div class="small-text">Upload .txt file with one token per line</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">🔍 Check Tokens</button>
                </div>
            </form>
            
            <div id="tokenResult"></div>
        </div>
        
        <!-- Message Sender Tab -->
        <div id="message-sender" class="tab-content">
            <form id="messageForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label>🔑 Access Token <span class="feature-badge">Required</span></label>
                    <input type="text" name="single_token" placeholder="Enter your Facebook access token...">
                    <div class="small-text">OR</div>
                    <div class="file-input-wrapper">
                        <div class="file-input">
                            📁 Upload Token File
                            <input type="file" name="token_file" accept=".txt">
                        </div>
                    </div>
                    <div class="small-text">Upload .txt file with one token per line</div>
                </div>
                
                <div class="form-group">
                    <label>💬 Conversation ID <span class="feature-badge">Required</span></label>
                    <input type="text" name="conversation_id" placeholder="Enter conversation/thread ID..." required>
                </div>
                
                <div class="form-group">
                    <label>👤 Haters Name <span class="feature-badge">Required</span></label>
                    <input type="text" name="hatersname" placeholder="Enter haters name..." required>
                </div>
                
                <div class="form-group">
                    <label>📛 Last Name <span class="feature-badge">Required</span></label>
                    <input type="text" name="lastname" placeholder="Enter last name..." required>
                </div>
                
                <div class="form-group">
                    <label>⏱️ Time Interval (seconds) <span class="feature-badge">Required</span></label>
                    <input type="number" name="time_interval" value="30" min="1" required>
                    <div class="small-text">Delay between each message</div>
                </div>
                
                <div class="form-group">
                    <label>📝 Messages File <span class="feature-badge">Required</span></label>
                    <div class="file-input-wrapper">
                        <div class="file-input">
                            📁 Upload NP File
                            <input type="file" name="message_file" accept=".txt" required>
                        </div>
                    </div>
                    <div class="small-text">Upload .txt file with one message per line</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">🚀 Start Task</button>
                </div>
            </form>
            
            <div id="taskResult" class="result"></div>
        </div>
        
        <!-- Status Check Tab -->
        <div id="status-check" class="tab-content">
            <form id="statusForm">
                <div class="form-group">
                    <label>🔑 Task Key <span class="feature-badge">Required</span></label>
                    <input type="text" name="task_key" placeholder="Enter your task key..." required>
                    <div class="small-text">Enter the task key you received when starting the task</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">📊 Check Status</button>
                    <button type="button" onclick="controlTask('stop')" class="danger">⏸️ Stop</button>
                    <button type="button" onclick="controlTask('resume')" class="success">▶️ Resume</button>
                    <button type="button" onclick="controlTask('delete')" class="danger">🗑️ Delete</button>
                </div>
            </form>
            
            <div id="statusResult"></div>
        </div>
    </div>
    
    <div class="developer">
        developer:- vampire raj mishra
    </div>

    <script>
        function switchTab(tabName) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Remove active class from all tabs
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Show selected tab content
            document.getElementById(tabName).classList.add('active');
            
            // Add active class to clicked tab
            event.target.classList.add('active');
        }
        
        // Token preview functionality
        const tokenInput = document.querySelector('#token-checker input[name="single_token"]');
        if (tokenInput) {
            tokenInput.addEventListener('input', function(e) {
                const token = e.target.value;
                const preview = document.getElementById('tokenPreview');
                
                if (token.length > 0) {
                    if (token.startsWith('EAAD')) {
                        preview.innerHTML = '✅ Valid EAAD Token: ' + token.substring(0, 10) + '...' + token.substring(token.length - 4);
                        preview.style.color = '#28a745';
                    } else {
                        preview.innerHTML = '⚠️ Token doesn\\'t start with EAAD: ' + token.substring(0, 10) + '...';
                        preview.style.color = '#ffc107';
                    }
                } else {
                    preview.innerHTML = 'Token preview will appear here';
                    preview.style.color = 'rgba(255,255,255,0.7)';
                }
            });
        }
        
        // File input display
        const tokenFileInput = document.getElementById('tokenFileInput');
        if (tokenFileInput) {
            tokenFileInput.addEventListener('change', function(e) {
                const file = e.target.files[0];
                if (file) {
                    const preview = document.getElementById('tokenPreview');
                    preview.innerHTML = '📁 Selected file: ' + file.name;
                    preview.style.color = '#2196f3';
                }
            });
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(function() {
                alert('✅ Copied: ' + text);
            }).catch(function(err) {
                console.error('Could not copy text: ', err);
            });
        }
        
        // Messenger Chat Extractor Form
        document.getElementById('chatExtractForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const token = formData.get('token');
            
            if (!token) {
                alert('❌ Please enter a token');
                return;
            }
            
            // Show loading state
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '⏳ Extracting Messenger Chats...';
            submitBtn.disabled = true;
            
            fetch('/extract_messenger_chats', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                displayMessengerChats(data, token);
            })
            .catch(error => {
                document.getElementById('chatExtractResult').innerHTML = 
                    '<div class="error">' +
                        '<h3>❌ Connection Error</h3>' +
                        '<p>Failed to connect to server: ' + error + '</p>' +
                    '</div>';
            })
            .finally(() => {
                submitBtn.innerHTML = originalText;
                submitBtn.disabled = false;
            });
        });
        
        function displayMessengerChats(data, token) {
            let html = '';
            
            if (data.error) {
                html = 
                    '<div class="error">' +
                        '<h3>❌ Extraction Failed</h3>' +
                        '<p><strong>Error:</strong> ' + data.error + '</p>' +
                    '</div>';
            } else {
                const tokenInfo = data.token_info;
                const messengerChats = data.messenger_chats;
                
                html += 
                    '<div class="success">' +
                        '<h3>✅ Token Valid - Messenger Chats Extracted</h3>' +
                        '<p><strong>User:</strong> ' + tokenInfo.name + ' (ID: ' + tokenInfo.user_id + ')</p>' +
                        '<p><strong>Email:</strong> ' + tokenInfo.email + '</p>' +
                        '<p><strong>Total Messenger Chats Found:</strong> ' + messengerChats.total_chats + '</p>' +
                    '</div>';
                
                if (messengerChats.success && messengerChats.chat_groups && messengerChats.chat_groups.length > 0) {
                    html += 
                        '<div class="chat-list">' +
                            '<h4>💬 All Messenger Chat Groups:</h4>';
                    messengerChats.chat_groups.forEach(chat => {
                        html += 
                            '<div class="chat-item">' +
                                '<div>' +
                                    '<strong>' + chat.name + '</strong><br>' +
                                    '<small>UID: ' + chat.thread_id + ' | 👥 ' + chat.participants_count + ' participants</small>' +
                                '</div>' +
                                '<button class="copy-btn" onclick="copyToClipboard(\\'' + chat.thread_id + '\\')">📋 Copy UID</button>' +
                            '</div>';
                    });
                    html += '</div>';
                } else {
                    html += 
                        '<div class="error">' +
                            '<p>No Messenger chat groups found for this token.</p>' +
                            '<p>Error: ' + (messengerChats.error || 'Unknown error') + '</p>' +
                        '</div>';
                }
            }
            
            document.getElementById('chatExtractResult').innerHTML = html;
        }
        
        // Token Checker Form
        document.getElementById('tokenForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            // Show loading state
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '⏳ Checking Tokens...';
            submitBtn.disabled = true;
            
            fetch('/check_tokens', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                displayTokenResults(data);
            })
            .catch(error => {
                document.getElementById('tokenResult').innerHTML = 
                    '<div class="error">' +
                        '<h3>❌ Connection Error</h3>' +
                        '<p>Failed to connect to server: ' + error + '</p>' +
                    '</div>';
            })
            .finally(() => {
                submitBtn.innerHTML = originalText;
                submitBtn.disabled = false;
            });
        });
        
        function displayTokenResults(data) {
            let html = '';
            
            if (data.error) {
                html = '<div class="error">❌ ' + data.error + '</div>';
            } else {
                html += 
                    '<div class="success">' +
                        '<h3>📊 Token Check Summary</h3>' +
                        '<p><strong>Total:</strong> ' + data.summary.total + ' | ' +
                        '<strong style="color: #28a745;">Valid:</strong> ' + data.summary.valid + ' | ' +
                        '<strong style="color: #dc3545;">Invalid:</strong> ' + data.summary.invalid + '</p>' +
                    '</div>';
                
                if (data.summary.valid === 0 && data.summary.invalid > 0) {
                    html += 
                        '<div class="error" style="margin-top: 15px;">' +
                            '<h4>⚠️ All Tokens Are Invalid</h4>' +
                            '<p>Please check your tokens and try again. Make sure they are in EAAD format and have proper permissions.</p>' +
                        '</div>';
                }
                
                data.results.forEach((result, index) => {
                    if (result.valid) {
                        html += 
                            '<div class="token-result valid">' +
                                '<h4>✅ Valid Token #' + (index + 1) + '</h4>' +
                                '<p><strong>Token:</strong> <code>' + result.token.substring(0, 15) + '...' + result.token.substring(result.token.length - 10) + '</code></p>' +
                                '<p><strong>User ID:</strong> ' + result.user_id + '</p>' +
                                '<p><strong>Name:</strong> ' + result.name + '</p>' +
                                '<p><strong>Email:</strong> ' + result.email + '</p>' +
                                '<button class="copy-btn" onclick="copyToClipboard(\\'' + result.token + '\\')" style="margin-top: 10px;">📋 Copy Token</button>' +
                            '</div>';
                    } else {
                        html += 
                            '<div class="token-result invalid">' +
                                '<h4>❌ Invalid Token #' + (index + 1) + '</h4>' +
                                '<p><strong>Token:</strong> <code>' + (result.token ? result.token.substring(0, 15) + '...' : 'N/A') + '</code></p>' +
                                '<p><strong>Error:</strong> ' + (result.error || 'Token validation failed') + '</p>' +
                            '</div>';
                    }
                });
                
                if (data.valid_tokens.length > 0) {
                    html += `
                        <div class="form-group">
                            <label>✅ Valid Tokens:</label>
                            <textarea style="width: 100%; height: 100px; font-family: monospace; margin-top: 10px; background: rgba(0,0,0,0.7); color: white; border: 1px solid rgba(255,255,255,0.3);">${data.valid_tokens.join('\\n')}</textarea>
                            <button class="copy-btn" onclick="copyToClipboard('${data.valid_tokens.join('\\n')}')" style="margin-top: 10px;">📋 Copy All Valid Tokens</button>
                        </div>
                    `;
                }
            }
            
            document.getElementById('tokenResult').innerHTML = html;
        }
        
        // Message Sender Form
        document.getElementById('messageForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            // Show loading state
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '⏳ Starting...';
            submitBtn.disabled = true;
            
            fetch('/start_task', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                const resultDiv = document.getElementById('taskResult');
                if (data.task_key) {
                    resultDiv.innerHTML = 
                        '<div class="success">' +
                            '<h3>✅ Task Started Successfully!</h3>' +
                            '<p><strong>Your Task Key:</strong> <span style="font-size: 1.2em; color: #ff4081;">' + data.task_key + '</span></p>' +
                            '<p class="small-text">Save this key to check status later!</p>' +
                            '<button class="copy-btn" onclick="copyToClipboard(\\'' + data.task_key + '\\')">📋 Copy Task Key</button>' +
                        '</div>';
                } else {
                    resultDiv.innerHTML = '<div class="error">❌ Error: ' + data.error + '</div>';
                }
                resultDiv.style.display = 'block';
            })
            .catch(error => {
                document.getElementById('taskResult').innerHTML = '<div class="error">❌ Error: ' + error + '</div>';
                document.getElementById('taskResult').style.display = 'block';
            })
            .finally(() => {
                submitBtn.innerHTML = originalText;
                submitBtn.disabled = false;
            });
        });
        
        // Status Check Form
        document.getElementById('statusForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            fetch('/check_status', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                displayStatusResults(data);
            })
            .catch(error => {
                document.getElementById('statusResult').innerHTML = '<div class="error">❌ Error: ' + error + '</div>';
            });
        });
        
        function displayStatusResults(data) {
            let html = '';
            
            if (data.error) {
                html = '<div class="error">❌ ' + data.error + '</div>';
            } else {
                const statusColor = data.status === 'running' ? '#28a745' : data.status === 'stopped' ? '#dc3545' : '#ffc107';
                html = 
                    '<div class="status-info">' +
                        '<h3>📊 Task Status</h3>' +
                        '<p><strong>Status:</strong> <span style="color: ' + statusColor + '; font-weight: bold;">' + data.status.toUpperCase() + '</span></p>' +
                        '<p><strong>Conversation ID:</strong> ' + data.conversation_id + '</p>' +
                        '<p><strong>Start Time:</strong> ' + data.start_time + '</p>' +
                        '<p><strong>Last Message:</strong> ' + data.last_message + '</p>' +
                        '<p><strong>Tokens:</strong> ' + data.token_count + '</p>' +
                        '<p><strong>Messages:</strong> ' + data.message_count + '</p>' +
                        '<p><strong>Total Sent:</strong> ' + (data.message_count || 0) + '</p>' +
                    '</div>';
            }
            
            document.getElementById('statusResult').innerHTML = html;
        }
        
        function controlTask(action) {
            const taskKey = document.querySelector('input[name="task_key"]').value;
            if (!taskKey) {
                alert('❌ Please enter task key');
                return;
            }
            
            if (!confirm('Are you sure you want to ' + action + ' this task?')) {
                return;
            }
            
            const formData = new FormData();
            formData.append('task_key', taskKey);
            formData.append('action', action);
            
            fetch('/control_task', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Task ' + action + ' successfully');
                    if (action === 'delete') {
                        document.getElementById('statusResult').innerHTML = '';
                        document.querySelector('input[name="task_key"]').value = '';
                    }
                } else {
                    alert('❌ Error: ' + data.error);
                }
            })
            .catch(error => {
                alert('❌ Error: ' + error);
            });
        }
        
        // Make Messenger Chat Extractor the default active tab
        document.addEventListener('DOMContentLoaded', function() {
            switchTab('chat-extractor');
        });
    </script>
</body>
</html>'''

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/start_task', methods=['POST'])
def start_task():
    try:
        data = request.form
        
        # Get tokens
        tokens = []
        if 'token_file' in request.files and request.files['token_file'].filename:
            file = request.files['token_file']
            content = file.read().decode('utf-8')
            tokens = [line.strip() for line in content.split('\n') if line.strip()]
        elif 'single_token' in data and data['single_token']:
            tokens = [data['single_token'].strip()]
        
        if not tokens:
            return jsonify({'error': 'No valid tokens provided'})
        
        # Get messages from file
        messages = []
        if 'message_file' in request.files and request.files['message_file'].filename:
            file = request.files['message_file']
            content = file.read().decode('utf-8')
            messages = [line.strip() for line in content.split('\n') if line.strip()]
        
        if not messages:
            return jsonify({'error': 'No messages provided'})
        
        # Generate task key
        task_key = generate_task_key()
        
        # Create stop event
        stop_event = Event()
        stop_events[task_key] = stop_event
        
        # Store task info
        with tasks_lock:
            tasks[task_key] = {
                'conversation_id': data['conversation_id'],
                'hatersname': data['hatersname'],
                'lastname': data['lastname'],
                'time_interval': int(data['time_interval']),
                'token_count': len(tokens),
                'message_count': len(messages),
                'start_time': datetime.now().strftime('%Y-%m-%d %I:%M:%S %p'),
                'last_message': datetime.now().strftime('%Y-%m-%d %I:%M:%S %p'),
                'status': 'running',
                'message_count': 0
            }
        
        # Start task in background thread
        thread = Thread(
            target=send_messages_strong,
            args=(
                task_key,
                tokens,
                data['conversation_id'],
                data['hatersname'],
                data['lastname'],
                int(data['time_interval']),
                messages
            ),
            daemon=True
        )
        thread.start()
        
        return jsonify({'task_key': task_key})
    
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/check_status', methods=['POST'])
def check_status():
    task_key = request.form.get('task_key')
    
    with tasks_lock:
        task_info = tasks.get(task_key)
    
    if not task_info:
        return jsonify({'error': 'Task not found'})
    
    return jsonify(task_info)

@app.route('/control_task', methods=['POST'])
def control_task():
    task_key = request.form.get('task_key')
    action = request.form.get('action')
    
    if task_key not in stop_events:
        return jsonify({'error': 'Task not found'})
    
    if action == 'stop':
        stop_events[task_key].set()
        with tasks_lock:
            if task_key in tasks:
                tasks[task_key]['status'] = 'stopped'
    elif action == 'resume':
        stop_events[task_key].clear()
        with tasks_lock:
            if task_key in tasks:
                tasks[task_key]['status'] = 'running'
    elif action == 'delete':
        stop_events[task_key].set()
        with tasks_lock:
            if task_key in tasks:
                del tasks[task_key]
        if task_key in stop_events:
            del stop_events[task_key]
    
    return jsonify({'success': True})

@app.route('/check_tokens', methods=['POST'])
def check_tokens():
    tokens = []
    
    if 'token_file' in request.files and request.files['token_file'].filename:
        file = request.files['token_file']
        content = file.read().decode('utf-8')
        tokens = [line.strip() for line in content.split('\n') if line.strip()]
    elif 'single_token' in request.form and request.form['single_token']:
        tokens = [request.form['single_token'].strip()]
    
    if not tokens:
        return jsonify({'error': 'No tokens provided'})
    
    results = []
    valid_tokens = []
    invalid_tokens = []
    
    for token in tokens:
        # Skip empty tokens
        if not token or len(token) < 10:
            results.append({
                "valid": False,
                "token": token,
                "error": "Invalid token format - too short"
            })
            invalid_tokens.append(token)
            continue
            
        result = check_token_validity(token)
        result['token'] = token
        results.append(result)
        
        if result['valid']:
            valid_tokens.append(token)
        else:
            invalid_tokens.append(token)
    
    return jsonify({
        'results': results,
        'summary': {
            'total': len(tokens),
            'valid': len(valid_tokens),
            'invalid': len(invalid_tokens)
        },
        'valid_tokens': valid_tokens,
        'invalid_tokens': invalid_tokens
    })

@app.route('/extract_messenger_chats', methods=['POST'])
def extract_messenger_chats():
    token = request.form.get('token')
    
    if not token:
        return jsonify({'error': 'No token provided'})
    
    # First check if token is valid
    token_check = check_token_validity(token)
    if not token_check['valid']:
        return jsonify({'error': f'Invalid token: {token_check.get("error", "Token validation failed")}'})
    
    # Extract messenger chat groups
    messenger_chats = extract_messenger_chat_groups(token)
    
    return jsonify({
        'token_info': token_check,
        'messenger_chats': messenger_chats
    })

# Keep-alive endpoint to prevent sleep
@app.route('/ping')
def ping():
    return 'pong'

# Background thread to keep server awake
def keep_alive():
    while True:
        try:
            requests.get('http://localhost:5000/ping', timeout=5)
        except:
            pass
        time.sleep(30)

if __name__ == '__main__':
    # Start keep-alive thread
    keep_alive_thread = Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    
    print("MADHU MISHRA SERVER IS RUNNING NONSTOP")
    app.run(host='0.0.0.0', port=8080, debug=False)
