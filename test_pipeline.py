"""
Local validation test for roblox-auto-shorts pipeline.
Run: python3 test_pipeline.py
"""
import os, sys, subprocess, asyncio

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
results = {}

def check(name, ok, detail=""):
    status = PASS if ok else FAIL
    print(f"{status} {name}" + (f" — {detail}" if detail else ""))
    results[name] = ok

# --- 1. Imports ---
print("\n=== Stage 1: Import Check ===")
for mod in ["requests", "groq", "edge_tts"]:
    try:
        __import__(mod); check(mod, True)
    except Exception as e: check(mod, False, str(e))

try:
    from PIL import Image; check("Pillow", True, Image.__version__)
except Exception as e: check("Pillow", False, str(e))

try:
    from google.oauth2.credentials import Credentials; check("google-auth", True)
except Exception as e: check("google-auth", False, str(e))

try:
    from googleapiclient.discovery import build; check("google-api-python-client", True)
except Exception as e: check("google-api-python-client", False, str(e))

try:
    import moviepy; check("moviepy removed", False, "still importable!")
except ImportError: check("moviepy removed", True, "correctly not installed")

# --- 2. FFmpeg ---
print("\n=== Stage 2: FFmpeg Check ===")
for tool in ["ffmpeg", "ffprobe"]:
    r = subprocess.run([tool, "-version"], capture_output=True, text=True)
    ok = r.returncode == 0
    check(tool, ok, r.stdout.split("\n")[0] if ok else r.stderr[:60])

r = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True)
check("ffmpeg subtitles filter (libass)", "subtitles" in r.stdout)

# --- 3. ASS field count ---
print("\n=== Stage 3: ASS Subtitle Format (Portrait & Landscape) ===")
def fmt_time(s):
    h=int(s//3600); m=int((s%3600)//60); sec=int(s%60); cs=int(round((s%1)*100))
    if cs==100: cs=0; sec+=1
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

chunks=["Luffy fights","the sea beast","at the ocean"]
total_w=sum(len(c.split()) for c in chunks)
current=0.0; events=[]
for chunk in chunks:
    wc=len(chunk.split()); dur=(wc/total_w)*10.0; end=current+dur
    ktext=" ".join(f"{{\\kf50}}{w}" for w in chunk.split())
    line=f"Dialogue: 0,{fmt_time(current)},{fmt_time(end)},RobloxStyle,,0,0,0,,{ktext}"
    events.append(line); current=end

all10=all(len(e.replace("Dialogue: ","").split(",",9))==10 for e in events)
check("Dialogue line has exactly 10 fields", all10, f"{len(events)} lines")
in_field10=all(e.replace("Dialogue: ","").split(",",9)[9].startswith("{") for e in events)
check("Text in field 10 (not Effect)", in_field10)

# --- 4. Full render dry run (9:16 Portrait & 16:9 Landscape) ---
print("\n=== Stage 4: Full Render Dry Run ===")
try:
    import tempfile
    tmp_dir = tempfile.gettempdir()
    test_img = os.path.join(tmp_dir, "test_scene_0.jpg")
    try:
        from PIL import Image as PILImage
        PILImage.new("RGB", (1920, 1080), (20, 20, 80)).save(test_img)
    except Exception:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1080", "-frames:v", "1", test_img],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    check("test image created", os.path.exists(test_img))

    test_audio = os.path.join(tmp_dir, "test_vo.mp3")
    print(f"{INFO} Generating TTS (takes a few seconds)...")
    async def gen():
        import edge_tts
        c = edge_tts.Communicate("Luffy fights the beast.", "en-US-ChristopherNeural")
        await c.save(test_audio)
    asyncio.run(gen())
    check("edge_tts audio generated", os.path.exists(test_audio))

    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", test_audio], capture_output=True, text=True)
    dur = float(r.stdout.strip()); check("audio duration", dur > 0, f"{dur:.2f}s")

    test_ass_ls = os.path.abspath(os.path.join(tmp_dir, "test_subs_ls.ass"))
    with open(test_ass_ls, "w") as f:
        f.write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: RobloxStyle,Impact,56,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,1,0,0,0,100,100,2,0,1,6,3,2,60,60,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:{int(dur):02d}.00,RobloxStyle,,0,0,0,,{{\\kf200}}Luffy {{\\kf200}}fights
""")
    check("Landscape 16:9 ASS file written", os.path.exists(test_ass_ls))

    frames = max(1, int(dur * 30)); d_str = f"{dur:.4f}"
    zp_ls = f"zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=30"
    vf_chain_ls = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,{zp_ls},fade=t=in:st=0:d=0.3"
    scene_out_ls = os.path.join(tmp_dir, "test_kb_ls.mp4")
    print(f"{INFO} Landscape Ken Burns render...")
    sr_ls = subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", test_img, "-vf", vf_chain_ls,
        "-t", d_str, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-r", "30", scene_out_ls], capture_output=True, text=True)
    if sr_ls.returncode != 0: print(sr_ls.stderr[-800:])
    check("Landscape 16:9 Ken Burns render", sr_ls.returncode == 0)

    mixed_ls = os.path.join(tmp_dir, "test_mixed_ls.mp4")
    mr_ls = subprocess.run(["ffmpeg", "-y", "-i", scene_out_ls, "-i", test_audio,
        "-c:v", "copy", "-c:a", "aac", "-shortest", mixed_ls], capture_output=True, text=True)
    check("audio mix landscape", mr_ls.returncode == 0)

    final_ls = os.path.join(tmp_dir, "test_final_ls.mp4")
    print(f"{INFO} Burning landscape subtitles...")
    esc_ass_ls = test_ass_ls.replace("\\", "/").replace(":", "\\:")
    subr_ls = subprocess.run(["ffmpeg", "-y", "-i", mixed_ls,
        "-vf", f"subtitles='{esc_ass_ls}'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "copy", final_ls], capture_output=True, text=True)
    if subr_ls.returncode != 0: print(subr_ls.stderr[-2000:])
    check("Landscape 16:9 subtitle burn (libass)", subr_ls.returncode == 0)
    if os.path.exists(final_ls):
        sz = os.path.getsize(final_ls)
        check("Landscape video > 30KB", sz > 30000, f"{sz//1024}KB")
        print(f"{INFO} Final Landscape video: {final_ls}")

except Exception as e:
    check("render dry run", False, str(e))
    import traceback; traceback.print_exc()

# --- Summary ---
print("\n"+"="*45)
passed=sum(1 for v in results.values() if v); total=len(results)
print(f"  {passed}/{total} checks passed")
if passed==total:
    print("  \033[92mAll tests PASSED — pipeline ready!\033[0m")
else:
    print(f"  \033[91m{total-passed} FAILED:\033[0m")
    for k,v in results.items():
        if not v: print(f"    ✗ {k}")
print("="*45)
