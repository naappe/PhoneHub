package com.phonehub.companion

import android.app.*
import android.content.*
import android.os.*
import android.provider.Settings
import android.os.StatFs
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import org.json.JSONArray
import android.content.pm.ApplicationInfo
import java.net.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class CompanionService : Service() {
    companion object {
        private const val CHANNEL="phonehub_connection"; private const val NOTIFICATION_ID=7001
        private const val PREFS="phonehub"; private const val ENABLED="companion_enabled"; private const val PAIR_KEY="pair_key"
        private const val DISCOVERY_PORT=47321; private const val COMMAND_PORT=47322
        private const val RELAY_URL="https://tmupbruwmwlrmewhoodn.supabase.co/functions/v1/phonehub-relay"
        fun enable(c:Context){
            val p=c.getSharedPreferences(PREFS,0)
            if(!p.contains(PAIR_KEY)){val b=ByteArray(32);java.security.SecureRandom().nextBytes(b);p.edit().putString(PAIR_KEY,android.util.Base64.encodeToString(b,android.util.Base64.NO_WRAP)).apply()}
            p.edit().putBoolean(ENABLED,true).apply();start(c)
        }
        fun isEnabled(c:Context)=c.getSharedPreferences(PREFS,0).getBoolean(ENABLED,false)
        fun start(c:Context){ContextCompat.startForegroundService(c,Intent(c,CompanionService::class.java))}
    }
    private val running=AtomicBoolean(false); private var heartbeatThread:Thread?=null; private var commandThread:Thread?=null; private var remoteThread:Thread?=null
    override fun onCreate(){super.onCreate();val m=getSystemService(NotificationManager::class.java);m.createNotificationChannel(NotificationChannel(CHANNEL,"PhoneHub connection",NotificationManager.IMPORTANCE_LOW));startForeground(NOTIFICATION_ID,NotificationCompat.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("PhoneHub").setContentText("Companion service active").setOngoing(true).setSilent(true).build());startWorkers()}
    private fun startWorkers(){startHeartbeat();startCommandServer();startRemotePresence()}
    private fun deviceId()=Settings.Secure.getString(contentResolver,Settings.Secure.ANDROID_ID)?:"android"
    private fun keyBytes():ByteArray?{val s=getSharedPreferences(PREFS,0).getString(PAIR_KEY,null)?:return null;return android.util.Base64.decode(s,android.util.Base64.NO_WRAP)}
    private fun hmac(key:ByteArray,data:String):String{val m=Mac.getInstance("HmacSHA256");m.init(SecretKeySpec(key,"HmacSHA256"));return m.doFinal(data.toByteArray()).joinToString(""){"%02x".format(it)}}
    private fun secureEquals(a:String,b:String)=MessageDigest.isEqual(a.toByteArray(),b.toByteArray())
    private fun decrypt(key:ByteArray,nonceB64:String,cipherB64:String):JSONObject{val nonce=android.util.Base64.decode(nonceB64,android.util.Base64.NO_WRAP);val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,nonce));val plain=cipher.doFinal(android.util.Base64.decode(cipherB64,android.util.Base64.NO_WRAP));return JSONObject(String(plain,Charsets.UTF_8))}
    private fun encrypt(key:ByteArray,value:JSONObject):JSONObject{val nonce=ByteArray(12);java.security.SecureRandom().nextBytes(nonce);val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,nonce));val out=cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8));return JSONObject().put("type","encrypted").put("version",2).put("nonce",android.util.Base64.encodeToString(nonce,android.util.Base64.NO_WRAP)).put("ciphertext",android.util.Base64.encodeToString(out,android.util.Base64.NO_WRAP))}
    private fun hex(b:ByteArray)=b.joinToString(""){"%02x".format(it)}
    private fun remoteMailbox(key:ByteArray)=hex(MessageDigest.getInstance("SHA-256").digest((deviceId()+":"+android.util.Base64.encodeToString(key,android.util.Base64.NO_WRAP)).toByteArray()))
    private fun statusJson():JSONObject{
        val bm=getSystemService(BATTERY_SERVICE) as android.os.BatteryManager;val level=bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val stat=StatFs(filesDir.absolutePath);val am=getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager;val mi=android.app.ActivityManager.MemoryInfo();am.getMemoryInfo(mi)
        val cm=getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager;val caps=cm.getNetworkCapabilities(cm.activeNetwork)
        val network=when{caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true->"Wi-Fi";caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)==true->"Cellular";caps?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)==true->"Ethernet";else->"Offline"}
        return JSONObject().put("type","remote_presence").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("battery_percent",level).put("charging",bm.isCharging).put("storage_total",stat.totalBytes).put("storage_free",stat.availableBytes).put("memory_total",mi.totalMem).put("memory_free",mi.availMem).put("network",network).put("timestamp",System.currentTimeMillis()/1000)
    }
    private fun relaySend(mailbox:String,payload:JSONObject){
        val conn=URL(RELAY_URL).openConnection() as HttpURLConnection;conn.requestMethod="POST";conn.connectTimeout=8000;conn.readTimeout=8000;conn.doOutput=true;conn.setRequestProperty("Content-Type","application/json")
        val body=JSONObject().put("action","send").put("mailbox",mailbox).put("direction","to_pc").put("payload",payload).toString().toByteArray()
        conn.outputStream.use{it.write(body)};conn.inputStream.use{it.readBytes()};conn.disconnect()
    }
    private fun startRemotePresence(){
        if(remoteThread?.isAlive==true)return
        remoteThread=Thread({while(running.get()){try{val key=keyBytes();if(key!=null)relaySend(remoteMailbox(key),encrypt(key,statusJson()))}catch(_:Exception){};try{Thread.sleep(10000)}catch(_:InterruptedException){break}}},"phonehub-remote").apply{isDaemon=true;start()}
    }
    private fun startHeartbeat(){
        if(!running.compareAndSet(false,true))return
        heartbeatThread=Thread({DatagramSocket().use{socket->socket.broadcast=true;while(running.get()){try{val p=JSONObject().put("type","heartbeat").put("version",1).put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("command_port",COMMAND_PORT).put("auth","hmac-sha256").put("timestamp",System.currentTimeMillis()/1000).toString().toByteArray();socket.send(DatagramPacket(p,p.size,InetAddress.getByName("255.255.255.255"),DISCOVERY_PORT))}catch(_:Exception){};try{Thread.sleep(5000)}catch(_:InterruptedException){break}}}},"phonehub-heartbeat").apply{isDaemon=true;start()}
    }
    private fun startCommandServer(){
        if(commandThread?.isAlive==true)return
        commandThread=Thread({try{ServerSocket(COMMAND_PORT).use{server->server.soTimeout=2000;while(running.get()){try{server.accept().use{client->client.soTimeout=5000;val line=client.getInputStream().bufferedReader().readLine()?:return@use;val wireReq=JSONObject(line);val key=keyBytes();val encrypted=wireReq.optString("type")=="encrypted"&&wireReq.optInt("version")==2;val req=if(encrypted&&key!=null)decrypt(key,wireReq.optString("nonce"),wireReq.optString("ciphertext")) else wireReq;val response=JSONObject().put("version",2);val ts=req.optLong("timestamp",0);val nonce=req.optString("nonce");val sig=req.optString("signature");val now=System.currentTimeMillis()/1000;val canonical=req.optString("type")+"|"+ts+"|"+nonce;val authorized=key!=null&&encrypted&&nonce.isNotBlank()&&kotlin.math.abs(now-ts)<=30&&secureEquals(hmac(key,canonical),sig)
            if(req.optString("type")=="enroll"){if(key==null)response.put("type","error").put("message","companion not enabled") else response.put("type","enrolled").put("device_id",deviceId()).put("pair_key",android.util.Base64.encodeToString(key,android.util.Base64.NO_WRAP))}
            else if(!authorized)response.put("type","error").put("message","unauthorized")
            else when(req.optString("type")){
                "ping"->response.put("type","pong").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("timestamp",now)
                "device_status"->{
                    val bm=getSystemService(BATTERY_SERVICE) as android.os.BatteryManager
                    val level=bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)
                    val charging=bm.isCharging
                    val stat=StatFs(filesDir.absolutePath);val total=stat.totalBytes;val free=stat.availableBytes
                    val am=getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager;val mi=android.app.ActivityManager.MemoryInfo();am.getMemoryInfo(mi)
                    val cm=getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager;val caps=cm.getNetworkCapabilities(cm.activeNetwork)
                    val network=when{caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true->"Wi-Fi";caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)==true->"Cellular";caps?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)==true->"Ethernet";else->"Offline"}
                    response.put("type","device_status").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("manufacturer",Build.MANUFACTURER).put("model",Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("battery_percent",level).put("charging",charging).put("storage_total",total).put("storage_free",free).put("memory_total",mi.totalMem).put("memory_free",mi.availMem).put("network",network).put("uptime_seconds",SystemClock.elapsedRealtime()/1000).put("timestamp",now)
                }
                "apps"->{
                    val offset=req.optInt("offset",0).coerceAtLeast(0);val limit=req.optInt("limit",50).coerceIn(1,100)
                    val all=packageManager.getInstalledApplications(0).sortedBy{packageManager.getApplicationLabel(it).toString().lowercase()}
                    val arr=JSONArray();all.drop(offset).take(limit).forEach{a->arr.put(JSONObject().put("name",packageManager.getApplicationLabel(a).toString()).put("package",a.packageName).put("system",(a.flags and ApplicationInfo.FLAG_SYSTEM)!=0).put("enabled",a.enabled))}
                    response.put("type","apps_page").put("apps",arr).put("offset",offset).put("next_offset",offset+arr.length()).put("total",all.size).put("has_more",offset+arr.length()<all.size)
                }
                "capabilities"->response.put("type","capabilities").put("notifications",false).put("files",true).put("camera",false).put("screen_control",false).put("app_inventory",true)
                else->response.put("type","error").put("message","unsupported command")
            }
            val wireResponse=if(encrypted&&key!=null)encrypt(key,response) else response;client.getOutputStream().bufferedWriter().use{w->w.write(wireResponse.toString());w.newLine();w.flush()}
        }}catch(_:SocketTimeoutException){}catch(_:Exception){}}}}catch(_:Exception){}},"phonehub-command").apply{isDaemon=true;start()}
    }
    override fun onDestroy(){running.set(false);heartbeatThread?.interrupt();commandThread?.interrupt();remoteThread?.interrupt();super.onDestroy()}
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{startWorkers();return START_STICKY}
    override fun onBind(intent:Intent?):IBinder?=null
}
