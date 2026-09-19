import unittest
from phonehub.services.discovery_service import DiscoveryService

class Result:
    ok=True
    stdout='{"Peer":{"a":{"Online":true,"HostName":"phone","TailscaleIPs":["100.99.209.74"]},"b":{"Online":false,"HostName":"old","TailscaleIPs":["100.70.1.2"]}}}'
class Runner:
    def run(self,args,timeout=8): return Result()

class DiscoveryTests(unittest.TestCase):
    def test_only_online_tailscale_peers(self):
        peers=DiscoveryService(Runner()).peers()
        self.assertEqual([(p.ip,p.name) for p in peers],[("100.99.209.74","phone")])
if __name__=="__main__": unittest.main()
