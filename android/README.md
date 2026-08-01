# LocalTube Android

This is a native Android client for a separately running LocalTube server. It does not embed Python, Flask, FFmpeg, or downloaded media. On first launch enter the server LAN address, for example `http://192.168.1.20:5000`. The `mobile` and `tv` debug APKs are built by GitHub Actions; they are unsigned and intended for testing. HTTP is enabled only for a trusted local network.
