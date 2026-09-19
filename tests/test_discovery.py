import unittest
from phonehub.core.command import CommandResult
from phonehub.services.discovery_service import DiscoveryService
class Runner:
    def __init__(self,text):self.text=text
    def run(self,args,timeout=8):return CommandResult(0,self.text,"")
class DiscoveryTests(unittest.TestCase):
    def test_online_tailscale_peers_only(self):
        text='{"Peer":{"a":{"Online":true,"HostName":"phone","TailscaleIPs":["100.99.209.74"]},"b":{"Online":false,"HostName":"old","TailscaleIPs":["100.70.1.2"]}}}'
        peers=DiscoveryService(Runner(text)).tailscale_peers()
        self.assertEqual([(p.ip,p.name) for p in peers],[("100.99.209.74","phone")])
if __name__=="__main__":unittest.main()
