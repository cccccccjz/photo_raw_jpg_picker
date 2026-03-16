import os
import shutil
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

JPG_EXTS = {".jpg", ".jpeg"}
RAW_EXTS = {".cr3", ".cr2", ".nef", ".arw", ".rw2", ".orf", ".raf", ".dng"}

JPG_DIR_NAME = "JPG_待筛选"
RAW_DIR_NAME = "RAW_原片"
RAW_SELECTED_DIR_NAME = "RAW_已同步"


class PhotoSyncApp:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.title("照片筛选同步工具（JPG/RAW）")
        self.master.geometry("760x520")

        self.root_var = tk.StringVar()
        self.running = False

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

        self.sync_btn = tk.Button(btns, text="2) 根据筛选后的 JPG 同步 RAW", command=self.start_sync)
        self.sync_btn.pack(side="left", padx=(0, 8))

        self.open_btn = tk.Button(btns, text="打开工作目录", command=self.open_work_dir)
        self.open_btn.pack(side="left")

        tip = (
            "使用步骤：\n"
            f"① 先点击【分开存储 JPG/RAW】。程序会在根目录下创建 {JPG_DIR_NAME}、{RAW_DIR_NAME}。\n"
            f"② 去 {JPG_DIR_NAME} 里手动删除不想要的 JPG（只保留你选中的）。\n"
            f"③ 点击【根据筛选后的 JPG 同步 RAW】。程序会把同名 RAW 移动到 {RAW_SELECTED_DIR_NAME}。\n\n"
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

    def split_files(self, root: Path):
        jpg_dir = root / JPG_DIR_NAME
        raw_dir = root / RAW_DIR_NAME
        raw_selected_dir = root / RAW_SELECTED_DIR_NAME

        jpg_dir.mkdir(exist_ok=True)
        raw_dir.mkdir(exist_ok=True)
        raw_selected_dir.mkdir(exist_ok=True)

        skipped_dirs = {jpg_dir.resolve(), raw_dir.resolve(), raw_selected_dir.resolve()}

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
        self._log(f"请到 {JPG_DIR_NAME} 中手动删除不需要的 JPG，然后执行第 2 步。")

    def sync_raw(self, root: Path):
        jpg_dir = root / JPG_DIR_NAME
        raw_dir = root / RAW_DIR_NAME
        raw_selected_dir = root / RAW_SELECTED_DIR_NAME

        if not jpg_dir.exists() or not raw_dir.exists():
            messagebox.showwarning("提示", "请先执行第 1 步：分开存储 JPG/RAW")
            return

        raw_selected_dir.mkdir(exist_ok=True)

        self._log("开始读取筛选后的 JPG 列表...")

        selected_stems = set()
        with os.scandir(jpg_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    p = Path(entry.path)
                    if p.suffix.lower() in JPG_EXTS:
                        selected_stems.add(p.stem)

        self._log(f"筛选后的 JPG 数量：{len(selected_stems)}")

        moved = 0
        miss = 0

        # 为了高效：一次遍历 RAW_原片 并按 stem 建映射
        raw_map = {}
        with os.scandir(raw_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    p = Path(entry.path)
                    if p.suffix.lower() in RAW_EXTS:
                        raw_map[p.stem] = p

        for stem in selected_stems:
            src = raw_map.get(stem)
            if src is None:
                miss += 1
                continue
            target = self._safe_target(raw_selected_dir, src.name)
            self._fast_move(src, target)
            moved += 1

        self._log(f"同步完成：已移动同名 RAW={moved}，缺失同名 RAW={miss}")
        self._log(f"结果目录：{raw_selected_dir}")

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
