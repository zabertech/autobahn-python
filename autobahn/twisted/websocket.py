###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) Tavendo GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

from __future__ import absolute_import

from base64 import b64encode, b64decode

from zope.interface import implementer

import twisted.internet.protocol
from twisted.internet.defer import maybeDeferred
from twisted.internet.interfaces import ITransport
from twisted.internet.error import ConnectionDone, ConnectionAborted, \
    ConnectionLost

from autobahn.wamp import websocket
from autobahn.websocket.types import ConnectionRequest, ConnectionResponse, \
    ConnectionDeny
from autobahn.websocket import protocol
from autobahn.twisted.util import peer2str

from txaio import make_logger

from autobahn.websocket.compress import PerMessageDeflateOffer, \
    PerMessageDeflateOfferAccept, \
    PerMessageDeflateResponse, \
    PerMessageDeflateResponseAccept


__all__ = (
    'WebSocketAdapterProtocol',
    'WebSocketServerProtocol',
    'WebSocketClientProtocol',
    'WebSocketAdapterFactory',
    'WebSocketServerFactory',
    'WebSocketClientFactory',

    'WrappingWebSocketAdapter',
    'WrappingWebSocketServerProtocol',
    'WrappingWebSocketClientProtocol',
    'WrappingWebSocketServerFactory',
    'WrappingWebSocketClientFactory',

    'listenWS',
    'connectWS',

    'WampWebSocketServerProtocol',
    'WampWebSocketServerFactory',
    'WampWebSocketClientProtocol',
    'WampWebSocketClientFactory',
)


class WebSocketAdapterProtocol(twisted.internet.protocol.Protocol):
    """
    Adapter class for Twisted WebSocket client and server protocols.
    """
    peer = '<never connected>'

    def connectionMade(self):
        # the peer we are connected to
        try:
            peer = self.transport.getPeer()
        except AttributeError:
            # ProcessProtocols lack getPeer()
            self.peer = "process {}".format(self.transport.pid)
        else:
            self.peer = peer2str(peer)

        self._connectionMade()

        # Set "Nagle"
        try:
            self.transport.setTcpNoDelay(self.tcpNoDelay)
        except:  # don't touch this! does not work: AttributeError, OSError
            # eg Unix Domain sockets throw Errno 22 on this
            pass

    def connectionLost(self, reason):
        if isinstance(reason.value, ConnectionDone):
            self.factory.log.debug("Connection to/from {peer} was closed cleanly",
                                   peer=self.peer)

        elif isinstance(reason.value, ConnectionAborted):
            self.factory.log.debug("Connection to/from {peer} was aborted locally",
                                   peer=self.peer)

        elif isinstance(reason.value, ConnectionLost):
            # The following is ridiculous, but the treatment of reason.value.args
            # across py2/3 and tx and over various corner cases is deeply fucked up.
            if hasattr(reason.value, 'message'):
                message = reason.value.message
            elif hasattr(reason.value, 'args') and type(reason.value.args) == tuple and len(reason.value.args) > 0:
                message = reason.value.args[0]
            else:
                message = None

            if message:
                self.factory.log.debug("Connection to/from {peer} was lost in a non-clean fashion: {message}",
                                       peer=self.peer, message=message)
            else:
                self.factory.log.debug("Connection to/from {peer} was lost in a non-clean fashion",
                                       peer=self.peer)

        # at least: FileDescriptorOverrun, ConnectionFdescWentAway - but maybe others as well?
        else:
            self.factory.log.info("Connection to/from {peer} lost ({error_type}): {error})",
                                  peer=self.peer, error_type=type(reason.value), error=reason.value)

        self._connectionLost(reason)

    def dataReceived(self, data):
        self._dataReceived(data)

    def _closeConnection(self, abort=False):
        if abort and hasattr(self.transport, 'abortConnection'):
            self.transport.abortConnection()
        else:
            # e.g. ProcessProtocol lacks abortConnection()
            self.transport.loseConnection()

    def _onOpen(self):
        self.onOpen()

    def _onMessageBegin(self, isBinary):
        self.onMessageBegin(isBinary)

    def _onMessageFrameBegin(self, length):
        self.onMessageFrameBegin(length)

    def _onMessageFrameData(self, payload):
        self.onMessageFrameData(payload)

    def _onMessageFrameEnd(self):
        self.onMessageFrameEnd()

    def _onMessageFrame(self, payload):
        self.onMessageFrame(payload)

    def _onMessageEnd(self):
        self.onMessageEnd()

    def _onMessage(self, payload, isBinary):
        self.onMessage(payload, isBinary)

    def _onPing(self, payload):
        self.onPing(payload)

    def _onPong(self, payload):
        self.onPong(payload)

    def _onClose(self, wasClean, code, reason):
        self.onClose(wasClean, code, reason)

    def registerProducer(self, producer, streaming):
        """
        Register a Twisted producer with this protocol.

        :param producer: A Twisted push or pull producer.
        :type producer: object
        :param streaming: Producer type.
        :type streaming: bool
        """
        self.transport.registerProducer(producer, streaming)


class WebSocketServerProtocol(WebSocketAdapterProtocol, protocol.WebSocketServerProtocol):
    """
    Base class for Twisted-based WebSocket server protocols.
    """

    def _onConnect(self, request):
        # onConnect() will return the selected subprotocol or None
        # or a pair (protocol, headers) or raise an HttpException
        res = maybeDeferred(self.onConnect, request)

        res.addCallback(self.succeedHandshake)

        def forwardError(failure):
            if failure.check(ConnectionDeny):
                return self.failHandshake(failure.value.reason, failure.value.code)
            else:
                if self.debug:
                    self.factory._log("Unexpected exception in onConnect ['%s']" % failure.value)
                return self.failHandshake("Internal server error: {}".format(failure.value), ConnectionDeny.INTERNAL_SERVER_ERROR)

        res.addErrback(forwardError)


class WebSocketClientProtocol(WebSocketAdapterProtocol, protocol.WebSocketClientProtocol):
    """
    Base class for Twisted-based WebSocket client protocols.
    """

    def _onConnect(self, response):
        self.onConnect(response)


class WebSocketAdapterFactory(object):
    """
    Adapter class for Twisted-based WebSocket client and server factories.
    """
    log = make_logger()


class WebSocketServerFactory(WebSocketAdapterFactory, protocol.WebSocketServerFactory, twisted.internet.protocol.ServerFactory):
    """
    Base class for Twisted-based WebSocket server factories.
    """

    def __init__(self, *args, **kwargs):
        """
        In addition to all arguments to the constructor of
        :class:`autobahn.websocket.protocol.WebSocketServerFactory`,
        you can supply a `reactor` keyword argument to specify the
        Twisted reactor to be used.
        """
        # lazy import to avoid reactor install upon module import
        reactor = kwargs.pop('reactor', None)
        if reactor is None:
            from twisted.internet import reactor
        self.reactor = reactor

        protocol.WebSocketServerFactory.__init__(self, *args, **kwargs)


class WebSocketClientFactory(WebSocketAdapterFactory, protocol.WebSocketClientFactory, twisted.internet.protocol.ClientFactory):
    """
    Base class for Twisted-based WebSocket client factories.
    """

    def __init__(self, *args, **kwargs):
        """
        In addition to all arguments to the constructor of
        :class:`autobahn.websocket.protocol.WebSocketClientFactory`,
        you can supply a `reactor` keyword argument to specify the
        Twisted reactor to be used.
        """
        # lazy import to avoid reactor install upon module import
        reactor = kwargs.pop('reactor', None)
        if reactor is None:
            from twisted.internet import reactor
        self.reactor = reactor

        protocol.WebSocketClientFactory.__init__(self, *args, **kwargs)


@implementer(ITransport)
class WrappingWebSocketAdapter(object):
    """
    An adapter for stream-based transport over WebSocket.

    This follows `websockify <https://github.com/kanaka/websockify>`_
    and should be compatible with that.

    It uses WebSocket subprotocol negotiation and supports the
    following WebSocket subprotocols:

      - ``binary`` (or a compatible subprotocol)
      - ``base64``

    Octets are either transmitted as the payload of WebSocket binary
    messages when using the ``binary`` subprotocol (or an alternative
    binary compatible subprotocol), or encoded with Base64 and then
    transmitted as the payload of WebSocket text messages when using
    the ``base64`` subprotocol.
    """

    def onConnect(self, requestOrResponse):

        # Negotiate either the 'binary' or the 'base64' WebSocket subprotocol
        if isinstance(requestOrResponse, ConnectionRequest):
            request = requestOrResponse
            for p in request.protocols:
                if p in self.factory._subprotocols:
                    self._binaryMode = (p != 'base64')
                    return p
            raise ConnectionDeny(ConnectionDeny.NOT_ACCEPTABLE, "this server only speaks %s WebSocket subprotocols" % self.factory._subprotocols)
        elif isinstance(requestOrResponse, ConnectionResponse):
            response = requestOrResponse
            if response.protocol not in self.factory._subprotocols:
                self.failConnection(protocol.WebSocketProtocol.CLOSE_STATUS_CODE_PROTOCOL_ERROR, "this client only speaks %s WebSocket subprotocols" % self.factory._subprotocols)
            self._binaryMode = (response.protocol != 'base64')
        else:
            # should not arrive here
            raise Exception("logic error")

    def onOpen(self):
        self._proto.connectionMade()

    def onMessage(self, payload, isBinary):
        if isBinary != self._binaryMode:
            self.failConnection(protocol.WebSocketProtocol.CLOSE_STATUS_CODE_UNSUPPORTED_DATA, "message payload type does not match the negotiated subprotocol")
        else:
            if not isBinary:
                try:
                    payload = b64decode(payload)
                except Exception as e:
                    self.failConnection(protocol.WebSocketProtocol.CLOSE_STATUS_CODE_INVALID_PAYLOAD, "message payload base64 decoding error: {0}".format(e))
            # print("forwarding payload: {0}".format(binascii.hexlify(payload)))
            self._proto.dataReceived(payload)

    # noinspection PyUnusedLocal
    def onClose(self, wasClean, code, reason):
        self._proto.connectionLost(None)

    def write(self, data):
        # print("sending payload: {0}".format(binascii.hexlify(data)))
        # part of ITransport
        assert(type(data) == bytes)
        if self._binaryMode:
            self.sendMessage(data, isBinary=True)
        else:
            data = b64encode(data)
            self.sendMessage(data, isBinary=False)

    def writeSequence(self, data):
        # part of ITransport
        for d in data:
            self.write(d)

    def loseConnection(self):
        # part of ITransport
        self.sendClose()

    def getPeer(self):
        # part of ITransport
        return self.transport.getPeer()

    def getHost(self):
        # part of ITransport
        return self.transport.getHost()


class WrappingWebSocketServerProtocol(WrappingWebSocketAdapter, WebSocketServerProtocol):
    """
    Server protocol for stream-based transport over WebSocket.
    """


class WrappingWebSocketClientProtocol(WrappingWebSocketAdapter, WebSocketClientProtocol):
    """
    Client protocol for stream-based transport over WebSocket.
    """


class WrappingWebSocketServerFactory(WebSocketServerFactory):
    """
    Wrapping server factory for stream-based transport over WebSocket.
    """

    def __init__(self,
                 factory,
                 url,
                 reactor=None,
                 enableCompression=True,
                 autoFragmentSize=0,
                 subprotocol=None,
                 debug=False):
        """

        :param factory: Stream-based factory to be wrapped.
        :type factory: A subclass of ``twisted.internet.protocol.Factory``
        :param url: WebSocket URL of the server this server factory will work for.
        :type url: unicode
        """
        self._factory = factory
        self._subprotocols = ['binary', 'base64']
        if subprotocol:
            self._subprotocols.append(subprotocol)

        WebSocketServerFactory.__init__(self,
                                        url=url,
                                        reactor=reactor,
                                        protocols=self._subprotocols,
                                        debug=debug)

        # automatically fragment outgoing traffic into WebSocket frames
        # of this size
        self.setProtocolOptions(autoFragmentSize=autoFragmentSize)

        # play nice and perform WS closing handshake
        self.setProtocolOptions(failByDrop=False)

        if enableCompression:
            # Enable WebSocket extension "permessage-deflate".

            # Function to accept offers from the client ..
            def accept(offers):
                for offer in offers:
                    if isinstance(offer, PerMessageDeflateOffer):
                        return PerMessageDeflateOfferAccept(offer)

            self.setProtocolOptions(perMessageCompressionAccept=accept)

    def buildProtocol(self, addr):
        proto = WrappingWebSocketServerProtocol()
        proto.factory = self
        proto._proto = self._factory.buildProtocol(addr)
        proto._proto.transport = proto
        return proto

    def startFactory(self):
        self._factory.startFactory()
        WebSocketServerFactory.startFactory(self)

    def stopFactory(self):
        self._factory.stopFactory()
        WebSocketServerFactory.stopFactory(self)


class WrappingWebSocketClientFactory(WebSocketClientFactory):
    """
    Wrapping client factory for stream-based transport over WebSocket.
    """

    def __init__(self,
                 factory,
                 url,
                 reactor=None,
                 enableCompression=True,
                 autoFragmentSize=0,
                 subprotocol=None,
                 debug=False):
        """

        :param factory: Stream-based factory to be wrapped.
        :type factory: A subclass of ``twisted.internet.protocol.Factory``
        :param url: WebSocket URL of the server this client factory will connect to.
        :type url: unicode
        """
        self._factory = factory
        self._subprotocols = ['binary', 'base64']
        if subprotocol:
            self._subprotocols.append(subprotocol)

        WebSocketClientFactory.__init__(self,
                                        url=url,
                                        reactor=reactor,
                                        protocols=self._subprotocols,
                                        debug=debug)

        # automatically fragment outgoing traffic into WebSocket frames
        # of this size
        self.setProtocolOptions(autoFragmentSize=autoFragmentSize)

        # play nice and perform WS closing handshake
        self.setProtocolOptions(failByDrop=False)

        if enableCompression:
            # Enable WebSocket extension "permessage-deflate".

            # The extensions offered to the server ..
            offers = [PerMessageDeflateOffer()]
            self.setProtocolOptions(perMessageCompressionOffers=offers)

            # Function to accept responses from the server ..
            def accept(response):
                if isinstance(response, PerMessageDeflateResponse):
                    return PerMessageDeflateResponseAccept(response)

            self.setProtocolOptions(perMessageCompressionAccept=accept)

    def buildProtocol(self, addr):
        proto = WrappingWebSocketClientProtocol()
        proto.factory = self
        proto._proto = self._factory.buildProtocol(addr)
        proto._proto.transport = proto
        return proto


def connectWS(factory, contextFactory=None, timeout=30, bindAddress=None):
    """
    Establish WebSocket connection to a server. The connection parameters like target
    host, port, resource and others are provided via the factory.

    :param factory: The WebSocket protocol factory to be used for creating client protocol instances.
    :type factory: An :class:`autobahn.websocket.WebSocketClientFactory` instance.
    :param contextFactory: SSL context factory, required for secure WebSocket connections ("wss").
    :type contextFactory: A `twisted.internet.ssl.ClientContextFactory <http://twistedmatrix.com/documents/current/api/twisted.internet.ssl.ClientContextFactory.html>`_ instance.
    :param timeout: Number of seconds to wait before assuming the connection has failed.
    :type timeout: int
    :param bindAddress: A (host, port) tuple of local address to bind to, or None.
    :type bindAddress: tuple

    :returns: The connector.
    :rtype: An object which implements `twisted.interface.IConnector <http://twistedmatrix.com/documents/current/api/twisted.internet.interfaces.IConnector.html>`_.
    """
    # lazy import to avoid reactor install upon module import
    if hasattr(factory, 'reactor'):
        reactor = factory.reactor
    else:
        from twisted.internet import reactor

    if factory.proxy is not None:
        if factory.isSecure:
            raise Exception("WSS over explicit proxies not implemented")
        else:
            conn = reactor.connectTCP(factory.proxy['host'], factory.proxy['port'], factory, timeout, bindAddress)
    else:
        if factory.isSecure:
            if contextFactory is None:
                # create default client SSL context factory when none given
                from twisted.internet import ssl
                contextFactory = ssl.ClientContextFactory()
            conn = reactor.connectSSL(factory.host, factory.port, factory, contextFactory, timeout, bindAddress)
        else:
            conn = reactor.connectTCP(factory.host, factory.port, factory, timeout, bindAddress)
    return conn


def listenWS(factory, contextFactory=None, backlog=50, interface=''):
    """
    Listen for incoming WebSocket connections from clients. The connection parameters like
    listening port and others are provided via the factory.

    :param factory: The WebSocket protocol factory to be used for creating server protocol instances.
    :type factory: An :class:`autobahn.websocket.WebSocketServerFactory` instance.
    :param contextFactory: SSL context factory, required for secure WebSocket connections ("wss").
    :type contextFactory: A twisted.internet.ssl.ContextFactory.
    :param backlog: Size of the listen queue.
    :type backlog: int
    :param interface: The interface (derived from hostname given) to bind to, defaults to '' (all).
    :type interface: str

    :returns: The listening port.
    :rtype: An object that implements `twisted.interface.IListeningPort <http://twistedmatrix.com/documents/current/api/twisted.internet.interfaces.IListeningPort.html>`_.
    """
    # lazy import to avoid reactor install upon module import
    if hasattr(factory, 'reactor'):
        reactor = factory.reactor
    else:
        from twisted.internet import reactor

    if factory.isSecure:
        if contextFactory is None:
            raise Exception("Secure WebSocket listen requested, but no SSL context factory given")
        listener = reactor.listenSSL(factory.port, factory, contextFactory, backlog, interface)
    else:
        listener = reactor.listenTCP(factory.port, factory, backlog, interface)
    return listener


class WampWebSocketServerProtocol(websocket.WampWebSocketServerProtocol, WebSocketServerProtocol):
    """
    Base class for Twisted-based WAMP-over-WebSocket server protocols.
    """


class WampWebSocketServerFactory(websocket.WampWebSocketServerFactory, WebSocketServerFactory):
    """
    Base class for Twisted-based WAMP-over-WebSocket server factories.
    """

    protocol = WampWebSocketServerProtocol

    def __init__(self, factory, *args, **kwargs):

        serializers = kwargs.pop('serializers', None)
        debug_wamp = kwargs.pop('debug_wamp', False)

        websocket.WampWebSocketServerFactory.__init__(self, factory, serializers, debug_wamp=debug_wamp)

        kwargs['protocols'] = self._protocols

        # noinspection PyCallByClass
        WebSocketServerFactory.__init__(self, *args, **kwargs)


class WampWebSocketClientProtocol(websocket.WampWebSocketClientProtocol, WebSocketClientProtocol):
    """
    Base class for Twisted-based WAMP-over-WebSocket client protocols.
    """


class WampWebSocketClientFactory(websocket.WampWebSocketClientFactory, WebSocketClientFactory):
    """
    Base class for Twisted-based WAMP-over-WebSocket client factories.
    """

    protocol = WampWebSocketClientProtocol

    def __init__(self, factory, *args, **kwargs):

        serializers = kwargs.pop('serializers', None)
        debug_wamp = kwargs.pop('debug_wamp', False)

        websocket.WampWebSocketClientFactory.__init__(self, factory, serializers, debug_wamp=debug_wamp)

        kwargs['protocols'] = self._protocols

        WebSocketClientFactory.__init__(self, *args, **kwargs)
