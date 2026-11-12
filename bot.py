import os, sys, json, time, asyncio, hashlib, pathlib, tempfile, textwrap, datetime
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

W, H = 1080, 1920
FONT = os.getenv("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
VOICE = os.getenv("TTS_VOICE", "de-DE-ConradNeural")
HANDLE = os.getenv("HANDLE") or "@unikat_4u"
PALETTES = [((20, 20, 60), (120, 40, 160)), ((10, 40, 50), (20, 130, 120)),
            ((60, 15, 25), (200, 70, 60)), ((15, 25, 60), (40, 110, 220))]

def _frame(text, size, palette, path, label=None):
    top, bot = palette
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    font = ImageFont.truetype(FONT, size)
    wrapped = "\n".join(textwrap.wrap(text, width=int(1000 / (size * 0.58))))
    d.multiline_text((W / 2, H / 2), wrapped, font=font, fill="white", anchor="mm",
                     align="center", spacing=size * 0.3)
    small = ImageFont.truetype(FONT, 44)
    d.text((W / 2, 220), label or "KRASS GEWUSST", font=small, fill=(255, 255, 255, 200), anchor="mm")
    d.text((W / 2, H - 260), HANDLE, font=small, fill="white", anchor="mm")
    img.save(path)

async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE, rate="+8%").save(path)

def build_video(script, out_path):
    pal = PALETTES[int(hashlib.md5(script["topic"].encode()).hexdigest(), 16) % len(PALETTES)]
    scenes = [(script["hook"], 96)] + [(l, 74) for l in script["lines"]] + \
             [("Folge für mehr krasse Fakten!", 80)]
    tmp = pathlib.Path(tempfile.mkdtemp())
    clips = []
    for i, (text, size) in enumerate(scenes):
        img, aud = tmp / f"{i}.png", tmp / f"{i}.mp3"
        _frame(text, size, pal, img)
        asyncio.run(_tts(text, str(aud)))
        a = AudioFileClip(str(aud))
        clips.append(ImageClip(str(img)).with_duration(a.duration + 0.35).with_audio(a))
    concatenate_videoclips(clips, method="compose").write_videofile(
        str(out_path), fps=30, codec="libx264", audio_codec="aac", logger=None)

API = f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION', 'v27.0')}"

def wait_for_url(url, tries=30):
    for _ in range(tries):
        try:
            if requests.head(url, timeout=15, allow_redirects=True).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(10)
    raise RuntimeError(f"Video-URL nicht erreichbar: {url}")

def publish_reel(video_url, caption):
    uid, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    r = requests.post(f"{API}/{uid}/media", data={
        "media_type": "REELS", "video_url": video_url,
        "caption": caption, "access_token": token}, timeout=60)
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(40):
        s = requests.get(f"{API}/{cid}", params={"fields": "status_code", "access_token": token}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram-Verarbeitung fehlgeschlagen: {s}")
        time.sleep(8)
    p = requests.post(f"{API}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}, timeout=60)
    p.raise_for_status()
    print("Veröffentlicht:", p.json())

OUT = pathlib.Path("videos"); OUT.mkdir(exist_ok=True)
HIST = pathlib.Path("history.json")
LATEST = OUT / "latest.json"
SCRIPTS = json.loads(pathlib.Path("scripts.json").read_text(encoding="utf-8"))

def generate():
    hist = json.loads(HIST.read_text()) if HIST.exists() else []
    todo = [s for s in SCRIPTS if s["topic"] not in hist]
    if not todo:
        hist, todo = [], SCRIPTS
    script = todo[0]
    name = f"{datetime.date.today().isoformat()}.mp4"
    build_video(script, OUT / name)
    caption = script["caption"] + "\n\n" + " ".join(script["hashtags"])
    LATEST.write_text(json.dumps({"file": name, "caption": caption}, ensure_ascii=False))
    HIST.write_text(json.dumps(hist + [script["topic"]], ensure_ascii=False))
    for old in sorted(OUT.glob("*.mp4"))[:-3]:
        old.unlink()
    print("Thema:", script["topic"])

def publish():
    info = json.loads(LATEST.read_text(encoding="utf-8"))
    repo, ref = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_REF_NAME", "main")
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/videos/{info['file']}"
    wait_for_url(url)
    publish_reel(url, info["caption"])

if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1] if len(sys.argv) > 1 else "generate"]()
