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
from anime_subtitle_sync import get_episode_scene_acts, generate_default_beats, CURATED_ACT_TIMELINES

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
                "short_title": "His Entire Family Was Slaughtered... 🩸 | Demon Slayer S1 Ep 1 Explanation Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "The deadliest Hashira in Japan showed absolutely zero mercy — but Tanjiro did something that changed everything!",
                "narration": "Water Hashira Giyu Tomioka is one of the most powerful demon slayers alive, and he didn't come here to talk. He swoops in with his blade already drawn, moving to decapitate Nezuko before she can harm another human. Tanjiro throws himself in front of the blow, screaming desperately: she still recognizes him, she is still his sister! But Giyu is unmoved. Compassion for demons is a fatal luxury. The weak have no rights in this world, and tears change nothing. Giyu kicks Tanjiro aside like he weighs nothing. But Tanjiro refuses to stay down. Every time he hits the ground, he drags himself back to his feet. His body is untrained, his strength is human, but his determination is something Giyu has genuinely never seen before. He charges again and again, taking hit after hit, refusing to beg but also refusing to quit. Then, in one desperate last gamble, Tanjiro flings his hand axe directly at Giyu's head — Giyu dodges by a hair — but that was just the distraction. Tanjiro dives low, catching Giyu in a surprise grapple from below. Giyu realizes with genuine shock: this ordinary boy just outsmarted him. And then Nezuko does something that stops every thought in Giyu's head cold.",
                "cliffhanger": "Did Tanjiro's secret counter actually work? See what Nezuko does in Part 3!",
                "time_range": [520, 860],
                "short_title": "Why Giyu Spared Nezuko's Life! 😱 | Demon Slayer S1 Ep 1 Explanation Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "Even after transforming into a bloodthirsty demon, Nezuko Kamado did something that no demon in history has ever done!",
                "narration": "Giyu Tomioka has hunted demons his entire life. He has seen them eat children, betray their own kind, and manipulate every emotion in pursuit of blood. He has never — not once in his career — seen a demon protect a human. But right now, with Tanjiro lying unconscious on the snow, Nezuko stands over her brother's body with her arms spread wide, growling with burning, protective defiance directly at one of the deadliest men alive. She will not move. She will not attack him. She just stands there, shielding her brother even though every demon instinct in her body must be screaming at her to feed. Giyu lowers his blade. He raises Tanjiro's hand, testing his grip unconsciously — it's the grip of someone who threw that axe on purpose, with perfect calculated timing. He has been underestimating this kid from the start. After a long silence, Giyu makes a decision that breaks every rule in the Demon Slayer Corps handbook. He gently but firmly knocks Nezuko unconscious, places a bamboo tube in her muzzle, and wraps her onto Tanjiro's back. When Tanjiro wakes up, there is a letter in his hand: seek out Master Sakonji Urokodaki on Mount Sagiri. The journey of the Demon Slayer officially begins — and nothing in the world of anime will ever be the same again.",
                "cliffhanger": "Subscribe to Bhaloo Ji for Episode 2 — the brutal training arc begins!",
                "time_range": [860, 1260],
                "short_title": "The First Demon Who Protected A Human! 🛡️ | Demon Slayer S1 Ep 1 Explanation Part 3 #shorts",
            }
        ]
    },
    "demon-slayer-s01e05": {
        "title": "His Own Sword",
        "summary": "Tanjiro survives the grueling seven-day Final Selection alongside Zenitsu, Kanao, and Genya. After choosing his tamahagane ore and returning to an emotional reunion with Nezuko and Urokodaki, swordsmith Haganezuka delivers Tanjiro's Nichirin blade—which transforms into an ominous pitch black.",
        "parts": [
            {
                "part": 1,
                "hook": "The story begins as only four young swordsmen emerge alive from the deadly mountain of demons.",
                "narration": "The seven days of terror on Fujikasane Mountain have finally drawn to a close as the rising morning sun drives away the demonic horrors of the night. Out of dozens of ambitious warriors who entered the trial, only four battered survivors stand before the wisteria blossoms: Tanjiro Kamado, covered in wounds and leaning on a broken blade; a blonde boy named Zenitsu Agatsuma, trembling uncontrollably and murmuring that he is going to die anyway; a quiet, stone-faced girl named Kanao Tsuyuri with a butterfly resting on her finger; and a menacing, mohawked brute named Genya Shinazugawa. Two twin guides with wisteria in their hair appear from the mist, warmly welcoming them into the Demon Slayer Corps and presenting them with the lowest starting rank of Mizunoto. But before anyone can celebrate surviving seven days in hell, Genya loses his patience completely, screaming that he doesn't care about ranks or ceremonies—he demands his Nichirin sword right now!",
                "cliffhanger": "Genya grabs the guide girl's hair in fury—wait until you see Tanjiro's reaction in Part 2!",
                "time_range": [505, 645],
                "beats": [
                    {"start": 505.0, "weight": 0.24, "desc": "Morning sun rises over Mt. Fujikasane, Tanjiro walks out battered"},
                    {"start": 535.0, "weight": 0.28, "desc": "Four survivors stand before wisteria: Tanjiro, trembling Zenitsu, Kanao, Genya"},
                    {"start": 575.0, "weight": 0.24, "desc": "Twin guides appear from mist presenting Mizunoto rank to survivors"},
                    {"start": 615.0, "weight": 0.24, "desc": "Genya screams angrily demanding his Nichirin sword immediately"},
                ],
                "short_title": "Only 4 Survived the Deadly Mountain! 😱 | Demon Slayer S1 Ep 5 Explanation Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "Genya grabbed the twin guide by her hair, but Tanjiro crushed his arm with bare hands!",
                "narration": "Enraged by the delay, Genya storms forward and violently grabs the white-haired guide girl by the hair, shouting that he only cares about killing demons. While Zenitsu cowers in fear, Tanjiro steps in without a second of hesitation. He grips Genya's wrist with inhuman crushing pressure, warning him coldly to let go of her immediately or he will snap his arm in two. When Genya tries to throw a punch, Tanjiro twists his arm with terrifying force until the brute screams in agony and releases the girl. With peace restored, the guides summon the Kasugai Crows—intelligent messenger birds assigned to deliver official demon slaying missions directly from Corps headquarters. Interestingly, while Tanjiro and Genya receive proud black crows, Zenitsu is comically assigned a tiny trembling sparrow. The survivors are then led to a table displaying several chunks of raw tamahagane ore. They are told that they must choose the specific metal from which their Nichirin swords will be forged. While the others struggle to distinguish between the identical-looking rocks, Tanjiro closes his eyes and uses his supernatural sense of smell, instantly sniffing out the purest, most resonant ore on the table.",
                "cliffhanger": "Will Tanjiro's broken body make it back to Mount Sagiri? Find out in Part 3!",
                "time_range": [645, 770],
                "beats": [
                    {"start": 645.0, "weight": 0.26, "desc": "Genya grabs white-haired guide girl violently by her hair"},
                    {"start": 675.0, "weight": 0.28, "desc": "Tanjiro crushes Genya wrist with bare hands warning him coldly"},
                    {"start": 710.0, "weight": 0.23, "desc": "Guides summon Kasugai crows, Zenitsu gets a tiny trembling sparrow"},
                    {"start": 740.0, "weight": 0.23, "desc": "Tamahagane ore table: Tanjiro uses smell to find purest resonant ore"},
                ],
                "short_title": "Tanjiro Breaks Genya’s Arm LIVE! 💥 | Demon Slayer S1 Ep 5 Explanation Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "Tanjiro dragged his broken body back home, and what happened when he reached the cabin will make you cry!",
                "narration": "Exhausted, battered, and relying on a wooden walking stick, Tanjiro begins the grueling trek back to Mount Sagiri. Every step sends agonizing shooting pain through his fractured ribs, but the burning thought of his sister Nezuko keeps his feet moving forward through the snow. As the familiar wooden cabin of Master Sakonji Urokodaki finally comes into view, Tanjiro collapses to his knees from pure exhaustion. But then, a deafening crash echoes through the mountain trees—the front door of the cabin is kicked clean off its hinges! Stepping out into the bright sunlight is Nezuko, fully awake from her two-year mystical slumber. Overwhelmed with emotion, Tanjiro drops his cane and crawls toward her in tears. Nezuko rushes forward with arms wide open, scooping her older brother into a tight, warm embrace. Just as Tanjiro is weeping into her shoulder, Master Urokodaki returns, dropping his bundle of firewood in shock. Tearing off his tengu mask in spirit, the stoic old master breaks down in tears and wraps his arms around both children, sobbing with profound relief that for the first time in decades, one of his beloved students has returned from the mountain alive.",
                "cliffhanger": "Wait until you see what happens when the mysterious swordsmith arrives in Part 4!",
                "time_range": [807, 965],
                "beats": [
                    {"start": 810.0, "weight": 0.25, "desc": "Exhausted Tanjiro trudges through snow with wooden walking stick"},
                    {"start": 850.0, "weight": 0.26, "desc": "Cabin door kicked off hinges, Nezuko awakens into bright sunlight"},
                    {"start": 895.0, "weight": 0.26, "desc": "Nezuko rushes forward embracing weeping Tanjiro tightly"},
                    {"start": 930.0, "weight": 0.23, "desc": "Master Urokodaki drops firewood and embraces both children in tears"},
                ],
                "short_title": "Nezuko Kicks the Door Open & Wakes Up! 😭 | Demon Slayer S1 Ep 5 Explanation Part 3 #shorts",
            },
            {
                "part": 4,
                "hook": "The legendary swordsmith arrived with wind chimes, and Tanjiro's blade turned a color nobody expected!",
                "narration": "Fifteen days pass as Tanjiro heals his wounds under Urokodaki's care, until the sharp ringing of wind chimes heralds the arrival of an eccentric visitor. Walking up the path is Hotaru Haganezuka, an official swordsmith from the hidden Swordsmith Village, sporting a wide straw hat hung with wind chimes and an outrageously funny Hyottoko clown mask. Completely ignoring Tanjiro's polite greetings, Haganezuka sits down on the dirt porch and launches into an obsessive, passionate rant about how he forged this Nichirin blade using scarlet iron sand and sunlight-absorbing ore. Once inside, Haganezuka hands Tanjiro the pristine hilt, eagerly urging him to unsheathe it. Nichirin blades are known as color-changing swords—their metal transforms into a distinct color reflecting the user's innate breathing affinity. Given Tanjiro's training under the former Water Hashira, Haganezuka and Urokodaki eagerly anticipate a brilliant azure blue blade. Tanjiro takes a deep breath, grips the handle, and draws the steel. Within seconds, a dark wave ripples across the metal, turning the entire blade into an ominous, pitch-black void!",
                "cliffhanger": "Why is a pitch-black blade an omen of death? Watch Part 5 for the chilling truth!",
                "time_range": [1044, 1207],
                "beats": [
                    {"start": 1048.0, "weight": 0.24, "desc": "Hotaru Haganezuka arrives wearing straw hat with wind chimes and clown mask"},
                    {"start": 1090.0, "weight": 0.26, "desc": "Haganezuka obsessive rant on porch explaining scarlet iron sand"},
                    {"start": 1130.0, "weight": 0.25, "desc": "Inside cabin Haganezuka hands hilt urging Tanjiro to draw sword"},
                    {"start": 1175.0, "weight": 0.25, "desc": "Dark wave ripples down blade turning steel into pitch-black void"},
                ],
                "short_title": "His Nichirin Sword Turned PITCH BLACK! ⚔️ | Demon Slayer S1 Ep 5 Explanation Part 4 #shorts",
            },
            {
                "part": 5,
                "hook": "A pitch-black sword was considered a deadly omen, but his first mission was already waiting!",
                "narration": "Haganezuka immediately flies into a furious comical rage, tackling Tanjiro to the ground because he desperately wanted to see a flashy bright red blade. Urokodaki intervenes, explaining the grave mystery of a pitch-black sword: throughout the centuries of the Demon Slayer Corps, almost no black-blade wielders have ever lived long enough for their true characteristics to be recorded, making it both exceptionally rare and historically omen-filled. Before Tanjiro can even process what this means, his Kasugai Crow swoops through the window, screeching orders in fluent human speech! The bird delivers his very first official assignment: in a town to the northwest, innocent young girls have been vanishing without a trace every single night, and Tanjiro must hunt down and exterminate the demon responsible. Urokodaki gifts Tanjiro the durable black uniform of the Corps, along with a custom light-resistant wooden box crafted from Kirin timber, allowing Nezuko to travel safely on his back during daytime. Donning his checkered haori and slinging the wooden box over his shoulders, Tanjiro takes his fateful first steps down the mountain—officially embarking on his journey to rid the world of demons!",
                "cliffhanger": "Subscribe to Bhaloo Ji for Episode 6 — Tanjiro hunts the Swamp Demon!",
                "time_range": [1207, 1370],
                "beats": [
                    {"start": 1210.0, "weight": 0.24, "desc": "Haganezuka comedic rage wrestling Tanjiro over black sword"},
                    {"start": 1250.0, "weight": 0.26, "desc": "Urokodaki explains black blade mystery and historic omen of death"},
                    {"start": 1290.0, "weight": 0.25, "desc": "Kasugai crow screeches first assignment in fluent human speech"},
                    {"start": 1330.0, "weight": 0.25, "desc": "Tanjiro receives Demon Slayer uniform and wooden box for Nezuko"},
                ],
                "short_title": "The First Demon Slaying Mission Begins! 🦅 | Demon Slayer S1 Ep 5 Explanation Part 5 #shorts",
            }
        ]
    },
    "demon-slayer-s01e06": {
        "title": "Swordsman with a Demon",
        "summary": "Tanjiro dons his Demon Slayer uniform and receives his first mission. Arriving at a northwestern town where young girls vanish every night, Tanjiro meets Kazumi and tracks the mysterious Swamp Demon beneath the earth.",
        "parts": [
            {
                "part": 1,
                "hook": "Master Urokodaki handed him a pitch-black sword and a sealed wooden box—unaware this blade was an omen of death!",
                "narration": "Tanjiro Kamado's journey from a grieving charcoal seller into an elite demon hunter begins the moment he dons the official uniform of the Demon Slayer Corps. Woven from specialized, indestructible fibers laced with wisteria minerals, this garment provides impenetrable defense against minor demon claws and fire while retaining maximum flexibility for high-speed swordplay. But as Tanjiro fastens his iconic checkered haori, Master Urokodaki reveals a chilling truth regarding the pitch-black Nichirin blade resting at his hip. Throughout the centuries-long records of the Corps, black-blade wielders have remained an ominous mystery; virtually none of them lived long enough to uncover their true breathing affinity or leave behind combat manuscripts. Unbeknownst to Tanjiro, black steel signifies an affinity for the primordial Sun itself. To ensure Nezuko's survival in the daytime world, the former Water Hashira gifts Tanjiro a custom-crafted box forged from sacred Kirin cedar. Coated in heavy natural lacquer, its light-resistant walls prevent fatal UV exposure while Nezuko recovers through mystical slumber. Hoisting his sister onto his shoulders with unwavering resolve, Tanjiro takes his fateful first strides down Mount Sagiri, stepping directly onto the brutal frontline where humans and demons clash.",
                "cliffhanger": "Will Tanjiro find the missing girls in the northwestern town? Watch Part 2!",
                "time_range": [132, 420],
                "beats": [
                    {"start": 132.0, "weight": 0.24, "desc": "Tanjiro in Demon Slayer uniform and wisteria fiber weave"},
                    {"start": 215.0, "weight": 0.27, "desc": "Urokodaki explaining pitch-black Nichirin blade omen and lore"},
                    {"start": 285.0, "weight": 0.26, "desc": "Master Urokodaki presents the Kirin cedar box parting gift"},
                    {"start": 370.0, "weight": 0.23, "desc": "Hoisting Nezuko on his back and descending Mount Sagiri"},
                ],
                "short_title": "The Secret Omen of Tanjiro's Black Sword! ⚔️ | Demon Slayer S1 Ep 6 Explanation Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "Young girls were vanishing into thin air every night, and the town accused a grieving fiancé of murder!",
                "narration": "Dispatched on his very first official assignment by his talking Kasugai crow, Tanjiro arrives in a bustling northwestern town. Yet beneath the vibrant daytime facade of vendor stalls and busy cobblestones lies an atmosphere of suffocating paranoia. Every single night, young maidens have been vanishing without leaving a single drop of blood or sign of forced entry. Tanjiro encounters Kazumi, a devastated young man hollowed out by grief and ostracized by the village. Just the previous evening, Kazumi was walking side-by-side with his bride Satoko when she literally dematerialized into the ground beneath their feet, leading the ignorant townsfolk to brand him a murderer. Tanjiro immediately recognizes the telltale agony in Kazumi's eyes and believes his story without hesitation. Dropping to his knees directly onto the dirt road, Tanjiro deploys his superhuman sense of smell. By filtering out the background scents of food and street dust, he pinpoints a faint, repulsive odor of rotting sulfur—confirming that a demon possesses the supernatural ability to traverse beneath the solid earth.",
                "cliffhanger": "The demon strikes again from the shadows—watch Part 3 for the explosive clash!",
                "time_range": [420, 660],
                "beats": [
                    {"start": 425.0, "weight": 0.28, "desc": "Tanjiro arrives at northwest town bustling vendor stalls"},
                    {"start": 495.0, "weight": 0.37, "desc": "Kazumi recounts Satoko vanishing into the ground"},
                    {"start": 575.0, "weight": 0.35, "desc": "Tanjiro sniffs cobblestones detecting sulfur scent underground"},
                ],
                "short_title": "Girls Vanishing Into Thin Air! 😱 | Demon Slayer S1 Ep 6 Explanation Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "The cobblestones dissolved into liquid swamp, dragging an innocent girl straight toward a demonic maw!",
                "narration": "As midnight plunges the northwestern alleys into darkness, the sulfuric scent spikes with terrifying intensity. Ahead in the shadows, another young maiden screams as the solid ground liquefies into a viscous, pitch-black swamp puddle that drags her downward. Tanjiro reacts with instantaneous combat reflexes, sprinting across the alley, plunging his Nichirin sword deep into the mud, and yanking the unconscious girl free just milliseconds before she is consumed whole. Rising from the dark surface is the Swamp Demon, gnashing his teeth with an irritating, rhythmic clatter that signals his predatory agitation. This repulsive creature has terrorized the region for months, preying exclusively on young girls whose flesh he believes is most tender, including Kazumi's beloved Satoko. Watching Kazumi weep beside the demon's sinister sneer ignites pure, unbridled fury within Tanjiro. Leaping high into the night sky to harness maximum gravitational acceleration, Tanjiro executes Water Breathing Eighth Form: Waterfall Basin! Crashing straight downward with a concentrated vertical kinetic shockwave, his blade cleaves through the demon's defenses and shatters the cobblestones beneath!",
                "cliffhanger": "The demon isn't alone—watch Part 4 to see Nezuko kick into action!",
                "time_range": [660, 940],
                "beats": [
                    {"start": 665.0, "weight": 0.24, "desc": "Night falls, black puddle opens on the ground dragging girl"},
                    {"start": 725.0, "weight": 0.24, "desc": "Tanjiro dashes forward, stabs ground and rescues unconscious girl"},
                    {"start": 785.0, "weight": 0.22, "desc": "Grotesque Swamp Demon surfaces grinding teeth rhythmically"},
                    {"start": 860.0, "weight": 0.30, "desc": "Tanjiro leaps into night sky, Waterfall Basin crushing strike"},
                ],
                "short_title": "Water Breathing Waterfall Basin LIVE! 🌊 | Demon Slayer S1 Ep 6 Explanation Part 3 #shorts",
            },
            {
                "part": 4,
                "hook": "The Swamp Demon cloned into three killers, but Nezuko's explosive kick smashed through everything!",
                "narration": "The crushing impact demolishes the street, yet the Swamp Demon survives through an unexpected Blood Demon Art: his body splits into three separate clones, each slipping into the subterranean marsh to encircle Tanjiro from every angle. Tanjiro is forced into a tactical dilemma—staying on the surface to shield Kazumi and the unconscious victim leaves him wide open to underground ambushes. Just as the third clone claws out of the wall to rip Kazumi apart, the wooden box on Tanjiro's back violently trembles—and Nezuko kicks the door clean off its hinges! Her demonic pink eyes blazing with protective fury, Nezuko unleashes a devastating axe kick that sends the demon violently ricocheting into a stone barrier. Under Master Urokodaki's hypnotic conditioning, Nezuko sees all humans as her fallen siblings and demons as merciless monsters to destroy. Realizing his sister can dominate the surface threat, Tanjiro takes a full breath of Total Concentration and dives headfirst into the swamp portal, bringing the fight directly into the demon's submerged territory!",
                "cliffhanger": "Subscribe to Bhaloo Ji for Episode 7 — Tanjiro encounters Muzan Kibutsuji!",
                "time_range": [940, 1260],
                "beats": [
                    {"start": 945.0, "weight": 0.24, "desc": "Impact shatters ground, Swamp Demon splits into three clones"},
                    {"start": 1015.0, "weight": 0.24, "desc": "Tactical dilemma defending Kazumi and unconscious girl"},
                    {"start": 1080.0, "weight": 0.27, "desc": "Box rattles, Nezuko kicks door open delivering savage axe kick"},
                    {"start": 1160.0, "weight": 0.25, "desc": "Tanjiro dives headfirst into underground swamp portal"},
                ],
                "short_title": "Nezuko Kicks The Swamp Demon! 💥 | Demon Slayer S1 Ep 6 Explanation Part 4 #shorts",
            }
        ]
    },
    "demon-slayer-s01e07": {
        "title": "Muzan Kibutsuji",
        "summary": "Tanjiro descends into the murky swamp dimension to exterminate two swamp clones using Water Breathing Sixth Form: Whirlpool. Returning to the surface, Tanjiro and Nezuko defeat the final demon and comfort Kazumi. Tanjiro journeys to neon Asakusa, Tokyo, where he catches the unmistakable scent of his family's slaughter—and confronts Muzan Kibutsuji living in plain sight.",
        "parts": [
            {
                "part": 1,
                "hook": "He dove straight into a pitch-black demonic swamp dimension, where demons thought he was completely helpless!",
                "narration": "Plunging headfirst into the viscous, liquid abyss, Tanjiro Kamado enters the Swamp Demon's subterranean pocket dimension. Suspended in pitch-black murk where normal humans would suffocate in seconds, two sinister demon clones encircle him with predatory glee, believing the young slayer is immobilized by immense hydrostatic pressure and zero traction. But they severely underestimate the brutal conditioning of former Water Hashira Sakonji Urokodaki! Water Breathing is fundamentally engineered to dominate aquatic physics. Planting his core and twisting his entire upper body with ferocious rotational torque, Tanjiro unleashes Water Breathing Sixth Form: Whirlpool! A violent, high-pressure hydro-vortex violently erupts through the dark marsh, sucking both demon clones into its razor-sharp spiral current and cleanly decapitating them before they can even scream!",
                "cliffhanger": "Can Nezuko survive on the surface alone? Watch Part 2 for the brutal clash!",
                "time_range": [120, 390],
                "beats": [
                    {"start": 120.0, "weight": 0.25, "desc": "Submerging into murky underwater swamp dimension"},
                    {"start": 210.0, "weight": 0.25, "desc": "Swamp demons taunting Tanjiro underwater"},
                    {"start": 290.0, "weight": 0.25, "desc": "Total concentration water breathing preparation"},
                    {"start": 355.0, "weight": 0.25, "desc": "Sixth Form Whirlpool vortex decapitation"},
                ],
                "short_title": "Water Breathing Sixth Form Whirlpool! 🌀 | Demon Slayer S1 Ep 7 Explanation Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "He pinned the terrified demon to the cobblestones, but mentioning one name caused pure cellular horror!",
                "narration": "Bursting through the muddy portal back onto the moonlit cobblestones, Tanjiro arrives just as Nezuko delivers a barrage of ferocious blows against the third and final demon clone. Moving with lightning precision, Tanjiro pins the mangled demon to the earth with his pitch-black Nichirin blade pressed hard against its neck. Looking coldly into the creature's panicked eyes, Tanjiro demands answers: 'How many innocent lives have you devoured? And what do you know about Muzan Kibutsuji?!' At the mere mention of that forbidden name, the demon's eyes dilate in absolute, paralyzing cellular terror. An ingrained biological curse planted deep in every demon's blood threatens instant vaporization if Muzan's identity is betrayed. Driven mad with hysteria, the demon lunges in a suicidal counterattack—and Tanjiro's blade severs his head in one clean stroke.",
                "cliffhanger": "Wait until you see Tanjiro's emotional farewell in Part 3!",
                "time_range": [390, 680],
                "beats": [
                    {"start": 395.0, "weight": 0.25, "desc": "Tanjiro bursts up onto surface streets"},
                    {"start": 480.0, "weight": 0.25, "desc": "Nezuko combat defending above ground"},
                    {"start": 570.0, "weight": 0.25, "desc": "Tanjiro pinning final demon to ground"},
                    {"start": 640.0, "weight": 0.25, "desc": "Interrogating demon about Muzan Kibutsuji"},
                ],
                "short_title": "The Demon Who Feared Muzan Kibutsuji! 😱 | Demon Slayer S1 Ep 7 Explanation Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "He handed back the keepsakes of the murdered brides, and his parting words will make you cry!",
                "narration": "With the nightmare over, Tanjiro recovers a collection of stolen hairpins and hair ribbons from the demon's lair, presenting them to the shattered Kazumi. Clutching his deceased fiancée Satoko's ribbon against his chest, Kazumi breaks down in uncontrollable sobs, crying out that no matter how many trinkets remain, the love of his life will never return to his arms. Tanjiro gently places his calloused, battle-scarred hand over Kazumi's trembling fingers. Looking directly into his grief-stricken eyes with profound warmth, Tanjiro speaks words carved from his own tragedy: 'No matter how much you lose, you have no choice but to keep on living.' Kazumi looks at Tanjiro's weathered face and realizes with heartbreaking clarity that this young swordsman has already endured losses far beyond comprehension. As the sun rises, Tanjiro and Nezuko depart for their next mission—marching toward the dazzling, electric-lit metropolis of Asakusa, Tokyo.",
                "cliffhanger": "What awaits Tanjiro in the neon streets of Tokyo? Watch Part 4 for the ultimate shock!",
                "time_range": [680, 950],
                "beats": [
                    {"start": 685.0, "weight": 0.25, "desc": "Returning missing girls items to weeping Kazumi"},
                    {"start": 765.0, "weight": 0.25, "desc": "Kazumi emotional farewell and gratitude"},
                    {"start": 845.0, "weight": 0.25, "desc": "Journeying toward Tokyo at dusk"},
                    {"start": 910.0, "weight": 0.25, "desc": "Arrival at neon Asakusa Tokyo metropolis"},
                ],
                "short_title": "The Most Heartbreaking Farewell in Demon Slayer 😭 | Demon Slayer S1 Ep 7 Explanation Part 3 #shorts",
            },
            {
                "part": 4,
                "hook": "He caught the scent of his family's killer in the crowded city, but what he found froze his blood solid!",
                "narration": "Arriving in Taisho-era Asakusa, Tanjiro is utterly overwhelmed by the dazzling sea of electric lamps, roaring streetcars, and bustling nighttime crowds. Seeking refuge from sensory overload, he retreats to an alley cart to eat a bowl of yam udon. But suddenly, mid-bite, his superhuman sense of smell catches a terrifying, unmistakable scent—the exact repulsive odor that permeated the frozen pool of blood at his family's slaughter! Dropping his bowl, Tanjiro sprints desperately through the packed streets, shoving through pedestrians with wild urgency until his hand clutches the shoulder of an elegant gentleman in a white fedora and western suit. The man turns around, revealing chilling crimson eyes and slit pupils—it is Muzan Kibutsuji himself! But as Tanjiro draws his blade to strike, his heart stops in pure, paralyzed horror: cradled gently in Muzan's arms is a smiling human toddler, and standing beside him is a loving human woman who calls him her husband!",
                "cliffhanger": "Subscribe to Bhaloo Ji for Episode 8 — The Blood Demon Art of Lady Tamayo!",
                "time_range": [950, 1270],
                "beats": [
                    {"start": 955.0, "weight": 0.25, "desc": "Overwhelmed by electric lights eating udon"},
                    {"start": 1035.0, "weight": 0.25, "desc": "Detecting scent of family slaughter"},
                    {"start": 1115.0, "weight": 0.25, "desc": "Sprinting desperately through Asakusa crowd"},
                    {"start": 1200.0, "weight": 0.25, "desc": "Confronting Muzan Kibutsuji holding human child"},
                ],
                "short_title": "Tanjiro Confronts Muzan Kibutsuji IN PUBLIC! 😱 | Demon Slayer S1 Ep 7 Explanation Part 4 #shorts",
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
                "short_title": "The Rotten Finger That Started Everything! 💀 | Jujutsu Kaisen S1 Ep 1 Explanation Part 1 #shorts",
            },
            {
                "part": 2,
                "hook": "Megumi's divine dogs were getting torn apart, leaving Yuji with only one insane choice!",
                "narration": "Megumi Fushiguro arrives with his shadow shikigami, but the curse is overwhelming. A colossal cursed spirit traps Megumi and Yuji's friends in its jaws, crushing them to near death. Yuji charges in barehanded, landing superhuman blows, but physical strength cannot destroy a curse. Cornered with seconds before his friends are eaten alive, Yuji looks at the grotesque finger of Sukuna in his hand. Realizing only cursed energy can defeat a curse, Yuji does the unthinkable—he tosses the rotting demon finger into his mouth and swallows it whole!",
                "cliffhanger": "Did Yuji just die, or awaken the King of Curses? Part 3 will blow your mind!",
                "time_range": [540, 900],
                "short_title": "He Swallowed Sukuna's Finger LIVE! 😱 | Jujutsu Kaisen S1 Ep 1 Explanation Part 2 #shorts",
            },
            {
                "part": 3,
                "hook": "The King of Curses awakened after a thousand years, but Yuji Itadori did the impossible!",
                "narration": "Demonic black tattoos erupt across Yuji's skin as Ryomen Sukuna takes over his body. With a single casual swipe, Sukuna vaporizes the giant curse into bloody mist, laughing maniacally as he revels in the moonlight: 'The light feels best in the flesh! Women and children are crawling everywhere—it will be a massacre!' But before Sukuna can slaughter Megumi, Yuji's sheer willpower forcibly suppresses Sukuna, regaining control of his body like nothing happened! Just as Megumi prepares to execute Yuji as a curse, the strongest sorcerer Gojo Satoru makes his legendary entrance!",
                "cliffhanger": "Gojo vs Sukuna is about to begin!",
                "time_range": [900, 1260],
                "short_title": "Sukuna Awakens & Gojo Arrives! 🔥 | Jujutsu Kaisen S1 Ep 1 Explanation Part 3 #shorts",
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
                "model": "openai/gpt-oss-120b",
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

    # Determine chronological scene acts for this episode (skipping OP and ED)
    scene_acts = get_episode_scene_acts(episode_info, num_parts=3)

    # If not in cache, use LLM to generate
    system_prompt = """You are an elite anime documentary narrator and scriptwriter modeling the signature style of RecapKun (@recapkun).
Your task is to write a MASTER long-form anime recap script for the full normal video.
Shorts will later be clipped as direct excerpts from the chapters of this normal video.

CRITICAL ARCHITECTURE RULES:
1. MASTER NORMAL VIDEO FIRST: There is NO word limit or time limit for the normal video. Be exhaustive, immersive, rich, and detailed.
2. CONTINUOUS FLOW: The narration across all chapters MUST be ONE continuous, uninterrupted story. Each chapter must flow seamlessly into the next with natural narrative transitions.
3. NO MID-VIDEO CLIFFHANGERS IN NARRATION: Never write phrases like 'Wait until you see in Part 2' or 'In Part 3' inside the narration text. Cliffhangers are only provided in the separate 'cliffhanger' metadata field for the Short excerpt teasers.
4. EXPLAIN THE LORE: Deeply explain combat mechanics, breathing forms, cursed energy techniques, character emotional conflicts, and power systems.
5. CHRONOLOGICAL SCENE ACTS: You MUST write each chapter specifically about its assigned chronological scene act, matching the EXACT time_range provided.
6. SHORTS ARE EXCERPTS: Provide an opening hook and high-CTR title for each chapter so that Shorts can be clipped as excerpts from this normal video.
7. Return ONLY valid JSON matching the requested schema.
"""

    prompt = f"""Write a master RecapKun-style anime recap script for:
Series: {series}
Season: {season}
Episode: {episode}
Filename: {episode_info.get('filename', '')}

ASSIGNED CHRONOLOGICAL SCENE ACTS & TIME RANGES:
{json.dumps(scene_acts, indent=2)}

Format strictly as JSON:
{{
  "episode_title": "Canonical title or main theme of this episode",
  "episode_summary": "In-depth overview of the full episode",
  "num_parts": {len(scene_acts)},
  "parts": [
    {{
      "part": 1,
      "hook": "Compelling opening hook for this chapter (0-3s)",
      "narration": "Deep, detailed continuous narration of this act with zero word-count constraints and smooth transitions to next act",
      "cliffhanger": "Teaser hook exclusively for the Short excerpt description/CTA",
      "time_range": {scene_acts[0]["time_range"] if scene_acts else [120, 500]},
      "short_title": "High CTR Title | {series} S{season} Ep {episode} Explanation Part 1 #shorts",
      "beats": [
        {{"start": 130.0, "weight": 0.25, "desc": "Action or dialogue occurring in this scene"}}
      ]
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
                parts = parsed.get("parts", [])
                # Ensure each part preserves exact scene time_range and beats
                for idx, p in enumerate(parts):
                    if idx < len(scene_acts):
                        if "time_range" not in p or p["time_range"] == [0, 450]:
                            p["time_range"] = scene_acts[idx]["time_range"]
                        if "beats" not in p or not p["beats"]:
                            p["beats"] = scene_acts[idx].get("beats", [])
                return _format_script_package(
                    episode_info,
                    parsed.get("episode_title", f"{series} Episode {episode}"),
                    parsed.get("episode_summary", f"Full recap of {series} Season {season} Episode {episode}"),
                    parts
                )
        except Exception:
            pass

    # Heuristic fallback if LLM is unavailable
    return _generate_heuristic_script(episode_info, scene_acts)


def _generate_heuristic_script(episode_info: dict, scene_acts: list[dict] = None) -> dict:
    """Intelligent narrative breakdown for unmapped episodes with scene-synced timestamps."""
    series = episode_info.get("series", "Anime")
    season = episode_info.get("season", 1)
    episode = episode_info.get("episode", 1)

    if not scene_acts:
        scene_acts = get_episode_scene_acts(episode_info, num_parts=3)

    parts = []
    default_hooks = [
        f"What happens in {series} Season {season} Episode {episode} completely changes the entire battle!",
        "They were pushed to their absolute limits, and had to unleash everything!",
        "The climax of this episode will leave your jaw on the floor!",
        "A shocking twist turns the battlefield upside down!"
    ]
    default_narrations = [
        f"The episode kicks off right in the middle of escalating tension. As our heroes advance into danger, enemy forces unleash unexpected techniques that catch everyone completely off guard. Every move is calculated, but the sheer difference in power is suffocating. Just when a counterattack seems possible, a shocking reveal turns the tide!",
        "With no room for hesitation, the battlefield explodes into high-speed combat. Blow for blow, neither side gives an inch as animation quality peaks. The emotional stakes reach a boiling point when a secret vulnerability is exposed, forcing a life-or-death gamble.",
        "In a final explosive clash, the decisive strike lands. The dust settles to reveal who survived and the heavy cost of victory. But the final seconds deliver a chilling revelation that sets up the next episode in the most hype way possible!",
        "As the dust settles, enemy reinforcements loom on the horizon, leaving everyone with an impossible ultimatum."
    ]

    for idx, act in enumerate(scene_acts):
        p_num = act.get("part", idx + 1)
        tr = act.get("time_range", [120 + (idx * 300), 120 + ((idx + 1) * 300)])
        theme = act.get("theme", f"Act {p_num}")
        parts.append({
            "part": p_num,
            "hook": default_hooks[idx % len(default_hooks)],
            "narration": f"{default_narrations[idx % len(default_narrations)]} Focusing on {theme}.",
            "cliffhanger": f"Check Part {p_num + 1} right now!" if p_num < len(scene_acts) else f"Subscribe to Bhaloo Ji for Episode {episode + 1} next!",
            "time_range": tr,
            "short_title": f"The Shocking Clashes of {series}! 💥 | S{season} Ep {episode} Explanation Part {p_num} #shorts"
        })

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
        est_duration = max(30.0, words / 2.8)  # ~170 wpm at +8% pace, no arbitrary ceiling

        mins = int(current_time // 60)
        secs = int(current_time % 60)
        chapters.append(f"{mins:02d}:{secs:02d} Part {i}: {p.get('hook', '')[:40]}...")
        current_time += est_duration

        # Full video script: continuous flowing story
        full_script_paragraphs.append(narration)

        beats = p.get("beats")
        if not beats:
            ep_key = episode_info.get("episode_key", "")
            if ep_key in CURATED_ACT_TIMELINES and i - 1 < len(CURATED_ACT_TIMELINES[ep_key]["acts"]):
                beats = CURATED_ACT_TIMELINES[ep_key]["acts"][i - 1].get("beats")
            if not beats:
                beats = generate_default_beats(p.get("time_range", [0, 450]))

        # Guarantee 'Explanation' is explicitly present in every Short title
        raw_st = p.get("short_title", "").strip()
        if not raw_st:
            raw_st = f"{series} S{season} Ep {episode} Explanation Part {i} #shorts"
        elif "explanation" not in raw_st.lower() and "explained" not in raw_st.lower():
            if re.search(rf"\bPart\s*{i}\b", raw_st, re.IGNORECASE):
                raw_st = re.sub(rf"\bPart\s*{i}\b", f"Explanation Part {i}", raw_st, count=1, flags=re.IGNORECASE)
            elif "#shorts" in raw_st.lower():
                raw_st = re.sub(r"#shorts", f"Explanation Part {i} #shorts", raw_st, count=1, flags=re.IGNORECASE)
            else:
                raw_st = f"{raw_st} | Explanation Part {i} #shorts"

        enriched_p = {
            "part": i,
            "total_parts": total_parts,
            "hook": p.get("hook", "").strip(),
            "narration": narration,
            "cliffhanger": p.get("cliffhanger", "").strip(),
            "time_range": p.get("time_range", [0, 450]),
            "beats": beats,
            "estimated_duration": est_duration,
            "short_title": raw_st,
            "badge": f"{series.upper()} • S{season:02d}E{episode:02d} • PART {i}/{total_parts}",
            "hashtags": [
                "anime", "animerecap", "animeexplanation", "shorts",
                series_tag.lower(), "bhalooji", "animelover", "otaku"
            ],
            "description": f"""{p.get('hook', '')}
Part {i} of {total_parts} covering {series} Season {season} Episode {episode}.

🎬 This is an excerpt from our FULL in-depth episode breakdown! Watch the complete video on our channel:
https://youtube.com/@bhalooji

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
