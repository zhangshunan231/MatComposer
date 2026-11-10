# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import json
import urllib.request
import urllib.error
import datetime
import ssl
import socket
import time

SYSTEM_PROMPT = """You are MatComposer, an expert technical artist in Blender. Your goal is to generate procedural PBR materials using Shader Nodes. You must output ONLY valid JSON describing the node graph topology and parameters. Do not use Markdown blocks. The JSON structure must strictly follow the schema provided.

If "available_templates" are provided in the prompt, you MUST check if any of them matches the user's request.
- If a good match is found, set "template_id" to that ID, and "use_template" to true.
- If no good match is found, set "use_template" to false and generate the graph from scratch.
- If "use_template" is true, you can optionally provide "parameter_overrides" to tweak the template.

JSON Schema:
{
  "material_name": "string",
  "use_template": boolean,
  "template_id": "string or null",
  "parameter_overrides": { "NodeName.SocketName": value },
  "components": [
    {
      "node_type": "string (Blender node type, e.g., ShaderNodeTexVoronoi)",
      "name": "string (Unique identifier)",
      "inputs": {
        "Socket Name": value (float or [r,g,b,a] or [x,y,z])
      }
    }
  ],
  "links": [
    {"from_node": "name", "from_socket": "name", "to_node": "name", "to_socket": "name"}
  ]
}
"""

SEMANTIC_SYSTEM_PROMPT = """You are MatComposer. Convert the user's raw text into a compact set of visual semantic tags and a 1-3 slot decomposition plan for a procedural material system.

Semantic taxonomy vectors (preferred vocabulary, examples not exhaustive):
1) Material Categories: metal, stone, wood, fabric, marble, cast iron, silk, concrete
2) Stylistic Attributes: realistic, toon, stylized, cyberpunk, ancient, modern, futuristic
3) Surface States: rusted, worn, cracked, scratched, mossy, snowy, dusty, wet, dry
4) Physical Perceptions: rough, smooth, viscous, glowing, translucent, metallic, matte
5) Usage Scenarios: floor, wall, roof, armor, terrain, prop, interior, exterior

Output ONLY valid JSON. No Markdown. No extra keys beyond the schema.

Schema:
{
  "tags": ["lowercase visual tags, short, 5-20 items"],
  "slot_count": 1,
  "slots": [
    {
      "role": "Base|Overlay|Detail",
      "concept": "short noun phrase",
      "tags": ["lowercase tags, 3-10 items"],
      "relation": "base|overlay|detail",
      "mask": "optional lowercase mask preference or empty string"
    }
  ]
}

Rules:
- slot_count must be 1..3 and equal to slots.length
- For common compound materials (e.g. rusty metal), split into Base + Overlay
- Prefer concrete appearance words (metal, rust, brushed, wet, dusty, scratched, painted, etc.)
- Prefer tags from the vocabulary above when they fit, but do not treat the examples as a closed list
- You may introduce additional short visual tags when they are clearly more accurate or more useful for retrieval
- Favor reusable visual terms over poetic or subjective wording
- Keep tags short and deduplicated
- Normalize obvious synonyms toward the preferred vocabulary when possible
- When applicable, include tags that cover multiple vectors above; prefer the closest matching keywords
- For overlay/detail slots, you may suggest a mask preference when it is visually obvious
- Preferred mask vocabulary: edge_mask, peeling_mask, splatter_mask, cell_mask, crack_mask, normal_mask, ao_mask, generated_mask
- For base slots, usually leave mask as an empty string
"""

class LLMClient:
    def __init__(self, api_key, model="qwen-vl-plus"):
        self.api_key = api_key
        self.model = model
        self.api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        self.timeout = 45
        self.max_retries = 3

    def _build_messages(self, system_prompt, user_text, image_data_url=None):
        if image_data_url:
            user_content = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        else:
            user_content = user_text
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _send_request(self, data, debug=False, debug_label="Request Payload"):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        if debug:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] [MatComposer DEBUG] --- {debug_label} ---")
            print(f"Model: {self.model}")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("---------------------------------")

        payload = json.dumps(data).encode('utf-8')
        ssl_ctx = ssl.create_default_context()
        last_error = ""

        for attempt in range(1, int(self.max_retries) + 1):
            try:
                req = urllib.request.Request(
                    self.api_url,
                    data=payload,
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_ctx) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    content = result['choices'][0]['message']['content']
                    return content, result
            except urllib.error.HTTPError as e:
                return None, {"error": f"HTTP Error: {e.code} - {e.reason}"}
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                last_error = str(reason)
            except (ssl.SSLError, socket.timeout, TimeoutError, ConnectionResetError) as e:
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            if attempt < int(self.max_retries):
                if debug:
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    print(f"[{now}] [MatComposer DEBUG] Request retry {attempt}/{self.max_retries - 1}: {last_error}")
                time.sleep(0.8 * attempt)

        lowered = str(last_error).lower()
        if "unexpected_eof_while_reading" in lowered or "eof occurred in violation of protocol" in lowered:
            msg = (
                "SSL connection to DashScope was interrupted during response read. "
                "This is usually a transient network/TLS issue. Please retry."
            )
        elif "timed out" in lowered:
            msg = "Request to DashScope timed out. Please retry."
        else:
            msg = f"Network Error: {last_error}" if last_error else "Network Error"
        return None, {"error": msg}

    def generate_material(self, user_prompt, templates=None, image_data_url=None, debug=False):
        final_prompt = user_prompt
        if templates:
            final_prompt += f"\n\nAvailable Templates (The user query might be in a different language or use different terms. Please check if any of these match semantically):\n{json.dumps(templates, indent=2)}"

        data = {
            "model": self.model,
            "messages": self._build_messages(SYSTEM_PROMPT, final_prompt, image_data_url=image_data_url),
            "temperature": 0.7
        }
        content, result = self._send_request(data, debug=debug, debug_label="Request Payload")
        if content is None:
            if debug and isinstance(result, dict) and result.get("error"):
                print(f"[MatComposer DEBUG] Error: {result['error']}")
            return {"error": result.get("error") if isinstance(result, dict) else "Error"}
        if debug:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] [MatComposer DEBUG] --- Raw Response ---")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print("\n--- Content ---")
            print(content)
            print("----------------------------------")
        return self._parse_json(content)

    def _parse_json(self, content):
        # Attempt to clean markdown if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]

        if content.endswith("```"):
            content = content[:-3]

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            return {"error": f"JSON Parse Error: {str(e)}", "raw_content": content}

    def generate_semantic_init(self, user_prompt, image_data_url=None, debug=False):
        data = {
            "model": self.model,
            "messages": self._build_messages(SEMANTIC_SYSTEM_PROMPT, user_prompt, image_data_url=image_data_url),
            "temperature": 0.2
        }
        content, result = self._send_request(data, debug=debug, debug_label="Semantic Init Request")
        if content is None:
            if debug and isinstance(result, dict) and result.get("error"):
                print(f"[MatComposer DEBUG] Error: {result['error']}")
            return {"error": result.get("error") if isinstance(result, dict) else "Error"}
        if debug:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] [MatComposer DEBUG] --- Semantic Init Raw Response ---")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print("\n--- Content ---")
            print(content)
            print("----------------------------------")
        return self._parse_json(content)
