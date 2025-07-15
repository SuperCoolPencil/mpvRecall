import os
import json
import subprocess
import streamlit as st
import re
import datetime

# Path to store last-played information
CACHE_PATH = os.path.expanduser("~/.cache/mpv_recall_last.json")

# --- Core Functions ---

import os
import datetime
import subprocess

def get_file_metadata(path):
    size = os.path.getsize(path)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    # use ffprobe to get duration in seconds
    cmd = [
        "ffprobe","-v","error",
        "-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",
        path
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        duration = float(out.strip())
    except Exception:
        duration = 0
    return {
        "size_str": f"{size/1024**3:.2f} GB" if size>1024**2 else f"{size/1024:.2f} MB",
        "duration_str": str(datetime.timedelta(seconds=int(duration))),
        "modified_str": mtime.strftime("%Y‑%m‑%d %H:%M")
    }


def load_last():
    """Loads the last played media information from the cache file."""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_last(info):
    """Saves media information to the cache file."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(info, f, indent=2)

def play(path_to_play, start_pos=None, playlist_start_index=None, resume_specific_file=None):
    """
    Plays media with mpv, blocking until it exits.
    Can specify a start time and a playlist start index.
    If resume_specific_file is provided, only applies start position to that specific file.
    Returns the last played file path and its position.
    """
    cmd = [
        "mpv",
        "--force-window",
        "--term-status-msg=[mpvRecall]PATH:${path}#POS:${playback-time}"
    ]
    
    # If we're resuming a specific file in a folder playlist
    if resume_specific_file and playlist_start_index is not None and os.path.isdir(path_to_play):
        # Start at the specific file in the playlist
        cmd.append(f"--playlist-start={playlist_start_index}")
        
        # Create a simple Lua script that seeks only on the first file load
        script_content = f'''
local sought = false
local target_time = {start_pos}

function on_file_loaded()
    if not sought then
        sought = true
        mp.commandv("seek", target_time, "absolute")
    end
end

mp.register_event("file-loaded", on_file_loaded)
'''
        
        # Create temporary script file
        script_path = "/tmp/mpv_resume_script.lua"
        with open(script_path, 'w') as f:
            f.write(script_content)
        cmd.append(f"--script={script_path}")
    else:
        # Standard behavior for single files or new playback
        if start_pos:
            cmd.append(f"--start={start_pos}")
        if playlist_start_index is not None:
            cmd.append(f"--playlist-start={playlist_start_index}")

    cmd.append(path_to_play)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        st.error("Error: `mpv` command not found. Please ensure mpv is installed and in your PATH.")
        return None
    finally:
        # Clean up temporary script file
        if resume_specific_file and os.path.exists("/tmp/mpv_resume_script.lua"):
            os.remove("/tmp/mpv_resume_script.lua")

    if proc.stdout or proc.stderr:
        with st.expander("Show raw mpv output (for debugging)"):
            st.code(f"--- STDOUT ---\n{proc.stdout}\n\n--- STDERR ---\n{proc.stderr}")

    last_status_line = ""
    all_lines = proc.stdout.strip().replace('\r', '\n').split('\n')
    
    for line in all_lines:
        if line.startswith("[mpvRecall]"):
            last_status_line = line
            
    if not last_status_line:
        return None

    match = re.search(r"PATH:(.*?)#POS:(\d{1,2}:\d{2}:\d{2})", last_status_line)
    if match:
        file_path = match.group(1)
        time_str = match.group(2)
        try:
            parts = time_str.split(':')
            h, m, s = map(int, parts)
            position = float(h * 3600 + m * 60 + s)
            
            if position > 2:
                return {"path": file_path, "position": position}
        except (ValueError, IndexError):
            return None
    
    return None

def pick_file_or_folder(mode="file"):
    """Opens a native file dialog using Zenity."""
    cmd = ["zenity", "--file-selection"]
    if mode == "folder":
        cmd.append("--directory")
    
    try:
        out = subprocess.check_output(cmd)
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        if "FileNotFoundError":
            st.error("`zenity` is not installed. Please run `sudo apt install zenity` (or equivalent).")
        return None

def get_media_files(folder):
    """Gets a sorted list of all media files in a given folder (non-recursive)."""
    try:
        return sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
        ])
    except Exception:
        return []

# --- Streamlit UI ---

st.set_page_config(
    page_title="mpvRecall", 
    layout="centered",
    page_icon="🎬",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
<style>
.main-header {
    text-align: center;
    padding: 1rem 0;
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-size: 2.5rem;
    font-weight: 800;
    margin-bottom: 0.5rem;
}

.subtitle {
    text-align: center;
    color: #666;
    font-size: 1.1rem;
    margin-bottom: 2rem;
}

.session-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 1.5rem;
    border-radius: 1rem;
    margin: 1rem 0;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}

.session-card h3 {
    color: white;
    margin-bottom: 0.5rem;
    font-size: 1.2rem;
}

.session-info {
    background: rgba(255,255,255,0.1);
    padding: 1rem;
    border-radius: 0.5rem;
    margin: 0.5rem 0;
}

.selection-card {
    background: linear-gradient(135deg, #5a4dae 0%, #52377f 100%);
    color: #fff;  
    padding: 1.5rem;
    border-radius: 1rem;
    margin: 1rem 0;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

.stButton > button {
    border-radius: 0.5rem;
    border: none;
    font-weight: 600;
    transition: all 0.3s ease;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
}
</style>
""", unsafe_allow_html=True)

# Main header
st.markdown('<h1 class="main-header">mpvRecall</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">🎬 Resume your media exactly where you left off</p>', unsafe_allow_html=True)

if 'selected_path' not in st.session_state:
    st.session_state['selected_path'] = None

# --- Section: Resume Last Played ---
st.markdown("### 🔄 Resume Last Session")

last_played_info = load_last()
if last_played_info and 'last_played_file' in last_played_info:
    # Display information about the last session
    last_file = last_played_info['last_played_file']
    last_pos_sec = last_played_info.get('last_played_position', 0)
    last_pos_hms = str(datetime.timedelta(seconds=int(last_pos_sec)))
    original_path = last_played_info.get('path')

    st.markdown(f"""
    <div class="session-card">
        <h3>📺 Last Watched</h3>
        <div class="session-info">
            <strong>File:</strong> {os.path.basename(last_file)}<br>
            <strong>Position:</strong> {last_pos_hms}<br>
            <strong>Location:</strong> {original_path}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("▶️ Resume Last Session", use_container_width=True, type="primary"):
        if not os.path.exists(original_path):
            st.error("⚠️ Original file or folder not found. It may have been moved or deleted.")
        else:
            # --- MODIFIED RESUME LOGIC ---
            is_folder_session = last_played_info.get('is_folder', False)
            path_to_play = original_path
            playlist_start_idx = None
            resume_file = None

            if is_folder_session:
                with st.spinner("🎬 Resuming folder playlist..."):
                    st.info("The app will wait until mpv closes.")
                # For a folder, find the index of the specific file to start on
                media_files = get_media_files(original_path)
                if last_file in media_files:
                    # Python's .index() is 0-based, which matches mpv's --playlist-start
                    playlist_start_idx = media_files.index(last_file)
                    resume_file = last_file
            else:
                with st.spinner("🎬 Resuming file..."):
                    st.info("The app will wait until mpv closes.")
            
            exit_info = play(
                path_to_play=original_path,  # Always pass the original path
                start_pos=last_pos_sec, 
                playlist_start_index=playlist_start_idx,
                resume_specific_file=resume_file
            )
            
            if exit_info:
                # Update cache with the new exit information
                last_played_info['last_played_file'] = exit_info['path']
                last_played_info['last_played_position'] = exit_info['position']
                save_last(last_played_info)
                st.success("✅ Playback stopped. New position saved!")
                st.rerun()
            else:
                st.warning("⚠️ Playback finished or no position was saved.")

else:
    st.info("💡 No previous playback data found. Play something new to begin!")

st.markdown("---")

# --- Section: Play New Media ---
st.markdown("### 🎵 Play New Media")

col1, col2 = st.columns(2)
with col1:
    if st.button("📄 Select File", use_container_width=True):
        selection = pick_file_or_folder("file")
        if selection and os.path.isfile(selection):
            st.session_state['selected_path'] = selection

with col2:
    if st.button("📁 Select Folder", use_container_width=True):
        selection = pick_file_or_folder("folder")
        if selection and os.path.isdir(selection):
            st.session_state['selected_path'] = selection

if st.session_state['selected_path']:
    path = st.session_state['selected_path']
    is_folder = os.path.isdir(path)
    
    icon = "📁" if is_folder else "📄"
    st.markdown(f"""
    <div class="selection-card">
    <h3>{icon} Selected Media</h3>
    <div class="session-info">
        {path}<br>
    </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("▶️ Play Selection", type="primary", use_container_width=True):
        if is_folder and not get_media_files(path):
            st.error("⚠️ No media files found in the selected folder.")
        else:
            with st.spinner("🎬 Starting mpv..."):
                st.info("The app will wait until you close mpv.")
                exit_info = play(path)

            if exit_info:
                info_to_save = {
                    "path": path,
                    "is_folder": is_folder,
                    "last_played_file": exit_info['path'],
                    "last_played_position": exit_info['position']
                }
                save_last(info_to_save)
                st.success(f"✅ Playback stopped. Position saved for {os.path.basename(exit_info['path'])}.")
                st.session_state['selected_path'] = None
                st.rerun()
            else:
                st.warning("⚠️ Playback finished or no position was saved.")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666; font-size: 0.9rem;'>"
    "Made with ❤️ • Powered by mpv & Streamlit"
    "</div>", 
    unsafe_allow_html=True
)