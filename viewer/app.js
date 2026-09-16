import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const SUPABASE_URL = 'https://tmupbruwmwlrmewhoodn.supabase.co';
const SUPABASE_KEY = 'sb_publishable_LAn1liS2zqMqlB33IQJxIw_NbgWKix1';
const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

const roomInput = document.querySelector('#room');
const connectButton = document.querySelector('#connect');
const statusEl = document.querySelector('#status');
const screen = document.querySelector('#screen');

let channel = null;
let pc = null;

function setStatus(text) {
  statusEl.textContent = text;
}

async function sendSignal(payload) {
  if (!channel) return;
  await channel.send({ type: 'broadcast', event: 'signal', payload });
}

function createPeer() {
  const peer = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
  });

  peer.onicecandidate = ({ candidate }) => {
    if (!candidate) return;
    sendSignal({
      type: 'ice',
      candidate: candidate.candidate,
      sdpMid: candidate.sdpMid,
      sdpMLineIndex: candidate.sdpMLineIndex
    });
  };

  peer.ontrack = (event) => {
    screen.srcObject = event.streams[0] ?? new MediaStream([event.track]);
    setStatus('Connected — live screen active');
  };

  peer.onconnectionstatechange = () => {
    if (peer.connectionState === 'failed') {
      setStatus('Connection failed. These networks may require TURN.');
    } else if (peer.connectionState === 'disconnected') {
      setStatus('Phone disconnected');
    } else if (peer.connectionState === 'connecting') {
      setStatus('Connecting WebRTC…');
    }
  };

  return peer;
}

async function handleSignal(message) {
  if (!pc) return;

  if (message.type === 'offer' && message.sdp) {
    await pc.setRemoteDescription({ type: 'offer', sdp: message.sdp });
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await sendSignal({ type: 'answer', sdp: answer.sdp });
    setStatus('Answer sent. Establishing direct connection…');
  }

  if (message.type === 'ice' && message.candidate) {
    try {
      await pc.addIceCandidate({
        candidate: message.candidate,
        sdpMid: message.sdpMid ?? null,
        sdpMLineIndex: message.sdpMLineIndex ?? 0
      });
    } catch (error) {
      console.warn('ICE candidate rejected', error);
    }
  }

  if (message.type === 'stop') {
    setStatus('Phone stopped sharing');
    screen.srcObject = null;
    pc.close();
    pc = null;
  }
}

async function connect() {
  const room = roomInput.value.trim();
  if (!/^\d{6}$/.test(room)) {
    setStatus('Enter the 6-digit room code shown on the phone.');
    return;
  }

  connectButton.disabled = true;
  setStatus('Joining room…');

  if (channel) {
    await supabase.removeChannel(channel);
    channel = null;
  }
  if (pc) pc.close();
  pc = createPeer();

  channel = supabase
    .channel(`phonehub-link:${room}`)
    .on('broadcast', { event: 'signal' }, ({ payload }) => handleSignal(payload))
    .subscribe(async (subscriptionStatus) => {
      if (subscriptionStatus === 'SUBSCRIBED') {
        setStatus('Room joined. Waiting for phone offer…');
        await sendSignal({ type: 'viewer-ready' });
      }
      if (subscriptionStatus === 'CHANNEL_ERROR' || subscriptionStatus === 'TIMED_OUT') {
        setStatus('Could not join signaling room.');
      }
    });

  setTimeout(() => {
    if (pc && ['new', 'connecting'].includes(pc.connectionState)) {
      setStatus('Still connecting. If this fails on different networks, TURN may be required.');
    }
  }, 20000);

  connectButton.disabled = false;
}

connectButton.addEventListener('click', connect);
roomInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') connect();
});
