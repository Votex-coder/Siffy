import os
import io
import math
import threading
import requests
import yt_dlp
from PIL import Image, ImageTk, ImageFilter, ImageDraw, ImageEnhance
import customtkinter as ctk
from tkinter import messagebox, filedialog
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
import pygame
import tkinter as tk
import shutil
import time
from pathlib import Path

import platform
import urllib.request
import zipfile
import tarfile
import subprocess
from plyer import notification
import json

# ========== CONFIG ==========
DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

WINDOW_W, WINDOW_H = 1380, 920
COVER_DISPLAY_SIZE = 300
BG_BLUR_RADIUS = 18
GLASS_ALPHA = 0.38
SHADOW_ALPHA = 0.08

# ========== INIT AUDIO ==========
try:
    pygame.mixer.init()
except Exception:
    print("Warning: pygame.mixer.init() failed — audio may not work.")

# ========== HELPERS ==========
def crop_center_square(img):
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))

def find_ffmpeg_binary(ffmpeg_dir):
    ffmpeg_dir = "ffmpeg"
    for root, dirs, files in os.walk(ffmpeg_dir):
        for file in files:
            if file in ['ffmpeg.exe', 'ffmpeg']:
                return os.path.join(root, file)
    return None

def get_ffmpeg_path():
    ffmpeg_path = find_ffmpeg_binary('ffmpeg')
    if ffmpeg_path and os.path.exists(ffmpeg_path):
        return ffmpeg_path


def make_blurred_background(img, target_size=(WINDOW_W, WINDOW_H), blur_radius=BG_BLUR_RADIUS):
    tw, th = target_size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    new_size = (math.ceil(iw * scale), math.ceil(ih * scale))
    img_resized = img.resize(new_size, Image.LANCZOS)
    left = (new_size[0] - tw) // 2
    top = (new_size[1] - th) // 2
    img_cropped = img_resized.crop((left, top, left + tw, top + th))
    img_blur = img_cropped.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    img_blur = ImageEnhance.Color(img_blur).enhance(0.9)
    img_blur = ImageEnhance.Brightness(img_blur).enhance(0.94)
    return img_blur


def rounded_rectangle_mask(size, radius):
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    return mask


def make_glass_plate_from_bg(bg_image, plate_box, radius=24, alpha=GLASS_ALPHA, shadow_alpha=SHADOW_ALPHA):
    left, top, right, bottom = plate_box
    plate_bg = bg_image.crop((left, top, right, bottom)).convert("RGBA")
    w, h = plate_bg.size
    overlay = Image.new("RGBA", (w, h), (255, 255, 255, int(alpha * 255)))
    grad = Image.new("L", (1, h))
    for y in range(h):
        val = int(255 * (1 - (y / h) * 0.6))
        grad.putpixel((0, y), val)
    gradient = grad.resize((w, h))
    light = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    light.putalpha(gradient)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=(0, 0, 0, int(shadow_alpha * 255)))
    mask = rounded_rectangle_mask((w, h), radius)
    plate = Image.alpha_composite(plate_bg, overlay)
    plate = Image.alpha_composite(plate, light)
    plate.putalpha(mask)
    shadow.putalpha(mask)
    return plate, shadow


def load_cover_image_for_mp3(mp3_path):
    # try jpg next to mp3
    jpg_path = os.path.splitext(mp3_path)[0] + ".jpg"
    if os.path.exists(jpg_path):
        try:
            return Image.open(jpg_path).convert("RGBA")
        except Exception:
            pass
    # try APIC inside tags
    try:
        tags = ID3(mp3_path)
        for tag in tags.values():
            if getattr(tag, "FrameID", "") == "APIC" or tag.__class__.__name__ == "APIC":
                data = tag.data
                try:
                    return Image.open(io.BytesIO(data)).convert("RGBA")
                except Exception:
                    pass
    except Exception:
        pass
    return None

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def show_once_with_config(message_id, message):
    config = load_config()
    
    if message_id not in config:
        messagebox.showinfo(message_id, message)
        config[message_id] = True
        save_config(config)


# ========== APP ==========
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Siffy")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        try:
            self.iconbitmap('assets/icon.ico')
        except Exception:
            pass

        # state
        self.tracks = []
        self.selected_track = None
        self.track_index = -1
        self.track_length = 0
        self.is_paused = False
        self.current_pos = 0
        self.user_seeking = False
        self.current_bg_image = None
        self.loop_enabled = False
        self.was_playing = False

        show_once_with_config("Добро пожаловать!", "Это MP3-плеер Siffy версия 1.5, имеющий скачку музыки с Youtube(not YT music) и Spotify.\nНе судите строго, я плох в Python, и врать не буду, использовал DeepSeek, \n\nно, в будущем возможно перенесу на другой язык, и найду команду для этого!\nПриятного использования!\n\n\n (В случае ошибок, писать на страницу гитхаба в Issues.)")

        # download queue state
        self.download_queue = []  # list of dicts: {'url':..., 'type':'yt'/'sp', 'status': 'queued'/'downloading'/'done'/'error', 'message':...}

        # Canvas for background
        self.bg_canvas = ctk.CTkCanvas(self, width=WINDOW_W, height=WINDOW_H, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0)
        self._bg_photo_ref = None
        self._plate_image_refs = []

        # layout boxes
        left_box = (40, 40, 420, WINDOW_H - 40)
        right_box = (480, 80, WINDOW_W - 40, WINDOW_H - 80)

        # initial blank background and plates
        blank_bg = Image.new("RGBA", (WINDOW_W, WINDOW_H), (12, 14, 20, 255))
        self.set_background_from_pil(blank_bg)
        self.create_glass_plates(left_box, right_box)

        # left panel (track list)
        self.tracks_frame = ctk.CTkFrame(self, width=left_box[2] - left_box[0], height=left_box[3] - left_box[1], corner_radius=0, fg_color="transparent")
        self.tracks_frame.place(x=left_box[0], y=left_box[1])

        ctk.CTkLabel(self.tracks_frame, text="Треки", font=("Arial", 16, "bold")).pack(pady=(10, 5))
        self.scrollable_track_frame = ctk.CTkScrollableFrame(
            self.tracks_frame,
            width=left_box[2] - left_box[0] - 40,
            height=(left_box[3] - left_box[1]) - 180,
            corner_radius=12,
            fg_color=("gray15", "gray20")
        )
        self.scrollable_track_frame.pack(padx=10, pady=5, fill="both", expand=True)
        self.scrollable_track_frame.grid_columnconfigure(0, weight=1)


        buttons_frame = ctk.CTkFrame(self.tracks_frame, fg_color="transparent")
        buttons_frame.pack(pady=10)

        self.btn_add = ctk.CTkButton(buttons_frame, text="➕ Добавить", corner_radius=14,
                                    command=self.add_tracks_from_files, width=120)
        self.btn_add.grid(row=0, column=0, padx=5, pady=5)

        self.btn_delete = ctk.CTkButton(buttons_frame, text="🗑 Удалить", corner_radius=14,
                                       command=self.delete_track, width=120)
        self.btn_delete.grid(row=0, column=1, padx=5, pady=5)

        # right panel (cover + controls)
        self.right_frame = ctk.CTkFrame(self, width=right_box[2] - right_box[0], height=right_box[3] - right_box[1], corner_radius=0, fg_color="transparent")
        self.right_frame.place(x=right_box[0], y=right_box[1])

        self.cover_label = ctk.CTkLabel(self.right_frame, text="", width=COVER_DISPLAY_SIZE, height=COVER_DISPLAY_SIZE)
        self.cover_label.grid(row=0, column=0, columnspan=3, padx=20, pady=(30, 10), sticky="n")

        self.track_info = ctk.CTkLabel(self.right_frame, text="", font=("Arial", 14))
        self.track_info.grid(row=0, column=0, columnspan=3, pady=(0, 5), sticky="n")

        # controls row
        self.controls_frame = ctk.CTkFrame(self.right_frame, corner_radius=14, fg_color="transparent")
        self.controls_frame.grid(row=1, column=1, padx=20, pady=10, sticky="w")

        self.btn_prev = ctk.CTkButton(self.controls_frame, text="⏮", width=70, height=50, corner_radius=14,
                                      command=self.prev_track, state="disabled")
        self.btn_prev.grid(row=0, column=0, padx=6, pady=6)

        self.btn_play = ctk.CTkButton(self.controls_frame, text="▶️", width=100, height=56, corner_radius=28,
                                      command=self.play_pause, state="disabled")
        self.btn_play.grid(row=0, column=1, padx=6, pady=6)

        self.btn_next = ctk.CTkButton(self.controls_frame, text="⏭", width=70, height=50, corner_radius=14,
                                      command=self.next_track, state="disabled")
        self.btn_next.grid(row=0, column=2, padx=6, pady=6)

        self.btn_loop = ctk.CTkButton(self.controls_frame, text="🔁", width=70, height=50, corner_radius=14,
                                      command=self.toggle_loop, state="disabled")
        self.btn_loop.grid(row=0, column=3, padx=6, pady=6)

        # progress
        self.progress = ctk.CTkSlider(self.right_frame, from_=0, to=100, width=640, command=lambda v: None)
        self.progress.grid(row=2, column=0, columnspan=2, padx=100, pady=(10, 0), sticky="w")
        self.progress.bind("<Button-1>", self.start_seek)
        self.progress.bind("<ButtonRelease-1>", self.end_seek)

        timers_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        timers_frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 10))
        self.time_elapsed = ctk.CTkLabel(timers_frame, text="")
        self.time_elapsed.pack(side="left")
        self.time_total = ctk.CTkLabel(timers_frame, text="")
        self.time_total.pack(side="right")

        # volume
        self.volume_label = ctk.CTkLabel(self.right_frame, text="Громкость:", font=("Arial", 12))
        self.volume_label.grid(row=4, column=0, padx=(20,5), pady=(10,5), sticky="e")

        self.volume_slider = ctk.CTkSlider(self.right_frame, from_=0, to=1, width=280, command=self.set_volume)
        self.volume_slider.set(0.5)
        self.volume_slider.grid(row=4, column=1, padx=20, pady=(10, 5), sticky="w")
        try:
            pygame.mixer.music.set_volume(0.5)
        except Exception:
            pass

        download_frame_parent = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        download_frame_parent.grid(row=5, column=0, columnspan=2, padx=20, pady=(10, 20), sticky="w")

        self.download_tabview = ctk.CTkTabview(download_frame_parent, width=720, height=220)
        self.download_tabview.add("YouTube")
        self.download_tabview.add("Spotify")
        self.download_tabview.add("Очередь")
        self.download_tabview.grid(row=0, column=0, sticky="w")

        yt_tab = self.download_tabview.tab("YouTube")
        self.yt_entry = ctk.CTkEntry(yt_tab, width=520, placeholder_text="Вставь ссылку на YouTube...")
        self.yt_entry.grid(row=0, column=0, padx=(10, 8), pady=16, sticky="w")

        self.yt_download_btn = ctk.CTkButton(yt_tab, text="⬇ Скачать", command=self.on_download_youtube)
        self.yt_download_btn.grid(row=0, column=1, padx=(0, 10), pady=16, sticky="w")

        sp_tab = self.download_tabview.tab("Spotify")
        self.sp_entry = ctk.CTkEntry(sp_tab, width=520, placeholder_text="Вставь ссылку на Spotify")
        self.sp_entry.grid(row=0, column=0, padx=(10, 8), pady=16, sticky="w")

        self.sp_download_btn = ctk.CTkButton(sp_tab, text="⬇ Скачать", command=self.on_download_spotify)
        self.sp_download_btn.grid(row=0, column=1, padx=(0, 10), pady=16, sticky="w")

        q_tab = self.download_tabview.tab("Очередь")
        q_frame = ctk.CTkFrame(q_tab, fg_color="transparent")
        q_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.queue_listbox = tk.Listbox(q_frame, width=70, height=8)
        self.queue_listbox.pack(side="left", fill="both", expand=True)
        q_scroll = tk.Scrollbar(q_frame, command=self.queue_listbox.yview)
        q_scroll.pack(side="right", fill="y")
        self.queue_listbox.config(yscrollcommand=q_scroll.set)

        self.open_downloads_btn = ctk.CTkButton(download_frame_parent, text="Открыть папку загрузок", command=self.open_downloads_folder)
        self.open_downloads_btn.grid(row=1, column=0, padx=10, pady=(6,0), sticky="w")

        # notification.notify(
        #     title='Загрузка завершена',
        #     message='Файл успешно скачан и сохранен',
        #     app_name='Мое Приложение',
        #     app_icon='assets/icon.ico',  # Можно указать путь к .ico (Windows) или .png (Linux)
        #     timeout=15,
        #     ticker='Новое уведомление',
        #     toast=False  # Для Windows 8+
        # )
        

        def paste_clipboard(event=None):
            try:
                self.yt_entry.delete(0, "end")
                self.yt_entry.insert(0, self.clipboard_get().strip())
            except Exception:
                pass
            return "break"

        self.yt_entry.bind("<Control-v>", paste_clipboard)
        self.yt_entry.bind("<Control-V>", paste_clipboard)



        # load and start loopers
        self.load_tracks()
        self.update_progress()
        self.after(700, self.check_end)
        self.after(1000, self._periodic_queue_update)

        self.tracks_frame.lift()
        self.right_frame.lift()

    # background 
    def set_background_from_pil(self, pil_img):
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        self._bg_photo_ref = ImageTk.PhotoImage(pil_img)
        self.bg_canvas.create_image(0, 0, anchor="nw", image=self._bg_photo_ref)
        self.bg_canvas.lower("all")

    def create_glass_plates(self, left_box, right_box):
        if self.current_bg_image is None:
            return
        plate, shadow = make_glass_plate_from_bg(self.current_bg_image, left_box, radius=20)
        self.left_plate_img = ImageTk.PhotoImage(plate)
        self.left_shadow_img = ImageTk.PhotoImage(shadow)
        plate_r, shadow_r = make_glass_plate_from_bg(self.current_bg_image, right_box, radius=26)
        self.right_plate_img = ImageTk.PhotoImage(plate_r)
        self.right_shadow_img = ImageTk.PhotoImage(shadow_r)
        self.bg_canvas.create_image(left_box[0], left_box[1], anchor="nw", image=self.left_shadow_img)
        self.bg_canvas.create_image(left_box[0], left_box[1], anchor="nw", image=self.left_plate_img)
        self.bg_canvas.create_image(right_box[0], right_box[1], anchor="nw", image=self.right_shadow_img)
        self.bg_canvas.create_image(right_box[0], right_box[1], anchor="nw", image=self.right_plate_img)
        return

    # tracks
    def load_tracks(self):
        for w in self.scrollable_track_frame.winfo_children():
            w.destroy()
        self.tracks.clear()
        files = [f for f in os.listdir(DOWNLOADS_DIR) if f.lower().endswith('.mp3')]
        files.sort()
        for fname in files:
            path = os.path.join(DOWNLOADS_DIR, fname)
            self.tracks.append(path)
            artist, title = self.get_tags(path)
            label = title if title else os.path.splitext(fname)[0]
            btn = ctk.CTkButton(
                self.scrollable_track_frame,
                text=label,
                corner_radius=12,
                anchor="w",
                width=self.scrollable_track_frame.winfo_width() - 20,
                command=lambda p=path: self.select_track(p)
            )
            btn.pack(padx=10, pady=4, fill="x")


    def get_tags(self, filepath):
        try:
            audio = ID3(filepath)
            artist = audio.get('TPE1')
            title = audio.get('TIT2')
            return (artist.text[0] if artist else '', title.text[0] if title else '')
        except Exception:
            return ('', '')

    def add_tracks_from_files(self):
        filetypes = (
            ('MP3 files', '*.mp3'),
            ('All files', '*.*')
        )
        files = filedialog.askopenfilenames(
            title="Выберите MP3 файлы",
            filetypes=filetypes
        )
        if not files:
            return
        added_count = 0
        for file_path in files:
            if file_path.lower().endswith('.mp3'):
                try:
                    filename = os.path.basename(file_path)
                    dest_path = os.path.join(DOWNLOADS_DIR, filename)
                    counter = 1
                    base_name, ext = os.path.splitext(filename)
                    while os.path.exists(dest_path):
                        new_filename = f"{base_name}_{counter}{ext}"
                        dest_path = os.path.join(DOWNLOADS_DIR, new_filename)
                        counter += 1
                    shutil.copy2(file_path, dest_path)
                    cover_path = self.find_cover_file(file_path)
                    if cover_path and os.path.exists(cover_path):
                        cover_ext = os.path.splitext(cover_path)[1]
                        new_cover_name = os.path.splitext(os.path.basename(dest_path))[0] + cover_ext
                        new_cover_path = os.path.join(DOWNLOADS_DIR, new_cover_name)
                        shutil.copy2(cover_path, new_cover_path)
                    added_count += 1
                except Exception as e:
                    #messagebox.showerror("Ошибка", f"Не удалось добавить файл {os.path.basename(file_path)}: {str(e)}")
                    notification.notify(
                        title='Ошибка',
                        message= f"Не удалось добавить файл {os.path.basename(file_path)}: {str(e)}",
                        app_name='Siffy Helper',
                        app_icon='assets/icon.ico',
                        timeout=15,
                        ticker='Новое уведомление',
                        toast=False 
                    )
        if added_count > 0:
            self.load_tracks()
            # messagebox.showinfo("Успех", f"Добавлено {added_count} треков")
            notification.notify(
                title='Загрузка завершена',
                message= f"Добавлено {added_count} треков",
                app_name='Siffy Helper',
                app_icon='assets/icon.ico',
                timeout=15,
                ticker='Новое уведомление',
                toast=False 
            )
        else:
            #messagebox.showwarning("Внимание", "Не было добавлено ни одного MP3 файла")
            notification.notify(
                title='Внимание',
                message= "Не было добавлено ни одного MP3 файла",
                app_name='Siffy Helper',
                app_icon='assets/icon.ico',
                timeout=15,
                ticker='Новое уведомление',
                toast=False 
            )

    def find_cover_file(self, mp3_path):
        base_name = os.path.splitext(mp3_path)[0]
        for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.JPG', '.JPEG', '.PNG', '.BMP', '.WEBP']:
            cover_path = base_name + ext
            if os.path.exists(cover_path):
                return cover_path
        return None

    def select_track(self, filepath):
        if filepath not in self.tracks:
            return
        self.selected_track = filepath
        self.track_index = self.tracks.index(filepath)
        self.current_pos = 0.0
        self.is_paused = False
        self.load_selected_track_ui()

    def load_selected_track_ui(self):
        if not self.selected_track:
            return
        cover = load_cover_image_for_mp3(self.selected_track)
        if cover:
            bg = make_blurred_background(cover, target_size=(WINDOW_W, WINDOW_H))
            self.set_background_from_pil(bg)
            crop = crop_center_square(cover)
            display_img = crop.resize((COVER_DISPLAY_SIZE, COVER_DISPLAY_SIZE), Image.LANCZOS)
            tkcover = ImageTk.PhotoImage(display_img)
            self.cover_label.configure(image=tkcover, text='')
            self.cover_label.image = tkcover
        else:
            blank = Image.new("RGBA", (WINDOW_W, WINDOW_H), (10, 12, 14, 255))
            self.set_background_from_pil(blank)
            self.cover_label.configure(image=None, text='(нет обложки)')

        artist, title = self.get_tags(self.selected_track)
        if artist or title:
            display_text = f"{artist}" if artist and title else artist or title #\n{title}
        else:
            display_text = os.path.basename(self.selected_track)
        self.track_info.configure(text=display_text)


        try:
            self.track_length = MP3(self.selected_track).info.length
        except Exception:
            self.track_length = 0.0
        mins, secs = divmod(int(self.track_length), 60)

        self.btn_play.configure(state='normal')
        self.btn_prev.configure(state='normal')
        self.btn_next.configure(state='normal')
        self.btn_loop.configure(state='normal')

    # playback
    def play_pause(self):
        if not self.selected_track:
            return
        try:
            if not pygame.mixer.music.get_busy() and not self.is_paused:
                pygame.mixer.music.load(self.selected_track)
                try:
                    pygame.mixer.music.play(start=self.current_pos)
                except TypeError:
                    pygame.mixer.music.play()
                self.is_paused = False
                self.btn_play.configure(text='⏸')
                self.was_playing = True
            elif not self.is_paused:
                pos_ms = pygame.mixer.music.get_pos()
                if pos_ms is not None and pos_ms >= 0:
                    self.current_pos = self.current_pos + (pos_ms / 1000.0)
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                self.is_paused = True
                self.btn_play.configure(text='▶️')
            else:
                pygame.mixer.music.load(self.selected_track)
                try:
                    pygame.mixer.music.play(start=self.current_pos)
                except TypeError:
                    pygame.mixer.music.play()
                self.is_paused = False
                self.btn_play.configure(text='⏸')
                self.was_playing = True
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def play_current(self, start_at=0.0):
        if not self.selected_track:
            return
        self.current_pos = start_at
        try:
            pygame.mixer.music.load(self.selected_track)
            try:
                pygame.mixer.music.play(start=self.current_pos)
            except TypeError:
                pygame.mixer.music.play()
            self.is_paused = False
            self.btn_play.configure(text='⏸')
            self.was_playing = True
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def next_track(self):
        if not self.tracks:
            return
        if self.track_index < len(self.tracks) - 1:
            self.track_index += 1
        else:
            self.track_index = 0
        self.selected_track = self.tracks[self.track_index]
        self.current_pos = 0.0
        self.load_selected_track_ui()
        self.play_current(0.0)

    def prev_track(self):
        if not self.tracks:
            return
        if self.track_index > 0:
            self.track_index -= 1
        else:
            self.track_index = len(self.tracks) - 1
        self.selected_track = self.tracks[self.track_index]
        self.current_pos = 0.0
        self.load_selected_track_ui()
        self.play_current(0.0)

    # seeking / progress
    def update_progress(self):
        try:
            if self.selected_track and (pygame.mixer.music.get_busy() or self.is_paused):
                if not self.is_paused:
                    pos = (pygame.mixer.music.get_pos() / 1000.0) + self.current_pos
                else:
                    pos = self.current_pos
                if not self.user_seeking and self.track_length > 0:
                    self.progress.set((pos / self.track_length) * 100)
                mins, secs = divmod(int(pos), 60)
                # self.time_elapsed.configure(text=f"{mins:02d}:{secs:02d}")
            # else:
            #     # если ничего не играет — оставляем 00:00
            #     if not self.selected_track:
            #         self.time_elapsed.configure(text="00:00")
        except Exception:
            pass
        self.after(500, self.update_progress)


    def start_seek(self, event=None):
        self.user_seeking = True

    def end_seek(self, event=None):
        if self.selected_track and self.track_length > 0:
            value = self.progress.get()
            new_pos = (value / 100.0) * self.track_length
            self.current_pos = new_pos
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.music.load(self.selected_track)
                try:
                    pygame.mixer.music.play(start=new_pos)
                except TypeError:
                    pygame.mixer.music.play()
                self.is_paused = False
                self.btn_play.configure(text='⏸')
                self.was_playing = True
            except Exception as e:
                messagebox.showerror("Seek error", str(e))
        self.user_seeking = False

    # volume 
    def set_volume(self, value):
        try:
            vol = float(value)
            pygame.mixer.music.set_volume(vol)
        except Exception:
            pass

    # delete
    def delete_track(self):
        if not self.selected_track:
            messagebox.showwarning("Внимание", "Выберите трек для удаления!")
            return
        name = os.path.basename(self.selected_track)
        if not messagebox.askyesno("Удалить", f"Удалить {name}?"):
            return
        try:
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
            except Exception:
                pass
            os.remove(self.selected_track)
            jpg = os.path.splitext(self.selected_track)[0] + '.jpg'
            if os.path.exists(jpg):
                try:
                    os.remove(jpg)
                except Exception:
                    pass
            self.selected_track = None
            self.track_index = -1
            self.load_tracks()
            blank = Image.new("RGBA", (WINDOW_W, WINDOW_H), (12, 14, 20, 255))
            self.set_background_from_pil(blank)
            self.cover_label.configure(image=None, text='')
            self.track_info.configure(text='')
            self.track_length = 0.0
            # self.time_total.configure(text='00:00')
            # self.time_elapsed.configure(text='00:00')
            self.progress.set(0)
            self.btn_play.configure(state='disabled', text='▶️')
            self.btn_prev.configure(state='disabled')
            self.btn_next.configure(state='disabled')
            self.btn_loop.configure(state='disabled')
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # loop / end detection
    def toggle_loop(self):
        self.loop_enabled = not self.loop_enabled
        if self.loop_enabled:
            try:
                self.btn_loop.configure(fg_color=("#EFF8FF", "#A7A7A7"))
            except Exception:
                pass
        else:
            try:
                self.btn_loop.configure(fg_color=None)
            except Exception:
                pass

    def check_end(self):
        try:
            busy = False
            try:
                busy = pygame.mixer.music.get_busy()
            except Exception:
                busy = False
            if self.was_playing and not busy and not self.is_paused and self.selected_track:
                if self.loop_enabled:
                    self.current_pos = 0.0
                    self.play_current(0.0)
                else:
                    self.next_track()
            if busy:
                self.was_playing = True
        except Exception:
            pass
        finally:
            self.after(700, self.check_end)

    # ----- downloader (yt_dlp) - YouTube -----
    def download_audio_with_cover(self, url):
        ffmpeg_path = get_ffmpeg_path()
        ydl_opts = {
            'format': 'bestaudio/best',
            'writethumbnail': True,
            'convert-thumbnails': 'jpg',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata'},
            ],
            'ffmpeg_location': ffmpeg_path,
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'retries': 10,              # Повторные попытки при ошибках
            'fragment_retries': 10,     # Повторные попытки на каждом фрагменте
            # 'socket_timeout': 30,       # Таймаут соединения
            'nocheckcertificate': True, # Игнорировать SSL ошибки
            # 'ratelimit': 500 * 1024,  # Ограничение скорости (раскомментируй при обрывах)
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'thumbnail' in info:
                thumb_url = info['thumbnail']
                try:
                    img_data = requests.get(thumb_url, timeout=15).content
                    img = Image.open(io.BytesIO(img_data))
                    thumb_path = os.path.join(DOWNLOADS_DIR, f"{info['title']}.jpg")
                    img.save(thumb_path)
                except Exception as e:
                    print(f"Не удалось сохранить отдельную обложку: {e}")

    # ----- downloader - Spotify -----
    def download_spotify_track(self, url: str, output_dir: str = DOWNLOADS_DIR) -> bool:
            cmd = [
                "spotdl", "download", url,
                "--output", output_dir,
                "--log-level", "INFO"
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )


    # UI: handlers for tab downloads
    def on_download_youtube(self):
        url = self.yt_entry.get().strip()
        if not url:
            messagebox.showwarning("Внимание", "Вставьте ссылку на YouTube")
            return
        job = {'url': url, 'type': 'yt', 'status': 'queued', 'message': ''}
        self.download_queue.append(job)
        self._refresh_queue_ui()

        self.download_tabview.set("Очередь")

        threading.Thread(target=self._worker_process_queue, daemon=True).start()

    def on_download_spotify(self):
        url = self.sp_entry.get().strip()
        if not url:
            messagebox.showwarning("Внимание", "Вставьте ссылку на Spotify")
            return
        job = {'url': url, 'type': 'sp', 'status': 'queued', 'message': ''}
        self.download_queue.append(job)
        self._refresh_queue_ui()
        self.download_tabview.set("Очередь")
        threading.Thread(target=self._worker_process_queue, daemon=True).start()

    def _worker_process_queue(self):
        for job in self.download_queue:
            if job['status'] == 'queued':
                job['status'] = 'downloading'
                self._refresh_queue_ui()
                try:
                    if job['type'] == 'yt':
                        self.download_audio_with_cover(job['url'])
                    else:
                        self.download_spotify_track(job['url'])
                    job['status'] = 'done'
                    job['message'] = 'OK'
                    self.load_tracks()
                except Exception as e:
                    job['status'] = 'error'
                    job['message'] = str(e)
                finally:
                    self._refresh_queue_ui()
                time.sleep(0.3)

    def _refresh_queue_ui(self):
        try:
            self.after(0, self._refresh_queue_ui_sync)
        except Exception:
            pass

    def _refresh_queue_ui_sync(self):
        self.queue_listbox.delete(0, tk.END)
        for idx, job in enumerate(self.download_queue):
            label = f"[{idx+1}] ({job['type']}) {job['status']}: {job['url']}"
            if job.get('message'):
                label += f" — {job['message']}"
            self.queue_listbox.insert(tk.END, label)

    def _periodic_queue_update(self):
        self._refresh_queue_ui()
        self.after(1000, self._periodic_queue_update)

    def open_downloads_folder(self):
        path = os.path.abspath(DOWNLOADS_DIR)
        try:
            if os.name == 'nt':
                os.startfile(path)
            elif os.name == 'posix':
                # xdg-open or open (mac)
                try:
                    os.system(f'xdg-open "{path}"')
                except Exception:
                    os.system(f'open "{path}"')
            else:
                #messagebox.showinfo("Папка загрузок", f"Путь: {path}")
                notification.notify(
                    title='Папка загрузок',
                    message= f"Путь: {path}",
                    app_name='Siffy Helper',
                    app_icon='assets/icon.ico',
                    timeout=15,
                    ticker='Новое уведомление',
                    toast=False 
                )
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))


if __name__ == "__main__":
    app = App()
    app.mainloop()
