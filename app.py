import streamlit as st
import configparser
import os
import pandas as pd
import concurrent.futures
from video_maker_lib import *

# --- App Setup ---
st.set_page_config(layout="wide", page_title="AI Video Maker")
st.title("🎬 AI Text-to-Video Maker")

# Create asset directories if they don't exist
os.makedirs("audio_clips", exist_ok=True)
os.makedirs("visual_assets", exist_ok=True)

# --- Session State Initialization ---
if 'shot_list_df' not in st.session_state:
    st.session_state.shot_list_df = pd.DataFrame()

# --- UI: Sidebar for Configuration ---
with st.sidebar:
    st.header("🔑 API Configuration")
    config = configparser.ConfigParser()
    config.read('config.ini')
    
     google_key = st.text_input("Google AI API Key", value=config['API_KEYS']['GOOGLE_API_KEY'], type="password")
    stability_key = st.text_input("Stability AI API Key", value=config['API_KEYS']['STABILITY_API_KEY'], type="password")
    elevenlabs_key = st.text_input("ElevenLabs API Key", value=config['API_KEYS']['ELEVENLABS_API_KEY'], type="password")
    pexels_key = st.text_input("Pexels API Key", value=config['API_KEYS']['PEXELS_API_KEY'], type="password")

    st.header("⚙️ Video Settings")
    voice_id = st.text_input("ElevenLabs Voice ID", value=config['SETTINGS']['ELEVENLABS_VOICE_ID'])

# --- UI: Main Page ---

# Step 1: Script Input
st.header("1. Input Your Script")
uploaded_file = st.file_uploader("Upload a .txt script file", type="txt")
script_text = ""
if uploaded_file:
    script_text = uploaded_file.read().decode("utf-8")
    st.text_area("Script Content", script_text, height=200)

if st.button("Generate Shot List 📝", disabled=(not script_text)):
    with st.spinner("Calling LLM to create a shot list..."):
        shot_list_data = generate_scene_breakdown(script_text, google_key)
        
        scenes_list = []
        # NEW: Check if the AI returned a dictionary (correct) or just a list (common mistake)
        if isinstance(shot_list_data, dict) and "scenes" in shot_list_data:
            scenes_list = shot_list_data["scenes"]
        elif isinstance(shot_list_data, list):
            scenes_list = shot_list_data # Use the list directly
        
        if scenes_list:
            st.session_state.shot_list_df = pd.DataFrame(scenes_list)
            st.success(f"Generated shot list with {len(st.session_state.shot_list_df)} scenes.")
        else:
            st.error("Failed to generate a valid shot list. The AI response was not in the expected format.")

# Step 2: Shot List Editor
if not st.session_state.shot_list_df.empty:
    st.header("2. Review and Edit Shot List")
    st.session_state.shot_list_df = st.data_editor(
        st.session_state.shot_list_df,
        column_config={"visual_type": st.column_config.SelectboxColumn("Type", options=["video", "image", "stock_footage"])},
        use_container_width=True, num_rows="dynamic"
    )

    st.header("3. Generate Video")
    if st.button("Generate Assets & Assemble Video 🚀"):
        edited_shot_list = st.session_state.shot_list_df.to_dict('records')
        total_scenes = len(edited_shot_list)

        # Asset Generation
        with st.status("Generating assets in parallel...", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_tasks = []
                for scene in edited_shot_list:
                    future_tasks.append(executor.submit(generate_audio, scene, elevenlabs_key, voice_id))
                    visual_type = scene.get('visual_type')
                    if visual_type == 'image':
                        future_tasks.append(executor.submit(generate_image, scene, stability_key))
                    elif visual_type == 'stock_footage':
                        future_tasks.append(executor.submit(download_stock_video, scene, pexels_key))
                    else:
                        future_tasks.append(executor.submit(generate_video, scene, stability_key))

                progress_bar = st.progress(0)
                for i, future in enumerate(concurrent.futures.as_completed(future_tasks)):
                    progress_bar.progress((i + 1) / len(future_tasks), text=f"Generated {i+1}/{len(future_tasks)} assets...")
            status.update(label="Asset generation complete!", state="complete")

        # Video Assembly
        with st.spinner("Assembling final video... This may take a while."):
            final_video_path = "final_video_output.mp4"
            assemble_video(edited_shot_list, final_video_path)
        
        st.success("🎉 Video generation complete!")
        with open(final_video_path, 'rb') as video_file:
            video_bytes = video_file.read()
            st.video(video_bytes)
            st.download_button("Download Video", data=video_bytes, file_name=final_video_path, mime="video/mp4")
        