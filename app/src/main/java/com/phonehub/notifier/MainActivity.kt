package com.phonehub.notifier

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { PhoneHubApp() }
    }
}

enum class Tab { HOME, APPS, POLICIES, NOTIFICATIONS, SETTINGS }

@Composable
fun PhoneHubApp() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val store = remember { PolicyStore(context) }
    val controller = remember { DevicePolicyController(context) }
    var tab by remember { mutableStateOf(Tab.HOME) }
    var selectedPackage by remember { mutableStateOf<String?>(null) }

    MaterialTheme(colorScheme = darkColorScheme()) {
        Scaffold(
            bottomBar = {
                NavigationBar {
                    val nav = listOf(
                        Tab.HOME to Icons.Default.Home,
                        Tab.APPS to Icons.Default.Apps,
                        Tab.POLICIES to Icons.Default.Policy,
                        Tab.NOTIFICATIONS to Icons.Default.Notifications,
                        Tab.SETTINGS to Icons.Default.Settings,
                    )
                    nav.forEach { (t, icon) ->
                        NavigationBarItem(
                            selected = tab == t,
                            onClick = { tab = t; selectedPackage = null },
                            icon = { Icon(icon, contentDescription = t.name) },
                            label = { Text(t.name.lowercase().replaceFirstChar { it.uppercase() }) }
                        )
                    }
                }
            }
        ) { pad ->
            Box(Modifier.padding(pad)) {
                if (selectedPackage != null) {
                    AppPolicyScreen(
                        packageName = selectedPackage!!,
                        store = store,
                        controller = controller,
                        onBack = { selectedPackage = null }
                    )
                } else when (tab) {
                    Tab.HOME -> HomeScreen(controller, store, onApps = { tab = Tab.APPS }, onPolicies = { tab = Tab.POLICIES }, onSettings = { tab = Tab.SETTINGS })
                    Tab.APPS -> AppsScreen(controller, store) { selectedPackage = it }
                    Tab.POLICIES -> PoliciesScreen(store, controller)
                    Tab.NOTIFICATIONS -> NotificationsScreen(store)
                    Tab.SETTINGS -> SettingsScreen(store, controller)
                }
            }
        }
    }
}

@Composable
private fun Header(title: String, subtitle: String? = null) {
    Column(Modifier.fillMaxWidth().padding(20.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        if (subtitle != null) Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun StatusCard(title: String, value: String, supporting: String, icon: @Composable () -> Unit, onClick: (() -> Unit)? = null) {
    Card(onClick = { onClick?.invoke() }, enabled = onClick != null, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            icon(); Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) { Text(title, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(value, fontWeight = FontWeight.Bold); Text(supporting, style = MaterialTheme.typography.bodySmall) }
            if (onClick != null) Icon(Icons.Default.ChevronRight, null)
        }
    }
}

@Composable
fun HomeScreen(controller: DevicePolicyController, store: PolicyStore, onApps: () -> Unit, onPolicies: () -> Unit, onSettings: () -> Unit) {
    val apps = remember { controller.installedApps() }
    val suspended = apps.count { store.get(it.packageName).suspended }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Header("PhoneHub", "Your device. Your control.") }
        item { StatusCard("Connection", if (store.receiverUrl().isBlank()) "Not configured" else "Configured", "PhoneHub receiver", { Icon(Icons.Default.Wifi, null) }, onSettings) }
        item { StatusCard("Device Owner", if (controller.isDeviceOwner()) "Active" else "Inactive", if (controller.isDeviceOwner()) "Policy controls available" else "Provisioning required", { Icon(Icons.Default.AdminPanelSettings, null) }, onSettings) }
        item { StatusCard("Managed Apps", "${apps.size} apps", "$suspended suspended", { Icon(Icons.Default.Apps, null) }, onApps) }
        item { StatusCard("Policies", if (store.autoApply()) "Auto apply ON" else "Auto apply OFF", "Tap to manage policy behavior", { Icon(Icons.Default.Policy, null) }, onPolicies) }
    }
}

@Composable
fun AppsScreen(controller: DevicePolicyController, store: PolicyStore, onSelect: (String) -> Unit) {
    var query by remember { mutableStateOf("") }
    var showSystem by remember { mutableStateOf(false) }
    val apps = remember { controller.installedApps() }
    val filtered = apps.filter { (showSystem || !it.isSystem) && (query.isBlank() || it.label.contains(query, true) || it.packageName.contains(query, true)) }
    Column {
        Header("Apps", "Manage installed apps on this device")
        OutlinedTextField(query, { query = it }, leadingIcon = { Icon(Icons.Default.Search, null) }, label = { Text("Search apps") }, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) { Switch(showSystem, { showSystem = it }); Spacer(Modifier.width(8.dp)); Text("Show system apps") }
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(filtered, key = { it.packageName }) { app ->
                val p = store.get(app.packageName)
                Card(onClick = { onSelect(app.packageName) }, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (app.isSystem) Icons.Default.Settings else Icons.Default.Android, null)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) { Text(app.label, fontWeight = FontWeight.SemiBold); Text(app.packageName, style = MaterialTheme.typography.bodySmall) }
                        Text(if (p.suspended || !p.allowUsage) "Suspended" else "Allowed", color = if (p.suspended || !p.allowUsage) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
                        Icon(Icons.Default.ChevronRight, null)
                    }
                }
            }
        }
    }
}

@Composable
fun AppPolicyScreen(packageName: String, store: PolicyStore, controller: DevicePolicyController, onBack: () -> Unit) {
    val app = remember { controller.installedApps().firstOrNull { it.packageName == packageName } }
    var p by remember { mutableStateOf(store.get(packageName)) }
    var status by remember { mutableStateOf("Not applied") }
    val protected = controller.protectedPackages().contains(packageName)
    Column {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) { IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, null) }; Column { Text("App Policy", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold); Text(app?.label ?: packageName) } }
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text(packageName, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            item { PolicyToggle("Keep Installed", "Prevent uninstall where Device Owner permits", p.keepInstalled, !protected) { p = p.copy(keepInstalled = it) } }
            item { PolicyToggle("Allow Usage", "Allow this app to be opened and used", p.allowUsage, !protected) { p = p.copy(allowUsage = it, suspended = if (it) false else p.suspended) } }
            item { PolicyToggle("Suspend App", "Temporarily disable app execution", p.suspended, !protected) { p = p.copy(suspended = it, allowUsage = if (it) false else p.allowUsage) } }
            item { PolicyToggle("Show Notifications", "Show this app's notifications locally", p.showNotifications, true) { p = p.copy(showNotifications = it) } }
            item { PolicyToggle("Forward to PhoneHub", "Forward notifications to configured receiver", p.forwardNotifications, true) { p = p.copy(forwardNotifications = it) } }
            item { PolicyToggle("Protect from Changes", "Keep policy protected from accidental changes", p.protectFromChanges, !protected) { p = p.copy(protectFromChanges = it) } }
            item { PolicyToggle("Auto Apply on Sync", "Apply this policy during sync", p.autoApplyOnSync, true) { p = p.copy(autoApplyOnSync = it) } }
            if (protected) item { AssistChip(onClick = {}, label = { Text("Protected critical package") }, leadingIcon = { Icon(Icons.Default.Shield, null) }) }
            item { Text("Enforcement status: $status") }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = { store.save(p); status = controller.apply(p).fold({ "Applied successfully" }, { it.message ?: "Failed" }) }, modifier = Modifier.weight(1f)) { Text("Save Policy") }
                    OutlinedButton(onClick = { p = AppPolicy(packageName); status = "Reset locally" }, modifier = Modifier.weight(1f)) { Text("Reset") }
                }
            }
        }
    }
}

@Composable
fun PolicyToggle(title: String, subtitle: String, checked: Boolean, enabled: Boolean, onChecked: (Boolean) -> Unit) {
    Card(Modifier.fillMaxWidth()) { Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) { Column(Modifier.weight(1f)) { Text(title, fontWeight = FontWeight.SemiBold); Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }; Switch(checked, onChecked, enabled = enabled) } }
}

@Composable
fun PoliciesScreen(store: PolicyStore, controller: DevicePolicyController) {
    var auto by remember { mutableStateOf(store.autoApply()) }
    var boot by remember { mutableStateOf(store.applyAtBoot()) }
    var result by remember { mutableStateOf("") }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Header("Policies", "Manage global policy behavior") }
        item { PolicyToggle("Auto Apply on Sync", "Apply saved policies when you sync", auto, true) { auto = it; store.setAutoApply(it) } }
        item { PolicyToggle("Apply at Boot", "Reapply policy after device restart", boot, true) { boot = it; store.setApplyAtBoot(it) } }
        item { Button(onClick = {
            var ok = 0; var fail = 0
            store.allPackages().forEach { pkg -> if (store.get(pkg).autoApplyOnSync) controller.apply(store.get(pkg)).fold({ ok++ }, { fail++ }) }
            result = "Applied $ok • Failed $fail"
        }, enabled = controller.isDeviceOwner(), modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Sync, null); Spacer(Modifier.width(8.dp)); Text("Sync Now") } }
        if (result.isNotBlank()) item { Text(result) }
    }
}

@Composable
fun NotificationsScreen(store: PolicyStore) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var global by remember { mutableStateOf(store.globalForwarding()) }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Header("Notifications", "Control local and forwarded notifications") }
        item { PolicyToggle("Forward Notifications", "Master switch for PhoneHub forwarding", global, true) { global = it; store.setGlobalForwarding(it) } }
        item { Button(onClick = { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }, modifier = Modifier.fillMaxWidth()) { Text("Open Notification Access") } }
        item { Text("Per-app notification visibility and forwarding are configured from Apps → App Policy.") }
    }
}

@Composable
fun SettingsScreen(store: PolicyStore, controller: DevicePolicyController) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var url by remember { mutableStateOf(store.receiverUrl()) }
    var token by remember { mutableStateOf(store.pairingToken()) }
    var saved by remember { mutableStateOf(false) }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Header("Settings", "Connection, protection and device status") }
        item { Text("Connection", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item { OutlinedTextField(url, { url = it; saved = false }, label = { Text("Receiver URL") }, modifier = Modifier.fillMaxWidth()) }
        item { OutlinedTextField(token, { token = it; saved = false }, label = { Text("Pairing token") }, modifier = Modifier.fillMaxWidth()) }
        item { Button(onClick = { store.saveConnection(url, token); saved = true }, modifier = Modifier.fillMaxWidth()) { Text(if (saved) "Saved" else "Save Connection") } }
        item { Text("Protection", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item { StatusCard("PhoneHub protection", "Protected", "PhoneHub and critical Android packages cannot be suspended from the UI", { Icon(Icons.Default.Shield, null) }) }
        item { Text("Logs & Status", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item { StatusCard("Device Owner", if (controller.isDeviceOwner()) "Active" else "Inactive", "Device-owner enforcement is required for suspend/uninstall-block controls", { Icon(Icons.Default.AdminPanelSettings, null) }) }
        item { Button(onClick = { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }, modifier = Modifier.fillMaxWidth()) { Text("Notification Access") } }
        item { Text("New Phone Setup", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        item { Text("Provision PhoneHub as Device Owner during initial device setup, then pair the receiver and sync policies.") }
    }
}
