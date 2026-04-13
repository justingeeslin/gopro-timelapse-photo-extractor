import os
import threading
import subprocess
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class FrameExtractorApp(tk.Tk):
	def __init__(self) -> None:
		super().__init__()
		self.title("Action Camera Timelapse Photo Extractor")
		self.geometry("720x430")
		self.minsize(680, 400)

		self.video_path = tk.StringVar()
		self.output_dir = tk.StringVar()
		self.prefix = tk.StringVar(value="frame")
		self.quality = tk.IntVar(value=2)  # 2 = high quality for ffmpeg MJPEG
		self.status_text = tk.StringVar(value="Select a action camera (ex. GoPro 360) video file to begin.")
		self.is_running = False

		self._build_ui()
		self._guess_default_output_dir()

	def _build_ui(self) -> None:
		container = ttk.Frame(self, padding=14)
		container.pack(fill="both", expand=True)

		ttk.Label(container, text="Action Camera Video → JPEG Frames", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(0, 12))

		file_frame = ttk.LabelFrame(container, text="Input Video", padding=10)
		file_frame.pack(fill="x", pady=(0, 10))

		ttk.Entry(file_frame, textvariable=self.video_path).pack(side="left", fill="x", expand=True, padx=(0, 8))
		ttk.Button(file_frame, text="Browse…", command=self.choose_video).pack(side="left")

		output_frame = ttk.LabelFrame(container, text="Output Folder", padding=10)
		output_frame.pack(fill="x", pady=(0, 10))

		ttk.Entry(output_frame, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=(0, 8))
		ttk.Button(output_frame, text="Browse…", command=self.choose_output_dir).pack(side="left")

		options = ttk.LabelFrame(container, text="Options", padding=10)
		options.pack(fill="x", pady=(0, 10))

		ttk.Label(options, text="Filename prefix:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
		ttk.Entry(options, textvariable=self.prefix, width=18).grid(row=0, column=1, sticky="w", pady=4)

		ttk.Label(options, text="JPEG quality (2=best, 31=lowest):").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
		ttk.Spinbox(options, from_=2, to=31, textvariable=self.quality, width=8).grid(row=1, column=1, sticky="w", pady=4)

		help_text = (
			"This app uses ffmpeg to extract every frame from the selected video as JPEG files.\n"
			"For a GoPro timelapse video, extracting every frame preserves each captured moment."
		)
		ttk.Label(container, text=help_text, justify="left").pack(anchor="w", pady=(0, 10))

		button_row = ttk.Frame(container)
		button_row.pack(fill="x", pady=(0, 10))

		ttk.Button(button_row, text="Open Output Folder", command=self.open_output_folder).pack(side="left")

		self.progress = ttk.Progressbar(button_row, mode="indeterminate", length=180)
		self.progress.pack(side="right", padx=(0, 10))
		self.progress.pack_forget()

		self.extract_button = ttk.Button(button_row, text="Extract Frames", command=self.start_extraction)
		self.extract_button.pack(side="right")

		status_frame = ttk.LabelFrame(container, text="Status", padding=10)
		status_frame.pack(fill="both", expand=True)

		self.status_label = ttk.Label(status_frame, textvariable=self.status_text, justify="left", anchor="nw")
		self.status_label.pack(fill="both", expand=True)

	def _guess_default_output_dir(self) -> None:
		home = Path.home()
		self.output_dir.set(str(home / "gopro_frames"))

	def choose_video(self) -> None:
		file_path = filedialog.askopenfilename(
			title="Choose a action camera video",
			filetypes=[
				("Video files", "*.mp4 *.mov *.mkv *.360"),
				("All files", "*.*"),
			],
		)
		if file_path:
			self.video_path.set(file_path)
			video_stem = Path(file_path).stem
			suggested = Path(self.output_dir.get()) / video_stem
			self.output_dir.set(str(suggested))
			self.status_text.set(f"Selected video: {file_path}")

	def choose_output_dir(self) -> None:
		directory = filedialog.askdirectory(title="Choose output folder")
		if directory:
			self.output_dir.set(directory)
			self.status_text.set(f"Selected output folder: {directory}")

	def open_output_folder(self) -> None:
		output = self.output_dir.get().strip()
		if not output:
			messagebox.showwarning("No folder", "Choose an output folder first.")
			return

		output_path = Path(output)
		if not output_path.exists():
			messagebox.showwarning("Folder not found", "The output folder does not exist yet.")
			return

		try:
			if os.name == "nt":
				os.startfile(str(output_path))
			elif shutil.which("open"):
				subprocess.Popen(["open", str(output_path)])
			else:
				subprocess.Popen(["xdg-open", str(output_path)])
		except Exception as exc:
			messagebox.showerror("Open folder failed", str(exc))

	def start_extraction(self) -> None:
		if self.is_running:
			return

		video = self.video_path.get().strip()
		output = self.output_dir.get().strip()
		prefix = self.prefix.get().strip()

		if not video:
			messagebox.showwarning("Missing video", "Please choose a video file.")
			return
		if not Path(video).exists():
			messagebox.showwarning("Video not found", "The selected video file does not exist.")
			return
		if not output:
			messagebox.showwarning("Missing output folder", "Please choose an output folder.")
			return
		if not prefix:
			messagebox.showwarning("Missing prefix", "Please provide a filename prefix.")
			return
		if shutil.which("ffmpeg") is None:
			messagebox.showerror(
				"ffmpeg not found",
				"ffmpeg is required but was not found on your PATH.\n\n"
				"Install it first, then reopen this app."
			)
			return

		self.is_running = True
		self.extract_button.config(state="disabled")
		self.progress.pack(side="right", padx=(0, 10))
		self.progress.start(10)
		self.status_text.set("Extracting frames…")

		thread = threading.Thread(target=self._extract_frames_worker, daemon=True)
		thread.start()

	def _extract_frames_worker(self) -> None:
		video = Path(self.video_path.get().strip())
		output = Path(self.output_dir.get().strip())
		prefix = self.prefix.get().strip()
		quality = int(self.quality.get())

		try:
			output.mkdir(parents=True, exist_ok=True)

			output_pattern = output / f"{prefix}_%06d.jpg"
			cmd = [
				"ffmpeg",
				"-hide_banner",
				"-loglevel",
				"error",
				"-i",
				str(video),
				"-vsync",
				"0",
				"-q:v",
				str(quality),
				str(output_pattern),
			]

			result = subprocess.run(cmd, capture_output=True, text=True)
			if result.returncode != 0:
				error_text = result.stderr.strip() or result.stdout.strip() or "Unknown ffmpeg error"
				self.after(0, self._finish_with_error, error_text)
				return

			frame_count = len(list(output.glob(f"{prefix}_*.jpg")))
			message = (
				f"Done. Extracted {frame_count} JPEG frame(s) to:\n{output}\n\n"
				f"Pattern: {prefix}_000001.jpg"
			)
			self.after(0, self._finish_success, message)
		except Exception as exc:
			self.after(0, self._finish_with_error, str(exc))

	def _finish_success(self, message: str) -> None:
		self.is_running = False
		self.extract_button.config(state="normal")
		self.progress.stop()
		self.progress.pack_forget()
		self.status_text.set(message)

	def _finish_with_error(self, error_message: str) -> None:
		self.is_running = False
		self.extract_button.config(state="normal")
		self.progress.stop()
		self.progress.pack_forget()
		self.status_text.set(f"Extraction failed:\n{error_message}")
		messagebox.showerror("Extraction failed", error_message)


if __name__ == "__main__":
	app = FrameExtractorApp()
	app.mainloop()
