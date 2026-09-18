# PhoneHub VPN

PhoneHub VPN is a very small PC-side WireGuard wrapper for PhoneHub Link.

It does not invent new cryptography. It uses WireGuard for the encrypted tunnel and keeps PhoneHub-specific setup simple.

## Addresses

- PC tunnel address: `10.77.0.1/24`
- Phone tunnel address: `10.77.0.2/32`
- Default UDP listen port: `51820`

## First setup

Install WireGuard for Windows, then run:

```powershell
cd C:\PhoneHub
.\START_PHONEHUB_VPN.bat setup
```

The script creates a PC key pair and prints the PC public key.

Enter that public key in the PhoneHub Link Android app.

The Android app generates a phone public key. Copy that phone public key back to the PC and run:

```powershell
.\START_PHONEHUB_VPN.bat setup -PhonePublicKey "PHONE_PUBLIC_KEY_HERE"
.\START_PHONEHUB_VPN.bat start
```

For the Android endpoint, use a reachable PC address followed by `:51820`.

On the same LAN that can be the PC LAN IP. Across different networks, the PC must have a reachable public endpoint/port-forward or a relay/server.

## Commands

```powershell
.\START_PHONEHUB_VPN.bat status
.\START_PHONEHUB_VPN.bat setup
.\START_PHONEHUB_VPN.bat start
.\START_PHONEHUB_VPN.bat stop
.\START_PHONEHUB_VPN.bat show
```

Private keys are stored only under `C:\PhoneHub\runtime\vpn`, which is already ignored by Git.
