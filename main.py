import os
import random
import asyncio
import edge_tts
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Connect to YouTube API using secrets
def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"]
    )
    return build("youtube", "v3", credentials=creds)

# 2. Generate Voiceover
async def generate_audio(text, output_file="audio.mp3"):
    tts = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await tts.save(output_file)

# 3. Upload Short
def upload_short(video_path, title, description):
    youtube = get_youtube_client()
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["Roblox", "RobloxShorts", "Gaming", "Shorts"],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"Successfully posted to YouTube! Video ID: {response.get('id')}")

if __name__ == "__main__":
    titles = [
        "Secret Vault in Brookhaven Roblox! 🤫 #Shorts #Roblox",
        "Top Blox Fruits Hack You Didn't Know! 🍎 #Shorts #Roblox",
        "How to Survive Doors Room 50 Easily! 🚪 #Shorts #Roblox"
    ]
    chosen_title = random.choice(titles)
    
    # Generate speech audio
    asyncio.run(generate_audio("Check out this crazy secret trick in Roblox! Subscribe for more!"))
    
    # Upload video
    upload_short("video.mp4", chosen_title, "Automated Roblox Shorts! #Roblox #Gaming")
