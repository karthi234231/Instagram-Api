#!/usr/bin/env python3
"""
Instagram Non-Follower Manager - PRO SINGLE FILE EDITION
Run: pip install fastapi uvicorn instagrapi python-multipart
     uvicorn app:app --reload
Then open http://localhost:8000
"""

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, PleaseWait
from typing import List, Dict, Any, Optional
import asyncio
import io
import csv
import json
import time
from collections import deque
import logging

# -------------------- Configuration --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Pydantic Models --------------------
class LoginData(BaseModel):
    username: str
    password: str

class InstagramUser(BaseModel):
    pk: int
    username: str
    full_name: str
    is_private: bool
    is_verified: bool
    profile_pic_url: str
    follower_count: int = 0

# -------------------- In-Memory Store --------------------
active_clients: Dict[str, Client] = {}          # username -> instagrapi client
comparison_cache: Dict[str, Dict] = {}          # username -> comparison result
activity_logs: Dict[str, deque] = {}            # username -> deque of log entries
MAX_LOG_ENTRIES = 100

def add_activity_log(username: str, message: str):
    """Add timestamped activity log entry."""
    if username not in activity_logs:
        activity_logs[username] = deque(maxlen=MAX_LOG_ENTRIES)
    timestamp = time.strftime("%H:%M:%S")
    activity_logs[username].appendleft(f"[{timestamp}] {message}")
    logger.info(f"[{username}] {message}")

# -------------------- Helper Functions --------------------
def map_user(user) -> InstagramUser:
    return InstagramUser(
        pk=user.pk,
        username=user.username,
        full_name=user.full_name,
        is_private=user.is_private,
        is_verified=user.is_verified,
        profile_pic_url=user.profile_pic_url,
        follower_count=getattr(user, 'follower_count', 0)
    )

async def fetch_followers(client: Client, user_id: int) -> List[InstagramUser]:
    loop = asyncio.get_event_loop()
    # instagrapi is sync; run in thread pool
    followers_dict = await loop.run_in_executor(None, client.user_followers, user_id)
    return [map_user(u) for u in followers_dict.values()]

async def fetch_following(client: Client, user_id: int) -> List[InstagramUser]:
    loop = asyncio.get_event_loop()
    following_dict = await loop.run_in_executor(None, client.user_following, user_id)
    return [map_user(u) for u in following_dict.values()]

def compute_comparison(followers: List[InstagramUser], following: List[InstagramUser]) -> Dict:
    follower_set = {u.pk for u in followers}
    following_set = {u.pk for u in following}
    non_followers = [u for u in following if u.pk not in follower_set]
    followers_not_following_back = [u for u in followers if u.pk not in following_set]
    mutual = [u for u in followers if u.pk in following_set]
    return {
        "non_followers": [u.dict() for u in non_followers],
        "followers_not_following_back": [u.dict() for u in followers_not_following_back],
        "mutual_followers": [u.dict() for u in mutual],
        "followers_count": len(followers),
        "following_count": len(following),
        "non_followers_count": len(non_followers),
        "mutual_count": len(mutual)
    }

# -------------------- FastAPI App --------------------
app = FastAPI(title="Instagram Non-Follower Manager", version="2.0")

# -------------------- API Endpoints --------------------
@app.post("/api/login")
async def api_login(login: LoginData):
    """Login to Instagram and store client in memory."""
    client = Client()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, client.login, login.username, login.password)
        active_clients[login.username] = client
        add_activity_log(login.username, "✅ Login successful")
        return {"status": "ok", "username": login.username}
    except Exception as e:
        logger.error(f"Login failed for {login.username}: {e}")
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/api/compare")
async def api_compare(username: str):
    """Fetch followers/following, compute differences, cache results."""
    client = active_clients.get(username)
    if not client:
        raise HTTPException(status_code=401, detail="Not logged in")
    add_activity_log(username, "🔍 Fetching followers...")
    followers = await fetch_followers(client, client.user_id)
    add_activity_log(username, f"📥 Fetched {len(followers)} followers")
    add_activity_log(username, "🔍 Fetching following...")
    following = await fetch_following(client, client.user_id)
    add_activity_log(username, f"📤 Fetched {len(following)} following")
    add_activity_log(username, "⚙️ Comparing lists...")
    result = compute_comparison(followers, following)
    comparison_cache[username] = result
    add_activity_log(username, f"✅ Comparison complete: {result['non_followers_count']} non‑followers")
    return result

@app.get("/api/activity/{username}")
async def get_activity(username: str):
    """Return recent activity logs for the user."""
    logs = list(activity_logs.get(username, []))
    return {"logs": logs}

@app.get("/api/export/csv/{username}")
async def export_csv(username: str):
    """Export non‑followers as CSV."""
    data = comparison_cache.get(username)
    if not data:
        raise HTTPException(status_code=404, detail="No comparison data. Run /compare first.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Username", "Full Name", "Private", "Verified", "Profile URL"])
    for u in data["non_followers"]:
        writer.writerow([
            u["username"], u["full_name"], u["is_private"], u["is_verified"],
            f"https://instagram.com/{u['username']}"
        ])
    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=non_followers.csv"
    add_activity_log(username, f"📁 Exported {len(data['non_followers'])} non‑followers to CSV")
    return response

@app.get("/api/export/json/{username}")
async def export_json(username: str):
    """Export non‑followers as JSON."""
    data = comparison_cache.get(username)
    if not data:
        raise HTTPException(status_code=404, detail="No comparison data.")
    export_data = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "username": username,
        "non_followers": data["non_followers"]
    }
    json_str = json.dumps(export_data, indent=2)
    response = StreamingResponse(iter([json_str]), media_type="application/json")
    response.headers["Content-Disposition"] = "attachment; filename=non_followers.json"
    add_activity_log(username, f"📁 Exported {len(data['non_followers'])} non‑followers to JSON")
    return response

# -------------------- Frontend (Embedded React + Tailwind) --------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Instagram Non-Follower Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <style>
        body { transition: background-color 0.3s, color 0.3s; }
        .dark { background-color: #1a1a2e; color: #eee; }
        .toast { transition: all 0.3s ease; }
        .activity-log { font-family: monospace; font-size: 0.8rem; }
        .card-hover { transition: transform 0.2s, box-shadow 0.2s; }
        .card-hover:hover { transform: translateY(-2px); box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1); }
        .unfollow-btn { transition: all 0.2s; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const { useState, useEffect } = React;

        // -------------------- Toast Context --------------------
        const ToastContext = React.createContext(null);
        const useToast = () => React.useContext(ToastContext);

        const ToastProvider = ({ children }) => {
            const [toasts, setToasts] = useState([]);
            const addToast = (message, type = 'info') => {
                const id = Date.now();
                setToasts(prev => [...prev, { id, message, type }]);
                setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000);
            };
            return (
                <ToastContext.Provider value={{ addToast }}>
                    {children}
                    <div className="fixed bottom-4 right-4 z-50 space-y-2">
                        {toasts.map(t => (
                            <div key={t.id} className={`px-4 py-2 rounded shadow-lg text-white ${
                                t.type === 'error' ? 'bg-red-500' : t.type === 'success' ? 'bg-green-500' : 'bg-blue-500'
                            }`}>{t.message}</div>
                        ))}
                    </div>
                </ToastContext.Provider>
            );
        };

        // -------------------- API Service --------------------
        const api = {
            login: async (username, password) => {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                if (!res.ok) throw new Error(await res.text());
                return res.json();
            },
            compare: async (username) => {
                const res = await fetch(`/api/compare?username=${encodeURIComponent(username)}`, { method: 'POST' });
                if (!res.ok) throw new Error(await res.text());
                return res.json();
            },
            getActivity: async (username) => {
                const res = await fetch(`/api/activity/${encodeURIComponent(username)}`);
                if (!res.ok) return { logs: [] };
                return res.json();
            },
            exportCSV: (username) => `/api/export/csv/${encodeURIComponent(username)}`,
            exportJSON: (username) => `/api/export/json/${encodeURIComponent(username)}`
        };

        // -------------------- Helper: Deep link to Instagram app --------------------
        const openInstagramProfile = (username) => {
            const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
            const isAndroid = /Android/.test(navigator.userAgent);
            let deepLink = '';
            const fallbackUrl = `https://www.instagram.com/${username}`;
            if (isIOS) deepLink = `instagram://user?username=${username}`;
            else if (isAndroid) deepLink = `intent://user?username=${username}#Intent;scheme=instagram;package=com.instagram.android;end`;
            else { window.open(fallbackUrl, '_blank'); return; }
            window.location.href = deepLink;
            setTimeout(() => { window.location.href = fallbackUrl; }, 500);
        };

        // -------------------- Login Component --------------------
        const LoginForm = ({ onLoginSuccess }) => {
            const [username, setUsername] = useState('');
            const [password, setPassword] = useState('');
            const [loading, setLoading] = useState(false);
            const { addToast } = useToast();
            const handleSubmit = async (e) => {
                e.preventDefault();
                setLoading(true);
                try {
                    await api.login(username, password);
                    addToast('Login successful!', 'success');
                    onLoginSuccess(username);
                } catch (err) {
                    addToast(err.message, 'error');
                } finally {
                    setLoading(false);
                }
            };
            return (
                <div className="min-h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-900 p-4">
                    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 w-full max-w-md">
                        <h1 className="text-2xl font-bold text-center mb-6 text-gray-800 dark:text-white">Instagram Non-Follower Manager</h1>
                        <form onSubmit={handleSubmit}>
                            <input type="text" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)}
                                className="w-full p-3 mb-4 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white" required />
                            <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)}
                                className="w-full p-3 mb-6 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white" required />
                            <button type="submit" disabled={loading}
                                className="w-full bg-gradient-to-r from-purple-500 to-pink-500 text-white p-3 rounded-lg font-semibold hover:opacity-90 transition">
                                {loading ? 'Logging in...' : 'Login'}
                            </button>
                        </form>
                        <p className="text-xs text-center text-gray-500 dark:text-gray-400 mt-6">
                            🔒 Your credentials never leave your computer. Session stored in memory only.
                        </p>
                    </div>
                </div>
            );
        };

        // -------------------- Dashboard Component --------------------
        const Dashboard = ({ username, onLogout }) => {
            const [data, setData] = useState(null);
            const [loading, setLoading] = useState(false);
            const [activityLogs, setActivityLogs] = useState([]);
            const [selectedUsers, setSelectedUsers] = useState([]);
            const [filterText, setFilterText] = useState('');
            const [filterVerified, setFilterVerified] = useState(false);
            const [filterPrivate, setFilterPrivate] = useState(false);
            const [sortBy, setSortBy] = useState('username'); // 'username', 'followers'
            const { addToast } = useToast();
            const [darkMode, setDarkMode] = useState(localStorage.getItem('theme') === 'dark');

            useEffect(() => {
                if (darkMode) document.body.classList.add('dark');
                else document.body.classList.remove('dark');
                localStorage.setItem('theme', darkMode ? 'dark' : 'light');
            }, [darkMode]);

            const fetchComparison = async () => {
                setLoading(true);
                try {
                    const res = await api.compare(username);
                    setData(res);
                    addToast(`Loaded ${res.non_followers_count} non‑followers`, 'success');
                    fetchActivity();
                } catch (err) {
                    addToast(err.message, 'error');
                } finally {
                    setLoading(false);
                }
            };

            const fetchActivity = async () => {
                try {
                    const { logs } = await api.getActivity(username);
                    setActivityLogs(logs);
                } catch (err) { /* ignore */ }
            };

            useEffect(() => {
                fetchComparison();
                const interval = setInterval(fetchActivity, 5000);
                return () => clearInterval(interval);
            }, []);

            const nonFollowers = data?.non_followers || [];
            const filtered = nonFollowers.filter(u => {
                if (filterText && !u.username.toLowerCase().includes(filterText.toLowerCase()) && !u.full_name.toLowerCase().includes(filterText.toLowerCase())) return false;
                if (filterVerified && !u.is_verified) return false;
                if (filterPrivate && !u.is_private) return false;
                return true;
            }).sort((a,b) => {
                if (sortBy === 'username') return a.username.localeCompare(b.username);
                if (sortBy === 'followers') return (b.follower_count || 0) - (a.follower_count || 0);
                return 0;
            });

            const toggleSelectAll = () => {
                if (selectedUsers.length === filtered.length) setSelectedUsers([]);
                else setSelectedUsers(filtered.map(u => u.username));
            };
            const toggleSelect = (username) => {
                if (selectedUsers.includes(username)) setSelectedUsers(selectedUsers.filter(u => u !== username));
                else setSelectedUsers([...selectedUsers, username]);
            };
            const copySelectedUsernames = () => {
                navigator.clipboard.writeText(selectedUsers.join('\\n'));
                addToast(`Copied ${selectedUsers.length} usernames`, 'success');
            };
            const exportSelected = (format) => {
                if (selectedUsers.length === 0) { addToast('Select at least one user', 'error'); return; }
                const selectedData = filtered.filter(u => selectedUsers.includes(u.username));
                let content = '';
                if (format === 'csv') {
                    content = 'Username,Full Name,Private,Verified,Profile URL\\n' + selectedData.map(u => `${u.username},${u.full_name},${u.is_private},${u.is_verified},https://instagram.com/${u.username}`).join('\\n');
                    const blob = new Blob([content], {type: 'text/csv'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'selected_non_followers.csv'; a.click();
                    URL.revokeObjectURL(url);
                } else {
                    content = JSON.stringify(selectedData, null, 2);
                    const blob = new Blob([content], {type: 'application/json'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'selected_non_followers.json'; a.click();
                    URL.revokeObjectURL(url);
                }
                addToast(`Exported ${selectedUsers.length} users`, 'success');
            };
            const bulkUnfollow = () => {
                if (selectedUsers.length === 0) { addToast('Select users to unfollow', 'error'); return; }
                if (confirm(`You are about to open ${selectedUsers.length} Instagram profiles. You will need to manually unfollow each. Proceed?`)) {
                    selectedUsers.forEach(username => openInstagramProfile(username));
                    setSelectedUsers([]);
                }
            };

            if (loading && !data) return <div className="min-h-screen flex items-center justify-center">Loading Instagram data... (may take 1-2 min)</div>;
            if (!data) return <div className="min-h-screen flex items-center justify-center">Click "Load Data" to start</div>;

            return (
                <div className="min-h-screen bg-gray-100 dark:bg-gray-900 p-4 md:p-6">
                    <div className="max-w-7xl mx-auto">
                        {/* Header */}
                        <div className="flex flex-wrap justify-between items-center mb-6 gap-4">
                            <div className="flex items-center gap-3">
                                <div className="
