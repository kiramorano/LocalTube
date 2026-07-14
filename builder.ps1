$base = "yt_dlp_plugins/extractor/getpot_bgutil"
New-Item -ItemType Directory -Force -Path $base | Out-Null

@"
from .getpot_bgutil import BgUtilPTPBase
__all__ = ['BgUtilPTPBase', 'getpot_bgutil', 'getpot_bgutil_http', 'getpot_bgutil_cli']
"@ | Out-File -FilePath "$base/__init__.py" -Encoding utf8

# Остальные файлы создайте аналогично, вставив их содержимое