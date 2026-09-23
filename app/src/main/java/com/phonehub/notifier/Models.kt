package com.phonehub.notifier

data class AppPolicy(
    val packageName: String,
    val keepInstalled: Boolean = true,
    val allowUsage: Boolean = true,
    val suspended: Boolean = false,
    val showNotifications: Boolean = true,
    val forwardNotifications: Boolean = false,
    val protectFromChanges: Boolean = false,
    val autoApplyOnSync: Boolean = true,
)

data class InstalledApp(
    val label: String,
    val packageName: String,
    val isSystem: Boolean,
)
