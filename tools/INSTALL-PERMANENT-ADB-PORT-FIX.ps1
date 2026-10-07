param(
    [string]$ProjectRoot = "C:\Project-Archive\AndroidBridge-Calls"
)

$ErrorActionPreference = "Stop"
$Package = "com.androidbridge.calls"
$PhoneTailIP = "100.127.244.20"
$PcTailIP = "100.113.209.27"
$QueryPort = 5572
$AndroidNs = "http://schemas.android.com/apk/res/android"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " ANDROIDBRIDGE - PERMANENT DYNAMIC ADB PORT FIX" -ForegroundColor Cyan
Write-Host " Phone publishes its current secure ADB TLS port over Tailscale." -ForegroundColor DarkGray
Write-Host " No uninstall / no pairing reset / no adb kill-server / no adb disconnect." -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $ProjectRoot)) {
    throw "Mobile project not found: $ProjectRoot"
}

$Manifest = Join-Path $ProjectRoot "app\src\main\AndroidManifest.xml"
$JavaDir = Join-Path $ProjectRoot "app\src\main\java\com\androidbridge"
$Discovery = Join-Path $JavaDir "AdbTlsPortDiscovery.java"
$Server = Join-Path $JavaDir "AdbPortQueryServer.java"
$Provider = Join-Path $JavaDir "AdbPortInitProvider.java"

if (-not (Test-Path $Manifest)) { throw "Manifest not found: $Manifest" }
New-Item -ItemType Directory -Path $JavaDir -Force | Out-Null

$Backup = Join-Path $env:TEMP ("AndroidBridge-AdbPortPublisher-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $Backup -Force | Out-Null
Copy-Item $Manifest (Join-Path $Backup "AndroidManifest.xml") -Force
foreach ($p in @($Discovery,$Server,$Provider)) {
    if (Test-Path $p) { Copy-Item $p (Join-Path $Backup ([IO.Path]::GetFileName($p))) -Force }
}
Write-Host ("Safety copy: " + $Backup) -ForegroundColor DarkGray

$discoverySource = @'
package com.androidbridge;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.util.Log;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

public final class AdbTlsPortDiscovery {
    private static final String TAG = "SamsungSecureAdbPort";
    private static final String SERVICE_TYPE = "_adb-tls-connect._tcp.";
    private static final String OWN_SERVICE_PREFIX = "adb-R5CY20RCX8E-";

    private AdbTlsPortDiscovery() {}

    public static int discover(Context context, long timeoutMs) {
        final NsdManager nsd =
                (NsdManager) context.getSystemService(Context.NSD_SERVICE);
        if (nsd == null) return -1;

        final CountDownLatch done = new CountDownLatch(1);
        final AtomicInteger port = new AtomicInteger(-1);
        final AtomicBoolean resolving = new AtomicBoolean(false);

        final NsdManager.DiscoveryListener listener =
                new NsdManager.DiscoveryListener() {
            @Override
            public void onDiscoveryStarted(String serviceType) {
                Log.d(TAG, "ADB TLS discovery started");
            }

            @Override
            public void onServiceFound(NsdServiceInfo service) {
                String name = service == null ? null : service.getServiceName();
                if (name == null || !name.startsWith(OWN_SERVICE_PREFIX)) return;
                if (!resolving.compareAndSet(false, true)) return;

                try {
                    nsd.resolveService(service, new NsdManager.ResolveListener() {
                        @Override
                        public void onResolveFailed(NsdServiceInfo info, int errorCode) {
                            resolving.set(false);
                            Log.w(TAG, "ADB TLS resolve failed: " + errorCode);
                        }

                        @Override
                        public void onServiceResolved(NsdServiceInfo info) {
                            int p = info == null ? -1 : info.getPort();
                            if (p >= 1 && p <= 65535) {
                                port.set(p);
                                Log.i(TAG, "ADB TLS port discovered: " + p);
                            }
                            done.countDown();
                        }
                    });
                } catch (Exception e) {
                    resolving.set(false);
                    Log.w(TAG, "ADB TLS resolve exception", e);
                }
            }

            @Override
            public void onServiceLost(NsdServiceInfo service) {}

            @Override
            public void onDiscoveryStopped(String serviceType) {}

            @Override
            public void onStartDiscoveryFailed(String serviceType, int errorCode) {
                Log.w(TAG, "ADB TLS discovery failed: " + errorCode);
                done.countDown();
            }

            @Override
            public void onStopDiscoveryFailed(String serviceType, int errorCode) {}
        };

        boolean started = false;
        try {
            nsd.discoverServices(
                    SERVICE_TYPE,
                    NsdManager.PROTOCOL_DNS_SD,
                    listener
            );
            started = true;
            done.await(Math.max(1000L, timeoutMs), TimeUnit.MILLISECONDS);
        } catch (Exception e) {
            Log.w(TAG, "ADB TLS discovery exception", e);
        } finally {
            if (started) {
                try {
                    nsd.stopServiceDiscovery(listener);
                } catch (Exception ignored) {}
            }
        }

        return port.get();
    }
}
'@

$serverSource = @'
package com.androidbridge;

import android.content.Context;
import android.util.Log;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;

public final class AdbPortQueryServer {
    private static final String TAG = "SamsungSecureAdbQuery";
    private static final int LISTEN_PORT = 5572;
    private static final String ALLOWED_PC_TAILSCALE_IP = "100.113.209.27";
    private static final String REQUEST = "ANDROIDBRIDGE_ADB_PORT?";
    private static final AtomicBoolean STARTED = new AtomicBoolean(false);

    private AdbPortQueryServer() {}

    public static void start(Context context) {
        if (!STARTED.compareAndSet(false, true)) return;

        final Context app = context.getApplicationContext();
        Thread thread = new Thread(() -> runServer(app), "SamsungSecure-AdbPortQuery");
        thread.setDaemon(true);
        thread.start();
    }

    private static void runServer(Context context) {
        try (ServerSocket server = new ServerSocket()) {
            server.setReuseAddress(true);
            server.bind(new InetSocketAddress((InetAddress) null, LISTEN_PORT));
            Log.i(TAG, "ADB port query server listening on " + LISTEN_PORT);

            while (true) {
                Socket client = null;
                try {
                    client = server.accept();
                    client.setSoTimeout(12000);

                    String remote = client.getInetAddress().getHostAddress();
                    if (!ALLOWED_PC_TAILSCALE_IP.equals(remote)) {
                        Log.w(TAG, "Rejected ADB port query from " + remote);
                        client.close();
                        continue;
                    }

                    BufferedReader in = new BufferedReader(
                            new InputStreamReader(
                                    client.getInputStream(),
                                    StandardCharsets.US_ASCII
                            )
                    );
                    PrintWriter out = new PrintWriter(
                            client.getOutputStream(),
                            true
                    );

                    String request = in.readLine();
                    if (!REQUEST.equals(request)) {
                        out.println("ERROR=BAD_REQUEST");
                        client.close();
                        continue;
                    }

                    int port = AdbTlsPortDiscovery.discover(context, 7000L);
                    if (port >= 1 && port <= 65535) {
                        out.println("ADB_TLS_PORT=" + port);
                    } else {
                        out.println("ADB_TLS_PORT=0");
                    }
                } catch (Exception e) {
                    Log.w(TAG, "ADB port query failed", e);
                } finally {
                    if (client != null) {
                        try { client.close(); } catch (Exception ignored) {}
                    }
                }
            }
        } catch (Exception e) {
            STARTED.set(false);
            Log.e(TAG, "ADB port query server stopped", e);
        }
    }
}
'@

$providerSource = @'
package com.androidbridge;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;

public final class AdbPortInitProvider extends ContentProvider {
    @Override
    public boolean onCreate() {
        if (getContext() != null) {
            AdbPortQueryServer.start(getContext());
        }
        return true;
    }

    @Override
    public Cursor query(
            Uri uri,
            String[] projection,
            String selection,
            String[] selectionArgs,
            String sortOrder
    ) {
        return null;
    }

    @Override
    public String getType(Uri uri) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(
            Uri uri,
            ContentValues values,
            String selection,
            String[] selectionArgs
    ) {
        return 0;
    }
}
'@

Write-Utf8NoBom $Discovery $discoverySource
Write-Utf8NoBom $Server $serverSource
Write-Utf8NoBom $Provider $providerSource
Write-Host "Phone-side port discovery/query components: READY" -ForegroundColor Green

[xml]$xml = Get-Content $Manifest -Raw
$manifestNode = $xml.manifest
$app = $manifestNode.application
if (-not $manifestNode -or -not $app) { throw "Invalid Android manifest." }

function Ensure-Permission([string]$PermissionName) {
    foreach ($node in @($manifestNode.'uses-permission')) {
        if ($node.GetAttribute("name", $AndroidNs) -eq $PermissionName) {
            return
        }
    }
    $permission = $xml.CreateElement("uses-permission")
    $permission.SetAttribute("name", $AndroidNs, $PermissionName)
    [void]$manifestNode.InsertBefore($permission, $app)
    Write-Host ("Manifest permission added: " + $PermissionName) -ForegroundColor Green
}

Ensure-Permission "android.permission.INTERNET"
Ensure-Permission "android.permission.ACCESS_NETWORK_STATE"

$providerNode = $null
foreach ($node in @($app.provider)) {
    if ($node.GetAttribute("name", $AndroidNs) -eq "com.androidbridge.AdbPortInitProvider") {
        $providerNode = $node
        break
    }
}

if (-not $providerNode) {
    $providerNode = $xml.CreateElement("provider")
    $providerNode.SetAttribute("name", $AndroidNs, "com.androidbridge.AdbPortInitProvider")
    $providerNode.SetAttribute("authorities", $AndroidNs, "com.androidbridge.calls.adbport")
    $providerNode.SetAttribute("exported", $AndroidNs, "false")
    $providerNode.SetAttribute("initOrder", $AndroidNs, "100")
    [void]$app.AppendChild($providerNode)
    Write-Host "Manifest provider: ADDED" -ForegroundColor Green
} else {
    Write-Host "Manifest provider: ALREADY PRESENT" -ForegroundColor DarkGray
}

$settings = New-Object System.Xml.XmlWriterSettings
$settings.Indent = $true
$settings.Encoding = New-Object System.Text.UTF8Encoding($false)
$writer = [System.Xml.XmlWriter]::Create($Manifest, $settings)
try { $xml.Save($writer) } finally { $writer.Close() }

Write-Host ""
Write-Host "[1/5] Building Samsung Secure..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & .\gradlew.bat assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}

$Apk = Join-Path $ProjectRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $Apk)) { throw "APK not found: $Apk" }

Write-Host ""
Write-Host "[2/5] Finding the already-authorized Samsung ADB route..." -ForegroundColor Cyan
$Device = $null
$rows = @(adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice(\s|$)" })
$serials = @($rows | ForEach-Object { ($_ -split "\s+")[0] })

$Device = $serials |
    Where-Object { $_ -match "^100\.127\.244\.20:\d+$" } |
    Select-Object -First 1

if (-not $Device) {
    $Device = $serials |
        Where-Object { $_ -eq "R5CY20RCX8E" } |
        Select-Object -First 1
}

if (-not $Device) {
    $cache = "C:\AndroidBridge-Lite\pc\.androidbridge-adb-tls-port"
    if (Test-Path $cache) {
        $p = (Get-Content $cache -Raw).Trim()
        if ($p -match "^\d+$") {
            adb connect ($PhoneTailIP + ":" + $p) | Out-Host
            Start-Sleep -Seconds 2
            if ((adb devices | Out-String) -match ([regex]::Escape($PhoneTailIP + ":" + $p) + "\s+device")) {
                $Device = $PhoneTailIP + ":" + $p
            }
        }
    }
}

if (-not $Device) {
    Write-Host "Existing endpoint unavailable; running the proven recovery once..." -ForegroundColor Yellow
    python "C:\AndroidBridge-Lite\tools\recover_remote_adb.py"
    if ($LASTEXITCODE -eq 0) {
        $Device = (adb devices | Select-Object -Skip 1 |
            Where-Object { $_ -match "^100\.127\.244\.20:\d+\s+device" } |
            ForEach-Object { ($_ -split "\s+")[0] } |
            Select-Object -First 1)
    }
}

if (-not $Device) {
    throw "No authorized Samsung ADB route is available. Nothing was uninstalled or reset."
}

Write-Host ("ADB route: " + $Device) -ForegroundColor Green

Write-Host ""
Write-Host "[3/5] Installing in place..." -ForegroundColor Cyan
adb -s $Device install -r $Apk | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "APK update failed. Existing Samsung Secure was NOT uninstalled."
}

adb -s $Device shell pm grant $Package android.permission.WRITE_SECURE_SETTINGS 2>$null
adb -s $Device shell settings put global adb_wifi_enabled 1
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "[4/5] Starting app process so the private query provider is initialized..." -ForegroundColor Cyan
adb -s $Device shell am start -n com.androidbridge.calls/com.androidbridge.MainActivity | Out-Null
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "[5/5] Verifying permanent port publisher through Tailscale..." -ForegroundColor Cyan

function Query-PortPublisher {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.ConnectAsync($PhoneTailIP, $QueryPort)
        if (-not $connect.Wait(5000)) {
            $client.Dispose()
            return $null
        }

        $stream = $client.GetStream()
        $stream.ReadTimeout = 12000
        $writer2 = [System.IO.StreamWriter]::new($stream, [Text.Encoding]::ASCII, 1024, $true)
        $writer2.NewLine = [Environment]::NewLine
        $writer2.WriteLine("ANDROIDBRIDGE_ADB_PORT?")
        $writer2.Flush()

        $reader = [System.IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 1024, $true)
        $line = $reader.ReadLine()
        $client.Dispose()
        return $line
    } catch {
        return $null
    }
}

$reply = $null
for ($i = 1; $i -le 6 -and -not $reply; $i++) {
    $reply = Query-PortPublisher
    if (-not $reply) { Start-Sleep -Seconds 3 }
}

Write-Host ("Publisher reply: " + $(if($reply){$reply}else{"NO RESPONSE"}))

if ($reply -notmatch "^ADB_TLS_PORT=(\d+)$" -or [int]$Matches[1] -le 0) {
    Write-Host ""
    Write-Host "APK installed, but the fixed Tailscale port publisher did not verify yet." -ForegroundColor Yellow
    Write-Host "Do not uninstall/reset anything. The existing ADB connection remains intact."
    exit 3
}

$PublishedPort = [int]$Matches[1]
Set-Content -Path "C:\AndroidBridge-Lite\pc\.androidbridge-adb-tls-port" -Value $PublishedPort -NoNewline -Encoding Ascii

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " PERMANENT DYNAMIC ADB PORT FIX INSTALLED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ("Phone Tailscale IP : " + $PhoneTailIP)
Write-Host ("Fixed query port   : " + $QueryPort)
Write-Host ("Current ADB TLS    : " + $PublishedPort)
Write-Host "ADB pairing         : PRESERVED"
Write-Host "App data            : PRESERVED"
Write-Host "Wireless Debugging  : PERSISTENT"
Write-Host "Fallback port scan  : KEPT ONLY AS EMERGENCY FALLBACK"
Write-Host ""
Write-Host "After future phone reboots AndroidBridge asks Samsung Secure for the"
Write-Host "new random ADB TLS port directly instead of scanning 28,000 ports."
