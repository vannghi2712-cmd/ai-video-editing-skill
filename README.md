# ðŸŽ¬ Vlog Auto Edit â€” AI Agent è‡ªåŠ¨å‰ªè¾‘æ—…è¡Œ Vlog

> æŠŠä¸€å †æ‰‹æœºæ‹çš„æ—…è¡Œç´ æï¼Œç”¨ AI Agent è‡ªåŠ¨å‰ªæˆä¸€ä¸ªå®Œæ•´ Vlogã€‚
> ä½ åªéœ€è¦æä¾›ç´ ææ–‡ä»¶å¤¹ï¼Œå‰©ä¸‹çš„äº¤ç»™ Agentã€‚

**Vibe Editing** â€” ä¸ç”¨å­¦å‰ªè¾‘è½¯ä»¶ï¼Œä¸ç”¨è‡ªå·±æŒ‘é€‰ç´ æï¼Œä¸ç”¨çº ç»“å™äº‹ç»“æž„ã€‚
å‘Šè¯‰ AI ä½ æƒ³è¦ä»€ä¹ˆé£Žæ ¼ï¼Œå®ƒå¸®ä½ ä»Žå¤´åˆ°å°¾æžå®šã€‚

ðŸ§‘â€ðŸ’» by **nyxç ”ç©¶æ‰€** â€” [GitHub](https://github.com/znyupup) Â· [Bç«™](https://space.bilibili.com/4330525) Â· [å°çº¢ä¹¦](https://www.xiaohongshu.com/) @nyxç ”ç©¶æ‰€ Â· [X / Twitter](https://x.com/znyupup_music)

---

## `auto_video_editor` â€” Python Pipeline (Phase 2)

> **Phase 3+ (transcription, scene detection, render) is NOT implemented.**
> Only the content profile system (load, validate, CLI) is available.

### Requirements

- **Python 3.11+** (tested on 3.11.9 â€” Microsoft Store build)
- No external runtime dependencies

### Setup

```powershell
# Clone and enter the repo
git clone https://github.com/vannghi2712-cmd/ai-video-editing-skill.git
cd ai-video-editing-skill

# Create isolated virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Editable install (zero runtime dependencies)
pip install --editable . --no-deps

# Verify
python -m auto_video_editor profiles list
```

### CLI Commands

```powershell
# List all content profiles (4 columns: ID, Display Name, TikTok Handle, Duration)
python -m auto_video_editor profiles list

# Show merged JSON for a specific profile
python -m auto_video_editor profiles show food_review
python -m auto_video_editor profiles show lifestyle_vlog
python -m auto_video_editor profiles show affiliate_fast

# Validate a single profile
python -m auto_video_editor profiles validate food_review

# Validate ALL child profiles (no-arg default or explicit --all)
python -m auto_video_editor profiles validate
python -m auto_video_editor profiles validate --all
```

**Exit codes:** `0` success Â· `2` usage error Â· `3` not found/unsafe Â· `4` validation failure Â· `5` internal error

### Run Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_*.py"
# OR via venv (PYTHONPATH not required):
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

### Content Profiles

| Profile | Account | Duration | Min | Max |
|---|---|---|---|---|
| `food_review` | @luenguynnn | 45s | 30s | 60s |
| `lifestyle_vlog` | @_bylue | 45s | 30s | 60s |
| `affiliate_fast` | @iz_lue | 40s | 25s | 50s |

See [`docs/PROFILE_GUIDE.md`](docs/PROFILE_GUIDE.md) for full schema and business rules.

---

## âœ¨ è¿™æ˜¯ä»€ä¹ˆ

è¿™æ˜¯ä¸€ä»½ç»™ AI Agentï¼ˆClaude Code / Hermes / OpenClaw / GPT ç­‰ï¼‰ä½¿ç”¨çš„ **Skill æ–‡ä»¶**ï¼Œå®šä¹‰äº†ä»ŽåŽŸå§‹ç´ æåˆ°æˆå“è§†é¢‘çš„å®Œæ•´è‡ªåŠ¨å‰ªè¾‘å·¥ä½œæµã€‚

å®ƒä¸æ˜¯ä¸€ä¸ªä¼ ç»Ÿçš„è½¯ä»¶ç¨‹åºâ€”â€”è€Œæ˜¯ä¸€ä»½**æŒ‡å¯¼ AI Agent å·¥ä½œçš„çŸ¥è¯†æ–‡ä»¶**ï¼ŒåŒ…å«ï¼š
- å®Œæ•´çš„å·¥ä½œæµç¨‹å®šä¹‰
- æ¯ä¸ªæ­¥éª¤çš„å…·ä½“å‘½ä»¤å’Œä»£ç 
- 24 æ¡å®žæˆ˜è¸©å‘ç»éªŒ
- å¯è§†åŒ–é¢„è§ˆå·¥å…·
- æ¨¡æ¿å’Œç¤ºä¾‹æ•°æ®

## ðŸŽ¯ è§£å†³ä»€ä¹ˆé—®é¢˜

ä½ åŽ»æ—…è¡Œæ‹äº† 80 ä¸ªè§†é¢‘ç‰‡æ®µï¼Œå›žæ¥ä¹‹åŽï¼š
- âŒ æ‰“å¼€å‰ªæ˜ /PRï¼Œé¢å¯¹å‡ åGç´ æä¸çŸ¥ä»Žä½•ä¸‹æ‰‹
- âŒ èŠ±äº†3å°æ—¶æŒ‘é€‰ç´ æï¼ŒåˆèŠ±3å°æ—¶è°ƒæ•´é¡ºåº
- âŒ æœ€åŽå‰ªå‡ºæ¥çš„è¦ä¹ˆæ˜¯æµæ°´è´¦ï¼Œè¦ä¹ˆèŠ‚å¥å¥‡æ€ª
- âŒ æˆ–è€…å°±è¿™ä¹ˆä¸€ç›´æ”¾ç€ï¼Œæ°¸è¿œä¸ä¼šåŽ»å‰ª

ç”¨äº†è¿™ä¸ª Skillï¼š
- âœ… æŠŠç´ ææ–‡ä»¶å¤¹ä¸¢ç»™ AI Agent
- âœ… Agent è‡ªåŠ¨ç†è§£æ¯æ¡ç´ æï¼ˆç”»é¢ã€è¯­éŸ³ã€éŸ³é‡ï¼‰
- âœ… Agent åƒä¸“ä¸šå‰ªè¾‘å¸ˆä¸€æ ·ç¼–æŽ’å™äº‹ç»“æž„
- âœ… ä½ åœ¨æµè§ˆå™¨é‡Œé¢„è§ˆç¡®è®¤
- âœ… Agent è‡ªåŠ¨æ¸²æŸ“ã€åŠ æ ‡é¢˜ã€é…BGMï¼Œè¾“å‡ºæˆå“

## ðŸ› ï¸ æœ€å°ä¾èµ–

ç³»ç»Ÿçº§åªéœ€è¦è£…ä¸¤æ ·ä¸œè¥¿ï¼š

| å·¥å…· | ç”¨é€” | å®‰è£… |
|------|------|------|
| **ffmpeg** | è§†é¢‘è£å‰ª/ç¼–ç /æ‹¼æŽ¥/æŠ½å¸§/æ··éŸ³ | `brew install ffmpeg` / `apt install ffmpeg` |
| **Python 3.9+** | è„šæœ¬èƒ¶æ°´ | macOS/Linux è‡ªå¸¦ |

Python ä¾èµ–ï¼ˆAgent ä¼šè‡ªåŠ¨æ£€æµ‹å’Œå®‰è£…ï¼‰ï¼š
- `openai-whisper` â€” è¯­éŸ³è½¬å½•
- `Pillow` â€” æ ‡é¢˜å›¾ç‰‡ç”Ÿæˆ

è¿˜éœ€è¦ä¸€ä¸ª**è§†è§‰ç†è§£ API**ï¼ˆç”¨æ¥çœ‹æ‡‚ç”»é¢å†…å®¹ï¼‰ï¼š

| æ¨¡åž‹ | è´¹ç”¨ | è¯´æ˜Ž |
|------|------|------|
| æ™ºè°± GLM-4.6V-Flash | å…è´¹ | æ³¨å†Œ [open.bigmodel.cn](https://open.bigmodel.cn) å³ç”¨ï¼Œä¸­æ–‡å¥½ |
| GPT-4o | ä»˜è´¹ | æ•ˆæžœæœ€å¥½ |
| Qwen-VL | ä»˜è´¹ | é˜¿é‡Œäº‘ï¼Œä¸­æ–‡å¥½ |

**ä¸éœ€è¦ï¼š** å‰ªæ˜  / CapCut / Premiere / moviepy / ImageMagick

## ðŸ“‹ åªæœ‰ 4 æ­¥

```
 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
 â”‚                                                          â”‚
 â”‚   ç´ ææ–‡ä»¶å¤¹           â¶ åˆ†æž          è‡ªåŠ¨ï¼Œä¸ç”¨ç®¡      â”‚
 â”‚   footage/ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¶ Agent ç†è§£æ¯æ¡ç´ æçš„ç”»é¢ã€       â”‚
 â”‚                        è¯­éŸ³ã€éŸ³é‡ï¼Œæ ‡è®°é—®é¢˜ç‰‡æ®µ          â”‚
 â”‚                                                          â”‚
 â”‚                        â· ç¼–æŽ’          è‡ªåŠ¨ï¼Œä¸ç”¨ç®¡      â”‚
 â”‚                        Agent åƒå‰ªè¾‘å¸ˆä¸€æ ·è§„åˆ’            â”‚
 â”‚                        å™äº‹ç»“æž„å’Œé•œå¤´èŠ‚å¥                â”‚
 â”‚                                                          â”‚
 â”‚                        â¸ é¢„è§ˆ     â—€â”€â”€ ä½ çœ‹ä¸€çœ¼          â”‚
 â”‚                        æµè§ˆå™¨æ‰“å¼€ Dashboard               â”‚
 â”‚                        ç¡®è®¤æ–¹æ¡ˆï¼Œæˆ–æä¿®æ”¹æ„è§             â”‚
 â”‚                                                          â”‚
 â”‚                        â¹ å‡ºç‰‡          è‡ªåŠ¨ï¼Œä¸ç”¨ç®¡      â”‚
 â”‚                        è£å‰ª â†’ åŠ æ ‡é¢˜ â†’ æ‹¼æŽ¥ â†’ BGM        â”‚
 â”‚                                 â”‚                        â”‚
 â”‚                                 â–¼                        â”‚
 â”‚                           ðŸŽ¬ final.mp4                   â”‚
 â”‚                                                          â”‚
 â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

**ä½ å”¯ä¸€éœ€è¦åšçš„å°±æ˜¯ç¬¬ â¸ æ­¥â€”â€”çœ‹ä¸€çœ¼æ–¹æ¡ˆï¼Œè¯´"å¯ä»¥"ã€‚** å…¶ä»–å…¨æ˜¯ Agent è‡ªåŠ¨å®Œæˆã€‚

### â¶ åˆ†æž â€” Agent ç†è§£ä½ çš„ç´ æ

Agent ä¼šè‡ªåŠ¨å¯¹æ¯æ¡ç´ æåšä¸‰ä»¶äº‹ï¼š
- **å¬** â€” Whisper è½¬å½•è¯­éŸ³å†…å®¹
- **çœ‹** â€” æŠ½å¸§ + è§†è§‰ API ç†è§£ç”»é¢ï¼ˆå†…å®¹ã€é•œå¤´ç±»åž‹ã€æ°›å›´ï¼‰
- **é‡** â€” æ£€æµ‹éŸ³é‡ï¼ŒåŒºåˆ†æœ‰è¯­éŸ³ / é™éŸ³ / çŽ¯å¢ƒéŸ³

ç„¶åŽè‡ªåŠ¨åšé¢„å¤„ç†ï¼šåŽ»æŽ‰å¼€å¤´çš„"å¥½äº†å¼€å§‹å½•äº†"ã€é‡å¤è¯´äº†ä¸‰éçš„åŒä¸€å¥è¯ã€ä¸¾æ‰‹æœºçš„æ™ƒåŠ¨ã€è¯´å®Œè¯åŽçš„æ‹–æ‹½ã€‚

### â· ç¼–æŽ’ â€” Agent åƒå‰ªè¾‘å¸ˆä¸€æ ·è§„åˆ’

åŸºäºŽç´ æåˆ†æžç»“æžœï¼ŒAgent ä¼šï¼š
- ç”¨**ä¸‰å¹•å¼ç»“æž„**ç¼–æŽ’å™äº‹ï¼ˆå¼€ç¯‡å¼•å…¥ â†’ ä¸»ä½“å‘å±• â†’ æƒ…æ„Ÿæ”¶å°¾ï¼‰
- æŽ§åˆ¶**é•œå¤´èŠ‚å¥**ï¼ˆå¹³å‡ 3-4 ç§’/é•œå¤´ï¼Œé•¿çŸ­äº¤æ›¿ï¼‰
- è‡ªåŠ¨é€‰æœ€ç²¾å½©çš„é•œå¤´åš**ç‰‡å¤´è’™å¤ªå¥‡**
- æ ¡éªŒè¯­éŸ³è¾¹ç•Œï¼Œ**ç¡®ä¿ä¸ä¼šæŠŠè¯åˆ‡åœ¨ä¸­é—´**
- å»ºè®® BGM é£Žæ ¼

### â¸ é¢„è§ˆ â€” ä½ åœ¨æµè§ˆå™¨é‡Œç¡®è®¤

Agent ç”Ÿæˆä¸€ä¸ªäº¤äº’å¼ Dashboard ç½‘é¡µï¼š

- **ç´ ææ€»è§ˆ** â€” ç¼©ç•¥å›¾ç½‘æ ¼ï¼Œæ ‡æ³¨å·²ç”¨/æœªç”¨/å«è¯­éŸ³ï¼Œç‚¹å‡»çœ‹è¯¦æƒ…
- **åˆ†é•œé¢„è§ˆ** â€” æ¯ä¸ªé•œå¤´çš„å…³é”®å¸§ + æ—¶é—´çº¿ + æ®µè½ç»“æž„

ä½ çœ‹å®Œè¯´"å¯ä»¥"ï¼Œæˆ–è€…è¯´"ç¬¬ä¸‰æ®µæ¢ä¸ªç´ æ"â€”â€”Agent è°ƒæ•´åŽå†ç»™ä½ çœ‹ã€‚

### â¹ å‡ºç‰‡ â€” Agent è‡ªåŠ¨æ¸²æŸ“

- ç»Ÿä¸€ç¼–ç ï¼ˆh264, 1080p, 30fpsï¼‰
- æ®µè½æ ‡é¢˜å åŠ ï¼ˆç™½å­—æŸ”å’Œé˜´å½±ï¼Œä¸æ˜¯é»‘åº•æ ‡é¢˜å¡ï¼‰
- ç‰‡æ®µæ‹¼æŽ¥æˆå®Œæ•´è§†é¢‘
- BGM æ··éŸ³ï¼ˆæœ‰è¯­éŸ³æ®µè‡ªåŠ¨åŽ‹ä½Ž BGMï¼‰
- è¾“å‡º `final.mp4` ðŸŽ¬

## ðŸš€ æ€Žä¹ˆç”¨

### å¿«é€Ÿå¼€å§‹

å¤åˆ¶ä¸‹é¢çš„æŒ‡ä»¤å‘ç»™ä½ çš„ AI Agentï¼Œå®ƒä¼šè‡ªåŠ¨å®Œæˆå®‰è£…å’Œé…ç½®ï¼š

```
è¯·ä»Ž https://github.com/znyupup/ai-video-editing-skill å…‹éš†ä»“åº“ï¼Œ
é˜…è¯» SKILL.md å­¦ä¹ å®Œæ•´å·¥ä½œæµï¼Œç„¶åŽå¸®æˆ‘æŠŠ footage/ ç›®å½•ä¸‹çš„ç´ æå‰ªæˆä¸€ä¸ªæ—…è¡Œvlogã€‚
```

> ðŸ’¡ ä¸€èˆ¬æƒ…å†µä¸‹ Agent èƒ½è‡ªè¡Œå®Œæˆ ffmpeg æ£€æµ‹ã€Python ä¾èµ–å®‰è£…ã€è§†è§‰ API é…ç½®ç­‰æ‰€æœ‰å‰ç½®æ­¥éª¤ã€‚ä½ åªéœ€è¦å‡†å¤‡å¥½ç´ ææ–‡ä»¶å¤¹å’Œä¸€ä¸ªè§†è§‰æ¨¡åž‹çš„ API Keyã€‚

### æ–¹å¼ä¸€ï¼šé…åˆ AI Agent ä½¿ç”¨ï¼ˆæŽ¨èï¼‰

1. æŠŠ `SKILL.md` åŠ è½½åˆ°ä½ çš„ AI Agent
2. å‘Šè¯‰ Agentï¼š`å¸®æˆ‘æŠŠ footage/ ç›®å½•ä¸‹çš„ç´ æå‰ªæˆä¸€ä¸ªæ—…è¡Œvlog`
3. ç­‰ç€çœ‹ Dashboardï¼Œç¡®è®¤æ–¹æ¡ˆï¼Œæ”¶ç‰‡

æ”¯æŒçš„ Agent å¹³å°ï¼š
- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) â€” `git clone` åŽ `/read SKILL.md` åŠ è½½
- [OpenClaw](https://github.com/nicepkg/openclaw) â€” å¯¼å…¥åˆ° Skill åº“
- å…¶ä»–æ”¯æŒè‡ªå®šä¹‰æŒ‡ä»¤/çŸ¥è¯†åº“çš„ Agent å‡å¯ä½¿ç”¨

### æ–¹å¼äºŒï¼šä½œä¸ºå‚è€ƒæ‰‹å†Œ

å³ä½¿ä¸ç”¨ AI Agentï¼ŒSKILL.md æœ¬èº«ä¹Ÿæ˜¯ä¸€ä»½è¯¦ç»†çš„ ffmpeg + Whisper + è§†è§‰ API è§†é¢‘å‰ªè¾‘æ‰‹å†Œï¼Œå¯ä»¥æ‰‹åŠ¨æŒ‰æ­¥éª¤æ‰§è¡Œã€‚

## ðŸ“ é¡¹ç›®ç»“æž„

```
vlog-auto-edit/
â”œâ”€â”€ SKILL.md                    # ðŸ§  æ ¸å¿ƒï¼šå®Œæ•´å·¥ä½œæµå®šä¹‰ï¼ˆç»™ AI Agent è¯»çš„ï¼‰
â”œâ”€â”€ README.md                   # ðŸ“– é¡¹ç›®ä»‹ç»ï¼ˆç»™äººç±»è¯»çš„ï¼‰
â”œâ”€â”€ LICENSE                     # MIT
â”‚
â”œâ”€â”€ scripts/
â”‚   â”œâ”€â”€ gen_dashboard.py        # ðŸ“Š Dashboard ç”Ÿæˆå™¨
â”‚   â””â”€â”€ gen_storyboard.py       # ðŸŽ¬ åˆ†é•œé¢„è§ˆç”Ÿæˆå™¨
â”‚
â”œâ”€â”€ templates/
â”‚   â””â”€â”€ edit_plan_prompt.md     # ðŸ“ LLM å™äº‹ç¼–æŽ’ prompt æ¨¡æ¿
â”‚
â””â”€â”€ examples/
    â”œâ”€â”€ clip_analysis.json      # ç¤ºä¾‹ï¼šç´ æåˆ†æžæ•°æ®
    â”œâ”€â”€ edit_plan.json          # ç¤ºä¾‹ï¼šå‰ªè¾‘æ–¹æ¡ˆ
    â””â”€â”€ project_structure.md    # ç¤ºä¾‹ï¼šé¡¹ç›®æ–‡ä»¶ç»“æž„è¯´æ˜Ž
```

## ðŸ§  è¿›é˜¶ç”¨æ³•

### å‚è€ƒç ”ç©¶

åœ¨åˆ†æžç´ æä¹‹å‰ï¼Œå¯ä»¥è®© Agent å…ˆç ”ç©¶ 2-3 ä¸ªåŒç±»åž‹ä¼˜è´¨ vlogï¼ˆBç«™/YouTubeï¼‰ï¼Œæå–é•œå¤´èŠ‚å¥å’Œå™äº‹ç»“æž„ä½œä¸ºå‚è€ƒã€‚è¿™ä¸€æ­¥å¯é€‰ï¼Œä½†èƒ½æ˜¾è‘—æå‡æˆå“è´¨é‡ã€‚

### è°ƒæ•´å‰ªè¾‘é£Žæ ¼

ç¼–è¾‘ `templates/edit_plan_prompt.md` ä¸­çš„å‚æ•°ï¼š
- é•œå¤´èŠ‚å¥ï¼ˆå¹³å‡ç§’æ•°/é•œå¤´ï¼‰
- å†…å®¹é…æ¯”ï¼ˆç¾Žé£Ÿ/é£Žæ™¯/äººç‰©æ¯”ä¾‹ï¼‰
- å™äº‹ç»“æž„ï¼ˆä¸‰å¹•å¼æ¯”ä¾‹ï¼‰
- ç›®æ ‡æ—¶é•¿

### è°ƒæ•´é¢„å¤„ç†ä¸¥æ ¼åº¦

Agent åœ¨åˆ†æžé˜¶æ®µæ”¯æŒä¸‰ç§é¢„å¤„ç†æ¨¡å¼ï¼š
- `strict` â€” æ¿€è¿›è£å‰ªï¼Œæœ€çŸ­æˆå“
- `normal` â€” å‡è¡¡æ¨¡å¼ï¼ˆé»˜è®¤ï¼‰
- `loose` â€” ä¿å®ˆè£å‰ªï¼Œä¿ç•™æ›´å¤šå†…å®¹

### è‡ªå®šä¹‰è§†è§‰æ¨¡åž‹

æ”¯æŒä»»ä½•å…¼å®¹ OpenAI Chat Completions æ ¼å¼çš„è§†è§‰æ¨¡åž‹ï¼Œæ›¿æ¢ SKILL.md ä¸­çš„ API é…ç½®å³å¯ã€‚

## âš ï¸ å·²çŸ¥é™åˆ¶

- ç›®å‰é’ˆå¯¹ **æ—…è¡Œ Vlog** ä¼˜åŒ–ï¼Œå…¶ä»–ç±»åž‹è§†é¢‘éœ€è°ƒæ•´ prompt æ¨¡æ¿
- éœ€è¦è§†è§‰ç†è§£ APIï¼ˆæŽ¨èæ™ºè°±å…è´¹æ¨¡åž‹ï¼‰
- Whisper è½¬å½•åœ¨ CPU ä¸Šè¾ƒæ…¢ï¼ˆ12åˆ†é’ŸéŸ³é¢‘çº¦3åˆ†é’Ÿï¼‰
- BGM è‡ªåŠ¨ç”Ÿæˆéœ€è¦é¢å¤–çš„éŸ³ä¹ APIï¼ˆå¯é€‰ï¼Œä¹Ÿå¯ä»¥æ‰‹åŠ¨åŠ  BGMï¼‰
- macOS çš„ Homebrew ffmpeg é€šå¸¸æ²¡æœ‰ drawtext filterï¼ŒSkill ä¸­å·²ç”¨ Pillow æ–¹æ¡ˆæ›¿ä»£

## âš ï¸ è¸©å‘åˆé›†

SKILL.md ä¸­è®°å½•äº† 24 æ¡å®žæˆ˜è¸©å‘ç»éªŒï¼Œè¿™é‡Œåˆ—å‡ ä¸ªå…³é”®çš„ï¼š

1. **å‰ªæ˜  v10.4+ é¡¹ç›®æ–‡ä»¶åŠ å¯†** â€” ä¸è¦å°è¯•ç¨‹åºåŒ–æ“ä½œå‰ªæ˜
2. **xfade é“¾å¼åˆå¹¶ä¼šä¸¢å¸§** â€” ç”¨ concat ä»£æ›¿
3. **overlay ä¸è¦åŠ  shortest=1** â€” PNG åªæœ‰1å¸§ï¼Œä¼šæˆªæ–­æ•´ä¸ªè§†é¢‘
4. **Whisper ä¼šå¹»è§‰** â€” çº¯çŽ¯å¢ƒéŸ³ä¼šç¼–é€ æ–‡å­—ï¼Œéœ€ç”¨éŸ³é‡é˜ˆå€¼è¿‡æ»¤
5. **å…ˆçŸ­ç‰‡æ®µéªŒè¯** â€” æ¯æ¬¡æ”¹æ¸²æŸ“æ–¹æ¡ˆå…ˆç”¨ 5-8 ç§’ç‰‡æ®µè¯•
6. **é¢„å¤„ç†æ˜¯å»ºè®®ä¸æ˜¯ç¡¬è£å‰ª** â€” LLM å¯èƒ½è§‰å¾—æŸä¸ª"å£ä»¤"å¾ˆæœ‰è¶£è¦ä¿ç•™

å®Œæ•´åˆ—è¡¨è§ [SKILL.md](./SKILL.md) çš„ Pitfalls ç« èŠ‚ã€‚

## ðŸ¤ è´¡çŒ®

æ¬¢è¿Žæ Issue å’Œ PRï¼ç‰¹åˆ«æ¬¢è¿Žï¼š
- æ›´å¤šç±»åž‹è§†é¢‘çš„ prompt æ¨¡æ¿ï¼ˆç¾Žé£ŸæŽ¢åº—ã€åŸŽå¸‚æ¼«æ­¥ã€æˆ·å¤–è¿åŠ¨...ï¼‰
- æ–°çš„è§†è§‰æ¨¡åž‹é€‚é…
- Dashboard åŠŸèƒ½å¢žå¼º
- å…¶ä»– Agent å¹³å°çš„é€‚é…æŒ‡å—

## ðŸ‘¤ ä½œè€…

**nyxç ”ç©¶æ‰€** â€” [GitHub](https://github.com/znyupup) Â· [Bç«™ @nyxç ”ç©¶æ‰€](https://space.bilibili.com/4330525) Â· å°çº¢ä¹¦ @nyxç ”ç©¶æ‰€ Â· [X / Twitter](https://x.com/znyupup_music)

## ðŸ“„ License

MIT â€” éšä¾¿ç”¨ï¼Œæ ‡æ³¨æ¥æºå°±è¡Œã€‚

## è‡´è°¢

- [ffmpeg](https://ffmpeg.org/) â€” è§†é¢‘å¤„ç†çš„ç‘žå£«å†›åˆ€
- [OpenAI Whisper](https://github.com/openai/whisper) â€” è¯­éŸ³è½¬å½•
- [æ™ºè°±AI](https://open.bigmodel.cn/) â€” å…è´¹è§†è§‰ç†è§£æ¨¡åž‹

---

## Phase 3 — Transcription (CPU-first Vietnamese)

> **Status: IMPLEMENTED.** Phase 4 (scene scoring, rendering) is NOT implemented.

Install the ML environment (one time):

`powershell
python -m venv .venv-whisperx
.\.venv-whisperx\Scripts\pip install torch==2.8.0+cpu torchaudio==2.8.0+cpu --index-url https://download.pytorch.org/whl/cpu
.\.venv-whisperx\Scripts\pip install whisperx==3.8.6 --extra-index-url https://pypi.org/simple/
.\.venv-whisperx\Scripts\pip install -e . --no-deps
`

Check readiness:

`powershell
.\.venv-whisperx\Scripts\python.exe -m auto_video_editor transcribe doctor
# exit 0 = READY
`

Transcribe a video:

`powershell
.\.venv-whisperx\Scripts\python.exe -m auto_video_editor transcribe run
  "input.mov" --output-dir "output/" --language vi --model tiny --device cpu
`

Outputs: 	ranscript.json, 	ranscript.srt, words.json, manifest.json.

See [docs/TRANSCRIPTION_GUIDE.md](docs/TRANSCRIPTION_GUIDE.md) for full documentation.
