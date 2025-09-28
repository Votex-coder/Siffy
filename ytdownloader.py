import os
import io
import yt_dlp
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from mutagen.id3 import ID3
import pygame
import requests

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

pygame.mixer.init()


class YouTubeMP3App:
    def __init__(self, root):
        self.root = root
        self.root.title("Siffy")
        self.root.geometry("900x450")

        self.selected_track = None
        self.track_length = 0
        self.is_paused = False

        # Левая часть: ввод ссылки
        frame_left = tk.Frame(root)
        frame_left.pack(side="left", fill="y", padx=10, pady=10)

        tk.Label(frame_left, text="Вставьте ссылку на видео:").pack()
        self.entry = tk.Entry(frame_left, width=40)
        self.entry.pack(pady=5)

        # Универсальная вставка (Windows/Linux/macOS)
        self.entry.bind("<Control-v>", self.paste_clipboard)
        self.entry.bind("<Control-V>", self.paste_clipboard)
        self.entry.bind("<Command-v>", self.paste_clipboard)

        tk.Button(frame_left, text="Скачать MP3", command=self.on_download).pack(pady=10)

        # Справа: список треков
        frame_right = tk.Frame(root)
        frame_right.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.tree = ttk.Treeview(frame_right, columns=("artist",), show="headings", height=15)
        self.tree.heading("artist", text="Исполнитель")
        self.tree.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_track_select)

        # Информация о треке
        frame_info = tk.Frame(frame_right)
        frame_info.pack(side="left", fill="both", expand=True, padx=10)

        self.cover_label = tk.Label(frame_info)
        self.cover_label.pack(pady=5)

        self.track_info = tk.Label(frame_info, text="", font=("Arial", 12))
        self.track_info.pack()

        # Кнопки управления
        control_frame = tk.Frame(frame_info)
        control_frame.pack(pady=10)

        self.btn_play = tk.Button(control_frame, text="▶️ Играть", command=self.play_track, state="disabled")
        self.btn_play.grid(row=0, column=0, padx=5)

        self.btn_pause = tk.Button(control_frame, text="⏸ Пауза", command=self.toggle_pause, state="disabled")
        self.btn_pause.grid(row=0, column=1, padx=5)

        self.btn_stop = tk.Button(control_frame, text="⏹ Стоп", command=self.stop_track, state="disabled")
        self.btn_stop.grid(row=0, column=2, padx=5)

        # Ползунок прогресса
        self.progress = ttk.Scale(frame_info, from_=0, to=100, orient="horizontal", command=self.seek_track)
        self.progress.pack(fill="x", pady=5)
        self.updating_slider = False

        self.load_tracks()
        self.update_progress()

    # ===== Вставка из буфера обмена =====
    def paste_clipboard(self, event=None):
        try:
            text = self.root.clipboard_get()
            self.entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"  # предотвращает двойную вставку

    # ===== Скачивание треков =====
    def download_audio_with_cover(self, url):
        ydl_opts = {
            'format': 'bestaudio/best',
            'writethumbnail': True,
            'convert-thumbnails': 'jpg',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata'},
            ],
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'retries': 10,              # Повторные попытки при ошибках
            'fragment_retries': 10,     # Повторные попытки на каждом фрагменте
            'socket_timeout': 30,       # Таймаут соединения
            'nocheckcertificate': True, # Игнорировать SSL ошибки
            'ratelimit': 500 * 1024,  # Ограничение скорости (раскомментируй при обрывах)
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # отдельно сохраним thumbnail как jpg
            if 'thumbnail' in info:
                thumb_url = info['thumbnail']
                try:
                    img_data = requests.get(thumb_url, timeout=15).content
                    img = Image.open(io.BytesIO(img_data))
                    thumb_path = os.path.join(DOWNLOADS_DIR, f"{info['title']}.jpg")
                    img.save(thumb_path)
                except Exception as e:
                    print(f"Не удалось сохранить отдельную обложку: {e}")

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

    # ===== Список треков =====
    def load_tracks(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for fname in os.listdir(DOWNLOADS_DIR):
            if fname.endswith(".mp3"):
                path = os.path.join(DOWNLOADS_DIR, fname)
                artist, title = self.get_tags(path)
                self.tree.insert("", "end", iid=path, values=(artist if artist else "Неизвестно",))

    def get_tags(self, filepath):
        try:
            audio = ID3(filepath)
            artist = audio.get("TPE1")
            title = audio.get("TIT2")
            return (artist.text[0] if artist else "", title.text[0] if title else os.path.basename(filepath))
        except Exception:
            return ("", os.path.basename(filepath))

    def on_track_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        filepath = selection[0]
        self.selected_track = filepath

        artist, title = self.get_tags(filepath)
        self.track_info.config(text=f"{artist} - {title}")

        cover_path = os.path.splitext(filepath)[0] + ".jpg"
        if os.path.exists(cover_path):
            image = Image.open(cover_path).resize((150, 150))
            img = ImageTk.PhotoImage(image)
            self.cover_label.config(image=img)
            self.cover_label.image = img
        else:
            self.cover_label.config(image="", text="(нет обложки)")

        self.btn_play.config(state="normal")
        self.btn_pause.config(state="normal")
        self.btn_stop.config(state="normal")

    # ===== Управление проигрывателем =====
    def play_track(self):
        if self.selected_track:
            pygame.mixer.music.load(self.selected_track)
            pygame.mixer.music.play()
            self.track_length = pygame.mixer.Sound(self.selected_track).get_length()
            self.is_paused = False

    def toggle_pause(self):
        if pygame.mixer.music.get_busy():
            if not self.is_paused:
                pygame.mixer.music.pause()
                self.is_paused = True
                self.btn_pause.config(text="▶️ Продолжить")
            else:
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.btn_pause.config(text="⏸ Пауза")

    def stop_track(self):
        pygame.mixer.music.stop()
        self.progress.set(0)
        self.is_paused = False
        self.btn_pause.config(text="⏸ Пауза")

    # ===== Прогресс =====
    def update_progress(self):
        if pygame.mixer.music.get_busy() and self.track_length > 0 and not self.is_paused:
            pos = pygame.mixer.music.get_pos() / 1000.0
            if pos >= 0:  # get_pos может вернуть -1
                if not self.updating_slider:
                    self.progress.set((pos / self.track_length) * 100)
        self.root.after(500, self.update_progress)

    def seek_track(self, val):
        if self.selected_track and self.track_length > 0:
            new_pos = float(val) / 100 * self.track_length
            pygame.mixer.music.set_pos(new_pos)


if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeMP3App(root)
    root.mainloop()
