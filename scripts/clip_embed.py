# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import argparse
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


def _l2_normalize(v: List[float]) -> List[float]:
    n2 = 0.0
    for x in v:
        n2 += float(x) * float(x)
    if n2 <= 1e-12:
        return [float(x) for x in v]
    n = n2 ** 0.5
    return [float(x) / n for x in v]


def _as_jsonable(v: Any, max_len: Optional[int] = None) -> Any:
    if isinstance(v, (list, tuple)):
        out = [float(x) for x in v]
        if max_len is not None:
            out = out[: max_len]
        return out
    return v


def _infer_item_meta(image_path: str, input_root: str) -> Dict[str, Any]:
    p = os.path.abspath(image_path)
    root = os.path.abspath(input_root)
    name = os.path.splitext(os.path.basename(p))[0]
    rel = ""
    try:
        rel = os.path.relpath(p, root)
    except Exception:
        rel = ""
    group = ""
    if rel and rel != "." and not rel.startswith(".."):
        group = os.path.dirname(rel).replace("\\", "/").strip("/")
    key = f"{group}:{name}" if group else name
    return {
        "key": key,
        "name": name,
        "group": group,
        "image_rel": rel if rel and rel != "." and not rel.startswith("..") else "",
    }


def _init_open_clip(model_name: str) -> Tuple[Optional[Callable[[str], List[float]]], Optional[Callable[[str], List[float]]], str]:
    try:
        import torch  # type: ignore
        import open_clip  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as e:
        return None, None, f"open_clip not available: {e}"

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained="openai")
    tokenizer = open_clip.get_tokenizer(model_name)
    model = model.to(device)
    model.eval()

    def embed_image(image_path: str) -> List[float]:
        img = Image.open(image_path).convert("RGB")
        image_in = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad():
            img_feat = model.encode_image(image_in)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            return img_feat.squeeze(0).detach().cpu().float().tolist()

    def embed_text(text: str) -> List[float]:
        tokens = tokenizer([text]).to(device)
        with torch.no_grad():
            txt_feat = model.encode_text(tokens)
            txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
            return txt_feat.squeeze(0).detach().cpu().float().tolist()

    return embed_image, embed_text, f"open_clip:{model_name}:{device}"


def _init_transformers_clip(model_id: str) -> Tuple[Optional[Callable[[str], List[float]]], Optional[Callable[[str], List[float]]], str]:
    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore
        from transformers import CLIPModel, CLIPProcessor, logging as hf_logging  # type: ignore
    except Exception as e:
        return None, None, f"transformers CLIP not available: {e}"

    hf_logging.set_verbosity_error()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = CLIPModel.from_pretrained(model_id).to(device)
    try:
        processor = CLIPProcessor.from_pretrained(model_id, use_fast=True)
    except TypeError:
        processor = CLIPProcessor.from_pretrained(model_id)
    model.eval()

    def embed_image(image_path: str) -> List[float]:
        img = Image.open(image_path).convert("RGB")
        with torch.no_grad():
            inputs = processor(images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            img_feat = model.get_image_features(**inputs)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            return img_feat.squeeze(0).detach().cpu().float().tolist()

    def embed_text(text: str) -> List[float]:
        with torch.no_grad():
            inputs = processor(text=[text], return_tensors="pt", padding=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}
            txt_feat = model.get_text_features(**inputs)
            txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
            return txt_feat.squeeze(0).detach().cpu().float().tolist()

    return embed_image, embed_text, f"transformers:{model_id}:{device}"


def _collect_images(path: str) -> List[str]:
    p = os.path.abspath(path)
    if not os.path.exists(p):
        return []
    if os.path.isfile(p):
        return [p]
    out: List[str] = []
    for root, _dirs, files in os.walk(p):
        for fn in files:
            low = fn.lower()
            if low.endswith(".png") or low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".webp"):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Image file or directory")
    ap.add_argument("--text", default="", help="Optional text prompt for text embedding")
    ap.add_argument("--backend", default="auto", choices=["auto", "open_clip", "transformers"], help="Embedding backend")
    ap.add_argument("--open-clip-model", default="ViT-B-32", help="open_clip model name")
    ap.add_argument("--hf-model", default="openai/clip-vit-base-patch32", help="HuggingFace model id")
    ap.add_argument("--out", default="", help="Output JSON path. If empty, print to stdout")
    ap.add_argument("--max", type=int, default=1, help="Max images to process")
    args = ap.parse_args()

    input_root = os.path.abspath(args.input)
    images = _collect_images(input_root)
    if not images:
        p = os.path.abspath(args.input)
        exists = os.path.exists(p)
        is_file = os.path.isfile(p)
        is_dir = os.path.isdir(p)
        raise SystemExit(
            "No images found.\n"
            f"Input: {args.input}\n"
            f"Resolved: {p}\n"
            f"Exists: {exists}  IsFile: {is_file}  IsDir: {is_dir}\n"
            "Supported extensions: .png .jpg .jpeg .webp"
        )
    images = images[: max(1, int(args.max))]
    text = (args.text or "").strip() or None

    results: Dict[str, Any] = {
        "backend": None,
        "items": [],
    }

    last_errs: List[str] = []

    embed_image: Optional[Callable[[str], List[float]]] = None
    embed_text: Optional[Callable[[str], List[float]]] = None
    backend_used: Optional[str] = None

    if args.backend in ("auto", "open_clip"):
        ei, et, meta = _init_open_clip(args.open_clip_model)
        if ei is not None:
            embed_image, embed_text, backend_used = ei, et, meta
        else:
            last_errs.append(meta)

    if embed_image is None and args.backend in ("auto", "transformers"):
        ei, et, meta = _init_transformers_clip(args.hf_model)
        if ei is not None:
            embed_image, embed_text, backend_used = ei, et, meta
        else:
            last_errs.append(meta)

    if embed_image is None or backend_used is None:
        err = "\n".join(last_errs[-4:]) if last_errs else "No backend succeeded"
        raise SystemExit(
            "No CLIP backend available.\n"
            "Install one of:\n"
            "  - pip install torch open_clip_torch pillow\n"
            "  - pip install torch transformers pillow\n"
            f"\nDetails:\n{err}"
        )

    results["backend"] = backend_used
    print(f"Backend: {backend_used}")
    print(f"Images: {len(images)}")

    text_vec_shared = None
    if text and embed_text is not None:
        print("Embedding text...")
        text_vec_shared = embed_text(text)

    for i, img_path in enumerate(images):
        if len(images) > 1 and (i == 0 or (i + 1) % 10 == 0 or (i + 1) == len(images)):
            print(f"[{i+1}/{len(images)}] {os.path.basename(img_path)}")

        img_vec = embed_image(img_path)
        meta = _infer_item_meta(img_path, input_root)
        results["items"].append(
            {
                "image": img_path,
                **meta,
                "image_vec": _as_jsonable(_l2_normalize(img_vec)),
                "text_vec": _as_jsonable(_l2_normalize(text_vec_shared)) if text_vec_shared is not None else None,
            }
        )

    out_text = json.dumps(results, ensure_ascii=False)
    if args.out:
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"Wrote: {out_path}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
