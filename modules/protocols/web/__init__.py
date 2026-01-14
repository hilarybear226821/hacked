"""Web protocol handlers"""

from modules.protocols.web.http2_handler import HTTP2Handler
from modules.protocols.web.websocket_hijack import WebSocketHijack

__all__ = ['HTTP2Handler', 'WebSocketHijack']
