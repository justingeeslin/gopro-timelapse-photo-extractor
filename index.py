import os
import threading
import subprocess
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class FrameExtractorApp(tk.Tk):
	def __init__(self) -> None:
		super().__init__()
		self.title("Action Camera Timelapse Batch Extractor")
		self.geometry("760x460")
		self.minsize(720, 420)

		self.input_dir = tk.StringVar()
		self.prefix = tk.StringVar(value="frame")
		self.status_text = tk.StringVar(
			value="Select a directory containing action camera timelapse videos."
		)

		self.is_running = False
		self.temp_root: Path | None = None

		# Processing configuration
		self.jpeg_quality = 2
		self.capture_interval_seconds = 0.5

		# Immich configuration
		self.immich_enabled = True
		self.immich_url = "http://localhost:2283/api"
		self.immich_api_key = "pRGcu77MKZwFXlaGiggCSE1jzFleZywxjbsZtN7Pxs"
		self.immich_auto_album = True
		self.immich_album_name = ""
		self.immich_upload_concurrency = 4
		self.immich_skip_hash = False

		self._build_ui()

	def _build_ui(self) -> None:
		container = ttk.Frame(self, padding=14)
		container.pack(fill="both", expand=True)

		ttk.Label(
			container,
			text="Action Camera Timelapse Batch Extractor",
			font=("TkDefaultFont", 14, "bold"),
		).pack(anchor="w", pady=(0, 12))

		input_frame = ttk.LabelFrame(container, text="Input Directory", padding=10)
		input_frame.pack(fill="x", pady=(0, 10))

		ttk.Entry(input_frame, textvariable=self.input_dir).pack(
			side="left", fill="x", expand=True, padx=(0, 8)
		)
		ttk.Button(input_frame, text="Browse…", command=self.choose_input_dir).pack(side="left")

		options = ttk.LabelFrame(container, text="Options", padding=10)
		options.pack(fill="x", pady=(0, 10))

		ttk.Label(options, text="Filename prefix:").grid(
			row=0, column=0, sticky="w", padx=(0, 8), pady=4
		)
		ttk.Entry(options, textvariable=self.prefix, width=18).grid(
			row=0, column=1, sticky="w", pady=4
		)

		help_text = (
			"This app scans a directory for action camera videos, extracts every frame as JPEG,\n"
			"extracts GoPro telemetry to GPX, assigns timestamps using the GPX master clock,\n"
			"geotags the frames, and uploads them to Immich."
		)
		ttk.Label(container, text=help_text, justify="left").pack(anchor="w", pady=(0, 10))

		button_row = ttk.Frame(container)
		button_row.pack(fill="x", pady=(0, 10))

		ttk.Button(button_row, text="Open Output Folder", command=self.open_output_folder).pack(
			side="left"
		)

		self.progress = ttk.Progressbar(button_row, mode="indeterminate", length=180)
		self.progress.pack(side="right", padx=(0, 10))
		self.progress.pack_forget()

		self.extract_button = ttk.Button(
			button_row, text="Process Videos", command=self.start_extraction
		)
		self.extract_button.pack(side="right")

		status_frame = ttk.LabelFrame(container, text="Status", padding=10)
		status_frame.pack(fill="both", expand=True)

		self.status_label = ttk.Label(
			status_frame,
			textvariable=self.status_text,
			justify="left",
			anchor="nw",
		)
		self.status_label.pack(fill="both", expand=True)

	def choose_input_dir(self) -> None:
		directory = filedialog.askdirectory(title="Choose directory containing videos")
		if directory:
			self.input_dir.set(directory)
			self.status_text.set(f"Selected input directory: {directory}")

	def open_output_folder(self) -> None:
		if self.temp_root is None:
			messagebox.showwarning("No output yet", "No temporary output folder has been created yet.")
			return

		if not self.temp_root.exists():
			messagebox.showwarning("Folder not found", "The temporary output folder no longer exists.")
			return

		self._open_folder_path(str(self.temp_root))

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

	def _find_video_files(self, input_dir: Path) -> list[Path]:
		supported_suffixes = {".mp4", ".mov", ".mkv", ".360"}
		return sorted(
			p for p in input_dir.iterdir()
			if p.is_file() and p.suffix.lower() in supported_suffixes
		)

	def _extract_gpx_track(self, video_path: Path, output_dir: Path) -> Path:
		gpx_path = output_dir / "track.gpx"

		cmd = [
			"exiftool",
			"-ee",
			"-p",
			"gpx.fmt",
			str(video_path),
		]

		with open(gpx_path, "w", encoding="utf-8") as f:
			result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)

		if result.returncode != 0:
			raise RuntimeError(
				result.stderr.strip() or "Failed to extract GPX track from video telemetry"
			)

		if not gpx_path.exists() or gpx_path.stat().st_size == 0:
			raise RuntimeError("GPX track extraction produced an empty file")

		return gpx_path

	def _get_gpx_start_datetime(self, gpx_path: Path) -> datetime:
		try:
			tree = ET.parse(gpx_path)
			root = tree.getroot()
		except Exception as exc:
			raise RuntimeError(f"Failed to parse GPX file: {exc}")

		ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
		time_elem = root.find(".//gpx:trkpt/gpx:time", ns)

		if time_elem is None:
			for elem in root.iter():
				if elem.tag.endswith("time") and elem.text:
					time_elem = elem
					break

		if time_elem is None or not time_elem.text:
			raise RuntimeError("No track timestamp found in GPX file")

		time_text = time_elem.text.strip()

		if time_text.endswith("Z"):
			dt = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
		else:
			dt = datetime.fromisoformat(time_text)

		if dt.tzinfo is not None:
			dt = dt.astimezone().replace(tzinfo=None)

		return dt

	def _format_exif_datetime(self, dt: datetime) -> str:
		return dt.strftime("%Y:%m:%d %H:%M:%S")

	def _write_exif_timestamps(
		self,
		output_dir: Path,
		prefix: str,
		start_dt: datetime,
		capture_interval_seconds: float,
	) -> None:
		frame_files = sorted(output_dir.glob(f"{prefix}_*.jpg"))
		if not frame_files:
			return

		for i, frame_file in enumerate(frame_files, start=1):
			seconds_offset = (i - 1) * capture_interval_seconds
			frame_dt = start_dt + timedelta(seconds=seconds_offset)

			exif_main = frame_dt.strftime("%Y:%m:%d %H:%M:%S")
			subsec = f"{frame_dt.microsecond // 1000:03d}".rstrip("0") or "0"

			cmd = [
				"exiftool",
				"-overwrite_original",
				f"-DateTimeOriginal={exif_main}",
				f"-CreateDate={exif_main}",
				f"-ModifyDate={exif_main}",
				f"-SubSecTimeOriginal={subsec}",
				f"-SubSecTimeDigitized={subsec}",
				f"-SubSecTime={subsec}",
				str(frame_file),
			]
			result = subprocess.run(cmd, capture_output=True, text=True)
			if result.returncode != 0:
				raise RuntimeError(
					f"Failed to write EXIF for {frame_file.name}: "
					f"{result.stderr.strip() or result.stdout.strip()}"
				)

	def _geotag_frames_with_gpx(self, output_dir: Path, prefix: str, gpx_path: Path) -> None:
		frame_files = sorted(output_dir.glob(f"{prefix}_*.jpg"))
		if not frame_files:
			return

		cmd = [
			"exiftool",
			"-overwrite_original",
			"-api",
			"GeoMaxIntSecs=600",
			f"-geotag={gpx_path}",
			"-geotime<${DateTimeOriginal}",
			*[str(frame_file) for frame_file in frame_files],
		]

		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode != 0:
			raise RuntimeError(
				result.stderr.strip()
				or result.stdout.strip()
				or "Failed to geotag frames from GPX"
			)

	def _find_immich_cli(self) -> str | None:
		return shutil.which("immich")

	def _upload_to_immich(self, upload_root: Path) -> None:
		if not self.immich_enabled:
			return

		immich_cli = self._find_immich_cli()
		if immich_cli is None:
			raise RuntimeError(
				"Immich CLI not found. Install it with:\n\n"
				"npm i -g @immich/cli"
			)

		cmd = [
			immich_cli,
			"-u", self.immich_url,
			"-k", self.immich_api_key,
			"upload",
			"--recursive",
			"-c", str(self.immich_upload_concurrency),
			"--no-progress",
		]

		if self.immich_skip_hash:
			cmd.append("--skip-hash")

		if self.immich_album_name.strip():
			cmd.extend(["--album-name", self.immich_album_name.strip()])
		elif self.immich_auto_album:
			cmd.append("--album")

		cmd.append(str(upload_root))

		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode != 0:
			raise RuntimeError(
				result.stderr.strip()
				or result.stdout.strip()
				or "Immich upload failed"
			)

	def _process_single_video(
		self,
		video: Path,
		video_output_dir: Path,
		prefix: str,
	) -> int:
		video_output_dir.mkdir(parents=True, exist_ok=True)

		quality = self.jpeg_quality
		capture_interval_seconds = self.capture_interval_seconds

		self.after(0, self.status_text.set, f"[{video.name}] Extracting frames…")

		output_pattern = video_output_dir / f"{prefix}_%06d.jpg"
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
			raise RuntimeError(
				f"{video.name}: "
				f"{result.stderr.strip() or result.stdout.strip() or 'Unknown ffmpeg error'}"
			)

		self.after(0, self.status_text.set, f"[{video.name}] Extracting GPS track…")
		gpx_path = self._extract_gpx_track(video, video_output_dir)

		self.after(0, self.status_text.set, f"[{video.name}] Reading GPX start time…")
		start_dt = self._get_gpx_start_datetime(gpx_path)

		self.after(0, self.status_text.set, f"[{video.name}] Writing photo timestamps…")
		self._write_exif_timestamps(
			video_output_dir,
			prefix,
			start_dt,
			capture_interval_seconds,
		)

		self.after(0, self.status_text.set, f"[{video.name}] Geotagging frames…")
		self._geotag_frames_with_gpx(video_output_dir, prefix, gpx_path)

		frame_count = len(list(video_output_dir.glob(f"{prefix}_*.jpg")))
		return frame_count

	def start_extraction(self) -> None:
		if self.is_running:
			return

		input_dir_str = self.input_dir.get().strip()
		prefix = self.prefix.get().strip()

		if not input_dir_str:
			messagebox.showwarning("Missing input directory", "Please choose an input directory.")
			return

		input_dir = Path(input_dir_str)
		if not input_dir.exists() or not input_dir.is_dir():
			messagebox.showwarning("Directory not found", "The selected input directory does not exist.")
			return

		if not prefix:
			messagebox.showwarning("Missing prefix", "Please provide a filename prefix.")
			return

		for tool_name, friendly_name in [
			("ffmpeg", "ffmpeg"),
			("ffprobe", "ffprobe"),
			("exiftool", "exiftool"),
		]:
			if shutil.which(tool_name) is None:
				messagebox.showerror(
					f"{friendly_name} not found",
					f"{friendly_name} is required but was not found on your PATH.\n\n"
					f"Install it first, then reopen this app.",
				)
				return

		if self.immich_enabled and self._find_immich_cli() is None:
			messagebox.showerror(
				"Immich CLI not found",
				"Immich upload is enabled, but the Immich CLI was not found.\n\n"
				"Install it with:\n"
				"npm i -g @immich/cli"
			)
			return

		video_files = self._find_video_files(input_dir)
		if not video_files:
			messagebox.showwarning(
				"No videos found",
				"No supported video files were found in the selected directory.",
			)
			return

		self.temp_root = Path(tempfile.mkdtemp(prefix="gopro_timelapse_extract_"))

		self.is_running = True
		self.extract_button.config(state="disabled")
		self.progress.pack(side="right", padx=(0, 10))
		self.progress.start(10)
		self.status_text.set(
			f"Found {len(video_files)} video(s). Processing into temporary folder:\n{self.temp_root}"
		)

		thread = threading.Thread(target=self._extract_directory_worker, daemon=True)
		thread.start()

	def _extract_directory_worker(self) -> None:
		input_dir = Path(self.input_dir.get().strip())
		prefix = self.prefix.get().strip()

		try:
			video_files = self._find_video_files(input_dir)
			if not video_files:
				self.after(0, self._finish_with_error, "No supported video files found.")
				return

			if self.temp_root is None:
				raise RuntimeError("Temporary output directory was not initialized.")

			total_frames = 0
			results = []

			for idx, video in enumerate(video_files, start=1):
				video_output_dir = self.temp_root / video.stem
				self.after(
					0,
					self.status_text.set,
					f"Processing video {idx} of {len(video_files)}:\n{video.name}",
				)

				frame_count = self._process_single_video(
					video,
					video_output_dir,
					prefix,
				)
				total_frames += frame_count
				results.append((video.name, frame_count, video_output_dir))

			if self.immich_enabled:
				self.after(0, self.status_text.set, "Uploading processed photos to Immich…")
				self._upload_to_immich(self.temp_root)

			summary_lines = [
				f"Done. Processed {len(video_files)} video(s).",
				"Temporary output folder:",
				f"{self.temp_root}",
				"",
				f"Total JPEG frames: {total_frames}",
				"",
			]

			if self.immich_enabled:
				summary_lines.extend([
					"Immich upload: complete",
					f"Immich server: {self.immich_url}",
					"",
				])

			for video_name, frame_count, out_dir in results:
				summary_lines.append(f"{video_name}: {frame_count} frame(s)")
				summary_lines.append(f"  {out_dir}")

			self.after(0, self._finish_success, "\n".join(summary_lines))
		except Exception as exc:
			self.after(0, self._finish_with_error, str(exc))

	def _finish_success(self, message: str) -> None:
		self.is_running = False
		self.extract_button.config(state="normal")
		self.progress.stop()
		self.progress.pack_forget()
		self.status_text.set(message)

		output = str(self.temp_root) if self.temp_root else ""
		try:
			open_now = messagebox.askyesno(
				"Processing complete",
				f"Processing complete.\n\nOpen temporary output folder?\n{output}",
			)
			if open_now and output:
				self._open_folder_path(output)
		except Exception:
			messagebox.showinfo("Processing complete", "Processing complete.")

	def _finish_with_error(self, error_message: str) -> None:
		self.is_running = False
		self.extract_button.config(state="normal")
		self.progress.stop()
		self.progress.pack_forget()
		self.status_text.set(f"Processing failed: {error_message}")
		messagebox.showerror("Processing failed", error_message)


if __name__ == "__main__":
	app = FrameExtractorApp()
	app.mainloop()