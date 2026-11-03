"""Model-specific adapters. Internal names only; not official SDK classes.

Each adapter isolates (1) how the request body is built and (2) how the reply is read.
The defaults follow the widely used chat-completions JSON shape. If the official Meta
documentation for your account uses a different schema, change only the `build_*`
and `parse_*` methods below.
"""
import base64
import io
import json
import re

from PIL import Image, ImageDraw, ImageFont
import requests
from django.conf import settings

from .base import BaseAdapter
from .errors import AIBadResponse, AINotConfigured, AIError


def _extract_text(data):
    """Parse Meta Responses API output[], skipping reasoning blocks, with OpenAI fallback."""
    # Meta Responses API: find the first 'message' output block
    try:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if isinstance(part.get("text"), str):
                        return part["text"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    # OpenAI Chat Completions fallback: choices[0].message.content
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    for key in ("output_text", "text", "content"):
        if isinstance(data.get(key), str) and data[key].strip():
            return data[key].strip()
    if data.get("status") == "incomplete" and data.get("incomplete_details", {}).get("reason") == "max_output_tokens":
        raise AIBadResponse("The AI model ran out of output tokens during reasoning. Please try asking a shorter question.")
    raise AIBadResponse("The AI service replied in an unexpected format.")


class MuseSparkService(BaseAdapter):
    """Text reasoning and tutoring."""
    service_name = "muse_spark"
    config_key = "spark"
    label = "The AI tutor"

    def build_payload(self, messages, system, max_tokens, temperature):
        """Build a Meta Responses API payload from a list of {role, content} dicts."""
        input_msgs = []
        if system:
            input_msgs.append({
                "role": "system",
                "content": [{"type": "input_text", "text": system}],
            })
        for m in messages:
            raw = m["content"]
            role = m["role"]
            default_type = "output_text" if role == "assistant" else "input_text"
            # Accept a plain string or an already-structured content list
            if isinstance(raw, str):
                content = [{"type": default_type, "text": raw}]
            elif isinstance(raw, list):
                content = []
                for item in raw:
                    if isinstance(item, dict):
                        item_copy = dict(item)
                        if role == "assistant" and item_copy.get("type") == "input_text":
                            item_copy["type"] = "output_text"
                        elif role != "assistant" and item_copy.get("type") == "output_text":
                            item_copy["type"] = "input_text"
                        elif "type" not in item_copy and "text" in item_copy:
                            item_copy["type"] = default_type
                        content.append(item_copy)
                    else:
                        content.append({"type": default_type, "text": str(item)})
            else:
                content = [{"type": default_type, "text": str(raw)}]
            input_msgs.append({"role": role, "content": content})
        # Meta muse models are reasoning models that generate internal reasoning tokens
        # before outputting text. Using minimal effort ensures fast (~2s) responses and prevents
        # reasoning tokens from consuming the entire output token limit.
        token_budget = max(int(max_tokens or 1500) + 500, 1500)
        return {
            "model": self.model_name,
            "input": input_msgs,
            "max_output_tokens": token_budget,
            "reasoning": {"effort": "minimal"},
            "temperature": temperature,
            "stream": False,
        }

    def parse_response(self, data):
        return _extract_text(data)

    def chat(self, messages, system="", user=None, max_tokens=1500, temperature=0.4):
        payload = self.build_payload(messages, system, max_tokens, temperature)
        size = len(system) + sum(len(m["content"]) for m in messages)
        data = self._post(user=user, input_chars=size, json=payload)
        text = self.parse_response(data)
        self.record_output(user, len(text))
        return text


class LocalMuseModelService(MuseSparkService):
    """Self-hosted open-weight model behind an OpenAI-compatible server (check licence terms first)."""
    service_name = "local_model"
    label = "The local model"

    @property
    def model_cfg(self):
        c = settings.META_AI["LOCAL"]
        return {"model": c["model"], "path": "/v1/chat/completions"}

    def is_configured(self):
        c = settings.META_AI["LOCAL"]
        return bool(c["base_url"] and c["model"])

    def _url(self):
        return settings.META_AI["LOCAL"]["base_url"].rstrip("/") + "/v1/chat/completions"

    def _headers(self):
        key = settings.META_AI["LOCAL"]["api_key"]
        return {"Authorization": f"Bearer {key}"} if key else {}


class MuseWonderService(MuseSparkService):
    """Optional multimodal model, used to read textbook images when configured."""
    service_name = "muse_wonder"
    config_key = "wonder"
    label = "Image reading"

    def interpret_image(self, image_bytes, mime, instruction, user=None, max_tokens=2000):
        b64 = base64.b64encode(image_bytes).decode()
        content = [
            {"type": "input_text", "text": instruction},
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
        ]
        payload = {
            "model": self.model_name,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": max(int(max_tokens or 2000) + 500, 2000),
            "reasoning": {"effort": "minimal"},
            "stream": False,
        }
        data = self._post(user=user, input_chars=len(instruction) + len(b64) // 10, json=payload)
        text = self.parse_response(data)
        self.record_output(user, len(text))
        return text


class MuseImageService(BaseAdapter):
    """Educational illustration generation."""
    service_name = "muse_image"
    config_key = "image"
    label = "Image generation"

    def build_payload(self, prompt):
        return {"model": self.model_name, "prompt": prompt, "n": 1}

    def parse_response(self, data):
        """Returns image bytes. Accepts base64 (data[0].b64_json) or a URL (data[0].url)."""
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError):
            raise AIBadResponse("The image service replied in an unexpected format.")
        if item.get("b64_json"):
            raw_bytes = base64.b64decode(item["b64_json"])
            try:
                im = Image.open(io.BytesIO(raw_bytes))
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                return raw_bytes
        if item.get("url"):
            r = requests.get(item["url"], timeout=self.cfg["TIMEOUT"])
            r.raise_for_status()
            try:
                im = Image.open(io.BytesIO(r.content))
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                return r.content
        raise AIBadResponse("The image service did not return an image.")

    def generate(self, prompt, user=None):
        if self.is_configured():
            try:
                data = self._post(user=user, input_chars=len(prompt), json=self.build_payload(prompt))
                img = self.parse_response(data)
                self.record_output(user, len(img))
                return img
            except Exception as exc:
                import logging
                logging.getLogger("myapp.ai").warning("Image API generation failed (%s), generating educational diagram fallback", exc)
        return self.generate_fallback(prompt, user=user)

    def generate_fallback(self, prompt, user=None):
        """Build an educational graphic illustration using Pillow when external generation is unavailable."""
        w, h = 1200, 800
        im = Image.new("RGB", (w, h), (15, 23, 42))
        draw = ImageDraw.Draw(im, "RGBA")

        # Soft background vertical gradient
        for y in range(h):
            r = int(15 + (y / h) * 18)
            g = int(23 + (y / h) * 22)
            b = int(42 + (y / h) * 28)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

        # Subtle background grid dots
        for gx in range(60, w - 60, 40):
            for gy in range(60, h - 60, 40):
                draw.point((gx, gy), fill=(71, 85, 105, 80))

        # Main container panel (glassmorphism look)
        draw.rounded_rectangle([50, 40, w - 50, h - 40], radius=24, fill=(30, 41, 59, 230), outline=(71, 85, 105, 255), width=2)

        # Badge
        draw.rounded_rectangle([80, 70, 370, 106], radius=16, fill=(13, 148, 136, 255))
        draw.text((96, 78), "LEARNMATE AI • EDUCATIONAL VISUAL", fill=(255, 255, 255))

        # Cleaned prompt title
        clean = re.sub(r"^(Educational illustration for students:?\s*)|(\.\s*Clean, simple, accurate.*)$", "", prompt, flags=re.I).strip()
        clean = re.sub(r"\s+", " ", clean).strip()
        title = (clean[:65] or "Educational Illustration").title()
        draw.text((80, 125), title, fill=(248, 250, 252))

        # Central visual diagram frame
        fx, fy, fw, fh = 80, 175, w - 160, 480
        draw.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=18, fill=(15, 23, 42, 210), outline=(51, 65, 85, 255), width=1)

        lower_prompt = prompt.lower()
        cx = fx + fw // 2
        cy = fy + fh // 2

        # Draw thematic educational visual elements based on keywords
        if any(k in lower_prompt for k in ("rose", "flower", "leaf", "plant", "photosynthesis", "tree")):
            # Central stem
            draw.line([(cx, cy - 80), (cx, cy + 180)], fill=(34, 197, 94, 255), width=8)
            # Leaves
            draw.polygon([(cx, cy + 60), (cx - 120, cy + 20), (cx - 140, cy + 70), (cx, cy + 80)], fill=(22, 163, 74, 230))
            draw.polygon([(cx, cy + 90), (cx + 120, cy + 50), (cx + 140, cy + 100), (cx, cy + 110)], fill=(22, 163, 74, 230))
            if any(k in lower_prompt for k in ("rose", "flower")):
                # Concentric rose petals
                for rad, col in [(90, (244, 63, 94, 255)), (70, (225, 29, 72, 255)), (50, (190, 18, 60, 255)), (30, (159, 18, 57, 255))]:
                    draw.ellipse([cx - rad, cy - 80 - rad, cx + rad, cy - 80 + rad], fill=col)
                draw.ellipse([cx - 15, cy - 95, cx + 15, cy - 65], fill=(251, 191, 36, 255))
            else:
                # Big stylized leaf with veins
                draw.ellipse([cx - 100, cy - 140, cx + 100, cy + 120], fill=(34, 197, 94, 230), outline=(74, 222, 128, 255), width=3)
                draw.line([(cx, cy - 130), (cx, cy + 110)], fill=(74, 222, 128, 255), width=4)
                for vy in range(-90, 90, 40):
                    draw.line([(cx, cy + vy), (cx - 65, cy + vy - 25)], fill=(74, 222, 128, 220), width=2)
                    draw.line([(cx, cy + vy), (cx + 65, cy + vy - 25)], fill=(74, 222, 128, 220), width=2)
        elif any(k in lower_prompt for k in ("water", "cycle", "rain", "cloud", "sea", "ocean")):
            # Water Cycle diagram
            draw.rounded_rectangle([fx + 20, fy + fh - 120, fx + fw - 20, fy + fh - 20], radius=12, fill=(14, 165, 233, 220))
            draw.ellipse([fx + 80, fy + 50, fx + 200, fy + 170], fill=(245, 158, 11, 255))
            draw.ellipse([cx + 60, fy + 60, cx + 220, fy + 150], fill=(226, 232, 240, 240))
            draw.ellipse([cx + 120, fy + 40, cx + 260, fy + 140], fill=(226, 232, 240, 240))
            draw.ellipse([cx + 190, fy + 70, cx + 320, fy + 150], fill=(226, 232, 240, 240))
            for rx in range(cx + 100, cx + 290, 25):
                draw.line([(rx, fy + 175), (rx - 15, fy + 225)], fill=(56, 189, 248, 230), width=3)
            draw.arc([fx + 180, fy + 160, cx + 40, fy + 340], start=180, end=340, fill=(244, 114, 182, 255), width=4)
        elif any(k in lower_prompt for k in ("solar", "space", "planet", "sun", "orbit", "earth")):
            # Solar System diagram
            draw.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=(245, 158, 11, 255), outline=(251, 191, 36, 255), width=4)
            planets = [(150, (148, 163, 184), 10), (220, (59, 130, 246), 18), (300, (239, 68, 68), 14), (390, (234, 179, 8), 26)]
            for r_dist, p_col, p_size in planets:
                draw.ellipse([cx - r_dist, cy - r_dist // 2, cx + r_dist, cy + r_dist // 2], outline=(71, 85, 105, 160), width=2)
                draw.ellipse([cx + r_dist - p_size, cy - p_size, cx + r_dist + p_size, cy + p_size], fill=p_col)
        else:
            # Universal Concept diagram: 3 connected interactive nodes with flows
            node_r = 75
            nodes = [
                (cx - 300, cy, "Input / Structure", (14, 165, 233, 240)),
                (cx, cy - 40, "Core Concept", (168, 85, 247, 240)),
                (cx + 300, cy, "Output / Function", (16, 185, 129, 240)),
            ]
            draw.line([(cx - 225, cy), (cx - 75, cy - 40)], fill=(148, 163, 184, 200), width=4)
            draw.line([(cx + 75, cy - 40), (cx + 225, cy)], fill=(148, 163, 184, 200), width=4)
            for nx, ny, nlbl, ncol in nodes:
                draw.ellipse([nx - node_r, ny - node_r, nx + node_r, ny + node_r], fill=ncol, outline=(255, 255, 255, 180), width=2)
                draw.text((nx - 60, ny - 8), nlbl, fill=(255, 255, 255))

        # Footer explanation bar
        draw.rounded_rectangle([80, h - 110, w - 80, h - 65], radius=12, fill=(30, 41, 59, 240), outline=(71, 85, 105, 200), width=1)
        draw.text((100, h - 94), f"Concept Study: {title}  •  Prepared for clear visual comprehension & student lessons", fill=(148, 163, 184))

        buf = io.BytesIO()
        im.save(buf, format="PNG")
        res = buf.getvalue()
        self.record_output(user, len(res))
        return res


class MuseVoiceTranscribeService(BaseAdapter):
    """Speech to text. Supported languages and audio formats must be verified in the official docs."""
    service_name = "muse_voice"
    config_key = "voice"
    label = "Voice transcription"

    def build_request(self, audio_bytes, filename, content_type, language):
        data = {"model": self.model_name}
        if language:
            data["language"] = language
        return {"data": data, "files": {"file": (filename, audio_bytes, content_type)}}

    def parse_response(self, data):
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise AIBadResponse("The transcription service replied in an unexpected format.")
        return text.strip()

    def transcribe(self, audio_bytes, filename, content_type, language="", user=None):
        req = self.build_request(audio_bytes, filename, content_type, language)
        data = self._post(user=user, input_chars=len(audio_bytes) // 100, **req)
        text = self.parse_response(data)
        self.record_output(user, len(text))
        return text


class SAM31Service(BaseAdapter):
    """Region segmentation for diagrams. SAM does segmentation only: no OCR, no explanations."""
    service_name = "sam"
    config_key = "sam"
    label = "Diagram segmentation"

    def build_request(self, image_bytes, filename, mime):
        return {"data": {"model": self.model_name}, "files": {"image": (filename, image_bytes, mime)}}

    def parse_response(self, data):
        """Each segment box must be [x, y, width, height] in PERCENT of the image (0-100).
        If your SAM deployment returns pixels or corner coordinates, convert them here."""
        segs = data.get("segments") if isinstance(data, dict) else None
        if not isinstance(segs, list):
            raise AIBadResponse("The segmentation service replied in an unexpected format.")
        clean = []
        for s in segs[:30]:
            if isinstance(s, dict) and isinstance(s.get("box"), list) and len(s["box"]) == 4:
                clean.append({"label": str(s.get("label", ""))[:60], "box": [float(v) for v in s["box"]]})
        return clean

    def segment(self, image_bytes, filename, mime, user=None):
        req = self.build_request(image_bytes, filename, mime)
        data = self._post(user=user, input_chars=len(image_bytes) // 100, **req)
        return self.parse_response(data)


def get_text_service():
    if settings.META_AI["TEXT_PROVIDER"] == "local":
        return LocalMuseModelService()
    return MuseSparkService()


def parse_json_block(text):
    """Pull a JSON object or array out of a model reply (handles ``` fences and chatter)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise AIBadResponse("The AI reply did not contain structured data.")
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        raise AIBadResponse("The AI reply could not be read as structured data.")
