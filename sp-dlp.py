import os
import sys
import subprocess
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from pathlib import Path
import logging
from typing import List, Optional

class SpotifyDownloader:
    def __init__(self, client_id: str = None, client_secret: str = None):
        self.setup_logging()
        self.client_id = client_id
        self.client_secret = client_secret
        self.spotify_client = None
        
        # Проверяем установлен ли spotDL
        self._check_spotdl_installation()
        
        # Инициализируем Spotify клиент если есть credentials
        if client_id and client_secret:
            self._setup_spotify_client()
    
    def setup_logging(self):
        """Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('spotify_downloader.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _check_spotdl_installation(self):
        """Проверка установки spotDL"""
        try:
            import spotdl
            self.logger.info("✅ spotDL найден в системе")
            self.spotdl_available = True
        except ImportError:
            self.logger.warning("❌ spotDL не установлен")
            self.spotdl_available = False
    
    def _setup_spotify_client(self):
        """Настройка Spotify клиента"""
        try:
            self.spotify_client = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
            )
            self.logger.info("✅ Spotify клиент инициализирован")
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации Spotify клиента: {e}")
    
    def install_spotdl(self):
        """Установка spotDL"""
        self.logger.info("Устанавливаем spotDL...")
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", "spotdl"
            ], check=True)
            self.spotdl_available = True
            self.logger.info("✅ spotDL успешно установлен")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"❌ Ошибка установки spotDL: {e}")
            return False
    
    def download_track(self, spotify_url: str, output_dir: str = "downloads") -> bool:
        """Скачать один трек"""
        if not self.spotdl_available:
            self.logger.error("spotDL не доступен")
            return False
        
        Path(output_dir).mkdir(exist_ok=True)
        
        try:
            self.logger.info(f"🎵 Начинаем загрузку трека: {spotify_url}")
            
            # Используем spotDL через командную строку
            cmd = [
                "spotdl", "download", spotify_url,
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
            
            # Логируем вывод в реальном времени
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.logger.info(f"📥 {line}")
            
            process.wait()
            
            if process.returncode == 0:
                self.logger.info("✅ Трек успешно загружен")
                return True
            else:
                self.logger.error(f"❌ Ошибка загрузки трека")
                return False
                
        except Exception as e:
            self.logger.error(f"💥 Ошибка при загрузке трека: {e}")
            return False
    
    def download_playlist(self, playlist_url: str, output_dir: str = "downloads") -> bool:
        """Скачать весь плейлист"""
        if not self.spotdl_available:
            self.logger.error("spotDL не доступен")
            return False
        
        Path(output_dir).mkdir(exist_ok=True)
        
        try:
            self.logger.info(f"🎵 Начинаем загрузку плейлиста: {playlist_url}")
            
            cmd = [
                "spotdl", "download", playlist_url,
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
            
            for line in process.stdout:
                line = line.strip()
                if line and "Downloaded" in line:
                    self.logger.info(f"✅ {line}")
                elif line and "Downloading" in line:
                    self.logger.info(f"📥 {line}")
                elif line and "error" in line.lower():
                    self.logger.error(f"❌ {line}")
            
            process.wait()
            
            if process.returncode == 0:
                self.logger.info("✅ Плейлист успешно загружен")
                return True
            else:
                self.logger.error("❌ Ошибка загрузки плейлиста")
                return False
                
        except Exception as e:
            self.logger.error(f"💥 Ошибка при загрузке плейлиста: {e}")
            return False
    
    def download_album(self, album_url: str, output_dir: str = "downloads") -> bool:
        """Скачать альбом"""
        return self.download_playlist(album_url, output_dir)
    
    def search_and_download(self, query: str, output_dir: str = "downloads") -> bool:
        """Поиск и загрузка по названию"""
        if not self.spotdl_available:
            self.logger.error("spotDL не доступен")
            return False
        
        try:
            self.logger.info(f"🔍 Поиск и загрузка: {query}")
            
            cmd = [
                "spotdl", "download", f"'{query}'",
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
            
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.logger.info(f"📥 {line}")
            
            process.wait()
            
            if process.returncode == 0:
                self.logger.info("✅ Трек успешно загружен")
                return True
            else:
                self.logger.error("❌ Ошибка загрузки")
                return False
                
        except Exception as e:
            self.logger.error(f"💥 Ошибка при поиске и загрузке: {e}")
            return False

# Пример использования
if __name__ == "__main__":
    # Инициализация без Spotify credentials (только для загрузки)
    downloader = SpotifyDownloader()
    
    # Установка spotDL если не установлен
    if not downloader.spotdl_available:
        downloader.install_spotdl()
    
    # Примеры использования
    downloader.download_track("https://open.spotify.com/track/3wHBCK8Ogp82xWYWbVg7Ri?si=779e804dab2143f3")
    # downloader.download_playlist("https://open.spotify.com/playlist/...")
    # downloader.search_and_download("artist - song name")