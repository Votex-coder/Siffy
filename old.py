import os
import io
import yt_dlp
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
import pygame
import requests

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

pygame.mixer.init()

class MP3PlayerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Siffy")
        self.root.geometry("1280x720")
        self.root.configure(bg="#2b2b2b")

        # Иконка окна
        try:
            icon_path = os.path.join("assets", "icon.png")
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
        except:
            pass
        
        self.root.resizable(False, False)

        self.tracks = []
        self.selected_track = None
        self.track_index = -1
        self.track_length = 0
        self.is_paused = False
        self.current_pos = 0
        self.user_seeking = False

        # Стили
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#3c3c3c", fieldbackground="#3c3c3c", foreground="white", rowheight=25)
        style.configure("Treeview.Heading", background="#2b2b2b", foreground="white", font=("Arial", 11, "bold"))
        style.configure("TButton", padding=6, relief="flat", background="#4c4c4c", foreground="white")
        style.map("TButton", background=[("active", "#5a5a5a")])

        # Левый блок (список треков)
        frame_left = tk.Frame(root, bg="#2b2b2b")
        frame_left.pack(side="left", fill="y", padx=10, pady=10)

        tk.Label(frame_left, text="Треки:", fg="white", bg="#2b2b2b", font=("Arial", 12)).pack()
        self.tree = ttk.Treeview(frame_left, columns=("title",), show="headings", height=25)
        self.tree.heading("title", text="Название трека")
        self.tree.pack(fill="y", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_track_select)

        # Правый блок
        frame_right = tk.Frame(root, bg="#2b2b2b")
        frame_right.pack(side="left", fill="both", expand=True, padx=20, pady=20)

        # Обложка
        self.cover_label = tk.Label(frame_right, bg="#2b2b2b")
        self.cover_label.pack(pady=10)

        # Информация о треке
        self.track_info = tk.Label(frame_right, text="", font=("Arial", 14), fg="white", bg="#2b2b2b")
        self.track_info.pack()

        # Кнопки управления
        control_frame = tk.Frame(frame_right, bg="#2b2b2b")
        control_frame.pack(pady=10)

        self.btn_prev = ttk.Button(control_frame, text="⏮\nназад", command=self.prev_track, state="disabled")
        self.btn_prev.grid(row=0, column=0, padx=5)

        self.btn_playpause = ttk.Button(control_frame, text="▶️", command=self.play_pause, state="disabled")
        self.btn_playpause.grid(row=0, column=1, padx=10)

        self.btn_next = ttk.Button(control_frame, text="⏭\nвперед", command=self.next_track, state="disabled")
        self.btn_next.grid(row=0, column=2, padx=5)

        # Прогресс
        self.progress = ttk.Scale(frame_right, from_=0, to=100, orient="horizontal")
        self.progress.pack(fill="x", pady=5)
        self.progress.bind("<Button-1>", self.start_seek)
        self.progress.bind("<ButtonRelease-1>", self.end_seek)

        # Таймер
        timer_frame = tk.Frame(frame_right, bg="#2b2b2b")
        timer_frame.pack(fill="x")

        self.time_elapsed = tk.Label(timer_frame, text="0:00", fg="white", bg="#2b2b2b", font=("Arial", 10))
        self.time_elapsed.pack(side="left")

        self.time_total = tk.Label(timer_frame, text="0:00", fg="white", bg="#2b2b2b", font=("Arial", 10))
        self.time_total.pack(side="right")

        # Громкость
        volume_frame = tk.Frame(frame_right, bg="#2b2b2b")
        volume_frame.pack(fill="x", pady=10)

        self.volume_icon = tk.Label(volume_frame, text="🔉", fg="white", bg="#2b2b2b", font=("Arial", 12))
        self.volume_icon.pack(side="left", padx=5)

        self.volume_slider = ttk.Scale(volume_frame, from_=0, to=1, orient="horizontal", command=self.set_volume)
        self.volume_slider.set(0.5)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=5)

        pygame.mixer.music.set_volume(0.5)

        # === Блок для скачивания с YouTube (перемещён ниже кнопок) ===
        download_frame = tk.Frame(frame_right, bg="#2b2b2b")
        download_frame.pack(pady=15, fill="x")

        tk.Label(download_frame, text="Ссылка YouTube:", fg="white", bg="#2b2b2b").pack(anchor="w")
        self.entry = tk.Entry(download_frame, width=40)
        self.entry.pack(pady=5, fill="x")

        self.entry.bind("<Control-v>", self.paste_clipboard)
        self.entry.bind("<Control-V>", self.paste_clipboard)
        self.entry.bind("<Command-v>", self.paste_clipboard)

        ttk.Button(download_frame, text="Скачать MP3", command=self.on_download).pack(pady=5)

        self.load_tracks()
        self.update_progress()

    # ===== YouTube Downloader =====
    def paste_clipboard(self, event=None):
        try:
            text = self.root.clipboard_get()
            self.entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"

    def download_audio_with_cover(self, url):
        ydl_opts = {
            'format': 'bestaudio/best',
            'writethumbnail': True,
            'convert-thumbnails': 'jpg',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata'},
            ],
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
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
                    print(f"Не удалось сохранить обложку: {e}")

    def on_download(self):
        url = self.entry.get().strip()
        if not url:
            messagebox.showwarning("Внимание", "Введите ссылку на YouTube!")
            return
        try:
            self.download_audio_with_cover(url)
            messagebox.showinfo("Готово ✅", "Аудио успешно скачано!")
            self.load_tracks()
        except Exception as e:
            messagebox.showerror("Ошибка ❌", str(e))

    # ===== Работа с файлами =====
    def load_tracks(self):
        self.tracks = []
        for i in self.tree.get_children():
            self.tree.delete(i)
        for fname in os.listdir(DOWNLOADS_DIR):
            if fname.lower().endswith(".mp3"):
                path = os.path.join(DOWNLOADS_DIR, fname)
                artist, title = self.get_tags(path)
                display_title = title if title else os.path.splitext(fname)[0]
                self.tree.insert("", "end", iid=path, values=(display_title,))
                self.tracks.append(path)

    def get_tags(self, filepath):
        try:
            audio = ID3(filepath)
            artist = audio.get("TPE1")
            title = audio.get("TIT2")
            return (artist.text[0] if artist else "", title.text[0] if title else "")
        except Exception:
            return ("", "")

    def get_cover(self, filepath):
        jpg_path = os.path.splitext(filepath)[0] + ".jpg"
        if os.path.exists(jpg_path):
            return Image.open(jpg_path)
        try:
            audio = ID3(filepath)
            for tag in audio.values():
                if tag.FrameID == "APIC":
                    return Image.open(io.BytesIO(tag.data))
        except Exception:
            return None
        return None

    # ===== Обработка выбора =====
    def on_track_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        self.track_index = self.tracks.index(selection[0])
        self.load_track()

    def load_track(self):
        filepath = self.tracks[self.track_index]
        self.selected_track = filepath

        artist, title = self.get_tags(filepath)
        display_text = f"{artist} - {title}" if artist and title else title if title else os.path.basename(filepath)
        self.track_info.config(text=display_text)

        cover_img = self.get_cover(filepath)
        if cover_img:
            image = cover_img.resize((200, 200))
            img = ImageTk.PhotoImage(image)
            self.cover_label.config(image=img, text="")
            self.cover_label.image = img
        else:
            self.cover_label.config(image="", text="(нет обложки)", fg="white")

        self.track_length = MP3(filepath).info.length
        mins, secs = divmod(int(self.track_length), 60)
        self.time_total.config(text=f"{mins}:{secs:02d}")

        self.btn_playpause.config(state="normal")
        self.btn_prev.config(state="normal")
        self.btn_next.config(state="normal")

    # ===== Управление =====
    def play_pause(self):
        if not self.selected_track:
            return

        if not pygame.mixer.music.get_busy() and not self.is_paused:
            pygame.mixer.music.load(self.selected_track)
            pygame.mixer.music.play(start=self.current_pos)
            self.is_paused = False
            self.btn_playpause.config(text="⏸")
        elif not self.is_paused:
            self.current_pos = pygame.mixer.music.get_pos() / 1000.0
            pygame.mixer.music.stop()
            self.is_paused = True
            self.btn_playpause.config(text="▶️")
        else:
            pygame.mixer.music.load(self.selected_track)
            pygame.mixer.music.play(start=self.current_pos)
            self.is_paused = False
            self.btn_playpause.config(text="⏸")

    def next_track(self):
        if self.track_index < len(self.tracks) - 1:
            self.track_index += 1
        else:
            self.track_index = 0
        self.current_pos = 0
        self.load_track()
        self.play_pause()

    def prev_track(self):
        if self.track_index > 0:
            self.track_index -= 1
        else:
            self.track_index = len(self.tracks) - 1
        self.current_pos = 0
        self.load_track()
        self.play_pause()

    # ===== Прогресс =====
    def update_progress(self):
        if self.selected_track and pygame.mixer.music.get_busy() and not self.is_paused:
            pos = pygame.mixer.music.get_pos() / 1000.0 + self.current_pos
            if not self.user_seeking and pos >= 0:
                self.progress.set((pos / self.track_length) * 100)
            mins, secs = divmod(int(pos), 60)
            self.time_elapsed.config(text=f"{mins}:{secs:02d}")

            if pos >= self.track_length - 1:
                self.next_track()

        self.root.after(500, self.update_progress)

    def start_seek(self, event):
        self.user_seeking = True

    def end_seek(self, event):
        if self.selected_track:
            value = self.progress.get()
            new_pos = (value / 100) * self.track_length
            self.current_pos = new_pos
            pygame.mixer.music.stop()
            pygame.mixer.music.load(self.selected_track)
            pygame.mixer.music.play(start=new_pos)
            self.is_paused = False
            self.btn_playpause.config(text="⏸")
        self.user_seeking = False

    # ===== Громкость =====
    def set_volume(self, value):
        vol = float(value)
        pygame.mixer.music.set_volume(vol)
        if vol == 0:
            self.volume_icon.config(text="🔇")
        elif vol < 0.5:
            self.volume_icon.config(text="🔉")
        else:
            self.volume_icon.config(text="🔊")


if __name__ == "__main__":
    root = tk.Tk()
    app = MP3PlayerApp(root)
    root.mainloop()
