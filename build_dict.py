import re
import json
import os
import pypinyin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(os.path.dirname(BASE_DIR), '.cache')
CEDICT_PATH = os.path.join(CACHE_DIR, 'cedict.txt')
OUTPUT_JS = os.path.join(BASE_DIR, 'dict_data.js')
OUTPUT_FULL_JSON = os.path.join(BASE_DIR, 'data', 'cedict_full.json')

pinyin_tone_marks = {
    'a': ['ā', 'á', 'ǎ', 'à', 'a'],
    'e': ['ē', 'é', 'ě', 'è', 'e'],
    'i': ['ī', 'í', 'ǐ', 'ì', 'i'],
    'o': ['ō', 'ó', 'ǒ', 'ò', 'o'],
    'u': ['ū', 'ú', 'ǔ', 'ù', 'u'],
    'v': ['ǖ', 'ǘ', 'ǚ', 'ǜ', 'ü'],
    'u:': ['ǖ', 'ǘ', 'ǚ', 'ǜ', 'ü'],
}

def num_to_tone(pinyin_str):
    def replace_syllable(match):
        syl = match.group(1).lower()
        tone = int(match.group(2))
        syl = syl.replace('u:', 'v')
        if tone == 5:
            return syl.replace('v', 'ü')
        t_idx = tone - 1
        
        # 1. 'a' or 'e'
        for v in ['a', 'e']:
            if v in syl:
                return syl.replace(v, pinyin_tone_marks[v][t_idx]).replace('v', 'ü')
        # 2. 'ou'
        if 'ou' in syl:
            return syl.replace('o', pinyin_tone_marks['o'][t_idx]).replace('v', 'ü')
        # 3. 'iu' -> on u; 'ui' -> on i
        if 'iu' in syl:
            return syl.replace('u', pinyin_tone_marks['u'][t_idx]).replace('v', 'ü')
        if 'ui' in syl:
            return syl.replace('i', pinyin_tone_marks['i'][t_idx]).replace('v', 'ü')
        # 4. other single vowel
        for v in ['o', 'u', 'i', 'v']:
            if v in syl:
                return syl.replace(v, pinyin_tone_marks[v][t_idx]).replace('v', 'ü')
        return syl.replace('v', 'ü')
    return re.sub(r'([a-zA-Z:]+)([1-5])', replace_syllable, pinyin_str)

def main():
    print("Building full dictionary data...")
    # 1. Load HSK 2.0 & 3.0 words
    hsk_map = {}
    hsk2_path = '/Users/a1/Claude/repos/开源资料/hsk20_大纲词汇_1-6级.json'
    if os.path.exists(hsk2_path):
        with open(hsk2_path) as f:
            d2 = json.load(f)
            for lvl, words in d2.items():
                for w in words:
                    hsk_map[w] = int(lvl)

    hsk3_path = '/Users/a1/Claude/repos/开源资料/hsk30/wordlist.txt'
    if os.path.exists(hsk3_path):
        current_lvl = 1
        with open(hsk3_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '级词汇表' in line:
                    m = re.search(r'([一二三四五六七八九十]+)级', line)
                    chinese_num = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
                    if m and m.group(1) in chinese_num:
                        current_lvl = chinese_num[m.group(1)]
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    raw_w = parts[1].split('｜')[0].split('（')[0]
                    if raw_w and raw_w not in hsk_map:
                        hsk_map[raw_w] = current_lvl

    print(f"Loaded {len(hsk_map)} HSK words.")

    # 2. Build single-character pinyin map for Unicode Chinese characters
    char_pinyin = {}
    for code in range(0x4e00, 0x9fa6):
        ch = chr(code)
        py = pypinyin.pinyin(ch, style=pypinyin.Style.TONE)[0][0]
        if py != ch:
            char_pinyin[ch] = py

    # 3. Parse CC-CEDICT
    all_dict = {}
    
    with open(CEDICT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^(\S+)\s+(\S+)\s+\[(.*?)\]\s+/(.*)/$', line)
            if not m:
                continue
            trad, simp, pinyin, defs = m.groups()
            defs_clean = [d for d in defs.split('/') if d and not d.startswith('surname ')]
            if not defs_clean:
                defs_clean = [d for d in defs.split('/') if d]
            
            pinyin_marked = num_to_tone(pinyin)
            def_str = '; '.join(defs_clean[:2])
            hsk_lvl = hsk_map.get(simp, 0)

            # Record simplified
            if simp not in all_dict:
                all_dict[simp] = [pinyin_marked, def_str, hsk_lvl]
            elif hsk_lvl > 0 and all_dict[simp][2] == 0:
                all_dict[simp][2] = hsk_lvl

            # Record traditional if different
            if trad != simp and trad not in all_dict:
                all_dict[trad] = [pinyin_marked, def_str, hsk_lvl]

    print(f"Total compiled dictionary entries: {len(all_dict)}")

    # 4. Save full JSON for local server
    os.makedirs(os.path.dirname(OUTPUT_FULL_JSON), exist_ok=True)
    with open(OUTPUT_FULL_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_dict, f, ensure_ascii=False)
    print(f"Saved full CEDICT to {OUTPUT_FULL_JSON}")

    # 5. Build curated example sentences for common words
    curated_examples = {}
    tt_hsk1 = '/Users/a1/Claude/repos/tone-trainer/data-source/hsk1_deck.json'
    if os.path.exists(tt_hsk1):
        with open(tt_hsk1) as f:
            d = json.load(f)
            for s in d.get('sents', []):
                zh = s.get('zh', '')
                en = s.get('en', '')
                zh_clean = re.sub(r'[，。！？、]', '', zh)
                for w in all_dict:
                    if len(w) >= 2 and w in zh_clean and w not in curated_examples:
                        py_sent = ' '.join(pypinyin.lazy_pinyin(zh, style=pypinyin.Style.TONE))
                        curated_examples[w] = {
                            'zh': zh,
                            'py': py_sent,
                            'en': en
                        }

    print(f"Matched {len(curated_examples)} curated sentences from HSK tone trainer.")

    # 6. Save dict_data.js
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write("/* Preply 生词与闪卡助手 · 核心离线词库 (全量 12 万条 CC-CEDICT + HSK) */\n")
        f.write("window.CHAR_PINYIN = ")
        json.dump(char_pinyin, f, ensure_ascii=False)
        f.write(";\n\n")
        f.write("window.DICT_DATA = ")
        json.dump(all_dict, f, ensure_ascii=False)
        f.write(";\n\n")
        f.write("window.CURATED_EXAMPLES = ")
        json.dump(curated_examples, f, ensure_ascii=False)
        f.write(";\n")
        f.write("console.log('✓ 离线词库就绪，收录 ' + Object.keys(window.DICT_DATA).length + ' 词');\n")

    size_mb = os.path.getsize(OUTPUT_JS) / (1024 * 1024)
    print(f"Successfully generated {OUTPUT_JS} ({size_mb:.2f} MB)")

if __name__ == '__main__':
    main()
