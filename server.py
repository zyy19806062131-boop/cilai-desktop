#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「词来」老师备课与课堂生词助手 · 本地伴侣服务
专为对外汉语老师打造：
1. 静态网页托管 (http://127.0.0.1:8765)
2. 全量 19.8 万 CEDICT 词库极速检索
3. 大模型超拟人神经网络语音合成 (豆包大模型 2.0 / 微软晓晓 / 云舟 / Vivi)
4. 双语言翻译体系：英文必备，母语二翻
5. 多学生生词本管理体系（为不同国籍学生独立建本归档）
6. 多题型 AI 随堂操练题生成（选词填空、连词成句、情境问答、词语搭配）
7. 智能路由与本地安全落盘
"""

import os
import sys
import json
import re
import time
import base64
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.parse
import shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# 2026-09-06 改（小克，K623）：端口可用环境变量改。老师桌面上开着的词来.app 长期占着 8765，
# 开发预览要另起一个端口（CILAI_PORT=8766），否则没法在不杀老师 app 的前提下看改动。
PORT = int(os.environ.get("CILAI_PORT", "8765") or 8765)
BASE_DIR = Path(__file__).resolve().parent

# 数据落在 app 包外面，跟 Electron 的 userData 同一个地方
if sys.platform == "darwin":
    USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "cilai"
else:
    USER_DATA_DIR = Path.home() / ".cilai"

DATA_DIR = USER_DATA_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
STUDENTS_FILE = DATA_DIR / "students_meta.json"
AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"
BUNDLE_DATA_DIR = BASE_DIR / "data"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 首次启动时若 BASE_DIR/data/history/ 里有 json 而新目录没有，拷过去做无损迁移
legacy_history = BUNDLE_DATA_DIR / "history"
if legacy_history.exists():
    for f in legacy_history.glob("*.json"):
        target = HISTORY_DIR / f.name
        if not target.exists():
            try:
                shutil.copy2(f, target)
            except Exception:
                pass

# ── 2026-09-03 加（小克，老师报「繁体简体混用，出题质量极差」）──────────
# 模型（Qwen/Gemini）时不时吐繁体：老师截图里第 3 题整句是
# 「他第一次見面時總是（____），不敢說話。」——教简体的课上不能出这个。
# prompt 里写"必须简体"只是**请求**，模型不一定听；这里加一道**确定性**的出口转换。
# opencc 本机实测可用（t2s）；万一没装就退回不转换，只靠 prompt，不让服务起不来。
try:
    import opencc as _opencc
    _T2S = _opencc.OpenCC("t2s")
    HAS_OPENCC = True
except Exception:
    _T2S = None
    HAS_OPENCC = False

_BRACKET_RE = re.compile(r"【\s*([^【】]*?)\s*】")

def strip_lens_brackets(value):
    """2026-09-03 加（小克）：模型爱用【】把目标词括起来，于是出现
    「让我【（____）】买点菜」这种双重括号，和「他【害羞】得说不出话」这种
    课件里不该有的标记。统一去掉【】只留里面的内容。"""
    if isinstance(value, str):
        return _BRACKET_RE.sub(r"\1", value)
    if isinstance(value, list):
        return [strip_lens_brackets(v) for v in value]
    if isinstance(value, dict):
        return {k: strip_lens_brackets(v) for k, v in value.items()}
    return value


def to_simplified(value):
    """递归把 dict/list/str 里的繁体字转成简体。非字符串原样返回。"""
    if not HAS_OPENCC:
        return value
    if isinstance(value, str):
        try:
            return _T2S.convert(value)
        except Exception:
            return value
    if isinstance(value, list):
        return [to_simplified(v) for v in value]
    if isinstance(value, dict):
        return {k: to_simplified(v) for k, v in value.items()}
    return value

SIMPLIFIED_RULE = (
    "【字形硬要求】全部中文一律使用**简体字**（中国大陆规范汉字）。"
    "禁止出现任何繁体字（例如不许写 見/時/總/說/話/學/國/這/會/來/後），"
    "题目、选项、答案、解析、例句一个字都不许是繁体。"
)

LANG_CODE_MAP = {
    "英语": "en",
    "西班牙语": "es",
    "俄语": "ru",
    "法语": "fr",
    "日语": "ja",
    "韩语": "ko",
    "德语": "de",
    "意大利语": "it",
    "葡萄牙语": "pt",
    "阿拉伯语": "ar",
    "越南语": "vi",
    "泰语": "th",
    "荷兰语": "nl",
    "波兰语": "pl",
    "乌克兰语": "uk",
    "希腊语": "el",
    "捷克语": "cs",
    "瑞典语": "sv",
    "匈牙利语": "hu",
    "罗马尼亚语": "ro",
    "丹麦语": "da",
    "芬兰语": "fi",
    "挪威语": "no",
    "塞尔维亚语": "sr",
    "克罗地亚语": "hr",
    "斯洛伐克语": "sk",
    "保加利亚语": "bg",
    "立陶宛语": "lt",
    "拉脱维亚语": "lv",
    "爱沙尼亚语": "et",
    "斯洛文尼亚语": "sl",
    "爱尔兰语": "ga",
    "印度尼西亚语": "id",
    "马来语": "ms",
    "土耳其语": "tr",
    "波斯语": "fa",
    "希伯来语": "he",
    "印地语": "hi",
    "孟加拉语": "bn",
    "乌尔都语": "ur",
    "菲律宾语": "tl",
    "缅甸语": "my",
    "高棉语": "km",
    "老挝语": "lo",
    "蒙古语": "mn",
    "哈萨克语": "kk",
    "乌兹别克语": "uz",
    "格鲁吉亚语": "ka",
    "亚美尼亚语": "hy",
    "阿塞拜疆语": "az",
    "泰米尔语": "ta",
    "泰卢固语": "te",
    "拉美西班牙语": "es-419",
    "巴西葡萄牙语": "pt-BR",
    "加拿大法语": "fr-CA",
    "斯瓦希里语": "sw",
    "南非荷兰语": "af",
    "阿姆哈拉语": "am",
    "豪萨语": "ha",
    "约鲁巴语": "yo",
    "祖鲁语": "zu"
}

def get_key_from_env_file(file_name, key_name):
    env_val = os.environ.get(key_name, "").strip()
    if env_val:
        return env_val
    key_file = Path.home() / ".config" / "gamekit" / file_name
    if key_file.exists():
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key_name}="):
                        return line.split("=", 1)[1].strip().strip("\"'")
        except Exception:
            pass
    return ""

DASHSCOPE_KEY = get_key_from_env_file("bailian.env", "DASHSCOPE_API_KEY")
GEMINI_KEY = get_key_from_env_file("gemini.env", "GEMINI_API_KEY")
def get_deepseek_key():
    k = get_key_from_env_file("deepseek.env", "DEEPSEEK_API_KEY")
    if k:
        return k
    cfg = Path.home() / ".config" / "video-distiller" / "config.json"
    if cfg.exists():
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d.get("deepseek_api_key", "").strip()
        except Exception:
            pass
    return ""

DEEPSEEK_KEY = get_deepseek_key()

def find_gcp_credentials():
    env_cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env_cred and os.path.exists(env_cred):
        return env_cred
    gamekit_dir = Path.home() / ".config" / "gamekit"
    candidates = [
        gamekit_dir / "google_translate.json",
        gamekit_dir / "gcp_service_account.json",
        gamekit_dir / "service_account.json"
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""

GCP_CREDENTIAL_PATH = find_gcp_credentials()

# 后端词库已由前端离线词库替代，避免重复消耗内存

# 神经网络超拟人语音合成
def generate_tts_audio(text, speaker="zh_female_shuangkuaisisi_uranus_bigtts"):
    clean_text = text.strip()
    if not clean_text:
        return None, None, "文本为空"

    h = hashlib.md5(f"{clean_text}_{speaker}".encode("utf-8")).hexdigest()

    if speaker.startswith("zh_"):
        out_wav = AUDIO_CACHE_DIR / f"{h}.wav"
        if out_wav.exists() and out_wav.stat().st_size > 1000:
            return str(out_wav), "audio/wav", None

        volc_script = Path.home() / "bin" / "gentts_volc.py"
        if volc_script.exists():
            try:
                cmd = ["python3", str(volc_script), clean_text, str(out_wav), speaker]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
                if res.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 1000:
                    return str(out_wav), "audio/wav", None
            except Exception as e:
                print(f"调用 gentts_volc 异常: {e}")

    edge_bin = "/Users/a1/Library/Python/3.9/bin/edge-tts"
    if os.path.exists(edge_bin):
        out_mp3 = AUDIO_CACHE_DIR / f"{h}.mp3"
        if out_mp3.exists() and out_mp3.stat().st_size > 500:
            return str(out_mp3), "audio/mp3", None

        voice_name = "zh-CN-XiaoxiaoNeural"
        if "yunxi" in speaker.lower():
            voice_name = "zh-CN-YunxiNeural"

        try:
            cmd = [edge_bin, "--voice", voice_name, "--text", clean_text, "--write-media", str(out_mp3)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and out_mp3.exists() and out_mp3.stat().st_size > 500:
                return str(out_mp3), "audio/mp3", None
        except Exception as e:
            print(f"调用 edge-tts 异常: {e}")

    return None, None, "语音合成不可用"

DIFFICULTY_STANDARDS = {
    "simple": {
        "label": "简单句 (初级 HSK 1-2)",
        "rule": "句式短小直接（8~14字），主谓宾基础结构，词汇日常通用，直白呈现生词核心本义，易读好练。"
    },
    "medium": {
        "label": "中等难度 (中级 HSK 3-4)",
        "rule": "真实生活常用复合句（14~20字），可带常用关联词（虽然…但是…、如果…就…等）或状语补语，展现地道口语交际逻辑。"
    },
    "complex": {
        "label": "复杂句 (高级 HSK 5-6)",
        "rule": "结构丰富、表达深入的高级复句（18~28字），包含思辨转折、职场商务交流或深层情感，用词凝练地道，富含表现力。"
    }
}

# AI 例句生成 (DeepSeek - 极速出题与高质量例句主力)
def generate_deepseek_sentence(word, pinyin="", base_english="", target_lang="英语", difficulty="medium", avoid_sentences=None, nonce=""):
    key = DEEPSEEK_KEY
    if not key:
        return None, "未配置 DeepSeek API Key"

    avoid_sentences = avoid_sentences or []
    diff_key = difficulty if difficulty in DIFFICULTY_STANDARDS else "medium"
    diff_spec = DIFFICULTY_STANDARDS[diff_key]
    is_second_lang = (target_lang and target_lang != "英语")

    avoid_prompt = ""
    if avoid_sentences:
        avoid_json = json.dumps(avoid_sentences[:6], ensure_ascii=False)
        avoid_prompt = f"\n【排重指令】：绝对不要重复或类似于以下已出现过的例句：\n{avoid_json}\n"

    lang_prompt = f"""语言要求：
1. 英文翻译为必备基础项（english、sentence_en）。
2. 学生母语为【{target_lang}】，必须同时提供二翻母语释义（native_def）与例句母语翻译（sentence_native）。""" if is_second_lang else "学生媒介语为【英语】。请输出简明地道的英文释义与例句英译。"

    prompt = f"""你是一位对外汉语专家名师。请为外国学生学习生词【{word}】设计一个生动实用、贴近生活的教学例句。
生词：【{word}】（参考拼音：{pinyin or "自动计算"}，参考英文：{base_english or "自动计算"}，学生母语：{target_lang}）。

【难度档位】：【{diff_spec['label']}】
【句式难度标准】：{diff_spec['rule']}

【教学铁律】：
1. 纯正地道：说中国人平时生活与工作中脱口而出的真话、人话，严禁任何机械套话（不许出现“我在学习怎么用……”、“关于这个……”）。
2. 场景完全自由开放：根据生词【{word}】的真实本义与生活搭配自然展开，严禁千篇一律套用“去超市买咖啡/下班顺路”，严禁为了凑语法硬套把字句。
3. 必须包含生词【{word}】，并用【】包裹目标生词，形如【{word}】，严禁用近义词替换。
4. sentence_py 必须是完整带调拼音，里面不许混杂汉字。
5. sentence_en 必须是自然口语化的英文整句。
{avoid_prompt}
{lang_prompt}

严格输出纯 JSON：
{{
  "word": "{word}",
  "pinyin": "带声调拼音",
  "english": "Concise English definition",
  "native_def": "{target_lang}母语释义" if is_second_lang else "",
  "sentence_zh": "中文例句",
  "sentence_py": "例句带声调拼音",
  "sentence_en": "Natural English translation",
  "sentence_native": "{target_lang}地道口语翻译" if is_second_lang else ""
}}"""

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional Chinese language teacher. Always respond with pure valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.85,
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
            return strip_lens_brackets(to_simplified(parsed)), None
    except Exception as e:
        return None, f"DeepSeek 调用失败: {e}"

# AI 多样化例句生成 (Qwen)
def generate_qwen_sentence(word, pinyin="", base_english="", target_lang="英语", difficulty="medium", avoid_sentences=None, scenario="", nonce=""):
    key = DASHSCOPE_KEY
    if not key:
        return None, "未配置百炼 API Key"

    avoid_sentences = avoid_sentences or []
    diff_key = difficulty if difficulty in DIFFICULTY_STANDARDS else "medium"
    diff_spec = DIFFICULTY_STANDARDS[diff_key]
    is_second_lang = (target_lang and target_lang != "英语")

    avoid_prompt = ""
    if avoid_sentences:
        avoid_json = json.dumps(avoid_sentences[:6], ensure_ascii=False)
        avoid_prompt = f"\n【重要排重指令】绝对不要重复或类似于以下已经出现过的例句：\n{avoid_json}\n"

    prompt = f"""你是一位拥有10年国际中文教学经验的权威名师（专攻成人 Preply 线上教学与新版 HSK 标准）。
请为外国学生学习生词【{word}】（拼音：{pinyin}，英文：{base_english}，学生母语：{target_lang}）设计一个高质量生活实用教学例句。

【难度档位】：【{diff_spec['label']}】
【句式难度标准】：{diff_spec['rule']}

【HSK 语法与生活实用铁律】：
1. 纯正地道：严禁任何机械套话（绝对不许出现“我在学习怎么用...”、“关于这个...”等假句子）。
2. 场景完全自由开放：根据生词【{word}】的真实本义与生活搭配展开，严禁千篇一律套用“去超市买咖啡/下班顺路”，严禁为了凑语法硬套把字句。
3. 必须包含生词【{word}】，并务必用【】包裹目标生词，形如【{word}】，严禁用近义词替换。
4. 英文和{target_lang}母语翻译必须口语化地道自然。
{avoid_prompt}
"""
    if is_second_lang:
        lang_prompt = f"""语言要求：
1. 英文翻译为必备基础项（english、sentence_en）。
2. 学生二翻母语为【{target_lang}】，必须同时提供二翻母语释义（native_def）与例句母语翻译（sentence_native）。"""
        json_schema = f"""{{
  "word": "{word}",
  "pinyin": "带声调拼音",
  "english": "Concise English definition (必备)",
  "native_def": "{target_lang}母语释义 (二翻)",
  "sentence_zh": "全新的地道生活中文例句",
  "sentence_py": "例句带声调拼音",
  "sentence_en": "Natural English translation (必备)",
  "sentence_native": "地道{target_lang}口语翻译 (二翻)"
}}"""
    else:
        lang_prompt = "学生母语或媒介语为【英语】。请输出简明地道的英文释义与例句英译。"
        json_schema = f"""{{
  "word": "{word}",
  "pinyin": "带声调拼音",
  "english": "Concise English definition",
  "native_def": "",
  "sentence_zh": "全新的地道生活中文例句",
  "sentence_py": "例句带声调拼音",
  "sentence_en": "Natural English translation",
  "sentence_native": ""
}}"""

    prompt += f"\n{lang_prompt}\n\n严格输出纯 JSON 格式：\n{json_schema}"

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen-turbo",
        "messages": [
            {"role": "system", "content": "You are a professional Chinese language teacher. Always respond with pure valid JSON. Never repeat previous example sentences."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.95,   # 2026-09-03 调高（小克）：老师报「重新生成是假功能」，同输入几乎出同样的句
        "max_tokens": 450
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
            return strip_lens_brackets(to_simplified(parsed)), None   # 2026-09-03（小克）：出口统一转简体，不靠模型自觉
    except Exception as e:
        return None, str(e)


# 多题型 AI 随堂操练生成 (包含选词填空、连词成句、情境问答、词语搭配)
# ── 2026-09-03 补回（小克，老师「先把引擎修好」）────────────────────────
# 09-03 00:33 那次整份重写把 Gemini 引擎删了，可前端下拉框还留着这个选项，
# 老师选了它实际跑的还是通义千问，界面上不说。这里按 K523 那版补回来。
# 走本机 127.0.0.1:1082 代理（跟原实现一致）。
def generate_gemini_sentence(word, pinyin="", base_english="", target_lang="英语",
                             difficulty="medium", avoid_sentences=None, scenario="", nonce=""):
    key = GEMINI_KEY
    if not key:
        return None, "未配置 GEMINI_API_KEY"

    avoid_sentences = avoid_sentences or []
    diff_key = difficulty if difficulty in DIFFICULTY_STANDARDS else "medium"
    diff_spec = DIFFICULTY_STANDARDS[diff_key]
    proxy_url = "http://127.0.0.1:1082"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )

    avoid_str = (f"绝对不要重复下列已出现过的例句：{json.dumps(avoid_sentences[:6], ensure_ascii=False)}。"
                 if avoid_sentences else "")
    is_second_lang = (target_lang and target_lang != "英语")
    native_fields = (f'''"native_def": "{target_lang}释义", "sentence_native": "{target_lang}例句翻译",'''
                     if is_second_lang else '''"native_def": "", "sentence_native": "",''')

    prompt = f"""你是一位专业的对外汉语教师。为外国学生学习生词【{word}】生成一个全新的教学词条。
参考拼音：{pinyin or "自动计算"}
参考释义：{base_english or "自动计算"}
【难度档位】：【{diff_spec['label']}】
【句式难度标准】：{diff_spec['rule']}
{avoid_str}
{SIMPLIFIED_RULE}
英文释义与例句英译为必备项。{"另需提供 " + target_lang + " 的释义与例句翻译。" if is_second_lang else ""}
只输出纯 JSON，不要代码块围栏：
{{"word": "{word}", "pinyin": "带声调拼音", "english": "简明英文释义",
  {native_fields}
  "sentence_zh": "地道生活化中文例句", "sentence_py": "例句带声调拼音",
  "sentence_en": "自然的英文翻译"}}"""

    # 2026-09-03 实测（小克）：gemini-2.5-flash 调用返回 404，Google 的错误原文是
    # "This model models/gemini-2.5-flash is no longer available to new users.
    #  Please update your code to use models/gemini-3.6-flash"。
    # ⚠️ ListModels 里**能查到**这个模型名，但**调不通**——能列出 ≠ 能调用，
    # 所以模型名只认实际 generateContent 跑通过的那个。gemini-3.6-flash 已实测可用。
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-3.6-flash:generateContent?key={key}")
    payload = {
        "contents": [{"parts": [{"text": prompt + (f"\n[变体标记 {nonce}]" if nonce else "")}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=30) as resp:   # 2026-09-03：走本机代理，12s 不够，实测要 20s+
            data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return strip_lens_brackets(to_simplified(json.loads(text))), None
    except Exception as e:
        return None, f"Gemini 调用失败: {e}"

def generate_deepseek_exercises(words_list, target_lang="英语", selected_types=None,
                                avoid_questions=None, nonce=""):
    key = DEEPSEEK_KEY
    if not key:
        return None, "未配置 DeepSeek API Key"

    selected_types = selected_types or ["cloze", "order", "dialogue", "collocation"]
    words_summary = []
    for item in words_list:
        w = item.get("word", "")
        py = item.get("pinyin", "")
        en = item.get("english", "")
        nat = item.get("native_def", "")
        desc = f"{w} ({py}) - {en}"
        if nat and target_lang != "英语":
            desc += f" / {nat}"
        words_summary.append(desc)

    words_text = "；".join(words_summary)
    words_only = [item.get("word", "") for item in words_list]
    avoid_questions = avoid_questions or []
    avoid_block = f"\n【排重指令】绝对不要重复下列已出过的题干：\n{json.dumps(avoid_questions[:8], ensure_ascii=False)}\n" if avoid_questions else ""
    is_second_lang = (target_lang and target_lang != "英语")
    lang_note = f"并在 translation 字段中提供【{target_lang}】题意翻译" if is_second_lang else "并在 translation 字段中提供英文题意翻译"

    type_instructions = []
    if "cloze" in selected_types:
        type_instructions.append("1. 选词填空 (type: 'cloze', typeName: '选词填空')：句子中留空“（____）”，提供 4 个选项，干扰项必须错误但具有教学辨析价值，唯一正确解。")
    if "order" in selected_types:
        type_instructions.append("2. 连词成句 (type: 'order', typeName: '连词成句')：打乱的 3-5 个中文词块数组 blocks，要求连成正确句子。")
    if "dialogue" in selected_types:
        type_instructions.append("3. 情境问答 (type: 'dialogue', typeName: '情境问答')：提供角色 A 的一句问话 context，要求学生用指定生词做地道回答，不要给 options。")
    if "collocation" in selected_types:
        type_instructions.append("4. 词语搭配 (type: 'collocation', typeName: '词语搭配')：4个选项必须每个都含该生词本身，仅1个为地道搭配。")

    type_prompt = "\n".join(type_instructions)
    prompt = f"""你是一位资深对外汉语一线名师。请根据学生本节课生词，设计 4 道不同题型的实用随堂练习题：

生词清单：{words_text}
候选词库：{json.dumps(words_only, ensure_ascii=False)}

题型要求：
{type_prompt}
{avoid_block}
{SIMPLIFIED_RULE}

设计铁律：
1. 每道题必须有唯一正确答案，干扰项语义或搭配上必须明确错误。
2. 场景多元，拒绝千篇一律套路。
3. 题目提供标准带调拼音，{lang_note}，拼音行与题意翻译绝对不许泄露答案。
4. explanation 给出老师看的教学简析。

只输出 JSON 格式：
{{
  "exercises": [
    {{
      "id": 1,
      "type": "cloze",
      "typeName": "选词填空",
      "question": "句子含（____）",
      "pinyin": "带调拼音，空格处写（____）",
      "translation": "题意翻译",
      "options": ["选项1", "选项2", "选项3", "选项4"],
      "answer": "正确选项",
      "explanation": "教学简析",
      "targetWord": "生词"
    }}
  ]
}}"""

    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional Chinese language teacher. Always respond with pure valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=16) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
            return to_simplified(parsed), None
    except Exception as e:
        return None, f"DeepSeek 出题失败: {e}"


def generate_ai_multi_exercises(words_list, target_lang="英语", selected_types=None,
                                avoid_questions=None, nonce=""):
    key = DASHSCOPE_KEY
    if not key:
        return None, "未配置 API Key"

    selected_types = selected_types or ["cloze", "order", "dialogue", "collocation"]

    words_summary = []
    for item in words_list:
        w = item.get("word", "")
        py = item.get("pinyin", "")
        en = item.get("english", "")
        nat = item.get("native_def", "")
        desc = f"{w} ({py}) - {en}"
        if nat and target_lang != "英语":
            desc += f" / {nat}"
        words_summary.append(desc)

    words_text = "；".join(words_summary)
    words_only = [item.get("word", "") for item in words_list]
    avoid_questions = avoid_questions or []
    avoid_block = ""
    if avoid_questions:
        avoid_block = ("\n【排重指令】下面这些题干上一轮已经出过，这次**必须全部换掉**，"
                       "换语境、换句式，不要只改几个字：\n"
                       + json.dumps(avoid_questions[:8], ensure_ascii=False) + "\n")
    if nonce:
        avoid_block += f"\n[本轮变体标记 {nonce}，据此换一批全新语境]\n"

    is_second_lang = (target_lang and target_lang != "英语")
    lang_note = f"并在 translation 字段中提供【{target_lang}】的题意翻译（附带简明英文）" if is_second_lang else "并在 translation 字段中提供英文题意翻译"

    type_instructions = []
    if "cloze" in selected_types:
        type_instructions.append("1. 选词填空 (type: 'cloze', typeName: '选词填空')：句子中留空“（____）”，提供 3-4 个选项。")
    if "order" in selected_types:
        type_instructions.append("2. 连词成句 (type: 'order', typeName: '连词成句')：给出打乱的 3-5 个中文词块数组 blocks，要求学生连成正确句子。")
    if "dialogue" in selected_types:
        type_instructions.append("3. 情境问答 (type: 'dialogue', typeName: '情境问答')：提供角色 A 的一句问话 context，要求学生用指定生词做出地道回答。")
    if "collocation" in selected_types:
        type_instructions.append("4. 词语搭配 (type: 'collocation', typeName: '词语搭配')：考查生词与哪些常用动词/名词搭配最自然。")

    type_prompt = "\n".join(type_instructions)

    prompt = f"""你是一位对外汉语一线教学名师。请根据学生本节课学习的生词清单，设计 4 道不同题型的实用随堂练习题：

生词清单：{words_text}
候选词库：{json.dumps(words_only, ensure_ascii=False)}

需要涵盖的题型：
{type_prompt}
{avoid_block}
{SIMPLIFIED_RULE}

设计原则：
1. 贴近真实口语交际，句子地道自然。
2. 题目提供标准带调拼音，{lang_note}。
3. 必须提供标准参考答案与教学简析。
4. 【搭配必须正确】离合词（帮忙、见面、聊天、结婚等）后面**不能直接带宾语**——
   写「帮我买点菜」「帮我一个忙」都行，但**不许写「帮忙买点菜」**。
   每道题落笔前先问一句：这个词这么用，中国人真的会这么说吗？不会就换一个说法。
5. 【空要挖在考点上】被挖掉的必须是这节课的生词本身，不能挖成一眼就能猜的虚词。
6. 【干扰项要像样】干扰项放进空里要在语法上说得通、意思上不对，才有区分度；
   不要放明显搭不上的词凑数。
7. 【每题语境不同】四道题不许用同一个场景反复套。
8. 【标点干净】不要用【】把词括起来；空格一律只写「（____）」，不要写成「【（____）】」。
9. 【题面必须自足】学生只看题面就要知道做什么：
   - 连词成句必须给出 blocks 词块数组，不能只写一句"请连成一句话"；
   - 情境问答必须给出 context（A 说的那句话），不能只写"请回答 A"；
   - 词语搭配必须在 targetWord 和 question 里写出考的是哪个生词。
   缺了这些字段的题**不要输出**，宁可少一道。
10. 【别在题面泄答案】连词成句的 pinyin 写正确整句的拼音没关系（界面会收进参考答案里），
    但 question 和 blocks 里不许出现完整答案句。
8. 严格输出纯 JSON 格式：
{{
  "exercises": [
    {{
      "id": 1,
      "type": "cloze",
      "typeName": "选词填空",
      "question": "中文题目（含 ____）",
      "pinyin": "带声调拼音",
      "translation": "外语翻译",
      "options": ["选项1", "选项2", "选项3"],
      "answer": "正确选项",
      "explanation": "简短解析"
    }},
    {{
      "id": 2,
      "type": "order",
      "typeName": "连词成句",
      "question": "请将下列词语按正确语序连成一句话：",
      "blocks": ["打乱词块1", "词块2", "词块3"],
      "pinyin": "整句拼音",
      "translation": "外语翻译",
      "answer": "完整的正确句子",
      "explanation": "语法结构简析"
    }},
    {{
      "id": 3,
      "type": "dialogue",
      "typeName": "情境问答",
      "context": "A: 对话上一句？",
      "question": "请用指定生词回答 A：",
      "pinyin": "拼音提示",
      "translation": "外语翻译",
      "answer": "地道参考回答",
      "explanation": "口语点拨"
    }},
    {{
      "id": 4,
      "type": "collocation",
      "typeName": "词语搭配",
      "targetWord": "本题考查的那个生词（必填，不能省）",
      "question": "「生词」后面接哪个说法最自然？（题面里要把生词写出来）",
      "options": ["搭配1", "搭配2", "搭配3"],
      "answer": "正确搭配",
      "explanation": "搭配规则"
    }}
  ]
}}"""

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen-turbo",
        "messages": [
            {"role": "system", "content": "You are a master Chinese teacher. Respond with pure JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.95,   # 2026-09-03 调高（小克）：老师报「重新生成是假功能」
        "max_tokens": 1000
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
            return strip_lens_brackets(to_simplified(parsed)), None   # 2026-09-03（小克）：出口统一转简体，不靠模型自觉
    except Exception as e:
        return None, str(e)


# 学生元数据管理 (多学生生词本持久化)
def _clean_student_name(name):
    """学生名进文件名前去掉路径分隔符和非法字符（和 save_lesson 同一套规则）。"""
    return re.sub(r'[\\/*?:"<>|]', "", str(name or "")).strip()


def _notebook_file(name):
    return HISTORY_DIR / f"{_clean_student_name(name)}_notebook.json"


def get_students_meta():
    """⚠️ 2026-09-06 改（小克，K623）：原来文件不存在时返回三个**编出来的**学生
    （Alex／塔米拉／Daniel），老师真用过的 Mike、victoria 反而看不到；而前端从来没调过
    POST /api/students，这个文件就从来没被建出来过——所以老师看到的永远是假名单。
    现在：文件没有就是空名单，真实名字由 discover_students() 从 history/ 里补。"""
    if STUDENTS_FILE.exists():
        try:
            with open(STUDENTS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return [x for x in d if isinstance(x, dict) and x.get("name")]
        except Exception:
            pass
    return []


_HISTORY_NAME_RE = re.compile(r"^(.+?)_(notebook|current|\d{4}-\d{2}-\d{2})\.json$")


def discover_students():
    """名单 = students_meta.json ∪ history/ 里出现过的名字。
    老师升级前存的生词（Alex_2026-09-03.json 这类）不能因为换了存法就看不见。"""
    students = get_students_meta()
    known = {s.get("name") for s in students}
    if HISTORY_DIR.exists():
        for f in sorted(HISTORY_DIR.glob("*.json")):
            m = _HISTORY_NAME_RE.match(f.name)
            if not m:
                continue
            name = m.group(1)
            if name and name not in known and name.lower() != "default":
                lang = ""
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        lang = (json.load(fh) or {}).get("target_lang", "") or ""
                except Exception:
                    pass
                students.append({"name": name, "lang": lang, "created": ""})
                known.add(name)
    return students


def load_notebook(name):
    """某个学生的整本生词本。没有 *_notebook.json 时，把旧的按日期存的
    <名>_<日期>.json 全部合并（每条打上 added=日期），一次性迁移。"""
    nb = _notebook_file(name)
    if nb.exists():
        try:
            with open(nb, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("vocab"), list):
                    return d
        except Exception:
            pass
    merged, seen, lang = [], set(), ""
    clean = _clean_student_name(name)
    for f in sorted(HISTORY_DIR.glob(f"{clean}_*.json")):
        m = _HISTORY_NAME_RE.match(f.name)
        if not m or m.group(1) != clean or m.group(2) in ("notebook", "current"):
            continue
        date = m.group(2)
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh) or {}
        except Exception:
            continue
        lang = d.get("target_lang") or lang
        for item in d.get("vocab") or []:
            if not isinstance(item, dict) or not item.get("word"):
                continue
            if item["word"] in seen:
                continue
            seen.add(item["word"])
            merged.append({**item, "added": item.get("added") or date})
    return {"student": name, "target_lang": lang, "vocab": merged}


def save_notebook(name, target_lang, vocab):
    nb = _notebook_file(name)
    data = {"student": name, "target_lang": target_lang or "", "vocab": vocab,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(nb, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return nb

def save_students_meta(students_list):
    try:
        with open(STUDENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(students_list, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存学生元数据失败: {e}")
        return False


ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}  # 2026-09-06 跟端口走（原写死 8765）

class AppRequestHandler(SimpleHTTPRequestHandler):
    timeout = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _origin_ok(self):
        """⚠️ 2026-09-03 加（小克，K525 第 1 条补漏）：只把 ACAO 收成白名单是不够的。
        CORS 是**浏览器**层面拦「能不能读响应」，服务端该干的活照干。
        实测：任意网页用 Content-Type: text/plain 发 POST（简单请求，浏览器不预检），
        请求照样打到这里、文件照样写进学生档案目录——攻击方读不到响应，但**写已经发生了**。
        所以带了 Origin 又不在白名单里的，一律拒。
        没有 Origin 头的（curl、本机脚本、app 自己）放行，不影响正常使用。"""
        origin = self.headers.get("Origin")
        if origin is None or origin in ALLOWED_ORIGINS:
            return True
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"403 Forbidden: cross-origin write rejected")
        return False

    def _host_ok(self):
        host = self.headers.get("Host", "").strip()
        if host in ALLOWED_HOSTS:
            return True
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"403 Forbidden: Invalid Host header")
        return False

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def send_json_resp(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def list_directory(self, path):
        self.send_error(404, "No permission to list directory")
        return None

    def do_GET(self):
        if not self._host_ok():
            return

        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/api/status":
            status = {
                "ok": True,
                "app_name": "词来",
                # ⚠️ 2026-09-03 修（小克）：这里原来写死 "dict_count": 18439，是个**编出来的数**——
                # 后端早就不载词库了（/api/lookup 已删，查词全在前端 dict_data.js 里做），
                # 真实词条数是 197930，写 18439 既不对也没人读。改成如实说"后端不管词库"。
                "dict_source": "frontend",
                # 2026-09-03 加（小克，K525 第 12 条）：前端下拉框有 4 个引擎，
                # 后端**只实现了 qwen 一个**（没有 generate_gemini_sentence / generate_google_v3_entry）。
                # 老师选 Gemini 或 Google v3，实际跑的还是通义千问，界面上不说。
                # 这里如实报出真正实现了的引擎，前端照着把没实现的置灰。
                # 以后谁把 Gemini/v3 加回来，就把名字加进这个列表，选项自动亮。
                # 2026-09-03 改（小克）：不再写死。qwen/gemini 有 key 才算，google_v3 要凭据文件。
                "engines": ([e for e, ok in (("deepseek", bool(DEEPSEEK_KEY)),
                                             ("qwen", bool(DASHSCOPE_KEY)),
                                             ("gemini", bool(GEMINI_KEY)),
                                             ("google_v3", bool(GCP_CREDENTIAL_PATH))) if ok]
                            + ["offline"]),
                "has_deepseek": bool(DEEPSEEK_KEY),
                "has_dashscope": bool(DASHSCOPE_KEY),
                "has_gemini": bool(GEMINI_KEY),
                "has_gcp_v3": bool(GCP_CREDENTIAL_PATH),
                "has_neural_tts": True,
                "port": PORT
            }
            self.send_json_resp(200, status)
            return

        # 获取所有学生名单与生词本元数据
        if parsed_url.path == "/api/students":
            students = discover_students()
            for s in students:
                try:
                    s["vocab_count"] = len(load_notebook(s.get("name", "")).get("vocab", []))
                except Exception:
                    s["vocab_count"] = 0
            self.send_json_resp(200, {"ok": True, "students": students})
            return

        # 2026-09-06 加（小克，K623）：某个学生的整本生词本（按学生分本，不再按日期分）
        if parsed_url.path == "/api/notebook":
            qs = urllib.parse.parse_qs(parsed_url.query)
            name = (qs.get("student", [""])[0] or "").strip()
            if not name:
                self.send_json_resp(400, {"ok": False, "error": "student required"})
                return
            try:
                self.send_json_resp(200, {"ok": True, "notebook": load_notebook(name)})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        # 获取语音文件或动态请求TTS
        if parsed_url.path == "/api/tts":
            params = urllib.parse.parse_qs(parsed_url.query)
            fname = params.get("file", [""])[0].strip()
            if fname and fname.endswith(".wav"):
                fpath = AUDIO_CACHE_DIR / fname
                if fpath.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self._cors()
                    self.end_headers()
                    with open(fpath, "rb") as f:
                        self.wfile.write(f.read())
                    return
                else:
                    self.send_json_resp(404, {"ok": False, "error": "file not found"})
                    return

            text = params.get("text", [""])[0].strip()
            speaker = params.get("speaker", ["zh_female_shuangkuaisisi_uranus_bigtts"])[0]
            fpath, mime, err = generate_tts_audio(text, speaker)
            if fpath and os.path.exists(fpath):
                self.send_response(200)
                self.send_header("Content-Type", mime or "audio/wav")
                self._cors()
                self.end_headers()
                with open(fpath, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_json_resp(500, {"ok": False, "error": err or "tts failed"})
                return

        # 静态文件访问控制：只允许白名单内的前端静态资源，严禁访问源码、数据和脚本
        req_path = parsed_url.path
        if req_path in ("/", ""):
            req_path = "/index.html"
        clean_path = req_path.lstrip("/")
        allowed_files = {"index.html", "dict_data.js"}
        if clean_path in allowed_files or clean_path.startswith("assets/"):
            target_file = (BASE_DIR / clean_path).resolve()
            if str(target_file).startswith(str(BASE_DIR.resolve())) and target_file.is_file():
                return super().do_GET()
        self.send_error(404, "File not found")
        return

    def do_POST(self):
        if not self._host_ok():
            return
        if not self._origin_ok():
            return
        parsed_url = urllib.parse.urlparse(self.path)

        # 保存/新增学生档案
        if parsed_url.path == "/api/students":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                new_student = data.get("student", {})
                name = new_student.get("name", "").strip()
                if not name:
                    self.send_json_resp(400, {"ok": False, "error": "student name required"})
                    return

                students = get_students_meta()
                found = False
                for i, s in enumerate(students):
                    if s.get("name") == name:
                        students[i] = new_student
                        found = True
                        break
                if not found:
                    students.append(new_student)
                save_students_meta(students)
                self.send_json_resp(200, {"ok": True, "students": students})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        # 删除学生档案
        if parsed_url.path == "/api/delete_student":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                name = data.get("name", "").strip()
                if not name:
                    self.send_json_resp(400, {"ok": False, "error": "student name required"})
                    return
                # 2026-09-06 改（小克，K623）：原来有「至少保留一名」的闸——名单本来就是假的，
                # 闸也就永远拦着。老师要能删就得真能删；删到零个界面会提示先加学生。
                # 文件不硬删，挪进 history/废纸篓/<时间>/ ，误删还能捞回来。
                students = [s for s in discover_students() if s.get("name") != name]
                save_students_meta(students)
                clean = _clean_student_name(name)
                moved = []
                if clean:
                    trash = HISTORY_DIR / "废纸篓" / time.strftime("%Y%m%d-%H%M%S")
                    for f in HISTORY_DIR.glob(f"{clean}_*.json"):
                        m = _HISTORY_NAME_RE.match(f.name)
                        if not m or m.group(1) != clean:
                            continue
                        trash.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(trash / f.name))
                        moved.append(f.name)
                self.send_json_resp(200, {"ok": True, "students": students, "moved": moved})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        # AI 智能生成全新例句
        # 保存自定义 Key (方便外部下载者一键生效)
        if parsed_url.path == "/api/save_keys":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                global DASHSCOPE_KEY, GEMINI_KEY, DEEPSEEK_KEY
                if data.get("deepseek_key"):
                    DEEPSEEK_KEY = data.get("deepseek_key").strip()
                    key_file = Path.home() / ".config" / "gamekit" / "deepseek.env"
                    key_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(key_file, "w", encoding="utf-8") as f:
                        f.write(f"DEEPSEEK_API_KEY={DEEPSEEK_KEY}\n")
                    key_file.chmod(0o600)
                if data.get("dashscope_key"):
                    DASHSCOPE_KEY = data.get("dashscope_key").strip()
                if data.get("gemini_key"):
                    GEMINI_KEY = data.get("gemini_key").strip()
                self.send_json_resp(200, {"ok": True})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        if parsed_url.path == "/api/generate_sentence":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                word = data.get("word", "").strip()
                pinyin = data.get("pinyin", "").strip()
                base_english = data.get("english", "").strip()
                target_lang = data.get("target_lang", "英语").strip() or "英语"
                difficulty = data.get("difficulty", "medium")
                engine = data.get("engine", "deepseek" if DEEPSEEK_KEY else "qwen")
                avoid_sentences = data.get("avoid_sentences", [])
                scenario = data.get("scenario", "").strip()

                nonce = str(data.get("nonce", "") or "")

                res, err, used = None, None, None
                if engine == "deepseek":
                    res, err = generate_deepseek_sentence(word, pinyin, base_english, target_lang,
                                                          difficulty=difficulty, avoid_sentences=avoid_sentences, nonce=nonce)
                    used = "deepseek"
                    if not res and DASHSCOPE_KEY:
                        res2, err2 = generate_qwen_sentence(word, pinyin, base_english, target_lang,
                                                            difficulty=difficulty, avoid_sentences=avoid_sentences, scenario=scenario, nonce=nonce)
                        if res2:
                            res, used = res2, "qwen"
                            err = f"DeepSeek 不可用，已自动切回通义千问"
                elif engine == "gemini":
                    res, err = generate_gemini_sentence(word, pinyin, base_english, target_lang,
                                                        difficulty=difficulty, avoid_sentences=avoid_sentences, scenario=scenario, nonce=nonce)
                    used = "gemini"
                    if not res:   # Gemini 挂了退回 qwen，但要**如实告诉老师退了**
                        res2, err2 = generate_qwen_sentence(word, pinyin, base_english, target_lang,
                                                            difficulty=difficulty, avoid_sentences=avoid_sentences, scenario=scenario, nonce=nonce)
                        if res2:
                            res, used = res2, "qwen"
                            err = f"Gemini 不可用（{err}），已自动改用通义千问"
                elif engine == "google_v3":
                    # 本机没有 Google Cloud 凭据，这条路走不通，不假装能跑。
                    res2, err2 = generate_qwen_sentence(word, pinyin, base_english, target_lang,
                                                        difficulty=difficulty, avoid_sentences=avoid_sentences, scenario=scenario, nonce=nonce)
                    res, used = res2, "qwen"
                    err = "Google Cloud Translation 未配置凭据，已自动改用通义千问" if res2 else err2
                else:
                    res, err = generate_qwen_sentence(word, pinyin, base_english, target_lang,
                                                      difficulty=difficulty, avoid_sentences=avoid_sentences, scenario=scenario, nonce=nonce)
                    used = "qwen"

                if res:
                    self.send_json_resp(200, {"ok": True, "data": res,
                                              "engine_used": used, "notice": err or ""})
                else:
                    self.send_json_resp(200, {"ok": False, "error": err or "例句生成失败"})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        # AI 随堂多题型操练生成
        if parsed_url.path == "/api/generate_exercises":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                words = data.get("words", [])
                target_lang = data.get("target_lang", "英语").strip() or "英语"
                selected_types = data.get("types", None)
                # 2026-09-03 加（小克，老师「重新生成是假功能」）：把上一轮题干和随机标记传下去，
                # 否则同输入让模型出同样的题，点「重新出一套」看着像没反应。
                avoid_questions = data.get("avoid_questions", []) or []
                nonce = str(data.get("nonce", "") or "")
                engine = data.get("engine", "deepseek" if DEEPSEEK_KEY else "qwen")

                if engine == "deepseek" and DEEPSEEK_KEY:
                    res, err = generate_deepseek_exercises(words, target_lang, selected_types,
                                                           avoid_questions, nonce)
                    if not res and DASHSCOPE_KEY:
                        res, err = generate_ai_multi_exercises(words, target_lang, selected_types,
                                                               avoid_questions, nonce)
                else:
                    res, err = generate_ai_multi_exercises(words, target_lang, selected_types,
                                                           avoid_questions, nonce)

                if res:
                    self.send_json_resp(200, {"ok": True, "data": res})
                else:
                    self.send_json_resp(200, {"ok": False, "error": err or "出题失败"})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        # 2026-09-06 加（小克，K623）：前端每次改动整本回写。
        if parsed_url.path == "/api/notebook":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                name = (data.get("student") or "").strip()
                vocab = data.get("vocab")
                if not name or not isinstance(vocab, list):
                    self.send_json_resp(400, {"ok": False, "error": "student and vocab[] required"})
                    return
                path = save_notebook(name, data.get("target_lang", ""), vocab)
                self.send_json_resp(200, {"ok": True, "path": str(path), "count": len(vocab)})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        if parsed_url.path == "/api/save_lesson":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                student = data.get("student", "default").strip() or "default"
                date_str = data.get("date", "unknown").strip()
                clean_name = re.sub(r'[\/*?:"<>|]', "", f"{student}_{date_str}")
                file_path = HISTORY_DIR / f"{clean_name}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                # 同时备份一份为该学生当前最新生词本
                curr_file = HISTORY_DIR / f"{student}_current.json"
                with open(curr_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                self.send_json_resp(200, {"ok": True, "path": str(file_path)})
            except Exception as e:
                self.send_json_resp(500, {"ok": False, "error": str(e)})
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        if not self._host_ok():
            return
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server():
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, AppRequestHandler)
    httpd.daemon_threads = True
    print(f"=====================================================")
    print(f"  「词来」老师教学工作台服务已启动 (双端支持)")
    print(f"  浏览器与小程序调试: http://127.0.0.1:{PORT}")
    print(f"  超拟人神经网络语音: 爽快思思 / 微软晓晓")
    print(f"  多学生独立建本系统: 已激活")
    print(f"  多题型 AI 出题引擎: 选词填空 / 连词成句 / 情境问答 / 词语搭配")
    print(f"=====================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
