import json
from datetime import datetime
from core.settings import get_app_data_dir

class HistoryManager:
    def __init__(self):
        self.history_file = get_app_data_dir() / 'history.json'
        self.history = self.load()

    def load(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save(self):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=4)

    def add_entry(self, title: str, author: str, platform: str = "YouTube", status: str = "Completed", url: str = "", media_type: str = "Audio"):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            'timestamp': now_str,
            'date': now_str,
            'title': title,
            'author': author,
            'platform': platform,
            'url': url,
            'type': media_type,
            'status': status
        }
        self.history.insert(0, entry) # Add to top
        self.save()

    def get_all(self):
        return self.history
        
    def clear(self):
        self.history = []
        self.save()
