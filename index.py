import os
import threading
import subprocess
import shutil
import json
from datetime import datetime, timedelta
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

		self._open_folder_path(str(output_path))

	def _open_folder_path(self, path: str) -> None:
		try:
			if os.name == "nt":
				os.startfile(path)
			elif shutil.which("open"):
				subprocess.Popen(["open", path])
			else:
				subprocess.Popen(["xdg-open", path])
		except Exception as exc:
			messagebox.showerror("Open folder failed", str(exc))

	def _get_video_start_datetime(self, video_path: Path) -> datetime:
		cmd = [
			"ffprobe",
			"-v", "error",
			"-show_entries", "format_tags=creation_time:stream_tags=creation_time",
			"-of", "json",
			str(video_path),
		]
		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode != 0:
			raise RuntimeError(result.stderr.strip() or "Could not read video metadata")

		data = json.loads(result.stdout)

		creation_time = None

		format_tags = data.get("format", {}).get("tags", {})
		creation_time = format_tags.get("creation_time")

		if not creation_time:
			for stream in data.get("streams", []):
				stream_tags = stream.get("tags", {})
				if "creation_time" in stream_tags:
					creation_time = stream_tags["creation_time"]
					break

		if not creation_time:
			raise RuntimeError(
				"No creation_time metadata found in the video. "
				"Cannot determine when the frames were captured."
			)

		creation_time = creation_time.replace("Z", "+00:00")
		dt = datetime.fromisoformat(creation_time)

		if dt.tzinfo is not None:
			dt = dt.astimezone().replace(tzinfo=None)

		return dt

	def _get_video_fps(self, video_path: Path) -> float:
		cmd = [
			"ffprobe",
			"-v", "error",
			"-select_streams", "v:0",
			"-show_entries", "stream=r_frame_rate",
			"-of", "json",
			str(video_path),
		]
		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode != 0:
			raise RuntimeError(result.stderr.strip() or "Could not determine video FPS")

		data = json.loads(result.stdout)
		streams = data.get("streams", [])
		if not streams:
			raise RuntimeError("No video stream found")

		rate = streams[0].get("r_frame_rate", "0/0")
		num_str, den_str = rate.split("/")
		num = float(num_str)
		den = float(den_str)
		if den == 0:
			raise RuntimeError("Invalid FPS reported by ffprobe")

		return num / den

	def _format_exif_datetime(self, dt: datetime) -> str:
		return dt.strftime("%Y:%m:%d %H:%M:%S")

	def _write_exif_timestamps(self, output_dir: Path, prefix: str, start_dt: datetime, fps: float) -> None:
		frame_files = sorted(output_dir.glob(f"{prefix}_*.jpg"))
		if not frame_files:
			return

		for i, frame_file in enumerate(frame_files, start=1):
			seconds_offset = (i - 1) / fps
			frame_dt = start_dt + timedelta(seconds=seconds_offset)
			exif_dt = self._format_exif_datetime(frame_dt)

			cmd = [
				"exiftool",
				"-overwrite_original",
				f"-DateTimeOriginal={exif_dt}",
				f"-CreateDate={exif_dt}",
				f"-ModifyDate={exif_dt}",
				str(frame_file),
			]
			result = subprocess.run(cmd, capture_output=True, text=True)
			if result.returncode != 0:
				raise RuntimeError(
					f"Failed to write EXIF for {frame_file.name}: "
					f"{result.stderr.strip() or result.stdout.strip()}"
				)

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
		if shutil.which("ffprobe") is None:
			messagebox.showerror(
				"ffprobe not found",
				"ffprobe is required but was not found on your PATH.\n\n"
				"Install ffmpeg/ffprobe, then reopen this app."
			)
			return
		if shutil.which("exiftool") is None:
			messagebox.showerror(
				"exiftool not found",
				"exiftool is required to write photo timestamps.\n\n"
				"Install it first, then reopen this app."
			)
			return

		self.is_running = True
		self.extract_button.config(state="disabled")
		self.progress.pack(side="right", padx=(0, 10))
		self.progress.start(10)
		self.status_text.set("Extracting frames and writing EXIF timestamps…")

		thread = threading.Thread(target=self._extract_frames_worker, daemon=True)
		thread.start()

	def _extract_frames_worker(self) -> None:
		video = Path(self.video_path.get().strip())
		output = Path(self.output_dir.get().strip())
		prefix = self.prefix.get().strip()
		quality = int(self.quality.get())

		try:
			output.mkdir(parents=True, exist_ok=True)

			start_dt = self._get_video_start_datetime(video)
			fps = self._get_video_fps(video)

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

			self._write_exif_timestamps(output, prefix, start_dt, fps)

			frame_count = len(list(output.glob(f"{prefix}_*.jpg")))
			message = (
				f"Done. Extracted {frame_count} JPEG frame(s) to:\n{output}\n\n"
				f"Photo start time: {self._format_exif_datetime(start_dt)}\n"
				f"FPS used for timestamps: {fps:.6f}\n"
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

		output = self.output_dir.get().strip()
		try:
			open_now = messagebox.askyesno(
				"Extraction complete",
				f"Extraction complete.\n\nOpen output folder?\n{output}"
			)
			if open_now and output:
				self._open_folder_path(output)
		except Exception:
			messagebox.showinfo("Extraction complete", "Extraction complete.")

	def _finish_with_error(self, error_message: str) -> None:
		self.is_running = False
		self.extract_button.config(state="normal")
		self.progress.stop()
		self.progress.pack_forget()
		self.status_text.set(f"Extraction failed: {error_message}")
		messagebox.showerror("Extraction failed", error_message)


if __name__ == "__main__":
	app = FrameExtractorApp()
	app.mainloop()