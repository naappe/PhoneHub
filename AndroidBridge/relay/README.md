# AndroidBridge Internet Relay

Authenticated WebSocket relay for AndroidBridge.

## Runtime

Python 3.11+

## Install

pip install -r requirements.txt

## Start

python relay_server.py

The server reads the listening port from:

PORT

Pairing credentials are supplied through the environment variable:

ANDROIDBRIDGE_PAIRINGS

Example structure only:

{"DEVICE_ID":"PAIRING_SECRET"}

Do NOT commit a real pairing secret.

## Transport

Production:

wss://

Local development:

ws://

The relay forwards authenticated AndroidBridge text and binary
messages between PHONE and PC clients belonging to the same Device ID.