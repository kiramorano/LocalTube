package com.localtube.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.res.AssetManager;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * Копирует исходники LocalTube (py/templates/static) из APK assets
 * в filesDir/localtube, чтобы сервер работал с реальной файловой системой.
 *
 * Код перезаписывается при обновлении приложения (по versionCode),
 * пользовательские данные (config.json, cookies.txt, видео и т.д.) сохраняются.
 */
public final class AssetCopier {

    private static final String ASSET_ROOT = "localtube";
    private static final String PREFS = "localtube_prefs";
    private static final String KEY_VERSION = "copied_version";

    /** Файлы, которые не перезаписываем, если пользователь их уже менял. */
    private static final Set<String> PRESERVE = new HashSet<>(
            Arrays.asList("config.json", "cookies.txt"));

    private AssetCopier() {}

    public static File appRoot(Context ctx) {
        return new File(ctx.getFilesDir(), ASSET_ROOT);
    }

    public static synchronized void ensureCopied(Context ctx) throws IOException {
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long current;
        try {
            PackageInfo pi = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
            current = pi.versionCode;
        } catch (Exception e) {
            current = 1;
        }

        File root = appRoot(ctx);
        boolean firstRun = !root.exists();
        if (!firstRun && prefs.getLong(KEY_VERSION, -1) == current) {
            return; // уже скопировано для этой версии
        }

        copyAssetDir(ctx.getAssets(), ASSET_ROOT, root, firstRun);
        prefs.edit().putLong(KEY_VERSION, current).apply();
    }

    private static void copyAssetDir(AssetManager am, String assetPath, File dst, boolean firstRun)
            throws IOException {
        String[] children = am.list(assetPath);
        if (children == null || children.length == 0) {
            // это файл
            copyAssetFile(am, assetPath, dst, firstRun);
            return;
        }
        if (!dst.exists() && !dst.mkdirs()) {
            throw new IOException("Не удалось создать папку: " + dst);
        }
        for (String child : children) {
            copyAssetDir(am, assetPath + "/" + child, new File(dst, child), firstRun);
        }
    }

    private static void copyAssetFile(AssetManager am, String assetPath, File dst, boolean firstRun)
            throws IOException {
        if (dst.exists() && PRESERVE.contains(dst.getName())) {
            return; // сохраняем пользовательские данные
        }
        File parent = dst.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();

        try (InputStream in = am.open(assetPath);
             OutputStream out = new FileOutputStream(dst)) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
    }
}
