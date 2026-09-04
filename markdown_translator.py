#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
沉浸式翻译器（支持批处理、全局语境与失败重试）
- 自然段落用 <PARAxxxxx>...</PARAxxxxx> 包裹
- 只翻译标签内的文本，标签本身必须原样保留
- 翻译失败后，用 <RETRYxxxxx> 重新包裹并重试一次
- 最终仍失败则在原文下方插入【失败原因 + 需要手动翻译manual translate】
"""

import re
import json
import time
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from tqdm import tqdm
from llama_cpp import Llama

try:
    import ahocorasick
    AHOCORASICK_AVAILABLE = True
except ImportError:
    AHOCORASICK_AVAILABLE = False

# OpenAI 异常类（仅 API 模式需要）
try:
    from openai import APITimeoutError, APIStatusError, APIConnectionError
except ImportError:
    # 若未安装 openai，定义占位异常（实际不会触发）
    class APITimeoutError(Exception): pass
    class APIStatusError(Exception): pass
    class APIConnectionError(Exception): pass


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        return len(encoding.encode(text))
    except (ImportError, Exception):
        return len(text) // 2 + 1


class HyMT2Translator:
    def __init__(self, model_path: str = None, n_gpu_layers: int = -1, n_ctx: int = 4096,
                 temperature: float = 0.7, top_p: float = 0.6, top_k: int = 20,
                 repeat_penalty: float = 1.05, max_tokens: int = 4096,
                 glossary_dict: dict = None, target_style: str = "", background_text: str = "",
                 use_api: bool = False,
                 api_key: str = None,
                 api_base: str = "https://api.deepseek.com",
                 api_model: str = "deepseek-v4-pro",
                 api_timeout: int = 60,
                 extra_body_str: str = ""):
        self.use_api = use_api
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.extra_body_str = extra_body_str
        self.glossary_dict = glossary_dict or {}
        self.target_style = target_style
        self.background_text = background_text
        self._build_automaton()

        if self.use_api:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=api_key,
                base_url=api_base,
                timeout=api_timeout,
            )
            self.api_model = api_model
        else:
            self.llm = Llama(
                model_path=model_path,
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                verbose=False,
            )
            self.default_params = {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repeat_penalty": repeat_penalty,
                "max_tokens": max_tokens,
            }

    def _build_automaton(self):
        if not self.glossary_dict:
            self.automaton = None
            return
        if AHOCORASICK_AVAILABLE:
            self.automaton = ahocorasick.Automaton()
            for src, tgt in self.glossary_dict.items():
                self.automaton.add_word(src, (src, tgt))
            self.automaton.make_automaton()
        else:
            self.automaton = None
            print("⚠️ pyahocorasick 未安装，使用简单匹配（性能较低）")

    def _match_terms(self, text: str) -> str:
        if not self.glossary_dict:
            return ""
        matched_terms = {}
        if self.automaton is not None:
            for _, (src, tgt) in self.automaton.iter(text):
                matched_terms[src] = tgt
        else:
            for src, tgt in self.glossary_dict.items():
                if src in text:
                    matched_terms[src] = tgt
        if not matched_terms:
            return ""
        terms_str = "\n".join([f"{src} 翻译成 {tgt}" for src, tgt in matched_terms.items()])
        return "参考下面的翻译：\n" + terms_str + "\n"

    def _build_prompt(self, text: str, target_lang: str, global_context: str = "") -> str:
        glossary_part = self._match_terms(text)

        html_instruction = (
            "【绝对指令】文本中包含以下格式的特殊标签：\n"
            "- <IMAGEXXXXX/>、<MATHXXXXX/>、<TABLEXXXXX/>、<CODEXXXXX/>、<LINKXXXXX/> 等（XXXXX 为十六进制数字）\n"
            "- <PARAXXXXX>...</PARAXXXXX> 和 <RETRYXXXXX>...</RETRYXXXXX> 是段落标记，只翻译标签之间的纯文本，标签本身必须原样保留。\n"
            "- 必须严格保持原有标签的层级嵌套、缩进和属性。\n"
        )

        if global_context:
            if glossary_part:
                prompt = f"全局语境摘要：\n{global_context}\n\n{glossary_part}\n{html_instruction}\n将以下文本翻译为 {target_lang}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
            else:
                prompt = f"全局语境摘要：\n{global_context}\n\n{html_instruction}\n将以下文本翻译为 {target_lang}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
        else:
            style_part = f"，注意翻译的风格要严格符合【{self.target_style}】" if self.target_style.strip() else ""
            bg_part = f"背景信息：{self.background_text}\n\n" if self.background_text.strip() else ""
            if glossary_part:
                prompt = f"{glossary_part}{bg_part}{html_instruction}\n将以下文本翻译为 {target_lang}{style_part}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
            else:
                prompt = f"{bg_part}{html_instruction}\n将以下文本翻译为 {target_lang}{style_part}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"

        return prompt

    def translate(self, text: str, target_lang: str = "中文") -> str:
        """简单翻译接口，失败返回原文"""
        if not text or not text.strip():
            return text
        prompt = self._build_prompt(text, target_lang)
        translated, error_msg, _, _ = self._call_translate(prompt, target_lang)
        if translated is None:
            print(f"⚠️ 翻译失败，返回原文。错误: {error_msg}")
            return text
        return translated

    def _call_translate(self, prompt: str, target_lang: str) -> Tuple[Optional[str], str, int, int]:
        """
        带指数退避重试、细化超时和错误分类的翻译调用
        返回: (译文或None, 错误信息, 输入token数, 输出token数)
        """
        max_retries = 5
        base_delay = 1
        max_delay = 60
        retryable_status_codes = {429, 500, 502, 503, 504}

        last_error = ""
        for attempt in range(max_retries):
            try:
                if self.use_api:
                    timeout_config = (10.0, 120.0)  # (connect, read) 超时
                    extra_body = None
                    if self.extra_body_str.strip():
                        try:
                            extra_body = json.loads(self.extra_body_str)
                        except json.JSONDecodeError:
                            print(f"⚠️ 额外参数JSON格式错误，已忽略: {self.extra_body_str}")

                    response = self.client.chat.completions.create(
                        model=self.api_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.temperature,
                        top_p=self.top_p,
                        max_tokens=self.max_tokens,
                        stream=False,
                        extra_body=extra_body,
                        timeout=timeout_config,
                    )
                    translated = response.choices[0].message.content.strip()
                    usage = response.usage
                    prompt_tokens = usage.prompt_tokens if usage else estimate_tokens(prompt)
                    completion_tokens = usage.completion_tokens if usage else estimate_tokens(translated)
                    if translated:
                        print(f"[Token] 输入: {prompt_tokens}, 输出: {completion_tokens}, 总计: {prompt_tokens + completion_tokens}")
                        return translated, "", prompt_tokens, completion_tokens
                    else:
                        last_error = "返回空内容"
                        if attempt == max_retries - 1:
                            break
                else:
                    # 本地模型（无网络，简单重试一次）
                    response = self.llm.create_chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        **self.default_params
                    )
                    translated = response["choices"][0]["message"]["content"].strip()
                    prompt_tokens = estimate_tokens(prompt)
                    completion_tokens = estimate_tokens(translated)
                    if translated:
                        return translated, "", prompt_tokens, completion_tokens
                    else:
                        last_error = "本地模型返回空内容"
                        return None, last_error, 0, 0

            except APITimeoutError as e:
                last_error = f"请求超时: {str(e)}"
                if attempt == max_retries - 1:
                    break
            except APIStatusError as e:
                status_code = e.status_code
                last_error = f"API 状态错误 {status_code}: {e.response.text}"
                if status_code in retryable_status_codes and attempt < max_retries - 1:
                    pass  # 可重试
                else:
                    break
            except APIConnectionError as e:
                last_error = f"网络连接错误: {str(e)}"
                if attempt == max_retries - 1:
                    break
            except Exception as e:
                last_error = f"未知异常: {str(e)}"
                if attempt == max_retries - 1:
                    break

            # 计算退避时间（带抖动）
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.2)
                sleep_time = delay + jitter
                print(f"⏳ 重试 {attempt+1}/{max_retries-1}，等待 {sleep_time:.2f} 秒后重试...")
                time.sleep(sleep_time)

        print(f"❌ 翻译失败，最后错误: {last_error}")
        return None, last_error, 0, 0

    def analyze_titles(self, titles: List[str]) -> dict:
        """
        分析标题生成全局语境，失败返回默认值。
        使用指数退避重试，仅对可恢复错误重试。
        """
        if not titles:
            return {"topic": "未知", "domain": "通用", "style": "通用", "audience": "通用读者"}

        prompt = (
            "以下是一篇文档的标题大纲，请根据这些标题推断该文档的主题、专业领域、写作风格和目标读者。"
            "请以 JSON 格式返回，包含字段：topic, domain, style, audience。简要回答。\n\n"
            "标题列表：\n" + "\n".join(f"- {t}" for t in titles)
        )
        title_max_tokens = int(max(500, self.max_tokens * 0.15))

        max_retries = 5
        base_delay = 1
        max_delay = 60
        retryable_status_codes = {429, 500, 502, 503, 504}
        last_error = ""

        for attempt in range(max_retries):
            try:
                if self.use_api:
                    # 使用较宽松的超时
                    response = self.client.chat.completions.create(
                        model=self.api_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=title_max_tokens,
                        timeout=(10.0, 60.0),  # 连接10s，读取60s
                    )
                    content = response.choices[0].message.content.strip()
                else:
                    response = self.llm.create_chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=title_max_tokens,
                    )
                    content = response["choices"][0]["message"]["content"].strip()

                # 解析 JSON
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
                else:
                    start = content.find('{')
                    end = content.rfind('}') + 1
                    if start != -1 and end != -1:
                        content = content[start:end]
                result = json.loads(content)
                return result

            except APITimeoutError as e:
                last_error = f"请求超时: {str(e)}"
                if attempt == max_retries - 1:
                    break
            except APIStatusError as e:
                status_code = e.status_code
                last_error = f"API 状态错误 {status_code}: {e.response.text}"
                if status_code in retryable_status_codes and attempt < max_retries - 1:
                    pass  # 可重试
                else:
                    break
            except APIConnectionError as e:
                last_error = f"网络连接错误: {str(e)}"
                if attempt == max_retries - 1:
                    break
            except Exception as e:
                # JSON 解析失败或其他未知错误，不重试直接返回默认值
                print(f"⚠️ 标题分析失败（解析/其他错误）: {e}，使用默认值")
                return {"topic": "未知", "domain": "通用", "style": "通用", "audience": "通用读者"}

            # 退避等待
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.2)
                sleep_time = delay + jitter
                print(f"⏳ 标题分析重试 {attempt+1}/{max_retries-1}，等待 {sleep_time:.2f} 秒...")
                time.sleep(sleep_time)

        # 所有重试失败
        print(f"⚠️ 标题分析最终失败: {last_error}，使用默认值")
        return {"topic": "未知", "domain": "通用", "style": "通用", "audience": "通用读者"}

    def translate_with_global_context(self, text: str, target_lang: str, global_context: str) -> Tuple[Optional[str], str, int, int]:
        prompt = self._build_prompt(text, target_lang, global_context)
        return self._call_translate(prompt, target_lang)


class MarkdownTranslator:
    def __init__(self, translator: HyMT2Translator, max_tokens: int = 4096, target_lang: str = "中文"):
        self.translator = translator
        self.max_tokens = max_tokens
        self.target_lang = target_lang

    def _is_pure_placeholder(self, text: str) -> bool:
        return bool(re.match(r'^<[A-Z]+[0-9A-F]{5}/>$', text.strip()))

    def _is_natural_paragraph(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        if self._is_pure_placeholder(text):
            return False
        return bool(re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', text))

    def _extract_titles(self, content: str) -> List[str]:
        titles = []
        in_code = False
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code = not in_code
                continue
            if not in_code and stripped.startswith('#') and not stripped.startswith('```'):
                titles.append(stripped)
        return titles

    def _build_global_context(self, analysis: dict) -> str:
        user_bg = self.translator.background_text or ""
        user_style = self.translator.target_style or ""
        return (
            f"【文档主题】{analysis.get('topic', '未知')}\n"
            f"【专业领域】{analysis.get('domain', '通用')}\n"
            f"【写作风格】{analysis.get('style', '通用')}\n"
            f"【目标读者】{analysis.get('audience', '通用读者')}\n"
            f"【用户背景】{user_bg}\n"
            f"【用户风格偏好】{user_style}\n"
            "请在整个翻译过程中遵循以上语境，保持术语和风格一致。"
        )

    def _split_into_windows(self, blocks: List[str]) -> List[List[int]]:
        windows = []
        current_window = []
        current_tokens = 0
        threshold = int(self.max_tokens * 0.65)
        print(f"[窗口划分] max_tokens={self.max_tokens}, 阈值={threshold}")
        for idx, block in enumerate(blocks):
            t = estimate_tokens(block)
            if current_tokens + t > threshold and current_window:
                windows.append(current_window)
                current_window = [idx]
                current_tokens = t
            else:
                current_window.append(idx)
                current_tokens += t
        if current_window:
            windows.append(current_window)
        print(f"[窗口划分] 共 {len(windows)} 个窗口")
        for i, w in enumerate(windows):
            win_tokens = sum(estimate_tokens(blocks[j]) for j in w)
            print(f"  窗口 {i+1}: {len(w)} 个段落，估算 token: {win_tokens}")
        return windows

    def translate_markdown_batch(self, content: str, target_lang: str = "英语") -> str:
        lines = content.split('\n')
        natural_paragraphs = []
        for line in lines:
            if self._is_natural_paragraph(line):
                natural_paragraphs.append(line)

        if not natural_paragraphs:
            return content

        titles = self._extract_titles(content)
        if not hasattr(self.translator, '_global_context'):
            analysis = self.translator.analyze_titles(titles)
            global_context = self._build_global_context(analysis)
            print("\n" + "="*60)
            print("全局语境摘要:")
            print(global_context)
            print("="*60 + "\n")
            self.translator._global_context = global_context

        # ---------- 第一轮翻译 ----------
        markers = [f"PARA{i:05X}" for i in range(len(natural_paragraphs))]
        wrapped_blocks = [f"<{marker}>{para}</{marker}>" for marker, para in zip(markers, natural_paragraphs)]
        windows = self._split_into_windows(wrapped_blocks)
        sep = "\n\n"
        translated_texts = [None] * len(natural_paragraphs)
        failure_reasons = {}

        total_prompt_tokens = 0
        total_completion_tokens = 0

        with tqdm(total=len(windows), desc="第一轮翻译", unit="窗口") as pbar:
            for win_idx, window_indices in enumerate(windows, 1):
                window_indices = [int(i) for i in window_indices]
                window_blocks = [wrapped_blocks[i] for i in window_indices]
                merged_text = sep.join(window_blocks)

                terms_str = self.translator._match_terms(merged_text)
                if terms_str:
                    term_lines = [line for line in terms_str.split('\n') if line.strip() and not line.startswith('参考')]
                    print(f"🔍 窗口 {win_idx} 术语匹配: {len(term_lines)} 条")
                    if term_lines:
                        sample = [line.strip() for line in term_lines[:3]]
                        print(f"   示例术语: {', '.join(sample)}")
                else:
                    print(f"🔍 窗口 {win_idx} 术语匹配: 0 条")

                translated, error_msg, prompt_tok, comp_tok = self.translator.translate_with_global_context(
                    merged_text, target_lang, self.translator._global_context
                )
                total_prompt_tokens += prompt_tok
                total_completion_tokens += comp_tok

                if translated is None:
                    for orig_idx in window_indices:
                        translated_texts[orig_idx] = None
                        failure_reasons[orig_idx] = error_msg or "翻译接口失败"
                    pbar.update(1)
                    pbar.set_postfix_str(f"窗口 {win_idx} 翻译失败")
                    continue

                pattern = re.compile(r'<PARA([0-9A-F]{5})>(.*?)</PARA\1>', re.DOTALL)
                matches = pattern.findall(translated)
                temp_map = {f"PARA{mid}": content.strip() for mid, content in matches}

                for local_idx, orig_idx in enumerate(window_indices):
                    marker = markers[orig_idx]
                    if marker in temp_map:
                        translated_texts[orig_idx] = temp_map[marker]
                    else:
                        translated_texts[orig_idx] = None
                        failure_reasons[orig_idx] = "标签解析失败，未找到对应译文"

                pbar.update(1)
                pbar.set_postfix_str(f"窗口 {win_idx} 包含 {len(window_indices)} 个段落")

        # ---------- 第二轮重试 ----------
        failed_indices = [idx for idx, val in enumerate(translated_texts) if val is None]
        if failed_indices:
            print(f"\n🔄 开始重试 {len(failed_indices)} 个失败段落...")
            retry_markers = [f"RETRY{idx:05X}" for idx in failed_indices]
            retry_blocks = [
                f"<{marker}>{natural_paragraphs[idx]}</{marker}>"
                for idx, marker in zip(failed_indices, retry_markers)
            ]
            retry_windows = self._split_into_windows(retry_blocks)
            retry_sep = "\n\n"

            with tqdm(total=len(retry_windows), desc="第二轮重试", unit="窗口") as pbar:
                for rwin_idx, rwindow_indices in enumerate(retry_windows, 1):
                    rwindow_indices = [int(i) for i in rwindow_indices]
                    rwindow_blocks = [retry_blocks[i] for i in rwindow_indices]
                    merged_text = retry_sep.join(rwindow_blocks)

                    translated, error_msg, prompt_tok, comp_tok = self.translator.translate_with_global_context(
                        merged_text, target_lang, self.translator._global_context
                    )
                    total_prompt_tokens += prompt_tok
                    total_completion_tokens += comp_tok

                    if translated is None:
                        for local_idx, orig_idx in enumerate(rwindow_indices):
                            real_idx = failed_indices[local_idx]
                            translated_texts[real_idx] = None
                            failure_reasons[real_idx] = error_msg or "重试失败"
                        pbar.update(1)
                        pbar.set_postfix_str(f"重试窗口 {rwin_idx} 翻译失败")
                        continue

                    pattern = re.compile(r'<RETRY([0-9A-F]{5})>(.*?)</RETRY\1>', re.DOTALL)
                    matches = pattern.findall(translated)
                    temp_map = {f"RETRY{mid}": content.strip() for mid, content in matches}

                    for local_idx, orig_idx in enumerate(rwindow_indices):
                        real_idx = failed_indices[local_idx]
                        marker = f"RETRY{real_idx:05X}"
                        if marker in temp_map:
                            translated_texts[real_idx] = temp_map[marker]
                        else:
                            translated_texts[real_idx] = None
                            failure_reasons[real_idx] = "重试后标签解析失败"

                    pbar.update(1)
                    pbar.set_postfix_str(f"重试窗口 {rwin_idx} 包含 {len(rwindow_indices)} 个段落")

        # ---------- 统计 ----------
        print("\n" + "="*50)
        print(f"📊 全文 Token 统计:")
        print(f"  总输入 token: {total_prompt_tokens}")
        print(f"  总输出 token: {total_completion_tokens}")
        print(f"  总 token: {total_prompt_tokens + total_completion_tokens}")
        print("="*50 + "\n")

        # ---------- 重建输出 ----------
        output_lines = []
        para_idx = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                output_lines.append(line)
                continue
            if self._is_pure_placeholder(stripped):
                output_lines.append(line)
                continue
            if self._is_natural_paragraph(line):
                output_lines.append(line)  # 原文
                if para_idx < len(translated_texts):
                    trans = translated_texts[para_idx]
                    if trans is not None:
                        output_lines.append(trans)
                    else:
                        err_msg = failure_reasons.get(para_idx, "未知原因")
                        output_lines.append(f"【---------失败原因: {err_msg} + 需要手动翻译manual translate---------】")
                else:
                    output_lines.append("【---------失败原因: 索引越界 + 需要手动翻译manual translate---------】")
                para_idx += 1
            else:
                output_lines.append(line)

        # 移除所有残留的标签
        output_text = "\n".join(output_lines)
        output_text = re.sub(r'<PARA[0-9A-F]{5}>|</PARA[0-9A-F]{5}>|<RETRY[0-9A-F]{5}>|</RETRY[0-9A-F]{5}>', '', output_text)
        return output_text

    def translate_file(self, input_path: Path, output_path: Path, target_lang: str = "英语") -> bool:
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()
            translated = self.translate_markdown_batch(content, target_lang)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(translated)
            return True
        except Exception as e:
            print(f"❌ 翻译文件失败 {input_path.name}: {e}")
            return False

    def process_folder(self, input_root: Path, output_root: Path, target_lang: str = "英语",
                       skip_existing: bool = False) -> None:
        if not input_root.is_dir():
            print(f"❌ 输入目录不存在: {input_root}")
            return
        md_files = list(input_root.rglob("*.md"))
        if not md_files:
            print("⚠️ 未找到任何 .md 文件")
            return
        print(f"📂 发现 {len(md_files)} 个 Markdown 文件")
        success = skip = fail = 0
        for idx, md_file in enumerate(md_files, 1):
            rel_path = md_file.relative_to(input_root)
            out_file = output_root / rel_path
            if skip_existing and out_file.exists():
                skip += 1
                print(f"[{idx}/{len(md_files)}] ⏭️ 跳过已存在: {rel_path}")
                continue
            print(f"[{idx}/{len(md_files)}] 🔄 翻译: {rel_path}")
            ok = self.translate_file(md_file, out_file, target_lang)
            if ok:
                success += 1
            else:
                fail += 1
        print(f"🎉 翻译完成！成功: {success}, 跳过: {skip}, 失败: {fail}")