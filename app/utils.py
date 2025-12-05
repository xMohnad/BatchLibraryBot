import logging
import re

SUPPORTED_MEDIA = {"photo", "video", "document", "audio", "voice"}
CAPTION_PATTERN = re.compile(
    r"المستوى:\s*(الأول|الثاني|الثالث|الرابع).*?"
    r"الترم:\s*(الأول|الثاني).*?"
    r"المقرر:\s*(.+?)\s*"
    r"العنوان:\s*(.+)",
    re.S,
)
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pymongo").setLevel(logging.WARNING)

logger = logging.getLogger("Batch7LibraryBot")
