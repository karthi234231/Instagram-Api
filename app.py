#!/usr/bin/env python3
"""
Instagram Non-Follower Manager - PRO SINGLE FILE EDITION
Run: pip install fastapi uvicorn instagrapi python-multipart
     uvicorn app:app --reload
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from instagrapi import Client
from typing import List, Dict
import asyncio
import io
import csv
import json
import time
from collections import deque
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Models --------------------
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
active_clients: Dict[str, Client] = {}
comparison_cache: Dict[str, Dict] = {}
activity_logs: Dict[str, deque] = {}

def add_activity_log(username: str, message: str):
    if username not in activity_logs:
        activity_logs[username] = deque(maxlen=100)
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

async def fetch_followers(client: Client, user_id: int):
    loop = asyncio.get_event_loop()
    followers_dict = await loop.run_in_executor(None, client.user_followers, user_id)
    return [map_user(u) for u in followers_dict.values()]

async def fetch_following(client: Client, user_id: int):
    loop = asyncio.get_event_loop()
    following_dict = await loop.run_in_executor(None, client.user_following, user_id)
    return [map_user(u) for u in following_dict.values()]

def compute_comparison(followers, following):
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
app = FastAPI(title="Instagram Non-Follower Manager")
@app.post("/api/login")
async def api_login(login: LoginData):
    client = Client()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, client.login, login.username, login.password)
        active_clients[login.username] = client
        add_activity_log(login.username, "✅ Login successful")
        return {"status": "ok", "username": login.username}
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/api/compare")
async def api_compare(username: str):
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
    logs = list(activity_logs.get(username, []))
    return {"logs": logs}

@app.get("/api/export/csv/{username}")
async def export_csv(username: str):
    data = comparison_cache.get(username)
    if not data:
        raise HTTPException(status_code=404, detail="No comparison data")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Username", "Full Name", "Private", "Verified", "Profile URL"])
    for u in data["non_followers"]:
        writer.writerow([u["username"], u["full_name"], u["is_private"], u["is_verified"], f"https://instagram.com/{u['username']}"])
    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=non_followers.csv"
    add_activity_log(username, f"📁 Exported {len(data['non_followers'])} non‑followers to CSV")
    return response

@app.get("/api/export/json/{username}")
async def export_json(username: str):
    data = comparison_cache.get(username)
    if not data:
        raise HTTPException(status_code=404, detail="No comparison data")
    export_data = {"exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "username": username, "non_followers": data["non_followers"]}
    json_str = json.dumps(export_data, indent=2)
    response = StreamingResponse(iter([json_str]), media_type="application/json")
    response.headers["Content-Disposition"] = "attachment; filename=non_followers.json"
    add_activity_log(username, f"📁 Exported {len(data['non_followers'])} non‑followers to JSON")
    return response
     # -------------------- Frontend HTML (fixed) --------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram Non-Follower Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <style>body{transition:background-color 0.3s}.dark{background:#1a1a2e;color:#eee}</style>
</head>
<body><div id="root"></div>
<script type="text/babel">
const { useState, useEffect } = React;

const ToastContext = React.createContext(null);
const useToast = () => React.useContext(ToastContext);

const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);
    const addToast = (msg, type='info') => {
        const id = Date.now();
        setToasts(p => [...p, {id, msg, type}]);
        setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 3000);
    };
    return (
        <ToastContext.Provider value={{addToast}}>
            {children}
            <div className="fixed bottom-4 right-4 z-50 space-y-2">
                {toasts.map(t => <div key={t.id} className={`px-4 py-2 rounded shadow text-white ${t.type==='error'?'bg-red-500':t.type==='success'?'bg-green-500':'bg-blue-500'}`}>{t.msg}</div>)}
            </div>
        </ToastContext.Provider>
    );
};

const api = {
    login: async (username, password) => {
        const res = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
        if(!res.ok) throw new Error(await res.text());
        return res.json();
    },
    compare: async (username) => {
        const res = await fetch(`/api/compare?username=${encodeURIComponent(username)}`, {method:'POST'});
        if(!res.ok) throw new Error(await res.text());
        return res.json();
    },
    getActivity: async (username) => {
        const res = await fetch(`/api/activity/${encodeURIComponent(username)}`);
        if(!res.ok) return {logs:[]};
        return res.json();
    },
    exportCSV: (username) => `/api/export/csv/${encodeURIComponent(username)}`,
    exportJSON: (username) => `/api/export/json/${encodeURIComponent(username)}`
};

const openInstagramProfile = (username) => {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isAndroid = /Android/.test(navigator.userAgent);
    const fallback = `https://www.instagram.com/${username}`;
    if(isIOS) window.location.href = `instagram://user?username=${username}`;
    else if(isAndroid) window.location.href = `intent://user?username=${username}#Intent;scheme=instagram;package=com.instagram.android;end`;
    else window.open(fallback, '_blank');
    setTimeout(() => { window.location.href = fallback; }, 500);
};

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
        } catch(err) { addToast(err.message, 'error'); }
        finally { setLoading(false); }
    };
    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-900 p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 w-full max-w-md">
                <h1 className="text-2xl font-bold text-center mb-6">Instagram Non-Follower Manager</h1>
                <form onSubmit={handleSubmit}>
                    <input type="text" placeholder="Username" value={username} onChange={e=>setUsername(e.target.value)} className="w-full p-3 mb-4 border rounded-lg dark:bg-gray-700" required />
                    <input type="password" placeholder="Password" value={password} onChange={e=>setPassword(e.target.value)} className="w-full p-3 mb-6 border rounded-lg dark:bg-gray-700" required />
                    <button type="submit" disabled={loading} className="w-full bg-gradient-to-r from-purple-500 to-pink-500 text-white p-3 rounded-lg font-semibold hover:opacity-90">{loading?'Logging in...':'Login'}</button>
                </form>
                <p className="text-xs text-center text-gray-500 mt-6">🔒 Credentials never leave the server. Session in memory only.</p>
            </div>
        </div>
    );
};

const Dashboard = ({ username, onLogout }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [activityLogs, setActivityLogs] = useState([]);
    const [selectedUsers, setSelectedUsers] = useState([]);
    const [filterText, setFilterText] = useState('');
    const [filterVerified, setFilterVerified] = useState(false);
    const [filterPrivate, setFilterPrivate] = useState(false);
    const [sortBy, setSortBy] = useState('username');
    const { addToast } = useToast();
    const [darkMode, setDarkMode] = useState(localStorage.getItem('theme') === 'dark');

    useEffect(() => {
        if(darkMode) document.body.classList.add('dark');
        else document.body.classList.remove('dark');
        localStorage.setItem('theme', darkMode ? 'dark' : 'light');
    }, [darkMode]);

    const fetchComparison = async () => {
        setLoading(true);
        try {
            const res = await api.compare(username);
            setData(res);
            addToast(`Loaded ${res.non_followers_count} non-followers`, 'success');
        } catch(err) { addToast(err.message, 'error'); }
        finally { setLoading(false); }
    };

    const fetchActivity = async () => {
        try {
            const { logs } = await api.getActivity(username);
            setActivityLogs(logs);
        } catch(e) {}
    };

    useEffect(() => {
        fetchComparison();
        const interval = setInterval(fetchActivity, 5000);
        return () => clearInterval(interval);
    }, []);

    const nonFollowers = data?.non_followers || [];
    const filtered = nonFollowers.filter(u => {
        if(filterText && !u.username.toLowerCase().includes(filterText.toLowerCase()) && !u.full_name.toLowerCase().includes(filterText.toLowerCase())) return false;
        if(filterVerified && !u.is_verified) return false;
        if(filterPrivate && !u.is_private) return false;
        return true;
    }).sort((a,b) => {
        if(sortBy === 'username') return a.username.localeCompare(b.username);
        if(sortBy === 'followers') return (b.follower_count||0) - (a.follower_count||0);
        return 0;
    });

    const toggleSelectAll = () => {
        if(selectedUsers.length === filtered.length) setSelectedUsers([]);
        else setSelectedUsers(filtered.map(u=>u.username));
    };
    const toggleSelect = (uname) => {
        if(selectedUsers.includes(uname)) setSelectedUsers(selectedUsers.filter(u=>u!==uname));
        else setSelectedUsers([...selectedUsers, uname]);
    };
    const copySelectedUsernames = () => {
        navigator.clipboard.writeText(selectedUsers.join('\\n'));
        addToast(`Copied ${selectedUsers.length} usernames`, 'success');
    };
    const exportSelected = (format) => {
        if(selectedUsers.length===0) { addToast('Select at least one user','error'); return; }
        const selectedData = filtered.filter(u=>selectedUsers.includes(u.username));
        if(format==='csv') {
            let csv = 'Username,Full Name,Private,Verified,Profile URL\\n' + selectedData.map(u=>`${u.username},${u.full_name},${u.is_private},${u.is_verified},https://instagram.com/${u.username}`).join('\\n');
            const blob = new Blob([csv], {type:'text/csv'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href=url; a.download='selected_non_followers.csv'; a.click();
            URL.revokeObjectURL(url);
        } else {
            const blob = new Blob([JSON.stringify(selectedData,null,2)], {type:'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href=url; a.download='selected_non_followers.json'; a.click();
            URL.revokeObjectURL(url);
        }
        addToast(`Exported ${selectedUsers.length} users`, 'success');
    };
    const bulkUnfollow = () => {
        if(selectedUsers.length===0) { addToast('Select users to unfollow','error'); return; }
        if(confirm(`Open ${selectedUsers.length} Instagram profiles to manually unfollow?`)) {
            selectedUsers.forEach(u=>openInstagramProfile(u));
            setSelectedUsers([]);
        }
    };

    if(loading && !data) return <div className="min-h-screen flex items-center justify-center">Loading Instagram data... (may take 1-2 min)</div>;
    if(!data) return <div className="min-h-screen flex items-center justify-center"><button onClick={fetchComparison} className="bg-purple-500 text-white px-4 py-2 rounded">Load Data</button></div>;

    return (
        <div className="min-h-screen bg-gray-100 dark:bg-gray-900 p-4 md:p-6">
            <div className="max-w-7xl mx-auto">
                <div className="flex flex-wrap justify-between items-center mb-6 gap-4">
                    <div className="flex items-center gap-3">
                        <div className="w-12 h-12 bg-gradient-to-br from-purple-500 to-pink-500 rounded-full flex items-center justify-center text-white font-bold text-xl">IG</div>
                        <div><h1 className="text-2xl font-bold">@{username}</h1><p className="text-sm text-gray-500">Non-Follower Manager</p></div>
                    </div>
                    <div className="flex gap-2">
                        <button onClick={()=>setDarkMode(!darkMode)} className="p-2 rounded-full bg-gray-200 dark:bg-gray-700">{darkMode?'☀️':'🌙'}</button>
                        <button onClick={onLogout} className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600">Logout</button>
                    </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow"><div className="text-gray-500 text-sm">Followers</div><div className="text-2xl font-bold">{data.followers_count.toLocaleString()}</div></div>
                    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow"><div className="text-gray-500 text-sm">Following</div><div className="text-2xl font-bold">{data.following_count.toLocaleString()}</div></div>
                    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow"><div className="text-gray-500 text-sm">Non‑Followers</div><div className="text-2xl font-bold text-red-500">{data.non_followers_count.toLocaleString()}</div></div>
                    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow"><div className="text-gray-500 text-sm">Mutual</div><div className="text-2xl font-bold text-green-500">{data.mutual_count.toLocaleString()}</div></div>
                </div>
                <div className="grid lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl shadow overflow-hidden">
                        <div className="p-4 border-b dark:border-gray-700 flex flex-wrap gap-2 justify-between items-center">
                            <div className="flex gap-2 flex-wrap">
                                <input type="text" placeholder="Search username..." value={filterText} onChange={e=>setFilterText(e.target.value)} className="px-3 py-1 border rounded dark:bg-gray-700" />
                                <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filterVerified} onChange={e=>setFilterVerified(e.target.checked)} /> Verified</label>
                                <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filterPrivate} onChange={e=>setFilterPrivate(e.target.checked)} /> Private</label>
                                <select value={sortBy} onChange={e=>setSortBy(e.target.value)} className="px-2 py-1 border rounded"><option value="username">Sort by Username</option><option value="followers">Sort by Followers</option></select>
                            </div>
                            <div className="flex gap-2">
                                <button onClick={toggleSelectAll} className="text-sm bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">Select All</button>
                                <button onClick={()=>setSelectedUsers([])} className="text-sm bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">Clear</button>
                                <button onClick={copySelectedUsernames} className="text-sm bg-blue-500 text-white px-2 py-1 rounded">Copy {selectedUsers.length}</button>
                                <button onClick={()=>exportSelected('csv')} className="text-sm bg-green-500 text-white px-2 py-1 rounded">CSV</button>
                                <button onClick={bulkUnfollow} className="text-sm bg-red-500 text-white px-2 py-1 rounded">Unfollow</button>
                            </div>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="bg-gray-100 dark:bg-gray-700"><tr><th className="p-2"><input type="checkbox" checked={selectedUsers.length===filtered.length && filtered.length>0} onChange={toggleSelectAll} /></th><th>Profile</th><th>Username</th><th>Full name</th><th>V</th><th>P</th><th>Action</th></tr></thead>
                                <tbody>
                                    {filtered.map(u=>(
                                        <tr key={u.pk} className="border-t dark:border-gray-700">
                                            <td className="p-2 text-center"><input type="checkbox" checked={selectedUsers.includes(u.username)} onChange={()=>toggleSelect(u.username)} /></td>
                                            <td className="p-1"><img src={u.profile_pic_url} className="w-8 h-8 rounded-full object-cover" /></td>
                                            <td className="p-1 font-medium">@{u.username}</td>
                                            <td className="p-1 truncate max-w-[120px]">{u.full_name}</td>
                                            <td className="p-1 text-center">{u.is_verified ? '✓' : ''}</td>
                                            <td className="p-1 text-center">{u.is_private ? '🔒' : '🌐'}</td>
                                            <td className="p-1"><button onClick={()=>openInstagramProfile(u.username)} className="bg-red-500 text-white px-3 py-1 rounded text-xs hover:bg-red-600">Unfollow</button></td>
                                        </tr>
                                    ))}
                                    {filtered.length===0 && <tr><td colSpan="7" className="p-4 text-center text-gray-500">No non-followers match filters</td></tr>}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
                        <h3 className="font-bold mb-3">Activity Log</h3>
                        <div className="bg-gray-100 dark:bg-gray-900 p-2 rounded h-80 overflow-y-auto text-xs font-mono">
                            {activityLogs.length===0 && <div className="text-gray-500">No activity yet...</div>}
                            {activityLogs.map((log,i)=><div key={i} className="border-b border-gray-300 dark:border-gray-700 py-1">{log}</div>)}
                        </div>
                        <div className="mt-4 flex flex-col gap-2">
                            <button onClick={fetchComparison} className="w-full bg-purple-500 text-white py-2 rounded hover:bg-purple-600">⟳ Refresh Data</button>
                            <div className="flex gap-2">
                                <a href={api.exportCSV(username)} className="flex-1 text-center bg-green-500 text-white py-2 rounded hover:bg-green-600">📎 CSV All</a>
                                <a href={api.exportJSON(username)} className="flex-1 text-center bg-blue-500 text-white py-2 rounded hover:bg-blue-600">📄 JSON All</a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

const App = () => {
    const [username, setUsername] = useState(localStorage.getItem('ig_username'));
    const handleLogin = (user) => { localStorage.setItem('ig_username', user); setUsername(user); };
    const handleLogout = () => { localStorage.removeItem('ig_username'); setUsername(null); };
    return (
        <ToastProvider>
            {username ? <Dashboard username={username} onLogout={handleLogout} /> : <LoginForm onLoginSuccess={handleLogin} />}
        </ToastProvider>
    );
};

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_TEMPLATE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
