import json
import os
import bpy
import math
import hashlib
import tempfile
import shutil
from . import semantic_init

class LibraryManager:
    def __init__(self):
        self.index_data = []
        self._id_index = {}
        self._preview_material_lru = []
        self._preview_material_limit = 16
        self._preview_collection = None
        self._thumb_image_cache = {}
        self._thumb_image_lru = []
        self._thumb_image_limit = 64
        self._clip_key_to_vec = {}
        self._clip_loaded = False
        self._gnn_key_to_vec = {}
        self._gnn_loaded = False

    def _repo_root_dir(self):
        try:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        except Exception:
            return os.path.abspath(os.getcwd())

    def _debug_enabled(self):
        try:
            scene = getattr(bpy.context, "scene", None)
            props = getattr(scene, "mat_composer", None) if scene else None
            return bool(getattr(props, "debug_mode", False))
        except Exception:
            return False

    def _addon_material_cache_dir(self):
        return os.path.join(self._repo_root_dir(), "material_cache")

    def _material_cache_dir(self):
        base = ""
        try:
            base = bpy.utils.user_resource('DATAFILES', path="MatComposer", create=True)
        except Exception:
            base = ""

        if not base:
            root = os.environ.get("APPDATA")
            if not root:
                root = os.path.expanduser("~")
            base = os.path.join(root, "MatComposer")
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                base = ""

        if not base:
            return self._addon_material_cache_dir()

        cache_dir = os.path.join(base, "material_cache")
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass
        return cache_dir

    def _cache_file_candidates(self, filename):
        out = []
        try:
            p1 = os.path.join(self._material_cache_dir(), filename)
            if p1:
                out.append(p1)
        except Exception:
            pass
        try:
            p2 = os.path.join(self._addon_material_cache_dir(), filename)
            if p2 and p2 not in out:
                out.append(p2)
        except Exception:
            pass
        return out

    def _first_existing_cache_file(self, filename):
        for p in self._cache_file_candidates(filename):
            try:
                if p and os.path.exists(p):
                    return p
            except Exception:
                continue
        return ""

    def _previews_root_dir(self):
        return os.path.join(self._material_cache_dir(), "previews")

    def _addon_previews_root_dir(self):
        return os.path.join(self._addon_material_cache_dir(), "previews")

    def _safe_filename(self, name):
        bad = '<>:"/\\|?*'
        out = []
        for ch in str(name or ""):
            out.append("_" if ch in bad else ch)
        s = "".join(out).strip().strip(".")
        if not s:
            s = "material"
        return s[:180]

    def _entry_preview_rel_dir(self, entry):
        catalog_path = str(entry.get("catalog_path") or "").replace("\\", "/").strip().strip("/")
        if catalog_path:
            return catalog_path
        return "MyMaterials"

    def _thumb_path_candidates(self, entry):
        entry_id = str(entry.get("id") or "")
        name_raw = str(entry.get("name") or "").strip()
        name_safe = self._safe_filename(name_raw)
        rel_dir = self._entry_preview_rel_dir(entry).replace("/", os.sep)
        previews_roots = []
        for r in (self._addon_previews_root_dir(), self._previews_root_dir()):
            rr = str(r or "")
            if rr and rr not in previews_roots:
                previews_roots.append(rr)

        candidates = []
        for previews_root in previews_roots:
            if name_raw:
                candidates.append(os.path.join(previews_root, rel_dir, f"{name_raw}.png"))
            if name_safe:
                candidates.append(os.path.join(previews_root, rel_dir, f"{name_safe}.png"))

            if rel_dir.lower() != "mymaterials":
                if name_raw:
                    candidates.append(os.path.join(previews_root, "MyMaterials", f"{name_raw}.png"))
                if name_safe:
                    candidates.append(os.path.join(previews_root, "MyMaterials", f"{name_safe}.png"))

        root = os.environ.get("APPDATA")
        if not root:
            root = os.path.expanduser("~")
        legacy_dir = os.path.join(root, "MatComposer", "thumbnails")
        candidates.append(os.path.join(legacy_dir, f"{entry_id}.png"))
        return candidates

    def _normalize_blend_path(self, path):
        p = str(path or "")
        if not p:
            return p
        try:
            p = os.path.abspath(p)
        except Exception:
            pass
        if os.name == "nt":
            if not p.startswith("\\\\?\\") and len(p) >= 250:
                p = "\\\\?\\" + p
        return p

    def _read_blend_header(self, path):
        try:
            with open(path, "rb") as f:
                header = f.read(12)
            return header
        except Exception:
            return b""

    def _is_valid_blend_header(self, path):
        header = self._read_blend_header(path)
        if header.startswith(b"BLENDER"):
            return True
        if header.startswith(b"\x1f\x8b"):
            return True
        if header.startswith(b"\x28\xb5\x2f\xfd"):
            return True
        return False

    def _find_backup_blend(self, path):
        p = str(path or "")
        if not p:
            return ""
        if p.lower().endswith(".blend"):
            for suffix in ("1", "2", "3"):
                alt = p + suffix
                if os.path.exists(alt):
                    return alt
        return ""

    def _copy_to_temp(self, path):
        try:
            base = os.path.basename(path)
            name = os.path.splitext(base)[0]
            temp_dir = os.path.join(tempfile.gettempdir(), "MatComposerScan")
            os.makedirs(temp_dir, exist_ok=True)
            dst = os.path.join(temp_dir, base)
            if not os.path.exists(dst):
                shutil.copy2(path, dst)
            return dst
        except Exception:
            return ""

    def _preview_material_name(self, entry):
        eid = str(entry.get("id") or "")
        src = str(entry.get("full_path") or "")
        name = str(entry.get("name") or "")
        h = hashlib.md5(f"{eid}|{src}|{name}".encode("utf-8")).hexdigest()[:12]
        return f"MC_PREVIEW_{h}"

    def _remember_preview_material(self, mat_name):
        name = str(mat_name or "")
        if not name:
            return
        if name in self._preview_material_lru:
            try:
                self._preview_material_lru.remove(name)
            except Exception:
                pass
        self._preview_material_lru.append(name)
        while len(self._preview_material_lru) > int(self._preview_material_limit):
            old = self._preview_material_lru.pop(0)
            m = bpy.data.materials.get(old)
            if m:
                try:
                    bpy.data.materials.remove(m, do_unlink=True)
                except Exception:
                    pass

    def _cleanup_preview_materials(self):
        keep = []
        for name in list(self._preview_material_lru):
            if bpy.data.materials.get(name):
                keep.append(name)
        self._preview_material_lru = keep

        for m in list(getattr(bpy.data, "materials", []) or []):
            name = str(getattr(m, "name", "") or "")
            lname = name.lower()
            if not (lname.startswith("mc_preview") or lname.startswith("mt_preview")):
                continue
            if name in self._preview_material_lru:
                continue
            try:
                if getattr(m, "users", 0) > 0:
                    continue
            except Exception:
                pass
            try:
                bpy.data.materials.remove(m, do_unlink=True)
            except Exception:
                pass

    def _ensure_preview_collection(self):
        if self._preview_collection is not None:
            return self._preview_collection
        try:
            previews = bpy.utils.previews
        except Exception:
            return None
        try:
            self._preview_collection = previews.new()
        except Exception:
            self._preview_collection = None
        return self._preview_collection

    def _remember_thumb_image(self, entry_id, image):
        key = str(entry_id or "")
        if not key or not image:
            return
        if key in self._thumb_image_lru:
            try:
                self._thumb_image_lru.remove(key)
            except Exception:
                pass
        self._thumb_image_lru.append(key)
        self._thumb_image_cache[key] = image

        while len(self._thumb_image_lru) > int(self._thumb_image_limit):
            old = self._thumb_image_lru.pop(0)
            img = self._thumb_image_cache.pop(old, None)
            if img:
                try:
                    bpy.data.images.remove(img, do_unlink=True)
                except Exception:
                    pass

    def _load_thumb_via_image(self, entry_id, path):
        key = str(entry_id or "")
        p = str(path or "")
        if not key or not p:
            return 0

        img = self._thumb_image_cache.get(key)
        if img:
            try:
                img.preview_ensure()
                prev = img.preview
                icon_id = int(getattr(prev, "icon_id", 0) or 0) if prev else 0
                if icon_id > 0:
                    self._remember_thumb_image(key, img)
                    return icon_id
            except Exception:
                pass

        try:
            img = bpy.data.images.load(p, check_existing=True)
        except Exception as e:
            if self._debug_enabled():
                print(f"[MatComposer] Image load failed: id={key} path={p} err={e}")
            return 0

        try:
            img.preview_ensure()
            prev = img.preview
            icon_id = int(getattr(prev, "icon_id", 0) or 0) if prev else 0
        except Exception as e:
            if self._debug_enabled():
                print(f"[MatComposer] Image preview failed: id={key} path={p} err={e}")
            icon_id = 0

        self._remember_thumb_image(key, img)
        return int(icon_id or 0)

    def try_load_entry_preview_image(self, entry):
        if not isinstance(entry, dict):
            return None

        entry_id = str(entry.get("id") or "")
        if not entry_id:
            return None

        img = self._thumb_image_cache.get(entry_id)
        if img and getattr(img, "name", "") in bpy.data.images:
            try:
                img.preview_ensure()
            except Exception:
                pass
            self._remember_thumb_image(entry_id, img)
            return img

        for p in self._thumb_path_candidates(entry):
            try:
                if not p or not os.path.exists(p):
                    continue
            except Exception:
                continue
            try:
                img = bpy.data.images.load(str(p), check_existing=True)
            except Exception as e:
                if self._debug_enabled():
                    print(f"[MatComposer] Image load failed: id={entry_id} path={p} err={e}")
                continue
            try:
                img.preview_ensure()
            except Exception:
                pass
            self._remember_thumb_image(entry_id, img)
            return img

        return None

    def _get_thumb_path(self, entry):
        if not isinstance(entry, dict):
            return ""
        candidates = self._thumb_path_candidates(entry)
        for p in candidates:
            try:
                if p and os.path.exists(p):
                    return p
            except Exception:
                continue
        previews_root = self._previews_root_dir()
        rel_dir = self._entry_preview_rel_dir(entry).replace("/", os.sep)
        name_raw = str(entry.get("name") or "").strip()
        name_safe = self._safe_filename(name_raw)
        dst = os.path.join(previews_root, rel_dir, f"{name_safe}.png")
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        except Exception:
            pass
        return dst

    def _save_pixels_to_png(self, pixels, width, height, filepath):
        if not pixels or width <= 0 or height <= 0:
            return False
        
        # Convert ints to floats if needed
        # preview.image_pixels is usually int list
        if isinstance(pixels[0], int):
            f_pixels = [x / 255.0 for x in pixels]
        else:
            f_pixels = pixels

        # Ensure correct length (RGBA)
        if len(f_pixels) != width * height * 4:
            return False

        temp_img = None
        try:
            temp_name = f"temp_thumb_{os.path.basename(filepath)}"
            if temp_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[temp_name])
            
            temp_img = bpy.data.images.new(temp_name, width, height, alpha=True)
            temp_img.pixels = f_pixels
            temp_img.filepath_raw = filepath
            temp_img.file_format = 'PNG'
            temp_img.save()
            return True
        except Exception as e:
            print(f"Error saving thumb: {e}")
            return False
        finally:
            if temp_img:
                try:
                    bpy.data.images.remove(temp_img)
                except Exception:
                    pass

    def _load_thumb_from_disk(self, entry_id, path, force_reload=False):
        pcoll = self._ensure_preview_collection()
        if not pcoll:
            return 0
        try:
            if entry_id in pcoll:
                try:
                    icon_id = int(getattr(pcoll[entry_id], "icon_id", 0) or 0)
                except Exception:
                    icon_id = 0
                return icon_id
            
            thumb = pcoll.load(entry_id, path, 'IMAGE', force_reload=bool(force_reload))
            return thumb.icon_id
        except Exception as e:
            if self._debug_enabled():
                print(f"[MatComposer] Preview load failed: id={entry_id} path={path} err={e}")
            return 0

    def try_load_entry_preview_icon_id(self, entry):
        if not isinstance(entry, dict):
            return 0
        try:
            existing = int(entry.get("_mc_preview_icon_id") or 0)
        except Exception:
            existing = 0
        if existing > 0:
            return existing

        entry_id = str(entry.get("id") or "")
        if not entry_id:
            return 0

        for p in self._thumb_path_candidates(entry):
            try:
                if not p or not os.path.exists(p):
                    continue
            except Exception:
                continue
            icon_id = self._load_thumb_from_disk(entry_id, p, force_reload=False)
            if icon_id <= 0:
                icon_id = self._load_thumb_via_image(entry_id, p)
            if self._debug_enabled() and icon_id <= 0:
                try:
                    pcoll = self._ensure_preview_collection()
                    raw_icon = 0
                    if pcoll and entry_id in pcoll:
                        raw_icon = int(getattr(pcoll[entry_id], "icon_id", 0) or 0)
                except Exception:
                    raw_icon = 0
                print(f"[MatComposer] Preview pending/empty: id={entry_id} icon_id={icon_id} pcoll_icon_id={raw_icon} path={p}")
            if icon_id > 0:
                entry["_mc_preview_icon_id"] = int(icon_id)
                return int(icon_id)
        return 0

    def ensure_entry_preview_icon_id(self, entry):
        if not isinstance(entry, dict):
            return 0
        
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            return 0
            
        # 1. Try Disk Cache
        thumb_path = self._get_thumb_path(entry)
        if os.path.exists(thumb_path):
            icon_id = self._load_thumb_from_disk(entry_id, thumb_path, force_reload=False)
            if icon_id <= 0:
                icon_id = self._load_thumb_via_image(entry_id, thumb_path)
            if icon_id > 0:
                entry["_mc_preview_icon_id"] = icon_id
                return icon_id

        # 2. Slow Path: Load Material
        self._cleanup_preview_materials()
        
        asset_type = str(entry.get("asset_type") or "MATERIAL")
        full_path = entry.get("full_path")
        source_path = entry.get("source_path") or full_path
        name = entry.get("name")
        if not full_path or not name or asset_type != "MATERIAL":
            entry["_mc_preview_icon_id"] = 0
            return 0
        full_path = self._normalize_blend_path(full_path)

        icon_id = 0
        loaded = None
        preview_name = ""
        try:
            existing_names = {m.name for m in bpy.data.materials}
            data_to = None
            try:
                with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
                    if name in data_from.materials:
                        data_to.materials = [name]
            except Exception:
                temp_path = self._copy_to_temp(source_path)
                if temp_path:
                    full_path = self._normalize_blend_path(temp_path)
                    entry["full_path"] = temp_path
                    with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
                        if name in data_from.materials:
                            data_to.materials = [name]
            loaded = data_to.materials[0] if getattr(data_to, "materials", None) else None
            if loaded:
                try:
                    # Force preview generation
                    loaded.preview_ensure()
                    prev = loaded.preview
                    if prev:
                        # Save to disk
                        w, h = prev.image_size
                        pix = list(prev.image_pixels)
                        if self._save_pixels_to_png(pix, w, h, thumb_path):
                            # Load back from disk
                            icon_id = self._load_thumb_from_disk(entry_id, thumb_path, force_reload=True)
                            if icon_id <= 0 and os.path.exists(thumb_path):
                                icon_id = self._load_thumb_via_image(entry_id, thumb_path)
                        else:
                            # Fallback to direct ID (session only)
                            icon_id = prev.icon_id
                            if icon_id > 0:
                                self._remember_preview_material(loaded.name)
                                icon_id = self._cache_custom_preview_icon(entry, icon_id)
                except Exception:
                    icon_id = 0
        except Exception:
            icon_id = 0
        finally:
            try:
                # Always remove loaded material if we saved to disk or failed
                # If we fell back to session ID, we might need to keep it? 
                # Actually, if we use session ID, we called _remember_preview_material
                # which keeps it in LRU. 
                # If we saved to disk, we can remove it.
                
                saved_to_disk = os.path.exists(thumb_path) and icon_id > 0
                
                should_remove = False
                if loaded and loaded.name not in existing_names:
                     if saved_to_disk:
                         should_remove = True
                     elif not self._preview_material_lru:
                         should_remove = True
                     elif loaded.name not in self._preview_material_lru:
                         should_remove = True
                         
                if should_remove:
                    bpy.data.materials.remove(loaded, do_unlink=True)
            except Exception:
                pass

        entry["_mc_preview_icon_id"] = int(icon_id or 0)
        return int(icon_id or 0)

    def _cache_custom_preview_icon(self, entry, icon_id):
        try:
            icon_id = int(icon_id or 0)
        except Exception:
            icon_id = 0
        if icon_id <= 0:
            return 0
        pcoll = self._ensure_preview_collection()
        if not pcoll:
            return icon_id
        key = str(entry.get("id") or "")
        if not key:
            return icon_id
        try:
            img = pcoll.get(key)
            if img is None:
                pcoll.new(key)
                img = pcoll.get(key)
            if img is not None:
                img.icon_id = icon_id
        except Exception:
            pass
        return icon_id

    def _first_str(self, data, keys):
        if not isinstance(data, dict):
            return ""
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                inner = v.get("url") or v.get("href") or v.get("path")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return ""

    def _first_list(self, data, keys):
        if not isinstance(data, dict):
            return []
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str) and v.strip():
                parts = [p.strip() for p in v.replace(",", " ").split(" ") if p.strip()]
                return parts
        return []
        
    def _normalize_catalog_uuid(self, value):
        s = str(value or "").strip()
        if not s:
            return ""
        if s.startswith("AssetCatalogID(") and s.endswith(")"):
            inner = s[len("AssetCatalogID(") : -1].strip()
            s = inner.strip().strip("'\"")
        if s.startswith("UUID(") and s.endswith(")"):
            inner = s[len("UUID(") : -1].strip()
            s = inner.strip().strip("'\"")
        s = s.strip().strip("{}").strip().strip("'\"")
        return s.lower()

    def _entry_clip_key_candidates(self, entry):
        if not isinstance(entry, dict):
            return []
        group = str(entry.get("catalog_path") or "").replace("\\", "/").strip().strip("/")
        name = str(entry.get("name") or "").strip()
        if not name:
            return []

        candidates = []
        if group:
            candidates.append(f"{group}:{name}")
            first = group.split("/", 1)[0].strip()
            if first and first != group:
                candidates.append(f"{first}:{name}")

            if group.startswith("MyMaterial") and not group.startswith("MyMaterials"):
                alt = "MyMaterials" + group[len("MyMaterial") :]
                candidates.append(f"{alt}:{name}")
                first_alt = alt.split("/", 1)[0].strip()
                if first_alt and first_alt != alt:
                    candidates.append(f"{first_alt}:{name}")
            elif group.startswith("MyMaterials") and not group.startswith("MyMaterial"):
                alt = "MyMaterial" + group[len("MyMaterials") :]
                candidates.append(f"{alt}:{name}")
                first_alt = alt.split("/", 1)[0].strip()
                if first_alt and first_alt != alt:
                    candidates.append(f"{first_alt}:{name}")

        candidates.append(f"MyMaterials:{name}")
        candidates.append(f"MyMaterial:{name}")
        candidates.append(name)

        out = []
        seen = set()
        for k in candidates:
            kk = str(k or "").strip()
            if not kk or kk in seen:
                continue
            seen.add(kk)
            out.append(kk)
        return out

    def _ensure_clip_vectors_loaded(self):
        if self._clip_loaded:
            return
        self._clip_loaded = True
        self._clip_key_to_vec = {}
        clip_path = self._first_existing_cache_file("clip_vectors.json")
        if not clip_path:
            return
        try:
            with open(clip_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        items = None
        if isinstance(data, dict):
            items = data.get("items")
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            key = str(it.get("key") or "").strip()
            vec = it.get("image_vec")
            if not key or not isinstance(vec, list) or not vec:
                continue
            if not all(isinstance(x, (int, float)) for x in vec):
                continue
            try:
                self._clip_key_to_vec[key] = [float(x) for x in vec]
            except Exception:
                continue

    def _ensure_gnn_vectors_loaded(self):
        if self._gnn_loaded:
            return
        self._gnn_loaded = True
        self._gnn_key_to_vec = {}
        gnn_path = self._first_existing_cache_file("gnn_vectors.json")
        if not gnn_path:
            return
        try:
            with open(gnn_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if isinstance(data, dict) and isinstance(data.get("items"), list):
            for it in data.get("items") or []:
                if not isinstance(it, dict):
                    continue
                key = str(it.get("key") or "").strip()
                vec = it.get("vec") or it.get("gnn_vec") or it.get("graph_vec")
                if not key or not isinstance(vec, list) or not vec:
                    continue
                if not all(isinstance(x, (int, float)) for x in vec):
                    continue
                try:
                    self._gnn_key_to_vec[key] = [float(x) for x in vec]
                except Exception:
                    continue
            return

        if isinstance(data, dict):
            for k, v in data.items():
                key = str(k or "").strip()
                vec = v
                if not key or not isinstance(vec, list) or not vec:
                    continue
                if not all(isinstance(x, (int, float)) for x in vec):
                    continue
                try:
                    self._gnn_key_to_vec[key] = [float(x) for x in vec]
                except Exception:
                    continue

    def attach_clip_vectors_to_entries(self):
        self._ensure_clip_vectors_loaded()
        if not self._clip_key_to_vec:
            return 0
        attached = 0
        for e in self.index_data:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("_mc_clip_vec"), list) and e.get("_mc_clip_vec"):
                continue
            for key in self._entry_clip_key_candidates(e):
                vec = self._clip_key_to_vec.get(key)
                if not vec:
                    continue
                e["_mc_clip_key"] = key
                e["_mc_clip_vec"] = vec
                attached += 1
                break
        return attached

    def attach_gnn_vectors_to_entries(self):
        self._ensure_gnn_vectors_loaded()
        if not self._gnn_key_to_vec:
            return 0
        attached = 0
        for e in self.index_data:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("_mc_gnn_vec"), list) and e.get("_mc_gnn_vec"):
                continue
            for key in self._entry_clip_key_candidates(e):
                vec = self._gnn_key_to_vec.get(key)
                if not vec:
                    continue
                e["_mc_gnn_key"] = key
                e["_mc_gnn_vec"] = vec
                attached += 1
                break
        return attached

    def scan_asset_libraries(self):
        """Scan all registered Asset Libraries in Blender preferences."""
        self.index_data = []
        self._id_index = {}
        libraries = bpy.context.preferences.filepaths.asset_libraries
        catalog_prefix = "MyMaterial"
        prefix_norm = str(catalog_prefix).strip().strip("/").lower()

        count = 0
        for lib in libraries:
            path = lib.path
            if path.startswith("//"):
                path = bpy.path.abspath(path)

            if not os.path.exists(path):
                print(f"[MatComposer] Warning: Asset Library path not found: {path}")
                continue

            catalog_map = self._read_catalog_map(path)
            if not catalog_map:
                print(f"[MatComposer] Warning: No catalog file found in '{path}'. Skipping (cannot filter '{catalog_prefix}').")
                continue
            if prefix_norm:
                has_prefix = False
                for p in catalog_map.values():
                    pp = str(p or "").strip().strip("/").lower()
                    if pp == prefix_norm or pp.startswith(prefix_norm + "/"):
                        has_prefix = True
                        break
                if not has_prefix:
                    continue
            print(f"[MatComposer] Scanning Asset Library: {lib.name} ({path})")
            count += self._scan_directory(path, lib.name, catalog_map, catalog_prefix=catalog_prefix)

        try:
            self.attach_clip_vectors_to_entries()
        except Exception:
            pass
        try:
            self.attach_gnn_vectors_to_entries()
        except Exception:
            pass
        return count

    def _read_catalog_map(self, library_root):
        file_path = os.path.join(library_root, "blender_assets.cats.txt")
        if not os.path.exists(file_path):
            return {}
        out = {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for raw in f.readlines():
                    line = str(raw or "").strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.upper().startswith("VERSION"):
                        continue
                    parts = line.split(":", 2)
                    if len(parts) < 2:
                        continue
                    uuid = self._normalize_catalog_uuid(parts[0])
                    path = parts[1].strip().strip("/")
                    if uuid and uuid not in out and path:
                        out[uuid] = path
        except Exception:
            return {}
        return out

    def _scan_directory(self, folder_path, library_name, catalog_map, catalog_prefix=None):
        """Scan a directory for blend files and extract material info."""
        count = 0
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.endswith(".blend"):
                    full_path = os.path.join(root, file)
                    # rel_path = os.path.relpath(full_path, folder_path)
                    
                    added = self._scan_blend_file(full_path, library_name, catalog_map, catalog_prefix=catalog_prefix)
                    if added:
                        count += added
        return count
        
    def _scan_blend_file(self, full_path, library_name, catalog_map, catalog_prefix=None):
        """Extract material info from a single blend file."""
        added_count = 0
        source_path = str(full_path or "")
        full_path = self._normalize_blend_path(full_path)
        try:
            if not self._is_valid_blend_header(full_path):
                backup = self._find_backup_blend(full_path)
                if backup:
                    full_path = self._normalize_blend_path(backup)
                else:
                    raise Exception("Invalid blend header")

            def _get_mat_names(path_to_use, use_assets_only):
                with bpy.data.libraries.load(path_to_use, link=False, assets_only=use_assets_only) as (data_from, data_to):
                    raw_mats = list(getattr(data_from, "materials", []) or [])
                out = []
                for m in raw_mats:
                    if hasattr(m, "name"):
                        name = str(getattr(m, "name", "") or "")
                    else:
                        name = str(m or "")
                    if name:
                        out.append(name)
                return out

            errors = []
            mat_names = None
            used_assets_only = True
            load_path = full_path
            for use_assets_only in (True, False):
                try:
                    mat_names = _get_mat_names(load_path, use_assets_only)
                    used_assets_only = use_assets_only
                    break
                except Exception as e:
                    errors.append(str(e))
                    mat_names = None
            if not mat_names:
                temp_path = self._copy_to_temp(full_path)
                if temp_path:
                    for use_assets_only in (True, False):
                        try:
                            mat_names = _get_mat_names(temp_path, use_assets_only)
                            used_assets_only = use_assets_only
                            load_path = temp_path
                            break
                        except Exception as e:
                            errors.append(str(e))
                            mat_names = None

            if not mat_names:
                raise Exception(" | ".join([e for e in errors if e]))

            safe_lib = library_name.replace(" ", "_").lower()
            filename = os.path.basename(full_path)
            prefix_norm = str(catalog_prefix or "").strip().strip("/").lower()
            existing_names = {m.name for m in bpy.data.materials}

            batch_size = 24
            for i in range(0, len(mat_names), batch_size):
                batch = [str(n) for n in mat_names[i : i + batch_size] if str(n)]
                if not batch:
                    continue

                with bpy.data.libraries.load(load_path, link=False, assets_only=used_assets_only) as (_df, _dt):
                    _dt.materials = batch
                loaded_mats = list(getattr(_dt, "materials", []) or [])

                for requested_name, loaded in zip(batch, loaded_mats):
                    requested_name = str(getattr(requested_name, "name", requested_name) or "")
                    if not requested_name:
                        continue
                    if not loaded:
                        continue

                    catalog_id = ""
                    try:
                        catalog_id = str(getattr(getattr(loaded, "asset_data", None), "catalog_id", "") or "")
                    except Exception:
                        catalog_id = ""
                    catalog_id = self._normalize_catalog_uuid(catalog_id)
                    catalog_path = str(catalog_map.get(catalog_id) or "").strip().strip("/")

                    if prefix_norm:
                        p = catalog_path.lower()
                        if not (p == prefix_norm or p.startswith(prefix_norm + "/")):
                            continue

                    safe_mat = str(requested_name).replace(" ", "_").lower()
                    entry_id = f"{safe_lib}_{filename}_material_{safe_mat}"

                    # Extract Blender Asset Tags
                    asset_tags = []
                    try:
                        if getattr(loaded, "asset_data", None):
                            asset_tags = [str(t.name) for t in getattr(loaded.asset_data, "tags", [])]
                    except Exception:
                        pass

                    tag_bucket = ["scanned", library_name, "material"]
                    if catalog_path:
                        tag_bucket.append(catalog_path)
                        tag_bucket.extend([p for p in str(catalog_path).replace("\\", "/").split("/") if p])
                    if filename:
                        tag_bucket.append(filename)
                    if requested_name:
                        tag_bucket.append(requested_name)
                    
                    if asset_tags:
                        tag_bucket.extend(asset_tags)

                    tag_bucket = [str(t).strip() for t in tag_bucket if str(t).strip()]
                    tag_bucket = list(dict.fromkeys(tag_bucket))

                    entry = {
                        "id": entry_id,
                        "asset_type": "MATERIAL",
                        "name": requested_name,
                        "library_name": library_name,
                        "full_path": load_path,
                        "source_path": source_path,
                        "catalog_path": catalog_path,
                        "description": f"Material '{requested_name}' from library '{library_name}' (File: {filename})",
                        "tags": tag_bucket,
                        "asset_tags": asset_tags,
                        "parameters": {}
                    }
                    self.index_data.append(entry)
                    self._id_index[entry_id] = entry
                    added_count += 1

                for loaded in loaded_mats:
                    try:
                        if loaded and loaded.name not in existing_names:
                            bpy.data.materials.remove(loaded, do_unlink=True)
                    except Exception:
                        pass
        except Exception as e:
            msg = str(e)
            header = self._read_blend_header(full_path)
            size = 0
            try:
                size = os.path.getsize(full_path)
            except Exception:
                size = 0
            print(f"[MatComposer] Failed to read {full_path}: {msg} | size={size} | header={header!r}")
            
        return added_count

    def get_all_templates(self):
        """Return a list of dicts with 'id', 'name', 'description' for the LLM."""
        templates = []
        for item in self.index_data:
            templates.append({
                "id": item.get("id"),
                "asset_type": item.get("asset_type", "MATERIAL"),
                "name": item.get("name"),
                "description": item.get("description", ""),
                "tags": item.get("tags", [])
            })
        return templates

    def get_lightweight_index(self, limit=200):
        """Return a simplified list of all templates (ID and Name only) for LLM context."""
        templates = []
        for item in self.index_data[:limit]:
            templates.append({
                "id": item.get("id"),
                "asset_type": item.get("asset_type", "MATERIAL"),
                "name": item.get("name"),
                # "tags": item.get("tags", []) # Tags might be useful too
            })
        return templates

    def search_templates(self, query, limit=10):
        """Search templates by query (Simple RAG Lite)."""
        if not query:
            return self.get_all_templates()[:limit]
            
        query_terms = query.lower().split()
        scored_items = []
        
        for item in self.index_data:
            score = 0
            # Simple scoring: +10 for name match, +1 for description/tag match
            name = item.get("name", "").lower()
            desc = item.get("description", "").lower()
            tags = [t.lower() for t in item.get("tags", [])]
            
            for term in query_terms:
                if term in name:
                    score += 10
                if term in desc:
                    score += 1
                for tag in tags:
                    if term in tag:
                        score += 2
                        
            if score > 0:
                scored_items.append((score, item))
        
        # Sort by score desc
        scored_items.sort(key=lambda x: x[0], reverse=True)
        
        # Return top N formatted
        templates = []
        for score, item in scored_items[:limit]:
            templates.append({
                "id": item.get("id"),
                "asset_type": item.get("asset_type", "MATERIAL"),
                "name": item.get("name"),
                "description": item.get("description", ""),
                "tags": item.get("tags", [])
            })
            
        return templates
        
    def get_entry_by_id(self, template_id):
        if not template_id:
            return None
        item = self._id_index.get(template_id)
        if item:
            return item
        for it in self.index_data:
            if it.get("id") == template_id:
                self._id_index[template_id] = it
                return it
        return None

    def ensure_entry_complexity(self, entry):
        if not isinstance(entry, dict):
            return 0.0
        if "complexity_norm" in entry and "k_vector" in entry:
            try:
                return float(entry.get("complexity_norm") or 0.0)
            except Exception:
                return 0.0

        asset_type = str(entry.get("asset_type") or "MATERIAL")
        full_path = entry.get("full_path")
        name = entry.get("name")
        if not full_path or not name:
            entry["complexity_nodes"] = 0
            entry["complexity_norm"] = 0.0
            return 0.0

        topology = {}
        if asset_type == "NODE_GROUP":
            topology = self._inspect_nodegroup_node_count(full_path, name)
        else:
            topology = self._inspect_material_node_count(full_path, name)

        if not isinstance(topology, dict):
            # Fallback for safety
            nodes = int(topology) if isinstance(topology, (int, float)) else 0
            topology = {"node_count": nodes}
        
        entry["k_topology"] = topology
        nodes = topology.get("node_count", 0)

        # Compute Structural Vector
        try:
            # Create a minimal representation wrapper to use the helper
            dummy_rep = semantic_init.MaterialRepresentation(
                raw_text="", tags=(), slots=(), s_vector=(), k_topology=topology
            )
            k_vec = semantic_init.get_structural_vector(dummy_rep)
            entry["k_vector"] = k_vec
        except Exception:
            entry["k_vector"] = [0.0] * 6

        entry["complexity_nodes"] = int(nodes)
        entry["complexity_norm"] = self._normalize_complexity(nodes)
        return float(entry["complexity_norm"])


    def get_structural_info(self, entry):
        """
        Returns structural badges info for UI display.
        Returns list of dicts: {'label': str, 'value': float, 'desc': str, 'color': (r,g,b,a)}
        """
        if not isinstance(entry, dict):
            return []
        
        vec = entry.get("k_vector")
        if not vec or len(vec) < 6:
            return []
            
        # 6-dim vector:
        # 0. Node Count (0-1)
        # 1. Structure Depth (0-1)
        # 2. Branching Factor (0-1)
        # 3. Main-path Dominance (0-1)
        # 4. Procedural Generator Ratio (0-1)
        # 5. Math-Transform Ratio (0-1)
        
        badges = []
        
        # Helper to format level
        def get_level(val):
            if val < 0.3: return "L", (0.5, 0.5, 0.5, 1.0) # Low
            if val < 0.7: return "M", (0.2, 0.6, 0.8, 1.0) # Med
            return "H", (0.8, 0.4, 0.2, 1.0) # High

        # Node Count
        lvl, col = get_level(vec[0])
        badges.append({'label': f"N:{lvl}", 'value': vec[0], 'desc': f"Node Count: {vec[0]:.2f}", 'color': col})

        # Depth
        lvl, col = get_level(vec[1])
        badges.append({'label': f"D:{lvl}", 'value': vec[1], 'desc': f"Depth: {vec[1]:.2f}", 'color': col})

        # Branching
        lvl, col = get_level(vec[2])
        badges.append({'label': f"B:{lvl}", 'value': vec[2], 'desc': f"Branching: {vec[2]:.2f}", 'color': col})

        # Procedural Generator Ratio
        lvl, col = get_level(vec[4])
        badges.append({'label': f"P:{lvl}", 'value': vec[4], 'desc': f"Procedural: {vec[4]:.2f}", 'color': col})
        
        return badges

    def get_structural_diff_explanation(self, entry_a, entry_b):
        """
        Returns a text explanation of structural differences between two entries.
        Used for Directional Exploration feedback.
        """
        if not entry_a or not entry_b:
            return "No comparison data."
            
        vec_a = entry_a.get("k_vector", [0] * 6)
        vec_b = entry_b.get("k_vector", [0] * 6)
        
        if len(vec_a) < 6 or len(vec_b) < 6:
            return "Missing structural data."
            
        diffs = []
        labels = ["Node Count", "Depth", "Branching", "Main-path", "Procedural", "Math-Transform"]
        
        for i, label in enumerate(labels):
            delta = vec_b[i] - vec_a[i]
            if abs(delta) > 0.15: # Significant change threshold
                direction = "increased" if delta > 0 else "decreased"
                diffs.append(f"{label} {direction} ({delta:+.2f})")
                
        if not diffs:
            return "Structure is similar."
            
        return "Changes: " + ", ".join(diffs)

    def _normalize_complexity(self, node_count):
        try:
            node_count = max(0, int(node_count))
        except Exception:
            node_count = 0
        max_nodes = 220
        return float(min(1.0, math.log1p(node_count) / math.log1p(max_nodes)))

    def _inspect_material_node_count(self, full_path, mat_name):
        existing_names = {m.name for m in bpy.data.materials}
        loaded_mat = None
        full_path = self._normalize_blend_path(full_path)
        try:
            with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
                if mat_name in data_from.materials:
                    data_to.materials = [mat_name]
            if getattr(locals().get("data_to", None), "materials", None):
                mats = data_to.materials
                loaded_mat = mats[0] if mats else None
            if not loaded_mat:
                loaded_mat = bpy.data.materials.get(mat_name)
            if not loaded_mat or not getattr(loaded_mat, "use_nodes", False):
                return {}
            tree = loaded_mat.node_tree
            if not tree:
                return {}
            return semantic_init.build_k_topology_from_node_tree(tree)
        except Exception:
            return {}
        finally:
            try:
                if loaded_mat and loaded_mat.name not in existing_names:
                    bpy.data.materials.remove(loaded_mat, do_unlink=True)
            except Exception:
                pass

    def _inspect_nodegroup_node_count(self, full_path, group_name):
        existing_names = {g.name for g in bpy.data.node_groups}
        loaded_group = None
        full_path = self._normalize_blend_path(full_path)
        try:
            with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
                if group_name in getattr(data_from, "node_groups", []) or []:
                    data_to.node_groups = [group_name]
            if getattr(locals().get("data_to", None), "node_groups", None):
                groups = data_to.node_groups
                loaded_group = groups[0] if groups else None
            if not loaded_group:
                loaded_group = bpy.data.node_groups.get(group_name)
            if not loaded_group:
                return {}
            return semantic_init.build_k_topology_from_node_tree(loaded_group)
        except Exception:
            return {}
        finally:
            try:
                if loaded_group and loaded_group.name not in existing_names:
                    bpy.data.node_groups.remove(loaded_group, do_unlink=True)
            except Exception:
                pass

library_manager = LibraryManager()
