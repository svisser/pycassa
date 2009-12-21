from exceptions import Exception
import threading
from Queue import Queue

from thrift import Thrift
from thrift.transport import TTransport
from thrift.transport import TSocket
from thrift.protocol import TBinaryProtocol
from cassandra import Cassandra

__all__ = ['connect', 'connect_thread_local']

DEFAULT_SERVER = 'localhost:9160'

class NoServerAvailable(Exception):
    pass

def create_client_transport(server):
    host, port = server.split(":")
    socket = TSocket.TSocket(host, int(port))
    transport = TTransport.TBufferedTransport(socket)
    protocol = TBinaryProtocol.TBinaryProtocolAccelerated(transport)
    client = Cassandra.Client(protocol)
    transport.open()

    return client, transport

def connect(servers=None):
    """
    Constructs a single Cassandra connection. Initially connects to the first
    server on the list.
    
    If the connection fails, it will attempt to connect to each server on the
    list in turn until one succeeds. If it is unable to find an active server,
    it will throw a NoServerAvailable exception.

    Parameters
    ----------
    servers : [server]
              List of Cassandra servers with format: "hostname:port"

              Default: ['localhost:9160']

    Returns
    -------
    Cassandra client
    """

    if servers is None:
        servers = [DEFAULT_SERVER]
    return SingleConnection(servers)

def connect_thread_local(servers=None, round_robin=True):
    """
    Constructs a Cassandra connection for each thread. By default, it attempts
    to connect in a round_robin (load-balancing) fashion. Turn it off by
    setting round_robin=False

    If the connection fails, it will attempt to connect to each server on the
    list in turn until one succeeds. If it is unable to find an active server,
    it will throw a NoServerAvailable exception.

    Parameters
    ----------
    servers : [server]
              List of Cassandra servers with format: "hostname:port"

              Default: ['localhost:9160']

    round_robin : bool
              Balance the connections. Set to False to connect to each server
              in turn.

    Returns
    -------
    Cassandra client
    """

    if servers is None:
        servers = [DEFAULT_SERVER]
    return ThreadLocalConnection(servers, round_robin)

class SingleConnection(object):
    def __init__(self, servers):
        self._servers = servers
        self._client = None

    def __getattr__(self, attr):
        def client_call(*args, **kwargs):
            if self._client is None:
                self._find_server()
            try:
                return getattr(self._client, attr)(*args, **kwargs)
            except Thrift.TException as exc:
                # Connection error, try to connect to all the servers
                self._transport.close()
                self._client = None
                self._find_server()

        setattr(self, attr, client_call)
        return getattr(self, attr)

    def _find_server(self):
        for server in self._servers:
            try:
                self._client, self._transport = create_client_transport(server)
                return
            except Thrift.TException as exc:
                continue
        raise NoServerAvailable()

class ThreadLocalConnection(object):
    def __init__(self, servers, round_robin):
        self._servers = servers
        self._queue = Queue()
        for i in xrange(len(servers)):
            self._queue.put(i)
        self._local = threading.local()
        self._round_robin = round_robin

    def __getattr__(self, attr):
        def client_call(*args, **kwargs):
            if getattr(self.local, 'client', None) is None:
                self._find_server()

            try:
                return getattr(self._local.client, attr)(*args, **kwargs)
            except Thrift.TException as exc:
                # Connection error, try a new server next time
                self._local.transport.close()
                self._local.client = None
                raise exc

        setattr(self, attr, client_call)
        return getattr(self, attr)

    def _find_server(self):
        servers = self._servers
        if self._round_robin:
            i = self._queue.get()
            self._queue.put(i)
            servers = servers[i:]+servers[:i]

        for server in servers:
            try:
                self._local.client, self._local.transport = create_client_transport(server)
                return
            except Thrift.TException as exc:
                continue
        raise NoServerAvailable()
