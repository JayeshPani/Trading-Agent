import { getApiBase, LiveStatus } from "../api/client";

export function connectLiveStatus(token: string, onMessage: (status: LiveStatus) => void): WebSocket {
  const wsBase = getApiBase().replace(/^http/, "ws");
  const socket = new WebSocket(`${wsBase}/ws/live-status?token=${encodeURIComponent(token)}`);
  socket.onmessage = (event) => {
    onMessage(JSON.parse(event.data) as LiveStatus);
  };
  return socket;
}
