import os
import shutil
import threading
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    Image = None
    ImageOps = None
    ImageTk = None

JPG_EXTS = {".jpg", ".jpeg"}
RAW_EXTS = {".cr3", ".cr2", ".nef", ".arw", ".rw2", ".orf", ".raf", ".dng"}

JPG_DIR_NAME = "JPG_待筛选"
RAW_DIR_NAME = "RAW_原片"
RAW_RETOUCH_DIR_NAME = "RAW_1_精修"
RAW_COLOR_DIR_NAME = "RAW_2_调色"
RAW_DELETE_DIR_NAME = "RAW_3_删除"
RATING_FILE_NAME = "jpg_ratings.json"


class PhotoSyncApp:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.title("照片筛选同步工具（JPG/RAW）")
        self.master.geometry("760x520")

        self.root_var = tk.StringVar()
        self.running = False
        self.rating_window = None
        self.rating_state = None

        self._build_ui()

    def _build_ui(self):
        top = tk.Frame(self.master)
        top.pack(fill="x", padx=12, pady=10)

        tk.Label(top, text="照片根目录：").pack(side="left")

        entry = tk.Entry(top, textvariable=self.root_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)

        tk.Button(top, text="选择文件夹", command=self.choose_dir).pack(side="left")

        btns = tk.Frame(self.master)
        btns.pack(fill="x", padx=12, pady=(0, 8))

        self.split_btn = tk.Button(btns, text="1) 分开存储 JPG/RAW", command=self.start_split)
        self.split_btn.pack(side="left", padx=(0, 8))

        self.rate_btn = tk.Button(btns, text="2) 查看 JPG 并打分", command=self.open_rating)
        self.rate_btn.pack(side="left", padx=(0, 8))

        self.sync_btn = tk.Button(btns, text="3) 根据评分同步 RAW", command=self.start_sync)
        self.sync_btn.pack(side="left", padx=(0, 8))

        self.open_btn = tk.Button(btns, text="打开工作目录", command=self.open_work_dir)
        self.open_btn.pack(side="left")

        tip = (
            "使用步骤：\n"
            f"① 先点击【分开存储 JPG/RAW】。程序会在根目录下创建 {JPG_DIR_NAME}、{RAW_DIR_NAME}。\n"
            f"② 点击【查看 JPG 并打分】，给每张 JPG 标记 1/2/3。\n"
            f"③ 点击【根据评分同步 RAW】。程序会把同名 RAW 分别移动到\n"
            f"   {RAW_RETOUCH_DIR_NAME}（1=精修）、{RAW_COLOR_DIR_NAME}（2=调色）、{RAW_DELETE_DIR_NAME}（3=删除）。\n\n"
            "性能说明：移动文件优先使用同盘重命名（速度快，不复制大文件内容）。"
        )
        tk.Label(self.master, text=tip, justify="left", anchor="w").pack(fill="x", padx=12)

        self.log = ScrolledText(self.master, height=18)
        self.log.pack(fill="both", expand=True, padx=12, pady=10)

    def choose_dir(self):
        d = filedialog.askdirectory(title="选择照片根目录")
        if d:
            self.root_var.set(d)
            self._log(f"已选择目录：{d}")

    def open_work_dir(self):
        root = self._get_root_path()
        if not root:
            return
        os.startfile(str(root))

    def _get_root_path(self):
        p = self.root_var.get().strip().strip('"')
        if not p:
            messagebox.showwarning("提示", "请先选择照片根目录")
            return None
        root = Path(p)
        if not root.exists() or not root.is_dir():
            messagebox.showerror("错误", "目录不存在或不可用")
            return None
        return root

    def _set_running(self, value: bool):
        self.running = value
        state = "disabled" if value else "normal"
        self.split_btn.config(state=state)
        self.rate_btn.config(state=state)
        self.sync_btn.config(state=state)

    def _run_background(self, fn):
        if self.running:
            messagebox.showinfo("提示", "任务正在执行，请稍后")
            return

        self._set_running(True)

        def worker():
            try:
                fn()
            except Exception as e:
                self._log(f"[错误] {e}")
                messagebox.showerror("执行失败", str(e))
            finally:
                self.master.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    def start_split(self):
        root = self._get_root_path()
        if not root:
            return
        self._run_background(lambda: self.split_files(root))

    def start_sync(self):
        root = self._get_root_path()
        if not root:
            return
        self._run_background(lambda: self.sync_raw(root))

    def open_rating(self):
        root = self._get_root_path()
        if not root:
            return

        if Image is None or ImageTk is None:
            messagebox.showerror(
                "缺少依赖",
                "内置 JPG 预览需要 Pillow。\n请先执行：python -m pip install pillow",
            )
            return

        jpg_dir = root / JPG_DIR_NAME
        if not jpg_dir.exists():
            messagebox.showwarning("提示", "请先执行第 1 步：分开存储 JPG/RAW")
            return

        image_files = self._list_jpg_files(jpg_dir)
        if not image_files:
            messagebox.showinfo("提示", f"{JPG_DIR_NAME} 中没有 JPG 文件")
            return

        ratings = self._load_ratings(root)
        self.rating_state = {
            "root": root,
            "jpg_dir": jpg_dir,
            "images": image_files,
            "ratings": ratings,
            "index": 0,
            "current_photo": None,
            "current_path": None,
        }

        if self.rating_window and self.rating_window.winfo_exists():
            self.rating_window.focus_force()
            self._rating_jump_to_first_unrated()
            self._show_current_image()
            return

        win = tk.Toplevel(self.master)
        win.title("JPG 打分（1=精修，2=调色，3=删除）")
        win.geometry("1100x760")
        win.minsize(860, 600)
        win.protocol("WM_DELETE_WINDOW", self._close_rating_window)
        self.rating_window = win

        top = tk.Frame(win)
        top.pack(fill="x", padx=10, pady=8)

        self.rating_title_var = tk.StringVar(value="")
        self.rating_status_var = tk.StringVar(value="")

        tk.Label(top, textvariable=self.rating_title_var, anchor="w").pack(fill="x")
        tk.Label(top, textvariable=self.rating_status_var, anchor="w", fg="#555").pack(fill="x", pady=(2, 0))

        preview_wrap = tk.Frame(win, bg="#1e1e1e")
        preview_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self.preview_label = tk.Label(preview_wrap, bg="#1e1e1e", fg="#e6e6e6", text="加载中...")
        self.preview_label.pack(fill="both", expand=True, padx=10, pady=10)

        controls = tk.Frame(win)
        controls.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(controls, text="上一张 ←", command=self._prev_image, width=12).pack(side="left")
        tk.Button(controls, text="下一张 →", command=self._next_image, width=12).pack(side="left", padx=(6, 12))
        tk.Button(controls, text="1 精修", command=lambda: self._set_rating(1), width=10).pack(side="left")
        tk.Button(controls, text="2 调色", command=lambda: self._set_rating(2), width=10).pack(side="left", padx=6)
        tk.Button(controls, text="3 删除", command=lambda: self._set_rating(3), width=10).pack(side="left")
        tk.Button(controls, text="清除评分", command=self._clear_rating, width=10).pack(side="left", padx=(12, 0))
        tk.Button(controls, text="关闭", command=self._close_rating_window, width=10).pack(side="right")

        win.bind("<Left>", lambda _e: self._prev_image())
        win.bind("<Right>", lambda _e: self._next_image())
        win.bind("1", lambda _e: self._set_rating(1))
        win.bind("2", lambda _e: self._set_rating(2))
        win.bind("3", lambda _e: self._set_rating(3))

        self._rating_jump_to_first_unrated()
        win.after(50, self._show_current_image)

    def _close_rating_window(self):
        if self.rating_state:
            self._save_ratings(self.rating_state["root"], self.rating_state["ratings"])
        if self.rating_window and self.rating_window.winfo_exists():
            self.rating_window.destroy()
        self.rating_window = None

    def _list_jpg_files(self, jpg_dir: Path):
        files = []
        with os.scandir(jpg_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    p = Path(entry.path)
                    if p.suffix.lower() in JPG_EXTS:
                        files.append(p)
        files.sort(key=lambda x: x.name.lower())
        return files

    @staticmethod
    def _rating_file(root: Path) -> Path:
        return root / RATING_FILE_NAME

    def _load_ratings(self, root: Path):
        rating_file = self._rating_file(root)
        if not rating_file.exists():
            return {}

        try:
            data = json.loads(rating_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}

            clean = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, int) and v in {1, 2, 3}:
                    clean[k] = v
            return clean
        except Exception:
            return {}

    def _save_ratings(self, root: Path, ratings):
        rating_file = self._rating_file(root)
        payload = json.dumps(ratings, ensure_ascii=False, indent=2)
        rating_file.write_text(payload, encoding="utf-8")

    def _rating_jump_to_first_unrated(self):
        if not self.rating_state:
            return
        images = self.rating_state["images"]
        ratings = self.rating_state["ratings"]

        for i, p in enumerate(images):
            if p.stem not in ratings:
                self.rating_state["index"] = i
                return
        self.rating_state["index"] = 0

    def _current_image_path(self):
        if not self.rating_state:
            return None
        images = self.rating_state["images"]
        if not images:
            return None
        i = self.rating_state["index"]
        i = max(0, min(i, len(images) - 1))
        self.rating_state["index"] = i
        return images[i]

    def _show_current_image(self):
        if not self.rating_state or not self.rating_window or not self.rating_window.winfo_exists():
            return

        path = self._current_image_path()
        if path is None:
            self.preview_label.config(text="没有可预览的图片", image="")
            return

        images = self.rating_state["images"]
        ratings = self.rating_state["ratings"]
        idx = self.rating_state["index"]

        score = ratings.get(path.stem)
        score_text = "未评分" if score is None else f"已评分：{score}"
        rated_count = sum(1 for p in images if p.stem in ratings)

        self.rating_title_var.set(f"{idx + 1}/{len(images)}  {path.name}")
        self.rating_status_var.set(f"{score_text}  |  已评分 {rated_count}/{len(images)}")

        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)

            box_w = max(self.preview_label.winfo_width() - 24, 200)
            box_h = max(self.preview_label.winfo_height() - 24, 200)
            if hasattr(Image, "Resampling"):
                resample = Image.Resampling.LANCZOS
            else:
                resample = Image.LANCZOS
            img.thumbnail((box_w, box_h), resample)

            tk_img = ImageTk.PhotoImage(img)
            self.rating_state["current_photo"] = tk_img
            self.rating_state["current_path"] = path
            self.preview_label.config(image=tk_img, text="")
        except Exception as e:
            self.preview_label.config(image="", text=f"无法加载图片：{path.name}\n{e}")

    def _prev_image(self):
        if not self.rating_state:
            return
        self.rating_state["index"] -= 1
        self._show_current_image()

    def _next_image(self):
        if not self.rating_state:
            return
        self.rating_state["index"] += 1
        self._show_current_image()

    def _set_rating(self, score: int):
        if not self.rating_state:
            return
        path = self._current_image_path()
        if path is None:
            return

        self.rating_state["ratings"][path.stem] = score
        self._save_ratings(self.rating_state["root"], self.rating_state["ratings"])
        self._next_image()

    def _clear_rating(self):
        if not self.rating_state:
            return
        path = self._current_image_path()
        if path is None:
            return

        self.rating_state["ratings"].pop(path.stem, None)
        self._save_ratings(self.rating_state["root"], self.rating_state["ratings"])
        self._show_current_image()

    def split_files(self, root: Path):
        jpg_dir = root / JPG_DIR_NAME
        raw_dir = root / RAW_DIR_NAME
        raw_retouch_dir = root / RAW_RETOUCH_DIR_NAME
        raw_color_dir = root / RAW_COLOR_DIR_NAME
        raw_delete_dir = root / RAW_DELETE_DIR_NAME

        jpg_dir.mkdir(exist_ok=True)
        raw_dir.mkdir(exist_ok=True)
        raw_retouch_dir.mkdir(exist_ok=True)
        raw_color_dir.mkdir(exist_ok=True)
        raw_delete_dir.mkdir(exist_ok=True)

        skipped_dirs = {
            jpg_dir.resolve(),
            raw_dir.resolve(),
            raw_retouch_dir.resolve(),
            raw_color_dir.resolve(),
            raw_delete_dir.resolve(),
        }

        move_jpg = 0
        move_raw = 0
        skip_other = 0

        self._log("开始分拣文件...")

        with os.scandir(root) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    continue

                src = Path(entry.path)
                ext = src.suffix.lower()

                if ext in JPG_EXTS:
                    target = self._safe_target(jpg_dir, src.name)
                    self._fast_move(src, target)
                    move_jpg += 1
                elif ext in RAW_EXTS:
                    target = self._safe_target(raw_dir, src.name)
                    self._fast_move(src, target)
                    move_raw += 1
                else:
                    skip_other += 1

        self._log(f"分拣完成：JPG={move_jpg}，RAW={move_raw}，其他跳过={skip_other}")
        self._log(f"请执行第 2 步，在 {JPG_DIR_NAME} 中浏览 JPG 并打分。")

    def sync_raw(self, root: Path):
        jpg_dir = root / JPG_DIR_NAME
        raw_dir = root / RAW_DIR_NAME
        raw_retouch_dir = root / RAW_RETOUCH_DIR_NAME
        raw_color_dir = root / RAW_COLOR_DIR_NAME
        raw_delete_dir = root / RAW_DELETE_DIR_NAME

        if not jpg_dir.exists() or not raw_dir.exists():
            messagebox.showwarning("提示", "请先执行第 1 步：分开存储 JPG/RAW")
            return

        raw_retouch_dir.mkdir(exist_ok=True)
        raw_color_dir.mkdir(exist_ok=True)
        raw_delete_dir.mkdir(exist_ok=True)

        ratings = self._load_ratings(root)
        if not ratings:
            messagebox.showwarning("提示", "未找到评分数据，请先执行第 2 步给 JPG 打分")
            return

        self._log("开始读取 JPG 评分数据...")

        available_jpg_stems = {p.stem for p in self._list_jpg_files(jpg_dir)}
        rated_stems = {stem for stem in ratings if stem in available_jpg_stems}
        self._log(f"评分 JPG 数量（当前仍存在于 {JPG_DIR_NAME}）：{len(rated_stems)}")

        moved_1 = 0
        moved_2 = 0
        moved_3 = 0
        miss = 0

        # 为了高效：一次遍历 RAW_原片 并按 stem 建映射
        raw_map = {}
        with os.scandir(raw_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    p = Path(entry.path)
                    if p.suffix.lower() in RAW_EXTS:
                        raw_map[p.stem] = p

        target_map = {
            1: raw_retouch_dir,
            2: raw_color_dir,
            3: raw_delete_dir,
        }

        for stem in rated_stems:
            src = raw_map.get(stem)
            if src is None:
                miss += 1
                continue

            score = ratings.get(stem)
            dst_folder = target_map.get(score)
            if dst_folder is None:
                continue

            target = self._safe_target(dst_folder, src.name)
            self._fast_move(src, target)
            if score == 1:
                moved_1 += 1
            elif score == 2:
                moved_2 += 1
            elif score == 3:
                moved_3 += 1

        self._log(
            "同步完成："
            f"精修={moved_1}，调色={moved_2}，删除={moved_3}，缺失同名 RAW={miss}"
        )
        self._log(f"结果目录：{raw_retouch_dir} | {raw_color_dir} | {raw_delete_dir}")

    @staticmethod
    def _safe_target(folder: Path, filename: str) -> Path:
        target = folder / filename
        if not target.exists():
            return target

        stem = target.stem
        ext = target.suffix
        i = 1
        while True:
            new_target = folder / f"{stem}_{i}{ext}"
            if not new_target.exists():
                return new_target
            i += 1

    @staticmethod
    def _fast_move(src: Path, dst: Path):
        # 同磁盘场景下，这通常是元数据操作，速度很快
        try:
            os.replace(src, dst)
        except OSError:
            # 跨磁盘时回退为 move
            shutil.move(str(src), str(dst))

    def _log(self, msg: str):
        def append():
            self.log.insert("end", msg + "\n")
            self.log.see("end")

        self.master.after(0, append)


def main():
    root = tk.Tk()
    app = PhotoSyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
