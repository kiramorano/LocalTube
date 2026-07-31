# Platform support and release artifacts

LocalTube is a Python/Flask application. Its UI is served locally by `app.py` and requires a compatible `ffmpeg` executable on `PATH` for media processing.

## Release artifacts

Pushing the exact `v1.7` tag runs the release workflow. It builds and attaches these real, runnable desktop packages to the GitHub Release:

- `LocalTube-windows-x64.zip` — PyInstaller `onedir` package built on Windows.
- `LocalTube-linux-x64.tar.gz` — PyInstaller `onedir` package built on Ubuntu.
- GitHub's automatically generated source ZIP and TAR.GZ for the tag.

Unpack a desktop archive, ensure `ffmpeg` is available on `PATH`, then run `LocalTube.exe` on Windows or `./LocalTube/LocalTube` on Linux. The package contains the Flask templates, static assets, default configuration, and `yt-dlp` runtime data. User media and runtime files are created next to the packaged application data.

## Not packaged

No APK, Android TV APK, macOS app, iOS app, or native TV package is produced. The repository contains only a CPython/Flask desktop/server application; it has no Android/TV project, Gradle build, native mobile UI, or supported embedded Python/FFmpeg runtime. A WebView wrapper alone would not run this local server and media stack, so creating one (or a placeholder APK) would be misleading.

macOS is not built because this release infrastructure is explicitly limited to the currently supported Windows and Linux desktop targets. A macOS build requires testing and distribution decisions (including platform signing/notarization where appropriate).
