import os
import json
import subprocess
import streamlit as st
import re
import datetime

# Path to store last-played information
CACHE_PATH = os.path.expanduser("~/.cache/mpv_recall_sessions.json") # Changed cache file name

# --- Core Functions ---

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

def load_all_sessions():
    """Loads all saved media session information from the cache file."""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_session_data(sessions):
    """Saves the entire sessions dictionary to the cache file."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(sessions, f, indent=2)

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
local target_time = {max(start_pos-5,0)}

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
            
            if position > 2: # Save only if position is significant (more than 2 seconds)
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
    media_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mp3', '.wav', '.ogg') # Add more as needed
    try:
        return sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(media_extensions)
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
    color: white; /* Ensure text is visible on the gradient background */
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
    word-wrap: break-word; /* Ensure long paths wrap */
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

# --- Section: Resume Saved Sessions ---
st.markdown("### 🔄 Saved Sessions")

all_sessions = load_all_sessions()

if all_sessions:
    # Sort sessions by last played timestamp, newest first
    sorted_sessions = sorted(
        all_sessions.items(), 
        key=lambda item: item[1].get('last_played_timestamp', ''), 
        reverse=True
    )

    for original_path, session_data in sorted_sessions:
        last_file = session_data['last_played_file']
        last_pos_sec = session_data.get('last_played_position', 0)
        last_pos_hms = str(datetime.timedelta(seconds=int(last_pos_sec)))
        is_folder_session = session_data.get('is_folder', False)
        session_type = "Folder" if is_folder_session else "File"
        last_played_ts = session_data.get('last_played_timestamp')
        
        st.markdown(f"""
        <div class="session-card">
            <h3>{os.path.basename(last_file)}</h3>
            <div class="session-info">
                <strong>Playing {session_type}:</strong> {os.path.basename(original_path)}<br>
                <strong>Position:</strong> {last_pos_hms}<br>
                <strong>Last Played:</strong> {last_played_ts if last_played_ts else 'N/A'}<br>
                <strong>Path:</strong> {original_path}
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_resume, col_delete = st.columns([0.7, 0.3])
        with col_resume:
            if st.button(f"▶️ Resume {os.path.basename(original_path)}", key=f"resume_{original_path}", use_container_width=True, type="primary"):
                if not os.path.exists(original_path):
                    st.error("⚠️ Original file or folder not found. It may have been moved or deleted.")
                    # Optionally remove the stale entry
                    del all_sessions[original_path]
                    save_session_data(all_sessions)
                    st.rerun()
                else:
                    with st.spinner("🎬 Resuming playback..."):
                        st.info("The app will wait until mpv closes.")
                    
                    path_to_play = original_path
                    playlist_start_idx = None
                    resume_file = None

                    if is_folder_session:
                        media_files = get_media_files(original_path)
                        if last_file in media_files:
                            playlist_start_idx = media_files.index(last_file)
                            resume_file = last_file
                        else:
                            st.warning(f"File '{os.path.basename(last_file)}' not found in folder '{os.path.basename(original_path)}'. Starting folder from beginning.")
                            last_pos_sec = 0 # Reset position if file not found
                            playlist_start_idx = 0

                    exit_info = play(
                        path_to_play=original_path,
                        start_pos=last_pos_sec,
                        playlist_start_index=playlist_start_idx,
                        resume_specific_file=resume_file
                    )
                    
                    if exit_info:
                        # Update specific session with new info
                        all_sessions[original_path]['last_played_file'] = exit_info['path']
                        all_sessions[original_path]['last_played_position'] = exit_info['position']
                        all_sessions[original_path]['last_played_timestamp'] = datetime.datetime.now().isoformat()
                        save_session_data(all_sessions)
                        st.success("✅ Playback stopped. New position saved!")
                        st.rerun()
                    else:
                        st.warning("⚠️ Playback finished or no position was saved.")
        with col_delete:
            if st.button("🗑️ Delete", key=f"delete_{original_path}", use_container_width=True):
                if original_path in all_sessions:
                    del all_sessions[original_path]
                    save_session_data(all_sessions)
                    st.success(f"🗑️ Session for {os.path.basename(original_path)} deleted.")
                    st.rerun()
        st.markdown("---") # Separator for each session
else:
    st.info("💡 No saved playback sessions found. Play something new to begin!")

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
                all_sessions = load_all_sessions() # Reload to get latest state
                info_to_save = {
                    "path": path, # Store the original selection path as the key
                    "is_folder": is_folder,
                    "last_played_file": exit_info['path'],
                    "last_played_position": exit_info['position'],
                    "last_played_timestamp": datetime.datetime.now().isoformat()
                }
                all_sessions[path] = info_to_save # Use path as the key
                save_session_data(all_sessions)
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