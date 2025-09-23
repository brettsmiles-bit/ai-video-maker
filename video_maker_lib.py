import os
import json
import time
import requests
import configparser
import google.generativeai as genai
from elevenlabs.client import ElevenLabs
from moviepy.editor import *

# --- 1. SCRIPT BREAKDOWN ---

def generate_scene_breakdown(script_content, api_key):
    """Sends the script to the Google Gemini API to be broken down into scenes."""
    
    # Configure the Gemini client
    genai.configure(api_key=api_key)
    
    # This system prompt is slightly modified for Gemini
    system_prompt = """
    You are an expert video director. Your task is to read a video script and break it down into a shot list.
    The entire output must be a single, valid JSON object with one key: "scenes".
    The "scenes" key must contain a list of objects.
    Each scene object must contain four keys:
    1. 'scene_number': An integer for the scene order.
    2. 'narration_text': The exact text to be spoken for the scene (1-3 sentences).
    3. 'visual_prompt': A descriptive prompt for an AI visual generator OR a search query for stock footage.
    4. 'visual_type': A string that is "video", "image", or "stock_footage". Choose "stock_footage" for realistic, generic scenes, "image" for static concepts, and "video" for specific actions.
    """
    
    config = configparser.ConfigParser()
    config.read('config.ini')
    model_name = config['SETTINGS']['LLM_MODEL']
    
    # Set up the model with JSON output configuration
    model = genai.GenerativeModel(
        model_name,
        generation_config={"response_mime_type": "application/json"}
    )

    try:
        # Combine the system prompt and the user's script for the API call
        full_prompt = f"{system_prompt}\n\nHere is the script:\n\n{script_content}"
        
        response = model.generate_content(full_prompt)
        
        # The Gemini response object is simpler to parse
        return json.loads(response.text)
        
    except Exception as e:
        print(f"Error breaking down script with Gemini: {e}")
        return None

# --- 2. ASSET GENERATION ---

def generate_audio(scene_data, api_key, voice_id):
    """Generates audio using ElevenLabs."""
    scene_num = scene_data['scene_number']
    output_path = f"audio_clips/scene_{scene_num}.mp3"
    if os.path.exists(output_path): return
    
    client = ElevenLabs(api_key=api_key)
    try:
        audio_stream = client.generate(text=scene_data['narration_text'], voice=voice_id)
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
    except Exception as e:
        print(f"Error generating audio for Scene {scene_num}: {e}")


def generate_image(scene_data, api_key):
    """Generates an image using Stability AI."""
    scene_num = scene_data['scene_number']
    output_path = f"visual_assets/scene_{scene_num}.png"
    if os.path.exists(output_path): return

    try:
        response = requests.post(
            "https://api.stability.ai/v2beta/stable-image/generate/sd3",
            headers={"authorization": f"Bearer {api_key}", "accept": "image/*"},
            files={'prompt': (None, scene_data['visual_prompt']), 'aspect_ratio': (None, '16:9')}
        )
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
    except Exception as e:
        print(f"Error generating image for Scene {scene_num}: {e}")

def download_stock_video(scene_data, api_key):
    """Downloads a stock video from Pexels."""
    scene_num = scene_data['scene_number']
    output_path = f"visual_assets/scene_{scene_num}.mp4"
    if os.path.exists(output_path): return

    try:
        headers = {"Authorization": api_key}
        url = f"https://api.pexels.com/videos/search?query={scene_data['visual_prompt']}&orientation=landscape&per_page=1"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        results = response.json()
        if not results['videos']: return

        video_url = results['videos'][0]['video_files'][0]['link']
        video_response = requests.get(video_url)
        video_response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(video_response.content)
    except Exception as e:
        print(f"Error downloading stock video for Scene {scene_num}: {e}")

def generate_video(scene_data, api_key):
    """Generates a video using Stability AI (asynchronous)."""
    scene_num = scene_data['scene_number']
    output_path = f"visual_assets/scene_{scene_num}.mp4"
    if os.path.exists(output_path): return

    try:
        response = requests.post(
            "https://api.stability.ai/v2beta/generation/generate-video",
            headers={"authorization": f"Bearer {api_key}"},
            files={'text_prompt': (None, scene_data['visual_prompt']), 'aspect_ratio': (None, '16:9')}
        )
        response.raise_for_status()
        generation_id = response.json()['id']
        
        while True:
            time.sleep(20)
            result_response = requests.get(
                f"https://api.stability.ai/v2beta/generation/video-result/{generation_id}",
                headers={"authorization": f"Bearer {api_key}", "Accept": "video/mp4"}
            )
            if result_response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(result_response.content)
                break
            elif result_response.status_code != 202:
                result_response.raise_for_status()
    except Exception as e:
        print(f"Error generating video for Scene {scene_num}: {e}")

# --- 3. VIDEO ASSEMBLY ---

def create_animated_image_clip(image_path, audio_duration):
    """Creates a Ken Burns effect clip from an image."""
    img_clip = ImageClip(image_path).set_duration(audio_duration)
    zoomed_clip = img_clip.fx(vfx.resize, lambda t: 1 + 0.1 * (t / audio_duration))
    w, h = img_clip.size
    return zoomed_clip.crop(width=w, height=h, x_center=zoomed_clip.w/2, y_center=zoomed_clip.h/2)

def assemble_video(shot_list, output_file="final_video.mp4"):
    """Assembles the final video with transitions, text, and music."""
    config = configparser.ConfigParser()
    config.read('config.ini')
    TRANSITION_DURATION = float(config['SETTINGS']['TRANSITION_DURATION_SECONDS'])
    MUSIC_FILE = config['SETTINGS']['BACKGROUND_MUSIC_FILE']
    MUSIC_VOLUME = float(config['SETTINGS']['MUSIC_VOLUME'])

    scene_clips = []
    for scene in sorted(shot_list, key=lambda x: x['scene_number']):
        scene_num = scene['scene_number']
        audio_path = f"audio_clips/scene_{scene_num}.mp3"
        video_path = f"visual_assets/scene_{scene_num}.mp4"
        image_path = f"visual_assets/scene_{scene_num}.png"

        if not os.path.exists(audio_path): continue
        audio_clip = AudioFileClip(audio_path)
        
        visual_clip = None
        if os.path.exists(video_path):
            visual_clip = VideoFileClip(video_path)
        elif os.path.exists(image_path):
            visual_clip = create_animated_image_clip(image_path, audio_clip.duration)
        if visual_clip is None: continue

        visual_clip = visual_clip.set_duration(audio_clip.duration).set_audio(audio_clip)

        text_clip = TextClip(
            scene['narration_text'], fontsize=30, color='white', font='Arial-Bold',
            bg_color='rgba(0,0,0,0.6)', size=(visual_clip.w * 0.8, None), method='caption'
        ).set_position(('center', 'bottom')).set_duration(visual_clip.duration).margin(bottom=20, opacity=0)
        
        scene_clips.append(CompositeVideoClip([visual_clip, text_clip]))

    if not scene_clips: return

    final_clips_with_transitions = [scene_clips[0]]
    for i in range(len(scene_clips) - 1):
        next_clip_faded = scene_clips[i+1].fx(vfx.fadein, TRANSITION_DURATION)
        final_clips_with_transitions.append(next_clip_faded.set_start(final_clips_with_transitions[-1].end - TRANSITION_DURATION))
    
    video_with_transitions = CompositeVideoClip(final_clips_with_transitions)

    if os.path.exists(MUSIC_FILE):
        music = AudioFileClip(MUSIC_FILE).fx(afx.audio_loop, duration=video_with_transitions.duration).volumex(MUSIC_VOLUME)
        final_audio = CompositeAudioClip([video_with_transitions.audio, music])
        video_with_transitions.audio = final_audio

    video_with_transitions.write_videofile(output_file, codec='libx264', audio_codec='aac', threads=4, fps=24)