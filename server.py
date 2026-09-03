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

PORT = 8765
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

# AI 多样化例句生成 (Qwen)
def generate_qwen_sentence(word, pinyin="", base_english="", target_lang="英语", level="初中级", avoid_sentences=None, scenario=""):
    key = DASHSCOPE_KEY
    if not key:
        return None, "未配置百炼 API Key"

    avoid_sentences = avoid_sentences or []
    is_second_lang = (target_lang and target_lang != "英语")

    avoid_prompt = ""
    if avoid_sentences:
        avoid_json = json.dumps(avoid_sentences[:6], ensure_ascii=False)
        avoid_prompt = f"\n【重要排重指令】绝对不要重复或类似于以下已经出现过的例句：\n{avoid_json}\n"

    scenario_prompt = f"【指定教学语境】：请重点在【{scenario}】场景下构造例句。" if scenario else "【情境要求】：请生成富有生活气息、真实自然的口语例句。"

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

    prompt = f"""你是一位拥有10年国际中文教学经验的权威名师（专攻成人 Preply 线上教学与新版 HSK 标准）。
请为外国学生学习生词【{word}】（拼音：{pinyin}，英文：{base_english}，学生母语：{target_lang}，目标水平：{level}）设计一个符合 HSK 真实教学标准的高质量生活例句。

【HSK 语法与生活实用铁律】：
1. 严禁任何机械套话（绝对不许出现“我在学习怎么用...”、“关于这个...”、“老师提醒我们...”等假句子）。
2. 必须是日常生活真实交际场景（如：买咖啡/超市购物/下班顺路/交房租/聚会/租房/出差/问路/叫外卖）。
3. 必须符合 HSK 常用核心语法句型结构：
   - 包含 HSK 规范的状语位置（副词放在谓语动词之前）；
   - 常用把字句（把...收拾干净）、连动句、结果补语或时态复合句；
   - 句子长度适中（14~20字），生词用【】包裹。
4. 英文和{target_lang}母语翻译必须口语化地道自然，绝不能机翻生硬。
{avoid_prompt}
{lang_prompt}

严格输出纯 JSON 格式：
{json_schema}"""

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
        "temperature": 0.88,
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
            return parsed, None
    except Exception as e:
        return None, str(e)


# 多题型 AI 随堂操练生成 (包含选词填空、连词成句、情境问答、词语搭配)
def generate_ai_multi_exercises(words_list, target_lang="英语", selected_types=None):
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

设计原则：
1. 贴近真实口语交际，句子地道自然。
2. 题目提供标准带调拼音，{lang_note}。
3. 必须提供标准参考答案与教学简析。
4. 严格输出纯 JSON 格式：
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
      "question": "下列哪个词与指定生词搭配最自然？",
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
        "temperature": 0.78,
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
            return parsed, None
    except Exception as e:
        return None, str(e)


# 学生元数据管理 (多学生生词本持久化)
def get_students_meta():
    if STUDENTS_FILE.exists():
        try:
            with open(STUDENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [
        {"name": "Alex", "lang": "英语", "level": "初级", "note": "Preply 成人"},
        {"name": "塔米拉", "lang": "俄语", "level": "中级", "note": "口语与HSKK"},
        {"name": "Daniel", "lang": "西班牙语", "level": "初中级", "note": "日常会话"}
    ]

def save_students_meta(students_list):
    try:
        with open(STUDENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(students_list, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存学生元数据失败: {e}")
        return False


ALLOWED_ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765"}
ALLOWED_HOSTS = {"127.0.0.1:8765", "localhost:8765"}

class AppRequestHandler(SimpleHTTPRequestHandler):
    timeout = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

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
                "dict_count": 18439,
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
            students = get_students_meta()
            for s in students:
                name = s.get("name", "")
                s_file = HISTORY_DIR / f"{name}_current.json"
                if s_file.exists():
                    try:
                        with open(s_file, "r", encoding="utf-8") as f:
                            d = json.load(f)
                            s["vocab_count"] = len(d.get("vocab", []))
                    except Exception:
                        s["vocab_count"] = 0
                else:
                    s["vocab_count"] = 0

            self.send_json_resp(200, {"ok": True, "students": students})
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

        # AI 智能生成全新例句
        if parsed_url.path == "/api/generate_sentence":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                word = data.get("word", "").strip()
                pinyin = data.get("pinyin", "").strip()
                base_english = data.get("english", "").strip()
                target_lang = data.get("target_lang", "英语").strip() or "英语"
                level = data.get("level", "初中级")
                engine = data.get("engine", "qwen")
                avoid_sentences = data.get("avoid_sentences", [])
                scenario = data.get("scenario", "").strip()

                res, err = generate_qwen_sentence(word, pinyin, base_english, target_lang, level, avoid_sentences, scenario)

                if res:
                    self.send_json_resp(200, {"ok": True, "data": res, "engine_used": "qwen"})
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
                res, err = generate_ai_multi_exercises(words, target_lang, selected_types)

                if res:
                    self.send_json_resp(200, {"ok": True, "data": res})
                else:
                    self.send_json_resp(200, {"ok": False, "error": err or "出题失败"})
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
