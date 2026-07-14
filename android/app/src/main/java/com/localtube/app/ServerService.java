package com.localtube.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * Foreground-сервис, в котором живёт встроенный Python-сервер LocalTube.
 * Сервер продолжает работать (скачивание видео и т.д.), пока приложение свернуто.
 */
public class ServerService extends Service {

    private static final String TAG = "LocalTubeServer";
    private static final String CHANNEL_ID = "localtube_server";
    private static final int NOTIFICATION_ID = 1;

    private static volatile boolean serverStarted = false;
    private Thread serverThread;

    public static void start(Context ctx) {
        Intent intent = new Intent(ctx, ServerService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ctx.startForegroundService(intent);
        } else {
            ctx.startService(intent);
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notification = buildNotification();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }

        if (!serverStarted) {
            serverStarted = true;
            serverThread = new Thread(this::runServer, "localtube-python");
            serverThread.setDaemon(true);
            serverThread.start();
        }
        return START_STICKY;
    }

    private void runServer() {
        try {
            AssetCopier.ensureCopied(this);

            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python py = Python.getInstance();
            String appRoot = AssetCopier.appRoot(this).getAbsolutePath();
            String nativeLibDir = getApplicationInfo().nativeLibraryDir;

            Log.i(TAG, "Запуск LocalTube: root=" + appRoot + " libs=" + nativeLibDir);
            // Блокируется навсегда (Flask app.run)
            py.getModule("localtube_bootstrap").callAttr("start_server", appRoot, nativeLibDir);
        } catch (Throwable t) {
            Log.e(TAG, "Сервер упал", t);
            serverStarted = false;
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.notification_channel),
                    NotificationManager.IMPORTANCE_LOW);
            channel.setShowBadge(false);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(getString(R.string.notification_text))
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
