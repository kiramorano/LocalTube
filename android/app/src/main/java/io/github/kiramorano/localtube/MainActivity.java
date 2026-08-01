package io.github.kiramorano.localtube;

import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
  private WebView web; private SharedPreferences prefs; private ValueCallback<Uri[]> picker;
  private final ActivityResultLauncher<Intent> chooseFile = registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), r -> {
    if (picker == null) return; Uri[] out = null;
    if (r.getResultCode() == RESULT_OK && r.getData() != null) { Uri u = r.getData().getData(); if (u != null) out = new Uri[]{u}; }
    picker.onReceiveValue(out); picker = null;
  });
  @SuppressLint("SetJavaScriptEnabled") @Override public void onCreate(Bundle state) { super.onCreate(state); setContentView(R.layout.activity_main);
    prefs=getSharedPreferences("localtube", MODE_PRIVATE); web=findViewById(R.id.webview);
    web.getSettings().setJavaScriptEnabled(true); web.getSettings().setDomStorageEnabled(true); web.getSettings().setAllowFileAccess(false);
    web.setWebViewClient(new WebViewClient(){ @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r){ Uri u=r.getUrl(); if ("http".equals(u.getScheme())||"https".equals(u.getScheme())) return false; try { startActivity(new Intent(Intent.ACTION_VIEW,u)); } catch(Exception ignored){} return true; }});
    web.setWebChromeClient(new WebChromeClient(){ @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p){ picker=cb; try { chooseFile.launch(p.createIntent()); return true; } catch(Exception e){ picker.onReceiveValue(null); picker=null; return false; } }});
    if (!prefs.contains("server")) showServerDialog(true); else load();
  }
  private String server(){ return prefs.getString("server", "http://localhost:5000"); }
  private void load(){ web.loadUrl(server()); }
  private void showServerDialog(boolean first){ EditText input=new EditText(this); input.setSingleLine(true); input.setText(server()); input.setHint(getString(R.string.server_hint)); int pad=(int)(20*getResources().getDisplayMetrics().density); input.setPadding(pad,0,pad,0); new AlertDialog.Builder(this).setTitle("LocalTube server").setMessage("This app connects to your LocalTube server. On a phone or TV, use your computer’s LAN address, e.g. http://192.168.1.20:5000.").setView(input).setCancelable(!first).setPositiveButton("Connect",(d,w)->{String s=input.getText().toString().trim(); if (!s.matches("https?://.+")){ showServerDialog(false); return;} prefs.edit().putString("server",s.replaceAll("/$","")).apply(); load();}).setNegativeButton(first?"Cancel":"Cancel",null).show(); }
  @Override public boolean onCreateOptionsMenu(Menu menu){getMenuInflater().inflate(R.menu.main_menu,menu);return true;}
  @Override public boolean onOptionsItemSelected(MenuItem item){if(item.getItemId()==R.id.action_server){showServerDialog(false);return true;}if(item.getItemId()==R.id.action_reload){load();return true;}return super.onOptionsItemSelected(item);}
  @Override public void onBackPressed(){if(web.canGoBack())web.goBack();else super.onBackPressed();}
}
