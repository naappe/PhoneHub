package com.phonehub.notifier

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

class DevicePolicyController(private val context: Context) {

    private val dpm =
        context.getSystemService(DevicePolicyManager::class.java)

    private val admin =
        ComponentName(context, PhoneHubDeviceAdminReceiver::class.java)

    fun isDeviceOwner(): Boolean =
        dpm.isDeviceOwnerApp(context.packageName)

    /*
     * Packages PhoneHub must never suspend, disable or
     * uninstall-protect incorrectly through normal policy operations.
     */
    fun protectedPackages(): Set<String> = setOf(
        context.packageName,
        "com.android.settings",
        "com.android.systemui",
        "com.google.android.packageinstaller",
        "com.android.packageinstaller",
        "com.android.permissioncontroller"
    )

    fun isProtected(packageName: String): Boolean =
        packageName in protectedPackages()

    fun apply(policy: AppPolicy): Result<Unit> = runCatching {

        check(isDeviceOwner()) {
            "PhoneHub is not Device Owner"
        }

        /*
         * PhoneHub itself is never modified through the generic
         * application-policy path.
         */
        if (policy.packageName == context.packageName) {
            return@runCatching
        }

        /*
         * Critical Android packages may be discovered/displayed,
         * but PhoneHub will refuse policies capable of disabling them.
         */
        if (isProtected(policy.packageName)) {

            check(policy.allowUsage) {
                "Protected package cannot have usage blocked: ${policy.packageName}"
            }

            check(!policy.suspended) {
                "Protected package cannot be suspended: ${policy.packageName}"
            }

            check(policy.showNotifications) {
                "Protected package notifications cannot be disabled: ${policy.packageName}"
            }

            return@runCatching
        }

        // Prevent uninstall when Keep Installed or Protect is enabled.
        dpm.setUninstallBlocked(
            admin,
            policy.packageName,
            policy.keepInstalled || policy.protectFromChanges
        )

        // Suspend application when explicitly suspended or usage disabled.
        dpm.setPackagesSuspended(
            admin,
            arrayOf(policy.packageName),
            policy.suspended || !policy.allowUsage
        )

        // Android 13+
        if (Build.VERSION.SDK_INT >= 33) {

            val grantState =
                if (policy.showNotifications) {
                    DevicePolicyManager.PERMISSION_GRANT_STATE_GRANTED
                } else {
                    DevicePolicyManager.PERMISSION_GRANT_STATE_DENIED
                }

            dpm.setPermissionGrantState(
                admin,
                policy.packageName,
                android.Manifest.permission.POST_NOTIFICATIONS,
                grantState
            )
        }
    }

    fun installedApps(): List<InstalledApp> {

        val pm = context.packageManager

        return pm.getInstalledApplications(
            PackageManager.ApplicationInfoFlags.of(0)
        )
            .map {
                InstalledApp(
                    label = pm.getApplicationLabel(it).toString(),
                    packageName = it.packageName,
                    isSystem =
                        (it.flags and
                            android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0
                )
            }
            .sortedBy {
                it.label.lowercase()
            }
    }
}
