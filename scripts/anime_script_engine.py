#!/usr/bin/env python3
"""
AI Anime Script Engine for Bhaloo Ji Anime Explanation Channel.
Generates gripping, cinematic 3-to-5 part episodic scripts (90-180s each)
plus unified long-form full episode explanation scripts.
Style: High-retention anime recap/explanation benchmarked against RecapKun (@recapkun).
"""

import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent

# Standardized Fair Use Disclaimer for Anime Recaps
FAIR_USE_DISCLAIMER = """---
Copyright Disclaimer Under Section 107 of the Copyright Act 1976:
Allowance is made for "fair use" for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. Fair use is a use permitted by copyright statute that might otherwise be infringing. Non-profit, educational or personal use tips the balance in favor of fair use.
All anime video clips and audio belong to their respective copyright holders (e.g. Ufotable, MAPPA, Shueisha, Aniplex). This video is an analytical, transformative recap and commentary.
Channel: Bhaloo Ji
---"""

# Pre-compiled knowledge base for Demon Slayer & JJK episodes for instant reliable offline fallback
EPISODE_KNOWLEDGE = {
    "demon-slayer-s01e01": {
        "title": "Cruelty (Cruelty to Compassion)",
        "summary": "Tanjiro Kamado returns home to find his family slaughtered by a demon, with his sister Nezuko turned into a demon. Water Hashira Giyu Tomioka attacks Nezuko, but Tanjiro defends her and Nezuko shields Tanjiro, convincing Giyu to spare her and guide them to Urokodaki.",
        "parts": [
            {
                "part": 1,
                "hook": "Imagine coming home after a cold night of selling charcoal and finding every single person you love slaughtered in the snow.",
                "narration": "High in the snowy mountain villages of Taisho-era Japan, Tanjiro Kamado was just a kind-hearted boy who sold charcoal to support his family. One evening, he stayed in town overnight because the roads were too dangerous. When he returns home the next morning, the scene he finds will haunt him for the rest of his life. The front door is hanging open. The smell of blood is overwhelming. Inside, his mother, his brothers, his sisters — all brutally slaughtered in pools of frozen blood. This is not a robbery. This is not an accident. This is the signature of a demon. But then he hears a sound. His sister Nezuko is still breathing, barely clinging to life. Relief floods through him as he lifts her and begins to sprint down the mountain to find help — but then something terrible happens. Nezuko's eyes snap open, glowing pink. Her nails extend into claws. Her body grows with supernatural strength. She turns her head, and she lunges straight for Tanjiro's throat with fangs like needles. His own sister has become a flesh-eating demon, and right as she is about to tear him apart — a figure in a haori slashes from the treeline with a blade of pure ice!",
                "cliffhanger": "Wait until you see who just arrived to execute Nezuko in Part 2!",
                "time_range": [180, 520],
                "short_title": "His Entire Family Was Slaughtered... 🩸 | Demon Slayer S1 Ep 1 Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "The deadliest Hashira in Japan showed absolutely zero mercy — but Tanjiro did something that changed everything!",
                "narration": "Water Hashira Giyu Tomioka is one of the most powerful demon slayers alive, and he didn't come here to talk. He swoops in with his blade already drawn, moving to decapitate Nezuko before she can harm another human. Tanjiro throws himself in front of the blow, screaming desperately: she still recognizes him, she is still his sister! But Giyu is unmoved. Compassion for demons is a fatal luxury. The weak have no rights in this world, and tears change nothing. Giyu kicks Tanjiro aside like he weighs nothing. But Tanjiro refuses to stay down. Every time he hits the ground, he drags himself back to his feet. His body is untrained, his strength is human, but his determination is something Giyu has genuinely never seen before. He charges again and again, taking hit after hit, refusing to beg but also refusing to quit. Then, in one desperate last gamble, Tanjiro flings his hand axe directly at Giyu's head — Giyu dodges by a hair — but that was just the distraction. Tanjiro dives low, catching Giyu in a surprise grapple from below. Giyu realizes with genuine shock: this ordinary boy just outsmarted him. And then Nezuko does something that stops every thought in Giyu's head cold.",
                "cliffhanger": "Did Tanjiro's secret counter actually work? See what Nezuko does in Part 3!",
                "time_range": [520, 860],
                "short_title": "Why Giyu Spared Nezuko's Life! 😱 | Demon Slayer S1 Ep 1 Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "Even after transforming into a bloodthirsty demon, Nezuko Kamado did something that no demon in history has ever done!",
                "narration": "Giyu Tomioka has hunted demons his entire life. He has seen them eat children, betray their own kind, and manipulate every emotion in pursuit of blood. He has never — not once in his career — seen a demon protect a human. But right now, with Tanjiro lying unconscious on the snow, Nezuko stands over her brother's body with her arms spread wide, growling with burning, protective defiance directly at one of the deadliest men alive. She will not move. She will not attack him. She just stands there, shielding her brother even though every demon instinct in her body must be screaming at her to feed. Giyu lowers his blade. He raises Tanjiro's hand, testing his grip unconsciously — it's the grip of someone who threw that axe on purpose, with perfect calculated timing. He has been underestimating this kid from the start. After a long silence, Giyu makes a decision that breaks every rule in the Demon Slayer Corps handbook. He gently but firmly knocks Nezuko unconscious, places a bamboo tube in her mouth as a muzzle, and wraps her onto Tanjiro's back. When Tanjiro wakes up, there is a letter in his hand: seek out Master Sakonji Urokodaki on Mount Sagiri. The journey of the Demon Slayer officially begins — and nothing in the world of anime will ever be the same again.",
                "cliffhanger": "Subscribe to Bhaloo Ji for Episode 2 — the brutal training arc begins!",
                "time_range": [860, 1260],
                "short_title": "The First Demon Who Protected A Human! 🛡️ | Demon Slayer S1 Ep 1 Part 3 #shorts",
            }
        ]
    },
    "jujutsu-kaisen-s01e01": {
        "title": "Ryomen Sukuna",
        "summary": "Yuji Itadori discovers a cursed talisman at his high school. When curses attack his friends, Yuji swallows Sukuna's finger to gain cursed energy, becoming the vessel for the King of Curses.",
        "parts": [
            {
                "part": 1,
                "hook": "He swallowed the deadliest ancient demon finger just to save his friends, and changed the anime world forever!",
                "narration": "Yuji Itadori was just an unnaturally athletic high schooler living a quiet life visiting his grandfather in the hospital. Before passing away, his grandfather gives him one final command: 'You are strong, so help others.' Little did Yuji know, his occult research club had just unsealed a special grade cursed object—a rotting, severed finger belonging to Ryomen Sukuna, the King of Curses! As darkness falls, bloodthirsty cursed spirits swarm the school, hunting down the students to feast on the finger's demonic power!",
                "cliffhanger": "Will Jujutsu sorcerer Megumi Fushiguro make it in time? Watch Part 2!",
                "time_range": [180, 540],
                "short_title": "The Rotten Finger That Started Everything! 💀 | Jujutsu Kaisen S1 Ep 1 Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "Megumi's divine dogs were getting torn apart, leaving Yuji with only one insane choice!",
                "narration": "Megumi Fushiguro arrives with his shadow shikigami, but the curse is overwhelming. A colossal cursed spirit traps Megumi and Yuji's friends in its jaws, crushing them to near death. Yuji charges in barehanded, landing superhuman blows, but physical strength cannot destroy a curse. Cornered with seconds before his friends are eaten alive, Yuji looks at the grotesque finger of Sukuna in his hand. Realizing only cursed energy can defeat a curse, Yuji does the unthinkable—he tosses the rotting demon finger into his mouth and swallows it whole!",
                "cliffhanger": "Did Yuji just die, or awaken the King of Curses? Part 3 will blow your mind!",
                "time_range": [540, 900],
                "short_title": "He Swallowed Sukuna's Finger LIVE! 😱 | Jujutsu Kaisen S1 Ep 1 Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "The King of Curses awakened after a thousand years, but Yuji Itadori did the impossible!",
                "narration": "Demonic black tattoos erupt across Yuji's skin as Ryomen Sukuna takes over his body. With a single casual swipe, Sukuna vaporizes the giant curse into bloody mist, laughing maniacally as he revels in the moonlight: 'The light feels best in the flesh! Women and children are crawling everywhere—it will be a massacre!' But before Sukuna can slaughter Megumi, Yuji's sheer willpower forcibly suppresses Sukuna, regaining control of his body like nothing happened! Just as Megumi prepares to execute Yuji as a curse, the strongest sorcerer Gojo Satoru makes his legendary entrance!",
                "cliffhanger": "Gojo vs Sukuna is about to begin!",
                "time_range": [900, 1260],
                "short_title": "Sukuna Awakens & Gojo Arrives! 🔥 | Jujutsu Kaisen S1 Ep 1 Part 3 #shorts",
            }
        ]
    }
}


def call_llm(prompt: str, system_prompt: str) -> str | None:
    """Call OpenRouter or Groq API for dynamic script generation."""
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    # 1. Try OpenRouter free tier models
    if openrouter_key:
        models = [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ]
        for model in models:
            try:
                req_data = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                }
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/loobah18-arch/bhaloo-shorts",
                        "X-Title": "Bhaloo Ji Anime Explanation",
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    content = res["choices"][0]["message"]["content"]
                    if content:
                        return content
            except Exception as e:
                continue

    # 2. Try Groq
    if groq_key:
        try:
            req_data = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
            }
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps(req_data).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                content = res["choices"][0]["message"]["content"]
                if content:
                    return content
        except Exception:
            pass

    return None


def generate_episode_script(episode_info: dict) -> dict:
    """
    Generate an AI-adaptive 3-to-5 part Shorts script package
    and full stitched video metadata.
    """
    ep_key = episode_info.get("episode_key", "")
    series = episode_info.get("series", "Anime")
    season = episode_info.get("season", 1)
    episode = episode_info.get("episode", 1)

    # Check pre-compiled knowledge base first
    if ep_key in EPISODE_KNOWLEDGE:
        data = EPISODE_KNOWLEDGE[ep_key]
        return _format_script_package(episode_info, data["title"], data["summary"], data["parts"])

    # If not in cache, use LLM to generate
    system_prompt = """You are an elite, viral anime recap narrator and scriptwriter benchmarked against RecapKun (@recapkun), the premier fast-paced anime recap creator.
Your task is to write an engaging, ultra-high-retention English episode recap divided into 3 to 5 parts for YouTube Shorts (90-180 seconds each, 200-450 words per part), followed by a stitched full video explanation.

RULES (RecapKun Style):
1. Every part must open with an irresistible 0-3 second HOOK (impossible dilemma, shocking action, or extreme question) that immediately stops scrolling.
2. The narration must be fast-paced, high-stakes, dramatic, and emotionally intense. Zero filler, pure narrative momentum.
3. Use punchy, crisp phrasing optimized for animated kinetic karaoke subtitles.
4. Every part (except the last) must end on an intense, razor-sharp CLIFFHANGER urging viewers to watch the next part.
5. Keep spoken words strictly between 200 and 450 words per part for rich, detailed recaps.
6. Provide a clickbait high-CTR Shorts title with part number and #shorts (e.g. 'He Swallowed Sukuna's Finger LIVE! 😱 | Jujutsu Kaisen S1 Ep 1 Part 2 #shorts').
7. Provide a comprehensive title and description for the full episode stitched video.
8. Return ONLY clean JSON matching the requested schema.
"""

    prompt = f"""Write an AI-adaptive anime recap script for:
Series: {series}
Season: {season}
Episode: {episode}
Filename: {episode_info.get('filename', '')}

Format strictly as JSON:
{{
  "episode_title": "Canonical title or main theme of this episode",
  "episode_summary": "1-2 sentence overview of the episode",
  "num_parts": 3,
  "parts": [
    {{
      "part": 1,
      "hook": "Provocative 0-3s hook sentence",
      "narration": "Fast-paced spoken narration (110-130 words)",
      "cliffhanger": "Ending hook for the next part",
      "time_range": [0, 450],
      "short_title": "High CTR Title | {series} S{season} Ep {episode} Part 1 #shorts"
    }}
  ]
}}"""

    llm_res = call_llm(prompt, system_prompt)
    if llm_res:
        try:
            # Extract JSON block
            match = re.search(r'\{.*\}', llm_res, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                return _format_script_package(
                    episode_info,
                    parsed.get("episode_title", f"{series} Episode {episode}"),
                    parsed.get("episode_summary", f"Full recap of {series} Season {season} Episode {episode}"),
                    parsed.get("parts", [])
                )
        except Exception as e:
            pass

    # Heuristic fallback if LLM is unavailable
    return _generate_heuristic_script(episode_info)


def _generate_heuristic_script(episode_info: dict) -> dict:
    """Intelligent narrative breakdown for unmapped episodes."""
    series = episode_info.get("series", "Anime")
    season = episode_info.get("season", 1)
    episode = episode_info.get("episode", 1)

    parts = [
        {
            "part": 1,
            "hook": f"What happens in {series} Season {season} Episode {episode} completely changes the entire battle!",
            "narration": f"The episode kicks off right in the middle of escalating tension. As our heroes advance into danger, enemy forces unleash unexpected techniques that catch everyone completely off guard. Every move is calculated, but the sheer difference in power is suffocating. Just when a counterattack seems possible, a shocking reveal turns the tide!",
            "cliffhanger": f"Wait until you see how they survive this attack in Part 2!",
            "time_range": [0, 450],
            "short_title": f"The Shocking Opening of {series}! 💥 | S{season} Ep {episode} Part 1 #shorts"
        },
        {
            "part": 2,
            "hook": "They were pushed to their absolute limits, and had to unleash everything!",
            "narration": f"With no room for hesitation, the battlefield explodes into high-speed combat. Blow for blow, neither side gives an inch as animation quality peaks. The emotional stakes reach a boiling point when a secret vulnerability is exposed, forcing a life-or-death gamble.",
            "cliffhanger": "Did their ultimate gamble pay off? Check Part 3 right now!",
            "time_range": [450, 900],
            "short_title": f"The Ultimate Power Revealed! 🔥 | {series} S{season} Ep {episode} Part 2 #shorts"
        },
        {
            "part": 3,
            "hook": "The climax of this episode will leave your jaw on the floor!",
            "narration": f"In a final explosive clash, the decisive strike lands. The dust settles to reveal who survived and the heavy cost of victory. But the final seconds deliver a chilling revelation that sets up the next episode in the most hype way possible!",
            "cliffhanger": f"Subscribe to Bhaloo Ji for Episode {episode + 1} next!",
            "time_range": [900, 1400],
            "short_title": f"The Insane Ending Explained! 🏆 | {series} S{season} Ep {episode} Part 3 #shorts"
        }
    ]

    return _format_script_package(
        episode_info,
        f"{series} Season {season} Episode {episode}",
        f"Detailed explanation and recap of {series} Season {season} Episode {episode}",
        parts
    )


def _format_script_package(episode_info: dict, ep_title: str, ep_summary: str, parts: list[dict]) -> dict:
    series = episode_info.get("series", "Anime")
    season = episode_info.get("season", 1)
    episode = episode_info.get("episode", 1)
    series_tag = series.replace(" ", "").replace(":", "")

    # Clean and enrich parts
    total_parts = len(parts)
    enriched_parts = []
    full_script_paragraphs = []
    chapters = []
    current_time = 0

    for i, p in enumerate(parts, 1):
        narration = p.get("narration", "").strip()
        words = len(narration.split())
        est_duration = max(45.0, min(180.0, words / 2.3))  # ~138 wpm, up to 3 min per part

        mins = int(current_time // 60)
        secs = int(current_time % 60)
        chapters.append(f"{mins:02d}:{secs:02d} Part {i}: {p.get('hook', '')[:40]}...")
        current_time += est_duration

        # Full video script avoids repetitive cliffhangers
        full_script_paragraphs.append(narration)

        enriched_p = {
            "part": i,
            "total_parts": total_parts,
            "hook": p.get("hook", "").strip(),
            "narration": narration,
            "cliffhanger": p.get("cliffhanger", "").strip(),
            "time_range": p.get("time_range", [0, 450]),
            "estimated_duration": est_duration,
            "short_title": p.get("short_title", f"{series} S{season} Ep {episode} Part {i} #shorts"),
            "badge": f"{series.upper()} • S{season:02d}E{episode:02d} • PART {i}/{total_parts}",
            "hashtags": [
                "anime", "animerecap", "animeexplanation", "shorts",
                series_tag.lower(), "bhalooji", "animelover", "otaku"
            ],
            "description": f"""{p.get('hook', '')}
Part {i} of {total_parts} covering {series} Season {season} Episode {episode}.

{FAIR_USE_DISCLAIMER}
#anime #{series_tag.lower()} #animerecap #shorts #bhalooji"""
        }
        enriched_parts.append(enriched_p)

    full_video_title = f"{series} Season {season} Episode {episode} Full Recap & Explanation | {ep_title}"
    full_description = f"""Full episode breakdown and explanation of {series} Season {season} Episode {episode}: {ep_title}.

Overview:
{ep_summary}

Episode Chapters:
{chr(10).join(chapters)}

Enjoying the breakdown? Like and Subscribe to Bhaloo Ji for daily anime recaps!

{FAIR_USE_DISCLAIMER}
#anime #{series_tag.lower()} #animerecap #animeexplained #bhalooji"""

    return {
        "series": series,
        "season": season,
        "episode": episode,
        "episode_key": episode_info.get("episode_key", f"anime-s{season:02d}e{episode:02d}"),
        "episode_title": ep_title,
        "episode_summary": ep_summary,
        "total_parts": total_parts,
        "parts": enriched_parts,
        "full_video": {
            "title": full_video_title[:100],
            "script": " ".join(full_script_paragraphs),
            "chapters": chapters,
            "description": full_description,
            "hashtags": ["anime", "animerecap", "animeexplained", series_tag.lower(), "bhalooji", "fullrecap"]
        }
    }


if __name__ == "__main__":
    from anime_catalog import get_next_episode
    ep = get_next_episode()
    if ep:
        print(f"Generating script for {ep['display_name']}...")
        script = generate_episode_script(ep)
        print(f"Episode: {script['episode_title']}")
        print(f"Total Parts: {script['total_parts']}")
        for p in script["parts"]:
            print(f"\n--- Part {p['part']}/{p['total_parts']} ---")
            print(f"Badge: {p['badge']}")
            print(f"Title: {p['short_title']}")
            print(f"Hook: {p['hook']}")
            print(f"Narration ({len(p['narration'].split())} words): {p['narration']}")
        print("\n=== FULL VIDEO TITLE ===")
        print(script["full_video"]["title"])
